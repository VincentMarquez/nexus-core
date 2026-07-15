"""Durable checkpointed task engine.

Checkpoints use atomic write-then-rename (Temporal / Durable Functions shape).
Each status/step transition also appends to an append-only JSONL event journal
(replay + audit; edict/MisterSmith-inspired, filesystem-only).
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
from .judge import RubricJudge
from .memory import MemorySpine
from .persist import append_jsonl, atomic_write_json, event_row, read_jsonl
from .steps import StepPolicy, structural_ok
from .trust import TrustLog


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
        return read_jsonl(self._events_path(task_id), limit=limit)

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
        for step in steps:
            if step.number <= task.current_step:
                continue
            if max_steps is not None and step.number > (start_step + max_steps):
                stopped_early = True
                break

            agent_name = self.panel.resolve(step)
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
            prompt = (
                f"Step {step.number} {step.name}: {step.description}\n"
                f"Objective: {task.objective}\n"
                f"Criteria: {task.success_criteria}\n"
                f"{ctx['cascade']}\n"
                f"Memory hits: {len(ctx['memory'])}\n"
            )

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
            if "artifacts" in output:
                task.meta["_artifact_path"] = (output["artifacts"] or [None])[0]
            self.save(task)
            self.record_event(
                task.task_id, "step_complete",
                step=step.number, agent=agent_name, status=task.status.value,
                detail=step.name,
                extra={"decision": getattr(verdict, "decision", "")},
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
                out.append(
                    {
                        "task_id": t.task_id,
                        "status": t.status.value,
                        "current_step": t.current_step,
                        "objective": t.objective[:120],
                        "events": len(self.events(t.task_id)) if self.journal else 0,
                    }
                )
            except Exception:
                continue
        return out
