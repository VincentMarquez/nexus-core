"""Marketplace-aware Planner: arXiv 2401.07324 × wshobson/agents hybrid.

Paper: *Small LLMs Are Weak Tool Learners: A Multi-LLM Agent*
https://arxiv.org/abs/2401.07324v3

GitHub pattern (shape only — not a vendored tree):
  wshobson/agents — single-source Markdown marketplace of plugins with
  agents/*.md, skills/*/SKILL.md, commands/*.md (+ multi-harness adapters).

Novel hybrid (portfolio cross_pattern):

  plugins/<id>/agents|skills|commands  (Markdown marketplace catalog)
                │
                ▼
         ┌──────────┐   structured JSON plan
         │  Planner │ ──► steps = ordered marketplace components
         └──────────┘   (small/offline role — no tool side effects)
                │
                ├── ready plan ──► Caller (optional mock / registry)
                └── ready plan ──► Orchestrator.run_task (with_plan)

Small specialized Planner decomposes complex tasks against the marketplace
component catalog (agents / skills / commands) *before* durable execution.
Never vendors the upstream plugin tree; reuses in-tree ``marketplace``
discovery + ``multi_llm_agent`` Planner/Caller.

Offline-first: heuristic Planner for tests/smoke; inject LLM JSON via plan_text.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import marketplace as mp
from . import multi_llm_agent as mla

SCHEMA = "nexus.marketplace_planner/v1"
PAPER = mla.PAPER  # arxiv:2401.07324v3
SOURCE_PATTERN = "wshobson/agents"
DEFAULT_KINDS: tuple[str, ...] = ("agent", "skill", "command")


class MarketPlanError(ValueError):
    """Marketplace catalog empty or plan invalid for marketplace handoff."""


# ── catalog: Markdown marketplace → Planner tools ───────────────────────────


def component_tool_id(kind: str, name: str, *, plugin_id: str = "") -> str:
    """Stable Planner tool id for a marketplace component.

    Shape: ``agent:durable-operator`` or ``skill:demo-skill@demo-plugin`` when
    a plugin id is provided (disambiguates cross-plugin name reuse).
    """
    k = str(kind or "").strip().lower() or "component"
    n = str(name or "").strip()
    if not n:
        raise MarketPlanError("component name must be non-empty")
    if plugin_id:
        return f"{k}:{n}@{plugin_id}"
    return f"{k}:{n}"


def parse_component_tool_id(tool_id: str) -> dict[str, str]:
    """Inverse of :func:`component_tool_id` (best-effort)."""
    raw = str(tool_id or "").strip()
    kind, _, rest = raw.partition(":")
    if not rest:
        return {"kind": "", "name": raw, "plugin_id": "", "tool": raw}
    name, _, plugin_id = rest.partition("@")
    return {
        "kind": kind.strip().lower(),
        "name": name.strip(),
        "plugin_id": plugin_id.strip(),
        "tool": raw,
    }


def _read_component_blurb(plugin_dir: Path, rel_path: str, *, max_chars: int = 200) -> str:
    """Pull a short description from Markdown frontmatter/body for ranking."""
    p = plugin_dir / rel_path
    if not p.is_file():
        return ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    # Prefer YAML description: line
    for line in text.splitlines()[:30]:
        low = line.strip().lower()
        if low.startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'")[:max_chars]
    # First non-empty, non-frontmatter heading/paragraph
    in_fm = False
    for line in text.splitlines():
        s = line.strip()
        if s == "---":
            in_fm = not in_fm
            continue
        if in_fm:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#"):
                return s.lstrip("#").strip()[:max_chars]
            continue
        return s[:max_chars]
    return ""


def marketplace_as_tools(
    workdir: Path | str,
    *,
    plugins_dir: str = mp.DEFAULT_PLUGINS_DIR,
    kinds: Optional[Iterable[str]] = None,
    max_privilege: Optional[str] = None,
    include_plugin_tags: bool = True,
    disambiguate: bool = True,
) -> list[dict[str, Any]]:
    """Build a Planner tool catalog from marketplace Markdown components.

    Each entry is ``{"name", "description", "kind", "plugin_id", "path", ...}``
    suitable for :class:`multi_llm_agent.Planner` (no side effects).
    """
    root = Path(workdir).resolve()
    want = {str(k).strip().lower() for k in (kinds or DEFAULT_KINDS)}
    want = {k for k in want if k in ("agent", "skill", "command")}
    if not want:
        want = set(DEFAULT_KINDS)

    # Privilege filter via list_plugins when requested
    plugin_priv: dict[str, str] = {}
    plugin_meta: dict[str, mp.PluginInfo] = {}
    try:
        rows = mp.list_plugins(
            root,
            plugins_dir=plugins_dir,
            max_privilege=max_privilege,
            validate=False,
        )
        for info in rows:
            plugin_priv[info.id] = info.privilege
            plugin_meta[info.id] = info
            # also key by directory name
            plugin_priv[Path(info.path).name] = info.privilege
            plugin_meta[Path(info.path).name] = info
    except Exception:  # noqa: BLE001 — empty catalog on discovery failure
        rows = []

    tools: list[dict[str, Any]] = []
    for d in mp.list_plugin_dirs(root, plugins_dir):
        try:
            man = mp.load_plugin_manifest(d)
            pid = str(man.get("name") or man.get("id") or d.name)
        except mp.MarketplaceError:
            pid = d.name
            man = {}

        # Skip plugins above max privilege when filter is set
        if max_privilege is not None and pid not in plugin_meta and d.name not in plugin_meta:
            # list_plugins already filtered; skip unknown under privilege mode
            if plugin_meta:
                continue

        desc_plugin = str(man.get("description") or "")
        tags = man.get("tags") or man.get("keywords") or []
        if not isinstance(tags, list):
            tags = []
        tag_s = " ".join(str(t) for t in tags)

        comps = mp.discover_components(d, pid)
        for c in comps:
            if c.kind not in want:
                continue
            # name collisions: prefer plugin-qualified id when disambiguate
            tool_name = component_tool_id(
                c.kind, c.name, plugin_id=pid if disambiguate else ""
            )
            blurb = _read_component_blurb(d, c.path)
            parts = [
                f"marketplace {c.kind}",
                f"plugin={pid}",
                desc_plugin[:120] if desc_plugin else "",
                blurb,
                tag_s if include_plugin_tags else "",
            ]
            description = " · ".join(p for p in parts if p).strip(" ·")
            tools.append(
                {
                    "name": tool_name,
                    "description": description,
                    "kind": c.kind,
                    "component": c.name,
                    "plugin_id": pid,
                    "path": c.path,
                    "privilege": str(man.get("privilege") or "read"),
                    "source": SOURCE_PATTERN,
                    "marketplace": True,
                }
            )
    return tools


def catalog_summary(tools: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Compact counts for plan meta / CLI."""
    by_kind: dict[str, int] = {}
    plugins: set[str] = set()
    for t in tools:
        k = str(t.get("kind") or "unknown")
        by_kind[k] = by_kind.get(k, 0) + 1
        if t.get("plugin_id"):
            plugins.add(str(t["plugin_id"]))
    return {
        "n_tools": len(tools),
        "n_plugins": len(plugins),
        "by_kind": dict(sorted(by_kind.items())),
        "plugins": sorted(plugins),
    }


