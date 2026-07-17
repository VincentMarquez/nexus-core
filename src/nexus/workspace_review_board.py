"""Workspace-first multi-agent delivery board with traces + stacked review gate.

Pattern from **phodal/routa** (shape only — not a vendored monorepo):

  Workspace is the top-level coordination boundary for goals, cards, sessions,
  traces, evidence, and review state (visible board, not buried chat).

  Delivery gate is a **stacked decision path**, not a single reviewer persona:

    1. Harness Monitor  — *what happened*
       traces, changed files, commands, git state, attribution
    2. Fitness          — *what should be true*
       hard gates, evidence requirements, scope/budget checks
    3. Gate Specialist  — *whether the card can move*
       acceptance criteria → Done / Dev / human escalation

  Lane happy path (routa kanban shape)::

      backlog → todo → dev → review → done
                              ↘ blocked (escape)

Schema: ``nexus.workspace_review_board/v1``

Offline-first. Does **not** vendor Routa (Next.js/Tauri/Rust) or depend on a
live LLM. Complements the SWE-Adept hybrid in :mod:`nexus.swe_delivery_board`
with a pure workspace + review-gate surface.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

SCHEMA = "nexus.workspace_review_board/v1"
SOURCE_PATTERN = "phodal/routa"
SOURCE_URL = "https://github.com/phodal/routa"
IDEA_ID = "phodal/routa"

# routa-shaped kanban lanes
LANES: tuple[str, ...] = ("backlog", "todo", "dev", "review", "done")
LANE_BLOCKED = "blocked"
ALL_LANES = frozenset(LANES) | {LANE_BLOCKED}

# Lane specialists (routa README shape, abbreviated)
SPECIALISTS: dict[str, str] = {
    "backlog": "Backlog Refiner",
    "todo": "Todo Orchestrator",
    "dev": "Dev Crafter",
    "review": "Review Guard",
    "done": "Done Reporter",
    "blocked": "Blocked Resolver",
}

# Anti-collusion roles: coordinator / crafter / gate must stay distinct
ROLES: dict[str, str] = {
    "coordinator": "routa:coordinator",
    "crafter": "routa:crafter",
    "gate": "routa:gate",
}

# Legal happy-path transitions (plus blocked escape / recovery)
_FORWARD: dict[str, frozenset[str]] = {
    "backlog": frozenset({"todo", "blocked"}),
    "todo": frozenset({"dev", "backlog", "blocked"}),
    "dev": frozenset({"review", "todo", "blocked"}),
    "review": frozenset({"done", "dev", "blocked"}),
    "done": frozenset(),  # terminal on happy path
    "blocked": frozenset({"backlog", "todo", "dev", "review"}),
}

# Evidence kinds the fitness layer expects before review→done
REQUIRED_REVIEW_EVIDENCE = frozenset(
    {
        "dev_evidence",
        "changed_files",
        "ac_check",
        "test_result",
    }
)

# Journal-projection claims — never satisfy REQUIRED_REVIEW_EVIDENCE
CLAIM_EVIDENCE_KINDS = frozenset(
    {
        "ac_claim",
        "dev_claim",
        "test_claim",
    }
)

# Anti-collusion triad keys (roles_distinct enforces these only)
ROLE_KEYS: tuple[str, ...] = ("coordinator", "crafter", "gate")

VERDICT_APPROVED = "APPROVED"
VERDICT_REJECTED = "REJECTED"
VERDICT_BLOCKED = "BLOCKED"
VERDICT_NEEDS_HUMAN = "NEEDS_HUMAN"

SIGNAL_CONTINUE = "continue"
SIGNAL_REPLAN = "replan"
SIGNAL_ESCALATE = "escalate"


class WorkspaceBoardError(ValueError):
    """Board / card / gate invalid for workspace delivery."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


def roles_distinct(roles: dict[str, str]) -> bool:
    """Anti-collusion: coordinator / crafter / gate must be distinct nonblank principals.

    Only the three required role keys are checked; extra map entries are ignored.
    """
    if not isinstance(roles, dict):
        return False
    vals: list[str] = []
    for key in ROLE_KEYS:
        raw = roles.get(key)
        if not isinstance(raw, str):
            return False
        v = raw.strip()
        if not v:
            return False
        vals.append(v)
    return len(set(vals)) == len(ROLE_KEYS)


def _normalize_lane(lane: str, *, default: str = "backlog") -> str:
    lane = str(lane or default).strip().lower() or default
    if lane not in ALL_LANES:
        return default
    return lane


@dataclass
class TraceEvent:
    """One append-only workspace trace (Harness Monitor surface)."""

    lane: str
    agent: str
    action: str
    detail: str = ""
    from_lane: Optional[str] = None
    ts: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "agent": self.agent,
            "action": self.action,
            "detail": self.detail,
            "from": self.from_lane,
            "ts": self.ts,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TraceEvent":
        return cls(
            lane=_normalize_lane(str(d.get("lane") or "backlog")),
            agent=str(d.get("agent") or ""),
            action=str(d.get("action") or ""),
            detail=str(d.get("detail") or "")[:240],
            from_lane=(
                str(d["from"])
                if d.get("from") is not None
                else (str(d["from_lane"]) if d.get("from_lane") is not None else None)
            ),
            ts=float(d.get("ts") or time.time()),
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
        )


@dataclass
class EvidenceItem:
    """One evidence claim attached to a card/lane (Fitness surface)."""

    kind: str
    ok: bool
    ref: str = ""
    detail: str = ""
    lane: str = "dev"
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ok": bool(self.ok),
            "ref": self.ref,
            "detail": self.detail,
            "lane": self.lane,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvidenceItem":
        return cls(
            kind=str(d.get("kind") or "note"),
            ok=bool(d.get("ok")),
            ref=str(d.get("ref") or "")[:200],
            detail=str(d.get("detail") or "")[:240],
            lane=_normalize_lane(str(d.get("lane") or "dev"), default="dev"),
            ts=float(d.get("ts") or time.time()),
        )


