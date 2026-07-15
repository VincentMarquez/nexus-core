"""Durable checkpointed task engine.

Checkpoints use atomic write-then-rename (Temporal / Durable Functions shape).
Each status/step transition also appends to an append-only JSONL event journal
(replay + audit; edict/MisterSmith-inspired, filesystem-only).

Also records swarm-style handoffs when the active agent changes, injects last-N
journal lines on resume (context engineering), and fail-closes on review veto
(edict-style).

Operator observability (P2):
- ``replay(task_id)`` — normalized timeline from the journal (open-multi-agent plan-replay).
- ``explain(task_id)`` — causal decision chain from events + step outputs (CEMA-style).
- ``why`` on step_complete — short judge rationale for post-hoc audit.

Ops / cost (P3):
- ``cost(task_id)`` — task-level token + score rollup from journal (mission-control shape).
- ``score`` / ``tokens`` / ``thresholds`` on step_complete — value-system + spend audit.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .agents import AgentPanel
from .cascade import CascadeIndex
from .config import Settings
from .judge import RubricJudge, decision_thresholds
from .memory import MemorySpine
from .persist import append_jsonl, atomic_write_json, event_row, read_jsonl
from .steps import StepPolicy, structural_ok
from .trust import TrustLog
from .usage import estimate_tokens

# Review step verdicts that hard-fail the pipeline (edict fail-closed audit).
REVIEW_VETO_VERDICTS = frozenset({"reject", "veto", "fail", "deny", "blocked"})


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    waiting_human = "waiting_human"
    completed = "completed"
    failed = "failed"


@dataclass
class Task:
    task_id: str
    objective: str
    success_criteria: list[str] = field(default_factory=list)
    namespace: str = "proj/demo"
    constraints: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.pending
    current_step: int = 0  # last completed step number
    outputs: dict[int, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        # json keys must be str
        d["outputs"] = {str(k): v for k, v in self.outputs.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        outs = {int(k): v for k, v in (d.get("outputs") or {}).items()}
        return cls(
            task_id=d["task_id"],
            objective=d.get("objective", ""),
            success_criteria=list(d.get("success_criteria") or []),
            namespace=d.get("namespace", "proj/demo"),
            constraints=list(d.get("constraints") or []),
            status=TaskStatus(d.get("status", "pending")),
            current_step=int(d.get("current_step") or 0),
            outputs=outs,
            meta=dict(d.get("meta") or {}),
        )


class DurableEngine:
    """
    Checkpoint after each step. Safe to kill and resume.

    Does not reimplement step business logic — calls AgentPanel + Judge.
    """

    def __init__(
        self,
        *,
        settings: Optional[Settings] = None,
        panel: Optional[AgentPanel] = None,
        memory: Optional[MemorySpine] = None,
        cascade: Optional[CascadeIndex] = None,
        policy: Optional[StepPolicy] = None,
        auto_approve: bool = True,
        journal: bool = True,
    ):
        self.settings = settings or Settings()
        self.settings.ensure_dirs()
        self.panel = panel or AgentPanel.demo()
        self.memory = memory or MemorySpine.demo()
        self.cascade = cascade or CascadeIndex.demo()
        self.policy = policy or StepPolicy.default()
        self.judge = RubricJudge(self.panel, prefer_cross_vendor=self.settings.prefer_cross_vendor_judge)
        self.trust = TrustLog(self.settings.state_dir / "trust.json")
        self.auto_approve = auto_approve
        self.journal = journal

    def _task_path(self, task_id: str) -> Path:
        return self.settings.state_dir / "tasks" / f"{task_id}.json"

    def _events_path(self, task_id: str) -> Path:
        return self.settings.state_dir / "tasks" / f"{task_id}.events.jsonl"

    def record_event(
        self,
        task_id: str,
        event: str,
        *,
        step: Optional[int] = None,
        agent: str = "",
        status: str = "",
        detail: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Append one audit event for *task_id* (no-op when journal disabled)."""
        if not self.journal:
            return
        append_jsonl(
            self._events_path(task_id),
            event_row(
                event,
                task_id=task_id,
                step=step,
                agent=agent,
                status=status,
                detail=detail,
                extra=extra,
            ),
        )

    def events(self, task_id: str, *, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Return the append-only event log for a task (replay / audit)."""
        rows = read_jsonl(self._events_path(task_id))
        if limit is not None and limit >= 0:
            # keep the most recent *limit* events for operator convenience
            rows = rows[-limit:] if limit else []
        return rows

    def journal_context(self, task_id: str, *, limit: int = 8) -> str:
        """Shallow last-N journal block for agent prompts (context engineering)."""
        if not self.journal or limit <= 0:
            return ""
        rows = self.events(task_id, limit=limit)
        if not rows:
            return ""
        lines = ["# RECENT TASK JOURNAL (read before acting)"]
        for r in rows:
            parts = [str(r.get("event", "?"))]
            if r.get("step") is not None:
                parts.append(f"step={r['step']}")
            if r.get("agent"):
                parts.append(f"agent={r['agent']}")
            if r.get("status"):
                parts.append(f"status={r['status']}")
            if r.get("detail"):
                parts.append(str(r["detail"])[:80])
            extra_bits = []
            for k in ("from_agent", "to_agent", "decision", "why"):
                if r.get(k):
                    val = str(r[k])[:60] if k == "why" else r[k]
                    extra_bits.append(f"{k}={val}")
            if extra_bits:
                parts.append(" ".join(extra_bits))
            lines.append("- " + " ".join(parts))
        return "\n".join(lines) + "\n"

    def save(self, task: Task) -> None:
        path = self._task_path(task.task_id)
        atomic_write_json(path, task.to_dict())

    def load(self, task_id: str) -> Task:
        path = self._task_path(task_id)
        if not path.exists():
            raise FileNotFoundError(path)
        return Task.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def run(self, task: Task, *, max_steps: Optional[int] = None) -> Task:
        if not self.settings.autonomy and task.meta.get("auto_created"):
            task.status = TaskStatus.failed
            task.meta["error"] = "autonomy disabled; refusing auto_created task"
            self.save(task)
            self.record_event(
                task.task_id, "failed",
                status=task.status.value, detail=task.meta["error"],
            )
            return task

        prev = task.status
        task.status = TaskStatus.running
        self.save(task)
        self.record_event(
            task.task_id, "status",
            status=task.status.value,
            detail=f"{prev.value}->{task.status.value}" if isinstance(prev, TaskStatus) else "running",
            step=task.current_step,
        )

        steps = list(self.policy)
        start_step = task.current_step
        stopped_early = False
        # seed prior agent from meta so resume still emits handoffs correctly
        prev_agent: Optional[str] = task.meta.get("last_agent")
        for step in steps:
            if step.number <= task.current_step:
                continue
            if max_steps is not None and step.number > (start_step + max_steps):
                stopped_early = True
                break

            agent_name = self.panel.resolve(step)
            # Swarm-style handoff when control transfers to a different agent
            if prev_agent and prev_agent != agent_name:
                self.record_event(
                    task.task_id, "handoff",
                    step=step.number, agent=agent_name, status=task.status.value,
                    detail=f"{prev_agent}->{agent_name}",
                    extra={"from_agent": prev_agent, "to_agent": agent_name},
                )
            self.record_event(
                task.task_id, "step_start",
                step=step.number, agent=agent_name, status=task.status.value,
                detail=step.name,
            )
            ctx = {
                "cascade": self.cascade.prompt_block(),
                "memory": self.memory.search(task.objective, ns=task.namespace, k=3),
                "objective": task.objective,
                "success_criteria": task.success_criteria,
                "prior": {n: task.outputs.get(n) for n in range(1, step.number)},
            }
            # Context engineering: shallow journal on resume / mid-run only
            journal_blk = ""
            if task.current_step > 0:
                journal_blk = self.journal_context(task.task_id, limit=8)
            prompt = (
                f"Step {step.number} {step.name}: {step.description}\n"
                f"Objective: {task.objective}\n"
                f"Criteria: {task.success_criteria}\n"
                f"{ctx['cascade']}\n"
                f"Memory hits: {len(ctx['memory'])}\n"
            )
            if journal_blk:
                prompt += journal_blk

            # Human gate — pause before running the approval step body
            if step.human and not self.auto_approve:
                # if already recorded an approval output (resume --approve), apply it
                if step.number in task.outputs and "approved" in task.outputs[step.number]:
                    if not task.outputs[step.number].get("approved"):
                        task.status = TaskStatus.failed
                        task.meta["error"] = "rejected by human"
                        self.save(task)
                        self.record_event(
                            task.task_id, "failed",
                            step=step.number, status=task.status.value,
                            detail=task.meta["error"],
                        )
                        return task
                    task.current_step = step.number
                    task.meta["last_agent"] = agent_name
                    prev_agent = agent_name
                    self.save(task)
                    self.record_event(
                        task.task_id, "step_complete",
                        step=step.number, agent=agent_name, status=task.status.value,
                        detail="human approved",
                    )
                    continue
                task.status = TaskStatus.waiting_human
                task.meta["waiting_step"] = step.number
                self.save(task)
                self.record_event(
                    task.task_id, "waiting_human",
                    step=step.number, status=task.status.value,
                    detail=step.name,
                )
                return task

            try:
                # carry last implement output for tester convenience
                if task.outputs:
                    last_n = max(task.outputs)
                    task.meta["last_output"] = task.outputs[last_n]
                run_task = {
                    "objective": task.objective,
                    "success_criteria": task.success_criteria,
                    "constraints": task.constraints,
                    "last_output": task.meta.get("last_output"),
                    "_artifact_path": task.meta.get(
                        "_artifact_path", f"results/{task.task_id}_artifact.txt"
                    ),
                    "task_id": task.task_id,
                }
                output = self.panel.run(agent_name, prompt, step=step, task=run_task)
            except Exception as e:
                task.status = TaskStatus.failed
                task.meta["error"] = f"step {step.number} agent error: {e}"
                self.save(task)
                self.record_event(
                    task.task_id, "failed",
                    step=step.number, agent=agent_name, status=task.status.value,
                    detail=task.meta["error"],
                )
                return task

            if self.settings.structural_pre_gate:
                ok, reason = structural_ok(step, output)
                if not ok:
                    task.status = TaskStatus.failed
                    task.meta["error"] = f"structural pre-gate: {reason}"
                    self.save(task)
                    self.record_event(
                        task.task_id, "failed",
                        step=step.number, agent=agent_name, status=task.status.value,
                        detail=task.meta["error"],
                    )
                    return task

            # Edict-style formal review veto (fail-closed)
            if step.name == "review":
                raw_verdict = str(output.get("verdict") or "").strip().lower()
                if raw_verdict in REVIEW_VETO_VERDICTS:
                    task.status = TaskStatus.failed
                    task.meta["error"] = f"review veto: {raw_verdict}"
                    task.outputs[step.number] = dict(output)
                    task.meta["last_agent"] = agent_name
                    self.save(task)
                    self.record_event(
                        task.task_id, "veto",
                        step=step.number, agent=agent_name, status=task.status.value,
                        detail=task.meta["error"],
                        extra={"verdict": raw_verdict},
                    )
                    self.record_event(
                        task.task_id, "failed",
                        step=step.number, agent=agent_name, status=task.status.value,
                        detail=task.meta["error"],
                    )
                    return task

            verdict = self.judge.evaluate(
                step=step, task=run_task, output=output, implementer=agent_name
            )
            self.trust.record_verdict(task.task_id, step.number, verdict.to_dict())
            self.trust.record_prov(
                task_id=task.task_id,
                step=step.number,
                agent=agent_name,
                vendor=self.panel.vendor_of.get(agent_name, "unknown"),
                summary=str(output)[:300],
            )

            # Hard-fail only on production-critical steps. Review/meta may lack
            # fresh artifact paths; their structural pre-gate is enough here.
            if verdict.decision == "fail" and step.name in {"implement", "test"}:
                task.status = TaskStatus.failed
                task.meta["error"] = f"judge failed step {step.number}: {verdict.rationale}"
                task.outputs[step.number] = {**output, "_verdict": verdict.to_dict()}
                self.save(task)
                self.record_event(
                    task.task_id, "failed",
                    step=step.number, agent=agent_name, status=task.status.value,
                    detail=task.meta["error"],
                    extra={"decision": verdict.decision},
                )
                return task

            task.outputs[step.number] = {**output, "_verdict": verdict.to_dict()}
            task.current_step = step.number
            task.meta["last_agent"] = agent_name
            prev_agent = agent_name
            if "artifacts" in output:
                task.meta["_artifact_path"] = (output["artifacts"] or [None])[0]
            # mission-control style per-step token estimate (prompt + output size)
            step_tokens = estimate_tokens(prompt) + estimate_tokens(
                json.dumps(output, default=str)
            )
            prev_tok = int(task.meta.get("tokens_total") or 0)
            task.meta["tokens_total"] = prev_tok + step_tokens
            self.save(task)
            # CEMA-style short causal "why" + value-system score/thresholds + tokens
            why = str(getattr(verdict, "rationale", "") or "")[:200]
            thr = getattr(verdict, "thresholds", None) or decision_thresholds()
            self.record_event(
                task.task_id, "step_complete",
                step=step.number, agent=agent_name, status=task.status.value,
                detail=step.name,
                extra={
                    "decision": getattr(verdict, "decision", ""),
                    "why": why,
                    "score": round(float(getattr(verdict, "score", 0.0) or 0.0), 4),
                    "tokens": step_tokens,
                    "thresholds": thr,
                },
            )

        if stopped_early:
            task.status = TaskStatus.running
            self.save(task)
            self.record_event(
                task.task_id, "checkpoint",
                step=task.current_step, status=task.status.value,
                detail=f"stopped early after {task.current_step}",
            )
            return task

        task.status = TaskStatus.completed
        task.meta["completed_at"] = time.time()
        self.save(task)
        self.record_event(
            task.task_id, "completed",
            step=task.current_step, status=task.status.value,
        )
        return task

    def resume(self, task_id: str, *, approve: Optional[bool] = None) -> Task:
        task = self.load(task_id)
        self.record_event(
            task_id, "resume",
            step=task.current_step, status=task.status.value,
            detail="approve" if approve is not None else "continue",
            extra={"approve": approve} if approve is not None else None,
        )
        if task.status == TaskStatus.waiting_human and approve is not None:
            step_n = int(task.meta.get("waiting_step") or 9)
            task.outputs[step_n] = {
                "approved": bool(approve),
                "feedback": "cli",
            }
            # do NOT advance current_step yet — run() consumes approval at gate
            task.status = TaskStatus.running
            self.save(task)
            if not approve:
                task.status = TaskStatus.failed
                task.meta["error"] = "rejected by human"
                self.save(task)
                self.record_event(
                    task_id, "failed",
                    step=step_n, status=task.status.value,
                    detail=task.meta["error"],
                )
                return task
        return self.run(task)

    def list_tasks(self) -> list[dict[str, Any]]:
        """Operator task board (MisterSmith / threadwork shape): status + last event."""
        d = self.settings.state_dir / "tasks"
        if not d.is_dir():
            return []
        out = []
        for p in sorted(d.glob("*.json")):
            # skip sidecar/tmp files
            if p.name.endswith(".tmp") or p.name.endswith(".events.jsonl"):
                continue
            if ".events." in p.name:
                continue
            try:
                t = Task.from_dict(json.loads(p.read_text(encoding="utf-8")))
                n_events = 0
                last_event = ""
                last_agent = t.meta.get("last_agent") or ""
                if self.journal:
                    rows = self.events(t.task_id)
                    n_events = len(rows)
                    if rows:
                        last_event = str(rows[-1].get("event") or "")
                        if not last_agent:
                            last_agent = str(rows[-1].get("agent") or "")
                out.append(
                    {
                        "task_id": t.task_id,
                        "status": t.status.value,
                        "current_step": t.current_step,
                        "objective": t.objective[:120],
                        "events": n_events,
                        "last_event": last_event,
                        "last_agent": last_agent,
                    }
                )
            except Exception:
                continue
        return out

    def replay(self, task_id: str, *, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Normalized decision timeline from the event journal (plan-replay shape).

        Does not re-run agents. Suitable for operator boards and post-hoc audit
        (open-multi-agent plan-replay / mission-control inspect patterns).
        """
        rows = self.events(task_id, limit=limit)
        timeline: list[dict[str, Any]] = []
        for i, r in enumerate(rows):
            entry: dict[str, Any] = {
                "i": i,
                "ts": r.get("ts"),
                "event": r.get("event"),
                "step": r.get("step"),
                "agent": r.get("agent") or "",
                "status": r.get("status") or "",
                "detail": r.get("detail") or "",
            }
            for k in (
                "from_agent", "to_agent", "decision", "why", "verdict", "approve",
                "score", "tokens", "thresholds",
            ):
                if r.get(k) not in (None, ""):
                    entry[k] = r[k]
            timeline.append(entry)
        return timeline

    def cost(self, task_id: str) -> dict[str, Any]:
        """Task-level token / score rollup (mission-control cost-tracker shape).

        Primary source: journal ``step_complete`` rows (tokens + judge score).
        Also merges optional global usage ledger rows tagged with meta.task_id.
        Read-only; does not re-run agents.
        """
        try:
            task = self.load(task_id)
        except FileNotFoundError:
            return {
                "task_id": task_id,
                "found": False,
                "error": f"task not found: {task_id}",
            }

        events = self.events(task_id)
        by_agent: dict[str, int] = {}
        by_step: dict[str, int] = {}
        scores: list[float] = []
        journal_tokens = 0
        step_rows: list[dict[str, Any]] = []
        thresholds: dict[str, float] = decision_thresholds()

        for e in events:
            if e.get("event") != "step_complete":
                continue
            tok = int(e.get("tokens") or 0)
            journal_tokens += tok
            agent = str(e.get("agent") or "") or "unknown"
            by_agent[agent] = by_agent.get(agent, 0) + tok
            sn = e.get("step")
            if sn is not None:
                by_step[str(sn)] = by_step.get(str(sn), 0) + tok
            sc = e.get("score")
            if sc is not None:
                try:
                    scores.append(float(sc))
                except (TypeError, ValueError):
                    pass
            thr = e.get("thresholds")
            if isinstance(thr, dict) and thr:
                thresholds = {str(k): float(v) for k, v in thr.items()}
            step_rows.append(
                {
                    "step": sn,
                    "name": e.get("detail") or "",
                    "agent": agent,
                    "tokens": tok,
                    "score": sc,
                    "decision": e.get("decision") or "",
                }
            )

        meta_tokens = int(task.meta.get("tokens_total") or 0)
        # Prefer journal sum; fall back to meta if older tasks lack per-step tokens
        total_tokens = journal_tokens if journal_tokens else meta_tokens

        ledger: dict[str, Any] = {}
        try:
            from . import usage as um

            # ledger lives under project root; try state_dir parent then cwd
            for root in (self.settings.state_dir.parent, Path.cwd()):
                ledger = um.by_task(task_id, root)
                if ledger.get("request_count"):
                    break
        except Exception:
            ledger = {}

        avg_score = round(sum(scores) / len(scores), 4) if scores else None
        return {
            "task_id": task.task_id,
            "found": True,
            "status": task.status.value,
            "total_tokens": total_tokens,
            "journal_tokens": journal_tokens,
            "meta_tokens": meta_tokens,
            "ledger_tokens": int(ledger.get("total_tokens") or 0),
            "request_count": len(step_rows),
            "avg_tokens_per_step": round(total_tokens / len(step_rows)) if step_rows else 0,
            "avg_score": avg_score,
            "thresholds": thresholds,
            "by_agent": by_agent,
            "by_step": by_step,
            "steps": step_rows,
            "ledger": ledger,
        }

    def explain(self, task_id: str) -> dict[str, Any]:
        """Causal decision chain for a task (CEMA-style sequential explanations).

        Merges checkpoint metadata, journal handoffs/vetoes, and per-step judge
        verdicts into a single operator-readable summary. Read-only.
        """
        try:
            task = self.load(task_id)
        except FileNotFoundError:
            return {
                "task_id": task_id,
                "found": False,
                "error": f"task not found: {task_id}",
            }

        events = self.events(task_id)
        handoffs = [
            {
                "step": e.get("step"),
                "from_agent": e.get("from_agent"),
                "to_agent": e.get("to_agent"),
                "detail": e.get("detail") or "",
            }
            for e in events
            if e.get("event") == "handoff"
        ]
        vetoes = [
            {
                "step": e.get("step"),
                "verdict": e.get("verdict") or e.get("detail") or "",
                "agent": e.get("agent") or "",
            }
            for e in events
            if e.get("event") == "veto"
        ]
        failures = [
            {
                "step": e.get("step"),
                "detail": e.get("detail") or "",
                "agent": e.get("agent") or "",
            }
            for e in events
            if e.get("event") == "failed"
        ]

        # Per-step causal chain: prefer journal why/decision, fall back to outputs
        by_step: dict[int, dict[str, Any]] = {}
        for e in events:
            if e.get("event") != "step_complete":
                continue
            sn = e.get("step")
            if sn is None:
                continue
            sn_i = int(sn)
            by_step[sn_i] = {
                "step": sn_i,
                "name": e.get("detail") or "",
                "agent": e.get("agent") or "",
                "decision": e.get("decision") or "",
                "why": e.get("why") or "",
                "score": e.get("score"),
                "tokens": e.get("tokens"),
            }
        for sn, out in (task.outputs or {}).items():
            sn_i = int(sn)
            row = by_step.setdefault(
                sn_i,
                {
                    "step": sn_i,
                    "name": "",
                    "agent": "",
                    "decision": "",
                    "why": "",
                    "score": None,
                    "tokens": None,
                },
            )
            verdict = out.get("_verdict") if isinstance(out, dict) else None
            if isinstance(verdict, dict):
                if not row.get("decision"):
                    row["decision"] = str(verdict.get("decision") or "")
                if not row.get("why"):
                    row["why"] = str(verdict.get("rationale") or "")[:200]
                if not row.get("agent") and verdict.get("implementer"):
                    row["agent"] = str(verdict.get("implementer") or "")
                if row.get("score") is None and verdict.get("score") is not None:
                    row["score"] = verdict.get("score")
            if isinstance(out, dict) and out.get("approved") is not None and not row.get("why"):
                row["why"] = "human approved" if out.get("approved") else "human rejected"
                row["decision"] = row.get("decision") or (
                    "pass" if out.get("approved") else "fail"
                )

        steps = [by_step[k] for k in sorted(by_step)]
        # One-line causal story for dashboards / MCP
        story_bits: list[str] = []
        for s in steps:
            bit = f"s{s['step']}"
            if s.get("name"):
                bit += f" {s['name']}"
            if s.get("agent"):
                bit += f"@{s['agent']}"
            if s.get("decision"):
                bit += f"→{s['decision']}"
            story_bits.append(bit)
        if vetoes:
            story_bits.append(f"veto@{vetoes[-1].get('step')}")
        if failures and task.status == TaskStatus.failed:
            story_bits.append("FAILED")
        elif task.status == TaskStatus.completed:
            story_bits.append("COMPLETED")

        cost_sum = self.cost(task_id)
        cost_brief = {
            "total_tokens": cost_sum.get("total_tokens", 0),
            "avg_score": cost_sum.get("avg_score"),
            "by_agent": cost_sum.get("by_agent") or {},
            "thresholds": cost_sum.get("thresholds") or decision_thresholds(),
        }

        return {
            "task_id": task.task_id,
            "found": True,
            "status": task.status.value,
            "current_step": task.current_step,
            "objective": task.objective,
            "error": task.meta.get("error") or "",
            "last_agent": task.meta.get("last_agent") or "",
            "n_events": len(events),
            "handoffs": handoffs,
            "vetoes": vetoes,
            "failures": failures,
            "steps": steps,
            "story": " | ".join(story_bits) if story_bits else "(no steps recorded)",
            "cost": cost_brief,
        }