# ── Planner over marketplace ────────────────────────────────────────────────


@dataclass
class MarketplacePlanner:
    """Dedicated Planner role whose catalog is the Markdown marketplace.

    Does **not** execute agents/skills/commands. Produces a ready
    :class:`multi_llm_agent.ToolPlan` for Caller or Orchestrator handoff.
    """

    workdir: Path | str = "."
    plugins_dir: str = mp.DEFAULT_PLUGINS_DIR
    kinds: tuple[str, ...] = DEFAULT_KINDS
    max_steps: int = 5
    max_privilege: Optional[str] = None
    auto_ready: bool = True
    disambiguate: bool = True
    _tools: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _loaded: bool = field(default=False, repr=False)

    def load_catalog(self, *, force: bool = False) -> list[dict[str, Any]]:
        if self._loaded and not force and self._tools:
            return list(self._tools)
        self._tools = marketplace_as_tools(
            self.workdir,
            plugins_dir=self.plugins_dir,
            kinds=self.kinds,
            max_privilege=self.max_privilege,
            disambiguate=self.disambiguate,
        )
        self._loaded = True
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
    ) -> mla.ToolPlan:
        """Break *task* into marketplace component steps (no side effects)."""
        catalog = self.load_catalog()
        do_ready = self.auto_ready if auto_ready is None else auto_ready
        steps = int(max_steps if max_steps is not None else self.max_steps)
        planner = mla.Planner(tools=catalog, max_steps=steps, auto_ready=do_ready)

        if plan_text:
            plan = planner.plan_from_text(
                plan_text, task=task, tools=catalog, auto_ready=do_ready
            )
        else:
            plan = planner.plan(
                task, tools=catalog, max_steps=steps, auto_ready=do_ready
            )

        plan.planner = planner_name or plan.planner or "marketplace-heuristic"
        if plan.planner == "heuristic":
            plan.planner = "marketplace-heuristic"
        if plan.planner == "injected":
            plan.planner = "marketplace-injected"

        plan.meta = dict(plan.meta or {})
        plan.meta.update(
            {
                "schema": SCHEMA,
                "paper": PAPER,
                "source_pattern": SOURCE_PATTERN,
                "catalog": catalog_summary(catalog),
                "handoff": "marketplace_planner",
                "kinds": list(self.kinds),
            }
        )
        # Annotate each step with parsed marketplace component identity
        for step in plan.steps:
            parsed = parse_component_tool_id(step.tool)
            step.args = dict(step.args or {})
            step.args.setdefault("kind", parsed.get("kind") or "")
            step.args.setdefault("component", parsed.get("name") or step.tool)
            if parsed.get("plugin_id"):
                step.args.setdefault("plugin_id", parsed["plugin_id"])
            # fill plugin_id from catalog when not in tool id
            if not step.args.get("plugin_id"):
                for t in catalog:
                    if t.get("name") == step.tool:
                        step.args["plugin_id"] = t.get("plugin_id") or ""
                        step.args.setdefault("kind", t.get("kind") or "")
                        step.args.setdefault("path", t.get("path") or "")
                        break
        return plan

    def prompt_block(self, task: str) -> str:
        """System prompt fragment for a live Planner LLM over marketplace catalog."""
        catalog = self.load_catalog()
        base = mla.Planner(tools=catalog).prompt_block(task, tools=catalog)
        header = (
            f"# Marketplace catalog source: {SOURCE_PATTERN} (pattern only)\n"
            f"# Schema: {SCHEMA} · paper: {PAPER}\n"
            "# Plan steps must use tool names from Available tools "
            "(agent:… / skill:… / command:… forms).\n"
            "# Do NOT execute agents/skills/commands — output JSON plan only.\n\n"
        )
        return header + base


