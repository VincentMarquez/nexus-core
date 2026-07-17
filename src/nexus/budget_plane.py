"""Budget-aware control plane: FutureWeaver × mission-control.

Cross-pattern hybrid (portfolio novel):

  arXiv:2512.11213v2 FutureWeaver
      plan / track / hard-limit multi-agent test-time compute
                ×
  builderz-labs/mission-control (shape only)
      SQLite-backed jobs + spend attribution + agent cost rollups
      + sticky task governance on the ops plane

Binds :class:`budget_alloc.BudgetAllocator` state to
:class:`ops_store.OpsStore` job rows so compute quotas survive process
restarts and operator boards can show per-agent spend vs plan.

Schema: ``nexus.budget_plane/v1``

Does **not** vendor FutureWeaver or mission-control trees.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .budget_alloc import (
    PAPER as FUTUREWEAVER_PAPER,
    AllocationExhausted,
    BudgetAllocator,
    format_brief,
    plan_for_orchestrator,
)
from .ops_store import OpsError, OpsStore

SCHEMA = "nexus.budget_plane/v1"
PAPER = FUTUREWEAVER_PAPER  # arxiv:2512.11213v2
SOURCE_PATTERN = "builderz-labs/mission-control"
META_KEY = "budget_alloc"
PLANE_LABEL = "budget_plane"

ACTIONS = frozenset(
    {
        "plan",
        "status",
        "record",
        "report",
        "finish",
        "rebalance",
        "brief",
    }
)


class BudgetPlaneError(RuntimeError):
    """Invalid budget-plane operation (missing job, exhausted share, …)."""

    def __init__(self, message: str, *, code: str = "budget_plane_error") -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "BudgetPlaneError",
            "code": self.code,
            "message": str(self),
        }


def _root(workdir: Optional[Path | str] = None) -> Path:
    import os

    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def agent_source(agent: str) -> str:
    """Canonical spend.source for per-agent attribution (mission-control shape)."""
    a = str(agent or "").strip() or "unknown"
    return f"agent:{a}"


def parse_agent_source(source: str) -> Optional[str]:
    s = str(source or "").strip()
    if s.startswith("agent:"):
        name = s[6:].strip()
        return name or None
    return None


def agent_spend_report(
    rows: Sequence[dict[str, Any]],
    *,
    alloc: Optional[BudgetAllocator] = None,
) -> dict[str, Any]:
    """Mission-control *agents* rollup from spend rows + optional plan quotas.

    Groups ``source=agent:<name>`` (and ``meta.agent``) into per-agent token stats,
    then overlays planned max/remaining when *alloc* is provided.
    """
    from .ops_store import calculate_stats

    by_agent: dict[str, list[dict[str, Any]]] = {}
    unattributed: list[dict[str, Any]] = []
    for r in rows:
        agent = None
        meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
        if meta and meta.get("agent"):
            agent = str(meta.get("agent")).strip() or None
        if agent is None:
            agent = parse_agent_source(str(r.get("source") or ""))
        if agent:
            by_agent.setdefault(agent, []).append(r)
        else:
            unattributed.append(r)

    agents_out: dict[str, dict[str, Any]] = {}
    for name, recs in by_agent.items():
        stats = calculate_stats(recs)
        entry: dict[str, Any] = {
            "agent": name,
            "stats": stats,
            "request_count": stats["request_count"],
            "tokens_used": stats["total_tokens"],
        }
        if alloc is not None and name in alloc.agents:
            q = alloc.agents[name]
            entry["planned_max_tokens"] = int(q.max_tokens)
            entry["remaining_tokens"] = q.remaining_tokens()
            entry["weight"] = float(q.weight)
            entry["finished"] = bool(q.finished)
            entry["exhausted"] = q.exhausted()
            entry["alloc_tokens_used"] = int(q.tokens_used)
        agents_out[name] = entry

    # Include planned agents with zero spend so the board shows full roster
    if alloc is not None:
        for name, q in alloc.agents.items():
            if name in agents_out:
                continue
            agents_out[name] = {
                "agent": name,
                "stats": calculate_stats([]),
                "request_count": 0,
                "tokens_used": 0,
                "planned_max_tokens": int(q.max_tokens),
                "remaining_tokens": q.remaining_tokens(),
                "weight": float(q.weight),
                "finished": bool(q.finished),
                "exhausted": q.exhausted(),
                "alloc_tokens_used": int(q.tokens_used),
            }

    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "summary": calculate_stats(list(rows)),
        "agents": agents_out,
        "unattributed": calculate_stats(unattributed),
        "n_agents": len(agents_out),
    }


class BudgetPlane:
    """SQLite-backed multi-agent compute budget governance.

    Lifecycle:
      1. ``plan`` — FutureWeaver split → job.meta.budget_alloc + running job
      2. ``record`` — hard-limit consume + spend row (agent:name)
      3. ``finish`` / ``rebalance`` — modular residual reclaim
      4. ``status`` / ``report`` — operator board (plan + spend + agents)
    """

    def __init__(self, store: OpsStore) -> None:
        self.store = store

    # ── plan / load ─────────────────────────────────────────────────────

    def plan(
        self,
        job_id: str,
        *,
        total_tokens: int,
        strategy: str = "weighted",
        agents: Optional[Iterable[str]] = None,
        weights: Optional[dict[str, float]] = None,
        total_steps: Optional[int] = None,
        hard: bool = True,
        reserved_fraction: float = 0.5,
        title: str = "",
        goal: str = "",
        kind: str = "task",
        status: str = "running",
    ) -> dict[str, Any]:
        """Plan allocation and bind full snapshot to the ops job row."""
        jid = str(job_id or "").strip()
        if not jid:
            raise BudgetPlaneError("job_id required", code="job_id_required")
        total = int(total_tokens)
        if total <= 0:
            raise BudgetPlaneError(
                "total_tokens must be > 0", code="invalid_total_tokens"
            )
        alloc = plan_for_orchestrator(
            total_tokens=total,
            agents=agents,
            strategy=strategy,
            weights=weights,
            total_steps=total_steps,
            hard=hard,
            reserved_fraction=reserved_fraction,
        )
        return self.bind(jid, alloc, title=title, goal=goal, kind=kind, status=status)

    def bind(
        self,
        job_id: str,
        alloc: BudgetAllocator,
        *,
        title: str = "",
        goal: str = "",
        kind: str = "task",
        status: str = "running",
        extra_meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Persist *alloc* on job meta (create job if needed)."""
        jid = str(job_id or "").strip()
        if not jid:
            raise BudgetPlaneError("job_id required", code="job_id_required")
        snap = alloc.to_meta()
        meta: dict[str, Any] = {
            META_KEY: snap,
            "budget_plane": True,
            "budget_paper": PAPER,
            "budget_schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            **(extra_meta or {}),
        }
        job = self.store.ensure_job(
            jid,
            kind=kind,
            title=title or jid,
            status=status,
            goal=goal,
            meta=meta,
        )
        # ensure_job merges meta; if job existed with empty title, keep bind meta
        # Force-write full allocator (ensure merge is enough when new; for old
        # jobs re-merge META_KEY).
        existing = self.store.get(jid) or job
        m = dict(existing.get("meta") or {})
        m[META_KEY] = snap
        m["budget_plane"] = True
        m["budget_paper"] = PAPER
        m["budget_schema"] = SCHEMA
        m["source_pattern"] = SOURCE_PATTERN
        if extra_meta:
            m.update(extra_meta)
        self.store.upsert_job(
            jid,
            kind=str(existing.get("kind") or kind),
            title=str(existing.get("title") or title or jid),
            status=str(existing.get("status") or status),
            goal=str(existing.get("goal") or goal),
            meta=m,
        )
        job = self.store.get(jid) or job
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "job_id": jid,
            "job": job,
            "budget_alloc": alloc.snapshot(),
            "brief": format_brief(alloc),
            "bound": True,
        }

    def load_alloc(self, job_id: str) -> BudgetAllocator:
        """Load BudgetAllocator from job.meta.budget_alloc (fail-closed)."""
        jid = str(job_id or "").strip()
        if not jid:
            raise BudgetPlaneError("job_id required", code="job_id_required")
        job = self.store.get(jid)
        if job is None:
            raise BudgetPlaneError(f"job not found: {jid}", code="job_not_found")
        meta = job.get("meta") if isinstance(job.get("meta"), dict) else {}
        raw = meta.get(META_KEY) if isinstance(meta, dict) else None
        if not isinstance(raw, dict) or not raw.get("agents"):
            raise BudgetPlaneError(
                f"no compute budget planned for job {jid}",
                code="no_budget_alloc",
            )
        return BudgetAllocator.from_dict(raw)

    def _save_alloc(self, job_id: str, alloc: BudgetAllocator) -> dict[str, Any]:
        jid = str(job_id)
        job = self.store.get(jid)
        if job is None:
            raise BudgetPlaneError(f"job not found: {jid}", code="job_not_found")
        m = dict(job.get("meta") or {})
        m[META_KEY] = alloc.to_meta()
        m["budget_plane"] = True
        m["budget_paper"] = PAPER
        m["budget_schema"] = SCHEMA
        self.store.upsert_job(
            jid,
            kind=str(job.get("kind") or "task"),
            title=str(job.get("title") or jid),
            status=str(job.get("status") or "running"),
            goal=str(job.get("goal") or ""),
            meta=m,
        )
        return self.store.get(jid) or job

    # ── record / finish / rebalance ─────────────────────────────────────

    def record(
        self,
        job_id: str,
        agent: str,
        *,
        tokens: int = 0,
        steps: int = 0,
        finish: bool = False,
        rebalance: bool = False,
        dual_write_usage: bool = False,
        kind: str = "task",
    ) -> dict[str, Any]:
        """Consume against FutureWeaver share; attribute spend on ops plane.

        Hard-fails with ``BudgetPlaneError(code=budget_exhausted)`` when the
        agent or pool would exceed its planned allocation.
        """
        jid = str(job_id or "").strip()
        agent_id = str(agent or "").strip()
        if not jid:
            raise BudgetPlaneError("job_id required", code="job_id_required")
        if not agent_id:
            raise BudgetPlaneError("agent required", code="agent_required")
        tok = max(0, int(tokens or 0))
        stp = max(0, int(steps or 0))
        alloc = self.load_alloc(jid)
        try:
            receipt = alloc.consume(agent_id, tokens=tok, steps=stp)
        except AllocationExhausted as e:
            raise BudgetPlaneError(str(e), code="budget_exhausted") from e
        except KeyError as e:
            raise BudgetPlaneError(str(e), code="unknown_agent") from e

        finish_info = None
        rebalance_info = None
        if finish:
            finish_info = alloc.finish(agent_id, reclaim=True)
        if rebalance:
            rebalance_info = alloc.rebalance()

        job = self._save_alloc(jid, alloc)
        spend_row = None
        if tok > 0:
            spend_row = self.store.record_spend(
                jid,
                tok,
                source=agent_source(agent_id),
                label=PLANE_LABEL,
                meta={
                    "agent": agent_id,
                    "steps": stp,
                    "schema": SCHEMA,
                    "paper": PAPER,
                },
                dual_write_usage=dual_write_usage,
                ensure=True,
                kind=kind,
            )
            job = spend_row.get("job") or self.store.get(jid) or job

        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "job_id": jid,
            "agent": agent_id,
            "receipt": receipt,
            "finish": finish_info,
            "rebalance": rebalance_info,
            "spend": spend_row,
            "budget_alloc": alloc.snapshot(),
            "brief": format_brief(alloc),
            "job": job,
        }

    def finish_agent(
        self,
        job_id: str,
        agent: str,
        *,
        rebalance: bool = True,
    ) -> dict[str, Any]:
        """Mark agent finished; reclaim modular share; optional residual rebalance."""
        return self.record(
            job_id,
            agent,
            tokens=0,
            steps=0,
            finish=True,
            rebalance=rebalance,
        )

    def rebalance(self, job_id: str) -> dict[str, Any]:
        """Redistribute residual pool to still-active agents (FutureWeaver)."""
        jid = str(job_id or "").strip()
        alloc = self.load_alloc(jid)
        info = alloc.rebalance()
        job = self._save_alloc(jid, alloc)
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "job_id": jid,
            "rebalance": info,
            "budget_alloc": alloc.snapshot(),
            "brief": format_brief(alloc),
            "job": job,
        }

    def set_job_status(
        self,
        job_id: str,
        status: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Sticky terminal governance on the bound job (mission-control)."""
        jid = str(job_id or "").strip()
        try:
            job = self.store.set_status(jid, status, force=force)
        except OpsError as e:
            raise BudgetPlaneError(str(e), code="ops_error") from e
        return {
            "schema": SCHEMA,
            "job_id": jid,
            "job": job,
            "status": (job or {}).get("status"),
        }

    # ── status / report ─────────────────────────────────────────────────

    def status(self, job_id: str) -> dict[str, Any]:
        """Operator status: plan snapshot + spend summary + agent board."""
        jid = str(job_id or "").strip()
        job = self.store.get(jid)
        if job is None:
            raise BudgetPlaneError(f"job not found: {jid}", code="job_not_found")
        alloc: Optional[BudgetAllocator] = None
        try:
            alloc = self.load_alloc(jid)
        except BudgetPlaneError:
            alloc = None
        rows = self.store.spend_rows(jid, limit=2000)
        report = agent_spend_report(rows, alloc=alloc)
        out: dict[str, Any] = {
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "job_id": jid,
            "job": job,
            "budget_alloc": alloc.snapshot() if alloc else None,
            "brief": format_brief(alloc) if alloc else "",
            "agent_report": report,
            "spend_summary": report["summary"],
        }
        return out

    def report(self, job_id: Optional[str] = None, *, limit: int = 500) -> dict[str, Any]:
        """Agent cost board (one job or all recent spend)."""
        jid = str(job_id or "").strip() or None
        rows = self.store.spend_rows(jid, limit=limit)
        alloc: Optional[BudgetAllocator] = None
        if jid:
            try:
                alloc = self.load_alloc(jid)
            except BudgetPlaneError:
                alloc = None
        base = agent_spend_report(rows, alloc=alloc)
        base["job_id"] = jid or ""
        if jid:
            base["job"] = self.store.get(jid)
        if alloc is not None:
            base["budget_alloc"] = alloc.snapshot()
            base["brief"] = format_brief(alloc)
        return base


def dispatch(
    action: str,
    *,
    workdir: Optional[Path | str] = None,
    job_id: str = "",
    agent: str = "",
    tokens: int = 0,
    steps: int = 0,
    total_tokens: int = 0,
    strategy: str = "weighted",
    agents: Optional[Any] = None,
    hard: bool = True,
    finish: bool = False,
    rebalance: bool = False,
    status: str = "",
    title: str = "",
    goal: str = "",
    kind: str = "task",
    limit: int = 500,
) -> dict[str, Any]:
    """Unified surface for CLI / MCP (mission-control action dispatch)."""
    act = str(action or "status").strip().lower()
    if act not in ACTIONS:
        raise BudgetPlaneError(
            f"unknown action {action!r}; allowed: {sorted(ACTIONS)}",
            code="unknown_action",
        )
    root = _root(workdir)

    # Pure plan (no SQLite) when job_id omitted and action=plan|brief
    if act in ("plan", "brief") and not str(job_id or "").strip():
        if act == "brief" and total_tokens <= 0:
            raise BudgetPlaneError(
                "total_tokens required for plan/brief without job_id",
                code="invalid_total_tokens",
            )
        roster = _parse_agents(agents)
        total = int(total_tokens)
        if total <= 0:
            raise BudgetPlaneError(
                "total_tokens must be > 0", code="invalid_total_tokens"
            )
        alloc = plan_for_orchestrator(
            total_tokens=total,
            agents=roster,
            strategy=strategy,
            hard=hard,
        )
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "action": act,
            "bound": False,
            "budget_alloc": alloc.snapshot(),
            "brief": format_brief(alloc),
        }

    with OpsStore.open(root) as store:
        plane = BudgetPlane(store)
        if act == "plan":
            roster = _parse_agents(agents)
            return plane.plan(
                job_id,
                total_tokens=int(total_tokens),
                strategy=strategy,
                agents=roster,
                hard=hard,
                title=title,
                goal=goal,
                kind=kind,
            )
        if act == "status":
            if not job_id:
                raise BudgetPlaneError("job_id required", code="job_id_required")
            return plane.status(job_id)
        if act == "brief":
            if not job_id:
                raise BudgetPlaneError("job_id required", code="job_id_required")
            st = plane.status(job_id)
            return {
                "schema": SCHEMA,
                "job_id": job_id,
                "brief": st.get("brief") or "",
                "budget_alloc": st.get("budget_alloc"),
            }
        if act == "record":
            if not job_id:
                raise BudgetPlaneError("job_id required", code="job_id_required")
            return plane.record(
                job_id,
                agent,
                tokens=int(tokens or 0),
                steps=int(steps or 0),
                finish=finish,
                rebalance=rebalance,
                kind=kind,
            )
        if act == "report":
            return plane.report(job_id or None, limit=int(limit or 500))
        if act == "finish":
            if not job_id:
                raise BudgetPlaneError("job_id required", code="job_id_required")
            if agent:
                return plane.finish_agent(job_id, agent, rebalance=rebalance or True)
            st = str(status or "completed")
            return plane.set_job_status(job_id, st)
        if act == "rebalance":
            if not job_id:
                raise BudgetPlaneError("job_id required", code="job_id_required")
            return plane.rebalance(job_id)
    raise BudgetPlaneError(f"unhandled action: {act}", code="unknown_action")


def _parse_agents(agents: Any) -> Optional[list[str]]:
    if agents is None or agents == "":
        return None
    if isinstance(agents, str):
        return [a.strip() for a in agents.split(",") if a.strip()]
    if isinstance(agents, (list, tuple)):
        return [str(a).strip() for a in agents if str(a).strip()]
    return None


def format_operator_table(status_payload: dict[str, Any]) -> str:
    """Human one-screen table for CLI."""
    lines: list[str] = []
    brief = str(status_payload.get("brief") or "").strip()
    if brief:
        lines.append(brief)
    agents = (status_payload.get("agent_report") or {}).get("agents") or {}
    if agents:
        lines.append("agent spend board:")
        lines.append(f"  {'AGENT':<14} {'USED':>8} {'PLAN':>8} {'REM':>8}  flags")
        for name in sorted(agents.keys()):
            a = agents[name]
            plan_max = a.get("planned_max_tokens")
            rem = a.get("remaining_tokens")
            flags = []
            if a.get("finished"):
                flags.append("done")
            if a.get("exhausted"):
                flags.append("EXHAUSTED")
            lines.append(
                f"  {name:<14} {int(a.get('tokens_used') or 0):>8} "
                f"{str(plan_max if plan_max is not None else '-'):>8} "
                f"{str(rem if rem is not None else '-'):>8}  "
                f"{','.join(flags)}"
            )
    return "\n".join(lines)
