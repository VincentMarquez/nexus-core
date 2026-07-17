"""Multi-LLM tool agent: dedicated Planner before Caller / Orchestrator (arXiv 2401.07324).

Paper: *Small LLMs Are Weak Tool Learners: A Multi-LLM Agent*
https://arxiv.org/abs/2401.07324v3

Key pattern (shape only — not a vendored upstream tree):

  task + tool catalog
        │
        ▼
   ┌──────────┐     structured JSON plan
   │  Planner │ ──► (list of steps / tools / args)
   └──────────┘     (small / specialized role — no tool side effects)
        │
        ├── ready plan ──► Caller (execute tools one step at a time)
        │
        └── ready plan ──► Orchestrator.run_task (with_plan / handoff)
                              envelope.meta["tool_plan"] + engine task.meta

Small LLMs struggle when forced to plan *and* emit tool calls in one shot.
Separating Planner (structure) from Caller/Orchestrator (execution) makes weak
tool learners reliable. This module is offline-first: a deterministic heuristic
Planner for tests/smoke, plus parse/inject of LLM JSON plans.

Fail-closed: :class:`Caller` refuses tool execution without a validated ready plan.
Orchestrator handoff is opt-in (``with_plan`` / ``plan_and_handoff``).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

SCHEMA = "nexus.multi_llm_agent/v1"
PAPER = "arxiv:2401.07324v3"

# Plan lifecycle
STATUS_DRAFT = "draft"
STATUS_READY = "ready"
STATUS_EXECUTING = "executing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# Step lifecycle
STEP_PENDING = "pending"
STEP_DONE = "done"
STEP_SKIPPED = "skipped"
STEP_FAILED = "failed"

PLAN_STATUSES = frozenset(
    {STATUS_DRAFT, STATUS_READY, STATUS_EXECUTING, STATUS_DONE, STATUS_FAILED}
)
STEP_STATUSES = frozenset(
    {STEP_PENDING, STEP_DONE, STEP_SKIPPED, STEP_FAILED}
)


class PlanError(ValueError):
    """Structured plan is invalid or not ready for calling."""


class CallGateError(RuntimeError):
    """Caller attempted a tool call without a ready plan (fail-closed)."""


# ── data ───────────────────────────────────────────────────────────────────


@dataclass
class PlanStep:
    """One planned tool invocation (Planner output; Caller input)."""

    id: int
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    status: str = STEP_PENDING
    result: Any = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": int(self.id),
            "tool": str(self.tool),
            "args": dict(self.args or {}),
            "rationale": str(self.rationale or ""),
            "status": str(self.status or STEP_PENDING),
            "result": self.result,
            "error": str(self.error or ""),
        }

    @classmethod
    def from_dict(cls, d: Any, *, default_id: int = 1) -> "PlanStep":
        if not isinstance(d, dict):
            raise PlanError(f"plan step must be a dict, got {type(d).__name__}")
        tool = str(d.get("tool") or d.get("name") or d.get("function") or "").strip()
        if not tool:
            raise PlanError("plan step missing tool name")
        try:
            sid = int(d.get("id") if d.get("id") is not None else default_id)
        except (TypeError, ValueError) as e:
            raise PlanError(f"plan step id must be int: {d.get('id')!r}") from e
        args = d.get("args") if d.get("args") is not None else d.get("arguments")
        if args is None:
            args = d.get("parameters") or {}
        if not isinstance(args, dict):
            raise PlanError(f"plan step args must be object, got {type(args).__name__}")
        status = str(d.get("status") or STEP_PENDING).strip().lower()
        if status not in STEP_STATUSES:
            status = STEP_PENDING
        return cls(
            id=sid,
            tool=tool,
            args=dict(args),
            rationale=str(d.get("rationale") or d.get("why") or d.get("reason") or ""),
            status=status,
            result=d.get("result"),
            error=str(d.get("error") or ""),
        )


@dataclass
class ToolPlan:
    """Structured multi-step plan produced by the Planner role."""

    task: str
    steps: list[PlanStep] = field(default_factory=list)
    status: str = STATUS_DRAFT
    planner: str = "heuristic"
    tools_available: list[str] = field(default_factory=list)
    schema: str = SCHEMA
    paper: str = PAPER
    created_at: float = field(default_factory=time.time)
    notes: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "paper": self.paper,
            "task": self.task,
            "status": self.status,
            "planner": self.planner,
            "tools_available": list(self.tools_available),
            "steps": [s.to_dict() for s in self.steps],
            "n_steps": len(self.steps),
            "created_at": self.created_at,
            "notes": self.notes,
            "meta": dict(self.meta or {}),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, d: Any) -> "ToolPlan":
        if not isinstance(d, dict):
            raise PlanError(f"plan must be a dict, got {type(d).__name__}")
        task = str(d.get("task") or d.get("goal") or d.get("objective") or "").strip()
        raw_steps = d.get("steps")
        if raw_steps is None:
            raw_steps = d.get("plan") or d.get("tool_calls") or []
        if not isinstance(raw_steps, list):
            raise PlanError("plan.steps must be a list")
        steps: list[PlanStep] = []
        for i, raw in enumerate(raw_steps, start=1):
            steps.append(PlanStep.from_dict(raw, default_id=i))
        status = str(d.get("status") or STATUS_DRAFT).strip().lower()
        if status not in PLAN_STATUSES:
            status = STATUS_DRAFT
        tools = d.get("tools_available") or d.get("tools") or []
        if not isinstance(tools, list):
            tools = []
        return cls(
            task=task,
            steps=steps,
            status=status,
            planner=str(d.get("planner") or "injected"),
            tools_available=[str(t) for t in tools],
            schema=str(d.get("schema") or SCHEMA),
            paper=str(d.get("paper") or PAPER),
            created_at=float(d.get("created_at") or time.time()),
            notes=str(d.get("notes") or ""),
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
        )

    def pending_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == STEP_PENDING]

    def is_ready(self) -> bool:
        return self.status == STATUS_READY and bool(self.steps)


def parse_plan_json(text: str) -> ToolPlan:
    """Parse Planner LLM/text output into a :class:`ToolPlan`.

    Accepts raw JSON, fenced ```json blocks, or a plan object embedded in prose.
    """
    if not text or not str(text).strip():
        raise PlanError("empty plan text")
    text = str(text).strip()

    def _try(s: str) -> Optional[ToolPlan]:
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            return None
        if isinstance(obj, list):
            return ToolPlan.from_dict({"task": "", "steps": obj, "status": STATUS_DRAFT})
        if isinstance(obj, dict):
            return ToolPlan.from_dict(obj)
        return None

    plan = _try(text)
    if plan is not None:
        return plan

    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.S)
    if m:
        plan = _try(m.group(1))
        if plan is not None:
            return plan

    # first object or array blob
    for pat in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pat, text, re.S)
        if m:
            plan = _try(m.group(0))
            if plan is not None:
                return plan
    raise PlanError("could not parse structured plan JSON from text")


# ── validation ─────────────────────────────────────────────────────────────


def _tool_names(tools: Optional[Iterable[Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for t in tools or []:
        if isinstance(t, str):
            name = t.strip()
        elif isinstance(t, dict):
            name = str(t.get("name") or t.get("tool") or "").strip()
        else:
            name = str(getattr(t, "name", "") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _tool_index(tools: Optional[Iterable[Any]]) -> dict[str, Any]:
    """Map tool name → description/entry for heuristic matching."""
    idx: dict[str, Any] = {}
    for t in tools or []:
        if isinstance(t, str):
            idx[t.strip()] = {"name": t.strip(), "description": t.strip()}
        elif isinstance(t, dict):
            name = str(t.get("name") or t.get("tool") or "").strip()
            if name:
                idx[name] = t
        else:
            name = str(getattr(t, "name", "") or "").strip()
            if name:
                desc = str(getattr(t, "description", "") or name)
                idx[name] = {"name": name, "description": desc}
    return idx


def validate_plan(
    plan: ToolPlan,
    *,
    allowed_tools: Optional[Sequence[str]] = None,
    require_steps: bool = True,
    require_task: bool = False,
) -> dict[str, Any]:
    """Validate plan structure; return report with ok + findings.

    When *allowed_tools* is set, unknown tool names are errors (fail-closed).
    """
    findings: list[dict[str, str]] = []
    ok = True

    def err(msg: str, path: str = "plan") -> None:
        nonlocal ok
        ok = False
        findings.append({"severity": "error", "path": path, "message": msg})

    def warn(msg: str, path: str = "plan") -> None:
        findings.append({"severity": "warning", "path": path, "message": msg})

    if require_task and not (plan.task or "").strip():
        err("task is empty", "task")
    if require_steps and not plan.steps:
        err("plan has no steps", "steps")
    if plan.status not in PLAN_STATUSES:
        err(f"invalid status {plan.status!r}", "status")

    allowed = {str(t).strip() for t in (allowed_tools or []) if str(t).strip()}
    seen_ids: set[int] = set()
    for i, step in enumerate(plan.steps):
        path = f"steps[{i}]"
        if step.id in seen_ids:
            err(f"duplicate step id {step.id}", f"{path}.id")
        seen_ids.add(step.id)
        if not step.tool:
            err("missing tool", f"{path}.tool")
        elif allowed and step.tool not in allowed:
            err(
                f"tool {step.tool!r} not in allowed tools {sorted(allowed)}",
                f"{path}.tool",
            )
        if step.status not in STEP_STATUSES:
            warn(f"unknown step status {step.status!r}", f"{path}.status")
        if not isinstance(step.args, dict):
            err("args must be object", f"{path}.args")

    return {
        "ok": ok,
        "schema": SCHEMA,
        "n_steps": len(plan.steps),
        "status": plan.status,
        "findings": findings,
        "errors": sum(1 for f in findings if f["severity"] == "error"),
        "warnings": sum(1 for f in findings if f["severity"] == "warning"),
    }


def mark_ready(
    plan: ToolPlan,
    *,
    allowed_tools: Optional[Sequence[str]] = None,
    require_steps: bool = True,
) -> ToolPlan:
    """Validate and flip plan status to ready (raises PlanError if invalid)."""
    rep = validate_plan(
        plan, allowed_tools=allowed_tools, require_steps=require_steps
    )
    if not rep["ok"]:
        msgs = "; ".join(f["message"] for f in rep["findings"] if f["severity"] == "error")
        raise PlanError(f"plan not ready: {msgs}")
    plan.status = STATUS_READY
    return plan


# ── Planner ────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", (text or "").lower()) if len(t) > 1}


def _score_tool(task_tokens: set[str], name: str, description: str = "") -> float:
    """Simple lexical score: tool name tokens + description overlap with task."""
    name_tokens = _tokenize(name.replace(".", " ").replace("-", " ").replace("_", " "))
    # also split camel/snake pieces already via tokenize
    desc_tokens = _tokenize(description)
    score = 0.0
    for tok in name_tokens:
        if tok in task_tokens:
            score += 3.0
        # partial: task mentions a stem of the tool
        for tt in task_tokens:
            if tok in tt or tt in tok:
                score += 1.0
                break
    for tok in desc_tokens:
        if tok in task_tokens:
            score += 0.5
    # boost common intent words → tool families
    intent = {
        "list": 1.5,
        "status": 1.5,
        "read": 1.0,
        "search": 1.5,
        "validate": 1.5,
        "export": 1.0,
        "catalog": 1.0,
        "grade": 1.0,
        "eval": 1.0,
        "plan": 1.0,
        "marketplace": 1.5,
        "skillpack": 1.0,
        "tool": 0.5,
    }
    for tok, w in intent.items():
        if tok in task_tokens and tok in (name_tokens | desc_tokens | {name.lower()}):
            score += w
    return score


def heuristic_plan(
    task: str,
    tools: Optional[Iterable[Any]] = None,
    *,
    max_steps: int = 5,
    default_args: Optional[dict[str, Any]] = None,
) -> ToolPlan:
    """Offline Planner: rank tools by lexical match and emit ordered steps.

    Deterministic — no LLM. Suitable for tests and smoke. Prefer inject/LLM
    plans in production when a stronger planner model is available.
    """
    task = str(task or "").strip()
    if not task:
        raise PlanError("task must be non-empty")
    idx = _tool_index(tools)
    if not idx:
        # Empty catalog still yields a draft with no steps (caller will fail closed)
        return ToolPlan(
            task=task,
            steps=[],
            status=STATUS_DRAFT,
            planner="heuristic",
            tools_available=[],
            notes="no tools available",
        )

    tokens = _tokenize(task)
    ranked: list[tuple[float, str]] = []
    for name, entry in idx.items():
        if isinstance(entry, dict):
            desc = str(entry.get("description") or "")
        else:
            desc = ""
        sc = _score_tool(tokens, name, desc)
        ranked.append((sc, name))
    ranked.sort(key=lambda x: (-x[0], x[1]))

    steps: list[PlanStep] = []
    base_args = dict(default_args or {})
    # Always take positive scores; if all zero, take top-1 as a weak guess
    positive = [(s, n) for s, n in ranked if s > 0]
    chosen = positive[: max(1, int(max_steps))] if positive else ranked[:1]
    for i, (sc, name) in enumerate(chosen[: max(1, int(max_steps))], start=1):
        steps.append(
            PlanStep(
                id=i,
                tool=name,
                args=dict(base_args),
                rationale=f"heuristic match score={sc:.1f} for task tokens",
                status=STEP_PENDING,
            )
        )

    plan = ToolPlan(
        task=task,
        steps=steps,
        status=STATUS_DRAFT,
        planner="heuristic",
        tools_available=sorted(idx.keys()),
        notes=f"heuristic selected {len(steps)} tool(s)",
        meta={"max_steps": int(max_steps)},
    )
    return plan


@dataclass
class Planner:
    """Dedicated Planner role: task → structured :class:`ToolPlan`.

    Does **not** execute tools. Use :class:`Caller` after :func:`mark_ready`.
    """

    tools: list[Any] = field(default_factory=list)
    max_steps: int = 5
    auto_ready: bool = True

    def plan(
        self,
        task: str,
        *,
        tools: Optional[Iterable[Any]] = None,
        max_steps: Optional[int] = None,
        default_args: Optional[dict[str, Any]] = None,
        auto_ready: Optional[bool] = None,
    ) -> ToolPlan:
        catalog = list(tools) if tools is not None else list(self.tools)
        p = heuristic_plan(
            task,
            catalog,
            max_steps=int(max_steps if max_steps is not None else self.max_steps),
            default_args=default_args,
        )
        do_ready = self.auto_ready if auto_ready is None else auto_ready
        if do_ready and p.steps:
            mark_ready(p, allowed_tools=_tool_names(catalog), require_steps=True)
        return p

    def plan_from_text(
        self,
        text: str,
        *,
        task: str = "",
        tools: Optional[Iterable[Any]] = None,
        auto_ready: Optional[bool] = None,
    ) -> ToolPlan:
        """Inject/parse an LLM Planner response into a validated plan."""
        catalog = list(tools) if tools is not None else list(self.tools)
        p = parse_plan_json(text)
        if task and not p.task:
            p.task = task
        p.planner = p.planner or "injected"
        if not p.tools_available:
            p.tools_available = _tool_names(catalog)
        do_ready = self.auto_ready if auto_ready is None else auto_ready
        if do_ready:
            mark_ready(
                p,
                allowed_tools=_tool_names(catalog) or None,
                require_steps=True,
            )
        return p

    def prompt_block(
        self,
        task: str,
        *,
        tools: Optional[Iterable[Any]] = None,
    ) -> str:
        """System-style prompt fragment for a live Planner LLM."""
        catalog = list(tools) if tools is not None else list(self.tools)
        names = _tool_names(catalog)
        tool_lines = []
        idx = _tool_index(catalog)
        for n in names:
            desc = ""
            ent = idx.get(n)
            if isinstance(ent, dict):
                desc = str(ent.get("description") or "")[:120]
            tool_lines.append(f"- {n}" + (f": {desc}" if desc else ""))
        tools_block = "\n".join(tool_lines) if tool_lines else "(no tools)"
        return (
            "# ROLE: Planner (multi-LLM tool agent; arXiv 2401.07324)\n"
            "You ONLY produce a structured plan. Do NOT call tools.\n"
            "Output a single JSON object:\n"
            "{\n"
            '  "task": "<echo task>",\n'
            '  "status": "ready",\n'
            '  "steps": [\n'
            '    {"id": 1, "tool": "<name>", "args": {}, "rationale": "..."}\n'
            "  ]\n"
            "}\n"
            f"## Task\n{task}\n"
            f"## Available tools\n{tools_block}\n"
        )


# ── Caller ─────────────────────────────────────────────────────────────────


@dataclass
class CallResult:
    step_id: int
    tool: str
    ok: bool
    result: Any = None
    error: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Caller:
    """Caller role: execute planned tools only after plan is ready.

    Fail-closed: any call without a ready plan raises :class:`CallGateError`.
    """

    plan: Optional[ToolPlan] = None
    history: list[CallResult] = field(default_factory=list)
    # optional tool registry: name → callable(**args) or callable(args)
    registry: dict[str, Callable[..., Any]] = field(default_factory=dict)

    def set_plan(self, plan: ToolPlan, *, require_ready: bool = True) -> None:
        if require_ready and not plan.is_ready():
            raise CallGateError(
                f"plan status must be ready with steps; got status={plan.status!r} "
                f"n_steps={len(plan.steps)}"
            )
        self.plan = plan

    def can_call(self) -> bool:
        if self.plan is None:
            return False
        if self.plan.status not in (STATUS_READY, STATUS_EXECUTING):
            return False
        return bool(self.plan.pending_steps())

    def next_step(self) -> Optional[PlanStep]:
        if not self.can_call() or self.plan is None:
            return None
        pending = self.plan.pending_steps()
        return pending[0] if pending else None

    def _invoke(self, tool: str, args: dict[str, Any]) -> Any:
        if tool not in self.registry:
            raise CallGateError(f"tool not in registry: {tool!r}")
        fn = self.registry[tool]
        try:
            return fn(**args)
        except TypeError:
            return fn(args)

    def call_next(self, *, executor: Optional[Callable[[str, dict[str, Any]], Any]] = None) -> CallResult:
        """Execute the next pending plan step. Fail-closed without ready plan."""
        if self.plan is None:
            raise CallGateError("no plan set; Planner must run first")
        if self.plan.status not in (STATUS_READY, STATUS_EXECUTING):
            raise CallGateError(
                f"plan not ready for tool calls (status={self.plan.status!r})"
            )
        step = self.next_step()
        if step is None:
            raise CallGateError("no pending steps in plan")

        self.plan.status = STATUS_EXECUTING
        try:
            if executor is not None:
                out = executor(step.tool, dict(step.args))
            else:
                out = self._invoke(step.tool, dict(step.args))
            step.status = STEP_DONE
            step.result = out
            cr = CallResult(step_id=step.id, tool=step.tool, ok=True, result=out)
        except Exception as e:  # noqa: BLE001 — surface to plan/history
            step.status = STEP_FAILED
            step.error = str(e)
            cr = CallResult(step_id=step.id, tool=step.tool, ok=False, error=str(e))
            self.history.append(cr)
            self.plan.status = STATUS_FAILED
            return cr

        self.history.append(cr)
        if not self.plan.pending_steps():
            self.plan.status = STATUS_DONE
        return cr

    def execute_all(
        self,
        *,
        executor: Optional[Callable[[str, dict[str, Any]], Any]] = None,
        stop_on_error: bool = True,
    ) -> list[CallResult]:
        """Drain pending steps in plan order."""
        results: list[CallResult] = []
        while self.can_call():
            cr = self.call_next(executor=executor)
            results.append(cr)
            if not cr.ok and stop_on_error:
                break
        return results


# ── Summarizer + pipeline ──────────────────────────────────────────────────


def summarize_run(
    plan: ToolPlan,
    history: Sequence[CallResult],
) -> dict[str, Any]:
    """Lightweight Summarizer role: roll up plan + call history (no LLM)."""
    ok_n = sum(1 for h in history if h.ok)
    fail_n = sum(1 for h in history if not h.ok)
    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "task": plan.task,
        "plan_status": plan.status,
        "n_steps": len(plan.steps),
        "n_calls": len(history),
        "n_ok": ok_n,
        "n_failed": fail_n,
        "ok": plan.status == STATUS_DONE and fail_n == 0 and ok_n > 0,
        "tools_used": [h.tool for h in history],
        "steps": [s.to_dict() for s in plan.steps],
        "history": [h.to_dict() for h in history],
    }


@dataclass
class MultiLLMToolAgent:
    """Planner → Caller (+ Summarizer) pipeline.

    Usage::

        agent = MultiLLMToolAgent(tools=[...], registry={...})
        report = agent.run("list marketplace plugins and validate catalog")
    """

    tools: list[Any] = field(default_factory=list)
    registry: dict[str, Callable[..., Any]] = field(default_factory=dict)
    max_steps: int = 5
    planner: Optional[Planner] = None
    caller: Optional[Caller] = None

    def __post_init__(self) -> None:
        if self.planner is None:
            self.planner = Planner(tools=list(self.tools), max_steps=self.max_steps)
        if self.caller is None:
            self.caller = Caller(registry=dict(self.registry))

    def run(
        self,
        task: str,
        *,
        tools: Optional[Iterable[Any]] = None,
        registry: Optional[dict[str, Callable[..., Any]]] = None,
        plan_text: Optional[str] = None,
        executor: Optional[Callable[[str, dict[str, Any]], Any]] = None,
        max_steps: Optional[int] = None,
        stop_on_error: bool = True,
    ) -> dict[str, Any]:
        """Full multi-LLM agent loop: plan (no tools) → call tools → summarize."""
        catalog = list(tools) if tools is not None else list(self.tools)
        assert self.planner is not None
        assert self.caller is not None
        if registry is not None:
            self.caller.registry = dict(registry)
        elif self.registry and not self.caller.registry:
            self.caller.registry = dict(self.registry)

        if plan_text:
            plan = self.planner.plan_from_text(plan_text, task=task, tools=catalog)
        else:
            plan = self.planner.plan(
                task, tools=catalog, max_steps=max_steps, auto_ready=True
            )

        # Hard gate: never call without ready plan
        if not plan.is_ready():
            return {
                "schema": SCHEMA,
                "paper": PAPER,
                "ok": False,
                "error": "planner_produced_no_ready_plan",
                "plan": plan.to_dict(),
                "summary": None,
                "phase": "plan",
            }

        self.caller.set_plan(plan, require_ready=True)
        results = self.caller.execute_all(
            executor=executor, stop_on_error=stop_on_error
        )
        summary = summarize_run(plan, results)
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "ok": bool(summary.get("ok")),
            "error": None if summary.get("ok") else "call_or_plan_failed",
            "plan": plan.to_dict(),
            "calls": [r.to_dict() for r in results],
            "summary": summary,
            "phase": "done" if summary.get("ok") else plan.status,
        }


def default_tools_from_catalog(
    *, max_privilege: Optional[str] = "read"
) -> list[dict[str, Any]]:
    """Load MCP tool names/descriptions from the live catalog (optional)."""
    try:
        from . import tool_catalog as tc

        entries = tc.build_entries(max_privilege=max_privilege)
        return [
            {
                "name": e.name,
                "description": e.description,
                "privilege": e.privilege,
            }
            for e in entries
        ]
    except Exception:  # noqa: BLE001 — offline / circular import safe
        return []


# ── Planner → Orchestrator handoff (arXiv 2401.07324) ───────────────────────


DEFAULT_ORCH_TOOLS = (
    "list_project_files",
    "nexus_status",
    "tool_catalog",
    "marketplace",
    "mcp_eval",
    "maf_bench",
    "run_task",
    "get_task_status",
)


LOCAL_REGISTRY_SCHEMA = "nexus.local_registry/v1"

# Tools with real local implementations under --real (read-only; no writes).
REAL_LOCAL_TOOLS: tuple[str, ...] = (
    "marketplace",
    "nexus_status",
    "tool_catalog",
    "list_project_files",
    # S13 capability-factory builtins (factory_tools wrappers)
    "nexus_lesson_query",
    "nexus_scope_check",
    "nexus_skill_search",
    "nexus_pack_validate",
    "nexus_code_review",
)

# Marketplace actions allowed when real=True (wshobson validate/self_check shape).
MARKETPLACE_READ_ACTIONS: frozenset[str] = frozenset(
    {
        "list",
        "validate",
        "catalog",
        "collisions",
        "self_check",
        "self-check",
        "capabilities",
        "portability",
        "garden",
    }
)

# Write / generate actions refused by the read-only registry.
MARKETPLACE_WRITE_ACTIONS: frozenset[str] = frozenset(
    {
        "export",
        "generate",
        "round_trip",
        "round-trip",
        "validate_generated",
        "validate-generated",
    }
)


def _workdir_path(workdir: Any = None) -> Path:
    """Resolve project root for local registry tools."""
    if workdir is not None and str(workdir).strip():
        return Path(workdir).expanduser().resolve()
    import os

    env = (os.environ.get("NEXUS_PROJECT_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def invoke_marketplace_readonly(
    workdir: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run a *read-only* marketplace action (wshobson-shaped self_check/list/…).

    Default action is ``self_check`` so heuristic plans that only name
    ``marketplace`` still exercise the structural gate. Write actions
    (export/generate/round-trip) are refused fail-closed.
    """
    from . import marketplace as mp

    root = _workdir_path(workdir)
    raw_action = kwargs.get("action") or kwargs.get("cmd") or "self_check"
    action = str(raw_action or "self_check").strip().lower() or "self_check"
    action_norm = action.replace("-", "_")

    if action in MARKETPLACE_WRITE_ACTIONS or action_norm in {
        a.replace("-", "_") for a in MARKETPLACE_WRITE_ACTIONS
    }:
        return {
            "schema": LOCAL_REGISTRY_SCHEMA,
            "ok": False,
            "real": True,
            "tool": "marketplace",
            "action": action,
            "error": f"write action refused in read-only registry: {action}",
            "allowed": sorted(MARKETPLACE_READ_ACTIONS),
        }

    if kwargs.get("include_skillpacks") is None:
        # Match CLI/MCP defaults: skillpacks on for catalog/self_check/garden.
        include_sp = action_norm in (
            "catalog",
            "self_check",
            "portability",
            "garden",
        )
    else:
        include_sp = bool(kwargs.get("include_skillpacks"))
    fail_on_oversize = bool(
        kwargs.get("fail_on_oversize") or kwargs.get("strict") or False
    )

    try:
        if action_norm in ("self_check", "selfcheck"):
            data = mp.self_check(
                root,
                include_skillpacks=(
                    True
                    if kwargs.get("include_skillpacks") is None
                    else include_sp
                ),
                fail_on_oversize=fail_on_oversize,
            )
            if not isinstance(data, dict):
                data = {"payload": data}
            data = dict(data)
            data.setdefault("ok", True)
            data["real"] = True
            data["tool"] = "marketplace"
            data["action"] = "self_check"
            data["workdir"] = str(root)
            return data

        if action_norm == "list":
            rows = mp.list_plugins(
                root,
                validate=bool(kwargs.get("validate", False)),
                include_skillpacks=include_sp,
            )
            return {
                "schema": LOCAL_REGISTRY_SCHEMA,
                "ok": True,
                "real": True,
                "tool": "marketplace",
                "action": "list",
                "workdir": str(root),
                "count": len(rows),
                "plugins": [r.to_dict() for r in rows],
            }

        if action_norm == "validate":
            data = mp.validate_all(root)
            if not isinstance(data, dict):
                data = {"payload": data}
            data = dict(data)
            data["real"] = True
            data["tool"] = "marketplace"
            data["action"] = "validate"
            data["workdir"] = str(root)
            data.setdefault("ok", data.get("errors", 0) == 0)
            return data

        if action_norm == "catalog":
            data = mp.build_catalog(root, include_skillpacks=include_sp)
            if not isinstance(data, dict):
                data = {"payload": data}
            data = dict(data)
            data["real"] = True
            data["tool"] = "marketplace"
            data["action"] = "catalog"
            data["workdir"] = str(root)
            data.setdefault("ok", True)
            return data

        if action_norm == "collisions":
            data = mp.collisions(root)
            if not isinstance(data, dict):
                data = {"payload": data}
            data = dict(data)
            data["real"] = True
            data["tool"] = "marketplace"
            data["action"] = "collisions"
            data["workdir"] = str(root)
            # collisions report uses ok / duplicates fields
            if "ok" not in data:
                dups = data.get("collisions") or data.get("duplicates") or []
                data["ok"] = not bool(dups)
            return data

        if action_norm == "capabilities":
            data = mp.capabilities_matrix()
            if not isinstance(data, dict):
                data = {"payload": data}
            data = dict(data)
            data["real"] = True
            data["tool"] = "marketplace"
            data["action"] = "capabilities"
            data.setdefault("ok", True)
            return data

        if action_norm == "portability":
            data = mp.portability(
                root,
                include_skillpacks=include_sp,
                fail_on_oversize=fail_on_oversize,
            )
            if not isinstance(data, dict):
                data = {"payload": data}
            data = dict(data)
            data["real"] = True
            data["tool"] = "marketplace"
            data["action"] = "portability"
            data["workdir"] = str(root)
            data.setdefault("ok", True)
            return data

        if action_norm == "garden":
            data = mp.garden(
                root,
                include_skillpacks=include_sp,
                fail_on_oversize=fail_on_oversize,
            )
            if not isinstance(data, dict):
                data = {"payload": data}
            data = dict(data)
            data["real"] = True
            data["tool"] = "marketplace"
            data["action"] = "garden"
            data["workdir"] = str(root)
            data.setdefault("ok", True)
            return data

        return {
            "schema": LOCAL_REGISTRY_SCHEMA,
            "ok": False,
            "real": True,
            "tool": "marketplace",
            "action": action,
            "error": (
                f"unknown or non-read marketplace action: {action!r}; "
                f"allowed={sorted(MARKETPLACE_READ_ACTIONS)}"
            ),
        }
    except Exception as e:  # noqa: BLE001 — surface as structured tool fail
        return {
            "schema": LOCAL_REGISTRY_SCHEMA,
            "ok": False,
            "real": True,
            "tool": "marketplace",
            "action": action,
            "error": str(e),
            "workdir": str(root),
        }


def invoke_nexus_status(workdir: Any = None, **kwargs: Any) -> dict[str, Any]:
    """Lightweight local nexus status (read-only; no process mutation)."""
    root = _workdir_path(workdir)
    plugins = root / "plugins"
    skillpacks = root / "skillpacks"
    state = root / ".nexus_state"
    n_plugins = 0
    if plugins.is_dir():
        n_plugins = sum(
            1
            for p in plugins.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
    runtime: dict[str, Any] = {}
    try:
        from .runtime import RuntimeManager

        runtime = dict(RuntimeManager().status() or {})
    except Exception:  # noqa: BLE001 — offline / no node runtime ok
        runtime = {"available": False}

    verbose = bool(kwargs.get("verbose", False))
    out: dict[str, Any] = {
        "schema": LOCAL_REGISTRY_SCHEMA,
        "ok": True,
        "real": True,
        "tool": "nexus_status",
        "workdir": str(root),
        "plugins_dir": str(plugins),
        "plugins_present": plugins.is_dir(),
        "n_plugins": n_plugins,
        "skillpacks_present": skillpacks.is_dir(),
        "state_dir_present": state.is_dir(),
        "alive_state": (state / "alive_state.json").is_file(),
        "runtime": runtime if verbose else {"keys": sorted(runtime.keys())[:12]},
    }
    return out


def invoke_tool_catalog_readonly(
    workdir: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Read-only tool_catalog actions (list / validate / catalog)."""
    from . import tool_catalog as tc

    root = _workdir_path(workdir)
    action = str(kwargs.get("action") or "validate").strip().lower() or "validate"
    action_norm = action.replace("-", "_")
    max_priv = str(kwargs.get("max_privilege") or "read")

    try:
        if action_norm in ("list", "entries"):
            entries = tc.build_entries(max_privilege=max_priv)
            return {
                "schema": LOCAL_REGISTRY_SCHEMA,
                "ok": True,
                "real": True,
                "tool": "tool_catalog",
                "action": "list",
                "count": len(entries),
                "tools": [
                    {
                        "name": e.name,
                        "privilege": getattr(e, "privilege", None),
                        "description": (getattr(e, "description", "") or "")[:160],
                    }
                    for e in entries
                ],
            }
        if action_norm in ("validate", "check"):
            rep = tc.validate_tools()
            data = rep.to_dict() if hasattr(rep, "to_dict") else dict(rep or {})
            if not isinstance(data, dict):
                data = {"payload": data}
            data = dict(data)
            data["real"] = True
            data["tool"] = "tool_catalog"
            data["action"] = "validate"
            data["workdir"] = str(root)
            data.setdefault("ok", getattr(rep, "ok", True))
            # Soft filter note — max_privilege is advisory on validate path
            data["max_privilege"] = max_priv
            return data
        if action_norm in ("catalog", "openapi"):
            data = tc.build_catalog(max_privilege=max_priv)
            if not isinstance(data, dict):
                data = {"payload": data}
            data = dict(data)
            data["real"] = True
            data["tool"] = "tool_catalog"
            data["action"] = action_norm
            data.setdefault("ok", True)
            return data
        if action_norm in ("export", "write", "install"):
            return {
                "schema": LOCAL_REGISTRY_SCHEMA,
                "ok": False,
                "real": True,
                "tool": "tool_catalog",
                "action": action,
                "error": f"write action refused in read-only registry: {action}",
            }
        return {
            "schema": LOCAL_REGISTRY_SCHEMA,
            "ok": False,
            "real": True,
            "tool": "tool_catalog",
            "action": action,
            "error": f"unknown tool_catalog action: {action!r}",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "schema": LOCAL_REGISTRY_SCHEMA,
            "ok": False,
            "real": True,
            "tool": "tool_catalog",
            "action": action,
            "error": str(e),
        }


def invoke_list_project_files(
    workdir: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Bounded directory listing under workdir (read-only)."""
    root = _workdir_path(workdir)
    rel = str(kwargs.get("path") or kwargs.get("dir") or ".").strip() or "."
    # Jail: never escape workdir
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return {
            "schema": LOCAL_REGISTRY_SCHEMA,
            "ok": False,
            "real": True,
            "tool": "list_project_files",
            "error": f"path escapes workdir: {rel!r}",
            "workdir": str(root),
        }
    limit = max(1, min(int(kwargs.get("limit") or 50), 200))
    if not target.exists():
        return {
            "schema": LOCAL_REGISTRY_SCHEMA,
            "ok": False,
            "real": True,
            "tool": "list_project_files",
            "error": f"path not found: {rel}",
            "workdir": str(root),
        }
    entries: list[dict[str, Any]] = []
    if target.is_file():
        entries.append(
            {
                "name": target.name,
                "path": str(target.relative_to(root)),
                "kind": "file",
                "size": target.stat().st_size,
            }
        )
    else:
        kids = sorted(target.iterdir(), key=lambda p: p.name.lower())
        for p in kids[:limit]:
            if p.name.startswith(".") and p.name not in (".github",):
                continue
            kind = "dir" if p.is_dir() else "file"
            item: dict[str, Any] = {
                "name": p.name,
                "path": str(p.relative_to(root)),
                "kind": kind,
            }
            if kind == "file":
                try:
                    item["size"] = p.stat().st_size
                except OSError:
                    pass
            entries.append(item)
    return {
        "schema": LOCAL_REGISTRY_SCHEMA,
        "ok": True,
        "real": True,
        "tool": "list_project_files",
        "workdir": str(root),
        "path": rel,
        "count": len(entries),
        "entries": entries,
    }


def build_local_registry(
    workdir: Any = None,
    *,
    tools: Optional[Iterable[Any]] = None,
    mock_fallback: bool = True,
) -> dict[str, Callable[..., Any]]:
    """Build a local read-only tool registry for CLI/MCP run/loop (F4).

    Real implementations (wshobson marketplace self_check + status/catalog/files)
    for :data:`REAL_LOCAL_TOOLS`. Other tool names get a mock stub when
    *mock_fallback* is True so mixed catalogs still plan/execute offline.

    Never mutates the tree (no marketplace generate/export).
    """
    root = _workdir_path(workdir)
    names = _tool_names(tools) if tools is not None else list(REAL_LOCAL_TOOLS)
    if not names:
        names = list(REAL_LOCAL_TOOLS)

    def _marketplace(**kw: Any) -> dict[str, Any]:
        return invoke_marketplace_readonly(root, **kw)

    def _status(**kw: Any) -> dict[str, Any]:
        return invoke_nexus_status(root, **kw)

    def _catalog(**kw: Any) -> dict[str, Any]:
        return invoke_tool_catalog_readonly(root, **kw)

    def _files(**kw: Any) -> dict[str, Any]:
        return invoke_list_project_files(root, **kw)

    def _factory_builtin(tool_name: str) -> Callable[..., Any]:
        def _fn(**kw: Any) -> dict[str, Any]:
            from . import factory_tools as ft

            # Map common arg aliases used by planners
            if tool_name == "nexus_pack_validate":
                if "path" not in kw and kw.get("query"):
                    kw = dict(kw)
                    kw["path"] = str(kw.pop("query"))
            if tool_name in ("nexus_scope_check", "nexus_code_review"):
                if "paths" not in kw and "paths_csv" not in kw and kw.get("path"):
                    kw = dict(kw)
                    kw["paths_csv"] = str(kw.pop("path"))
            try:
                out = ft.invoke_tool(tool_name, root, **kw)
            except TypeError:
                out = ft.invoke_tool(tool_name, root)
            if not isinstance(out, dict):
                out = {"ok": False, "error": "non-dict tool result", "tool": tool_name}
            else:
                out = dict(out)
            out.setdefault("real", True)
            out.setdefault("schema", LOCAL_REGISTRY_SCHEMA)
            out.setdefault("tool", tool_name)
            return out

        return _fn

    real_fns: dict[str, Callable[..., Any]] = {
        "marketplace": _marketplace,
        "nexus_status": _status,
        "tool_catalog": _catalog,
        "list_project_files": _files,
        "nexus_lesson_query": _factory_builtin("nexus_lesson_query"),
        "nexus_scope_check": _factory_builtin("nexus_scope_check"),
        "nexus_skill_search": _factory_builtin("nexus_skill_search"),
        "nexus_pack_validate": _factory_builtin("nexus_pack_validate"),
        "nexus_code_review": _factory_builtin("nexus_code_review"),
    }

    registry: dict[str, Callable[..., Any]] = {}
    for name in names:
        key = str(name or "").strip()
        if not key:
            continue
        if key in real_fns:
            registry[key] = real_fns[key]
        elif mock_fallback:
            registry[key] = (
                lambda _t=key, **kw: {
                    "ok": True,
                    "tool": _t,
                    "args": kw,
                    "mock": True,
                    "real": False,
                    "note": "no real local handler; mock fallback",
                }
            )
    # Always register real tools even if not in plan tools (Caller may still see them)
    for key, fn in real_fns.items():
        registry.setdefault(key, fn)
    return registry


def mock_registry(tools: Optional[Iterable[Any]] = None) -> dict[str, Callable[..., Any]]:
    """All-mock registry (default offline path; no filesystem side effects)."""
    names = _tool_names(tools) if tools is not None else list(DEFAULT_ORCH_TOOLS)
    return {
        n: (
            lambda _t=n, **kw: {
                "ok": True,
                "tool": _t,
                "args": kw,
                "mock": True,
                "real": False,
            }
        )
        for n in names
    }


def resolve_registry(
    tools: Optional[Iterable[Any]] = None,
    *,
    real: bool = False,
    workdir: Any = None,
    mock_fallback: bool = True,
) -> dict[str, Callable[..., Any]]:
    """Pick mock or local real read-only registry for run/loop."""
    if real:
        return build_local_registry(
            workdir, tools=tools, mock_fallback=mock_fallback
        )
    return mock_registry(tools)


def format_plan_brief(plan: ToolPlan | dict[str, Any], *, max_steps: int = 8) -> str:
    """Compact one-block brief of a ToolPlan for Orchestrator goal/meta injection."""
    d = plan.to_dict() if isinstance(plan, ToolPlan) else dict(plan or {})
    steps = list(d.get("steps") or [])[: max(1, int(max_steps))]
    lines = [
        f"[multi-LLM pre-plan paper={d.get('paper') or PAPER} "
        f"planner={d.get('planner') or '?'} status={d.get('status')} "
        f"n_steps={d.get('n_steps', len(d.get('steps') or []))}]",
    ]
    for s in steps:
        tool = s.get("tool") if isinstance(s, dict) else getattr(s, "tool", "?")
        sid = s.get("id") if isinstance(s, dict) else getattr(s, "id", "?")
        why = ""
        if isinstance(s, dict):
            why = str(s.get("rationale") or "")
        else:
            why = str(getattr(s, "rationale", "") or "")
        line = f"  {sid}. {tool}"
        if why:
            line += f" — {why[:80]}"
        lines.append(line)
    return "\n".join(lines)


def plan_for_orchestrator(
    task: str,
    *,
    tools: Optional[Iterable[Any]] = None,
    max_steps: int = 5,
    plan_text: Optional[str] = None,
    auto_ready: bool = True,
    planner_name: str = "",
) -> ToolPlan:
    """Dedicated Planner role for Orchestrator handoff (no tool execution).

    Uses the small/offline heuristic Planner by default; pass *plan_text* to
    inject a stronger Planner-LLM JSON response. Never invokes tools.
    """
    catalog: list[Any]
    if tools is not None:
        catalog = list(tools)
    else:
        live = default_tools_from_catalog(max_privilege="read")
        catalog = live if live else list(DEFAULT_ORCH_TOOLS)

    planner = Planner(tools=catalog, max_steps=int(max_steps), auto_ready=auto_ready)
    if plan_text:
        plan = planner.plan_from_text(
            plan_text, task=task, tools=catalog, auto_ready=auto_ready
        )
    else:
        plan = planner.plan(task, tools=catalog, max_steps=max_steps, auto_ready=auto_ready)
    if planner_name:
        plan.planner = str(planner_name)
    plan.meta = dict(plan.meta or {})
    plan.meta["handoff"] = "orchestrator"
    plan.meta["paper"] = PAPER
    return plan


def plan_payload_for_meta(plan: ToolPlan) -> dict[str, Any]:
    """Serialize a plan for Orchestrator envelope / ops job meta (JSON-safe)."""
    d = plan.to_dict()
    # Keep meta lean for envelope: drop bulky step results if any
    lean_steps = []
    for s in d.get("steps") or []:
        lean_steps.append(
            {
                "id": s.get("id"),
                "tool": s.get("tool"),
                "args": s.get("args") or {},
                "rationale": s.get("rationale") or "",
                "status": s.get("status") or STEP_PENDING,
            }
        )
    return {
        "schema": d.get("schema") or SCHEMA,
        "paper": d.get("paper") or PAPER,
        "task": d.get("task") or "",
        "status": d.get("status") or STATUS_DRAFT,
        "planner": d.get("planner") or "heuristic",
        "n_steps": len(lean_steps),
        "steps": lean_steps,
        "tools_available": list(d.get("tools_available") or [])[:40],
        "notes": d.get("notes") or "",
        "brief": format_plan_brief(plan),
        "meta": {
            "handoff": "orchestrator",
            "paper": PAPER,
            **{
                k: v
                for k, v in (d.get("meta") or {}).items()
                if k in ("max_steps", "handoff", "paper", "source")
            },
        },
    }


def plan_and_handoff(
    description: str,
    *,
    workdir: Any = None,
    tools: Optional[Iterable[Any]] = None,
    max_steps: int = 5,
    plan_text: Optional[str] = None,
    require_ready: bool = True,
    agent_mode: str = "fake",
    task_id: Optional[str] = None,
    kind: str = "task",
    wait: bool = False,
    wait_timeout_s: float = 120.0,
    sync_fake: bool = True,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Plan with dedicated Planner, then pass ready plan to Orchestrator.run_task.

    Pattern from arXiv 2401.07324: small specialized Planner decomposes the
    complex task; Orchestrator owns durable execution. Does not execute tools
    in the Planner phase.
    """
    from . import orchestrator as orch

    plan = plan_for_orchestrator(
        description,
        tools=tools,
        max_steps=max_steps,
        plan_text=plan_text,
        auto_ready=True,
    )
    if require_ready and not plan.is_ready():
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "ok": False,
            "error": "planner_produced_no_ready_plan",
            "phase": "plan",
            "plan": plan_payload_for_meta(plan),
            "orchestrator": None,
        }

    o = orch.Orchestrator(workdir)
    status = o.run_task(
        description,
        kind=kind,
        agent_mode=agent_mode,
        task_id=task_id,
        wait=wait,
        wait_timeout_s=wait_timeout_s,
        with_plan=True,
        plan=plan,
        require_plan=require_ready,
        meta=meta,
        sync_fake=sync_fake if agent_mode == "fake" else False,
    )
    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "ok": status.get("status") not in (None, "failed"),
        "error": None,
        "phase": "orchestrator",
        "plan": status.get("plan") or plan_payload_for_meta(plan),
        "orchestrator": status,
    }


# ── MCP / operator dispatch (arXiv 2401.07324 surface) ─────────────────────


def _resolve_tools(
    tools: Optional[Iterable[Any]] = None,
    *,
    tools_csv: str = "",
    max_privilege: str = "read",
) -> list[Any]:
    """Resolve a tool catalog for Planner (explicit list → CSV → live catalog → defaults)."""
    if tools is not None:
        return list(tools)
    raw = str(tools_csv or "").strip()
    if raw:
        return [t.strip() for t in raw.split(",") if t.strip()]
    live = default_tools_from_catalog(max_privilege=max_privilege)
    if live:
        return live
    return list(DEFAULT_ORCH_TOOLS)


def dispatch_action(
    action: str,
    *,
    task: str = "",
    tools: Optional[Iterable[Any]] = None,
    tools_csv: str = "",
    max_steps: int = 5,
    plan_text: Optional[str] = None,
    plan_json: Optional[str] = None,
    auto_ready: bool = True,
    workdir: Any = None,
    task_id: Optional[str] = None,
    agent_mode: str = "fake",
    require_ready: bool = True,
    max_privilege: str = "read",
) -> dict[str, Any]:
    """MCP/CLI unified surface for Planner → Caller / Orchestrator.

    Actions:
      - ``plan``     — Planner only (structured JSON ToolPlan; never calls tools)
      - ``run``      — Planner → mock Caller (no real side effects)
      - ``prompt``   — Planner LLM system prompt block
      - ``validate`` — validate plan_json / plan_text against allowed tools
      - ``handoff``  — Planner → Orchestrator.run_task(with_plan=True)

    Fail-closed: Caller paths never execute tools without a ready plan.
    """
    act = str(action or "plan").strip().lower().replace("-", "_")
    catalog = _resolve_tools(
        tools, tools_csv=tools_csv, max_privilege=max_privilege
    )
    task_s = str(task or "").strip()
    ms = max(1, int(max_steps or 5))

    if act == "plan":
        if not task_s and not (plan_text or plan_json):
            return {
                "schema": SCHEMA,
                "paper": PAPER,
                "ok": False,
                "error": "task required for plan",
                "action": act,
            }
        planner = Planner(tools=catalog, max_steps=ms, auto_ready=auto_ready)
        if plan_text or plan_json:
            plan = planner.plan_from_text(
                str(plan_text or plan_json),
                task=task_s,
                tools=catalog,
                auto_ready=auto_ready,
            )
        else:
            plan = planner.plan(task_s, tools=catalog, max_steps=ms, auto_ready=auto_ready)
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "ok": bool(plan.steps),
            "action": act,
            "phase": "plan",
            "plan": plan.to_dict(),
            "brief": format_plan_brief(plan),
        }

    if act == "run":
        if not task_s and not (plan_text or plan_json):
            return {
                "schema": SCHEMA,
                "paper": PAPER,
                "ok": False,
                "error": "task required for run",
                "action": act,
            }
        names = _tool_names(catalog)
        registry = {
            n: (lambda _t=n, **kw: {"ok": True, "tool": _t, "args": kw, "mock": True})
            for n in names
        }
        agent = MultiLLMToolAgent(tools=catalog, registry=registry, max_steps=ms)
        report = agent.run(
            task_s or "task",
            tools=catalog,
            plan_text=plan_text or plan_json,
            max_steps=ms,
        )
        report["action"] = act
        return report

    if act == "prompt":
        if not task_s:
            return {
                "schema": SCHEMA,
                "paper": PAPER,
                "ok": False,
                "error": "task required for prompt",
                "action": act,
            }
        planner = Planner(tools=catalog)
        block = planner.prompt_block(task_s, tools=catalog)
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "ok": True,
            "action": act,
            "phase": "prompt",
            "prompt": block,
            "n_tools": len(_tool_names(catalog)),
        }

    if act == "validate":
        raw = str(plan_json or plan_text or "").strip()
        if not raw:
            return {
                "schema": SCHEMA,
                "paper": PAPER,
                "ok": False,
                "error": "plan_json or plan_text required for validate",
                "action": act,
            }
        try:
            plan = parse_plan_json(raw)
        except PlanError as e:
            return {
                "schema": SCHEMA,
                "paper": PAPER,
                "ok": False,
                "error": str(e),
                "action": act,
                "phase": "validate",
            }
        if task_s and not plan.task:
            plan.task = task_s
        allowed = _tool_names(catalog) or None
        rep = validate_plan(plan, allowed_tools=allowed, require_steps=True)
        rep["action"] = act
        rep["paper"] = PAPER
        rep["plan"] = plan.to_dict()
        return rep

    if act == "handoff":
        if not task_s:
            return {
                "schema": SCHEMA,
                "paper": PAPER,
                "ok": False,
                "error": "task required for handoff",
                "action": act,
            }
        report = plan_and_handoff(
            task_s,
            workdir=workdir,
            tools=catalog,
            max_steps=ms,
            plan_text=plan_text or plan_json,
            require_ready=require_ready,
            agent_mode=str(agent_mode or "fake"),
            task_id=task_id,
            sync_fake=True,
        )
        report["action"] = act
        return report

    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "ok": False,
        "error": f"unknown action {action!r} (plan|run|prompt|validate|handoff)",
        "action": act,
    }


# ── CLI helpers ────────────────────────────────────────────────────────────


def format_plan(plan: ToolPlan | dict[str, Any]) -> str:
    d = plan.to_dict() if isinstance(plan, ToolPlan) else plan
    lines = [
        f"schema:  {d.get('schema')}",
        f"paper:   {d.get('paper')}",
        f"task:    {d.get('task')}",
        f"status:  {d.get('status')}",
        f"planner: {d.get('planner')}",
        f"steps:   {d.get('n_steps', len(d.get('steps') or []))}",
        "",
    ]
    for s in d.get("steps") or []:
        lines.append(
            f"  [{s.get('id')}] {s.get('tool')}  status={s.get('status')}"
            f"  args={json.dumps(s.get('args') or {}, default=str)}"
        )
        if s.get("rationale"):
            lines.append(f"       why: {s.get('rationale')}")
    return "\n".join(lines)


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"ok:     {report.get('ok')}",
        f"phase:  {report.get('phase')}",
        f"paper:  {report.get('paper')}",
        f"error:  {report.get('error')}",
    ]
    plan = report.get("plan") or {}
    lines.append(f"plan:   status={plan.get('status')} steps={plan.get('n_steps')}")
    summary = report.get("summary") or {}
    if summary:
        lines.append(
            f"calls:  ok={summary.get('n_ok')} failed={summary.get('n_failed')} "
            f"tools={summary.get('tools_used')}"
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m nexus.multi_llm_agent plan|run|validate``."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        prog="nexus.multi_llm_agent",
        description="Planner-then-Caller multi-LLM tool agent (arXiv 2401.07324)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="Planner only — emit structured JSON plan")
    p_plan.add_argument("task", help="task description")
    p_plan.add_argument(
        "--tools",
        default="",
        help="comma-separated tool names (default: sample catalog stubs)",
    )
    p_plan.add_argument("--max-steps", type=int, default=5)
    p_plan.add_argument("--json", action="store_true")
    p_plan.add_argument("--no-ready", action="store_true", help="leave status=draft")

    p_run = sub.add_parser(
        "run",
        help="Planner → Caller pipeline (mock registry; --real for local RO tools)",
    )
    p_run.add_argument("task", help="task description")
    p_run.add_argument("--tools", default="")
    p_run.add_argument("--max-steps", type=int, default=5)
    p_run.add_argument("--json", action="store_true")
    p_run.add_argument(
        "--real",
        action="store_true",
        help="use local read-only tool registry (marketplace/status/factory builtins)",
    )
    p_run.add_argument(
        "--workdir",
        default="",
        help="project root for --real tools (default: cwd / NEXUS_PROJECT_ROOT)",
    )

    p_val = sub.add_parser("validate", help="validate plan JSON from stdin or --file")
    p_val.add_argument("--file", default="", help="path to plan JSON")
    p_val.add_argument("--tools", default="", help="allowed tools (comma-separated)")
    p_val.add_argument("--json", action="store_true")

    p_ho = sub.add_parser(
        "handoff",
        help="Planner → Orchestrator: plan then run_task(with_plan) [arXiv 2401.07324]",
    )
    p_ho.add_argument("task", help="complex task description")
    p_ho.add_argument("--tools", default="")
    p_ho.add_argument("--max-steps", type=int, default=5)
    p_ho.add_argument("--task-id", default="", dest="task_id")
    p_ho.add_argument(
        "--agent-mode",
        default="fake",
        choices=sorted({"fake", "demo", "auto", "bus"}),
        dest="agent_mode",
    )
    p_ho.add_argument("--json", action="store_true")
    p_ho.add_argument(
        "--workdir",
        default="",
        help="project root for Orchestrator (default: cwd / NEXUS_PROJECT_ROOT)",
    )

    args = ap.parse_args(list(argv) if argv is not None else None)

    def _tools_list() -> list[str]:
        raw = str(getattr(args, "tools", "") or "").strip()
        if raw:
            return [t.strip() for t in raw.split(",") if t.strip()]
        return list(DEFAULT_ORCH_TOOLS)

    if args.cmd == "plan":
        tools = _tools_list()
        planner = Planner(tools=tools, max_steps=int(args.max_steps), auto_ready=not args.no_ready)
        plan = planner.plan(args.task, auto_ready=not args.no_ready)
        if args.json:
            print(plan.to_json())
        else:
            print(format_plan(plan))
        return 0 if plan.steps else 1

    if args.cmd == "run":
        tools = _tools_list()
        use_real = bool(getattr(args, "real", False))
        wd = str(getattr(args, "workdir", "") or "").strip() or None
        registry = resolve_registry(
            tools, real=use_real, workdir=wd, mock_fallback=True
        )
        agent = MultiLLMToolAgent(tools=tools, registry=registry, max_steps=int(args.max_steps))
        report = agent.run(args.task)
        report["registry"] = "real" if use_real else "mock"
        if use_real:
            report["workdir"] = str(_workdir_path(wd))
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(format_report(report))
            print()
            if report.get("plan"):
                print(format_plan(report["plan"]))
        return 0 if report.get("ok") else 1

    if args.cmd == "handoff":
        tools = _tools_list()
        wd = str(getattr(args, "workdir", "") or "").strip() or None
        tid = str(getattr(args, "task_id", "") or "").strip() or None
        report = plan_and_handoff(
            args.task,
            workdir=wd,
            tools=tools,
            max_steps=int(args.max_steps),
            agent_mode=str(args.agent_mode),
            task_id=tid,
            sync_fake=True,
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(format_report(report))
            if report.get("plan"):
                print()
                print(format_plan(report["plan"]))
            orch = report.get("orchestrator") or {}
            if orch:
                print(
                    f"\norchestrator: task_id={orch.get('task_id')} "
                    f"status={orch.get('status')} pre_planned={orch.get('pre_planned')}"
                )
        return 0 if report.get("ok") and (report.get("orchestrator") or {}).get("status") != "failed" else 1

    if args.cmd == "validate":
        if args.file:
            text = open(args.file, encoding="utf-8").read()
        else:
            text = sys.stdin.read()
        try:
            plan = parse_plan_json(text)
        except PlanError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        allowed = _tools_list() if args.tools else None
        rep = validate_plan(plan, allowed_tools=allowed)
        if args.json or True:
            print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1

    return 2


__all__ = [
    "SCHEMA",
    "PAPER",
    "PlanError",
    "CallGateError",
    "PlanStep",
    "ToolPlan",
    "Planner",
    "Caller",
    "CallResult",
    "MultiLLMToolAgent",
    "parse_plan_json",
    "validate_plan",
    "mark_ready",
    "heuristic_plan",
    "summarize_run",
    "default_tools_from_catalog",
    "format_plan",
    "format_plan_brief",
    "format_report",
    "plan_for_orchestrator",
    "plan_payload_for_meta",
    "plan_and_handoff",
    "dispatch_action",
    "DEFAULT_ORCH_TOOLS",
    "REAL_LOCAL_TOOLS",
    "build_local_registry",
    "resolve_registry",
    "mock_registry",
    "main",
    "STATUS_DRAFT",
    "STATUS_READY",
    "STATUS_EXECUTING",
    "STATUS_DONE",
    "STATUS_FAILED",
]


if __name__ == "__main__":
    raise SystemExit(main())