def plan_from_marketplace(
    task: str,
    *,
    workdir: Path | str = ".",
    plugins_dir: str = mp.DEFAULT_PLUGINS_DIR,
    kinds: Optional[Iterable[str]] = None,
    max_steps: int = 5,
    max_privilege: Optional[str] = None,
    plan_text: Optional[str] = None,
    auto_ready: bool = True,
    disambiguate: bool = True,
) -> mla.ToolPlan:
    """Convenience: one-shot marketplace Planner (no tool execution)."""
    kinds_t = tuple(kinds) if kinds is not None else DEFAULT_KINDS
    mp_planner = MarketplacePlanner(
        workdir=workdir,
        plugins_dir=plugins_dir,
        kinds=kinds_t,
        max_steps=max_steps,
        max_privilege=max_privilege,
        auto_ready=auto_ready,
        disambiguate=disambiguate,
    )
    return mp_planner.plan(task, plan_text=plan_text, auto_ready=auto_ready)


def plan_payload(plan: mla.ToolPlan) -> dict[str, Any]:
    """JSON-safe plan payload with marketplace schema stamp."""
    base = mla.plan_payload_for_meta(plan)
    base["marketplace_schema"] = SCHEMA
    base["source_pattern"] = SOURCE_PATTERN
    meta = dict(base.get("meta") or {})
    meta.update(
        {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "paper": PAPER,
            "handoff": meta.get("handoff") or "marketplace_planner",
        }
    )
    # surface catalog summary if present on plan
    if isinstance(plan.meta, dict) and "catalog" in plan.meta:
        meta["catalog"] = plan.meta["catalog"]
    base["meta"] = meta
    return base


