"""Action-order scheduler for the self-improve pipeline (AOAD-MAT-inspired).

P0.2 from docs/LATEST_IMPROVE_PLAN.md — fixed stage graph so workers cannot
skip ahead or run out of order.

Default full order::

  scout → mine → grade → claim_verify → plan_apply → review → apply → regrade

First-apply smoke order (subset)::

  mine → grade → claim_verify

Stages refuse to run unless all predecessors are completed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

# Full self-improve action order (paper 2510.13343 — ordered agent actions).
DEFAULT_STAGES: tuple[str, ...] = (
    "scout",
    "mine",
    "grade",
    "claim_verify",
    "plan_apply",
    "review",
    "apply",
    "regrade",
)

# Minimal vertical slice for offline smoke (no live apply).
SMOKE_STAGES: tuple[str, ...] = (
    "mine",
    "grade",
    "claim_verify",
)


class StageOrderError(RuntimeError):
    """Stage requested out of order or unknown."""


def normalize_stages(stages: Sequence[str] | None = None) -> tuple[str, ...]:
    """Return a non-empty ordered tuple of stage names."""
    if not stages:
        return DEFAULT_STAGES
    out: list[str] = []
    seen: set[str] = set()
    for s in stages:
        name = str(s or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    if not out:
        raise StageOrderError("stage list must be non-empty")
    return tuple(out)


def stage_index(stages: Sequence[str], name: str) -> int:
    order = normalize_stages(list(stages))
    key = str(name or "").strip().lower()
    try:
        return order.index(key)
    except ValueError as e:
        raise StageOrderError(f"unknown stage {name!r}; known={list(order)}") from e


def predecessors(stages: Sequence[str], name: str) -> tuple[str, ...]:
    """Stages that must be completed before *name* may run."""
    order = normalize_stages(list(stages))
    idx = stage_index(order, name)
    return order[:idx]


def can_run(
    stages: Sequence[str],
    name: str,
    completed: Iterable[str],
) -> bool:
    """True when all predecessors of *name* are in *completed*."""
    done = {str(x).strip().lower() for x in completed}
    try:
        preds = predecessors(stages, name)
    except StageOrderError:
        return False
    return all(p in done for p in preds)


def assert_can_run(
    stages: Sequence[str],
    name: str,
    completed: Iterable[str],
) -> None:
    """Raise StageOrderError if *name* cannot run given *completed*."""
    order = normalize_stages(list(stages))
    key = str(name or "").strip().lower()
    if key not in order:
        raise StageOrderError(f"unknown stage {name!r}; known={list(order)}")
    done = {str(x).strip().lower() for x in completed}
    missing = [p for p in predecessors(order, key) if p not in done]
    if missing:
        raise StageOrderError(
            f"stage {key!r} refused: incomplete predecessors {missing} "
            f"(completed={sorted(done)}, order={list(order)})"
        )


def next_stage(
    stages: Sequence[str],
    completed: Iterable[str],
) -> Optional[str]:
    """First stage not yet completed, or None when all done."""
    order = normalize_stages(list(stages))
    done = {str(x).strip().lower() for x in completed}
    for s in order:
        if s not in done:
            return s
    return None


@dataclass
class StageRunner:
    """Tracks completed stages and enforces order on mark_complete / run gates."""

    stages: tuple[str, ...] = field(default_factory=lambda: DEFAULT_STAGES)
    completed: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.stages = normalize_stages(self.stages)
        # Keep only known stages, preserve order of first occurrence
        seen: set[str] = set()
        cleaned: list[str] = []
        for c in self.completed:
            name = str(c or "").strip().lower()
            if name in self.stages and name not in seen:
                seen.add(name)
                cleaned.append(name)
        self.completed = cleaned

    @classmethod
    def smoke(cls) -> "StageRunner":
        """Runner for the first-apply mine→grade→claim_verify slice."""
        return cls(stages=SMOKE_STAGES)

    def can_run(self, name: str) -> bool:
        return can_run(self.stages, name, self.completed)

    def assert_can_run(self, name: str) -> None:
        assert_can_run(self.stages, name, self.completed)

    def mark_complete(self, name: str) -> list[str]:
        """Mark stage complete after order check; idempotent if already done."""
        key = str(name or "").strip().lower()
        if key in self.completed:
            return list(self.completed)
        self.assert_can_run(key)
        self.completed.append(key)
        return list(self.completed)

    def next(self) -> Optional[str]:
        return next_stage(self.stages, self.completed)

    def is_done(self) -> bool:
        return self.next() is None

    def status(self) -> dict[str, Any]:
        nxt = self.next()
        return {
            "schema": "nexus.stages/v1",
            "stages": list(self.stages),
            "completed": list(self.completed),
            "next": nxt,
            "done": nxt is None,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.status()
