"""SWE-Adept × routa delivery board: localization→resolution as kanban lanes.

Cross-pattern hybrid (portfolio novel:arxiv:2603.01327v2+phodal/routa):

  arXiv 2603.01327v2 SWE-Adept
      structured multi-step planning that **separates localization**
      (identify issue-relevant files) from **resolution** (edit/test/verify)
                ×
  phodal/routa (shape only — not a vendored monorepo)
      multi-agent software-delivery board
      Backlog → Todo → Dev → Review → Done
      + lane specialists + traces + evidence + review signal

Maps SWE-Adept phases onto a routa-shaped board so the orchestrator exposes
a visible delivery surface **before** workers edit code::

  issue
    │
    ▼
  localization  ──►  backlog / todo   (Localizer specialist)
    targets[]
    │
    ▼
  resolution    ──►  dev / review / done  (Crafter → Gate → Reporter)
    resolve.*

Schema: ``nexus.swe_delivery_board/v1``

Offline-first; reuses in-tree :mod:`nexus.swe_adept_plan`. Does **not** vendor
Routa (Next.js/Tauri/Rust) or the paper implementation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from . import swe_adept_plan as sap

SCHEMA = "nexus.swe_delivery_board/v1"
PAPER = sap.PAPER  # arxiv:2603.01327v2
SOURCE_PATTERN = "phodal/routa"
SOURCE_URL = "https://github.com/phodal/routa"
IDEA_ID = "novel:arxiv:2603.01327v2+phodal/routa"

# routa-shaped kanban lanes (happy path + blocked escape)
LANES: tuple[str, ...] = ("backlog", "todo", "dev", "review", "done")
LANE_BLOCKED = "blocked"
ALL_LANES = frozenset(LANES) | {LANE_BLOCKED}

# Lane specialists (routa README shape, abbreviated + SWE-Adept roles)
SPECIALISTS: dict[str, str] = {
    "backlog": "Backlog Refiner",
    "todo": "Localizer",  # SWE-Adept localization (where?)
    "dev": "Dev Crafter",  # SWE-Adept resolution edit
    "review": "Review Guard",  # resolve.test / resolve.verify
    "done": "Done Reporter",
    "blocked": "Blocked Resolver",
}

# Anti-collusion roles (localizer ≠ resolver ≠ gate)
ROLES: dict[str, str] = {
    "localizer": "swe:localize",
    "resolver": "swe:resolve",
    "gate": "routa:gate",
}

# SWE-Adept phase / action → default lane
_LOCATE_LANE = "todo"
_RESOLVE_EDIT_LANE = "dev"
_RESOLVE_VERIFY_LANE = "review"
_RESOLVE_DONE_LANE = "done"


class DeliveryBoardError(ValueError):
    """Board invalid for delivery handoff."""


@dataclass
class BoardCard:
    """One delivery card on the board (workspace-first, routa shape)."""

    id: str
    goal: str
    lane: str = "backlog"
    specialist: str = SPECIALISTS["backlog"]
    targets: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    phase: str = sap.PHASE_LOCALIZATION
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "lane": self.lane,
            "specialist": self.specialist,
            "targets": list(self.targets),
            "acceptance": list(self.acceptance),
            "phase": self.phase,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BoardCard":
        lane = str(d.get("lane") or "backlog")
        if lane not in ALL_LANES:
            lane = "backlog"
        return cls(
            id=str(d.get("id") or "card"),
            goal=str(d.get("goal") or ""),
            lane=lane,
            specialist=str(d.get("specialist") or SPECIALISTS.get(lane, "")),
            targets=[str(t) for t in (d.get("targets") or []) if t],
            acceptance=[str(a) for a in (d.get("acceptance") or []) if a],
            phase=str(d.get("phase") or sap.PHASE_LOCALIZATION),
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
        )


@dataclass
class DeliveryBoard:
    """Routa-shaped multi-agent delivery board driven by a SWE-Adept plan."""

    goal: str
    card: BoardCard
    lanes: list[str] = field(default_factory=lambda: list(LANES))
    lane_history: list[str] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=lambda: dict(ROLES))
    traces: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    handoffs: list[dict[str, str]] = field(default_factory=list)
    localization: dict[str, Any] = field(default_factory=dict)
    resolution: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    signal: str = "continue"
    status: str = "ready"
    paper: str = PAPER
    source_pattern: str = SOURCE_PATTERN
    notes: str = ""
    ts: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "paper": self.paper,
            "source_pattern": self.source_pattern,
            "source_url": SOURCE_URL,
            "idea_id": IDEA_ID,
            "goal": self.goal,
            "card": self.card.to_dict(),
            "lanes": list(self.lanes),
            "lane_history": list(self.lane_history),
            "roles": dict(self.roles),
            "roles_ok": roles_distinct(self.roles),
            "traces": list(self.traces),
            "evidence": list(self.evidence),
            "handoffs": list(self.handoffs),
            "localization": dict(self.localization),
            "resolution": dict(self.resolution),
            "decision": dict(self.decision),
            "signal": self.signal,
            "status": self.status,
            "notes": self.notes,
            "ts": self.ts,
            "meta": dict(self.meta),
        }


def roles_distinct(roles: dict[str, str]) -> bool:
    """Anti-collusion: localizer / resolver / gate must be distinct principals."""
    vals = [str(v).strip() for v in (roles or {}).values() if str(v).strip()]
    return len(vals) >= 3 and len(set(vals)) == len(vals)


def _action_lane(action: str, phase: str) -> str:
    a = str(action or "").strip().lower()
    p = str(phase or "").strip().lower()
    if p == sap.PHASE_LOCALIZATION or a.startswith("locate.") or a.startswith(
        "localization."
    ):
        return _LOCATE_LANE
    if a.startswith("resolve.edit") or a.startswith("resolve.patch") or a.startswith(
        "resolve.read"
    ):
        return _RESOLVE_EDIT_LANE
    if a.startswith("resolve.test") or a.startswith("resolve.verify"):
        return _RESOLVE_VERIFY_LANE
    if a.startswith("resolve.checkpoint") or a.startswith("resolve.done"):
        return _RESOLVE_DONE_LANE
    if p == sap.PHASE_RESOLUTION:
        return _RESOLVE_EDIT_LANE
    return "backlog"


def _walk_lanes_for_plan(
    plan: sap.SweAdeptPlan,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    """Derive lane history, traces, evidence, handoffs from SWE phases.

    Planning surface (not runtime execution): walks the happy-path lanes that
    the plan **implies**, so operators see localization before resolution.
    """
    history: list[str] = ["backlog"]
    traces: list[dict[str, Any]] = [
        {
            "lane": "backlog",
            "agent": SPECIALISTS["backlog"],
            "action": "accept_issue",
            "phase": sap.PHASE_LOCALIZATION,
            "from": None,
        }
    ]
    evidence: list[dict[str, Any]] = [
        {
            "lane": "backlog",
            "kind": "story",
            "ok": True,
            "ref": "issue:accepted",
            "detail": (plan.task or "")[:160],
        }
    ]
    handoffs: list[dict[str, str]] = []

    def _enter(lane: str, *, phase: str, action: str = "handoff", detail: str = "") -> None:
        """Lane transitions only — never emit per-step traces (loop body does)."""
        prev = history[-1] if history else None
        if prev == lane:
            return  # stay-in-lane: no handoff, no duplicate step trace
        history.append(lane)
        if prev is not None:
            handoffs.append({"from": prev, "to": lane})
        traces.append(
            {
                "lane": lane,
                "agent": SPECIALISTS.get(lane, lane),
                "action": "handoff" if prev is not None else action,
                "phase": phase,
                "from": prev,
                "detail": detail[:120],
            }
        )

    # Localization → todo
    if plan.localization.steps or plan.localization.targets:
        _enter(
            _LOCATE_LANE,
            phase=sap.PHASE_LOCALIZATION,
            action="localize",
            detail=f"targets={len(plan.localization.targets)}",
        )
        for s in plan.localization.steps:
            traces.append(
                {
                    "lane": _LOCATE_LANE,
                    "agent": SPECIALISTS[_LOCATE_LANE],
                    "action": s.action,
                    "phase": sap.PHASE_LOCALIZATION,
                    "step_id": s.id,
                    "target": s.target or "",
                    "from": _LOCATE_LANE,
                }
            )
        for t in plan.localization.targets[:12]:
            evidence.append(
                {
                    "lane": _LOCATE_LANE,
                    "kind": "localization_target",
                    "ok": True,
                    "ref": t,
                    "detail": "localized path",
                }
            )
        if plan.localization.hits:
            evidence.append(
                {
                    "lane": _LOCATE_LANE,
                    "kind": "localization_hits",
                    "ok": True,
                    "ref": f"hits:{len(plan.localization.hits)}",
                    "detail": ",".join(
                        f"{h.path}:{h.score:.1f}" for h in plan.localization.hits[:5]
                    ),
                }
            )

    # Resolution steps → dev / review / done
    seen_review = False
    for s in plan.resolution.steps:
        lane = _action_lane(s.action, s.phase or sap.PHASE_RESOLUTION)
        _enter(
            lane,
            phase=sap.PHASE_RESOLUTION,
            action=s.action,
            detail=s.target or s.rationale or "",
        )
        traces.append(
            {
                "lane": lane,
                "agent": SPECIALISTS.get(lane, lane),
                "action": s.action,
                "phase": sap.PHASE_RESOLUTION,
                "step_id": s.id,
                "target": s.target or "",
                "from": lane,
            }
        )
        kind = {
            "dev": "dev_evidence",
            "review": "acceptance_check",
            "done": "completion_summary",
        }.get(lane, "note")
        evidence.append(
            {
                "lane": lane,
                "kind": kind,
                "ok": True,
                "ref": f"{s.id}:{s.action}",
                "detail": (s.target or s.rationale or "")[:120],
            }
        )
        if lane == "review":
            seen_review = True

    # If resolution planned but never reached review, still open review gate
    # for operator visibility when targets exist.
    if plan.resolution.steps and not seen_review and plan.localization.targets:
        _enter(
            _RESOLVE_VERIFY_LANE,
            phase=sap.PHASE_RESOLUTION,
            action="gate_open",
            detail="review pending execution",
        )

    return history, traces, evidence, handoffs


def current_lane_for_plan(plan: sap.SweAdeptPlan) -> str:
    """Pick the furthest planned lane (not execution progress)."""
    if not plan.resolution.steps and not plan.localization.targets:
        return "backlog"
    if not plan.resolution.steps:
        return _LOCATE_LANE
    # Prefer last resolution step's lane
    last = plan.resolution.steps[-1]
    return _action_lane(last.action, last.phase or sap.PHASE_RESOLUTION)


def plan_to_board(
    plan: sap.SweAdeptPlan,
    *,
    card_id: Optional[str] = None,
    roles: Optional[dict[str, str]] = None,
) -> DeliveryBoard:
    """Map a SWE-Adept plan onto a routa-shaped delivery board (no execution)."""
    if not plan.task and not plan.localization.steps:
        raise DeliveryBoardError("plan empty — nothing to put on the board")

    history, traces, evidence, handoffs = _walk_lanes_for_plan(plan)
    lane = current_lane_for_plan(plan)
    if history and history[-1] != lane:
        # Align card.lane with walk history:
        # - if walk never visited planned lane, append it
        # - if walk advanced past last step (e.g. gate_open → review), prefer history tail
        if lane not in history:
            prev = history[-1]
            history.append(lane)
            handoffs.append({"from": prev, "to": lane})
        else:
            lane = history[-1]

    cid = str(card_id or "swe-card").strip() or "swe-card"
    targets = list(plan.localization.targets)
    acceptance = [
        "localization targets identified",
        "resolution plan has edit/test/verify lifecycle",
        "tests green after resolve",
    ]
    card = BoardCard(
        id=cid,
        goal=plan.task or "",
        lane=lane,
        specialist=SPECIALISTS.get(lane, SPECIALISTS["todo"]),
        targets=targets,
        acceptance=acceptance,
        phase=(
            sap.PHASE_RESOLUTION
            if plan.resolution.steps
            else sap.PHASE_LOCALIZATION
        ),
        meta={
            "n_targets": len(targets),
            "n_localization_steps": len(plan.localization.steps),
            "n_resolution_steps": len(plan.resolution.steps),
            "plan_status": plan.status,
        },
    )
    role_map = dict(roles) if roles else dict(ROLES)
    # Review decision: plan structure ready → allow continue into execution
    ready = plan.status == sap.STATUS_READY and (
        bool(plan.localization.targets or plan.localization.steps)
        and bool(plan.resolution.steps)
    )
    decision = {
        "ok": ready,
        "reason": "plan_ready" if ready else "plan_incomplete",
        "confidence": 0.9 if ready else 0.4,
        "evidence_refs": [
            e.get("ref") for e in evidence if e.get("lane") in ("todo", "review")
        ][:8],
        "phases": [sap.PHASE_LOCALIZATION, sap.PHASE_RESOLUTION],
    }
    signal = "continue" if ready and roles_distinct(role_map) else "replan"

    return DeliveryBoard(
        goal=plan.task or "",
        card=card,
        lanes=list(LANES),
        lane_history=history,
        roles=role_map,
        traces=traces,
        evidence=evidence,
        handoffs=handoffs,
        localization={
            "targets": targets[:20],
            "n_steps": len(plan.localization.steps),
            "status": plan.localization.status,
            "hits": [
                {"path": h.path, "score": h.score, "reason": (h.reason or "")[:80]}
                for h in plan.localization.hits[:8]
            ],
        },
        resolution={
            "n_steps": len(plan.resolution.steps),
            "status": plan.resolution.status,
            "actions": [s.action for s in plan.resolution.steps[:20]],
        },
        decision=decision,
        signal=signal,
        status="ready" if ready else "draft",
        notes=(
            f"SWE-Adept×routa board: localization({len(targets)} targets) "
            f"→ resolution({len(plan.resolution.steps)} steps) lane={lane}"
        ),
        meta={
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "idea_id": IDEA_ID,
            "plan_schema": sap.SCHEMA,
            "phases": [sap.PHASE_LOCALIZATION, sap.PHASE_RESOLUTION],
        },
    )


def build_board_for_issue(
    issue: str,
    *,
    workdir: Optional[Path | str] = None,
    card_id: Optional[str] = None,
    max_targets: int = 8,
    max_resolution_steps: int = 12,
    search_roots: Sequence[str] = sap.DEFAULT_SEARCH_ROOTS,
    hints: Optional[Sequence[str]] = None,
    require_targets: bool = False,
    auto_ready: bool = True,
) -> DeliveryBoard:
    """Build SWE-Adept plan then project it onto the delivery board."""
    plan = sap.build_swe_adept_plan(
        issue,
        workdir=workdir,
        search_roots=search_roots,
        max_targets=max_targets,
        max_resolution_steps=max_resolution_steps,
        hints=hints,
        auto_ready=auto_ready,
    )
    if require_targets and not plan.localization.targets:
        raise DeliveryBoardError("localization produced no targets (require_targets)")
    if auto_ready:
        try:
            sap.mark_ready(plan, require_targets=require_targets)
        except sap.SweAdeptPlanError as e:
            raise DeliveryBoardError(str(e)) from e
    return plan_to_board(plan, card_id=card_id)


def format_board(board: DeliveryBoard | dict[str, Any]) -> str:
    """Human-readable routa-lite delivery board for SWE-Adept plans."""
    d = board.to_dict() if isinstance(board, DeliveryBoard) else dict(board)
    card = d.get("card") or {}
    roles = d.get("roles") or {}
    lines = [
        "=== NEXUS SWE delivery board (SWE-Adept × routa) ===",
        f"goal: {d.get('goal') or card.get('goal') or ''}",
        f"status: {d.get('status')}  signal: {d.get('signal')}  "
        f"paper: {d.get('paper') or PAPER}",
        f"card: {card.get('id')}  lane={card.get('lane')}  "
        f"specialist={card.get('specialist')}  phase={card.get('phase')}",
        f"roles: localizer={roles.get('localizer')}  "
        f"resolver={roles.get('resolver')}  gate={roles.get('gate')}  "
        f"[{'OK' if d.get('roles_ok') else 'COLLISION'}]",
        "",
        f"lane_history: {' → '.join(d.get('lane_history') or [])}",
        "",
        "localization targets:",
    ]
    locs = (d.get("localization") or {}).get("targets") or card.get("targets") or []
    if not locs:
        lines.append("  (none yet)")
    for t in locs[:12]:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append(
        f"resolution actions ({(d.get('resolution') or {}).get('n_steps', 0)}):"
    )
    acts = (d.get("resolution") or {}).get("actions") or []
    if not acts:
        lines.append("  (none)")
    for a in acts[:12]:
        lines.append(f"  - {a}")
    lines.append("")
    lines.append("traces (tail):")
    for tr in (d.get("traces") or [])[-8:]:
        lines.append(
            f"  [{tr.get('lane')}] {tr.get('action')} "
            f"agent={tr.get('agent')} phase={tr.get('phase')}"
        )
    dec = d.get("decision") or {}
    lines.append("")
    lines.append(
        f"decision: ok={dec.get('ok')} reason={dec.get('reason')} "
        f"confidence={dec.get('confidence')}"
    )
    if d.get("notes"):
        lines.append(f"notes: {d.get('notes')}")
    return "\n".join(lines)


def board_payload_for_meta(board: DeliveryBoard | dict[str, Any]) -> dict[str, Any]:
    """Lean JSON-safe payload for envelope / ops meta."""
    d = board.to_dict() if isinstance(board, DeliveryBoard) else dict(board)
    card = d.get("card") or {}
    brief_full = format_board(d)
    brief_lines = brief_full.splitlines()[:16]
    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "idea_id": IDEA_ID,
        "status": d.get("status"),
        "signal": d.get("signal"),
        "goal": (d.get("goal") or "")[:200],
        "lane": card.get("lane"),
        "specialist": card.get("specialist"),
        "phase": card.get("phase"),
        "n_targets": len((d.get("localization") or {}).get("targets") or []),
        "targets": list((d.get("localization") or {}).get("targets") or [])[:12],
        "n_localization_steps": (d.get("localization") or {}).get("n_steps"),
        "n_resolution_steps": (d.get("resolution") or {}).get("n_steps"),
        "lane_history": list(d.get("lane_history") or [])[:12],
        "roles": dict(d.get("roles") or {}),
        "roles_ok": bool(d.get("roles_ok")),
        "n_traces": len(d.get("traces") or []),
        "n_evidence": len(d.get("evidence") or []),
        "n_handoffs": len(d.get("handoffs") or []),
        "decision": {
            "ok": (d.get("decision") or {}).get("ok"),
            "reason": (d.get("decision") or {}).get("reason"),
            "confidence": (d.get("decision") or {}).get("confidence"),
        },
        "notes": (d.get("notes") or "")[:240],
        # brief is always a string; brief_lines is the truncated list form for UIs
        "brief": "\n".join(brief_lines),
        "brief_lines": brief_lines,
    }


def maybe_build_for_task(
    workdir: Optional[Path | str],
    task_id: str,
    goal: str,
    meta: Optional[dict[str, Any]],
    *,
    plan_result: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Build delivery board when SWE-Adept plan is requested / available.

    Trigger: same opt-in keys as :func:`swe_adept_plan.maybe_build_for_task`,
    plus explicit ``with_delivery_board`` / ``swe_board``.

    When *plan_result* is a successful SWE-Adept payload (from orchestrator),
    reuse it instead of re-localizing.
    """
    if not meta or not isinstance(meta, dict):
        return None
    explicit_board = bool(
        meta.get("with_delivery_board") or meta.get("swe_board") is True
    )
    swe_on = bool(
        meta.get("swe_adept")
        or meta.get("with_swe_plan")
        or meta.get("swe_plan") is True
        or isinstance(meta.get("swe_plan"), dict)
        or meta.get("swe_plan_text")
        or explicit_board
    )
    # Either alias can opt out (explicit False). Unset → hybrid default-on.
    if meta.get("with_delivery_board") is False or meta.get("swe_board") is False:
        return None
    # Default: board rides along when SWE plan is on (hybrid).
    if not swe_on and not explicit_board:
        return None
    if (
        meta.get("with_swe_plan") is False
        and meta.get("swe_adept") is False
        and not explicit_board
    ):
        return None

    try:
        plan: Optional[sap.SweAdeptPlan] = None
        if plan_result and plan_result.get("ok") and isinstance(
            plan_result.get("plan"), dict
        ):
            plan = sap.SweAdeptPlan.from_dict(plan_result["plan"])
            if not plan.task:
                plan.task = str(goal or "")
            # Re-validate purity / readiness for reused or injected plans
            plan = sap.mark_ready(
                plan, require_targets=bool(meta.get("swe_require_targets"))
            )
        elif plan_result and plan_result.get("ok") is False:
            return {
                "ok": False,
                "schema": SCHEMA,
                "paper": PAPER,
                "task_id": str(task_id or ""),
                "error": plan_result.get("error") or "swe plan failed",
                "status": "failed",
            }
        else:
            # Build board end-to-end
            require_targets = bool(meta.get("swe_require_targets"))
            max_targets = sap.clamp_swe_limit(meta.get("swe_max_targets"), 8)
            max_res = sap.clamp_swe_limit(meta.get("swe_max_resolution_steps"), 12)
            roots = meta.get("swe_search_roots") or list(sap.DEFAULT_SEARCH_ROOTS)
            if not isinstance(roots, (list, tuple)):
                roots = list(sap.DEFAULT_SEARCH_ROOTS)
            hints = (
                meta.get("swe_hints")
                if isinstance(meta.get("swe_hints"), list)
                else None
            )
            board = build_board_for_issue(
                str(goal or ""),
                workdir=workdir,
                card_id=str(task_id or "swe-card"),
                max_targets=max_targets,
                max_resolution_steps=max_res,
                search_roots=[str(r) for r in roots],
                hints=hints,
                require_targets=require_targets,
            )
            payload = board_payload_for_meta(board)
            return {
                "ok": True,
                "schema": SCHEMA,
                "paper": PAPER,
                "source_pattern": SOURCE_PATTERN,
                "task_id": str(task_id or ""),
                "status": board.status,
                "lane": board.card.lane,
                "n_targets": len(board.localization.get("targets") or []),
                "signal": board.signal,
                "board": payload,
                "brief": format_board(board),
            }

        if plan is None:
            return None
        board = plan_to_board(plan, card_id=str(task_id or "swe-card"))
        payload = board_payload_for_meta(board)
        return {
            "ok": True,
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "task_id": str(task_id or ""),
            "status": board.status,
            "lane": board.card.lane,
            "n_targets": len(board.localization.get("targets") or []),
            "signal": board.signal,
            "board": payload,
            "brief": format_board(board),
        }
    except (DeliveryBoardError, sap.SweAdeptPlanError) as e:
        return {
            "ok": False,
            "schema": SCHEMA,
            "paper": PAPER,
            "task_id": str(task_id or ""),
            "error": str(e),
            "status": "failed",
        }


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="python -m nexus.swe_delivery_board",
        description=(
            "SWE-Adept × routa delivery board "
            f"({PAPER} × {SOURCE_PATTERN})"
        ),
    )
    p.add_argument("issue", nargs="?", default="", help="Issue / task text")
    p.add_argument("--path", default=".", help="Repo root (default: cwd)")
    p.add_argument("--max-targets", type=int, default=8)
    p.add_argument("--json", action="store_true")
    p.add_argument("--brief", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    issue = str(args.issue or "").strip()
    if not issue:
        issue = "Implement structured localization and resolution on the delivery board"
    board = build_board_for_issue(
        issue,
        workdir=args.path,
        max_targets=int(args.max_targets),
    )
    if args.json:
        import json

        print(json.dumps(board.to_dict(), indent=2, default=str))
        return 0
    print(format_board(board))
    if not args.brief:
        print()
        print(
            f"lanes={board.lane_history}  "
            f"traces={len(board.traces)}  evidence={len(board.evidence)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SCHEMA",
    "PAPER",
    "SOURCE_PATTERN",
    "SOURCE_URL",
    "IDEA_ID",
    "LANES",
    "LANE_BLOCKED",
    "SPECIALISTS",
    "ROLES",
    "DeliveryBoardError",
    "BoardCard",
    "DeliveryBoard",
    "roles_distinct",
    "current_lane_for_plan",
    "plan_to_board",
    "build_board_for_issue",
    "format_board",
    "board_payload_for_meta",
    "maybe_build_for_task",
    "main",
]
