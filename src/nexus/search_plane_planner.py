"""Search-based plane planner: arXiv 2407.01476 × wshobson/agents.

Paper: *Tree Search for Language Model Agents*
https://arxiv.org/abs/2407.01476v4

GitHub pattern (shape only — not a vendored tree):
  wshobson/agents — single-source Markdown marketplace of plugins with
  agents/*.md, skills/*/SKILL.md, commands/*.md (+ multi-harness adapters).

Novel hybrid (portfolio cross_pattern):

  plugins/<id>/agents|skills|commands  (Markdown marketplace catalog)
                │
                ▼
         ┌────────────────┐   beam / A* search tree
         │ Search Planner │ ──► ordered component + plane steps
         └────────────────┘   (offline — no tool side effects)
                │
                ├── ready plan ──► control plane guide (ops job meta / govern)
                └── ready plan ──► Orchestrator.run_task (with_plan)

Tree search (beam width or A* f=g+h) selects marketplace components that best
cover a task, then wraps them with control-plane governance so the
orchestrator is guided by a search-derived plan rather than a single greedy
heuristic rank.

Offline-first: deterministic scores for tests/smoke; no live LLM required.
"""

from __future__ import annotations

import heapq
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import control_plane_planner as cpp
from . import marketplace as mp
from . import marketplace_planner as mplan
from . import multi_llm_agent as mla
from . import ops_store as ops

SCHEMA = "nexus.search_plane_planner/v1"
PAPER = "arxiv:2407.01476v4"
SOURCE_PATTERN = "wshobson/agents"
CONTROL_PLANE_PATTERN = "builderz-labs/mission-control"  # shape via plane tools
DEFAULT_BEAM_WIDTH = 3
DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_EXPANSIONS = 64
ALGORITHMS = frozenset({"beam", "astar"})


class SearchPlanError(ValueError):
    """Search catalog empty or plan invalid for plane/orchestrator handoff."""


# ── search nodes ────────────────────────────────────────────────────────────


@dataclass(order=True)
class _HeapItem:
    """Priority queue entry for A* (lowest f first)."""

    f: float
    seq: int
    node: "SearchNode" = field(compare=False)


@dataclass
class SearchNode:
    """One node in the marketplace / plane action search tree."""

    path: tuple[str, ...] = ()
    scores: tuple[float, ...] = ()
    covered: frozenset[str] = field(default_factory=frozenset)
    g: float = 0.0
    h: float = 0.0
    depth: int = 0

    @property
    def f(self) -> float:
        return float(self.g) + float(self.h)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": list(self.path),
            "scores": [float(s) for s in self.scores],
            "covered": sorted(self.covered),
            "g": float(self.g),
            "h": float(self.h),
            "f": float(self.f),
            "depth": int(self.depth),
        }


@dataclass
class SearchTrace:
    """Diagnostic trail of a search run (for plan meta / operator boards)."""

    algorithm: str
    expanded: int = 0
    generated: int = 0
    beam_width: int = 0
    max_depth: int = 0
    best_f: float = 0.0
    best_path: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "expanded": int(self.expanded),
            "generated": int(self.generated),
            "beam_width": int(self.beam_width),
            "max_depth": int(self.max_depth),
            "best_f": float(self.best_f),
            "best_path": list(self.best_path),
            "notes": self.notes,
        }


# ── scoring / heuristic ─────────────────────────────────────────────────────


def _tool_text(entry: dict[str, Any]) -> str:
    parts = [
        str(entry.get("name") or ""),
        str(entry.get("description") or ""),
        str(entry.get("kind") or ""),
        str(entry.get("component") or ""),
        str(entry.get("plugin_id") or ""),
    ]
    return " ".join(p for p in parts if p)


def action_score(task_tokens: set[str], entry: dict[str, Any]) -> float:
    """Lexical relevance of a catalog action to the task (higher = better)."""
    name = str(entry.get("name") or "")
    desc = _tool_text(entry)
    return float(mla._score_tool(task_tokens, name, desc))  # noqa: SLF001


def step_cost(score: float, *, base: float = 1.0) -> float:
    """Convert relevance score → positive path cost (lower is better)."""
    # High score → low cost; never zero so depth still costs something.
    sc = max(0.0, float(score))
    return float(base) / (1.0 + sc)


def uncovered_tokens(task_tokens: set[str], covered: frozenset[str]) -> set[str]:
    return {t for t in task_tokens if t not in covered}


def heuristic_h(
    task_tokens: set[str],
    covered: frozenset[str],
    *,
    remaining_actions: int,
) -> float:
    """Admissible-ish h: fraction of task tokens still uncovered.

    Scales lightly with remaining budget so deeper unfinished paths are
    preferred only when they still cover new tokens.
    """
    if not task_tokens:
        return 0.0
    left = uncovered_tokens(task_tokens, covered)
    frac = len(left) / max(1, len(task_tokens))
    # small residual so empty-uncovered goals are preferred
    return float(frac) + (0.05 if remaining_actions <= 0 and left else 0.0)


def tokens_covered_by(entry: dict[str, Any], task_tokens: set[str]) -> frozenset[str]:
    """Task tokens that appear in the action name/description."""
    text_tokens = mla._tokenize(_tool_text(entry))  # noqa: SLF001
    return frozenset(t for t in task_tokens if t in text_tokens)


# ── catalogs ────────────────────────────────────────────────────────────────


