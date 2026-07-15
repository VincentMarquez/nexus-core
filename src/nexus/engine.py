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

Provenance / integrity (P4):
- ``provenance(task_id)`` — unified PROV-style agents/activities/entities/relations
  (PROV-AGENT shape; routa/mission-control trace export).
- ``verify(task_id)`` — checkpoint ↔ journal consistency checks
  (fault-tolerant durability / integrity gate).

Budget + call-graph (P5):
- ``meta.max_tokens`` hard-stop after each step (cycgraph / open-multi-agent
  maxTokenBudget / mission-control spend cap shape; may overshoot by one step).
- ``graph(task_id)`` — agent call-graph + space-time sequence from journal
  (MAS call-graph / space-time profiling papers; routa trace shape).

Evidence pack + norms (P6):
- ``evidence(task_id)`` — single portable audit pack (routa evidence board /
  mission-control export / AssetOpsBench eval shape).
- ``task_norms(task)`` — constraints/meta as structured norms (NorMAS /
  constitutional multi-agent governance light).

HITL resume (P7):
- ``resume(task_id, approve=…, feedback=…)`` — human-in-the-loop gate for
  ``waiting_human`` (rojak Temporal resume / mission-control operator shape).
- CLI: ``nexus task resume <id> --approve|--reject`` records a ``human_decision``
  journal event and continues or fail-closes.

Wall-clock budget (P8):
- ``meta.max_wall_s`` / constraint ``max_wall_s=…`` hard-stop by elapsed wall time
  (cycgraph multi-budget / latency-tracker shape; may overshoot by one step).
- ``task_max_wall_s()`` + ``task_elapsed_s()``; journal ``budget`` events carry
  ``kind=wall``; ``cost()`` / ``evidence()`` expose elapsed + remaining wall.

Norm enforcement (P9):
- Opt-in via ``meta.enforce_norms`` or constraint ``enforce_norms=true``
  (NorMAS / constitutional MAS / mission-control quality-gate shape).
- Pre-step **deny** match against step name / agent / description → fail-closed.
- Pre-complete **require** coverage of pipeline steps → fail if unmet.
- Journal ``norm`` events; evidence gate ``norms_ok``.

Per-run durability package (P10 — cycgraph first-apply slice):
- ``nexus.durability`` — ``RunBudget`` (steps/tokens/cost), ``TaintSet`` labels,
  ``DurableAgent`` step wrapper (budget pre-check + taint post-write).
- ``meta.max_steps`` / constraint ``max_steps=N`` hard-stop this run (distinct
  from ``run(max_steps=)`` soft early-stop).
- Env defaults: ``NEXUS_MAX_STEPS``, ``NEXUS_MAX_COST`` (via durability helpers).

Zero-trust state slice (P11 — cycgraph read_keys / write_keys):
- ``nexus.durability.StateSlice`` — permission-scoped view/merge; empty default
  is deny-all; ``*`` for trusted system agents; protected ``_`` keys unwritable.
- ``DurableAgent(slice=…)`` enforces read/write keys; ``view()`` filters state.
- Opt-in via ``meta.read_keys`` / ``meta.write_keys`` / ``meta.state_slice``.

Multi-agent task DAG (P1.2 — open-multi-agent + AOAD-MAT):
- Schedule via ``StepPolicy.ready(completed)`` (dependency gate, not pure linear).
- ``meta.action_order[]`` records explicit step order (AOAD-MAT).
- ``dag(task_id)`` — policy dependency snapshot + mermaid (``nexus.dag/v1``).
- Context ``prior`` uses dependency outputs when ``depends_on`` is set.

Consensus grading (P1.3 — gossipcat independent findings + trust weights):
- ``Settings.consensus_judge`` (default on) runs multi-grader ``ConsensusJudge``.
- Per-step verdict carries ``findings`` / ``agreement_ratio`` / ``counts``.
- Journal ``consensus`` events; ``consensus(task_id)`` operator export.
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
from .durability import RunBudget, budget_from_env, budget_from_meta
from .consensus import ConsensusJudge, SCHEMA as CONSENSUS_SCHEMA
from .judge import RubricJudge, decision_thresholds
from .memory import MemorySpine
from .persist import append_jsonl, atomic_write_json, event_row, read_jsonl
from .steps import StepPolicy, completed_set, structural_ok
from .trust import TrustLog
from .usage import estimate_tokens

# Review step verdicts that hard-fail the pipeline (edict fail-closed audit).
REVIEW_VETO_VERDICTS = frozenset({"reject", "veto", "fail", "deny", "blocked"})


def task_max_tokens(task: "Task") -> Optional[int]:
    """Resolve per-task token hard-cap from meta or constraints (None = unlimited).

    Sources (first match wins):
    - ``task.meta["max_tokens"]`` (int / numeric string)
    - constraint strings like ``max_tokens=5000`` or ``max_tokens: 5000``
    """
    raw = (task.meta or {}).get("max_tokens")
    if raw is not None and raw != "":
        try:
            n = int(raw)
            return n if n > 0 else None
        except (TypeError, ValueError):
            pass
    for c in task.constraints or []:
        s = str(c).strip().lower().replace(" ", "")
        for prefix in ("max_tokens=", "max_tokens:"):
            if s.startswith(prefix):
                try:
                    n = int(s[len(prefix) :])
                    return n if n > 0 else None
                except ValueError:
                    break
    return None


def task_max_steps(task: "Task") -> Optional[int]:
    """Resolve per-run step hard-cap from meta or constraints (None = unlimited).

    Distinct from ``DurableEngine.run(..., max_steps=)`` which soft-stops and
    leaves status=running for resume. This hard-fails with ``budget_exhausted``
    (cycgraph / durability RunBudget shape).

    Sources (first match wins):
    - ``task.meta["max_steps"]``
    - constraint strings like ``max_steps=5`` or ``max_steps: 5``
    """
    raw = (task.meta or {}).get("max_steps")
    if raw is not None and raw != "":
        try:
            n = int(raw)
            return n if n > 0 else None
        except (TypeError, ValueError):
            pass
    for c in task.constraints or []:
        s = str(c).strip().lower().replace(" ", "")
        for prefix in ("max_steps=", "max_steps:"):
            if s.startswith(prefix):
                try:
                    n = int(s[len(prefix) :])
                    return n if n > 0 else None
                except ValueError:
                    break
    return None


def task_run_budget(task: "Task", *, use_env: bool = False) -> RunBudget:
    """Build a :class:`RunBudget` snapshot for *task* (meta + optional env)."""
    b = budget_from_meta(task.meta)
    # prefer explicit resolvers so constraint strings are honored
    ms = task_max_steps(task)
    if ms is not None:
        b.max_steps = ms
    mt = task_max_tokens(task)
    if mt is not None:
        b.max_tokens = mt
    if use_env:
        env_b = budget_from_env()
        if b.max_steps is None:
            b.max_steps = env_b.max_steps
        if b.max_tokens is None:
            b.max_tokens = env_b.max_tokens
        if b.max_cost_usd is None:
            b.max_cost_usd = env_b.max_cost_usd
    return b


def task_max_wall_s(task: "Task") -> Optional[float]:
    """Resolve per-task wall-clock hard-cap in seconds (None = unlimited).

    Sources (first match wins):
    - ``task.meta["max_wall_s"]`` or ``task.meta["max_wall_seconds"]``
    - constraint strings like ``max_wall_s=30``, ``max_wall_s: 30``,
      ``max_seconds=30``, ``max_wall=30``

    cycgraph multi-budget / latency shape: pair with ``max_tokens`` for dual caps.
    """
    meta = task.meta or {}
    for key in ("max_wall_s", "max_wall_seconds", "max_seconds"):
        raw = meta.get(key)
        if raw is not None and raw != "":
            try:
                n = float(raw)
                return n if n > 0 else None
            except (TypeError, ValueError):
                pass
    for c in task.constraints or []:
        s = str(c).strip().lower().replace(" ", "")
        for prefix in (
            "max_wall_s=",
            "max_wall_s:",
            "max_wall_seconds=",
            "max_wall_seconds:",
            "max_seconds=",
            "max_seconds:",
            "max_wall=",
            "max_wall:",
        ):
            if s.startswith(prefix):
                try:
                    n = float(s[len(prefix) :])
                    return n if n > 0 else None
                except ValueError:
                    break
    return None