def plan_and_handoff(
    description: str,
    *,
    workdir: Any = None,
    plugins_dir: str = mp.DEFAULT_PLUGINS_DIR,
    kinds: Optional[Iterable[str]] = None,
    max_steps: int = 5,
    max_privilege: Optional[str] = None,
    plan_text: Optional[str] = None,
    require_ready: bool = True,
    agent_mode: str = "fake",
    task_id: Optional[str] = None,
    kind: str = "task",
    wait: bool = False,
    wait_timeout_s: float = 120.0,
    sync_fake: bool = True,
    meta: Optional[dict[str, Any]] = None,
    disambiguate: bool = True,
) -> dict[str, Any]:
    """Plan against marketplace catalog, then hand off to Orchestrator.

    Pattern: arXiv 2401.07324 Planner (structure) + wshobson Markdown marketplace
    catalog + durable Orchestrator execution. Planner never runs components.
    """
    from . import orchestrator as orch

    root = Path(workdir).resolve() if workdir is not None else Path.cwd()
    plan = plan_from_marketplace(
        description,
        workdir=root,
        plugins_dir=plugins_dir,
        kinds=kinds,
        max_steps=max_steps,
        max_privilege=max_privilege,
        plan_text=plan_text,
        auto_ready=True,
        disambiguate=disambiguate,
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
            "orchestrator": None,
            "catalog": (plan.meta or {}).get("catalog") or catalog_summary([]),
        }

    extra_meta = {
        "marketplace_plan": True,
        "source_pattern": SOURCE_PATTERN,
        "marketplace_schema": SCHEMA,
        **(meta or {}),
    }
    o = orch.Orchestrator(root)
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
        meta=extra_meta,
        sync_fake=sync_fake if agent_mode == "fake" else False,
    )
    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "ok": status.get("status") not in (None, "failed"),
        "error": None,
        "phase": "orchestrator",
        "plan": status.get("plan") or payload,
        "orchestrator": status,
        "catalog": (plan.meta or {}).get("catalog"),
    }