@dataclass
class WorkspaceCard:
    """One workspace-scoped delivery card (routa kanban card shape)."""

    id: str
    goal: str
    lane: str = "backlog"
    specialist: str = SPECIALISTS["backlog"]
    acceptance: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    traces: list[TraceEvent] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    review_findings: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "lane": self.lane,
            "specialist": self.specialist,
            "acceptance": list(self.acceptance),
            "changed_files": list(self.changed_files),
            "traces": [t.to_dict() for t in self.traces],
            "evidence": [e.to_dict() for e in self.evidence],
            "review_findings": dict(self.review_findings),
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkspaceCard":
        lane = _normalize_lane(str(d.get("lane") or "backlog"))
        traces = [
            TraceEvent.from_dict(t)
            for t in (d.get("traces") or [])
            if isinstance(t, dict)
        ]
        evidence = [
            EvidenceItem.from_dict(e)
            for e in (d.get("evidence") or [])
            if isinstance(e, dict)
        ]
        return cls(
            id=str(d.get("id") or "card"),
            goal=str(d.get("goal") or ""),
            lane=lane,
            specialist=str(d.get("specialist") or SPECIALISTS.get(lane, "")),
            acceptance=[str(a) for a in (d.get("acceptance") or []) if a],
            changed_files=[str(f) for f in (d.get("changed_files") or []) if f],
            traces=traces,
            evidence=evidence,
            review_findings=(
                dict(d.get("review_findings") or {})
                if isinstance(d.get("review_findings"), dict)
                else {}
            ),
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
        )


@dataclass
class WorkspaceBoard:
    """Workspace-first multi-agent delivery board (routa shape)."""

    workspace_id: str
    goal: str
    cards: list[WorkspaceCard] = field(default_factory=list)
    lanes: list[str] = field(default_factory=lambda: list(LANES))
    roles: dict[str, str] = field(default_factory=lambda: dict(ROLES))
    signal: str = SIGNAL_CONTINUE
    status: str = "ready"
    notes: str = ""
    ts: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "source_url": SOURCE_URL,
            "idea_id": IDEA_ID,
            "workspace_id": self.workspace_id,
            "goal": self.goal,
            "cards": [c.to_dict() for c in self.cards],
            "lanes": list(self.lanes),
            "roles": dict(self.roles),
            "roles_ok": roles_distinct(self.roles),
            "signal": self.signal,
            "status": self.status,
            "notes": self.notes,
            "ts": self.ts,
            "meta": dict(self.meta),
            "n_cards": len(self.cards),
            "lane_counts": lane_counts(self),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkspaceBoard":
        """Rehydrate a board from :meth:`to_dict` / envelope ``board_full``."""
        if not isinstance(d, dict):
            raise WorkspaceBoardError("board payload must be a dict")
        cards = [
            WorkspaceCard.from_dict(c)
            for c in (d.get("cards") or [])
            if isinstance(c, dict)
        ]
        roles_raw = d.get("roles")
        if isinstance(roles_raw, dict) and roles_raw:
            roles = {str(k): str(v) for k, v in roles_raw.items()}
        else:
            roles = dict(ROLES)
        lanes_raw = d.get("lanes")
        if isinstance(lanes_raw, (list, tuple)) and lanes_raw:
            lanes = [str(x) for x in lanes_raw if str(x).strip()]
        else:
            lanes = list(LANES)
        signal = str(d.get("signal") or SIGNAL_CONTINUE)
        if signal not in (SIGNAL_CONTINUE, SIGNAL_REPLAN, SIGNAL_ESCALATE):
            signal = SIGNAL_CONTINUE
        try:
            ts = float(d.get("ts") or time.time())
        except (TypeError, ValueError):
            ts = time.time()
        return cls(
            workspace_id=str(d.get("workspace_id") or "workspace").strip() or "workspace",
            goal=str(d.get("goal") or ""),
            cards=cards,
            lanes=lanes,
            roles=roles,
            signal=signal,
            status=str(d.get("status") or "ready"),
            notes=str(d.get("notes") or "")[:500],
            ts=ts,
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
        )


