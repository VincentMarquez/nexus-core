"""Domain-MCP-aware Planner: arXiv 2401.07324 × IBM/AssetOpsBench.

Paper: *Small LLMs Are Weak Tool Learners: A Multi-LLM Agent*
https://arxiv.org/abs/2401.07324v3

GitHub pattern (shape only — not a vendored tree):
  IBM/AssetOpsBench — Industry 4.0 multi-agent benchmark with domain MCP
  servers (iot, fmsr, tsfm, wo, vibration, utilities) and a plan-execute
  orchestrator that assigns server + tool (+ dependencies) per step.

Novel hybrid (portfolio cross_pattern):

  domain MCP catalog (iot / fmsr / tsfm / wo / vibration / utilities)
                │
                ▼
         ┌──────────┐   structured JSON plan
         │  Planner │ ──► steps = ordered aob.<server>.<tool> calls
         └──────────┘   (small/offline role — no industrial backends)
                │
                ├── ready plan ──► Caller (mock / offline registry)
                └── ready plan ──► Orchestrator.run_task (with_plan)

Small specialized Planner decomposes complex asset-ops / multi-domain tasks
against the AssetOpsBench-shaped domain MCP catalog *before* durable
execution. Never vendors CouchDB, industrial fixtures, or the upstream tree.
Reuses in-tree ``multi_llm_agent`` Planner/Caller.

Offline-first: heuristic Planner for tests/smoke; inject LLM JSON via plan_text;
deterministic ``diagnostic_workflow_plan`` for failure-mode / work-order walks.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import multi_llm_agent as mla

SCHEMA = "nexus.assetops_planner/v1"
PAPER = mla.PAPER  # arxiv:2401.07324v3
SOURCE_PATTERN = "IBM/AssetOpsBench"
TOOL_PREFIX = "aob"

# Stable domain server ids (AssetOpsBench mcphub shape)
SERVER_IOT = "iot"
SERVER_FMSR = "fmsr"
SERVER_TSFM = "tsfm"
SERVER_WO = "wo"
SERVER_VIBRATION = "vibration"
SERVER_UTILITIES = "utilities"

DOMAIN_SERVER_IDS: tuple[str, ...] = (
    SERVER_IOT,
    SERVER_FMSR,
    SERVER_TSFM,
    SERVER_WO,
    SERVER_VIBRATION,
    SERVER_UTILITIES,
)


class AssetOpsPlanError(ValueError):
    """Domain MCP catalog empty or plan invalid for AssetOps handoff."""


# ── domain catalog (AssetOpsBench MCP servers → Planner tools) ──────────────


# Lite tool signatures (pattern only; not full industrial schemas).
# privilege: read tools are default for offline smoke; write is explicit.
_DOMAIN_TOOLS: dict[str, tuple[dict[str, Any], ...]] = {
    SERVER_UTILITIES: (
        {
            "tool": "current_date_time",
            "description": "Return current UTC date/time (utilities context).",
            "params": [],
            "privilege": "read",
            "kind": "context",
        },
        {
            "tool": "json_reader",
            "description": "Read a local JSON fixture by file name (utilities).",
            "params": ["file_name"],
            "privilege": "read",
            "kind": "context",
        },
    ),
    SERVER_IOT: (
        {
            "tool": "sites",
            "description": "List site identifiers in the asset registry.",
            "params": [],
            "privilege": "read",
            "kind": "discovery",
        },
        {
            "tool": "assets",
            "description": "List assets at a site with compact metadata.",
            "params": ["site_name", "assettype"],
            "privilege": "read",
            "kind": "discovery",
        },
        {
            "tool": "asset_detail",
            "description": "Registry details and sensor count for one asset.",
            "params": ["site_name", "asset_id"],
            "privilege": "read",
            "kind": "discovery",
        },
        {
            "tool": "installed_sensors",
            "description": "List sensor names assigned to an asset.",
            "params": ["site_name", "asset_id"],
            "privilege": "read",
            "kind": "discovery",
        },
        {
            "tool": "latest_reading",
            "description": "Newest telemetry record for an asset/sensor.",
            "params": ["site_name", "asset_id", "sensor"],
            "privilege": "read",
            "kind": "telemetry",
        },
        {
            "tool": "history",
            "description": "Chronological telemetry observations (windowed).",
            "params": ["site_name", "asset_id", "start", "end", "sensors", "limit"],
            "privilege": "read",
            "kind": "telemetry",
        },
        {
            "tool": "sensor_stats",
            "description": "Per-sensor numeric stats over a time window.",
            "params": ["site_name", "asset_id", "sensor", "start", "end"],
            "privilege": "read",
            "kind": "telemetry",
        },
    ),
    SERVER_FMSR: (
        {
            "tool": "get_failure_modes",
            "description": "Known failure modes for an asset class (FMEA).",
            "params": ["asset_class"],
            "privilege": "read",
            "kind": "diagnosis",
        },
        {
            "tool": "generate_failure_modes",
            "description": "Generate/extend failure-mode list (LLM-use shape).",
            "params": ["asset_class", "max_modes"],
            "privilege": "read",
            "kind": "diagnosis",
        },
        {
            "tool": "generate_failure_mode_sensor_mapping",
            "description": "Score failure-mode ↔ sensor relevancy mapping.",
            "params": ["asset_class", "failure_modes", "sensors"],
            "privilege": "read",
            "kind": "diagnosis",
        },
    ),
    SERVER_TSFM: (
        {
            "tool": "forecasting",
            "description": "Time-series foundation model forecast for a sensor.",
            "params": ["asset_id", "sensor", "horizon"],
            "privilege": "read",
            "kind": "analytics",
        },
        {
            "tool": "anomaly_detection",
            "description": "Detect anomalies in recent sensor history.",
            "params": ["asset_id", "sensor", "window"],
            "privilege": "read",
            "kind": "analytics",
        },
        {
            "tool": "data_quality",
            "description": "Data-quality score for a telemetry stream.",
            "params": ["asset_id", "sensor"],
            "privilege": "read",
            "kind": "analytics",
        },
    ),
    SERVER_WO: (
        {
            "tool": "list_workorders",
            "description": "List work orders filtered by asset/site/status.",
            "params": ["site_name", "asset_id", "status", "limit"],
            "privilege": "read",
            "kind": "workorder",
        },
        {
            "tool": "get_workorder",
            "description": "Fetch one work order by id.",
            "params": ["workorder_id"],
            "privilege": "read",
            "kind": "workorder",
        },
        {
            "tool": "create_workorder",
            "description": "Create a maintenance work order (write).",
            "params": ["site_name", "asset_id", "title", "priority", "failure_code"],
            "privilege": "write",
            "kind": "workorder",
        },
        {
            "tool": "update_workorder_status",
            "description": "Update work-order status (write).",
            "params": ["workorder_id", "status"],
            "privilege": "write",
            "kind": "workorder",
        },
    ),
    SERVER_VIBRATION: (
        {
            "tool": "fft_analysis",
            "description": "FFT vibration spectrum for a bearing/machine.",
            "params": ["asset_id", "axis"],
            "privilege": "read",
            "kind": "vibration",
        },
        {
            "tool": "envelope_analysis",
            "description": "Envelope analysis for bearing fault frequencies.",
            "params": ["asset_id", "axis"],
            "privilege": "read",
            "kind": "vibration",
        },
        {
            "tool": "fault_detection",
            "description": "Vibration-based fault detection summary.",
            "params": ["asset_id"],
            "privilege": "read",
            "kind": "vibration",
        },
    ),
}


def tool_id(server: str, tool: str) -> str:
    """Stable Planner tool id: ``aob.<server>.<tool>``."""
    s = str(server or "").strip().lower()
    t = str(tool or "").strip()
    if not s or not t:
        raise AssetOpsPlanError("server and tool must be non-empty")
    return f"{TOOL_PREFIX}.{s}.{t}"


def parse_tool_id(name: str) -> dict[str, str]:
    """Inverse of :func:`tool_id` (best-effort)."""
    raw = str(name or "").strip()
    parts = raw.split(".")
    if len(parts) >= 3 and parts[0] == TOOL_PREFIX:
        return {
            "prefix": parts[0],
            "server": parts[1],
            "tool": ".".join(parts[2:]),
            "name": raw,
        }
    if len(parts) == 2:
        return {
            "prefix": "",
            "server": parts[0],
            "tool": parts[1],
            "name": raw,
        }
    return {"prefix": "", "server": "", "tool": raw, "name": raw}


def list_domain_servers() -> list[dict[str, Any]]:
    """Catalog of offline domain MCP servers (AssetOpsBench mcphub shape)."""
    out: list[dict[str, Any]] = []
    for sid in DOMAIN_SERVER_IDS:
        tools = _DOMAIN_TOOLS.get(sid) or ()
        out.append(
            {
                "id": sid,
                "n_tools": len(tools),
                "tools": [str(t["tool"]) for t in tools],
                "description": {
                    SERVER_IOT: "IoT asset registry and telemetry",
                    SERVER_FMSR: "Failure mode and sensor relations",
                    SERVER_TSFM: "Time-series foundation model analytics",
                    SERVER_WO: "Work order lifecycle",
                    SERVER_VIBRATION: "Vibration diagnostics",
                    SERVER_UTILITIES: "Utilities (time, JSON fixtures)",
                }.get(sid, sid),
                "source": SOURCE_PATTERN,
            }
        )
    return out


def domain_mcp_as_tools(
    *,
    servers: Optional[Sequence[str]] = None,
    max_privilege: Optional[str] = None,
    include_write: bool = True,
) -> list[dict[str, Any]]:
    """Build a Planner tool catalog from AssetOpsBench-shaped domain MCP servers.

    Each entry is structure-only until :func:`plan_and_run` / Caller executes
    against a mock or injected registry. No CouchDB / industrial backends.
    """
    want = {str(s).strip().lower() for s in (servers or DOMAIN_SERVER_IDS) if s}
    if not want:
        want = set(DOMAIN_SERVER_IDS)

    priv_rank = {"read": 0, "write": 1, "admin": 2}
    max_rank = None
    if max_privilege is not None:
        max_rank = priv_rank.get(str(max_privilege).strip().lower(), 0)

    tools: list[dict[str, Any]] = []
    for sid in DOMAIN_SERVER_IDS:
        if sid not in want:
            continue
        for spec in _DOMAIN_TOOLS.get(sid) or ():
            priv = str(spec.get("privilege") or "read").lower()
            if not include_write and priv != "read":
                continue
            if max_rank is not None and priv_rank.get(priv, 0) > max_rank:
                continue
            name = tool_id(sid, str(spec["tool"]))
            tools.append(
                {
                    "name": name,
                    "description": (
                        f"[{sid}] {spec.get('description') or spec['tool']}"
                    ),
                    "server": sid,
                    "tool": str(spec["tool"]),
                    "privilege": priv,
                    "kind": str(spec.get("kind") or "domain"),
                    "params": list(spec.get("params") or []),
                    "domain_mcp": True,
                    "source": SOURCE_PATTERN,
                }
            )
    return tools


def catalog_summary(tools: Optional[Sequence[dict[str, Any]]] = None) -> dict[str, Any]:
    """Compact catalog stats for plan meta / CLI."""
    tools = list(tools) if tools is not None else domain_mcp_as_tools()
    by_server: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for t in tools:
        s = str(t.get("server") or "other")
        k = str(t.get("kind") or "other")
        by_server[s] = by_server.get(s, 0) + 1
        by_kind[k] = by_kind.get(k, 0) + 1
    return {
        "n_tools": len(tools),
        "n_servers": len(by_server),
        "by_server": dict(sorted(by_server.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "names": [str(t.get("name") or "") for t in tools],
        "source_pattern": SOURCE_PATTERN,
    }


# ── deterministic diagnostic workflow (AssetOps plan-execute shape) ─────────


def diagnostic_workflow_plan(
    task: str,
    *,
    site_name: str = "MAIN",
    asset_id: str = "asset-1",
    asset_class: str = "chiller",
    sensor: str = "temperature",
    include_vibration: bool = False,
    include_workorder_write: bool = False,
    auto_ready: bool = True,
) -> mla.ToolPlan:
    """Deterministic multi-domain diagnosis walk as a ready plan.

    Mirrors AssetOpsBench plan-execute industrial troubleshooting order::

        utilities.context → iot.discovery → iot.telemetry
        → fmsr.failure_modes → tsfm.anomaly → [vibration]
        → wo.list → [wo.create]

    Planner still does not call MCP; Caller / :func:`plan_and_run` does.
    """
    task = str(task or "").strip()
    if not task:
        raise AssetOpsPlanError("task must be non-empty")

    steps: list[mla.PlanStep] = []
    n = 0

    def add(
        server: str,
        tool: str,
        args: dict[str, Any],
        why: str,
        *,
        depends_on: Optional[list[int]] = None,
    ) -> int:
        nonlocal n
        n += 1
        tid = tool_id(server, tool)
        step_args = dict(args)
        step_args.setdefault("server", server)
        step_args.setdefault("domain_tool", tool)
        if depends_on:
            step_args["depends_on"] = list(depends_on)
        steps.append(
            mla.PlanStep(
                id=n,
                tool=tid,
                args=step_args,
                rationale=why,
                status=mla.STEP_PENDING,
            )
        )
        return n

    s_ctx = add(
        SERVER_UTILITIES,
        "current_date_time",
        {},
        "establish UTC context (utilities)",
    )
    s_sites = add(
        SERVER_IOT,
        "sites",
        {},
        "discover sites in asset registry",
        depends_on=[s_ctx],
    )
    s_assets = add(
        SERVER_IOT,
        "assets",
        {"site_name": site_name},
        f"list assets at site={site_name}",
        depends_on=[s_sites],
    )
    s_detail = add(
        SERVER_IOT,
        "asset_detail",
        {"site_name": site_name, "asset_id": asset_id},
        f"inspect asset registry detail for {asset_id}",
        depends_on=[s_assets],
    )
    s_read = add(
        SERVER_IOT,
        "latest_reading",
        {"site_name": site_name, "asset_id": asset_id, "sensor": sensor},
        f"latest telemetry for {asset_id}/{sensor}",
        depends_on=[s_detail],
    )
    s_fm = add(
        SERVER_FMSR,
        "get_failure_modes",
        {"asset_class": asset_class},
        f"load known failure modes for class={asset_class}",
        depends_on=[s_read],
    )
    s_anom = add(
        SERVER_TSFM,
        "anomaly_detection",
        {"asset_id": asset_id, "sensor": sensor, "window": "24h"},
        "detect anomalies in recent sensor history",
        depends_on=[s_fm],
    )
    last = s_anom
    if include_vibration:
        last = add(
            SERVER_VIBRATION,
            "fault_detection",
            {"asset_id": asset_id},
            "vibration fault detection summary",
            depends_on=[s_anom],
        )
    s_wo = add(
        SERVER_WO,
        "list_workorders",
        {"site_name": site_name, "asset_id": asset_id, "limit": 10},
        "list related open work orders",
        depends_on=[last],
    )
    last = s_wo
    if include_workorder_write:
        last = add(
            SERVER_WO,
            "create_workorder",
            {
                "site_name": site_name,
                "asset_id": asset_id,
                "title": task[:80],
                "priority": "medium",
            },
            "open maintenance work order from diagnosis",
            depends_on=[s_wo],
        )

    allowed = [s.tool for s in steps]
    plan = mla.ToolPlan(
        task=task,
        steps=steps,
        status=mla.STATUS_DRAFT,
        planner="assetops-diagnostic",
        tools_available=allowed,
        notes="deterministic AssetOpsBench-shaped multi-domain diagnostic walk",
        meta={
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "handoff": "assetops_planner",
            "workflow": "diagnostic",
            "site_name": site_name,
            "asset_id": asset_id,
            "asset_class": asset_class,
            "sensor": sensor,
            "catalog": catalog_summary(domain_mcp_as_tools()),
            "n_servers_touched": len({parse_tool_id(s.tool)["server"] for s in steps}),
        },
    )
    if auto_ready:
        mla.mark_ready(plan, allowed_tools=allowed, require_steps=True)
    return plan


def _wants_diagnostic(task: str) -> bool:
    """Heuristic: prefer full multi-domain walk for diagnosis/asset tasks."""
    tokens = mla._tokenize(task)  # noqa: SLF001 — shared offline tokenizer
    triggers = {
        "diagnos",
        "failure",
        "fault",
        "asset",
        "chiller",
        "pump",
        "motor",
        "sensor",
        "telemetry",
        "anomaly",
        "vibration",
        "workorder",
        "work",
        "order",
        "maintenance",
        "iot",
        "fmsr",
        "tsfm",
        "fmea",
        "industrial",
        "bearing",
        "forecast",
        "troubleshoot",
        "degrad",
        "alarm",
        "wo",
    }
    # substring-friendly: tokens may be full words only; also scan raw
    raw = str(task or "").lower()
    if any(t in raw for t in ("work order", "failure mode", "asset ops", "iot")):
        return True
    return bool(tokens & triggers) or any(t in raw for t in triggers)


# ── Planner over domain MCP catalog ─────────────────────────────────────────


@dataclass
class AssetOpsPlanner:
    """Dedicated Planner role whose catalog is AssetOpsBench domain MCP tools.

    Does **not** call industrial backends. Produces a ready
    :class:`multi_llm_agent.ToolPlan` for Caller or Orchestrator handoff.
    """

    max_steps: int = 8
    auto_ready: bool = True
    prefer_diagnostic: bool = True
    servers: Optional[tuple[str, ...]] = None
    max_privilege: Optional[str] = None
    include_write: bool = True
    _tools: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def load_catalog(self, *, force: bool = False) -> list[dict[str, Any]]:
        if self._tools and not force:
            return list(self._tools)
        self._tools = domain_mcp_as_tools(
            servers=self.servers,
            max_privilege=self.max_privilege,
            include_write=self.include_write,
        )
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
        use_diagnostic: Optional[bool] = None,
        site_name: str = "MAIN",
        asset_id: str = "asset-1",
        asset_class: str = "chiller",
        sensor: str = "temperature",
        include_vibration: bool = False,
        include_workorder_write: bool = False,
    ) -> mla.ToolPlan:
        """Break *task* into domain-MCP steps (no industrial side effects)."""
        catalog = self.load_catalog()
        if not catalog:
            raise AssetOpsPlanError("domain MCP catalog is empty")
        do_ready = self.auto_ready if auto_ready is None else auto_ready
        steps = int(max_steps if max_steps is not None else self.max_steps)

        if plan_text:
            planner = mla.Planner(tools=catalog, max_steps=steps, auto_ready=do_ready)
            plan = planner.plan_from_text(
                plan_text, task=task, tools=catalog, auto_ready=do_ready
            )
            plan.planner = planner_name or "assetops-injected"
        elif (
            (use_diagnostic is True)
            or (
                use_diagnostic is None
                and self.prefer_diagnostic
                and _wants_diagnostic(task)
            )
        ):
            plan = diagnostic_workflow_plan(
                task,
                site_name=site_name,
                asset_id=asset_id,
                asset_class=asset_class,
                sensor=sensor,
                include_vibration=include_vibration,
                include_workorder_write=include_workorder_write,
                auto_ready=do_ready,
            )
            if planner_name:
                plan.planner = planner_name
        else:
            planner = mla.Planner(tools=catalog, max_steps=steps, auto_ready=do_ready)
            plan = planner.plan(
                task, tools=catalog, max_steps=steps, auto_ready=do_ready
            )
            plan.planner = planner_name or plan.planner or "assetops-heuristic"
            if plan.planner == "heuristic":
                plan.planner = "assetops-heuristic"
            if plan.planner == "injected":
                plan.planner = "assetops-injected"

        plan.meta = dict(plan.meta or {})
        plan.meta.update(
            {
                "schema": SCHEMA,
                "paper": PAPER,
                "source_pattern": SOURCE_PATTERN,
                "catalog": catalog_summary(catalog),
                "handoff": "assetops_planner",
            }
        )
        # Annotate steps with server / domain_tool defaults
        for step in plan.steps:
            parsed = parse_tool_id(step.tool)
            step.args = dict(step.args or {})
            if parsed.get("server"):
                step.args.setdefault("server", parsed["server"])
            if parsed.get("tool"):
                step.args.setdefault("domain_tool", parsed["tool"])
            # fill from catalog when needed
            for t in catalog:
                if t.get("name") == step.tool:
                    step.args.setdefault("server", t.get("server") or "")
                    step.args.setdefault("domain_tool", t.get("tool") or "")
                    step.args.setdefault("privilege", t.get("privilege") or "read")
                    break
        return plan

    def prompt_block(self, task: str) -> str:
        """System prompt fragment for a live Planner LLM over domain catalog."""
        catalog = self.load_catalog()
        base = mla.Planner(tools=catalog).prompt_block(task, tools=catalog)
        servers = ", ".join(DOMAIN_SERVER_IDS)
        header = (
            f"# Domain MCP source: {SOURCE_PATTERN} (pattern only)\n"
            f"# Schema: {SCHEMA} · paper: {PAPER}\n"
            f"# Servers: {servers}\n"
            "# Plan steps must use aob.<server>.<tool> names from Available tools.\n"
            "# Prefer multi-domain order: utilities → iot → fmsr → tsfm "
            "→ [vibration] → wo.\n"
            "# Do NOT call industrial backends — output JSON plan only.\n"
            "# Optional step.args.depends_on: list of earlier step ids "
            "(AssetOpsBench plan-execute shape).\n\n"
        )
        return header + base


def plan_from_assetops(
    task: str,
    *,
    max_steps: int = 8,
    plan_text: Optional[str] = None,
    auto_ready: bool = True,
    use_diagnostic: Optional[bool] = None,
    prefer_diagnostic: bool = True,
    servers: Optional[Sequence[str]] = None,
    max_privilege: Optional[str] = None,
    include_write: bool = True,
    site_name: str = "MAIN",
    asset_id: str = "asset-1",
    asset_class: str = "chiller",
    sensor: str = "temperature",
    include_vibration: bool = False,
    include_workorder_write: bool = False,
) -> mla.ToolPlan:
    """Convenience: one-shot domain-MCP Planner (no industrial side effects)."""
    servers_t = tuple(servers) if servers is not None else None
    ap = AssetOpsPlanner(
        max_steps=max_steps,
        auto_ready=auto_ready,
        prefer_diagnostic=prefer_diagnostic,
        servers=servers_t,
        max_privilege=max_privilege,
        include_write=include_write,
    )
    return ap.plan(
        task,
        plan_text=plan_text,
        auto_ready=auto_ready,
        use_diagnostic=use_diagnostic,
        site_name=site_name,
        asset_id=asset_id,
        asset_class=asset_class,
        sensor=sensor,
        include_vibration=include_vibration,
        include_workorder_write=include_workorder_write,
    )


def plan_payload(plan: mla.ToolPlan) -> dict[str, Any]:
    """JSON-safe plan payload with AssetOps schema stamp."""
    base = mla.plan_payload_for_meta(plan)
    base["assetops_schema"] = SCHEMA
    base["source_pattern"] = SOURCE_PATTERN
    meta = dict(base.get("meta") or {})
    meta.update(
        {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "paper": PAPER,
            "handoff": meta.get("handoff") or "assetops_planner",
        }
    )
    if isinstance(plan.meta, dict):
        if "catalog" in plan.meta:
            meta["catalog"] = plan.meta["catalog"]
        if plan.meta.get("workflow"):
            meta["workflow"] = plan.meta["workflow"]
        if plan.meta.get("asset_id"):
            meta["asset_id"] = plan.meta["asset_id"]
        if plan.meta.get("n_servers_touched") is not None:
            meta["n_servers_touched"] = plan.meta["n_servers_touched"]
    base["meta"] = meta
    return base


# ── offline mock Caller registry (no industrial backends) ───────────────────


def make_mock_registry(
    *,
    site_name: str = "MAIN",
    asset_id: str = "asset-1",
) -> dict[str, Callable[..., Any]]:
    """Build a Caller registry that returns structured offline stubs.

    Mirrors AssetOpsBench multi-server routing (server+tool) without CouchDB
    or live MCP. Safe for unit tests and CLI ``aob-run``.
    """

    def _ok(srv: str, tl: str, call_args: dict[str, Any]) -> dict[str, Any]:
        clean = {
            k: v
            for k, v in call_args.items()
            if k not in ("server", "domain_tool", "depends_on", "privilege")
        }
        return {
            "ok": True,
            "server": srv,
            "tool": tl,
            "mock": True,
            "source": SOURCE_PATTERN,
            "args": clean,
            "result": f"mock:{srv}.{tl}",
        }

    registry: dict[str, Callable[..., Any]] = {}
    for t in domain_mcp_as_tools(include_write=True):
        name = str(t["name"])
        server = str(t["server"])
        tool = str(t["tool"])

        def _make(srv: str, tl: str) -> Callable[..., Any]:
            def fn(*_pos: Any, **kwargs: Any) -> dict[str, Any]:
                # Caller may pass kwargs or a single args dict positionally.
                if _pos and isinstance(_pos[0], dict) and not kwargs:
                    kwargs = dict(_pos[0])
                payload = _ok(srv, tl, dict(kwargs))
                # light domain-shaped extras for common tools
                if tl == "sites":
                    payload["sites"] = [site_name, "SITE_B"]
                elif tl == "assets":
                    payload["assets"] = [
                        {"asset_id": asset_id, "type": "chiller", "site": site_name}
                    ]
                elif tl == "asset_detail":
                    payload["asset"] = {
                        "asset_id": kwargs.get("asset_id") or asset_id,
                        "site_name": kwargs.get("site_name") or site_name,
                        "n_sensors": 4,
                    }
                elif tl == "latest_reading":
                    payload["reading"] = {
                        "sensor": kwargs.get("sensor") or "temperature",
                        "value": 42.0,
                        "unit": "C",
                    }
                elif tl == "get_failure_modes":
                    payload["failure_modes"] = [
                        "bearing_wear",
                        "seal_leak",
                        "overheat",
                    ]
                elif tl == "anomaly_detection":
                    payload["anomalies"] = [{"ts": "mock", "score": 0.12}]
                elif tl == "list_workorders":
                    payload["workorders"] = []
                elif tl == "create_workorder":
                    payload["workorder_id"] = f"wo-{uuid.uuid4().hex[:8]}"
                    payload["status"] = "open"
                elif tl == "current_date_time":
                    payload["utc"] = "1970-01-01T00:00:00Z"
                return payload

            return fn

        registry[name] = _make(server, tool)
    return registry


def plan_and_run(
    task: str,
    *,
    max_steps: int = 8,
    plan_text: Optional[str] = None,
    require_ready: bool = True,
    use_diagnostic: Optional[bool] = None,
    stop_on_error: bool = True,
    site_name: str = "MAIN",
    asset_id: str = "asset-1",
    asset_class: str = "chiller",
    sensor: str = "temperature",
    include_vibration: bool = False,
    include_workorder_write: bool = False,
    registry: Optional[dict[str, Callable[..., Any]]] = None,
    cedar_gate: bool = False,
    min_domains: int = 3,
) -> dict[str, Any]:
    """Plan against domain MCP tools, then execute on offline mock registry.

    Pattern: arXiv 2401.07324 Planner (structure) + AssetOpsBench multi-domain
    plan-execute (Caller). Planner phase never calls backends; Caller phase
    uses mock stubs unless *registry* is injected.

    When *cedar_gate* is True, run arXiv 2606.26649 Cedar Policy validation
    (via :mod:`nexus.assetops_work_gate`) before Caller execution — fail-closed
    for incomplete / unsafe domain work plans.
    """
    plan = plan_from_assetops(
        task,
        max_steps=max_steps,
        plan_text=plan_text,
        auto_ready=True,
        use_diagnostic=use_diagnostic,
        site_name=site_name,
        asset_id=asset_id,
        asset_class=asset_class,
        sensor=sensor,
        include_vibration=include_vibration,
        include_workorder_write=include_workorder_write,
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
            "calls": [],
            "summary": None,
            "catalog": (plan.meta or {}).get("catalog") or catalog_summary(),
        }

    work_gate: Optional[dict[str, Any]] = None
    if cedar_gate:
        from . import assetops_work_gate as awg

        work_gate = awg.gate_plan_for_handoff(
            plan, min_domains=int(min_domains), require=True
        )
        if not work_gate.get("ok"):
            return {
                "schema": SCHEMA,
                "paper": PAPER,
                "source_pattern": SOURCE_PATTERN,
                "ok": False,
                "error": "cedar_work_gate_denied",
                "phase": "cedar_gate",
                "plan": payload,
                "work_gate": work_gate,
                "calls": [],
                "summary": None,
                "catalog": (plan.meta or {}).get("catalog") or catalog_summary(),
            }

    reg = registry if registry is not None else make_mock_registry(
        site_name=site_name, asset_id=asset_id
    )
    agent = mla.MultiLLMToolAgent(
        tools=domain_mcp_as_tools(),
        registry=reg,
        max_steps=max_steps,
    )
    assert agent.caller is not None
    agent.caller.set_plan(plan, require_ready=True)
    results = agent.caller.execute_all(stop_on_error=stop_on_error)
    summary = mla.summarize_run(plan, results)
    # Prefer server from call result payload, else parse tool id.
    servers_hit: set[str] = set()
    for r in results:
        if not r.ok:
            continue
        srv = ""
        if isinstance(r.result, dict):
            srv = str(r.result.get("server") or "")
        if not srv:
            srv = str(parse_tool_id(r.tool).get("server") or "")
        if srv:
            servers_hit.add(srv)
    servers_hit_list = sorted(servers_hit)
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "ok": bool(summary.get("ok")),
        "error": None if summary.get("ok") else "run_or_plan_failed",
        "phase": "run",
        "plan": plan.to_dict(),
        "calls": [r.to_dict() for r in results],
        "summary": summary,
        "servers_hit": servers_hit_list,
        "n_servers_hit": len(servers_hit_list),
        "catalog": (plan.meta or {}).get("catalog"),
    }
    if work_gate is not None:
        out["work_gate"] = work_gate
    return out


def plan_and_handoff(
    description: str,
    *,
    workdir: Any = None,
    max_steps: int = 8,
    plan_text: Optional[str] = None,
    require_ready: bool = True,
    agent_mode: str = "fake",
    task_id: Optional[str] = None,
    kind: str = "task",
    wait: bool = False,
    wait_timeout_s: float = 120.0,
    sync_fake: bool = True,
    meta: Optional[dict[str, Any]] = None,
    run_mock: bool = False,
    use_diagnostic: Optional[bool] = None,
    site_name: str = "MAIN",
    asset_id: str = "asset-1",
    asset_class: str = "chiller",
    sensor: str = "temperature",
    cedar_gate: bool = False,
    min_domains: int = 3,
) -> dict[str, Any]:
    """Plan against domain MCP catalog, optionally mock-run, then Orchestrator.

    Pattern: arXiv 2401.07324 Planner + AssetOpsBench domain tools + durable
    Orchestrator execution. Planner never runs tools; mock run is opt-in.

    When *cedar_gate* is True, apply Cedar Policy validation
    (:mod:`nexus.assetops_work_gate`) before handoff — fail-closed.
    """
    from . import orchestrator as orch

    root = Path(workdir).resolve() if workdir is not None else Path.cwd()
    tid = str(task_id or "").strip() or f"aob-{uuid.uuid4().hex[:10]}"

    plan = plan_from_assetops(
        description,
        max_steps=max_steps,
        plan_text=plan_text,
        auto_ready=True,
        use_diagnostic=use_diagnostic,
        site_name=site_name,
        asset_id=asset_id,
        asset_class=asset_class,
        sensor=sensor,
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
            "run": None,
            "orchestrator": None,
            "catalog": (plan.meta or {}).get("catalog") or catalog_summary(),
        }

    work_gate: Optional[dict[str, Any]] = None
    if cedar_gate or bool((meta or {}).get("cedar_gate") or (meta or {}).get("work_gate")):
        from . import assetops_work_gate as awg

        work_gate = awg.gate_plan_for_handoff(
            plan, min_domains=int(min_domains), require=True
        )
        if not work_gate.get("ok"):
            return {
                "schema": SCHEMA,
                "paper": PAPER,
                "source_pattern": SOURCE_PATTERN,
                "ok": False,
                "error": "cedar_work_gate_denied",
                "phase": "cedar_gate",
                "plan": payload,
                "work_gate": work_gate,
                "run": None,
                "orchestrator": None,
                "catalog": (plan.meta or {}).get("catalog") or catalog_summary(),
            }

    # Keep a pristine ready plan for Orchestrator; run mutates step status.
    orch_plan = mla.ToolPlan.from_dict(plan.to_dict())
    if orch_plan.status != mla.STATUS_READY and orch_plan.steps:
        allowed = [s.tool for s in orch_plan.steps] or [
            t["name"] for t in domain_mcp_as_tools()
        ]
        mla.mark_ready(orch_plan, allowed_tools=allowed, require_steps=True)

    run_report: Optional[dict[str, Any]] = None
    if run_mock:
        run_plan = mla.ToolPlan.from_dict(plan.to_dict())
        for s in run_plan.steps:
            s.status = mla.STEP_PENDING
            s.result = None
            s.error = ""
        run_plan.status = mla.STATUS_READY
        reg = make_mock_registry(site_name=site_name, asset_id=asset_id)
        caller = mla.Caller(registry=reg)
        caller.set_plan(run_plan, require_ready=True)
        results = caller.execute_all(stop_on_error=True)
        summary = mla.summarize_run(run_plan, results)
        run_report = {
            "ok": bool(summary.get("ok")),
            "summary": summary,
            "n_calls": len(results),
            "mock": True,
        }

    extra_meta = {
        "assetops_plan": True,
        "source_pattern": SOURCE_PATTERN,
        "assetops_schema": SCHEMA,
        "asset_id": asset_id,
        "site_name": site_name,
        **(meta or {}),
    }
    if work_gate is not None:
        extra_meta["work_gate"] = {
            "ok": work_gate.get("ok"),
            "allowed": work_gate.get("allowed"),
            "reason": work_gate.get("reason"),
            "n_servers_touched": work_gate.get("n_servers_touched"),
            "schema": work_gate.get("schema"),
        }
    o = orch.Orchestrator(root)
    status = o.run_task(
        description,
        kind=kind,
        agent_mode=agent_mode,
        task_id=tid,
        wait=wait,
        wait_timeout_s=wait_timeout_s,
        with_plan=True,
        plan=orch_plan,
        require_plan=require_ready,
        meta=extra_meta,
        sync_fake=sync_fake if agent_mode == "fake" else False,
    )
    orch_ok = status.get("status") not in (None, "failed")
    run_ok = True if run_report is None else bool(run_report.get("ok"))
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "ok": bool(orch_ok and run_ok),
        "error": None,
        "phase": "orchestrator",
        "plan": status.get("plan") or payload,
        "run": run_report,
        "orchestrator": status,
        "task_id": tid,
        "catalog": (plan.meta or {}).get("catalog"),
    }
    if work_gate is not None:
        out["work_gate"] = work_gate
    return out


def format_assetops_plan(plan: mla.ToolPlan | dict[str, Any]) -> str:
    """Human-readable plan with AssetOps schema header."""
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
        f"workflow:   {meta.get('workflow') or '-'}",
        f"asset:      {meta.get('asset_id') or '?'}",
        f"catalog:    n={cat.get('n_tools', '?')} "
        f"servers={cat.get('n_servers', '?')} by_server={cat.get('by_server', {})}",
        "",
    ]
    for s in d.get("steps") or []:
        args = s.get("args") or {}
        deps = args.get("depends_on") or []
        lines.append(
            f"  [{s.get('id')}] {s.get('tool')}  "
            f"server={args.get('server') or '?'}  "
            f"deps={deps or '-'}  "
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
        f"task_id:  {report.get('task_id') or '-'}",
    ]
    cat = report.get("catalog") or {}
    if cat:
        lines.append(
            f"catalog:  tools={cat.get('n_tools')} servers={cat.get('n_servers')} "
            f"by_server={cat.get('by_server')}"
        )
    plan = report.get("plan") or {}
    lines.append(
        f"plan:     status={plan.get('status')} steps={plan.get('n_steps')}"
    )
    if report.get("servers_hit") is not None:
        lines.append(
            f"servers:  hit={report.get('n_servers_hit')} "
            f"ids={report.get('servers_hit')}"
        )
    run = report.get("run") or {}
    if run:
        lines.append(
            f"run:      ok={run.get('ok')} n_calls={run.get('n_calls')} "
            f"mock={run.get('mock')}"
        )
    summary = report.get("summary") or {}
    if summary:
        lines.append(
            f"summary:  ok={summary.get('ok')} "
            f"done={summary.get('n_done')} failed={summary.get('n_failed')}"
        )
    orch_st = report.get("orchestrator") or {}
    if orch_st:
        lines.append(
            f"orch:     task_id={orch_st.get('task_id')} "
            f"status={orch_st.get('status')} "
            f"pre_planned={orch_st.get('pre_planned')}"
        )
    return "\n".join(lines)


# ── module CLI ──────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(
        prog="python -m nexus.assetops_planner",
        description=(
            "AssetOpsBench-shaped domain-MCP Planner "
            "(arXiv 2401.07324 × IBM/AssetOpsBench)"
        ),
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("catalog", help="list domain MCP tools")
    sub.add_parser("servers", help="list domain MCP servers")

    pp = sub.add_parser("plan", help="plan task (no side effects)")
    pp.add_argument("task")
    pp.add_argument("--max-steps", type=int, default=8)
    pp.add_argument("--no-diagnostic", action="store_true")
    pp.add_argument("--no-ready", action="store_true")
    pp.add_argument("--asset-id", default="asset-1")
    pp.add_argument("--site-name", default="MAIN")
    pp.add_argument("--asset-class", default="chiller")
    pp.add_argument("--sensor", default="temperature")
    pp.add_argument("--json", action="store_true")

    pr = sub.add_parser("run", help="plan + mock-execute domain tools")
    pr.add_argument("task")
    pr.add_argument("--max-steps", type=int, default=8)
    pr.add_argument("--no-diagnostic", action="store_true")
    pr.add_argument("--asset-id", default="asset-1")
    pr.add_argument("--site-name", default="MAIN")
    pr.add_argument("--json", action="store_true")

    ph = sub.add_parser("handoff", help="plan → Orchestrator with_plan")
    ph.add_argument("task")
    ph.add_argument("--workdir", default=".")
    ph.add_argument("--max-steps", type=int, default=8)
    ph.add_argument("--task-id", default="")
    ph.add_argument("--run-mock", action="store_true")
    ph.add_argument(
        "--agent-mode",
        default="fake",
        choices=["fake", "demo", "auto", "bus"],
    )
    ph.add_argument("--json", action="store_true")

    ppr = sub.add_parser("prompt", help="print Planner LLM prompt")
    ppr.add_argument("task")

    args = p.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "catalog":
        tools = domain_mcp_as_tools()
        summary = catalog_summary(tools)
        print(json.dumps({"schema": SCHEMA, "summary": summary, "tools": tools}, indent=2))
        return 0 if tools else 1

    if args.cmd == "servers":
        print(json.dumps({"schema": SCHEMA, "servers": list_domain_servers()}, indent=2))
        return 0

    if args.cmd == "plan":
        plan = plan_from_assetops(
            args.task,
            max_steps=int(args.max_steps),
            auto_ready=not args.no_ready,
            use_diagnostic=False if args.no_diagnostic else None,
            site_name=args.site_name,
            asset_id=args.asset_id,
            asset_class=args.asset_class,
            sensor=args.sensor,
        )
        if args.json:
            print(plan.to_json())
        else:
            print(format_assetops_plan(plan))
        return 0 if plan.steps else 1

    if args.cmd == "run":
        report = plan_and_run(
            args.task,
            max_steps=int(args.max_steps),
            use_diagnostic=False if args.no_diagnostic else None,
            site_name=args.site_name,
            asset_id=args.asset_id,
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(format_report(report))
            if report.get("plan"):
                print()
                print(format_assetops_plan(report["plan"]))
        return 0 if report.get("ok") else 1

    if args.cmd == "handoff":
        tid = str(args.task_id or "").strip() or None
        report = plan_and_handoff(
            args.task,
            workdir=args.workdir,
            max_steps=int(args.max_steps),
            agent_mode=str(args.agent_mode),
            task_id=tid,
            run_mock=bool(args.run_mock),
            sync_fake=True,
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(format_report(report))
            if report.get("plan"):
                print()
                print(format_assetops_plan(report["plan"]))
        ok = bool(report.get("ok")) and (report.get("orchestrator") or {}).get(
            "status"
        ) not in ("failed", None)
        return 0 if ok else 1

    if args.cmd == "prompt":
        print(AssetOpsPlanner().prompt_block(args.task))
        return 0

    print("usage: catalog|servers|plan|run|handoff|prompt", file=sys.stderr)
    return 2


__all__ = [
    "SCHEMA",
    "PAPER",
    "SOURCE_PATTERN",
    "TOOL_PREFIX",
    "DOMAIN_SERVER_IDS",
    "SERVER_IOT",
    "SERVER_FMSR",
    "SERVER_TSFM",
    "SERVER_WO",
    "SERVER_VIBRATION",
    "SERVER_UTILITIES",
    "AssetOpsPlanError",
    "AssetOpsPlanner",
    "tool_id",
    "parse_tool_id",
    "list_domain_servers",
    "domain_mcp_as_tools",
    "catalog_summary",
    "diagnostic_workflow_plan",
    "plan_from_assetops",
    "plan_payload",
    "make_mock_registry",
    "plan_and_run",
    "plan_and_handoff",
    "format_assetops_plan",
    "format_report",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
