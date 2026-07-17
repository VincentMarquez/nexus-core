"""Orchestration façade: async tasks with durable envelopes + OpsStore.

Design: docs/design/nexus-orchestration-mcp-server.md

Public API used by MCP:
  - run_task(...)
  - get_task_status(..., action=status|cancel|logs)
  - worker_main() for subprocess workers

task_id == ops job id == envelope filename stem.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .ops_store import (
    JOB_KINDS,
    JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    OpsError,
    OpsStore,
)

SCHEMA = "nexus.orchestrator/v1"
PUBLIC_KINDS = frozenset({"task", "research"})
AGENT_MODES = frozenset({"demo", "fake", "bus", "auto"})
_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")

# FutureWeaver (arxiv:2512.11213v2) multi-agent compute budget keys on meta
_COMPUTE_BUDGET_KEYS = frozenset(
    {
        "compute_budget",
        "budget_alloc",
        "total_tokens",
        "max_tokens",
        "budget_strategy",
        "budget_agents",
    }
)


class OrchError(RuntimeError):
    """Orchestrator client error (maps to MCP isError)."""

    def __init__(self, message: str, *, code: str = "orch_error"):
        super().__init__(message)
        self.code = code


def project_root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def orch_dir(root: Path) -> Path:
    d = root / ".nexus_state" / "orchestrator"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sanitize_task_id(raw: Optional[str] = None) -> str:
    if raw:
        tid = str(raw).strip()
        if not _ID_RE.match(tid):
            raise OrchError(
                f"invalid task_id: {raw!r} (use [a-zA-Z0-9._-] max 64)",
                code="invalid_id",
            )
        if ".." in tid or "/" in tid or "\\" in tid:
            raise OrchError(f"invalid task_id path chars: {raw!r}", code="invalid_id")
        return tid
    return f"task-{uuid.uuid4().hex[:12]}"


@dataclass
class Envelope:
    """On-disk job envelope (JSON under .nexus_state/orchestrator/)."""

    task_id: str
    kind: str
    goal: str
    status: str = "running"
    agent_mode: str = "demo"
    backend: str = "fake"
    cancel_requested: bool = False
    pid: Optional[int] = None
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    log_tail: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Envelope":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kw = {k: v for k, v in data.items() if k in known}
        kw.setdefault("meta", {})
        kw.setdefault("log_tail", [])
        return cls(**kw)


def _envelope_path(root: Path, task_id: str) -> Path:
    # Jail: only basename under orch dir
    safe = sanitize_task_id(task_id)
    return orch_dir(root) / f"{safe}.json"


def load_envelope(root: Path, task_id: str) -> Optional[Envelope]:
    p = _envelope_path(root, task_id)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return Envelope.from_dict(data)


def save_envelope(root: Path, env: Envelope) -> None:
    env.updated_at = time.time()
    p = _envelope_path(root, env.task_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(env.to_dict(), indent=2, default=str) + "\n", encoding="utf-8"
    )
    tmp.replace(p)


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_worker_pid(pid: Optional[int], *, grace_s: float = 10.0) -> None:
    """SIGTERM then SIGKILL. Not RuntimeManager (bus bridges only)."""
    if not pid or pid <= 0:
        return
    if not _pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + max(0.1, grace_s)
    while time.time() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


class Orchestrator:
    """High-level run_task / get_task_status façade."""

    def __init__(self, workdir: Optional[Path | str] = None):
        self.root = project_root(workdir)
        orch_dir(self.root)

    def _ops(self) -> OpsStore:
        return OpsStore.open(self.root)

    def run_task(
        self,
        description: str,
        *,
        kind: str = "task",
        agent_mode: str = "auto",
        task_id: Optional[str] = None,
        wait: bool = False,
        wait_timeout_s: float = 120.0,
        with_brief: bool = False,
        with_plan: bool = False,
        plan: Any = None,
        plan_tools: Optional[list[Any]] = None,
        plan_text: Optional[str] = None,
        plan_max_steps: int = 5,
        require_plan: bool = False,
        meta: Optional[dict[str, Any]] = None,
        sync_fake: bool = False,
    ) -> dict[str, Any]:
        """Start a task; returns status payload including task_id.

        When *with_plan* is True (arXiv 2401.07324), a dedicated Planner
        decomposes *description* into a structured tool plan **before** the
        Orchestrator spawns work. The plan is stored on envelope/ops meta and
        injected into the engine worker. Planner never executes tools.
        """
        goal = str(description or "").strip()
        if not goal:
            raise OrchError("description required", code="invalid_args")

        k = str(kind or "task").strip().lower()
        if k not in PUBLIC_KINDS:
            raise OrchError(
                f"invalid kind {kind!r}; allowed: {sorted(PUBLIC_KINDS)}",
                code="invalid_kind",
            )
        if k not in JOB_KINDS:
            raise OrchError(f"kind not in JOB_KINDS: {k}", code="invalid_kind")

        mode = str(agent_mode or "auto").strip().lower()
        if mode not in AGENT_MODES:
            raise OrchError(
                f"invalid agent_mode {agent_mode!r}; allowed: {sorted(AGENT_MODES)}",
                code="invalid_args",
            )
        if mode == "auto":
            mode = "demo"

        tid = sanitize_task_id(task_id)
        if load_envelope(self.root, tid) is not None:
            raise OrchError(f"task_id already exists: {tid}", code="already_exists")

        # ── Planner pre-phase (optional; arXiv 2401.07324) ────────────────
        plan_payload: Optional[dict[str, Any]] = None
        if with_plan or plan is not None:
            plan_payload = self._build_pre_plan(
                goal,
                plan=plan,
                plan_tools=plan_tools,
                plan_text=plan_text,
                plan_max_steps=plan_max_steps,
                require_plan=require_plan,
            )

        # ── Multi-agent compute budget (optional; arXiv 2512.11213v2) ─────
        budget_payload: Optional[dict[str, Any]] = None
        try:
            budget_payload = self._maybe_plan_compute_budget(meta)
        except Exception as e:
            raise OrchError(
                f"compute budget plan failed: {e}", code="budget_plan_failed"
            ) from e

        backend = "fake" if mode == "fake" else ("research" if k == "research" else "engine")
        env_meta: dict[str, Any] = {
            **(meta or {}),
            "with_brief": bool(with_brief),
            "with_plan": bool(with_plan or plan is not None),
            "schema": SCHEMA,
        }
        if plan_payload is not None:
            env_meta["tool_plan"] = plan_payload
            env_meta["pre_planned"] = True
            env_meta["planner_paper"] = plan_payload.get("paper") or "arxiv:2401.07324v3"
        if budget_payload is not None:
            env_meta["budget_alloc"] = budget_payload
            env_meta["compute_budget_planned"] = True
            env_meta["budget_paper"] = budget_payload.get("paper") or "arxiv:2512.11213v2"

        # ── Intermediate state cache (optional; arXiv 2601.22129v2 SWE-Replay) ─
        # Capture marketplace catalog / directory listings for selective replay.
        state_replay_payload: Optional[dict[str, Any]] = None
        try:
            from .state_replay import maybe_capture_for_task

            state_replay_payload = maybe_capture_for_task(
                self.root, tid, env_meta, step_id="init"
            )
        except Exception:
            state_replay_payload = None
        if state_replay_payload and state_replay_payload.get("ok"):
            env_meta["state_replay"] = True
            env_meta["state_replay_init"] = {
                "n_captured": state_replay_payload.get("n_captured"),
                "captured": state_replay_payload.get("captured"),
                "paper": state_replay_payload.get("paper"),
                "schema": state_replay_payload.get("schema"),
            }
            env_meta["state_replay_paper"] = "arxiv:2601.22129v2"

        # ── User Intent Model (optional; arXiv 2510.21903v2 ToM-SWE) ────────
        # Infer goals/constraints/preferences from instruction + history;
        # suggest marketplace agents/skills/commands (wshobson surfaces).
        user_intent_payload: Optional[dict[str, Any]] = None
        try:
            from .user_intent import maybe_infer_for_task

            user_intent_payload = maybe_infer_for_task(
                self.root, tid, goal, env_meta
            )
        except Exception:
            user_intent_payload = None
        if user_intent_payload and user_intent_payload.get("ok"):
            env_meta["user_intent"] = True
            env_meta["user_intent_init"] = {
                "intent_id": user_intent_payload.get("intent_id"),
                "confidence": user_intent_payload.get("confidence"),
                "is_ambiguous": user_intent_payload.get("is_ambiguous"),
                "n_suggestions": user_intent_payload.get("n_suggestions"),
                "goal_verbs": user_intent_payload.get("goal_verbs"),
                "ambiguity": user_intent_payload.get("ambiguity"),
                "paper": user_intent_payload.get("paper"),
                "schema": user_intent_payload.get("schema"),
            }
            env_meta["user_intent_paper"] = "arxiv:2510.21903v2"
            # Clarified instruction for the SWE agent (ToM partner output)
            clarified = str(
                user_intent_payload.get("clarified_instruction") or ""
            ).strip()
            if clarified:
                env_meta["clarified_goal"] = clarified
            top = user_intent_payload.get("top_suggestions") or []
            if top:
                env_meta["intent_suggestions"] = top

        env = Envelope(
            task_id=tid,
            kind=k,
            goal=goal,
            status="running",
            agent_mode=mode,
            backend=backend,
            meta=env_meta,
        )
        env.log_tail.append(f"created kind={k} mode={mode} backend={backend}")
        if plan_payload is not None:
            n = int(plan_payload.get("n_steps") or 0)
            env.log_tail.append(
                f"planner: ready={plan_payload.get('status') == 'ready'} "
                f"n_steps={n} planner={plan_payload.get('planner')}"
            )
            brief = str(plan_payload.get("brief") or "").strip()
            if brief:
                for line in brief.splitlines()[:12]:
                    env.log_tail.append(f"plan: {line}")
        if budget_payload is not None:
            env.log_tail.append(
                f"compute_budget: strategy={budget_payload.get('strategy')} "
                f"total={budget_payload.get('total_tokens')} "
                f"agents={len(budget_payload.get('agents') or {})} "
                f"paper={budget_payload.get('paper')}"
            )
        if state_replay_payload and state_replay_payload.get("ok"):
            env.log_tail.append(
                f"state_replay: captured={state_replay_payload.get('n_captured')} "
                f"paper={state_replay_payload.get('paper')}"
            )
        if user_intent_payload and user_intent_payload.get("ok"):
            env.log_tail.append(
                f"user_intent: conf={user_intent_payload.get('confidence')} "
                f"ambiguous={user_intent_payload.get('is_ambiguous')} "
                f"suggestions={user_intent_payload.get('n_suggestions')} "
                f"paper={user_intent_payload.get('paper')}"
            )

        ops_meta: dict[str, Any] = {
            "orchestrator": True,
            "agent_mode": mode,
            "backend": backend,
            "with_plan": bool(plan_payload is not None),
            "with_compute_budget": bool(budget_payload is not None),
            "with_state_replay": bool(
                state_replay_payload and state_replay_payload.get("ok")
            ),
            "with_user_intent": bool(
                user_intent_payload and user_intent_payload.get("ok")
            ),
        }
        if plan_payload is not None:
            ops_meta["tool_plan"] = {
                "n_steps": plan_payload.get("n_steps"),
                "status": plan_payload.get("status"),
                "planner": plan_payload.get("planner"),
                "paper": plan_payload.get("paper"),
                "steps": [
                    {"id": s.get("id"), "tool": s.get("tool")}
                    for s in (plan_payload.get("steps") or [])[:20]
                    if isinstance(s, dict)
                ],
            }
        if budget_payload is not None:
            # Full FutureWeaver snapshot on ops job (budget_plane hybrid);
            # keeps agent quotas durable for mission-control-style spend boards.
            ops_meta["budget_alloc"] = budget_payload
            ops_meta["budget_plane"] = True
            ops_meta["budget_paper"] = budget_payload.get("paper") or "arxiv:2512.11213v2"
            ops_meta["budget_schema"] = "nexus.budget_plane/v1"
        if state_replay_payload and state_replay_payload.get("ok"):
            # SWE-Replay intermediate states for selective test-time re-use.
            ops_meta["state_replay_init"] = env_meta.get("state_replay_init")
            ops_meta["state_replay_paper"] = "arxiv:2601.22129v2"
            ops_meta["state_replay_schema"] = "nexus.state_replay/v1"
        if user_intent_payload and user_intent_payload.get("ok"):
            # ToM-SWE user intent for clarified goals + marketplace routing.
            ops_meta["user_intent_init"] = env_meta.get("user_intent_init")
            ops_meta["user_intent_paper"] = "arxiv:2510.21903v2"
            ops_meta["user_intent_schema"] = "nexus.user_intent/v1"
            if env_meta.get("clarified_goal"):
                ops_meta["clarified_goal"] = env_meta.get("clarified_goal")
            if env_meta.get("intent_suggestions"):
                ops_meta["intent_suggestions"] = env_meta.get("intent_suggestions")

        with self._ops() as store:
            store.ensure_job(
                tid,
                kind=k,
                title=goal[:80] or tid,
                status="running",
                goal=goal,
                meta=ops_meta,
            )
            if budget_payload is not None:
                # Best-effort bind via budget_plane (SQLite control plane).
                try:
                    from .budget_alloc import BudgetAllocator
                    from .budget_plane import BudgetPlane

                    alloc = BudgetAllocator.from_dict(budget_payload)
                    BudgetPlane(store).bind(
                        tid,
                        alloc,
                        title=goal[:80] or tid,
                        goal=goal,
                        kind=k,
                        status="running",
                        extra_meta={
                            "orchestrator": True,
                            "with_compute_budget": True,
                        },
                    )
                except Exception:
                    pass

        save_envelope(self.root, env)

        # In-process fake for unit tests / instant path
        if backend == "fake" and (
            sync_fake or os.environ.get("NEXUS_ORCH_SYNC_FAKE", "").strip() == "1"
        ):
            self._run_fake(env)
            return self.get_task_status(tid)

        if backend == "fake" and wait:
            self._run_fake(env)
            return self.get_task_status(tid)

        # Subprocess worker for durable async work
        pid = self._spawn_worker(tid)
        env.pid = pid
        env.log_tail.append(f"spawned worker pid={pid}")
        save_envelope(self.root, env)

        if wait:
            self._wait_done(tid, timeout_s=min(float(wait_timeout_s), 300.0))
        return self.get_task_status(tid)

    def _maybe_plan_compute_budget(
        self, meta: Optional[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """Plan multi-agent compute pool when meta requests it (FutureWeaver).

        Triggers when meta contains any of:
        - ``compute_budget``: dict spec (total_tokens / strategy / agents / …)
        - ``budget_alloc``: already-planned allocator dict (pass-through)
        - ``budget_strategy`` + (``total_tokens`` | ``max_tokens``)
        """
        if not meta or not isinstance(meta, dict):
            return None
        # Already planned snapshot — validate shape lightly
        if isinstance(meta.get("budget_alloc"), dict) and meta["budget_alloc"].get(
            "agents"
        ) is not None:
            from .budget_alloc import BudgetAllocator

            return BudgetAllocator.from_dict(meta["budget_alloc"]).to_meta()

        spec: Optional[dict[str, Any]] = None
        if isinstance(meta.get("compute_budget"), dict):
            spec = dict(meta["compute_budget"])
        elif meta.get("budget_strategy") or meta.get("enable_budget_alloc"):
            total = meta.get("total_tokens", meta.get("max_tokens"))
            if total is None:
                return None
            spec = {
                "total_tokens": total,
                "strategy": meta.get("budget_strategy") or "weighted",
                "agents": meta.get("budget_agents"),
                "weights": meta.get("budget_weights"),
                "total_steps": meta.get("total_steps") or meta.get("max_steps"),
                "hard": meta.get("budget_hard", True),
            }
        if not spec:
            return None
        from .budget_alloc import BudgetAllocator, plan_for_orchestrator

        if spec.get("agents") is None and not spec.get("total_tokens") and not spec.get(
            "max_tokens"
        ):
            return None
        # Prefer plan_for_orchestrator defaults when agents omitted
        agents = spec.get("agents")
        total = int(spec.get("total_tokens") or spec.get("max_tokens") or 0)
        if total <= 0:
            raise ValueError("compute_budget.total_tokens must be > 0")
        alloc = plan_for_orchestrator(
            total_tokens=total,
            agents=agents,
            strategy=str(spec.get("strategy") or "weighted"),
            weights=spec.get("weights") if isinstance(spec.get("weights"), dict) else None,
            total_steps=spec.get("total_steps") or spec.get("max_steps"),
            hard=bool(spec.get("hard", True)),
            reserved_fraction=float(
                spec.get("reserved_fraction", 0.5)
            ),
        )
        # Keep a copy of the request spec for audit
        out = alloc.to_meta()
        out["request"] = {
            k: v
            for k, v in spec.items()
            if k in ("total_tokens", "max_tokens", "strategy", "agents", "hard")
        }
        return out

    def plan_compute_budget(
        self,
        *,
        total_tokens: int,
        agents: Optional[list[str]] = None,
        strategy: str = "weighted",
        weights: Optional[dict[str, float]] = None,
        total_steps: Optional[int] = None,
        hard: bool = True,
    ) -> dict[str, Any]:
        """Public helper: plan a multi-agent compute allocation (no task start)."""
        from .budget_alloc import format_brief, plan_for_orchestrator

        alloc = plan_for_orchestrator(
            total_tokens=int(total_tokens),
            agents=agents,
            strategy=strategy,
            weights=weights,
            total_steps=total_steps,
            hard=hard,
        )
        snap = alloc.snapshot()
        snap["brief"] = format_brief(alloc)
        return snap

    def get_compute_budget(self, task_id: str) -> dict[str, Any]:
        """Return current multi-agent compute allocation for a task."""
        from .budget_alloc import BudgetAllocator, format_brief

        tid = sanitize_task_id(task_id)
        env = load_envelope(self.root, tid)
        if env is None:
            raise OrchError(f"not found: {tid}", code="not_found")
        raw = (env.meta or {}).get("budget_alloc")
        if not isinstance(raw, dict):
            return {
                "schema": "nexus.budget_alloc/v1",
                "task_id": tid,
                "planned": False,
                "budget_alloc": None,
            }
        alloc = BudgetAllocator.from_dict(raw)
        snap = alloc.snapshot()
        return {
            "schema": snap["schema"],
            "task_id": tid,
            "planned": True,
            "budget_alloc": snap,
            "brief": format_brief(alloc),
        }

    def record_agent_usage(
        self,
        task_id: str,
        agent: str,
        *,
        tokens: int = 0,
        steps: int = 0,
        finish: bool = False,
        rebalance: bool = False,
    ) -> dict[str, Any]:
        """Accrue per-agent compute against the task's budget allocator.

        Fail-closed when the agent or pool would exceed its planned share
        (FutureWeaver hard limit). Persists updated allocation on the envelope.
        """
        from .budget_alloc import AllocationExhausted, BudgetAllocator, format_brief

        tid = sanitize_task_id(task_id)
        env = load_envelope(self.root, tid)
        if env is None:
            raise OrchError(f"not found: {tid}", code="not_found")
        raw = (env.meta or {}).get("budget_alloc")
        if not isinstance(raw, dict):
            raise OrchError(
                f"no compute budget planned for {tid}", code="no_budget_alloc"
            )
        alloc = BudgetAllocator.from_dict(raw)
        try:
            receipt = alloc.consume(agent, tokens=int(tokens or 0), steps=int(steps or 0))
        except AllocationExhausted as e:
            raise OrchError(str(e), code="budget_exhausted") from e
        finish_info = None
        rebalance_info = None
        if finish:
            finish_info = alloc.finish(agent, reclaim=True)
        if rebalance:
            rebalance_info = alloc.rebalance()
        env.meta = dict(env.meta or {})
        env.meta["budget_alloc"] = alloc.to_meta()
        env.log_tail.append(
            f"budget: agent={agent} +tok={tokens} +steps={steps} "
            f"rem={receipt.get('remaining_tokens')}"
            + (" finish" if finish else "")
            + (" rebalance" if rebalance else "")
        )
        save_envelope(self.root, env)
        # Best-effort: persist allocator + spend on SQLite budget plane
        # (FutureWeaver × mission-control hybrid).
        try:
            from .budget_plane import BudgetPlane

            with self._ops() as store:
                plane = BudgetPlane(store)
                try:
                    plane.load_alloc(tid)
                    plane._save_alloc(tid, alloc)  # noqa: SLF001 — same-process sync
                except Exception:
                    plane.bind(
                        tid,
                        alloc,
                        title=str((env.meta or {}).get("title") or tid),
                        goal=env.goal or "",
                        kind=env.kind or "task",
                        status=env.status or "running",
                        extra_meta={"orchestrator": True},
                    )
                if tokens:
                    store.record_spend(
                        tid,
                        tokens=int(tokens),
                        source=f"agent:{agent}",
                        label="budget_plane",
                        meta={
                            "agent": str(agent),
                            "schema": "nexus.budget_plane/v1",
                            "paper": "arxiv:2512.11213v2",
                        },
                    )
        except Exception:
            pass
        return {
            "schema": "nexus.budget_alloc/v1",
            "task_id": tid,
            "receipt": receipt,
            "finish": finish_info,
            "rebalance": rebalance_info,
            "budget_alloc": alloc.snapshot(),
            "brief": format_brief(alloc),
        }

    def _build_pre_plan(
        self,
        goal: str,
        *,
        plan: Any = None,
        plan_tools: Optional[list[Any]] = None,
        plan_text: Optional[str] = None,
        plan_max_steps: int = 5,
        require_plan: bool = False,
    ) -> dict[str, Any]:
        """Run dedicated Planner (or accept injected plan) before orchestration."""
        from . import multi_llm_agent as mla

        try:
            if plan is not None:
                if isinstance(plan, mla.ToolPlan):
                    tp = plan
                    if tp.status != mla.STATUS_READY and tp.steps:
                        mla.mark_ready(
                            tp,
                            allowed_tools=tp.tools_available or None,
                            require_steps=True,
                        )
                elif isinstance(plan, dict):
                    tp = mla.ToolPlan.from_dict(plan)
                    if not tp.task:
                        tp.task = goal
                    if tp.steps and tp.status != mla.STATUS_READY:
                        mla.mark_ready(
                            tp,
                            allowed_tools=tp.tools_available or None,
                            require_steps=bool(require_plan),
                        )
                elif isinstance(plan, str):
                    tp = mla.plan_for_orchestrator(
                        goal,
                        tools=plan_tools,
                        max_steps=int(plan_max_steps),
                        plan_text=plan,
                        auto_ready=True,
                    )
                else:
                    raise OrchError(
                        f"invalid plan type: {type(plan).__name__}",
                        code="invalid_plan",
                    )
            else:
                tp = mla.plan_for_orchestrator(
                    goal,
                    tools=plan_tools,
                    max_steps=int(plan_max_steps),
                    plan_text=plan_text,
                    auto_ready=True,
                )
        except mla.PlanError as e:
            if require_plan:
                raise OrchError(f"planner failed: {e}", code="plan_failed") from e
            # Soft path: empty draft payload for observability
            return {
                "schema": mla.SCHEMA,
                "paper": mla.PAPER,
                "task": goal,
                "status": mla.STATUS_FAILED,
                "planner": "error",
                "n_steps": 0,
                "steps": [],
                "notes": str(e),
                "brief": f"[planner error] {e}",
                "meta": {"handoff": "orchestrator", "error": str(e)},
            }

        if require_plan and not tp.is_ready():
            raise OrchError(
                "planner produced no ready plan (require_plan=true)",
                code="plan_not_ready",
            )
        return mla.plan_payload_for_meta(tp)

    def _spawn_worker(self, task_id: str) -> int:
        env = os.environ.copy()
        env["NEXUS_PROJECT_ROOT"] = str(self.root)
        env["PYTHONPATH"] = os.pathsep.join(
            [
                str(Path(__file__).resolve().parents[1]),
                env.get("PYTHONPATH", ""),
            ]
        ).strip(os.pathsep)
        cmd = [
            sys.executable,
            "-m",
            "nexus.orchestrator",
            "worker",
            "--task-id",
            task_id,
            "--root",
            str(self.root),
        ]
        log_path = orch_dir(self.root) / f"{task_id}.worker.log"
        log_f = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.root),
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return int(proc.pid)

    def _wait_done(self, task_id: str, *, timeout_s: float) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            st = self.get_task_status(task_id)
            if st.get("status") in TERMINAL_JOB_STATUSES:
                return
            time.sleep(0.15)
        # leave running; client can poll

    def _run_fake(self, env: Envelope) -> None:
        """Complete immediately (test / fake mode)."""
        if env.cancel_requested or env.status == "cancelled":
            return
        env.status = "completed"
        env.detail = "fake backend completed"
        env.log_tail.append("fake: completed")
        save_envelope(self.root, env)
        with self._ops() as store:
            try:
                store.set_status(env.task_id, "completed")
            except OpsError:
                pass

    def reap_if_needed(self, task_id: str) -> None:
        """If worker died without terminal status, mark failed (reaper)."""
        env = load_envelope(self.root, task_id)
        if env is None:
            return
        if env.status in TERMINAL_JOB_STATUSES:
            return
        if env.cancel_requested:
            self._force_status(env, "cancelled", "reaper: cancel_requested")
            return
        if env.pid and not _pid_alive(env.pid):
            # brief grace: worker may be exiting
            time.sleep(0.05)
            env2 = load_envelope(self.root, task_id)
            if env2 and env2.status not in TERMINAL_JOB_STATUSES:
                self._force_status(
                    env2, "failed", f"reaper: worker pid {env.pid} exited"
                )

    def _force_status(self, env: Envelope, status: str, detail: str) -> None:
        env.status = status
        env.detail = detail
        env.log_tail.append(detail)
        env.pid = None
        save_envelope(self.root, env)
        with self._ops() as store:
            try:
                store.set_status(env.task_id, status, force=False)
            except OpsError:
                pass

    def cancel(self, task_id: str) -> dict[str, Any]:
        tid = sanitize_task_id(task_id)
        env = load_envelope(self.root, tid)
        with self._ops() as store:
            job = store.get(tid)

        if env is None and job is None:
            raise OrchError(f"not found: {tid}", code="not_found")

        # Idempotent if already terminal
        cur = (env.status if env else None) or (job or {}).get("status")
        if cur in TERMINAL_JOB_STATUSES:
            return self.get_task_status(tid)

        if env is None:
            env = Envelope(
                task_id=tid,
                kind=str((job or {}).get("kind") or "task"),
                goal=str((job or {}).get("goal") or ""),
                status="cancelled",
                cancel_requested=True,
                detail="cancel without envelope",
            )
        else:
            env.cancel_requested = True
            env.status = "cancelled"
            env.detail = "cancelled by client"
            env.log_tail.append("cancel_requested")

        grace = float(os.environ.get("NEXUS_ORCH_CANCEL_GRACE_S") or 10)
        pid = env.pid
        kill_worker_pid(pid, grace_s=grace)
        env.pid = None
        save_envelope(self.root, env)

        with self._ops() as store:
            if store.get(tid) is None:
                store.ensure_job(
                    tid,
                    kind=env.kind if env.kind in JOB_KINDS else "task",
                    title=env.goal[:80] or tid,
                    status="cancelled",
                    goal=env.goal,
                    meta={"cancel_requested": True},
                )
            else:
                store.set_status(tid, "cancelled", force=False)
                store.ensure_job(tid, meta={"cancel_requested": True, "reason": "cancelled"})

        return self.get_task_status(tid)

    def get_task_status(
        self,
        task_id: str,
        *,
        action: str = "status",
        log_lines: int = 40,
    ) -> dict[str, Any]:
        action = str(action or "status").strip().lower()
        tid = sanitize_task_id(task_id)

        if action == "cancel":
            return self.cancel(tid)

        self.reap_if_needed(tid)
        env = load_envelope(self.root, tid)
        with self._ops() as store:
            job = store.get(tid)

        if env is None and job is None:
            # legacy best-effort (engine checkpoint only)
            legacy = self._legacy_lookup(tid)
            if legacy:
                legacy["legacy"] = True
                return legacy
            raise OrchError(f"not found: {tid}", code="not_found")

        status = (env.status if env else None) or (job or {}).get("status") or "running"
        # Prefer ops if terminal sticky won
        if job and job.get("status") in TERMINAL_JOB_STATUSES:
            status = job["status"]

        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "task_id": tid,
            "status": status,
            "kind": (env.kind if env else None) or (job or {}).get("kind"),
            "goal": (env.goal if env else None) or (job or {}).get("goal"),
            "detail": (env.detail if env else "") or "",
            "agent_mode": env.agent_mode if env else None,
            "backend": env.backend if env else None,
            "cancel_requested": bool(env.cancel_requested) if env else False,
            "pid": env.pid if env else None,
            "worker_alive": _pid_alive(env.pid) if env else False,
            "updated_at": (env.updated_at if env else None)
            or (job or {}).get("updated_at"),
            "ops": {
                "tokens": (job or {}).get("tokens"),
                "cost": (job or {}).get("cost"),
                "title": (job or {}).get("title"),
            }
            if job
            else None,
            "legacy": False,
        }
        # Surface Planner→Orchestrator handoff (arXiv 2401.07324)
        env_meta = (env.meta if env else None) or {}
        job_meta = (job or {}).get("meta") if job else None
        if not isinstance(job_meta, dict):
            job_meta = {}
        tool_plan = env_meta.get("tool_plan") or job_meta.get("tool_plan")
        if isinstance(tool_plan, dict) and tool_plan:
            payload["pre_planned"] = True
            payload["plan"] = tool_plan
            payload["plan_summary"] = {
                "n_steps": tool_plan.get("n_steps"),
                "status": tool_plan.get("status"),
                "planner": tool_plan.get("planner"),
                "paper": tool_plan.get("paper"),
                "tools": [
                    s.get("tool")
                    for s in (tool_plan.get("steps") or [])
                    if isinstance(s, dict) and s.get("tool")
                ],
            }
        else:
            payload["pre_planned"] = bool(
                env_meta.get("pre_planned") or env_meta.get("with_plan")
            )
        # Surface multi-agent compute budget (arXiv 2512.11213v2 FutureWeaver)
        budget_raw = env_meta.get("budget_alloc") or job_meta.get("budget_alloc")
        if isinstance(budget_raw, dict) and budget_raw:
            try:
                from .budget_alloc import BudgetAllocator, format_brief

                # Full allocator dict has agents map; ops may store a summary only
                if isinstance(budget_raw.get("agents"), dict):
                    alloc = BudgetAllocator.from_dict(budget_raw)
                    payload["compute_budget"] = alloc.snapshot()
                    payload["compute_budget_brief"] = format_brief(alloc)
                else:
                    payload["compute_budget"] = budget_raw
                payload["compute_budget_planned"] = True
            except Exception:
                payload["compute_budget"] = budget_raw
                payload["compute_budget_planned"] = True
        else:
            payload["compute_budget_planned"] = bool(
                env_meta.get("compute_budget_planned")
            )
        if action == "logs":
            n = max(1, min(int(log_lines or 40), 200))
            lines = list(env.log_tail if env else [])[-n:]
            log_path = orch_dir(self.root) / f"{tid}.worker.log"
            if log_path.is_file():
                try:
                    file_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    lines = (lines + file_lines)[-n:]
                except OSError:
                    pass
            payload["logs"] = lines
        return payload

    def _legacy_lookup(self, task_id: str) -> Optional[dict[str, Any]]:
        try:
            from .config import Settings
            from .engine import DurableEngine

            settings = Settings(state_dir=self.root / ".nexus_state")
            engine = DurableEngine(settings=settings, auto_approve=True)
            task = engine.load(task_id)
            return {
                "schema": SCHEMA,
                "task_id": task_id,
                "status": _map_engine_status(task.status.value),
                "kind": "task",
                "goal": task.objective,
                "detail": f"legacy engine checkpoint step={task.current_step}",
                "legacy": True,
            }
        except Exception:
            return None


def _map_engine_status(st: str) -> str:
    m = {
        "pending": "inbox",
        "running": "running",
        "waiting_human": "blocked",
        "completed": "completed",
        "failed": "failed",
    }
    return m.get(st, "running")


# ---------------------------------------------------------------------------
# Worker process
# ---------------------------------------------------------------------------


def worker_main(task_id: str, root: Optional[Path] = None) -> int:
    """Entry for ``python -m nexus.orchestrator worker``."""
    root = project_root(root)
    os.environ["NEXUS_PROJECT_ROOT"] = str(root)
    tid = sanitize_task_id(task_id)
    env = load_envelope(root, tid)
    if env is None:
        print(f"envelope missing: {tid}", file=sys.stderr)
        return 2

    def _cancelled() -> bool:
        e = load_envelope(root, tid)
        if e is None:
            return True
        if e.cancel_requested or e.status == "cancelled":
            return True
        try:
            with OpsStore.open(root) as store:
                job = store.get(tid)
                if job and job.get("status") == "cancelled":
                    return True
        except Exception:
            pass
        return False

    def _set(status: str, detail: str = "") -> None:
        e = load_envelope(root, tid) or env
        # K15/K16: refuse to write completed if cancelled
        if status == "completed" and (
            e.cancel_requested or e.status == "cancelled" or _cancelled()
        ):
            status = "cancelled"
            detail = detail or "completed suppressed; already cancelled"
        e.status = status
        e.detail = detail or e.detail
        e.log_tail.append(f"worker: {status} {detail}".strip())
        if status in TERMINAL_JOB_STATUSES:
            e.pid = None
        save_envelope(root, e)
        try:
            with OpsStore.open(root) as store:
                store.set_status(tid, status, force=False)
        except OpsError as ex:
            print(f"ops set_status: {ex}", file=sys.stderr)

    if _cancelled():
        _set("cancelled", "worker start aborted; cancelled")
        return 0

    try:
        if env.backend == "fake" or env.agent_mode == "fake":
            time.sleep(0.05)
            if _cancelled():
                _set("cancelled", "cancelled during fake")
                return 0
            _set("completed", "fake backend ok")
            return 0

        if env.kind == "research" or env.backend == "research":
            return _worker_research(root, env, _cancelled, _set)

        return _worker_engine(root, env, _cancelled, _set)
    except Exception as e:
        if _cancelled():
            _set("cancelled", f"cancelled after error: {e}")
            return 0
        _set("failed", f"{type(e).__name__}: {e}")
        return 1


def _worker_engine(root: Path, env: Envelope, _cancelled, _set) -> int:
    from .agents import AgentPanel
    from .config import Settings
    from .engine import DurableEngine, Task

    if _cancelled():
        _set("cancelled", "cancelled before engine")
        return 0

    settings = Settings(autonomy=False, state_dir=root / ".nexus_state")
    settings.ensure_dirs()
    # demo panel — no bus auto-start
    if env.agent_mode == "bus":
        try:
            panel = AgentPanel.from_bus()
        except Exception as e:
            _set("blocked", f"bus_down: {e}")
            return 0
    else:
        panel = AgentPanel.demo()

    engine = DurableEngine(
        settings=settings,
        panel=panel,
        auto_approve=True,
    )
    task = Task(
        task_id=env.task_id,
        objective=env.goal,
        success_criteria=["pipeline completes"],
        namespace=f"orch/{env.task_id}",
    )
    task.meta["orchestrator"] = True
    task.meta["cancel_check"] = True

    # Inject Planner pre-plan into engine (arXiv 2401.07324 multi-LLM split)
    tool_plan = (env.meta or {}).get("tool_plan")
    if isinstance(tool_plan, dict) and tool_plan:
        task.meta["tool_plan"] = tool_plan
        task.meta["pre_planned"] = True
        task.meta["planner_paper"] = tool_plan.get("paper") or "arxiv:2401.07324v3"
        brief = str(tool_plan.get("brief") or "").strip()
        if brief:
            # Keep objective readable; store brief for plan-stage agents
            task.meta["plan_brief"] = brief
            prior = str(task.meta.get("journal_seed") or "")
            task.meta["journal_seed"] = (
                (prior + "\n" if prior else "") + "PRE-PLAN (Planner→Orchestrator):\n" + brief
            )
        _set("running", f"engine with pre-plan n_steps={tool_plan.get('n_steps')}")

    # Inject multi-agent compute budget (arXiv 2512.11213v2 FutureWeaver)
    budget_alloc = (env.meta or {}).get("budget_alloc")
    if isinstance(budget_alloc, dict) and budget_alloc.get("agents") is not None:
        task.meta["budget_alloc"] = budget_alloc
        task.meta["budget_paper"] = budget_alloc.get("paper") or "arxiv:2512.11213v2"
        # Mirror total token cap onto task max_tokens for engine hard-stop
        total_tok = budget_alloc.get("total_tokens")
        if total_tok and not task.meta.get("max_tokens"):
            task.meta["max_tokens"] = int(total_tok)
        _set(
            "running",
            f"engine with compute_budget total={total_tok} "
            f"strategy={budget_alloc.get('strategy')}",
        )

    # Run with cooperative cancel between steps via max_steps loop
    # DurableEngine.run may take a while; check cancel before start
    if _cancelled():
        _set("cancelled", "cancelled before run")
        return 0

    try:
        # Optional step-budget from env for faster tests
        max_steps = os.environ.get("NEXUS_ORCH_MAX_STEPS")
        ms = int(max_steps) if max_steps else None
        result = engine.run(task, max_steps=ms)
    except Exception as e:
        if _cancelled():
            _set("cancelled", str(e))
            return 0
        _set("failed", f"engine: {e}")
        return 1

    if _cancelled():
        _set("cancelled", "cancelled after engine")
        return 0

    st = _map_engine_status(result.status.value)
    if st == "blocked":
        _set("blocked", "waiting_human or bus")
        return 0
    if st == "completed":
        _set("completed", f"engine step={result.current_step}")
        return 0
    if st == "failed":
        _set("failed", str(result.meta.get("error") or "engine failed"))
        return 1
    _set(st, f"engine status={result.status.value}")
    return 0 if st == "completed" else 1


def _worker_research(root: Path, env: Envelope, _cancelled, _set) -> int:
    from .research_job import ResearchJobRunner

    if _cancelled():
        _set("cancelled", "cancelled before research")
        return 0

    with_brief = bool((env.meta or {}).get("with_brief"))
    # K14: default False
    runner = ResearchJobRunner(
        project_root=root,
        state_dir=root / ".nexus_state" / "research_jobs",
    )
    try:
        out = runner.run(
            env.goal,
            with_brief=with_brief,
            job_id=env.task_id,
            download_pdf=False,
            max_results=5,
        )
    except Exception as e:
        if _cancelled():
            _set("cancelled", str(e))
            return 0
        _set("failed", f"research: {e}")
        return 1

    if _cancelled():
        _set("cancelled", "cancelled after research")
        return 0

    st = getattr(out, "status", None) or "completed"
    if st == "failed":
        _set("failed", "research job failed")
        return 1
    _set("completed", f"research ok with_brief={with_brief} status={st}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(prog="nexus.orchestrator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("worker", help="Run worker for a task envelope")
    w.add_argument("--task-id", required=True)
    w.add_argument("--root", default=None)

    r = sub.add_parser("run", help="CLI submit task")
    r.add_argument("description")
    r.add_argument("--kind", default="task")
    r.add_argument("--mode", default="fake")
    r.add_argument("--wait", action="store_true")
    r.add_argument("--root", default=None)

    s = sub.add_parser("status", help="Poll task")
    s.add_argument("task_id")
    s.add_argument("--root", default=None)

    c = sub.add_parser("cancel", help="Cancel task")
    c.add_argument("task_id")
    c.add_argument("--root", default=None)

    args = ap.parse_args(argv)
    if args.cmd == "worker":
        return worker_main(args.task_id, Path(args.root) if args.root else None)
    orch = Orchestrator(args.root)
    if args.cmd == "run":
        out = orch.run_task(
            args.description,
            kind=args.kind,
            agent_mode=args.mode,
            wait=args.wait,
            sync_fake=(args.mode == "fake"),
        )
        print(json.dumps(out, indent=2, default=str))
        return 0
    if args.cmd == "status":
        print(json.dumps(orch.get_task_status(args.task_id), indent=2, default=str))
        return 0
    if args.cmd == "cancel":
        print(json.dumps(orch.cancel(args.task_id), indent=2, default=str))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