def lane_counts(board: WorkspaceBoard) -> dict[str, int]:
    """Count cards per lane (operator board summary)."""
    counts = {lane: 0 for lane in list(LANES) + [LANE_BLOCKED]}
    for c in board.cards:
        lane = _normalize_lane(c.lane)
        counts[lane] = counts.get(lane, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Construction helpers
# ---------------------------------------------------------------------------


def create_board(
    workspace_id: str,
    goal: str,
    *,
    roles: Optional[dict[str, str]] = None,
    card_id: str = "card-1",
    acceptance: Optional[Sequence[str]] = None,
) -> WorkspaceBoard:
    """Create a workspace board with one backlog card (routa entry shape)."""
    ws = str(workspace_id or "").strip() or "workspace"
    g = str(goal or "").strip()
    if not g:
        raise WorkspaceBoardError("goal required for workspace board")
    card = WorkspaceCard(
        id=str(card_id or "card-1").strip() or "card-1",
        goal=g,
        lane="backlog",
        specialist=SPECIALISTS["backlog"],
        acceptance=[str(a) for a in (acceptance or []) if str(a).strip()],
    )
    card.traces.append(
        TraceEvent(
            lane="backlog",
            agent=SPECIALISTS["backlog"],
            action="accept_goal",
            detail=g[:120],
            from_lane=None,
        )
    )
    role_map = dict(roles) if roles else dict(ROLES)
    return WorkspaceBoard(
        workspace_id=ws,
        goal=g,
        cards=[card],
        roles=role_map,
        signal=SIGNAL_CONTINUE if roles_distinct(role_map) else SIGNAL_REPLAN,
        status="ready",
        notes=f"workspace={ws} card={card.id} lane=backlog",
        meta={"idea_id": IDEA_ID, "source_pattern": SOURCE_PATTERN},
    )


def get_card(board: WorkspaceBoard, card_id: str) -> WorkspaceCard:
    cid = str(card_id or "").strip()
    for c in board.cards:
        if c.id == cid:
            return c
    raise WorkspaceBoardError(f"card not found: {cid!r}")


def append_trace(
    board: WorkspaceBoard,
    card_id: str,
    *,
    action: str,
    detail: str = "",
    lane: Optional[str] = None,
    agent: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
) -> TraceEvent:
    """Append a Harness-Monitor style trace on a card."""
    card = get_card(board, card_id)
    use_lane = _normalize_lane(lane or card.lane)
    ev = TraceEvent(
        lane=use_lane,
        agent=str(agent or SPECIALISTS.get(use_lane, use_lane)),
        action=str(action or "note").strip() or "note",
        detail=str(detail or "")[:240],
        from_lane=card.lane,
        meta=dict(meta or {}),
    )
    card.traces.append(ev)
    return ev


def append_evidence(
    board: WorkspaceBoard,
    card_id: str,
    *,
    kind: str,
    ok: bool,
    ref: str = "",
    detail: str = "",
    lane: Optional[str] = None,
) -> EvidenceItem:
    """Append a Fitness-layer evidence item on a card."""
    card = get_card(board, card_id)
    item = EvidenceItem(
        kind=str(kind or "note").strip() or "note",
        ok=bool(ok),
        ref=str(ref or "")[:200],
        detail=str(detail or "")[:240],
        lane=_normalize_lane(lane or card.lane, default=card.lane),
    )
    card.evidence.append(item)
    return item


def set_changed_files(
    board: WorkspaceBoard, card_id: str, files: Sequence[str]
) -> list[str]:
    """Record changed files (Harness + Fitness entry surface)."""
    card = get_card(board, card_id)
    cleaned = [str(f).strip() for f in files if str(f).strip()]
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for f in cleaned:
        if f not in seen:
            seen.add(f)
            out.append(f)
    card.changed_files = out
    if out:
        append_evidence(
            board,
            card_id,
            kind="changed_files",
            ok=True,
            ref=f"files:{len(out)}",
            detail=",".join(out[:8]),
            lane=card.lane,
        )
    return out


# ---------------------------------------------------------------------------
# Stacked review gate (Harness → Fitness → Gate)
# ---------------------------------------------------------------------------


def _evidence_by_kind(card: WorkspaceCard) -> dict[str, list[EvidenceItem]]:
    by: dict[str, list[EvidenceItem]] = {}
    for e in card.evidence:
        by.setdefault(e.kind, []).append(e)
    return by


def _effective_evidence(card: WorkspaceCard) -> list[EvidenceItem]:
    """Latest-wins per (kind, ref) so reject→fix→re-check can converge."""
    latest: dict[tuple[str, str], EvidenceItem] = {}
    for e in card.evidence:
        latest[(e.kind, e.ref or "")] = e
    return list(latest.values())


def _is_satisfying_evidence(item: EvidenceItem) -> bool:
    """True when item may satisfy a required fitness kind (not a journal claim)."""
    if item.kind in CLAIM_EVIDENCE_KINDS:
        return False
    ref = item.ref or ""
    if ref.startswith("journal:"):
        return False
    return True


def _ac_ref_matches(ref: str, index: int, key: str) -> bool:
    """Exact AC id match (``ac:N`` or ``ACn``); no prefix hazard at ≥10 ACs."""
    r = (ref or "").strip()
    if not r:
        return False
    rl = r.lower()
    if rl == key.lower():
        return True
    if rl == f"ac:{index + 1}":
        return True
    if rl.startswith("ac:"):
        try:
            return int(rl.split(":", 1)[1].strip()) == index + 1
        except (TypeError, ValueError):
            return False
    return False


def evaluate_harness(
    card: WorkspaceCard,
    *,
    git_clean: Optional[bool] = None,
    committed: Optional[bool] = None,
) -> dict[str, Any]:
    """Layer 1 — Harness Monitor: *what happened*."""
    issues: list[str] = []
    n_traces = len(card.traces)
    n_files = len(card.changed_files)
    if n_traces < 1:
        issues.append("no traces — harness cannot attribute work")
    if card.lane in ("review", "done") and n_files < 1:
        # Review requires a file list (routa Review Guard entry gate)
        issues.append("no changed_files listed for review")
    if git_clean is False:
        issues.append("git working tree dirty")
    if committed is False:
        issues.append("implementation not committed")
    # Dev must have left some action beyond accept_goal
    dev_actions = [
        t
        for t in card.traces
        if t.lane == "dev" or t.action.startswith("resolve.") or t.action.startswith("dev.")
    ]
    if card.lane in ("review", "done") and not dev_actions and n_files < 1:
        issues.append("no dev traces/actions observed")
    return {
        "layer": "harness",
        "ok": not issues,
        "n_traces": n_traces,
        "n_changed_files": n_files,
        "git_clean": git_clean,
        "committed": committed,
        "issues": issues,
    }


def evaluate_fitness(
    card: WorkspaceCard,
    *,
    require_kinds: Optional[Sequence[str]] = None,
    max_changed_files: Optional[int] = None,
) -> dict[str, Any]:
    """Layer 2 — Fitness: *what should be true* (hard gates + evidence).

    Uses latest-wins per ``(kind, ref)`` so a failed check that is later
    superseded by a passing one does not permanently wedge the card.
    Journal ``*_claim`` kinds and ``journal:`` refs never satisfy required kinds.
    """
    issues: list[str] = []
    effective = _effective_evidence(card)
    kinds: dict[str, list[EvidenceItem]] = {}
    for e in effective:
        kinds.setdefault(e.kind, []).append(e)
    required = list(require_kinds) if require_kinds is not None else list(
        REQUIRED_REVIEW_EVIDENCE
    )
    # Only enforce full evidence set when moving out of review (or already past)
    enforce = card.lane in ("review", "done") or bool(require_kinds)
    present_ok: dict[str, bool] = {}
    if enforce:
        for kind in required:
            items = kinds.get(kind) or []
            ok_items = [i for i in items if i.ok and _is_satisfying_evidence(i)]
            present_ok[kind] = bool(ok_items)
            if not ok_items:
                issues.append(f"missing or failed evidence kind={kind!r}")
    # Effective failing evidence is a fitness miss (history may still hold old fails)
    failed = [e for e in effective if not e.ok]
    if failed:
        issues.append(f"{len(failed)} evidence item(s) marked ok=false")
    if max_changed_files is not None and len(card.changed_files) > int(max_changed_files):
        issues.append(
            f"changed_files budget exceeded "
            f"({len(card.changed_files)} > {int(max_changed_files)})"
        )
    # Acceptance criteria must exist before Done
    if card.lane in ("review", "done") and not card.acceptance:
        issues.append("no acceptance criteria on card")
    return {
        "layer": "fitness",
        "ok": not issues,
        "required_kinds": required if enforce else [],
        "present_ok": present_ok,
        "n_evidence": len(card.evidence),
        "n_failed_evidence": len(failed),
        "issues": issues,
    }


def evaluate_gate(
    card: WorkspaceCard,
    *,
    harness: dict[str, Any],
    fitness: dict[str, Any],
    roles: Optional[dict[str, str]] = None,
    human_required: bool = False,
) -> dict[str, Any]:
    """Layer 3 — Gate Specialist: *can the card move*."""
    issues: list[str] = []
    if human_required:
        return {
            "layer": "gate",
            "ok": False,
            "verdict": VERDICT_NEEDS_HUMAN,
            "target_lane": "review",
            "issues": ["human escalation requested"],
            "ac_status": {},
        }

    role_map = roles or dict(ROLES)
    if not roles_distinct(role_map):
        issues.append("role collision (coordinator/crafter/gate not distinct)")

    # Map acceptance criteria → ac_check only (claims never verify)
    ac_status: dict[str, str] = {}
    effective = _effective_evidence(card)
    ac_evidence = [
        e
        for e in effective
        if e.kind == "ac_check" and _is_satisfying_evidence(e)
    ]
    for i, ac in enumerate(card.acceptance):
        key = f"AC{i + 1}"
        matched = [e for e in ac_evidence if _ac_ref_matches(e.ref or "", i, key)]
        # Detail fallback only when no exact-ref evidence exists for this AC
        # and the candidate is not already bound to another ac:N ref.
        if not matched:
            needle = (ac[:40] or "").lower()
            if needle:
                matched = [
                    e
                    for e in ac_evidence
                    if needle in (e.detail or "").lower()
                    and not (e.ref or "").lower().startswith("ac:")
                ]
        if matched and all(e.ok for e in matched):
            ac_status[key] = "verified"
        elif matched:
            ac_status[key] = "failed"
            issues.append(f"{key} failed verification")
        else:
            # If no per-AC evidence, only fail when reviewing toward done
            if card.lane in ("review", "done") and card.acceptance:
                ac_status[key] = "missing"
                issues.append(f"{key} not verified")
            else:
                ac_status[key] = "pending"

    if not harness.get("ok"):
        issues.extend(f"harness: {x}" for x in (harness.get("issues") or []))
    if not fitness.get("ok"):
        issues.extend(f"fitness: {x}" for x in (fitness.get("issues") or []))

    if issues:
        # Dirty git / missing evidence / role collision → reject to dev when
        # leaving review (routa replan path). VERDICT_BLOCKED reserved for
        # explicit blocked-lane recovery flows.
        verdict = VERDICT_REJECTED
        target = "dev" if card.lane in ("review", "done") else card.lane
        return {
            "layer": "gate",
            "ok": False,
            "verdict": verdict,
            "target_lane": target,
            "issues": issues,
            "ac_status": ac_status,
        }

    return {
        "layer": "gate",
        "ok": True,
        "verdict": VERDICT_APPROVED,
        "target_lane": "done" if card.lane == "review" else card.lane,
        "issues": [],
        "ac_status": ac_status,
    }


def evaluate_review_gate(
    card: WorkspaceCard,
    *,
    roles: Optional[dict[str, str]] = None,
    git_clean: Optional[bool] = None,
    committed: Optional[bool] = None,
    require_kinds: Optional[Sequence[str]] = None,
    max_changed_files: Optional[int] = None,
    human_required: bool = False,
) -> dict[str, Any]:
    """Run the full stacked review gate (Harness → Fitness → Gate)."""
    harness = evaluate_harness(card, git_clean=git_clean, committed=committed)
    fitness = evaluate_fitness(
        card, require_kinds=require_kinds, max_changed_files=max_changed_files
    )
    gate = evaluate_gate(
        card,
        harness=harness,
        fitness=fitness,
        roles=roles,
        human_required=human_required,
    )
    ok = bool(gate.get("ok"))
    verdict = str(gate.get("verdict") or VERDICT_REJECTED)
    if verdict == VERDICT_NEEDS_HUMAN:
        signal = SIGNAL_ESCALATE
    elif ok:
        signal = SIGNAL_CONTINUE
    else:
        signal = SIGNAL_REPLAN

    reasons = list(gate.get("issues") or [])
    return {
        "schema": f"{SCHEMA}#review_gate",
        "source_pattern": SOURCE_PATTERN,
        "ok": ok,
        "verdict": verdict,
        "target_lane": gate.get("target_lane"),
        "signal": signal,
        "layers": {
            "harness": harness,
            "fitness": fitness,
            "gate": gate,
        },
        "reasons": reasons,
        "ac_status": dict(gate.get("ac_status") or {}),
        "evidence_refs": [
            e.ref or e.kind for e in card.evidence if e.ok
        ][:12],
        "card_id": card.id,
        "lane": card.lane,
    }


# ---------------------------------------------------------------------------
# Moves (entry-gated)
# ---------------------------------------------------------------------------


def can_transition(from_lane: str, to_lane: str) -> bool:
    """Whether *to_lane* is a legal transition from *from_lane*."""
    src = _normalize_lane(from_lane)
    dst = _normalize_lane(to_lane, default=src)
    if src == dst:
        return True
    return dst in _FORWARD.get(src, frozenset())


def try_move_card(
    board: WorkspaceBoard,
    card_id: str,
    target_lane: str,
    *,
    git_clean: Optional[bool] = None,
    committed: Optional[bool] = None,
    max_changed_files: Optional[int] = None,
    human_required: bool = False,
    force: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    """Move a card only when transition + review entry gates allow.

    Review → Done always runs the stacked gate unless *force* is True.
    Dev → Review requires at least traces + (changed_files or dev evidence).
    """
    card = get_card(board, card_id)
    # Fail closed on unknown lanes (do not map typos → current lane success)
    raw_target = str(target_lane or "").strip().lower()
    if not raw_target or raw_target not in ALL_LANES:
        return {
            "ok": False,
            "moved": False,
            "lane": card.lane,
            "reason": f"unknown lane {target_lane!r}",
            "gate": None,
        }
    target = raw_target
    if target == card.lane:
        return {
            "ok": True,
            "moved": False,
            "lane": card.lane,
            "reason": "already_in_lane",
            "gate": None,
        }
    if not can_transition(card.lane, target) and not force:
        return {
            "ok": False,
            "moved": False,
            "lane": card.lane,
            "reason": f"illegal transition {card.lane!r} → {target!r}",
            "gate": None,
        }

    gate_result: Optional[dict[str, Any]] = None

    # Entry gates for review-bound / done-bound moves
    if target == "review" and not force:
        if not card.traces:
            return {
                "ok": False,
                "moved": False,
                "lane": card.lane,
                "reason": "entry_gate: no traces before review",
                "gate": None,
            }
        has_dev_ev = any(
            e.kind in ("dev_evidence", "changed_files")
            and e.ok
            and _is_satisfying_evidence(e)
            for e in card.evidence
        )
        if not has_dev_ev and not card.changed_files:
            return {
                "ok": False,
                "moved": False,
                "lane": card.lane,
                "reason": "entry_gate: need dev_evidence or changed_files before review",
                "gate": None,
            }

    if target == "done" and not force:
        # Stacked review gate is mandatory for Done.
        # git_clean / committed stay None when unobserved (no false attestation).
        gate_result = evaluate_review_gate(
            card,
            roles=board.roles,
            git_clean=git_clean,
            committed=committed,
            max_changed_files=max_changed_files,
            human_required=human_required,
        )
        if not gate_result.get("ok"):
            # Auto-route reject target when gate says so
            reject_to = str(gate_result.get("target_lane") or "dev")
            if reject_to != card.lane and can_transition(card.lane, reject_to):
                prev = card.lane
                card.lane = reject_to
                card.specialist = SPECIALISTS.get(reject_to, reject_to)
                card.review_findings = {
                    "verdict": gate_result.get("verdict"),
                    "reasons": list(gate_result.get("reasons") or []),
                    "ac_status": dict(gate_result.get("ac_status") or {}),
                }
                card.traces.append(
                    TraceEvent(
                        lane=reject_to,
                        agent=SPECIALISTS.get("review", "Review Guard"),
                        action="gate_reject",
                        detail="; ".join(gate_result.get("reasons") or [])[:200],
                        from_lane=prev,
                    )
                )
                board.signal = str(gate_result.get("signal") or SIGNAL_REPLAN)
                return {
                    "ok": False,
                    "moved": True,
                    "lane": card.lane,
                    "reason": "gate_rejected",
                    "gate": gate_result,
                }
            return {
                "ok": False,
                "moved": False,
                "lane": card.lane,
                "reason": "gate_rejected",
                "gate": gate_result,
            }

    prev = card.lane
    card.lane = target
    card.specialist = SPECIALISTS.get(target, target)
    detail = (reason or f"move {prev}→{target}")[:200]
    card.traces.append(
        TraceEvent(
            lane=target,
            agent=SPECIALISTS.get(target, target),
            action="move_card",
            detail=detail,
            from_lane=prev,
        )
    )
    if gate_result and gate_result.get("ok"):
        card.review_findings = {
            "verdict": VERDICT_APPROVED,
            "reasons": [],
            "ac_status": dict(gate_result.get("ac_status") or {}),
        }
        board.signal = SIGNAL_CONTINUE
        # Done evidence
        append_evidence(
            board,
            card_id,
            kind="completion_summary",
            ok=True,
            ref=f"done:{card_id}",
            detail=detail,
            lane="done",
        )
    board.notes = f"workspace={board.workspace_id} card={card.id} lane={card.lane}"
    return {
        "ok": True,
        "moved": True,
        "lane": card.lane,
        "reason": "moved",
        "gate": gate_result,
        "from": prev,
        "to": target,
    }


# ---------------------------------------------------------------------------
# Journal-driven lane advance (engine event → board)
# ---------------------------------------------------------------------------


# Map engine journal event names → board actions
_JOURNAL_STEP_DONE = "step_complete"
_JOURNAL_HANDOFF = "handoff"
_JOURNAL_VETO = "veto"
_JOURNAL_HUMAN = "human_decision"
_JOURNAL_FAIL = "failed"
_JOURNAL_BUDGET = "budget"


def advance_from_journal(
    board: WorkspaceBoard,
    events: Sequence[dict[str, Any]],
    *,
    card_id: Optional[str] = None,
    git_clean: Optional[bool] = None,
    committed: Optional[bool] = None,
) -> dict[str, Any]:
    """Project engine journal events onto the workspace board.

    Offline / pure: does not mutate the engine. Appends traces and attempts
    gated lane moves when journal implies progress (routa traces-and-review).

    Event heuristics (shape only)::

      handoff → to_agent contains gate/review  → try move to review
      handoff → to_agent contains craft/dev    → try move to dev
      step_complete (ok/score high) on review → try move to done
      veto / human reject                     → move toward dev/blocked
      human approve                           → try move to done
      budget/fail hard stop                   → blocked
    """
    if not board.cards:
        raise WorkspaceBoardError("board has no cards to advance")
    cid = str(card_id or board.cards[0].id)
    card = get_card(board, cid)
    applied: list[dict[str, Any]] = []
    moves: list[dict[str, Any]] = []

    for raw in events or []:
        if not isinstance(raw, dict):
            continue
        ev = str(raw.get("event") or raw.get("type") or "").strip().lower()
        if not ev:
            continue
        agent = str(raw.get("agent") or raw.get("to_agent") or raw.get("from_agent") or "")
        detail = str(raw.get("detail") or raw.get("why") or raw.get("msg") or "")[:200]
        append_trace(
            board,
            cid,
            action=f"journal:{ev}",
            detail=detail or agent,
            lane=card.lane,
            agent=agent or SPECIALISTS.get(card.lane, card.lane),
            meta={"event": ev, "raw_keys": sorted(str(k) for k in raw.keys())[:12]},
        )
        applied.append({"event": ev, "agent": agent, "lane": card.lane})

        move: Optional[dict[str, Any]] = None
        step_moves: list[dict[str, Any]] = []

        if ev == _JOURNAL_HANDOFF:
            to_agent = str(raw.get("to_agent") or agent).lower()
            if any(k in to_agent for k in ("gate", "review", "verify", "judge")):
                if card.lane in ("dev", "todo"):
                    # Journal claim only — does not satisfy fitness/entry as real evidence
                    if not any(
                        e.kind == "dev_evidence" and _is_satisfying_evidence(e)
                        for e in card.evidence
                    ):
                        append_evidence(
                            board,
                            cid,
                            kind="dev_claim",
                            ok=True,
                            ref="journal:handoff_to_gate",
                            detail=detail or "handoff to gate",
                            lane="dev",
                        )
                    move = try_move_card(board, cid, "review", force=False)
            elif any(k in to_agent for k in ("craft", "dev", "implement", "resolver")):
                # Walk backlog → todo → dev; accumulate every intermediate move
                if card.lane == "backlog":
                    m_todo = try_move_card(board, cid, "todo")
                    if m_todo is not None:
                        step_moves.append(m_todo)
                    card = get_card(board, cid)
                if card.lane == "todo":
                    move = try_move_card(board, cid, "dev")

        elif ev == _JOURNAL_STEP_DONE:
            score = raw.get("score")
            ok_flag = raw.get("ok")
            score_ok = False
            if score is not None:
                try:
                    score_ok = float(score) >= 0.7
                except (TypeError, ValueError):
                    score_ok = False
            good = (ok_flag is True) or score_ok
            if good and card.lane == "review":
                # Claims only — gate stays meaningful (no rubber-stamp approval)
                _seed_ac_claims_from_acceptance(board, cid)
                if not any(
                    e.kind == "test_result" and _is_satisfying_evidence(e)
                    for e in card.evidence
                ):
                    append_evidence(
                        board,
                        cid,
                        kind="test_claim",
                        ok=True,
                        ref="journal:step_complete",
                        detail=detail or "step_complete ok",
                        lane="review",
                    )
                move = try_move_card(
                    board,
                    cid,
                    "done",
                    git_clean=git_clean,
                    committed=committed,
                )
            elif good and card.lane == "dev":
                if not any(
                    e.kind == "dev_evidence" and _is_satisfying_evidence(e)
                    for e in card.evidence
                ):
                    append_evidence(
                        board,
                        cid,
                        kind="dev_claim",
                        ok=True,
                        ref="journal:step_complete",
                        detail=detail or "dev step ok",
                        lane="dev",
                    )
                if card.changed_files or any(
                    e.kind == "changed_files" and _is_satisfying_evidence(e)
                    for e in card.evidence
                ):
                    move = try_move_card(board, cid, "review")

        elif ev in (_JOURNAL_VETO, "review_veto"):
            if card.lane in ("review", "done", "dev"):
                move = try_move_card(board, cid, "dev", force=True, reason="veto")
            board.signal = SIGNAL_REPLAN

        elif ev == _JOURNAL_HUMAN:
            approved = bool(
                raw.get("approve")
                or raw.get("approved")
                or str(raw.get("decision") or "").lower() in ("approve", "approved")
            )
            if approved:
                # Human is an explicit privileged override — do not mint ac_check.
                # Seed claims for audit, then force-move to done with reason.
                _seed_ac_claims_from_acceptance(board, cid)
                if not any(e.kind == "test_claim" for e in card.evidence):
                    append_evidence(
                        board,
                        cid,
                        kind="test_claim",
                        ok=True,
                        ref="journal:human_approve",
                        detail="human approved",
                        lane="review",
                    )
                if card.lane != "review":
                    m_rev = try_move_card(
                        board, cid, "review", force=True, reason="human_path"
                    )
                    if m_rev is not None:
                        step_moves.append(m_rev)
                    card = get_card(board, cid)
                move = try_move_card(
                    board,
                    cid,
                    "done",
                    git_clean=git_clean,
                    committed=committed,
                    force=True,
                    reason="human_approve",
                )
                card = get_card(board, cid)
                card.review_findings = {
                    "verdict": VERDICT_APPROVED,
                    "reasons": ["human_approve override"],
                    "ac_status": dict(card.review_findings.get("ac_status") or {}),
                    "override": "human_approve",
                }
                board.signal = SIGNAL_CONTINUE
            else:
                move = try_move_card(
                    board, cid, "dev", force=True, reason="human_reject"
                )
                board.signal = SIGNAL_REPLAN

        elif ev in (_JOURNAL_FAIL, _JOURNAL_BUDGET, "norm"):
            kind = str(raw.get("kind") or "").lower()
            hard_stop = ev in (_JOURNAL_FAIL, _JOURNAL_BUDGET) or (
                ev == "norm" and kind in ("wall", "tokens", "steps")
            )
            if hard_stop:
                if card.lane != LANE_BLOCKED:
                    move = try_move_card(
                        board,
                        cid,
                        LANE_BLOCKED,
                        force=True,
                        reason=f"journal:{ev}",
                    )
                board.signal = SIGNAL_REPLAN

        for m in step_moves:
            moves.append(m)
        if move is not None:
            moves.append(move)
        if step_moves or move is not None:
            # refresh card ref after move(s)
            card = get_card(board, cid)

    return {
        "ok": True,
        "card_id": cid,
        "lane": card.lane,
        "n_events": len(applied),
        "n_moves": len(moves),
        "applied": applied,
        "moves": moves,
        "signal": board.signal,
        "lane_counts": lane_counts(board),
    }


def _seed_ac_claims_from_acceptance(board: WorkspaceBoard, card_id: str) -> None:
    """Seed non-satisfying AC *claims* from acceptance text (journal path).

    Claims never verify the gate — only real ``ac_check`` evidence does.
    """
    card = get_card(board, card_id)
    existing = {
        (e.ref or "").lower()
        for e in card.evidence
        if e.kind in ("ac_check", "ac_claim")
    }
    for i, ac in enumerate(card.acceptance):
        ref = f"ac:{i + 1}"
        key = f"ac{i + 1}"
        if ref in existing or key in existing:
            continue
        append_evidence(
            board,
            card_id,
            kind="ac_claim",
            ok=True,
            ref=f"journal:{ref}",
            detail=str(ac)[:120],
            lane="review",
        )


# Back-compat alias (old name; still non-satisfying)
_seed_ac_from_acceptance = _seed_ac_claims_from_acceptance


# ---------------------------------------------------------------------------
# Formatting / payload
# ---------------------------------------------------------------------------


def format_board(board: WorkspaceBoard | dict[str, Any]) -> str:
    """Human-readable workspace delivery board (routa-lite operator surface)."""
    d = board.to_dict() if isinstance(board, WorkspaceBoard) else dict(board)
    roles = d.get("roles") or {}
    lines = [
        "=== NEXUS workspace review board (phodal/routa) ===",
        f"workspace: {d.get('workspace_id')}  status: {d.get('status')}  "
        f"signal: {d.get('signal')}",
        f"goal: {d.get('goal')}",
        f"roles: coordinator={roles.get('coordinator')}  "
        f"crafter={roles.get('crafter')}  gate={roles.get('gate')}  "
        f"[{'OK' if d.get('roles_ok') else 'COLLISION'}]",
        f"lane_counts: {d.get('lane_counts')}",
        "",
    ]
    for c in d.get("cards") or []:
        lines.append(
            f"card {c.get('id')}: lane={c.get('lane')}  "
            f"specialist={c.get('specialist')}"
        )
        lines.append(f"  goal: {c.get('goal')}")
        if c.get("acceptance"):
            lines.append("  acceptance:")
            for a in c["acceptance"][:6]:
                lines.append(f"    - {a}")
        if c.get("changed_files"):
            lines.append(
                "  changed_files: " + ", ".join(c["changed_files"][:8])
            )
        traces = c.get("traces") or []
        if traces:
            lines.append("  traces (tail):")
            for tr in traces[-6:]:
                lines.append(
                    f"    [{tr.get('lane')}] {tr.get('action')} "
                    f"agent={tr.get('agent')}"
                )
        findings = c.get("review_findings") or {}
        if findings:
            lines.append(
                f"  review: verdict={findings.get('verdict')} "
                f"ac={findings.get('ac_status')}"
            )
        lines.append("")
    if d.get("notes"):
        lines.append(f"notes: {d.get('notes')}")
    return "\n".join(lines).rstrip() + "\n"


def board_payload_for_meta(board: WorkspaceBoard | dict[str, Any]) -> dict[str, Any]:
    """Lean JSON-safe payload for envelope / ops meta."""
    d = board.to_dict() if isinstance(board, WorkspaceBoard) else dict(board)
    cards = d.get("cards") or []
    primary = cards[0] if cards else {}
    brief = format_board(d)
    brief_lines = brief.splitlines()[:16]
    return {
        "schema": SCHEMA,
        "source_pattern": SOURCE_PATTERN,
        "idea_id": IDEA_ID,
        "workspace_id": d.get("workspace_id"),
        "status": d.get("status"),
        "signal": d.get("signal"),
        "goal": (d.get("goal") or "")[:200],
        "n_cards": len(cards),
        "lane_counts": d.get("lane_counts") or {},
        "primary_lane": primary.get("lane"),
        "primary_card": primary.get("id"),
        "roles_ok": bool(d.get("roles_ok")),
        "n_traces": sum(len(c.get("traces") or []) for c in cards),
        "n_evidence": sum(len(c.get("evidence") or []) for c in cards),
        "brief": "\n".join(brief_lines),
        "brief_lines": brief_lines,
    }


def maybe_build_for_task(
    workdir: Any,
    task_id: str,
    goal: str,
    meta: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Opt-in builder for orchestrator / MCP (``with_workspace_board``).

    *workdir* is accepted for API parity with other maybe_build helpers; the
    pure board is workspace-id scoped and does not scan the filesystem.
    """
    del workdir  # pure board — no FS scan
    if not meta or not isinstance(meta, dict):
        return None
    # Any truthy flag opts in (True wins over a False sibling alias)
    _board_flags = ("with_workspace_board", "workspace_board", "routa_board")
    if not any(bool(meta.get(k)) for k in _board_flags):
        return None

    ws = str(
        meta.get("workspace_id")
        or meta.get("workspace")
        or task_id
        or "workspace"
    ).strip()
    acceptance = meta.get("acceptance") if isinstance(meta.get("acceptance"), list) else None
    try:
        board = create_board(
            ws,
            str(goal or ""),
            card_id=str(task_id or "card-1"),
            acceptance=acceptance,
            roles=meta.get("roles") if isinstance(meta.get("roles"), dict) else None,
        )
        # Optional seed files / start lane
        files = meta.get("changed_files")
        if isinstance(files, (list, tuple)) and files:
            set_changed_files(board, board.cards[0].id, [str(f) for f in files])
        start_lane = meta.get("start_lane") or meta.get("lane")
        if start_lane and str(start_lane) != "backlog":
            # walk forward with force for seed placement only;
            # cap at review — done always requires the stacked gate
            order = list(LANES)
            target = _normalize_lane(str(start_lane))
            if target == LANE_BLOCKED:
                try_move_card(
                    board,
                    board.cards[0].id,
                    LANE_BLOCKED,
                    force=True,
                    reason="seed_start_lane",
                )
            elif target in order:
                idx = min(order.index(target), order.index("review"))
                for lane in order[1 : idx + 1]:
                    try_move_card(
                        board,
                        board.cards[0].id,
                        lane,
                        force=True,
                        reason="seed_start_lane",
                    )
                if target == "done":
                    card0 = board.cards[0]
                    card0.meta = dict(card0.meta or {})
                    card0.meta["seed_capped"] = "review"
                    card0.review_findings = {
                        "verdict": "SEEDED",
                        "reasons": ["start_lane=done capped at review; gate required"],
                    }
        payload = board_payload_for_meta(board)
        return {
            "ok": True,
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "idea_id": IDEA_ID,
            "task_id": str(task_id or ""),
            "workspace_id": board.workspace_id,
            "status": board.status,
            "signal": board.signal,
            "lane": board.cards[0].lane if board.cards else None,
            "board": payload,
            "board_full": board.to_dict(),
            "brief": format_board(board),
        }
    except WorkspaceBoardError as e:
        return {
            "ok": False,
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "task_id": str(task_id or ""),
            "error": str(e),
            "status": "failed",
        }


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(
        prog="python -m nexus.workspace_review_board",
        description=(
            "Workspace-first routa-shaped delivery board "
            f"({SOURCE_PATTERN} traces + stacked review gate)"
        ),
    )
    p.add_argument("goal", nargs="?", default="", help="Workspace goal / card text")
    p.add_argument("--workspace", default="ws-demo", help="Workspace id")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--demo-gate",
        action="store_true",
        help="Seed dev evidence and print stacked gate result",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    goal = str(args.goal or "").strip() or (
        "Ship workspace-first traces and stacked review gate"
    )
    board = create_board(
        str(args.workspace),
        goal,
        acceptance=[
            "traces visible on board",
            "review gate stacks harness+fitness+gate",
            "illegal moves rejected",
        ],
    )
    card_id = board.cards[0].id

    if args.demo_gate:
        try_move_card(board, card_id, "todo", force=True)
        try_move_card(board, card_id, "dev", force=True)
        set_changed_files(board, card_id, ["src/nexus/workspace_review_board.py"])
        append_evidence(
            board,
            card_id,
            kind="dev_evidence",
            ok=True,
            ref="demo:impl",
            detail="implemented workspace review board",
            lane="dev",
        )
        try_move_card(board, card_id, "review")
        for i, ac in enumerate(board.cards[0].acceptance):
            append_evidence(
                board,
                card_id,
                kind="ac_check",
                ok=True,
                ref=f"ac:{i + 1}",
                detail=ac,
                lane="review",
            )
        append_evidence(
            board,
            card_id,
            kind="test_result",
            ok=True,
            ref="pytest:workspace_review_board",
            detail="tests green",
            lane="review",
        )
        gate = evaluate_review_gate(
            board.cards[0], roles=board.roles, git_clean=True, committed=True
        )
        move = try_move_card(
            board, card_id, "done", git_clean=True, committed=True
        )
        if args.json:
            print(
                json.dumps(
                    {"board": board.to_dict(), "gate": gate, "move": move},
                    indent=2,
                    default=str,
                )
            )
            return 0
        print(format_board(board))
        print(f"gate: verdict={gate.get('verdict')} ok={gate.get('ok')}")
        print(f"move: {move}")
        return 0

    if args.json:
        print(json.dumps(board.to_dict(), indent=2, default=str))
        return 0
    print(format_board(board))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SCHEMA",
    "SOURCE_PATTERN",
    "SOURCE_URL",
    "IDEA_ID",
    "LANES",
    "LANE_BLOCKED",
    "ALL_LANES",
    "SPECIALISTS",
    "ROLES",
    "ROLE_KEYS",
    "REQUIRED_REVIEW_EVIDENCE",
    "CLAIM_EVIDENCE_KINDS",
    "VERDICT_APPROVED",
    "VERDICT_REJECTED",
    "VERDICT_BLOCKED",
    "VERDICT_NEEDS_HUMAN",
    "SIGNAL_CONTINUE",
    "SIGNAL_REPLAN",
    "SIGNAL_ESCALATE",
    "WorkspaceBoardError",
    "TraceEvent",
    "EvidenceItem",
    "WorkspaceCard",
    "WorkspaceBoard",
    "roles_distinct",
    "lane_counts",
    "create_board",
    "get_card",
    "append_trace",
    "append_evidence",
    "set_changed_files",
    "evaluate_harness",
    "evaluate_fitness",
    "evaluate_gate",
    "evaluate_review_gate",
    "can_transition",
    "try_move_card",
    "advance_from_journal",
    "format_board",
    "board_payload_for_meta",
    "maybe_build_for_task",
    "main",
]