def format_market_plan(plan: mla.ToolPlan | dict[str, Any]) -> str:
    """Human-readable plan with marketplace schema header."""
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
        f"catalog:    n={cat.get('n_tools', '?')} plugins={cat.get('n_plugins', '?')} "
        f"by_kind={cat.get('by_kind', {})}",
        "",
    ]
    for s in d.get("steps") or []:
        args = s.get("args") or {}
        kind = args.get("kind") or parse_component_tool_id(str(s.get("tool") or "")).get(
            "kind"
        )
        lines.append(
            f"  [{s.get('id')}] {s.get('tool')}  kind={kind}  "
            f"plugin={args.get('plugin_id') or '?'}  status={s.get('status')}"
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
    ]
    cat = report.get("catalog") or {}
    if cat:
        lines.append(
            f"catalog:  tools={cat.get('n_tools')} plugins={cat.get('n_plugins')} "
            f"kinds={cat.get('by_kind')}"
        )
    plan = report.get("plan") or {}
    lines.append(
        f"plan:     status={plan.get('status')} steps={plan.get('n_steps')}"
    )
    orch = report.get("orchestrator") or {}
    if orch:
        lines.append(
            f"orch:     task_id={orch.get('task_id')} status={orch.get('status')} "
            f"pre_planned={orch.get('pre_planned')}"
        )
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m nexus.marketplace_planner plan|handoff|catalog|prompt``."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        prog="nexus.marketplace_planner",
        description=(
            "Marketplace-aware Planner (arXiv 2401.07324 × wshobson/agents)"
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cat = sub.add_parser("catalog", help="list marketplace components as Planner tools")
    p_cat.add_argument("--workdir", default=".")
    p_cat.add_argument("--plugins-dir", default=mp.DEFAULT_PLUGINS_DIR, dest="plugins_dir")
    p_cat.add_argument(
        "--kinds",
        default="agent,skill,command",
        help="comma-separated kinds (agent|skill|command)",
    )
    p_cat.add_argument("--json", action="store_true")

    p_plan = sub.add_parser("plan", help="Planner only over marketplace catalog")
    p_plan.add_argument("task", help="complex task description")
    p_plan.add_argument("--workdir", default=".")
    p_plan.add_argument("--plugins-dir", default=mp.DEFAULT_PLUGINS_DIR, dest="plugins_dir")
    p_plan.add_argument("--kinds", default="agent,skill,command")
    p_plan.add_argument("--max-steps", type=int, default=5, dest="max_steps")
    p_plan.add_argument("--no-ready", action="store_true")
    p_plan.add_argument("--json", action="store_true")

    p_ho = sub.add_parser(
        "handoff",
        help="Marketplace Planner → Orchestrator (with_plan)",
    )
    p_ho.add_argument("task", help="complex task description")
    p_ho.add_argument("--workdir", default=".")
    p_ho.add_argument("--plugins-dir", default=mp.DEFAULT_PLUGINS_DIR, dest="plugins_dir")
    p_ho.add_argument("--kinds", default="agent,skill,command")
    p_ho.add_argument("--max-steps", type=int, default=5, dest="max_steps")
    p_ho.add_argument("--task-id", default="", dest="task_id")
    p_ho.add_argument(
        "--agent-mode",
        default="fake",
        choices=sorted({"fake", "demo", "auto", "bus"}),
        dest="agent_mode",
    )
    p_ho.add_argument("--json", action="store_true")

    p_pr = sub.add_parser("prompt", help="Planner LLM prompt over marketplace catalog")
    p_pr.add_argument("task")
    p_pr.add_argument("--workdir", default=".")
    p_pr.add_argument("--plugins-dir", default=mp.DEFAULT_PLUGINS_DIR, dest="plugins_dir")
    p_pr.add_argument("--kinds", default="agent,skill,command")

    args = ap.parse_args(list(argv) if argv is not None else None)

    def _kinds() -> tuple[str, ...]:
        raw = str(getattr(args, "kinds", "") or "")
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return tuple(parts) if parts else DEFAULT_KINDS

    if args.cmd == "catalog":
        tools = marketplace_as_tools(
            args.workdir, plugins_dir=args.plugins_dir, kinds=_kinds()
        )
        summary = catalog_summary(tools)
        if args.json:
            print(json.dumps({"schema": SCHEMA, "summary": summary, "tools": tools}, indent=2))
        else:
            print(
                f"schema={SCHEMA} tools={summary['n_tools']} "
                f"plugins={summary['n_plugins']} by_kind={summary['by_kind']}"
            )
            for t in tools:
                print(f"  - {t['name']}: {t.get('description', '')[:80]}")
        return 0 if tools else 1

    if args.cmd == "plan":
        plan = plan_from_marketplace(
            args.task,
            workdir=args.workdir,
            plugins_dir=args.plugins_dir,
            kinds=_kinds(),
            max_steps=int(args.max_steps),
            auto_ready=not args.no_ready,
        )
        if args.json:
            print(plan.to_json())
        else:
            print(format_market_plan(plan))
        return 0 if plan.steps else 1

    if args.cmd == "handoff":
        tid = str(getattr(args, "task_id", "") or "").strip() or None
        report = plan_and_handoff(
            args.task,
            workdir=args.workdir,
            plugins_dir=args.plugins_dir,
            kinds=_kinds(),
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
                print(format_market_plan(report["plan"]))
        ok = bool(report.get("ok")) and (report.get("orchestrator") or {}).get(
            "status"
        ) not in ("failed", None)
        return 0 if ok else 1

    if args.cmd == "prompt":
        planner = MarketplacePlanner(
            workdir=args.workdir,
            plugins_dir=args.plugins_dir,
            kinds=_kinds(),
        )
        print(planner.prompt_block(args.task))
        return 0

    print("usage: plan|handoff|catalog|prompt", file=sys.stderr)
    return 2


__all__ = [
    "SCHEMA",
    "PAPER",
    "SOURCE_PATTERN",
    "DEFAULT_KINDS",
    "MarketPlanError",
    "MarketplacePlanner",
    "component_tool_id",
    "parse_component_tool_id",
    "marketplace_as_tools",
    "catalog_summary",
    "plan_from_marketplace",
    "plan_payload",
    "plan_and_handoff",
    "format_market_plan",
    "format_report",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