def hybrid_catalog(
    workdir: Path | str = ".",
    *,
    plugins_dir: str = mp.DEFAULT_PLUGINS_DIR,
    kinds: Optional[Iterable[str]] = None,
    include_plane: bool = True,
    max_privilege: Optional[str] = None,
    disambiguate: bool = True,
) -> list[dict[str, Any]]:
    """Marketplace components (+ optional plane ops) as a search action space.

    Marketplace entries are the primary expansion candidates (wshobson shape).
    Plane tools are available when *include_plane* so search can also choose
    governance ops (inspect/list/report) when task tokens match.
    """
    tools = mplan.marketplace_as_tools(
        workdir,
        plugins_dir=plugins_dir,
        kinds=kinds,
        max_privilege=max_privilege,
        disambiguate=disambiguate,
    )
    # Tag for search filtering
    for t in tools:
        t.setdefault("search_family", "marketplace")
    if include_plane:
        for t in cpp.control_plane_as_tools():
            row = dict(t)
            row["search_family"] = "plane"
            tools.append(row)
    return tools


def catalog_summary(tools: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Compact counts for plan meta / CLI."""
    by_kind: dict[str, int] = {}
    by_family: dict[str, int] = {}
    plugins: set[str] = set()
    for t in tools:
        k = str(t.get("kind") or "unknown")
        by_kind[k] = by_kind.get(k, 0) + 1
        fam = str(t.get("search_family") or "other")
        by_family[fam] = by_family.get(fam, 0) + 1
        if t.get("plugin_id"):
            plugins.add(str(t["plugin_id"]))
    return {
        "n_tools": len(tools),
        "n_plugins": len(plugins),
        "by_kind": dict(sorted(by_kind.items())),
        "by_family": dict(sorted(by_family.items())),
        "plugins": sorted(plugins),
        "source_pattern": SOURCE_PATTERN,
        "paper": PAPER,
    }


# ── core search algorithms ──────────────────────────────────────────────────


def _index_tools(tools: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for t in tools:
        name = str(t.get("name") or "").strip()
        if name:
            idx[name] = t
    return idx


def beam_search(
    task: str,
    tools: Sequence[dict[str, Any]],
    *,
    beam_width: int = DEFAULT_BEAM_WIDTH,
    max_depth: int = DEFAULT_MAX_DEPTH,
    prefer_marketplace: bool = True,
) -> tuple[SearchNode, SearchTrace]:
    """Beam search over catalog actions (Tree Search for LM Agents shape).

    At each depth keep the *beam_width* partial paths with lowest f = g + h.
    Does not execute tools.
    """
    task = str(task or "").strip()
    if not task:
        raise SearchPlanError("task must be non-empty")
    idx = _index_tools(tools)
    if not idx:
        empty = SearchNode(h=1.0)
        return empty, SearchTrace(
            algorithm="beam",
            beam_width=int(beam_width),
            max_depth=int(max_depth),
            notes="empty catalog",
        )

    tokens = mla._tokenize(task)  # noqa: SLF001
    width = max(1, int(beam_width))
    depth_lim = max(1, int(max_depth))
    root = SearchNode(
        h=heuristic_h(tokens, frozenset(), remaining_actions=depth_lim),
    )
    beam: list[SearchNode] = [root]
    best = root
    expanded = 0
    generated = 0

    for _depth in range(depth_lim):
        candidates: list[SearchNode] = []
        for node in beam:
            expanded += 1
            used = set(node.path)
            scored: list[tuple[float, str, dict[str, Any]]] = []
            for name, entry in idx.items():
                if name in used:
                    continue
                if prefer_marketplace and entry.get("search_family") == "plane":
                    # De-prioritize plane ops during component search unless
                    # they score strongly on their own.
                    sc = action_score(tokens, entry)
                    if sc < 2.0:
                        continue
                else:
                    sc = action_score(tokens, entry)
                if sc <= 0 and prefer_marketplace:
                    continue
                scored.append((sc, name, entry))
            if not scored:
                # keep node as terminal candidate
                candidates.append(node)
                continue
            scored.sort(key=lambda x: (-x[0], x[1]))
            # Expand top actions from this node (branch factor ≈ beam_width)
            for sc, name, entry in scored[:width]:
                new_cover = node.covered | tokens_covered_by(entry, tokens)
                child = SearchNode(
                    path=node.path + (name,),
                    scores=node.scores + (sc,),
                    covered=new_cover,
                    g=node.g + step_cost(sc),
                    h=heuristic_h(
                        tokens,
                        new_cover,
                        remaining_actions=depth_lim - (node.depth + 1),
                    ),
                    depth=node.depth + 1,
                )
                generated += 1
                candidates.append(child)
                if child.h < best.h or (
                    abs(child.h - best.h) < 1e-9 and child.g < best.g
                ):
                    if child.path:
                        best = child
                elif not best.path and child.path:
                    best = child

        if not candidates:
            break
        # Keep lowest f, tie-break by more coverage then name path
        candidates.sort(
            key=lambda n: (
                n.f,
                -len(n.covered),
                -n.depth,
                n.path,
            )
        )
        beam = candidates[:width]
        # Update best among beam
        for n in beam:
            if not n.path:
                continue
            if not best.path:
                best = n
            elif n.h < best.h or (abs(n.h - best.h) < 1e-9 and n.g < best.g):
                best = n
            elif abs(n.h - best.h) < 1e-9 and abs(n.g - best.g) < 1e-9:
                if len(n.covered) > len(best.covered):
                    best = n

        # Early stop if fully covered
        if best.path and not uncovered_tokens(tokens, best.covered):
            break

    # Fallback: best single action by score if search found nothing
    if not best.path:
        ranked = sorted(
            (
                (action_score(tokens, e), n)
                for n, e in idx.items()
            ),
            key=lambda x: (-x[0], x[1]),
        )
        if ranked:
            sc, name = ranked[0]
            entry = idx[name]
            cov = tokens_covered_by(entry, tokens)
            best = SearchNode(
                path=(name,),
                scores=(sc,),
                covered=cov,
                g=step_cost(sc),
                h=heuristic_h(tokens, cov, remaining_actions=0),
                depth=1,
            )
            generated += 1

    trace = SearchTrace(
        algorithm="beam",
        expanded=expanded,
        generated=generated,
        beam_width=width,
        max_depth=depth_lim,
        best_f=float(best.f),
        best_path=list(best.path),
        notes="beam search over marketplace/plane catalog",
    )
    return best, trace


def astar_search(
    task: str,
    tools: Sequence[dict[str, Any]],
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
    prefer_marketplace: bool = True,
) -> tuple[SearchNode, SearchTrace]:
    """A* search over catalog actions (f = g + h).

    g = cumulative step_cost(score); h = uncovered task-token fraction.
    Offline / deterministic — no LLM value model.
    """
    task = str(task or "").strip()
    if not task:
        raise SearchPlanError("task must be non-empty")
    idx = _index_tools(tools)
    if not idx:
        empty = SearchNode(h=1.0)
        return empty, SearchTrace(
            algorithm="astar",
            max_depth=int(max_depth),
            notes="empty catalog",
        )

    tokens = mla._tokenize(task)  # noqa: SLF001
    depth_lim = max(1, int(max_depth))
    exp_lim = max(1, int(max_expansions))
    root = SearchNode(
        h=heuristic_h(tokens, frozenset(), remaining_actions=depth_lim),
    )
    heap: list[_HeapItem] = []
    seq = 0
    heapq.heappush(heap, _HeapItem(f=root.f, seq=seq, node=root))
    best = root
    expanded = 0
    generated = 0
    seen: dict[tuple[str, ...], float] = {(): root.f}

    while heap and expanded < exp_lim:
        item = heapq.heappop(heap)
        node = item.node
        expanded += 1

        if node.path and (
            not best.path
            or node.h < best.h
            or (abs(node.h - best.h) < 1e-9 and node.g < best.g)
            or (
                abs(node.h - best.h) < 1e-9
                and abs(node.g - best.g) < 1e-9
                and len(node.covered) > len(best.covered)
            )
        ):
            best = node

        if node.path and not uncovered_tokens(tokens, node.covered):
            best = node
            break
        if node.depth >= depth_lim:
            continue

        used = set(node.path)
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for name, entry in idx.items():
            if name in used:
                continue
            sc = action_score(tokens, entry)
            if prefer_marketplace and entry.get("search_family") == "plane" and sc < 2.0:
                continue
            if sc <= 0 and prefer_marketplace:
                continue
            scored.append((sc, name, entry))
        if not scored and not node.path:
            # expand weak top-1 so A* still returns something
            ranked = sorted(
                ((action_score(tokens, e), n, e) for n, e in idx.items()),
                key=lambda x: (-x[0], x[1]),
            )
            if ranked:
                scored = [ranked[0]]

        for sc, name, entry in scored:
            new_cover = node.covered | tokens_covered_by(entry, tokens)
            child = SearchNode(
                path=node.path + (name,),
                scores=node.scores + (sc,),
                covered=new_cover,
                g=node.g + step_cost(sc),
                h=heuristic_h(
                    tokens,
                    new_cover,
                    remaining_actions=depth_lim - (node.depth + 1),
                ),
                depth=node.depth + 1,
            )
            generated += 1
            key = child.path
            prev = seen.get(key)
            if prev is not None and prev <= child.f:
                continue
            seen[key] = child.f
            seq += 1
            heapq.heappush(heap, _HeapItem(f=child.f, seq=seq, node=child))

    if not best.path:
        ranked = sorted(
            ((action_score(tokens, e), n) for n, e in idx.items()),
            key=lambda x: (-x[0], x[1]),
        )
        if ranked:
            sc, name = ranked[0]
            entry = idx[name]
            cov = tokens_covered_by(entry, tokens)
            best = SearchNode(
                path=(name,),
                scores=(sc,),
                covered=cov,
                g=step_cost(sc),
                h=heuristic_h(tokens, cov, remaining_actions=0),
                depth=1,
            )
            generated += 1

    trace = SearchTrace(
        algorithm="astar",
        expanded=expanded,
        generated=generated,
        beam_width=0,
        max_depth=depth_lim,
        best_f=float(best.f),
        best_path=list(best.path),
        notes=f"A* max_expansions={exp_lim}",
    )
    return best, trace


def run_search(
    task: str,
    tools: Sequence[dict[str, Any]],
    *,
    algorithm: str = "beam",
    beam_width: int = DEFAULT_BEAM_WIDTH,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
    prefer_marketplace: bool = True,
) -> tuple[SearchNode, SearchTrace]:
    """Dispatch to beam or A*."""
    algo = str(algorithm or "beam").strip().lower()
    if algo not in ALGORITHMS:
        raise SearchPlanError(
            f"unknown algorithm {algorithm!r}; expected one of {sorted(ALGORITHMS)}"
        )
    if algo == "astar":
        return astar_search(
            task,
            tools,
            max_depth=max_depth,
            max_expansions=max_expansions,
            prefer_marketplace=prefer_marketplace,
        )
    return beam_search(
        task,
        tools,
        beam_width=beam_width,
        max_depth=max_depth,
        prefer_marketplace=prefer_marketplace,
    )


# ── plan construction ───────────────────────────────────────────────────────


def _plane_guide_steps(
    job_id: str,
    task: str,
    *,
    n_component_steps: int,
    spend_tokens: int = 16,
) -> list[mla.PlanStep]:
    """Control-plane governance shell that wraps search-selected components.

    Shape: upsert(inbox) → running → (components inserted by caller) →
    record_spend → completed. Planner does not write SQLite.
    """
    jid = str(job_id or "").strip() or f"search-{uuid.uuid4().hex[:10]}"
    title = (task or "search plan")[:80]
    steps: list[mla.PlanStep] = [
        mla.PlanStep(
            id=1,
            tool=cpp.TOOL_UPSERT_JOB,
            args={
                "job_id": jid,
                "kind": "task",
                "title": title,
                "status": "inbox",
                "goal": task,
                "meta": {
                    "source": SCHEMA,
                    "search_guided": True,
                    "n_components": int(n_component_steps),
                },
            },
            rationale="open search-guided job on control plane (inbox)",
        ),
        mla.PlanStep(
            id=2,
            tool=cpp.TOOL_SET_STATUS,
            args={"job_id": jid, "status": "running"},
            rationale="start search-guided execution; status → running",
        ),
    ]
    return steps


def _plane_close_steps(
    job_id: str,
    *,
    start_id: int,
    spend_tokens: int = 16,
    include_report: bool = True,
) -> list[mla.PlanStep]:
    jid = str(job_id or "").strip()
    steps: list[mla.PlanStep] = [
        mla.PlanStep(
            id=start_id,
            tool=cpp.TOOL_RECORD_SPEND,
            args={
                "job_id": jid,
                "tokens": int(spend_tokens),
                "source": "search_plane_planner",
                "label": "search_plan",
            },
            rationale="attribute search-plan spend on control plane",
        ),
        mla.PlanStep(
            id=start_id + 1,
            tool=cpp.TOOL_SET_STATUS,
            args={"job_id": jid, "status": "completed"},
            rationale="complete search-guided job (sticky terminal)",
        ),
    ]
    if include_report:
        steps.append(
            mla.PlanStep(
                id=start_id + 2,
                tool=cpp.TOOL_SPEND_REPORT,
                args={"job_id": jid},
                rationale="operator spend report for search-guided job",
            )
        )
    return steps


def node_to_plan(
    task: str,
    node: SearchNode,
    tools: Sequence[dict[str, Any]],
    *,
    trace: Optional[SearchTrace] = None,
    guide_plane: bool = True,
    job_id: str = "",
    auto_ready: bool = True,
    spend_tokens: int = 16,
    include_report: bool = True,
) -> mla.ToolPlan:
    """Materialize a :class:`ToolPlan` from a search node (+ optional plane shell)."""
    idx = _index_tools(tools)
    jid = str(job_id or "").strip() or f"search-{uuid.uuid4().hex[:10]}"
    steps: list[mla.PlanStep] = []
    sid = 1

    if guide_plane:
        shell = _plane_guide_steps(
            jid, task, n_component_steps=len(node.path), spend_tokens=spend_tokens
        )
        steps.extend(shell)
        sid = len(steps) + 1

    for i, name in enumerate(node.path):
        entry = idx.get(name) or {"name": name}
        sc = float(node.scores[i]) if i < len(node.scores) else 0.0
        args: dict[str, Any] = {
            "search_score": sc,
            "search_family": entry.get("search_family") or "marketplace",
        }
        # Marketplace component identity
        if entry.get("marketplace") or entry.get("search_family") == "marketplace":
            parsed = mplan.parse_component_tool_id(name)
            args["kind"] = entry.get("kind") or parsed.get("kind") or ""
            args["component"] = entry.get("component") or parsed.get("name") or name
            if entry.get("plugin_id") or parsed.get("plugin_id"):
                args["plugin_id"] = entry.get("plugin_id") or parsed.get("plugin_id")
            if entry.get("path"):
                args["path"] = entry["path"]
        if entry.get("search_family") == "plane" or str(name).startswith("plane."):
            args.setdefault("job_id", jid)
            args["plane_tool"] = name
        steps.append(
            mla.PlanStep(
                id=sid,
                tool=name,
                args=args,
                rationale=(
                    f"search {trace.algorithm if trace else 'beam'} "
                    f"score={sc:.1f} g={node.g:.3f} h={node.h:.3f}"
                ),
                status=mla.STEP_PENDING,
            )
        )
        sid += 1

    if guide_plane:
        close = _plane_close_steps(
            jid,
            start_id=sid,
            spend_tokens=spend_tokens,
            include_report=include_report,
        )
        steps.extend(close)

    tools_available = [str(t.get("name") or "") for t in tools if t.get("name")]
    # also list plane tools used in shell
    for s in steps:
        if s.tool not in tools_available:
            tools_available.append(s.tool)

    algo = (trace.algorithm if trace else "beam")
    plan = mla.ToolPlan(
        task=task,
        steps=steps,
        status=mla.STATUS_DRAFT,
        planner=f"search-plane-{algo}",
        tools_available=tools_available,
        notes=f"tree search ({algo}) → control plane guide",
        paper=PAPER,
        meta={
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "control_plane_pattern": CONTROL_PLANE_PATTERN,
            "handoff": "search_plane_planner",
            "job_id": jid,
            "guide_plane": bool(guide_plane),
            "search": (trace.to_dict() if trace else node.to_dict()),
            "node": node.to_dict(),
            "catalog": catalog_summary(tools),
            "ts": time.time(),
        },
    )
    if auto_ready and plan.steps:
        allowed = list(dict.fromkeys(tools_available))
        mla.mark_ready(plan, allowed_tools=allowed, require_steps=True)
    return plan


# ── Planner façade ──────────────────────────────────────────────────────────


@dataclass
class SearchPlanePlanner:
    """Search-based Planner: beam/A* over marketplace catalog → plane guide.

    Does **not** execute marketplace components or write the ops plane during
    :meth:`plan`. Produces a ready :class:`multi_llm_agent.ToolPlan`.
    """

    workdir: Path | str = "."
    plugins_dir: str = mp.DEFAULT_PLUGINS_DIR
    kinds: tuple[str, ...] = mplan.DEFAULT_KINDS
    algorithm: str = "beam"
    beam_width: int = DEFAULT_BEAM_WIDTH
    max_depth: int = DEFAULT_MAX_DEPTH
    max_expansions: int = DEFAULT_MAX_EXPANSIONS
    include_plane: bool = True
    guide_plane: bool = True
    prefer_marketplace: bool = True
    max_privilege: Optional[str] = None
    disambiguate: bool = True
    auto_ready: bool = True
    _tools: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _loaded: bool = field(default=False, repr=False)

    def load_catalog(self, *, force: bool = False) -> list[dict[str, Any]]:
        if self._loaded and not force and self._tools:
            return list(self._tools)
        self._tools = hybrid_catalog(
            self.workdir,
            plugins_dir=self.plugins_dir,
            kinds=self.kinds,
            include_plane=self.include_plane,
            max_privilege=self.max_privilege,
            disambiguate=self.disambiguate,
        )
        self._loaded = True
        return list(self._tools)

    @property
    def tools(self) -> list[dict[str, Any]]:
        return self.load_catalog()

    def search(
        self,
        task: str,
        *,
        algorithm: Optional[str] = None,
    ) -> tuple[SearchNode, SearchTrace]:
        catalog = self.load_catalog()
        return run_search(
            task,
            catalog,
            algorithm=algorithm or self.algorithm,
            beam_width=self.beam_width,
            max_depth=self.max_depth,
            max_expansions=self.max_expansions,
            prefer_marketplace=self.prefer_marketplace,
        )

    def plan(
        self,
        task: str,
        *,
        algorithm: Optional[str] = None,
        guide_plane: Optional[bool] = None,
        job_id: str = "",
        auto_ready: Optional[bool] = None,
        spend_tokens: int = 16,
    ) -> mla.ToolPlan:
        """Search then materialize a ready plan (no side effects)."""
        task = str(task or "").strip()
        if not task:
            raise SearchPlanError("task must be non-empty")
        catalog = self.load_catalog()
        if not catalog:
            plan = mla.ToolPlan(
                task=task,
                steps=[],
                status=mla.STATUS_DRAFT,
                planner="search-plane-empty",
                tools_available=[],
                notes="empty hybrid catalog",
                paper=PAPER,
                meta={
                    "schema": SCHEMA,
                    "paper": PAPER,
                    "source_pattern": SOURCE_PATTERN,
                    "handoff": "search_plane_planner",
                    "catalog": catalog_summary([]),
                },
            )
            return plan

        node, trace = self.search(task, algorithm=algorithm)
        do_guide = self.guide_plane if guide_plane is None else guide_plane
        do_ready = self.auto_ready if auto_ready is None else auto_ready
        return node_to_plan(
            task,
            node,
            catalog,
            trace=trace,
            guide_plane=do_guide,
            job_id=job_id,
            auto_ready=do_ready,
            spend_tokens=spend_tokens,
        )

    def prompt_block(self, task: str) -> str:
        """System prompt fragment describing search + marketplace catalog."""
        catalog = self.load_catalog()
        summary = catalog_summary(catalog)
        names = [str(t.get("name") or "") for t in catalog[:40]]
        lines = [
            f"# Search-based plane planner — {PAPER} × {SOURCE_PATTERN}",
            f"# Schema: {SCHEMA}",
            f"# Algorithm: {self.algorithm} (beam_width={self.beam_width}, "
            f"max_depth={self.max_depth})",
            "# Expand a search tree over marketplace components; wrap with "
            "control-plane governance (upsert → running → components → "
            "spend → completed).",
            "# Do NOT execute tools — output ordered plan only.",
            f"# Catalog: n={summary['n_tools']} by_family={summary['by_family']} "
            f"by_kind={summary['by_kind']}",
            f"# Task: {task}",
            "# Available tools (truncated):",
        ]
        for n in names:
            lines.append(f"  - {n}")
        if len(catalog) > 40:
            lines.append(f"  … +{len(catalog) - 40} more")
        return "\n".join(lines) + "\n"


def plan_from_search(
    task: str,
    *,
    workdir: Path | str = ".",
    plugins_dir: str = mp.DEFAULT_PLUGINS_DIR,
    kinds: Optional[Iterable[str]] = None,
    algorithm: str = "beam",
    beam_width: int = DEFAULT_BEAM_WIDTH,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
    include_plane: bool = True,
    guide_plane: bool = True,
    job_id: str = "",
    auto_ready: bool = True,
    prefer_marketplace: bool = True,
) -> mla.ToolPlan:
    """Convenience: one-shot search-based plan (no tool execution)."""
    kinds_t = tuple(kinds) if kinds is not None else mplan.DEFAULT_KINDS
    planner = SearchPlanePlanner(
        workdir=workdir,
        plugins_dir=plugins_dir,
        kinds=kinds_t,
        algorithm=algorithm,
        beam_width=beam_width,
        max_depth=max_depth,
        max_expansions=max_expansions,
        include_plane=include_plane,
        guide_plane=guide_plane,
        prefer_marketplace=prefer_marketplace,
        auto_ready=auto_ready,
    )
    return planner.plan(task, job_id=job_id, auto_ready=auto_ready)


def plan_payload(plan: mla.ToolPlan) -> dict[str, Any]:
    """JSON-safe plan payload with search-plane schema stamp."""
    base = mla.plan_payload_for_meta(plan)
    base["search_plane_schema"] = SCHEMA
    base["source_pattern"] = SOURCE_PATTERN
    base["paper"] = PAPER
    meta = dict(base.get("meta") or {})
    meta.update(
        {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "paper": PAPER,
            "handoff": meta.get("handoff") or "search_plane_planner",
        }
    )
    if isinstance(plan.meta, dict):
        for k in ("catalog", "search", "node", "job_id", "guide_plane"):
            if k in plan.meta:
                meta[k] = plan.meta[k]
    base["meta"] = meta
    return base


# ── guide control plane + orchestrator ──────────────────────────────────────


def plan_and_guide(
    task: str,
    *,
    workdir: Any = None,
    algorithm: str = "beam",
    beam_width: int = DEFAULT_BEAM_WIDTH,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
    plugins_dir: str = mp.DEFAULT_PLUGINS_DIR,
    kinds: Optional[Iterable[str]] = None,
    require_ready: bool = True,
    job_id: str = "",
    govern: bool = True,
    spend_tokens: int = 16,
) -> dict[str, Any]:
    """Search plan, stamp ops job meta, optionally execute plane shell on SQLite.

    Marketplace component steps are **not** executed (no agent/skill side
    effects). Plane steps (upsert/status/spend/report) run when *govern* is
    True so the control plane is guided by the search result.
    """
    root = Path(workdir).resolve() if workdir is not None else Path.cwd()
    jid = str(job_id or "").strip() or f"search-{uuid.uuid4().hex[:10]}"
    plan = plan_from_search(
        task,
        workdir=root,
        plugins_dir=plugins_dir,
        kinds=kinds,
        algorithm=algorithm,
        beam_width=beam_width,
        max_depth=max_depth,
        max_expansions=max_expansions,
        guide_plane=True,
        job_id=jid,
        auto_ready=True,
    )
    payload = plan_payload(plan)

    if require_ready and not plan.is_ready():
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "ok": False,
            "error": "search_produced_no_ready_plan",
            "phase": "plan",
            "plan": payload,
            "guide": None,
            "job": None,
            "catalog": (plan.meta or {}).get("catalog") or catalog_summary([]),
        }

    guide_report: Optional[dict[str, Any]] = None
    job_row: Optional[dict[str, Any]] = None
    if govern:
        # Only execute plane.* steps; skip marketplace component steps.
        plane_steps = [
            mla.PlanStep.from_dict(s.to_dict())
            for s in plan.steps
            if str(s.tool).startswith("plane.")
        ]
        for i, s in enumerate(plane_steps, start=1):
            s.id = i
            s.status = mla.STEP_PENDING
            s.result = None
            s.error = ""
            s.args = dict(s.args or {})
            s.args.setdefault("job_id", jid)
        gov_plan = mla.ToolPlan(
            task=task,
            steps=plane_steps,
            status=mla.STATUS_DRAFT,
            planner="search-plane-govern",
            tools_available=list(cpp.PLANE_TOOL_NAMES),
            paper=PAPER,
            meta={"schema": SCHEMA, "job_id": jid, "search_guided": True},
        )
        if plane_steps:
            mla.mark_ready(
                gov_plan,
                allowed_tools=list(cpp.PLANE_TOOL_NAMES),
                require_steps=True,
            )
        with ops.OpsStore.open(root) as store:
            # Stamp full search plan onto job meta before/with upsert
            search_meta = {
                "search_plane_schema": SCHEMA,
                "paper": PAPER,
                "source_pattern": SOURCE_PATTERN,
                "search": (plan.meta or {}).get("search"),
                "node": (plan.meta or {}).get("node"),
                "tool_plan": plan.to_dict(),
                "guided_at": time.time(),
            }
            registry = cpp.make_ops_registry(store, default_job_id=jid)
            # Ensure upsert carries search meta
            if gov_plan.steps and gov_plan.steps[0].tool == cpp.TOOL_UPSERT_JOB:
                meta_arg = dict(gov_plan.steps[0].args.get("meta") or {})
                meta_arg.update(search_meta)
                gov_plan.steps[0].args["meta"] = meta_arg
            if plane_steps:
                caller = mla.Caller(registry=registry)
                caller.set_plan(gov_plan, require_ready=True)
                results = caller.execute_all(stop_on_error=True)
                summary = mla.summarize_run(gov_plan, results)
            else:
                results = []
                summary = {"ok": True, "n_steps": 0}
            # Dual-stamp meta even if upsert args were incomplete
            row = store.get(jid)
            if row is not None:
                merged = dict(row.get("meta") or {})
                merged.update(search_meta)
                store.upsert_job(
                    jid,
                    kind=str(row.get("kind") or "task"),
                    title=str(row.get("title") or jid),
                    status=str(row.get("status") or "inbox"),
                    goal=str(row.get("goal") or task),
                    meta=merged,
                )
            else:
                store.upsert_job(
                    jid,
                    kind="task",
                    title=task[:80],
                    status="inbox",
                    goal=task,
                    meta=search_meta,
                )
            job_row = store.get(jid)
            guide_report = {
                "ok": bool(summary.get("ok")),
                "job_id": jid,
                "n_plane_steps": len(plane_steps),
                "n_calls": len(results),
                "summary": summary,
                "search": (plan.meta or {}).get("search"),
            }

    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "ok": True if guide_report is None else bool(guide_report.get("ok")),
        "error": None,
        "phase": "guide" if govern else "plan",
        "plan": plan.to_dict(),
        "guide": guide_report,
        "job_id": jid,
        "job": job_row,
        "catalog": (plan.meta or {}).get("catalog"),
        "search": (plan.meta or {}).get("search"),
    }


def plan_and_handoff(
    description: str,
    *,
    workdir: Any = None,
    algorithm: str = "beam",
    beam_width: int = DEFAULT_BEAM_WIDTH,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
    plugins_dir: str = mp.DEFAULT_PLUGINS_DIR,
    kinds: Optional[Iterable[str]] = None,
    require_ready: bool = True,
    agent_mode: str = "fake",
    task_id: Optional[str] = None,
    kind: str = "task",
    wait: bool = False,
    wait_timeout_s: float = 120.0,
    sync_fake: bool = True,
    meta: Optional[dict[str, Any]] = None,
    govern: bool = True,
) -> dict[str, Any]:
    """Search plan → guide control plane → Orchestrator ``with_plan``.

    Pattern: arXiv 2407.01476 tree search + wshobson marketplace catalog +
    control-plane governance + durable Orchestrator execution.
    """
    from . import orchestrator as orch

    root = Path(workdir).resolve() if workdir is not None else Path.cwd()
    jid = str(task_id or "").strip() or f"search-{uuid.uuid4().hex[:10]}"

    plan = plan_from_search(
        description,
        workdir=root,
        plugins_dir=plugins_dir,
        kinds=kinds,
        algorithm=algorithm,
        beam_width=beam_width,
        max_depth=max_depth,
        max_expansions=max_expansions,
        guide_plane=True,
        job_id=jid,
        auto_ready=True,
    )
    payload = plan_payload(plan)

    if require_ready and not plan.is_ready():
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "ok": False,
            "error": "search_produced_no_ready_plan",
            "phase": "plan",
            "plan": payload,
            "guide": None,
            "orchestrator": None,
            "catalog": (plan.meta or {}).get("catalog") or catalog_summary([]),
        }

    # Pristine plan for orchestrator (govern mutates step status)
    orch_plan = mla.ToolPlan.from_dict(plan.to_dict())
    if orch_plan.status != mla.STATUS_READY and orch_plan.steps:
        allowed = list(orch_plan.tools_available or [])
        for s in orch_plan.steps:
            if s.tool not in allowed:
                allowed.append(s.tool)
        mla.mark_ready(orch_plan, allowed_tools=allowed, require_steps=True)

    guide_report: Optional[dict[str, Any]] = None
    if govern:
        guided = plan_and_guide(
            description,
            workdir=root,
            algorithm=algorithm,
            beam_width=beam_width,
            max_depth=max_depth,
            max_expansions=max_expansions,
            plugins_dir=plugins_dir,
            kinds=kinds,
            require_ready=True,
            job_id=jid,
            govern=True,
        )
        guide_report = guided.get("guide")

    extra_meta = {
        "search_plane_plan": True,
        "source_pattern": SOURCE_PATTERN,
        "search_plane_schema": SCHEMA,
        "paper": PAPER,
        "ops_job_id": jid,
        "search": (plan.meta or {}).get("search"),
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
    guide_ok = True if guide_report is None else bool(guide_report.get("ok"))
    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "ok": bool(orch_ok and guide_ok),
        "error": None,
        "phase": "orchestrator",
        "plan": status.get("plan") or payload,
        "guide": guide_report,
        "orchestrator": status,
        "job_id": jid,
        "catalog": (plan.meta or {}).get("catalog"),
        "search": (plan.meta or {}).get("search"),
    }


# ── formatting ──────────────────────────────────────────────────────────────


def format_search_plan(plan: mla.ToolPlan | dict[str, Any]) -> str:
    """Human-readable plan with search-plane schema header."""
    d = plan.to_dict() if isinstance(plan, mla.ToolPlan) else dict(plan or {})
    meta = d.get("meta") or {}
    cat = meta.get("catalog") or {}
    search = meta.get("search") or {}
    lines = [
        f"schema:     {SCHEMA}",
        f"paper:      {d.get('paper') or PAPER}",
        f"source:     {SOURCE_PATTERN}",
        f"task:       {d.get('task')}",
        f"status:     {d.get('status')}",
        f"planner:    {d.get('planner')}",
        f"steps:      {d.get('n_steps', len(d.get('steps') or []))}",
        f"job_id:     {meta.get('job_id') or '?'}",
        f"search:     algo={search.get('algorithm', '?')} "
        f"expanded={search.get('expanded', '?')} "
        f"generated={search.get('generated', '?')} "
        f"best_f={search.get('best_f', '?')}",
        f"catalog:    n={cat.get('n_tools', '?')} "
        f"by_family={cat.get('by_family', {})} by_kind={cat.get('by_kind', {})}",
        "",
    ]
    for s in d.get("steps") or []:
        args = s.get("args") or {}
        fam = args.get("search_family") or (
            "plane" if str(s.get("tool") or "").startswith("plane.") else "?"
        )
        lines.append(
            f"  [{s.get('id')}] {s.get('tool')}  family={fam}  "
            f"score={args.get('search_score', '-')}  "
            f"status={s.get('status')}"
        )
        if s.get("rationale"):
            lines.append(f"       why: {s.get('rationale')}")
    return "\n".join(lines)


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"ok:       {report.get('ok')}",
        f"phase:    {report.get('phase')}",
        f"paper:    {report.get('paper') or PAPER}",
        f"source:   {report.get('source_pattern') or SOURCE_PATTERN}",
        f"error:    {report.get('error')}",
        f"schema:   {report.get('schema') or SCHEMA}",
        f"job_id:   {report.get('job_id') or '?'}",
    ]
    search = report.get("search") or {}
    if search:
        lines.append(
            f"search:   algo={search.get('algorithm')} "
            f"expanded={search.get('expanded')} path={search.get('best_path')}"
        )
    cat = report.get("catalog") or {}
    if cat:
        lines.append(
            f"catalog:  tools={cat.get('n_tools')} "
            f"families={cat.get('by_family')} kinds={cat.get('by_kind')}"
        )
    plan = report.get("plan") or {}
    lines.append(
        f"plan:     status={plan.get('status')} steps={plan.get('n_steps')}"
    )
    guide = report.get("guide") or {}
    if guide:
        lines.append(
            f"guide:    ok={guide.get('ok')} plane_steps={guide.get('n_plane_steps')}"
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
    """``python -m nexus.search_plane_planner plan|guide|handoff|catalog``."""
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(
        prog="nexus.search_plane_planner",
        description=(
            "Search-based plane planner "
            "(arXiv 2407.01476 × wshobson/agents marketplace)"
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cat = sub.add_parser("catalog", help="hybrid marketplace+plane catalog")
    p_cat.add_argument("--workdir", default=".")
    p_cat.add_argument("--plugins-dir", default=mp.DEFAULT_PLUGINS_DIR, dest="plugins_dir")
    p_cat.add_argument("--no-plane", action="store_true")
    p_cat.add_argument("--json", action="store_true")

    p_plan = sub.add_parser("plan", help="beam/A* plan only (no side effects)")
    p_plan.add_argument("task")
    p_plan.add_argument("--workdir", default=".")
    p_plan.add_argument("--plugins-dir", default=mp.DEFAULT_PLUGINS_DIR, dest="plugins_dir")
    p_plan.add_argument("--algorithm", choices=sorted(ALGORITHMS), default="beam")
    p_plan.add_argument("--beam-width", type=int, default=DEFAULT_BEAM_WIDTH, dest="beam_width")
    p_plan.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH, dest="max_depth")
    p_plan.add_argument("--no-plane-guide", action="store_true")
    p_plan.add_argument("--job-id", default="", dest="job_id")
    p_plan.add_argument("--json", action="store_true")

    p_guide = sub.add_parser("guide", help="search + guide control plane (SQLite)")
    p_guide.add_argument("task")
    p_guide.add_argument("--workdir", default=".")
    p_guide.add_argument("--plugins-dir", default=mp.DEFAULT_PLUGINS_DIR, dest="plugins_dir")
    p_guide.add_argument("--algorithm", choices=sorted(ALGORITHMS), default="beam")
    p_guide.add_argument("--beam-width", type=int, default=DEFAULT_BEAM_WIDTH, dest="beam_width")
    p_guide.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH, dest="max_depth")
    p_guide.add_argument("--job-id", default="", dest="job_id")
    p_guide.add_argument("--json", action="store_true")

    p_hand = sub.add_parser("handoff", help="search → guide → Orchestrator")
    p_hand.add_argument("task")
    p_hand.add_argument("--workdir", default=".")
    p_hand.add_argument("--plugins-dir", default=mp.DEFAULT_PLUGINS_DIR, dest="plugins_dir")
    p_hand.add_argument("--algorithm", choices=sorted(ALGORITHMS), default="beam")
    p_hand.add_argument("--beam-width", type=int, default=DEFAULT_BEAM_WIDTH, dest="beam_width")
    p_hand.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH, dest="max_depth")
    p_hand.add_argument("--task-id", default="", dest="task_id")
    p_hand.add_argument("--json", action="store_true")

    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "catalog":
        tools = hybrid_catalog(
            args.workdir,
            plugins_dir=args.plugins_dir,
            include_plane=not args.no_plane,
        )
        summary = catalog_summary(tools)
        if args.json:
            print(json.dumps({"schema": SCHEMA, "summary": summary, "tools": tools}, indent=2))
        else:
            print(
                f"schema={SCHEMA} tools={summary['n_tools']} "
                f"by_family={summary['by_family']} by_kind={summary['by_kind']}"
            )
            for t in tools:
                print(f"  - {t['name']}: {(t.get('description') or '')[:72]}")
        return 0 if tools else 1

    if args.cmd == "plan":
        plan = plan_from_search(
            args.task,
            workdir=args.workdir,
            plugins_dir=args.plugins_dir,
            algorithm=args.algorithm,
            beam_width=args.beam_width,
            max_depth=args.max_depth,
            guide_plane=not args.no_plane_guide,
            job_id=args.job_id,
        )
        if args.json:
            print(plan.to_json())
        else:
            print(format_search_plan(plan))
        return 0 if plan.steps else 1

    if args.cmd == "guide":
        report = plan_and_guide(
            args.task,
            workdir=args.workdir,
            plugins_dir=args.plugins_dir,
            algorithm=args.algorithm,
            beam_width=args.beam_width,
            max_depth=args.max_depth,
            job_id=args.job_id,
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(format_report(report))
            if report.get("plan"):
                print()
                print(format_search_plan(report["plan"]))
        return 0 if report.get("ok") else 1

    if args.cmd == "handoff":
        report = plan_and_handoff(
            args.task,
            workdir=args.workdir,
            plugins_dir=args.plugins_dir,
            algorithm=args.algorithm,
            beam_width=args.beam_width,
            max_depth=args.max_depth,
            task_id=args.task_id or None,
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(format_report(report))
            if report.get("plan"):
                print()
                print(format_search_plan(report["plan"]))
        return 0 if report.get("ok") else 1

    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