def task_elapsed_s(task: "Task", *, now: Optional[float] = None) -> Optional[float]:
    """Elapsed wall seconds since ``meta.started_at`` (None if not started)."""
    raw = (task.meta or {}).get("started_at")
    if raw is None or raw == "":
        return None
    try:
        started = float(raw)
    except (TypeError, ValueError):
        return None
    t = float(now if now is not None else time.time())
    return max(0.0, t - started)


# require:token → step names that satisfy the requirement (substring match on step.name)
_REQUIRE_STEP_HINTS: dict[str, tuple[str, ...]] = {
    "tests": ("test",),
    "test": ("test",),
    "review": ("review", "meta_review"),
    "plan": ("plan",),
    "human": ("approval",),
    "approval": ("approval",),
    "implement": ("implement",),
    "deliver": ("deliver",),
    "goal": ("goal",),
    "challenge": ("challenge",),
    "log": ("log",),
}


def task_enforce_norms(task: "Task") -> bool:
    """Whether deny/require norms hard-fail the run (opt-in; default off).

    Sources:
    - ``task.meta["enforce_norms"]`` truthy/falsey strings
    - constraint ``enforce_norms``, ``enforce_norms=true``, ``enforce_norms=false``
    """
    raw = (task.meta or {}).get("enforce_norms")
    if raw is not None and raw != "":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
    for c in task.constraints or []:
        s = str(c).strip().lower().replace(" ", "")
        if s in ("enforce_norms", "enforce_norms=true", "enforce_norms:true", "enforce_norms=1"):
            return True
        if s in ("enforce_norms=false", "enforce_norms:false", "enforce_norms=0"):
            return False
    return False


def norm_deny_hit(
    task: "Task",
    *,
    step_name: str,
    agent_name: str,
    step_description: str = "",
) -> Optional[str]:
    """Return the deny token if this step/agent is blocked, else None."""
    norms = task_norms(task)
    hay = f"{step_name} {agent_name} {step_description}".lower()
    for d in norms.get("deny") or []:
        token = str(d).strip().lower()
        if token and token in hay:
            return str(d).strip()
    return None


def norm_require_gaps(task: "Task", *, policy: Optional["StepPolicy"] = None) -> list[str]:
    """Return require tokens not yet satisfied by completed steps.

    Satisfaction: a completed step whose name contains a known hint for the
    token (e.g. require:tests ↔ step ``test``), or the raw token itself.
    """
    norms = task_norms(task)
    reqs = [str(r).strip() for r in (norms.get("require") or []) if str(r).strip()]
    if not reqs:
        return []

    completed_names: list[str] = []
    if policy is not None:
        for s in policy:
            if s.number <= int(task.current_step or 0):
                completed_names.append(s.name.lower())
    # Also use output keys as completed step numbers when policy unavailable
    if not completed_names and task.outputs:
        completed_names = [f"step{n}" for n in task.outputs]

    gaps: list[str] = []
    for req in reqs:
        key = req.lower().replace(" ", "")
        hints = _REQUIRE_STEP_HINTS.get(key, (key,))
        ok = False
        for name in completed_names:
            for h in hints:
                if h and h in name:
                    ok = True
                    break
            if ok:
                break
        # human: also accept explicit approval output
        if not ok and key in ("human", "approval"):
            for out in (task.outputs or {}).values():
                if isinstance(out, dict) and out.get("approved") is True:
                    ok = True
                    break
        if not ok:
            gaps.append(req)
    return gaps


