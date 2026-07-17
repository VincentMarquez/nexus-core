"""Control-plane-aware Planner: arXiv 2401.07324 × builderz-labs/mission-control.

Paper: *Small LLMs Are Weak Tool Learners: A Multi-LLM Agent*
https://arxiv.org/abs/2401.07324v3

GitHub pattern (shape only — not a vendored tree):
  builderz-labs/mission-control — self-hosted SQLite-backed AI agent control
  plane with task governance, spend tracking, sticky terminal statuses, and
  operator board surfaces (list / status / cost).

Novel hybrid (portfolio cross_pattern):

  ops plane tools (upsert_job / set_status / record_spend / list_jobs / …)
                │
                ▼
         ┌──────────┐   structured JSON plan
         │  Planner │ ──► steps = ordered governance ops
         └──────────┘   (small/offline role — no SQLite writes in plan())
                │
                ├── ready plan ──► Caller (execute against OpsStore)
                └── ready plan ──► Orchestrator.run_task (with_plan)
                                   + optional job row on the ops plane

Small specialized Planner decomposes complex tasks against the mission-control
shaped control-plane catalog *before* durable execution or spend writes.
Reuses in-tree ``ops_store`` + ``multi_llm_agent`` Planner/Caller.

Offline-first: heuristic Planner for tests/smoke; inject LLM JSON via plan_text.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import multi_llm_agent as mla
from . import ops_store as ops

SCHEMA = "nexus.control_plane_planner/v1"
PAPER = mla.PAPER  # arxiv:2401.07324v3
SOURCE_PATTERN = "builderz-labs/mission-control"

# Stable Planner tool ids (plane.* namespace — no collision with marketplace tools)
TOOL_UPSERT_JOB = "plane.upsert_job"
TOOL_SET_STATUS = "plane.set_status"
TOOL_RECORD_SPEND = "plane.record_spend"
TOOL_GET_JOB = "plane.get_job"
TOOL_LIST_JOBS = "plane.list_jobs"
TOOL_SPEND_REPORT = "plane.spend_report"

PLANE_TOOL_NAMES: tuple[str, ...] = (
    TOOL_UPSERT_JOB,
    TOOL_SET_STATUS,
    TOOL_RECORD_SPEND,
    TOOL_GET_JOB,
    TOOL_LIST_JOBS,
    TOOL_SPEND_REPORT,
)


class PlanePlanError(ValueError):
    """Control-plane catalog empty or plan invalid for plane handoff."""


# ── catalog: mission-control plane ops → Planner tools ──────────────────────


def control_plane_as_tools() -> list[dict[str, Any]]:
    """Build a Planner tool catalog from SQLite control-plane governance ops.

    Pattern only (mission-control task board + spend + sticky status). Each
    entry is structure-only until :func:`plan_and_govern` / Caller executes
    against an :class:`ops_store.OpsStore`.
    """
    return [
        {
            "name": TOOL_UPSERT_JOB,
            "description": (
                "Create or update a governed job on the SQLite control plane "
                "(inbox assignment, title, goal, kind). Mission-control task board."
            ),
            "privilege": "write",
            "plane": True,
            "source": SOURCE_PATTERN,
            "kind": "governance",
            "params": ["job_id", "kind", "title", "status", "goal"],
        },
        {
            "name": TOOL_SET_STATUS,
            "description": (
                "Update job status on the control plane with sticky terminal "
                "governance (inbox → running → blocked → completed/failed/cancelled)."
            ),
            "privilege": "write",
            "plane": True,
            "source": SOURCE_PATTERN,
            "kind": "governance",
            "params": ["job_id", "status", "force"],
        },
        {
            "name": TOOL_RECORD_SPEND,
            "description": (
                "Attribute token spend / cost to a governed job (mission-control "
                "task-costs). Roll up job tokens and cost."
            ),
            "privilege": "write",
            "plane": True,
            "source": SOURCE_PATTERN,
            "kind": "spend",
            "params": ["job_id", "tokens", "source", "label", "cost"],
        },
        {
            "name": TOOL_GET_JOB,
            "description": (
                "Inspect one job on the operator control plane "
                "(status, tokens, cost, meta)."
            ),
            "privilege": "read",
            "plane": True,
            "source": SOURCE_PATTERN,
            "kind": "inspect",
            "params": ["job_id"],
        },
        {
            "name": TOOL_LIST_JOBS,
            "description": (
                "List jobs on the SQLite control plane board filtered by kind "
                "or status (operator task board)."
            ),
            "privilege": "read",
            "plane": True,
            "source": SOURCE_PATTERN,
            "kind": "inspect",
            "params": ["kind", "status", "limit"],
        },
        {
            "name": TOOL_SPEND_REPORT,
            "description": (
                "Mission-control TaskCostReport lite: spend summary by job "
                "and source for operator governance."
            ),
            "privilege": "read",
            "plane": True,
            "source": SOURCE_PATTERN,
            "kind": "spend",
            "params": ["job_id", "limit"],
        },
    ]


def catalog_summary(tools: Optional[Sequence[dict[str, Any]]] = None) -> dict[str, Any]:
    """Compact catalog stats for plan meta / operator boards."""
    tools = list(tools) if tools is not None else control_plane_as_tools()
    by_kind: dict[str, int] = {}
    for t in tools:
        k = str(t.get("kind") or "other")
        by_kind[k] = by_kind.get(k, 0) + 1
    return {
        "n_tools": len(tools),
        "by_kind": dict(sorted(by_kind.items())),
        "names": [str(t.get("name") or "") for t in tools],
        "source_pattern": SOURCE_PATTERN,
    }


# ── lifecycle helper (deterministic governance walk) ────────────────────────


def lifecycle_plan(
    task: str,
    *,
    job_id: str = "",
    kind: str = "task",
    title: str = "",
    spend_tokens: int = 32,
    include_blocked: bool = True,
    include_report: bool = True,
    auto_ready: bool = True,
) -> mla.ToolPlan:
    """Deterministic mission-control governance lifecycle as a ready plan.

    Walks the ops plane shape::

        upsert(inbox) → set_status(running) → record_spend
        → [set_status(blocked)] → set_status(completed) → [spend_report]

    Useful when the task is explicitly about governance / lifecycle / spend
    (heuristic ranking alone may scatter steps). Planner still does not write
    SQLite until Caller / :func:`plan_and_govern` runs.
    """
    task = str(task or "").strip()
    if not task:
        raise PlanePlanError("task must be non-empty")
    jid = str(job_id or "").strip() or f"plane-{uuid.uuid4().hex[:10]}"
    steps: list[mla.PlanStep] = []
    n = 0

    def add(tool: str, args: dict[str, Any], why: str) -> None:
        nonlocal n
        n += 1
        steps.append(
            mla.PlanStep(
                id=n,
                tool=tool,
                args=dict(args),
                rationale=why,
                status=mla.STEP_PENDING,
            )
        )

    add(
        TOOL_UPSERT_JOB,
        {
            "job_id": jid,
            "kind": kind,
            "title": title or task[:80],
            "status": "inbox",
            "goal": task,
        },
        "open governed job on SQLite control plane (inbox)",
    )
    add(
        TOOL_SET_STATUS,
        {"job_id": jid, "status": "running"},
        "start execution; status → running",
    )
    add(
        TOOL_RECORD_SPEND,
        {
            "job_id": jid,
            "tokens": int(spend_tokens),
            "source": "control_plane_planner",
            "label": "governance",
        },
        "attribute token spend (mission-control task-costs)",
    )
    if include_blocked:
        add(
            TOOL_SET_STATUS,
            {"job_id": jid, "status": "blocked"},
            "quality / governance pause (blocked)",
        )
    add(
        TOOL_SET_STATUS,
        {"job_id": jid, "status": "completed"},
        "complete governed job (sticky terminal)",
    )
    if include_report:
        add(
            TOOL_SPEND_REPORT,
            {"job_id": jid},
            "operator spend report for governed job",
        )

    plan = mla.ToolPlan(
        task=task,
        steps=steps,
        status=mla.STATUS_DRAFT,
        planner="control-plane-lifecycle",
        tools_available=list(PLANE_TOOL_NAMES),
        notes="deterministic control-plane governance lifecycle",
        meta={
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "handoff": "control_plane_planner",
            "job_id": jid,
            "lifecycle": True,
            "catalog": catalog_summary(),
        },
    )
    if auto_ready:
        mla.mark_ready(plan, allowed_tools=list(PLANE_TOOL_NAMES), require_steps=True)
    return plan


def _wants_lifecycle(task: str) -> bool:
    """Heuristic: prefer full governance walk for lifecycle/spend/board tasks."""
    tokens = mla._tokenize(task)  # noqa: SLF001 — shared offline tokenizer
    triggers = {
        "govern",
        "governance",
        "lifecycle",
        "control",
        "plane",
        "spend",
        "cost",
        "inbox",
        "mission",
        "board",
        "ops",
        "status",
        "job",
        "task",
        "complete",
        "budget",
        "token",
    }
    return bool(tokens & triggers)


# ── Planner over control plane ──────────────────────────────────────────────


@dataclass
class ControlPlanePlanner:
    """Dedicated Planner role whose catalog is the SQLite control plane.

    Does **not** write jobs/spend. Produces a ready
    :class:`multi_llm_agent.ToolPlan` for Caller or Orchestrator handoff.
    """

    max_steps: int = 6
    auto_ready: bool = True
    prefer_lifecycle: bool = True
    _tools: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def load_catalog(self, *, force: bool = False) -> list[dict[str, Any]]:
        if self._tools and not force:
            return list(self._tools)
        self._tools = control_plane_as_tools()
        return list(self._tools)

    @property
    def tools(self) -> list[dict[str, Any]]:
        return self.load_catalog()

    def plan(
        self,
        task: str,
        *,
        max_steps: Optional[int] = None,
        plan_text: Optional[str] = None,
        auto_ready: Optional[bool] = None,
        planner_name: str = "",
        job_id: str = "",
        use_lifecycle: Optional[bool] = None,
    ) -> mla.ToolPlan:
        """Break *task* into control-plane governance steps (no SQLite writes)."""
        catalog = self.load_catalog()
        do_ready = self.auto_ready if auto_ready is None else auto_ready
        steps = int(max_steps if max_steps is not None else self.max_steps)

        if plan_text:
            planner = mla.Planner(tools=catalog, max_steps=steps, auto_ready=do_ready)
            plan = planner.plan_from_text(
                plan_text, task=task, tools=catalog, auto_ready=do_ready
            )
            plan.planner = planner_name or "control-plane-injected"
        elif (
            (use_lifecycle is True)
            or (use_lifecycle is None and self.prefer_lifecycle and _wants_lifecycle(task))
        ):
            plan = lifecycle_plan(
                task,
                job_id=job_id,
                auto_ready=do_ready,
            )
            if planner_name:
                plan.planner = planner_name
        else:
            planner = mla.Planner(tools=catalog, max_steps=steps, auto_ready=do_ready)
            plan = planner.plan(
                task, tools=catalog, max_steps=steps, auto_ready=do_ready
            )
            plan.planner = planner_name or plan.planner or "control-plane-heuristic"
            if plan.planner == "heuristic":
                plan.planner = "control-plane-heuristic"
            if plan.planner == "injected":
                plan.planner = "control-plane-injected"

        plan.meta = dict(plan.meta or {})
        plan.meta.update(
            {
                "schema": SCHEMA,
                "paper": PAPER,
                "source_pattern": SOURCE_PATTERN,
                "catalog": catalog_summary(catalog),
                "handoff": "control_plane_planner",
            }
        )
        if job_id and not plan.meta.get("job_id"):
            plan.meta["job_id"] = job_id
        # Annotate steps with plane identity defaults
        params_by_tool = {
            str(t.get("name") or ""): list(t.get("params") or []) for t in catalog
        }
        for step in plan.steps:
            step.args = dict(step.args or {})
            step.args.setdefault("plane_tool", step.tool)
            if job_id and "job_id" in params_by_tool.get(step.tool, []):
                step.args.setdefault("job_id", job_id)
        return plan

    def prompt_block(self, task: str) -> str:
        """System prompt fragment for a live Planner LLM over plane catalog."""
        catalog = self.load_catalog()
        base = mla.Planner(tools=catalog).prompt_block(task, tools=catalog)
        header = (
            f"# Control plane source: {SOURCE_PATTERN} (pattern only)\n"
            f"# Schema: {SCHEMA} · paper: {PAPER}\n"
            "# Plan steps must use plane.* tools (upsert_job, set_status, "
            "record_spend, get_job, list_jobs, spend_report).\n"
            "# Do NOT execute governance ops — output JSON plan only.\n"
            "# Prefer sticky terminal status order: "
            "inbox → running → [blocked] → completed.\n\n"
        )
        return header + base


def plan_from_control_plane(
    task: str,
    *,
    max_steps: int = 6,
    plan_text: Optional[str] = None,
    auto_ready: bool = True,
    job_id: str = "",
    use_lifecycle: Optional[bool] = None,
    prefer_lifecycle: bool = True,
) -> mla.ToolPlan:
    """Convenience: one-shot control-plane Planner (no SQLite writes)."""
    cp = ControlPlanePlanner(
        max_steps=max_steps,
        auto_ready=auto_ready,
        prefer_lifecycle=prefer_lifecycle,
    )
    return cp.plan(
        task,
        plan_text=plan_text,
        auto_ready=auto_ready,
        job_id=job_id,
        use_lifecycle=use_lifecycle,
    )


def plan_payload(plan: mla.ToolPlan) -> dict[str, Any]:
    """JSON-safe plan payload with control-plane schema stamp."""
    base = mla.plan_payload_for_meta(plan)
    base["control_plane_schema"] = SCHEMA
    base["source_pattern"] = SOURCE_PATTERN
    meta = dict(base.get("meta") or {})
    meta.update(
        {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "paper": PAPER,
            "handoff": meta.get("handoff") or "control_plane_planner",
        }
    )
    if isinstance(plan.meta, dict):
        if "catalog" in plan.meta:
            meta["catalog"] = plan.meta["catalog"]
        if "job_id" in plan.meta:
            meta["job_id"] = plan.meta["job_id"]
        if plan.meta.get("lifecycle"):
            meta["lifecycle"] = True
    base["meta"] = meta
    return base


# ── execute against OpsStore (Caller) ───────────────────────────────────────


def make_ops_registry(
    store: ops.OpsStore,
    *,
    default_job_id: str = "",
) -> dict[str, Callable[..., Any]]:
    """Build a Caller registry that maps plane.* tools → OpsStore methods."""

    def _jid(args: dict[str, Any]) -> str:
        return str(args.get("job_id") or default_job_id or "").strip()

    def upsert_job(**kwargs: Any) -> dict[str, Any]:
        args = dict(kwargs)
        jid = _jid(args) or f"plane-{uuid.uuid4().hex[:10]}"
        return store.upsert_job(
            jid,
            kind=str(args.get("kind") or "task"),
            title=str(args.get("title") or jid),
            status=str(args.get("status") or "inbox"),
            goal=str(args.get("goal") or ""),
            meta=args.get("meta") if isinstance(args.get("meta"), dict) else {"source": SCHEMA},
        )

    def set_status(**kwargs: Any) -> dict[str, Any]:
        args = dict(kwargs)
        jid = _jid(args)
        if not jid:
            raise PlanePlanError("set_status requires job_id")
        st = str(args.get("status") or "running")
        force = bool(args.get("force") or False)
        # Auto-create missing job so partial plans still govern
        if store.get(jid) is None:
            store.upsert_job(jid, kind="task", title=jid, status="inbox", goal="")
        return store.set_status(jid, st, force=force)

    def record_spend(**kwargs: Any) -> dict[str, Any]:
        args = dict(kwargs)
        jid = _jid(args)
        if not jid:
            raise PlanePlanError("record_spend requires job_id")
        tokens = int(args.get("tokens") or 0)
        return store.record_spend(
            jid,
            tokens,
            source=str(args.get("source") or "control_plane_planner"),
            label=str(args.get("label") or "governance"),
            cost=float(args["cost"]) if args.get("cost") is not None else None,
            dual_write_usage=False,
            ensure=True,
            kind=str(args.get("kind") or "task"),
        )

    def get_job(**kwargs: Any) -> dict[str, Any]:
        args = dict(kwargs)
        jid = _jid(args)
        if not jid:
            raise PlanePlanError("get_job requires job_id")
        row = store.get(jid)
        return row or {"id": jid, "status": "missing"}

    def list_jobs(**kwargs: Any) -> list[dict[str, Any]]:
        args = dict(kwargs)
        return store.list_jobs(
            kind=str(args["kind"]) if args.get("kind") else None,
            status=str(args["status"]) if args.get("status") else None,
            limit=int(args.get("limit") or 50),
        )

    def spend_report(**kwargs: Any) -> dict[str, Any]:
        args = dict(kwargs)
        jid = str(args.get("job_id") or default_job_id or "").strip() or None
        return store.spend_report(jid, limit=int(args.get("limit") or 500))

    return {
        TOOL_UPSERT_JOB: upsert_job,
        TOOL_SET_STATUS: set_status,
        TOOL_RECORD_SPEND: record_spend,
        TOOL_GET_JOB: get_job,
        TOOL_LIST_JOBS: list_jobs,
        TOOL_SPEND_REPORT: spend_report,
    }


def plan_and_govern(
    task: str,
    *,
    workdir: Any = None,
    max_steps: int = 6,
    plan_text: Optional[str] = None,
    require_ready: bool = True,
    job_id: str = "",
    use_lifecycle: Optional[bool] = None,
    stop_on_error: bool = True,
) -> dict[str, Any]:
    """Plan against control-plane tools, then execute on SQLite OpsStore.

    Pattern: arXiv 2401.07324 Planner (structure) + mission-control SQLite
    governance (execution). Planner phase never writes; Caller phase does.
    """
    root = Path(workdir).resolve() if workdir is not None else Path.cwd()
    plan = plan_from_control_plane(
        task,
        max_steps=max_steps,
        plan_text=plan_text,
        auto_ready=True,
        job_id=job_id,
        use_lifecycle=use_lifecycle,
    )
    payload = plan_payload(plan)

    if require_ready and not plan.is_ready():
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "ok": False,
            "error": "planner_produced_no_ready_plan",
            "phase": "plan",
            "plan": payload,
            "govern": None,
            "job": None,
            "catalog": (plan.meta or {}).get("catalog") or catalog_summary(),
        }

    # Resolve job_id from plan steps / meta for operator board
    jid = str(job_id or (plan.meta or {}).get("job_id") or "").strip()
    if not jid:
        for s in plan.steps:
            cand = str((s.args or {}).get("job_id") or "").strip()
            if cand:
                jid = cand
                break
    if not jid:
        jid = f"plane-{uuid.uuid4().hex[:10]}"
        for s in plan.steps:
            if "job_id" in (s.args or {}) or s.tool in {
                TOOL_UPSERT_JOB,
                TOOL_SET_STATUS,
                TOOL_RECORD_SPEND,
                TOOL_GET_JOB,
                TOOL_SPEND_REPORT,
            }:
                s.args = dict(s.args or {})
                s.args.setdefault("job_id", jid)

    with ops.OpsStore.open(root) as store:
        registry = make_ops_registry(store, default_job_id=jid)
        agent = mla.MultiLLMToolAgent(
            tools=control_plane_as_tools(),
            registry=registry,
            max_steps=max_steps,
        )
        # Skip re-plan: feed ready plan through Caller only
        assert agent.caller is not None
        agent.caller.set_plan(plan, require_ready=True)
        results = agent.caller.execute_all(stop_on_error=stop_on_error)
        summary = mla.summarize_run(plan, results)
        job = store.get(jid)
        spend = store.spend_report(jid)

    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "ok": bool(summary.get("ok")),
        "error": None if summary.get("ok") else "govern_or_plan_failed",
        "phase": "govern",
        "plan": plan.to_dict(),
        "calls": [r.to_dict() for r in results],
        "summary": summary,
        "job_id": jid,
        "job": job,
        "spend": spend.get("summary") if isinstance(spend, dict) else None,
        "catalog": (plan.meta or {}).get("catalog"),
    }


def plan_and_handoff(
    description: str,
    *,
    workdir: Any = None,
    max_steps: int = 6,
    plan_text: Optional[str] = None,
    require_ready: bool = True,
    agent_mode: str = "fake",
    task_id: Optional[str] = None,
    kind: str = "task",
    wait: bool = False,
    wait_timeout_s: float = 120.0,
    sync_fake: bool = True,
    meta: Optional[dict[str, Any]] = None,
    govern: bool = True,
    use_lifecycle: Optional[bool] = None,
) -> dict[str, Any]:
    """Plan against control plane, optionally govern on SQLite, then Orchestrator.

    Pattern: arXiv 2401.07324 Planner + mission-control governance + durable
    Orchestrator execution. Planner never runs tools; governance is opt-in.
    """
    from . import orchestrator as orch

    root = Path(workdir).resolve() if workdir is not None else Path.cwd()
    jid = str(task_id or "").strip() or f"plane-{uuid.uuid4().hex[:10]}"

    plan = plan_from_control_plane(
        description,
        max_steps=max_steps,
        plan_text=plan_text,
        auto_ready=True,
        job_id=jid,
        use_lifecycle=use_lifecycle,
    )
    payload = plan_payload(plan)

    if require_ready and not plan.is_ready():
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "ok": False,
            "error": "planner_produced_no_ready_plan",
            "phase": "plan",
            "plan": payload,
            "govern": None,
            "orchestrator": None,
            "catalog": (plan.meta or {}).get("catalog") or catalog_summary(),
        }

    # Keep a pristine ready plan for Orchestrator; govern mutates step status.
    orch_plan = mla.ToolPlan.from_dict(plan.to_dict())
    if orch_plan.status != mla.STATUS_READY and orch_plan.steps:
        mla.mark_ready(
            orch_plan, allowed_tools=list(PLANE_TOOL_NAMES), require_steps=True
        )

    govern_report: Optional[dict[str, Any]] = None
    if govern:
        gov_plan = mla.ToolPlan.from_dict(plan.to_dict())
        for s in gov_plan.steps:
            s.args = dict(s.args or {})
            if s.tool in {
                TOOL_UPSERT_JOB,
                TOOL_SET_STATUS,
                TOOL_RECORD_SPEND,
                TOOL_GET_JOB,
                TOOL_SPEND_REPORT,
            }:
                s.args.setdefault("job_id", jid)
            # Reset step lifecycle for a clean govern run
            s.status = mla.STEP_PENDING
            s.result = None
            s.error = ""
        gov_plan.status = mla.STATUS_READY
        with ops.OpsStore.open(root) as store:
            registry = make_ops_registry(store, default_job_id=jid)
            caller = mla.Caller(registry=registry)
            caller.set_plan(gov_plan, require_ready=True)
            results = caller.execute_all(stop_on_error=True)
            summary = mla.summarize_run(gov_plan, results)
            govern_report = {
                "ok": bool(summary.get("ok")),
                "job_id": jid,
                "job": store.get(jid),
                "summary": summary,
                "n_calls": len(results),
            }

    extra_meta = {
        "control_plane_plan": True,
        "source_pattern": SOURCE_PATTERN,
        "control_plane_schema": SCHEMA,
        "ops_job_id": jid,
        **(meta or {}),
    }
    o = orch.Orchestrator(root)
    status = o.run_task(
        description,
        kind=kind,
        agent_mode=agent_mode,
        task_id=task_id or jid,
        wait=wait,
        wait_timeout_s=wait_timeout_s,
        with_plan=True,
        plan=orch_plan,
        require_plan=require_ready,
        meta=extra_meta,
        sync_fake=sync_fake if agent_mode == "fake" else False,
    )
    orch_ok = status.get("status") not in (None, "failed")
    gov_ok = True if govern_report is None else bool(govern_report.get("ok"))
    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "ok": bool(orch_ok and gov_ok),
        "error": None,
        "phase": "orchestrator",
        "plan": status.get("plan") or payload,
        "govern": govern_report,
        "orchestrator": status,
        "job_id": jid,
        "catalog": (plan.meta or {}).get("catalog"),
    }


def format_plane_plan(plan: mla.ToolPlan | dict[str, Any]) -> str:
    """Human-readable plan with control-plane schema header."""
    d = plan.to_dict() if isinstance(plan, mla.ToolPlan) else dict(plan or {})
    meta = d.get("meta") or {}
    cat = meta.get("catalog") or {}
    lines = [
        f"schema:     {SCHEMA}",
        f"paper:      {d.get('paper') or PAPER}",
        f"source:     {SOURCE_PATTERN}",
        f"task:       {d.get('task')}",
        f"status:     {d.get('status')}",
        f"planner:    {d.get('planner')}",
        f"steps:      {d.get('n_steps', len(d.get('steps') or []))}",
        f"job_id:     {meta.get('job_id') or '?'}",
        f"catalog:    n={cat.get('n_tools', '?')} by_kind={cat.get('by_kind', {})}",
        "",
    ]
    for s in d.get("steps") or []:
        args = s.get("args") or {}
        lines.append(
            f"  [{s.get('id')}] {s.get('tool')}  "
            f"job={args.get('job_id') or '?'}  "
            f"status_arg={args.get('status') or '-'}  "
            f"step_status={s.get('status')}"
        )
        if s.get("rationale"):
            lines.append(f"       why: {s.get('rationale')}")
    return "\n".join(lines)


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"ok:       {report.get('ok')}",
        f"phase:    {report.get('phase')}",
        f"paper:    {report.get('paper')}",
        f"source:   {report.get('source_pattern') or SOURCE_PATTERN}",
        f"error:    {report.get('error')}",
        f"schema:   {report.get('schema') or SCHEMA}",
        f"job_id:   {report.get('job_id') or ((report.get('govern') or {}).get('job_id'))}",
    ]
    cat = report.get("catalog") or {}
    if cat:
        lines.append(
            f"catalog:  tools={cat.get('n_tools')} kinds={cat.get('by_kind')}"
        )
    plan = report.get("plan") or {}
    lines.append(
        f"plan:     status={plan.get('status')} steps={plan.get('n_steps')}"
    )
    gov = report.get("govern") or {}
    if gov:
        job = gov.get("job") or report.get("job") or {}
        lines.append(
            f"govern:   ok={gov.get('ok')} job_status={job.get('status')} "
            f"tokens={job.get('tokens')}"
        )
    if report.get("job"):
        job = report["job"]
        lines.append(
            f"job:      status={job.get('status')} tokens={job.get('tokens')} "
            f"cost={job.get('cost')}"
        )
    if report.get("spend"):
        sp = report["spend"]
        lines.append(
            f"spend:    tokens={sp.get('total_tokens')} "
            f"requests={sp.get('request_count')}"
        )
    orch_st = report.get("orchestrator") or {}
    if orch_st:
        lines.append(
            f"orch:     task_id={orch_st.get('task_id')} status={orch_st.get('status')} "
            f"pre_planned={orch_st.get('pre_planned')}"
        )
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m nexus.control_plane_planner plan|govern|handoff|catalog|prompt``."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        prog="nexus.control_plane_planner",
        description=(
            "Control-plane Planner "
            "(arXiv 2401.07324 × builderz-labs/mission-control)"
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cat = sub.add_parser("catalog", help="list control-plane ops as Planner tools")
    p_cat.add_argument("--json", action="store_true")

    p_plan = sub.add_parser("plan", help="Planner only over control-plane catalog")
    p_plan.add_argument("task", help="complex task description")
    p_plan.add_argument("--max-steps", type=int, default=6, dest="max_steps")
    p_plan.add_argument("--job-id", default="", dest="job_id")
    p_plan.add_argument("--no-lifecycle", action="store_true")
    p_plan.add_argument("--no-ready", action="store_true")
    p_plan.add_argument("--json", action="store_true")

    p_gov = sub.add_parser(
        "govern",
        help="Planner → execute governance on SQLite OpsStore",
    )
    p_gov.add_argument("task", help="complex task description")
    p_gov.add_argument("--workdir", default=".")
    p_gov.add_argument("--max-steps", type=int, default=6, dest="max_steps")
    p_gov.add_argument("--job-id", default="", dest="job_id")
    p_gov.add_argument("--json", action="store_true")

    p_ho = sub.add_parser(
        "handoff",
        help="Planner → govern (opt) → Orchestrator with_plan",
    )
    p_ho.add_argument("task", help="complex task description")
    p_ho.add_argument("--workdir", default=".")
    p_ho.add_argument("--max-steps", type=int, default=6, dest="max_steps")
    p_ho.add_argument("--task-id", default="", dest="task_id")
    p_ho.add_argument("--no-govern", action="store_true")
    p_ho.add_argument(
        "--agent-mode",
        default="fake",
        choices=sorted({"fake", "demo", "auto", "bus"}),
        dest="agent_mode",
    )
    p_ho.add_argument("--json", action="store_true")

    p_pr = sub.add_parser("prompt", help="Planner LLM prompt over plane catalog")
    p_pr.add_argument("task")

    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "catalog":
        tools = control_plane_as_tools()
        summary = catalog_summary(tools)
        if args.json:
            print(json.dumps({"schema": SCHEMA, "summary": summary, "tools": tools}, indent=2))
        else:
            print(
                f"schema={SCHEMA} tools={summary['n_tools']} "
                f"by_kind={summary['by_kind']}"
            )
            for t in tools:
                print(f"  - {t['name']}: {t.get('description', '')[:90]}")
        return 0 if tools else 1

    if args.cmd == "plan":
        plan = plan_from_control_plane(
            args.task,
            max_steps=int(args.max_steps),
            auto_ready=not args.no_ready,
            job_id=str(args.job_id or ""),
            use_lifecycle=False if args.no_lifecycle else None,
        )
        if args.json:
            print(plan.to_json())
        else:
            print(format_plane_plan(plan))
        return 0 if plan.steps else 1

    if args.cmd == "govern":
        report = plan_and_govern(
            args.task,
            workdir=args.workdir,
            max_steps=int(args.max_steps),
            job_id=str(args.job_id or ""),
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(format_report(report))
            if report.get("plan"):
                print()
                print(format_plane_plan(report["plan"]))
        return 0 if report.get("ok") else 1

    if args.cmd == "handoff":
        tid = str(getattr(args, "task_id", "") or "").strip() or None
        report = plan_and_handoff(
            args.task,
            workdir=args.workdir,
            max_steps=int(args.max_steps),
            agent_mode=str(args.agent_mode),
            task_id=tid,
            govern=not args.no_govern,
            sync_fake=True,
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(format_report(report))
            if report.get("plan"):
                print()
                print(format_plane_plan(report["plan"]))
        ok = bool(report.get("ok")) and (report.get("orchestrator") or {}).get(
            "status"
        ) not in ("failed", None)
        return 0 if ok else 1

    if args.cmd == "prompt":
        planner = ControlPlanePlanner()
        print(planner.prompt_block(args.task))
        return 0

    print("usage: plan|govern|handoff|catalog|prompt", file=sys.stderr)
    return 2


__all__ = [
    "SCHEMA",
    "PAPER",
    "SOURCE_PATTERN",
    "PLANE_TOOL_NAMES",
    "TOOL_UPSERT_JOB",
    "TOOL_SET_STATUS",
    "TOOL_RECORD_SPEND",
    "TOOL_GET_JOB",
    "TOOL_LIST_JOBS",
    "TOOL_SPEND_REPORT",
    "PlanePlanError",
    "ControlPlanePlanner",
    "control_plane_as_tools",
    "catalog_summary",
    "lifecycle_plan",
    "plan_from_control_plane",
    "plan_payload",
    "make_ops_registry",
    "plan_and_govern",
    "plan_and_handoff",
    "format_plane_plan",
    "format_report",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
