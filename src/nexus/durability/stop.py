"""Principled stopping discipline for long-running improve loops (zenith pattern).

Long-horizon agent harnesses fail from *premature* stop *or* endless thrash.
Zenith isolates **stopping discipline** + **gap review**: continue while open
gaps remain *and* progress is still possible; stop only with an auditable reason.

Does not vendor zenith; pattern only.

Evidence drivers:
- Intelligent-Internet/zenith — gap-finding + adaptive stop (not premature; not infinite)
- RALPH contrast — repeated gap reopen without a principled stop rule
- NEXUS alive loop — budget already hard-stops; this adds gap/progress discipline
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional


# ── stop reasons (auditable) ────────────────────────────────────────────

REASON_CONTINUE = "continue"
REASON_GAPS_CLOSED = "gaps_closed"
REASON_NO_PROGRESS = "no_progress"
REASON_MAX_CYCLES = "max_cycles"
REASON_BUDGET = "budget"
REASON_TESTS_RED = "tests_red"
REASON_ABORT = "abort"
REASON_USER = "user"

STOP_REASONS = frozenset(
    {
        REASON_GAPS_CLOSED,
        REASON_NO_PROGRESS,
        REASON_MAX_CYCLES,
        REASON_BUDGET,
        REASON_TESTS_RED,
        REASON_ABORT,
        REASON_USER,
    }
)


@dataclass
class GapItem:
    """One falsifiable remaining gap between goal/state and definition-of-done."""

    id: str
    description: str = ""
    open: bool = True
    evidence: str = ""
    closed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GapItem":
        return cls(
            id=str(d.get("id") or ""),
            description=str(d.get("description") or ""),
            open=bool(d.get("open", True)),
            evidence=str(d.get("evidence") or ""),
            closed_at=float(d.get("closed_at") or 0.0),
        )


@dataclass
class StopPolicy:
    """Tunable stop discipline (fail-open to continue when ambiguous)."""

    # stop after N consecutive cycles with no measurable progress
    max_no_progress: int = 3
    # hard cap on total cycles (None = unlimited)
    max_cycles: Optional[int] = None
    # when True, stop once every registered gap is closed (and ≥1 gap exists)
    stop_when_gaps_closed: bool = True
    # when True and no gaps registered, never stop for gaps_closed
    require_registered_gaps: bool = True
    # optional hard stop if self-check fails (default off — prefer fix loops)
    stop_on_tests_red: bool = False
    # when True, budget block is a stop reason (alive already returns early)
    stop_on_budget: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_no_progress": int(self.max_no_progress),
            "max_cycles": self.max_cycles,
            "stop_when_gaps_closed": bool(self.stop_when_gaps_closed),
            "require_registered_gaps": bool(self.require_registered_gaps),
            "stop_on_tests_red": bool(self.stop_on_tests_red),
            "stop_on_budget": bool(self.stop_on_budget),
        }

    @classmethod
    def from_dict(cls, d: Optional[dict[str, Any]] = None) -> "StopPolicy":
        d = d or {}
        max_cycles = d.get("max_cycles")
        try:
            mc = None if max_cycles in (None, "", 0, "0") else int(max_cycles)
        except (TypeError, ValueError):
            mc = None
        try:
            mnp = int(d.get("max_no_progress", 3))
        except (TypeError, ValueError):
            mnp = 3
        return cls(
            max_no_progress=max(1, mnp),
            max_cycles=mc,
            stop_when_gaps_closed=bool(d.get("stop_when_gaps_closed", True)),
            require_registered_gaps=bool(d.get("require_registered_gaps", True)),
            stop_on_tests_red=bool(d.get("stop_on_tests_red", False)),
            stop_on_budget=bool(d.get("stop_on_budget", True)),
        )

    @classmethod
    def from_meta(cls, meta: Optional[dict[str, Any]] = None) -> "StopPolicy":
        """Build from task/alive meta keys: ``stop_max_no_progress``, nested ``stop``."""
        meta = meta or {}
        nested = meta.get("stop") if isinstance(meta.get("stop"), dict) else {}
        merged = {**nested}
        if "stop_max_no_progress" in meta:
            merged["max_no_progress"] = meta["stop_max_no_progress"]
        if "stop_max_cycles" in meta:
            merged["max_cycles"] = meta["stop_max_cycles"]
        if "stop_when_gaps_closed" in meta:
            merged["stop_when_gaps_closed"] = meta["stop_when_gaps_closed"]
        if "stop_on_tests_red" in meta:
            merged["stop_on_tests_red"] = meta["stop_on_tests_red"]
        return cls.from_dict(merged)


@dataclass
class StopDecision:
    """Outcome of one stop evaluation."""

    stop: bool
    reason: str = REASON_CONTINUE
    detail: str = ""
    cycle: int = 0
    no_progress_streak: int = 0
    gaps_open: int = 0
    gaps_closed: int = 0
    progressed: bool = False
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stop": self.stop,
            "reason": self.reason,
            "detail": self.detail,
            "cycle": self.cycle,
            "no_progress_streak": self.no_progress_streak,
            "gaps_open": self.gaps_open,
            "gaps_closed": self.gaps_closed,
            "progressed": self.progressed,
            "ts": self.ts,
        }


@dataclass
class PrincipledStop:
    """Gap board + stop evaluator for improve / alive loops.

    Typical use::

        stop = PrincipledStop(policy=StopPolicy(max_no_progress=3))
        stop.register_gap("P0.4", "principled stop module")
        d = stop.record_cycle(progressed=True, tests_ok=True)
        assert not d.stop
        stop.close_gap("P0.4", evidence="landed + tests green")
        d = stop.record_cycle(progressed=True)
        assert d.stop and d.reason == "gaps_closed"
    """

    policy: StopPolicy = field(default_factory=StopPolicy)
    gaps: dict[str, GapItem] = field(default_factory=dict)
    cycle: int = 0
    no_progress_streak: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    # ── gap board ───────────────────────────────────────────────────────

    def register_gap(
        self,
        gap_id: str,
        description: str = "",
        *,
        evidence: str = "",
    ) -> GapItem:
        gid = (gap_id or "").strip()
        if not gid:
            raise ValueError("gap id required")
        existing = self.gaps.get(gid)
        if existing is not None:
            if description:
                existing.description = description
            if evidence:
                existing.evidence = evidence
            # re-open if previously closed and re-registered
            existing.open = True
            existing.closed_at = 0.0
            return existing
        item = GapItem(id=gid, description=description, open=True, evidence=evidence)
        self.gaps[gid] = item
        return item

    def close_gap(self, gap_id: str, *, evidence: str = "") -> GapItem:
        gid = (gap_id or "").strip()
        if gid not in self.gaps:
            raise KeyError(f"unknown gap {gid!r}")
        item = self.gaps[gid]
        item.open = False
        item.closed_at = time.time()
        if evidence:
            item.evidence = evidence
        return item

    def reopen_gap(self, gap_id: str, *, evidence: str = "") -> GapItem:
        """Zenith/RALPH-style gap reopen when verification finds residual work."""
        gid = (gap_id or "").strip()
        if gid not in self.gaps:
            return self.register_gap(gid, evidence=evidence)
        item = self.gaps[gid]
        item.open = True
        item.closed_at = 0.0
        if evidence:
            item.evidence = evidence
        return item

    def sync_gaps(
        self,
        items: Iterable[dict[str, Any] | GapItem | str],
        *,
        close_missing: bool = False,
    ) -> list[GapItem]:
        """Upsert gaps from a backlog list; optionally close ids not present."""
        seen: set[str] = set()
        out: list[GapItem] = []
        for raw in items:
            if isinstance(raw, GapItem):
                g = self.register_gap(raw.id, raw.description, evidence=raw.evidence)
                if not raw.open:
                    self.close_gap(raw.id, evidence=raw.evidence)
                    g = self.gaps[raw.id]
            elif isinstance(raw, str):
                g = self.register_gap(raw)
            else:
                g = self.register_gap(
                    str(raw.get("id") or raw.get("gap_id") or ""),
                    str(raw.get("description") or raw.get("title") or ""),
                    evidence=str(raw.get("evidence") or ""),
                )
                if raw.get("open") is False:
                    self.close_gap(g.id, evidence=str(raw.get("evidence") or ""))
                    g = self.gaps[g.id]
            seen.add(g.id)
            out.append(g)
        if close_missing:
            for gid, item in list(self.gaps.items()):
                if gid not in seen and item.open:
                    self.close_gap(gid, evidence="sync:missing_from_backlog")
        return out

    def open_gaps(self) -> list[GapItem]:
        return [g for g in self.gaps.values() if g.open]

    def closed_gaps(self) -> list[GapItem]:
        return [g for g in self.gaps.values() if not g.open]

    def gap_counts(self) -> dict[str, int]:
        open_n = sum(1 for g in self.gaps.values() if g.open)
        closed_n = len(self.gaps) - open_n
        return {"open": open_n, "closed": closed_n, "total": len(self.gaps)}

    # ── evaluate / record ───────────────────────────────────────────────

    def abort(self, reason: str = "operator abort") -> StopDecision:
        self.aborted = True
        self.abort_reason = (reason or "abort").strip() or "abort"
        return self.evaluate(
            progressed=False,
            tests_ok=True,
            budget_ok=True,
            force_reason=REASON_ABORT,
        )

    def evaluate(
        self,
        *,
        progressed: bool = False,
        tests_ok: bool = True,
        budget_ok: bool = True,
        force_reason: str = "",
        preview: bool = True,
    ) -> StopDecision:
        """Evaluate stop against board + policy without mutating state.

        When *preview* is True (default), projects the cycle/streak that would
        result if this outcome were recorded. When False, uses the already
        updated counters (used by :meth:`record_cycle` after mutation).
        """
        counts = self.gap_counts()
        if preview:
            cycle = int(self.cycle) + 1
            streak = 0 if progressed else int(self.no_progress_streak) + 1
        else:
            cycle = int(self.cycle)
            streak = int(self.no_progress_streak)

        def _dec(stop: bool, reason: str, detail: str) -> StopDecision:
            return StopDecision(
                stop=stop,
                reason=reason,
                detail=detail,
                cycle=cycle,
                no_progress_streak=streak,
                gaps_open=counts["open"],
                gaps_closed=counts["closed"],
                progressed=progressed,
            )

        if force_reason == REASON_ABORT or self.aborted:
            return _dec(
                True,
                REASON_ABORT,
                self.abort_reason or force_reason or "aborted",
            )

        if force_reason == REASON_USER:
            return _dec(True, REASON_USER, "user requested stop")

        if self.policy.stop_on_budget and not budget_ok:
            return _dec(True, REASON_BUDGET, "usage or run budget blocked")

        if self.policy.stop_on_tests_red and not tests_ok:
            return _dec(True, REASON_TESTS_RED, "self-check not green")

        if self.policy.max_cycles is not None and cycle >= int(self.policy.max_cycles):
            return _dec(
                True,
                REASON_MAX_CYCLES,
                f"cycle {cycle} >= max_cycles {self.policy.max_cycles}",
            )

        # no-progress thrash guard
        if streak >= int(self.policy.max_no_progress):
            return _dec(
                True,
                REASON_NO_PROGRESS,
                f"{streak} consecutive cycles without progress "
                f"(max_no_progress={self.policy.max_no_progress})",
            )

        if self.policy.stop_when_gaps_closed:
            total = counts["total"]
            if total > 0 and counts["open"] == 0:
                return _dec(
                    True,
                    REASON_GAPS_CLOSED,
                    f"all {total} registered gaps closed",
                )
            if total == 0 and not self.policy.require_registered_gaps:
                return _dec(
                    True,
                    REASON_GAPS_CLOSED,
                    "no gaps registered (require_registered_gaps=false)",
                )

        return _dec(
            False,
            REASON_CONTINUE,
            "open gaps remain or progress still possible",
        )

    def record_cycle(
        self,
        *,
        progressed: bool,
        tests_ok: bool = True,
        budget_ok: bool = True,
        note: str = "",
    ) -> StopDecision:
        """Advance cycle counter, update no-progress streak, evaluate stop."""
        self.cycle += 1
        if progressed:
            self.no_progress_streak = 0
        else:
            self.no_progress_streak += 1
        decision = self.evaluate(
            progressed=progressed,
            tests_ok=tests_ok,
            budget_ok=budget_ok,
            preview=False,
        )
        entry = decision.to_dict()
        if note:
            entry["note"] = note
        self.history.append(entry)
        return decision

    # ── persistence ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.to_dict(),
            "gaps": {k: v.to_dict() for k, v in self.gaps.items()},
            "cycle": self.cycle,
            "no_progress_streak": self.no_progress_streak,
            "history": list(self.history[-50:]),  # cap audit tail
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
        }

    @classmethod
    def from_dict(cls, d: Optional[dict[str, Any]] = None) -> "PrincipledStop":
        d = d or {}
        gaps_raw = d.get("gaps") or {}
        gaps: dict[str, GapItem] = {}
        if isinstance(gaps_raw, dict):
            for k, v in gaps_raw.items():
                if isinstance(v, dict):
                    gaps[str(k)] = GapItem.from_dict({**v, "id": v.get("id") or k})
        elif isinstance(gaps_raw, list):
            for v in gaps_raw:
                if isinstance(v, dict) and v.get("id"):
                    gaps[str(v["id"])] = GapItem.from_dict(v)
        hist = d.get("history") or []
        if not isinstance(hist, list):
            hist = []
        return cls(
            policy=StopPolicy.from_dict(d.get("policy") if isinstance(d.get("policy"), dict) else {}),
            gaps=gaps,
            cycle=int(d.get("cycle") or 0),
            no_progress_streak=int(d.get("no_progress_streak") or 0),
            history=list(hist),
            aborted=bool(d.get("aborted", False)),
            abort_reason=str(d.get("abort_reason") or ""),
        )

    def save(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: Path | str) -> "PrincipledStop":
        p = Path(path)
        if not p.is_file():
            return cls()
        try:
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return cls()


def cycle_progressed(report: dict[str, Any]) -> bool:
    """Heuristic: did this alive/improve cycle make measurable progress?

    True when apply landed, code/docs steps succeeded beyond pure mine/log,
    or an explicit ``progressed`` flag is set. Used so no-progress thrash
    can stop the watch loop without requiring LLM judgment.
    """
    if not report:
        return False
    if report.get("progressed") is True:
        return True
    if report.get("blocked"):
        return False
    steps = report.get("steps") or []
    progress_steps = {
        "self_approve_apply",
        "apply",
        "improve_apply",
        "publish_github",
        "plan_snapshot",
        "improvements_log",
    }
    for s in steps:
        if not isinstance(s, dict):
            continue
        name = str(s.get("step") or "")
        if s.get("error") or s.get("blocked"):
            continue
        if s.get("skipped"):
            continue
        if name in progress_steps and s.get("ok", True):
            # publish skipped counts as not progress
            if name == "publish_github" and s.get("skipped"):
                continue
            if name == "self_approve_apply":
                apply = s.get("apply") or {}
                if isinstance(apply, dict) and apply.get("status") in {
                    "completed",
                    "ok",
                    "applied",
                }:
                    return True
                if s.get("ok"):
                    return True
            if name in {"apply", "improve_apply"} and s.get("ok", True):
                return True
            if name == "publish_github" and (s.get("pushed") or s.get("committed")):
                return True
            # docs snapshots alone are weak progress — only count with apply-ish ok
            if name in {"plan_snapshot", "improvements_log"} and report.get("applied"):
                return True
    # explicit apply payload on report
    applied = report.get("applied") or report.get("apply")
    if isinstance(applied, dict) and applied.get("status") in {
        "completed",
        "ok",
        "applied",
    }:
        return True
    return False


def default_stop_path(workdir: Path | str) -> Path:
    return Path(workdir) / ".nexus_state" / "alive_stop.json"