def task_norms(task: "Task") -> dict[str, Any]:
    """Interpret constraints + meta as structured operator norms.

    Light NorMAS / constitutional-governance shape: free-form constraints stay
    as ``raw``; recognized prefixes become typed rules (require / deny / budget).
    Enforcement is opt-in via ``task_enforce_norms`` (P9); packs always expose norms.
    """
    raw = [str(c) for c in (task.constraints or [])]
    rules: list[dict[str, Any]] = []
    require: list[str] = []
    deny: list[str] = []

    for c in raw:
        s = c.strip()
        low = s.lower().replace(" ", "")
        # P9: enforce flag is meta for the pack, not a soft constraint
        if low.startswith("enforce_norms"):
            rules.append(
                {
                    "kind": "enforce",
                    "value": task_enforce_norms(task),
                    "source": c,
                }
            )
            continue
        # token budget
        budget_matched = False
        for prefix in ("max_tokens=", "max_tokens:"):
            if low.startswith(prefix):
                try:
                    n = int(low[len(prefix) :])
                    if n > 0:
                        rules.append({"kind": "budget", "key": "max_tokens", "value": n, "source": c})
                except ValueError:
                    rules.append({"kind": "budget", "key": "max_tokens", "value": None, "source": c})
                budget_matched = True
                break
        if budget_matched:
            continue
        # wall-clock budget (P8)
        for prefix in (
            "max_wall_s=",
            "max_wall_s:",
            "max_wall_seconds=",
            "max_wall_seconds:",
            "max_seconds=",
            "max_seconds:",
            "max_wall=",
            "max_wall:",
        ):
            if low.startswith(prefix):
                try:
                    n = float(low[len(prefix) :])
                    if n > 0:
                        rules.append({"kind": "budget", "key": "max_wall_s", "value": n, "source": c})
                except ValueError:
                    rules.append({"kind": "budget", "key": "max_wall_s", "value": None, "source": c})
                budget_matched = True
                break
        if budget_matched:
            continue
        for kind, prefixes in (
            ("require", ("require:", "require=", "must:", "must=")),
            ("deny", ("deny:", "deny=", "forbid:", "forbid=", "no:")),
        ):
            matched = False
            for p in prefixes:
                if low.startswith(p.replace(" ", "")) or s.lower().startswith(p):
                    # keep original value after first separator
                    sep = ":" if ":" in s else ("=" if "=" in s else None)
                    val = s.split(sep, 1)[1].strip() if sep else s
                    rules.append({"kind": kind, "value": val, "source": c})
                    if kind == "require":
                        require.append(val)
                    else:
                        deny.append(val)
                    matched = True
                    break
            if matched:
                break
        else:
            # unstructured constraint → soft norm
            if s:
                rules.append({"kind": "constraint", "value": s, "source": c})

    cap = task_max_tokens(task)
    wall = task_max_wall_s(task)
    enforce = task_enforce_norms(task)
    # meta-level norms (not duplicated if already in rules)
    if cap is not None and not any(r.get("key") == "max_tokens" for r in rules):
        rules.append({"kind": "budget", "key": "max_tokens", "value": cap, "source": "meta.max_tokens"})
    if wall is not None and not any(r.get("key") == "max_wall_s" for r in rules):
        rules.append({"kind": "budget", "key": "max_wall_s", "value": wall, "source": "meta.max_wall_s"})
    if enforce and not any(r.get("kind") == "enforce" for r in rules):
        rules.append({"kind": "enforce", "value": True, "source": "meta.enforce_norms"})

    if (task.meta or {}).get("require_human") in (True, "true", "1", 1):
        rules.append({"kind": "require", "value": "human", "source": "meta.require_human"})
        if "human" not in require:
            require.append("human")

    return {
        "raw": raw,
        "rules": rules,
        "require": require,
        "deny": deny,
        "max_tokens": cap,
        "max_wall_s": wall,
        "enforce": enforce,
        "n_rules": len(rules),
    }


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
        prefer_xv = self.settings.prefer_cross_vendor_judge
        if getattr(self.settings, "consensus_judge", True):
            self.judge = ConsensusJudge(
                self.panel,
                prefer_cross_vendor=prefer_xv,
                min_graders=int(getattr(self.settings, "consensus_min_graders", 2) or 2),
                max_graders=int(getattr(self.settings, "consensus_max_graders", 3) or 3),
            )
        else:
            self.judge = RubricJudge(self.panel, prefer_cross_vendor=prefer_xv)
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
        try:
            from . import metrics as metrics_mod

            metrics_mod.record_task_event(event, status=status or "")
            metrics_mod.flush(self.settings.state_dir.parent if self.settings else None)
        except Exception:
            pass

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
        # P8: durable wall-clock origin (preserved across crash-resume)
        if not task.meta.get("started_at"):
            task.meta["started_at"] = time.time()
        self.save(task)
        self.record_event(
            task.task_id, "status",
            status=task.status.value,
            detail=f"{prev.value}->{task.status.value}" if isinstance(prev, TaskStatus) else "running",
            step=task.current_step,
        )

        start_step = task.current_step
        stopped_early = False
        # P10: per-run step counter for meta.max_steps hard-cap (durability)
        steps_this_run = 0
        run_step_cap = task_max_steps(task)
        # P1.2: multi-agent task DAG — completed set + explicit action order
        try:
            self.policy.validate()
        except ValueError as e:
            task.status = TaskStatus.failed
            task.meta["error"] = f"invalid step DAG: {e}"
            self.save(task)
            self.record_event(
                task.task_id, "failed",
                status=task.status.value, detail=task.meta["error"],
            )
            return task
        completed = completed_set(task.outputs, current_step=task.current_step)
        action_order: list[str] = [
            str(x) for x in (task.meta.get("action_order") or []) if x is not None
        ]
        # seed prior agent from meta so resume still emits handoffs correctly
        prev_agent: Optional[str] = task.meta.get("last_agent")
        while True:
            ready_list = self.policy.ready(
                completed, current_step=task.current_step
            )
            if not ready_list:
                # No ready work: done, or deadlocked on unmet deps
                remaining = self.policy.pending(completed)
                if remaining:
                    blocked = self.policy.blocked(completed)
                    detail = (
                        "dag blocked: no ready steps; remaining="
                        + ",".join(str(s.number) for s in remaining)
                    )
                    if blocked:
                        waits = []
                        for b in blocked:
                            miss = sorted(set(b.depends_on) - completed)
                            waits.append(f"{b.number}:wait:{','.join(map(str, miss))}")
                        detail += " blocked=" + ";".join(waits)
                    task.status = TaskStatus.failed
                    task.meta["error"] = detail
                    task.meta["dag_deadlock"] = True
                    task.meta["action_order"] = action_order
                    self.save(task)
                    self.record_event(
                        task.task_id, "failed",
                        step=task.current_step, status=task.status.value,
                        detail=detail,
                        extra={"kind": "dag_deadlock", "remaining": [s.number for s in remaining]},
                    )
                    return task
                break

            # Soft max_steps: only consider ready steps within start_step+max_steps
            eligible = ready_list
            if max_steps is not None:
                eligible = [
                    s for s in ready_list
                    if s.number <= (start_step + max_steps)
                ]
                if not eligible:
                    stopped_early = True
                    break

            step = eligible[0]  # lowest number among ready (stable AOAD-MAT order)

            # P10: meta.max_steps hard-stop (fail-closed; distinct from soft max_steps arg)
            if run_step_cap is not None and steps_this_run >= run_step_cap:
                task.status = TaskStatus.failed
                task.meta["error"] = (
                    f"task step budget exceeded: steps_this_run={steps_this_run} "
                    f"max_steps={run_step_cap}"
                )
                task.meta["budget_exhausted"] = True
                task.meta["run_budget"] = task_run_budget(task).snapshot()
                self.save(task)
                self.record_event(
                    task.task_id, "budget",
                    step=task.current_step, status=task.status.value,
                    detail=task.meta["error"],
                    extra={
                        "kind": "steps",
                        "max_steps": run_step_cap,
                        "steps_this_run": steps_this_run,
                        "remaining": 0,
                        "phase": "pre_step",
                    },
                )
                self.record_event(
                    task.task_id, "failed",
                    step=task.current_step, status=task.status.value,
                    detail=task.meta["error"],
                )
                return task

            # Pre-step budget gate (already spent ≥ cap → refuse further work)
            cap = task_max_tokens(task)
            spent = int(task.meta.get("tokens_total") or 0)
            if cap is not None and spent >= cap:
                task.status = TaskStatus.failed
                task.meta["error"] = (
                    f"task budget exceeded: tokens_total={spent} max_tokens={cap}"
                )
                task.meta["budget_exhausted"] = True
                self.save(task)
                self.record_event(
                    task.task_id, "budget",
                    step=task.current_step, status=task.status.value,
                    detail=task.meta["error"],
                    extra={
                        "kind": "tokens",
                        "max_tokens": cap,
                        "tokens_total": spent,
                        "remaining": 0,
                        "phase": "pre_step",
                    },
                )
                self.record_event(
                    task.task_id, "failed",
                    step=task.current_step, status=task.status.value,
                    detail=task.meta["error"],
                )
                return task

            # Pre-step wall-clock gate (cycgraph multi-budget / latency hard-stop)
            wall_cap = task_max_wall_s(task)
            elapsed = task_elapsed_s(task)
            if wall_cap is not None and elapsed is not None and elapsed >= wall_cap:
                task.status = TaskStatus.failed
                task.meta["error"] = (
                    f"task wall budget exceeded: elapsed_s={elapsed:.3f} max_wall_s={wall_cap}"
                )
                task.meta["budget_exhausted"] = True
                task.meta["wall_exhausted"] = True
                task.meta["elapsed_s"] = round(elapsed, 3)
                self.save(task)
                self.record_event(
                    task.task_id, "budget",
                    step=task.current_step, status=task.status.value,
                    detail=task.meta["error"],
                    extra={
                        "kind": "wall",
                        "max_wall_s": wall_cap,
                        "elapsed_s": round(elapsed, 3),
                        "remaining": 0,
                        "phase": "pre_step",
                    },
                )
                self.record_event(
                    task.task_id, "failed",
                    step=task.current_step, status=task.status.value,
                    detail=task.meta["error"],
                )
                return task

            agent_name = self.panel.resolve(step)

            # P9: opt-in deny gate (NorMAS / quality-gate fail-closed)
            if task_enforce_norms(task):
                denied = norm_deny_hit(
                    task,
                    step_name=step.name,
                    agent_name=agent_name,
                    step_description=step.description or "",
                )
                if denied:
                    task.status = TaskStatus.failed
                    task.meta["error"] = (
                        f"norm deny: {denied!r} blocked step={step.name} agent={agent_name}"
                    )
                    task.meta["norm_violation"] = {
                        "kind": "deny",
                        "token": denied,
                        "step": step.number,
                        "step_name": step.name,
                        "agent": agent_name,
                    }
                    self.save(task)
                    self.record_event(
                        task.task_id, "norm",
                        step=step.number, agent=agent_name, status=task.status.value,
                        detail=task.meta["error"],
                        extra={
                            "kind": "deny",
                            "token": denied,
                            "phase": "pre_step",
                            "step_name": step.name,
                        },
                    )
                    self.record_event(
                        task.task_id, "failed",
                        step=step.number, agent=agent_name, status=task.status.value,
                        detail=task.meta["error"],
                    )
                    return task

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
            # P1.2: dependency-scoped prior context (open-multi-agent memoryScope)
            prior_keys = self.policy.prior_keys(step)
            ctx = {
                "cascade": self.cascade.prompt_block(),
                "memory": self.memory.search(task.objective, ns=task.namespace, k=3),
                "objective": task.objective,
                "success_criteria": task.success_criteria,
                "prior": {n: task.outputs.get(n) for n in prior_keys if n in task.outputs},
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
                    task.current_step = max(int(task.current_step or 0), step.number)
                    completed.add(step.number)
                    order_token = f"{step.number}:{step.name}"
                    if order_token not in action_order:
                        action_order.append(order_token)
                    task.meta["action_order"] = list(action_order)
                    task.meta["last_agent"] = agent_name
                    prev_agent = agent_name
                    self.save(task)
                    self.record_event(
                        task.task_id, "step_complete",
                        step=step.number, agent=agent_name, status=task.status.value,
                        detail="human approved",
                        extra={
                            "action_order_i": len(action_order),
                            "depends_on": list(step.depends_on),
                        },
                    )
                    continue
                task.status = TaskStatus.waiting_human
                task.meta["waiting_step"] = step.number
                task.meta["action_order"] = list(action_order)
                self.save(task)
                self.record_event(
                    task.task_id, "waiting_human",
                    step=step.number, status=task.status.value,
                    detail=step.name,
                    extra={"ready": [s.number for s in ready_list], "depends_on": list(step.depends_on)},
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
            task.current_step = max(int(task.current_step or 0), step.number)
            completed.add(step.number)
            order_token = f"{step.number}:{step.name}"
            action_order.append(order_token)
            task.meta["action_order"] = list(action_order)
            task.meta["last_agent"] = agent_name
            prev_agent = agent_name
            steps_this_run += 1
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
            complete_extra: dict[str, Any] = {
                "decision": getattr(verdict, "decision", ""),
                "why": why,
                "score": round(float(getattr(verdict, "score", 0.0) or 0.0), 4),
                "tokens": step_tokens,
                "thresholds": thr,
                "action_order_i": len(action_order),
                "depends_on": list(step.depends_on),
            }
            # Gossipcat-style consensus summary when multi-grader path is active
            findings_list = getattr(verdict, "findings", None)
            if findings_list is not None:
                complete_extra["consensus"] = True
                complete_extra["agreement_ratio"] = round(
                    float(getattr(verdict, "agreement_ratio", 0.0) or 0.0), 4
                )
                complete_extra["n_graders"] = int(
                    getattr(verdict, "n_graders", 0) or 0
                )
                complete_extra["counts"] = dict(
                    getattr(verdict, "counts", None) or {}
                )
                grader_names: list[str] = []
                for f in findings_list:
                    if isinstance(f, dict):
                        grader_names.append(str(f.get("grader") or ""))
                    else:
                        grader_names.append(str(getattr(f, "grader", "") or ""))
                self.record_event(
                    task.task_id, "consensus",
                    step=step.number, agent=agent_name, status=task.status.value,
                    detail=step.name,
                    extra={
                        "decision": getattr(verdict, "decision", ""),
                        "score": complete_extra["score"],
                        "agreement_ratio": complete_extra["agreement_ratio"],
                        "n_graders": complete_extra["n_graders"],
                        "counts": complete_extra["counts"],
                        "graders": grader_names,
                        "degraded": bool(getattr(verdict, "degraded", False)),
                        "schema": getattr(verdict, "schema", CONSENSUS_SCHEMA),
                    },
                )
            self.record_event(
                task.task_id, "step_complete",
                step=step.number, agent=agent_name, status=task.status.value,
                detail=step.name,
                extra=complete_extra,
            )

            # Post-step budget hard-stop (open-multi-agent: may overshoot by 1 turn)
            cap = task_max_tokens(task)
            spent = int(task.meta.get("tokens_total") or 0)
            if cap is not None and spent > cap:
                task.status = TaskStatus.failed
                task.meta["error"] = (
                    f"task budget exceeded: tokens_total={spent} max_tokens={cap}"
                )
                task.meta["budget_exhausted"] = True
                self.save(task)
                self.record_event(
                    task.task_id, "budget",
                    step=step.number, agent=agent_name, status=task.status.value,
                    detail=task.meta["error"],
                    extra={
                        "kind": "tokens",
                        "max_tokens": cap,
                        "tokens_total": spent,
                        "remaining": 0,
                        "phase": "post_step",
                        "step_tokens": step_tokens,
                    },
                )
                self.record_event(
                    task.task_id, "failed",
                    step=step.number, agent=agent_name, status=task.status.value,
                    detail=task.meta["error"],
                )
                return task

            # Post-step wall-clock hard-stop (may overshoot by one completed step)
            wall_cap = task_max_wall_s(task)
            elapsed = task_elapsed_s(task)
            if wall_cap is not None and elapsed is not None and elapsed > wall_cap:
                task.status = TaskStatus.failed
                task.meta["error"] = (
                    f"task wall budget exceeded: elapsed_s={elapsed:.3f} max_wall_s={wall_cap}"
                )
                task.meta["budget_exhausted"] = True
                task.meta["wall_exhausted"] = True
                task.meta["elapsed_s"] = round(elapsed, 3)
                self.save(task)
                self.record_event(
                    task.task_id, "budget",
                    step=step.number, agent=agent_name, status=task.status.value,
                    detail=task.meta["error"],
                    extra={
                        "kind": "wall",
                        "max_wall_s": wall_cap,
                        "elapsed_s": round(elapsed, 3),
                        "remaining": 0,
                        "phase": "post_step",
                    },
                )
                self.record_event(
                    task.task_id, "failed",
                    step=step.number, agent=agent_name, status=task.status.value,
                    detail=task.meta["error"],
                )
                return task

        if stopped_early:
            task.status = TaskStatus.running
            self.save(task)
            self.record_event(
                task.task_id, "checkpoint",
                step=task.current_step, status=task.status.value,
                detail=f"stopped early after {task.current_step}",
            )
            return task

        # P9: opt-in require coverage gate before completed
        if task_enforce_norms(task):
            gaps = norm_require_gaps(task, policy=self.policy)
            if gaps:
                task.status = TaskStatus.failed
                task.meta["error"] = f"norm require unmet: {', '.join(gaps)}"
                task.meta["norm_violation"] = {
                    "kind": "require",
                    "unmet": gaps,
                    "step": task.current_step,
                }
                self.save(task)
                self.record_event(
                    task.task_id, "norm",
                    step=task.current_step, status=task.status.value,
                    detail=task.meta["error"],
                    extra={"kind": "require", "unmet": gaps, "phase": "pre_complete"},
                )
                self.record_event(
                    task.task_id, "failed",
                    step=task.current_step, status=task.status.value,
                    detail=task.meta["error"],
                )
                return task

        task.status = TaskStatus.completed
        task.meta["completed_at"] = time.time()
        el = task_elapsed_s(task)
        if el is not None:
            task.meta["elapsed_s"] = round(el, 3)
        self.save(task)
        self.record_event(
            task.task_id, "completed",
            step=task.current_step, status=task.status.value,
            extra={"elapsed_s": task.meta.get("elapsed_s")} if el is not None else None,
        )
        return task

    def resume(
        self,
        task_id: str,
        *,
        approve: Optional[bool] = None,
        feedback: Optional[str] = None,
    ) -> Task:
        """Continue a checkpointed task; optionally resolve a human gate.

        When status is ``waiting_human``:
        - ``approve=True`` records the human decision and continues the pipeline
        - ``approve=False`` fail-closes with ``rejected by human``
        - ``approve=None`` leaves the decision unset (caller / CLI should refuse
          silent auto-approve for HITL tasks)

        Crash-resume (status ``running`` / partial) ignores ``approve`` and
        continues from the last completed step.
        """
        task = self.load(task_id)
        fb = (feedback or "").strip() or ("cli" if approve is not None else "")
        self.record_event(
            task_id, "resume",
            step=task.current_step, status=task.status.value,
            detail=(
                "approve" if approve is True
                else "reject" if approve is False
                else "continue"
            ),
            extra=(
                {"approve": approve, "feedback": fb}
                if approve is not None
                else ({"feedback": fb} if fb else None)
            ),
        )
        if task.status == TaskStatus.waiting_human and approve is not None:
            step_n = int(task.meta.get("waiting_step") or 9)
            task.outputs[step_n] = {
                "approved": bool(approve),
                "feedback": fb or "cli",
            }
            task.meta["human_decision"] = {
                "approved": bool(approve),
                "feedback": fb or "cli",
                "step": step_n,
                "ts": time.time(),
            }
            # do NOT advance current_step yet — run() consumes approval at gate
            task.status = TaskStatus.running
            self.save(task)
            self.record_event(
                task_id, "human_decision",
                step=step_n, status=task.status.value,
                detail="approve" if approve else "reject",
                extra={
                    "approve": bool(approve),
                    "feedback": fb or "cli",
                    "decision": "approve" if approve else "reject",
                },
            )
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
                tokens = int(t.meta.get("tokens_total") or 0)
                out.append(
                    {
                        "task_id": t.task_id,
                        "status": t.status.value,
                        "current_step": t.current_step,
                        "objective": t.objective[:120],
                        "events": n_events,
                        "last_event": last_event,
                        "last_agent": last_agent,
                        "tokens": tokens,
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
                "score", "tokens", "thresholds", "feedback",
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
        cap = task_max_tokens(task)
        remaining: Optional[int]
        if cap is None:
            remaining = None
            token_exhausted = False
        else:
            remaining = max(0, cap - total_tokens)
            token_exhausted = total_tokens > cap

        wall_cap = task_max_wall_s(task)
        # Prefer stored elapsed on terminal tasks; else live clock from started_at
        if task.meta.get("elapsed_s") is not None and task.status in (
            TaskStatus.completed,
            TaskStatus.failed,
        ):
            try:
                elapsed: Optional[float] = float(task.meta["elapsed_s"])
            except (TypeError, ValueError):
                elapsed = task_elapsed_s(task)
        else:
            elapsed = task_elapsed_s(task)

        remaining_wall: Optional[float]
        if wall_cap is None:
            remaining_wall = None
            wall_exhausted = bool(task.meta.get("wall_exhausted"))
        else:
            el = float(elapsed or 0.0)
            remaining_wall = max(0.0, round(wall_cap - el, 3))
            wall_exhausted = bool(task.meta.get("wall_exhausted")) or el > wall_cap

        # Honor explicit fail-closed flags from the engine run path
        if task.meta.get("wall_exhausted"):
            wall_exhausted = True
        if task.meta.get("budget_exhausted") and not task.meta.get("wall_exhausted"):
            # token-path hard-stop without wall
            err = str(task.meta.get("error") or "")
            if "max_tokens=" in err or "tokens_total=" in err:
                token_exhausted = True

        exhausted = bool(
            token_exhausted
            or wall_exhausted
            or task.meta.get("budget_exhausted")
        )
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
            # P5: per-task hard token budget (None = unlimited)
            "max_tokens": cap,
            "remaining_tokens": remaining,
            # P8: wall-clock budget (cycgraph multi-budget)
            "max_wall_s": wall_cap,
            "elapsed_s": None if elapsed is None else round(float(elapsed), 3),
            "remaining_wall_s": remaining_wall,
            "wall_exhausted": wall_exhausted,
            "started_at": task.meta.get("started_at"),
            "budget_exhausted": exhausted,
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
        human_decisions = [
            {
                "step": e.get("step"),
                "decision": e.get("decision") or e.get("detail") or "",
                "approve": e.get("approve"),
                "feedback": e.get("feedback") or "",
            }
            for e in events
            if e.get("event") == "human_decision"
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
        if human_decisions:
            hd = human_decisions[-1]
            story_bits.append(
                f"human@{hd.get('step')}→{hd.get('decision') or ('approve' if hd.get('approve') else 'reject')}"
            )
        if vetoes:
            story_bits.append(f"veto@{vetoes[-1].get('step')}")
        if failures and task.status == TaskStatus.failed:
            story_bits.append("FAILED")
        elif task.status == TaskStatus.completed:
            story_bits.append("COMPLETED")
        elif task.status == TaskStatus.waiting_human:
            story_bits.append("WAITING_HUMAN")

        cost_sum = self.cost(task_id)
        cost_brief = {
            "total_tokens": cost_sum.get("total_tokens", 0),
            "avg_score": cost_sum.get("avg_score"),
            "by_agent": cost_sum.get("by_agent") or {},
            "thresholds": cost_sum.get("thresholds") or decision_thresholds(),
            "max_tokens": cost_sum.get("max_tokens"),
            "max_wall_s": cost_sum.get("max_wall_s"),
            "elapsed_s": cost_sum.get("elapsed_s"),
            "remaining_wall_s": cost_sum.get("remaining_wall_s"),
            "wall_exhausted": cost_sum.get("wall_exhausted", False),
            "budget_exhausted": cost_sum.get("budget_exhausted", False),
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
            "human_decisions": human_decisions,
            "steps": steps,
            "story": " | ".join(story_bits) if story_bits else "(no steps recorded)",
            "cost": cost_brief,
            "waiting_step": task.meta.get("waiting_step"),
        }

    def provenance(self, task_id: str) -> dict[str, Any]:
        """Unified PROV-style document of agent interactions (PROV-AGENT shape).

        Emits agents, activities (steps), entities (task + artifacts), and
        relations (wasAssociatedWith / used / generated / wasInformedBy /
        wasDerivedFrom handoffs). Read-only; merges checkpoint, journal, and
        optional trust-log rows for this task.
        """
        try:
            task = self.load(task_id)
        except FileNotFoundError:
            return {
                "task_id": task_id,
                "found": False,
                "schema": "nexus.prov/v1",
                "error": f"task not found: {task_id}",
            }

        events = self.events(task_id)
        explained = self.explain(task_id)
        cost_sum = self.cost(task_id)

        # --- agents (PROV Agent) ---
        agents_map: dict[str, dict[str, Any]] = {}
        for e in events:
            name = str(e.get("agent") or "").strip()
            if not name:
                continue
            row = agents_map.setdefault(
                name,
                {
                    "id": name,
                    "type": "agent",
                    "steps": [],
                    "vendor": self.panel.vendor_of.get(name, "unknown"),
                    "tokens": 0,
                },
            )
            sn = e.get("step")
            if sn is not None and int(sn) not in row["steps"]:
                row["steps"].append(int(sn))
            if e.get("event") == "step_complete" and e.get("tokens") is not None:
                try:
                    row["tokens"] += int(e.get("tokens") or 0)
                except (TypeError, ValueError):
                    pass
        for h in explained.get("handoffs") or []:
            for key in ("from_agent", "to_agent"):
                name = str(h.get(key) or "").strip()
                if name and name not in agents_map:
                    agents_map[name] = {
                        "id": name,
                        "type": "agent",
                        "steps": [],
                        "vendor": self.panel.vendor_of.get(name, "unknown"),
                        "tokens": 0,
                    }

        # --- activities (PROV Activity = pipeline steps) ---
        activities: list[dict[str, Any]] = []
        act_ids: list[str] = []
        for s in explained.get("steps") or []:
            sn = int(s.get("step") or 0)
            act_id = f"act-{sn}"
            act_ids.append(act_id)
            activities.append(
                {
                    "id": act_id,
                    "type": "activity",
                    "step": sn,
                    "name": s.get("name") or "",
                    "agent": s.get("agent") or "",
                    "decision": s.get("decision") or "",
                    "score": s.get("score"),
                    "tokens": s.get("tokens"),
                    "why": (s.get("why") or "")[:200],
                }
            )
        # include veto/fail terminal activities not already in step_complete
        for v in explained.get("vetoes") or []:
            sn = v.get("step")
            if sn is None:
                continue
            act_id = f"act-{int(sn)}"
            if act_id not in act_ids:
                act_ids.append(act_id)
                activities.append(
                    {
                        "id": act_id,
                        "type": "activity",
                        "step": int(sn),
                        "name": "review",
                        "agent": v.get("agent") or "",
                        "decision": "veto",
                        "score": None,
                        "tokens": None,
                        "why": str(v.get("verdict") or "")[:200],
                    }
                )

        # --- entities (PROV Entity) ---
        task_entity_id = f"task:{task.task_id}"
        entities: list[dict[str, Any]] = [
            {
                "id": task_entity_id,
                "type": "task",
                "objective": task.objective,
                "status": task.status.value,
                "current_step": task.current_step,
                "namespace": task.namespace,
            }
        ]
        art_path = task.meta.get("_artifact_path") or ""
        art_id = ""
        if art_path:
            art_id = f"artifact:{Path(str(art_path)).name}"
            entities.append(
                {
                    "id": art_id,
                    "type": "artifact",
                    "path": str(art_path),
                }
            )
        # journal as durable entity
        journal_path = self._events_path(task_id)
        if journal_path.is_file():
            entities.append(
                {
                    "id": f"journal:{task.task_id}",
                    "type": "journal",
                    "path": str(journal_path),
                    "n_events": len(events),
                }
            )

        # --- relations ---
        relations: list[dict[str, Any]] = []
        for act in activities:
            aid = act["id"]
            agent = act.get("agent") or ""
            if agent:
                relations.append(
                    {
                        "type": "wasAssociatedWith",
                        "activity": aid,
                        "agent": agent,
                    }
                )
            relations.append(
                {
                    "type": "used",
                    "activity": aid,
                    "entity": task_entity_id,
                }
            )
            if art_id and (act.get("name") in {"implement", "test", "review"} or act.get("decision")):
                relations.append(
                    {
                        "type": "generated",
                        "activity": aid,
                        "entity": art_id,
                    }
                )
        # sequential wasInformedBy (activity chain)
        for i in range(1, len(act_ids)):
            relations.append(
                {
                    "type": "wasInformedBy",
                    "activity": act_ids[i],
                    "informed_by": act_ids[i - 1],
                }
            )
        # handoffs as wasDerivedFrom control transfer
        for h in explained.get("handoffs") or []:
            relations.append(
                {
                    "type": "wasDerivedFrom",
                    "agent": h.get("to_agent") or "",
                    "derived_from": h.get("from_agent") or "",
                    "step": h.get("step"),
                    "kind": "handoff",
                }
            )

        # --- trust-log rows for this task (if present) ---
        trust_rows: list[dict[str, Any]] = []
        try:
            trust_path = self.settings.state_dir / "trust.json"
            if trust_path.is_file():
                raw = json.loads(trust_path.read_text(encoding="utf-8"))
                for p in raw.get("provenance") or []:
                    if str(p.get("task_id") or "") == task.task_id:
                        trust_rows.append(p)
                for v in raw.get("verdicts") or []:
                    if str(v.get("task_id") or "") == task.task_id:
                        trust_rows.append({"kind": "verdict", **v})
        except Exception:
            trust_rows = []

        return {
            "task_id": task.task_id,
            "found": True,
            "schema": "nexus.prov/v1",
            "status": task.status.value,
            "current_step": task.current_step,
            "objective": task.objective,
            "agents": sorted(agents_map.values(), key=lambda a: a["id"]),
            "activities": activities,
            "entities": entities,
            "relations": relations,
            "handoffs": explained.get("handoffs") or [],
            "vetoes": explained.get("vetoes") or [],
            "failures": explained.get("failures") or [],
            "trust": trust_rows,
            "story": explained.get("story") or "",
            "cost": {
                "total_tokens": cost_sum.get("total_tokens", 0),
                "avg_score": cost_sum.get("avg_score"),
                "by_agent": cost_sum.get("by_agent") or {},
                "thresholds": cost_sum.get("thresholds") or decision_thresholds(),
            },
            "n_events": len(events),
        }

    def verify(self, task_id: str) -> dict[str, Any]:
        """Checkpoint ↔ journal integrity checks (fault-tolerant durability).

        Detects partial writes, missing journals, step/status drift, and
        token meta mismatches. Read-only; returns ``ok`` plus structured
        ``issues`` (severity: error|warn) and a ``checks`` map.
        """
        issues: list[dict[str, str]] = []
        checks: dict[str, bool] = {}

        path = self._task_path(task_id)
        if not path.is_file():
            return {
                "task_id": task_id,
                "found": False,
                "ok": False,
                "error": f"task not found: {task_id}",
                "issues": [{"severity": "error", "code": "no_checkpoint", "msg": f"missing {path}"}],
                "checks": {"checkpoint_exists": False},
            }

        try:
            task = self.load(task_id)
            checks["checkpoint_parseable"] = True
        except Exception as e:
            return {
                "task_id": task_id,
                "found": True,
                "ok": False,
                "error": f"checkpoint corrupt: {e}",
                "issues": [
                    {
                        "severity": "error",
                        "code": "checkpoint_corrupt",
                        "msg": str(e),
                    }
                ],
                "checks": {"checkpoint_exists": True, "checkpoint_parseable": False},
            }

        checks["checkpoint_exists"] = True
        jpath = self._events_path(task_id)
        journal_exists = jpath.is_file()
        checks["journal_exists"] = journal_exists

        events: list[dict[str, Any]] = []
        if journal_exists:
            try:
                events = self.events(task_id)
                checks["journal_parseable"] = True
            except Exception as e:
                checks["journal_parseable"] = False
                issues.append(
                    {
                        "severity": "error",
                        "code": "journal_corrupt",
                        "msg": str(e),
                    }
                )
        else:
            checks["journal_parseable"] = False
            if task.current_step > 0 or task.status != TaskStatus.pending:
                issues.append(
                    {
                        "severity": "error",
                        "code": "journal_missing",
                        "msg": f"no journal at {jpath} but status={task.status.value} step={task.current_step}",
                    }
                )
            else:
                issues.append(
                    {
                        "severity": "warn",
                        "code": "journal_missing",
                        "msg": f"no journal yet for pending task ({jpath})",
                    }
                )

        # Max step_complete vs checkpoint current_step
        complete_steps = [
            int(e["step"])
            for e in events
            if e.get("event") == "step_complete" and e.get("step") is not None
        ]
        max_complete = max(complete_steps) if complete_steps else 0
        checks["step_alignment"] = True
        if complete_steps and max_complete > task.current_step:
            checks["step_alignment"] = False
            issues.append(
                {
                    "severity": "error",
                    "code": "step_ahead",
                    "msg": (
                        f"journal max step_complete={max_complete} > "
                        f"checkpoint current_step={task.current_step}"
                    ),
                }
            )
        elif (
            task.current_step > 0
            and complete_steps
            and max_complete < task.current_step
            and task.status
            not in (TaskStatus.waiting_human, TaskStatus.failed)
        ):
            # waiting_human may pause before step_complete; failed may veto mid-step
            checks["step_alignment"] = False
            issues.append(
                {
                    "severity": "warn",
                    "code": "step_behind",
                    "msg": (
                        f"journal max step_complete={max_complete} < "
                        f"checkpoint current_step={task.current_step}"
                    ),
                }
            )
        elif task.current_step > 0 and not complete_steps and journal_exists:
            checks["step_alignment"] = False
            issues.append(
                {
                    "severity": "warn",
                    "code": "no_step_complete",
                    "msg": f"checkpoint at step {task.current_step} but no step_complete in journal",
                }
            )

        # Terminal status consistency
        event_names = {str(e.get("event") or "") for e in events}
        checks["status_alignment"] = True
        if task.status == TaskStatus.completed:
            if "completed" not in event_names:
                checks["status_alignment"] = False
                issues.append(
                    {
                        "severity": "error",
                        "code": "missing_completed_event",
                        "msg": "status=completed but journal has no completed event",
                    }
                )
        elif task.status == TaskStatus.failed:
            if "failed" not in event_names and "veto" not in event_names:
                checks["status_alignment"] = False
                issues.append(
                    {
                        "severity": "error",
                        "code": "missing_failed_event",
                        "msg": "status=failed but journal has no failed/veto event",
                    }
                )
        elif task.status == TaskStatus.waiting_human:
            if "waiting_human" not in event_names:
                checks["status_alignment"] = False
                issues.append(
                    {
                        "severity": "warn",
                        "code": "missing_waiting_event",
                        "msg": "status=waiting_human but journal has no waiting_human event",
                    }
                )

        # last_agent consistency
        checks["agent_alignment"] = True
        meta_agent = str(task.meta.get("last_agent") or "")
        last_complete_agent = ""
        for e in reversed(events):
            if e.get("event") == "step_complete" and e.get("agent"):
                last_complete_agent = str(e.get("agent") or "")
                break
        if meta_agent and last_complete_agent and meta_agent != last_complete_agent:
            checks["agent_alignment"] = False
            issues.append(
                {
                    "severity": "warn",
                    "code": "agent_mismatch",
                    "msg": (
                        f"meta.last_agent={meta_agent!r} != "
                        f"last step_complete agent={last_complete_agent!r}"
                    ),
                }
            )

        # token meta vs journal sum
        checks["token_alignment"] = True
        journal_tokens = 0
        for e in events:
            if e.get("event") == "step_complete" and e.get("tokens") is not None:
                try:
                    journal_tokens += int(e.get("tokens") or 0)
                except (TypeError, ValueError):
                    pass
        meta_tokens = int(task.meta.get("tokens_total") or 0)
        if journal_tokens and meta_tokens and journal_tokens != meta_tokens:
            # allow small drift only if equal; any mismatch is a warn
            checks["token_alignment"] = False
            issues.append(
                {
                    "severity": "warn",
                    "code": "token_mismatch",
                    "msg": (
                        f"meta.tokens_total={meta_tokens} != "
                        f"journal step_complete sum={journal_tokens}"
                    ),
                }
            )

        # outputs keys should not exceed current_step
        checks["outputs_bounded"] = True
        for k in (task.outputs or {}):
            try:
                if int(k) > task.current_step and task.status != TaskStatus.waiting_human:
                    checks["outputs_bounded"] = False
                    issues.append(
                        {
                            "severity": "warn",
                            "code": "output_ahead",
                            "msg": f"output for step {k} but current_step={task.current_step}",
                        }
                    )
            except (TypeError, ValueError):
                continue

        n_errors = sum(1 for i in issues if i.get("severity") == "error")
        n_warns = sum(1 for i in issues if i.get("severity") == "warn")
        ok = n_errors == 0
        return {
            "task_id": task.task_id,
            "found": True,
            "ok": ok,
            "status": task.status.value,
            "current_step": task.current_step,
            "n_events": len(events),
            "n_errors": n_errors,
            "n_warns": n_warns,
            "issues": issues,
            "checks": checks,
            "journal_tokens": journal_tokens,
            "meta_tokens": meta_tokens,
            "max_step_complete": max_complete,
        }

    def dag(self, task_id: str) -> dict[str, Any]:
        """Multi-agent task dependency DAG snapshot (open-multi-agent plan shape).

        Distinct from ``graph()`` (agent handoff call-graph): this exports the
        **policy** step DAG with completed/ready/blocked status, explicit
        ``action_order`` (AOAD-MAT), and mermaid for operator paste.

        Schema: ``nexus.dag/v1``.
        """
        try:
            task = self.load(task_id)
        except FileNotFoundError:
            return {
                "task_id": task_id,
                "found": False,
                "schema": "nexus.dag/v1",
                "error": f"task not found: {task_id}",
            }
        done = completed_set(task.outputs, current_step=task.current_step)
        order = [str(x) for x in (task.meta.get("action_order") or []) if x is not None]
        if not order:
            # Reconstruct from journal step_complete order when meta missing
            for e in self.events(task_id):
                if e.get("event") != "step_complete":
                    continue
                sn = e.get("step")
                name = e.get("detail") or ""
                if sn is not None:
                    order.append(f"{sn}:{name}" if name else str(sn))
        snap = self.policy.dag_snapshot(
            completed=done,
            current_step=task.current_step,
            action_order=order,
        )
        snap.update(
            {
                "task_id": task.task_id,
                "found": True,
                "status": task.status.value,
                "current_step": task.current_step,
                "objective": task.objective,
            }
        )
        return snap

    def consensus(self, task_id: str) -> dict[str, Any]:
        """Multi-grader consensus export (gossipcat findings + trust weights).

        Collects journal ``consensus`` events and step ``_verdict`` findings
        into a single operator pack (``nexus.consensus/v1``).
        """
        try:
            task = self.load(task_id)
        except FileNotFoundError:
            return {
                "task_id": task_id,
                "found": False,
                "schema": CONSENSUS_SCHEMA,
                "error": f"task not found: {task_id}",
            }
        events = [
            e for e in self.events(task_id) if e.get("event") == "consensus"
        ]
        rounds: list[dict[str, Any]] = []
        for e in events:
            rounds.append(
                {
                    "step": e.get("step"),
                    "detail": e.get("detail"),
                    "decision": e.get("decision"),
                    "score": e.get("score"),
                    "agreement_ratio": e.get("agreement_ratio"),
                    "n_graders": e.get("n_graders"),
                    "counts": e.get("counts") or {},
                    "graders": e.get("graders") or [],
                    "degraded": e.get("degraded"),
                    "ts": e.get("ts"),
                }
            )
        # Also harvest findings from step outputs when present
        step_findings: list[dict[str, Any]] = []
        for sn, out in sorted(task.outputs.items(), key=lambda x: int(x[0])):
            if not isinstance(out, dict):
                continue
            v = out.get("_verdict") or {}
            if not isinstance(v, dict):
                continue
            findings = v.get("findings")
            if not findings:
                continue
            step_findings.append(
                {
                    "step": int(sn),
                    "decision": v.get("decision"),
                    "score": v.get("score"),
                    "agreement_ratio": v.get("agreement_ratio"),
                    "n_graders": v.get("n_graders"),
                    "counts": v.get("counts") or {},
                    "findings": findings,
                    "degraded": v.get("degraded"),
                }
            )
        n_agree = sum(
            int((r.get("counts") or {}).get("agreement") or 0) for r in rounds
        )
        n_dis = sum(
            int((r.get("counts") or {}).get("disagreement") or 0) for r in rounds
        )
        avg_agree = None
        if rounds:
            vals = [
                float(r["agreement_ratio"])
                for r in rounds
                if r.get("agreement_ratio") is not None
            ]
            if vals:
                avg_agree = round(sum(vals) / len(vals), 4)
        trust_weights: dict[str, float] = {}
        judge = getattr(self, "judge", None)
        if judge is not None and hasattr(judge, "trust"):
            try:
                trust_weights = judge.trust.to_dict()
            except Exception:
                trust_weights = {}
        return {
            "schema": CONSENSUS_SCHEMA,
            "task_id": task.task_id,
            "found": True,
            "status": task.status.value,
            "current_step": task.current_step,
            "objective": task.objective,
            "n_rounds": len(rounds),
            "rounds": rounds,
            "step_findings": step_findings,
            "totals": {
                "agreement": n_agree,
                "disagreement": n_dis,
                "avg_agreement_ratio": avg_agree,
            },
            "trust_weights": trust_weights,
            "enabled": bool(getattr(self.settings, "consensus_judge", True)),
        }

    def graph(self, task_id: str) -> dict[str, Any]:
        """Agent call-graph + space-time sequence from the journal (MAS profiling).

        Read-only export inspired by call-graph / space-time diagram papers and
        routa/mission-control trace boards:

        - **nodes** — agents with step counts + token spend
        - **edges** — handoff edges (from→to) with multiplicity
        - **sequence** — ordered (step, agent, event) space-time spine
        - **mermaid** — compact flowchart string for docs/dashboards
        """
        try:
            task = self.load(task_id)
        except FileNotFoundError:
            return {
                "task_id": task_id,
                "found": False,
                "schema": "nexus.graph/v1",
                "error": f"task not found: {task_id}",
            }

        events = self.events(task_id)
        nodes: dict[str, dict[str, Any]] = {}
        edge_counts: dict[tuple[str, str], int] = {}
        sequence: list[dict[str, Any]] = []

        def _node(name: str) -> dict[str, Any]:
            row = nodes.setdefault(
                name,
                {
                    "id": name,
                    "type": "agent",
                    "vendor": self.panel.vendor_of.get(name, "unknown"),
                    "steps": [],
                    "n_starts": 0,
                    "n_completes": 0,
                    "tokens": 0,
                },
            )
            return row

        for e in events:
            ev = str(e.get("event") or "")
            agent = str(e.get("agent") or "").strip()
            sn = e.get("step")
            sn_i = int(sn) if sn is not None else None

            if ev == "handoff":
                src = str(e.get("from_agent") or "").strip()
                dst = str(e.get("to_agent") or agent).strip()
                if src:
                    _node(src)
                if dst:
                    _node(dst)
                if src and dst:
                    edge_counts[(src, dst)] = edge_counts.get((src, dst), 0) + 1
                sequence.append(
                    {
                        "event": "handoff",
                        "step": sn_i,
                        "from_agent": src,
                        "to_agent": dst,
                        "ts": e.get("ts"),
                    }
                )
                continue

            if agent:
                node = _node(agent)
                if sn_i is not None and sn_i not in node["steps"]:
                    node["steps"].append(sn_i)
                if ev == "step_start":
                    node["n_starts"] += 1
                    sequence.append(
                        {
                            "event": "step_start",
                            "step": sn_i,
                            "agent": agent,
                            "name": e.get("detail") or "",
                            "ts": e.get("ts"),
                        }
                    )
                elif ev == "step_complete":
                    node["n_completes"] += 1
                    try:
                        node["tokens"] += int(e.get("tokens") or 0)
                    except (TypeError, ValueError):
                        pass
                    sequence.append(
                        {
                            "event": "step_complete",
                            "step": sn_i,
                            "agent": agent,
                            "name": e.get("detail") or "",
                            "decision": e.get("decision") or "",
                            "tokens": e.get("tokens"),
                            "score": e.get("score"),
                            "ts": e.get("ts"),
                        }
                    )
                elif ev in {"budget", "veto", "failed", "waiting_human", "completed"}:
                    sequence.append(
                        {
                            "event": ev,
                            "step": sn_i,
                            "agent": agent,
                            "detail": e.get("detail") or "",
                            "ts": e.get("ts"),
                        }
                    )
            elif ev in {"budget", "failed", "completed", "status", "resume", "checkpoint"}:
                sequence.append(
                    {
                        "event": ev,
                        "step": sn_i,
                        "agent": "",
                        "detail": e.get("detail") or "",
                        "ts": e.get("ts"),
                    }
                )

        edges = [
            {
                "from": a,
                "to": b,
                "count": c,
                "kind": "handoff",
            }
            for (a, b), c in sorted(edge_counts.items(), key=lambda x: (-x[1], x[0][0], x[0][1]))
        ]

        # Mermaid flowchart for quick operator paste
        mermaid_lines = ["flowchart LR"]
        if not nodes and not edges:
            mermaid_lines.append("  empty[no agents yet]")
        else:
            for n in sorted(nodes.values(), key=lambda x: x["id"]):
                safe = n["id"].replace('"', "")
                label = f'{safe}\\ntok={n["tokens"]} steps={len(n["steps"])}'
                mermaid_lines.append(f'  {safe}["{label}"]')
            for e in edges:
                frm = str(e["from"]).replace('"', "")
                to = str(e["to"]).replace('"', "")
                cnt = e["count"]
                arrow = f"|x{cnt}|" if cnt > 1 else ""
                mermaid_lines.append(f"  {frm} -->{arrow} {to}")
        mermaid = "\n".join(mermaid_lines)

        cost_sum = self.cost(task_id)
        return {
            "task_id": task.task_id,
            "found": True,
            "schema": "nexus.graph/v1",
            "status": task.status.value,
            "current_step": task.current_step,
            "objective": task.objective,
            "nodes": sorted(nodes.values(), key=lambda x: x["id"]),
            "edges": edges,
            "sequence": sequence,
            "n_handoffs": sum(e["count"] for e in edges),
            "n_agents": len(nodes),
            "mermaid": mermaid,
            "cost": {
                "total_tokens": cost_sum.get("total_tokens", 0),
                "max_tokens": cost_sum.get("max_tokens"),
                "remaining_tokens": cost_sum.get("remaining_tokens"),
                "budget_exhausted": cost_sum.get("budget_exhausted", False),
                "by_agent": cost_sum.get("by_agent") or {},
            },
            "n_events": len(events),
        }

    def evidence(
        self,
        task_id: str,
        *,
        compact: bool = False,
        timeline_limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """Unified portable evidence pack for a task (routa / mission-control export).

        Read-only composition of checkpoint, norms, timeline, explain, cost,
        provenance, verify, and call-graph — one document for delivery boards,
        eval harnesses, and post-hoc audit (AssetOpsBench evidence shape).

        When *compact* is True, omits full provenance relations and graph
        sequence (keeps summaries + readiness gates).
        """
        try:
            task = self.load(task_id)
        except FileNotFoundError:
            return {
                "task_id": task_id,
                "found": False,
                "schema": "nexus.evidence/v1",
                "error": f"task not found: {task_id}",
            }

        explained = self.explain(task_id)
        cost_sum = self.cost(task_id)
        verified = self.verify(task_id)
        graph_doc = self.graph(task_id)
        norms = task_norms(task)
        timeline = self.replay(task_id, limit=timeline_limit)

        # Full vs compact slices
        if compact:
            prov = self.provenance(task_id)
            provenance_brief = {
                "schema": prov.get("schema"),
                "n_agents": len(prov.get("agents") or []),
                "n_activities": len(prov.get("activities") or []),
                "n_entities": len(prov.get("entities") or []),
                "n_relations": len(prov.get("relations") or []),
                "n_handoffs": len(prov.get("handoffs") or []),
                "story": prov.get("story"),
            }
            graph_brief = {
                "schema": graph_doc.get("schema"),
                "n_agents": graph_doc.get("n_agents", 0),
                "n_handoffs": graph_doc.get("n_handoffs", 0),
                "n_events": graph_doc.get("n_events", 0),
                "mermaid": graph_doc.get("mermaid"),
                "nodes": [
                    {
                        "id": n.get("id"),
                        "vendor": n.get("vendor"),
                        "tokens": n.get("tokens", 0),
                        "n_completes": n.get("n_completes", 0),
                    }
                    for n in (graph_doc.get("nodes") or [])
                ],
                "edges": graph_doc.get("edges") or [],
            }
            provenance_out: Any = provenance_brief
            graph_out: Any = graph_brief
        else:
            provenance_out = self.provenance(task_id)
            graph_out = graph_doc

        # Delivery / readiness gates (routa Entrix-inspired hard checks)
        status = task.status.value
        terminal = status in (TaskStatus.completed.value, TaskStatus.failed.value)
        integrity_ok = bool(verified.get("ok"))
        budget_exhausted = bool(
            cost_sum.get("budget_exhausted") or task.meta.get("budget_exhausted")
        )
        budget_ok = not budget_exhausted
        has_timeline = len(timeline) > 0
        n_vetoes = len(explained.get("vetoes") or [])
        n_failures = len(explained.get("failures") or [])
        completed = status == TaskStatus.completed.value
        waiting_human = status == TaskStatus.waiting_human.value
        # P9: norms_ok — no recorded violation; when enforce on, also require gaps empty
        norm_violation = task.meta.get("norm_violation")
        require_gaps = (
            norm_require_gaps(task, policy=self.policy) if task_enforce_norms(task) else []
        )
        norms_ok = not bool(norm_violation) and not require_gaps
        # Ready to treat as delivered evidence: completed + integrity + budget + norms
        ready = bool(
            completed
            and integrity_ok
            and budget_ok
            and has_timeline
            and not waiting_human
            and norms_ok
        )
        gates = {
            "integrity_ok": integrity_ok,
            "budget_ok": budget_ok,
            "has_timeline": has_timeline,
            "terminal": terminal,
            "completed": completed,
            "no_veto": n_vetoes == 0,
            "not_waiting_human": not waiting_human,
            "norms_ok": norms_ok,
            "ready": ready,
        }
        gate_failures = [k for k, v in gates.items() if k != "ready" and not v]

        task_brief = {
            "task_id": task.task_id,
            "status": status,
            "current_step": task.current_step,
            "objective": task.objective,
            "success_criteria": list(task.success_criteria or []),
            "namespace": task.namespace,
            "constraints": list(task.constraints or []),
            "last_agent": task.meta.get("last_agent") or "",
            "error": task.meta.get("error"),
            "tokens_total": int(task.meta.get("tokens_total") or 0),
            "max_tokens": task_max_tokens(task),
            "max_wall_s": task_max_wall_s(task),
            "elapsed_s": cost_sum.get("elapsed_s"),
            "budget_exhausted": budget_exhausted,
            "wall_exhausted": bool(cost_sum.get("wall_exhausted") or task.meta.get("wall_exhausted")),
            "waiting_step": task.meta.get("waiting_step"),
            "started_at": task.meta.get("started_at"),
            "completed_at": task.meta.get("completed_at"),
        }

        explain_brief = {
            "story": explained.get("story"),
            "status": explained.get("status"),
            "n_events": explained.get("n_events"),
            "handoffs": explained.get("handoffs") or [],
            "vetoes": explained.get("vetoes") or [],
            "failures": explained.get("failures") or [],
            "steps": explained.get("steps") or [],
            "cost": explained.get("cost") or {},
            "error": explained.get("error"),
            "last_agent": explained.get("last_agent") or "",
        }

        verify_brief = {
            "ok": verified.get("ok"),
            "n_errors": verified.get("n_errors", 0),
            "n_warns": verified.get("n_warns", 0),
            "issues": verified.get("issues") or [],
            "checks": verified.get("checks") or {},
            "journal_tokens": verified.get("journal_tokens"),
            "meta_tokens": verified.get("meta_tokens"),
        }

        cost_brief = {
            "total_tokens": cost_sum.get("total_tokens", 0),
            "avg_score": cost_sum.get("avg_score"),
            "request_count": cost_sum.get("request_count", 0),
            "max_tokens": cost_sum.get("max_tokens"),
            "remaining_tokens": cost_sum.get("remaining_tokens"),
            "max_wall_s": cost_sum.get("max_wall_s"),
            "elapsed_s": cost_sum.get("elapsed_s"),
            "remaining_wall_s": cost_sum.get("remaining_wall_s"),
            "wall_exhausted": cost_sum.get("wall_exhausted", False),
            "budget_exhausted": cost_sum.get("budget_exhausted", False),
            "by_agent": cost_sum.get("by_agent") or {},
            "thresholds": cost_sum.get("thresholds") or {},
        }

        return {
            "task_id": task.task_id,
            "found": True,
            "schema": "nexus.evidence/v1",
            "generated_at": time.time(),
            "compact": compact,
            "task": task_brief,
            "norms": norms,
            "gates": gates,
            "gate_failures": gate_failures,
            "ready": ready,
            "story": explained.get("story") or "",
            "explain": explain_brief,
            "cost": cost_brief,
            "verify": verify_brief,
            "timeline": timeline,
            "n_timeline": len(timeline),
            "provenance": provenance_out,
            "graph": graph_out,
            "n_vetoes": n_vetoes,
            "n_failures": n_failures,
        }
