"""Per-run step/token/cost budgets (cycgraph BudgetMonitor / budget-guard shape).

Hard-fail when a hard cap is exceeded mid-run so alive/mine loops cannot
thrash forever. Soft mode marks exhausted without raising (controlled stop).

Does not vendor cycgraph; pattern only.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


class BudgetExhausted(RuntimeError):
    """Raised when a per-run budget hard-cap is exceeded.

    Attributes:
        kind: which dimension exhausted (``steps`` | ``tokens`` | ``cost``).
        used: amount consumed on that dimension.
        limit: configured cap for that dimension.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        used: float,
        limit: float,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.used = used
        self.limit = limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "BudgetExhausted",
            "message": str(self),
            "kind": self.kind,
            "used": self.used,
            "limit": self.limit,
        }


@dataclass
class RunBudget:
    """Mutable per-run spend tracker with optional hard caps.

    ``None`` on a cap means unlimited for that dimension.
    """

    max_steps: Optional[int] = None
    max_tokens: Optional[int] = None
    max_cost_usd: Optional[float] = None
    steps_used: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    hard: bool = True
    # soft-mode bookkeeping when hard=False and a cap is hit
    soft_stop: bool = False
    soft_reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    # ── inspection ──────────────────────────────────────────────────────

    def remaining_steps(self) -> Optional[int]:
        if self.max_steps is None:
            return None
        return max(0, int(self.max_steps) - int(self.steps_used))

    def remaining_tokens(self) -> Optional[int]:
        if self.max_tokens is None:
            return None
        return max(0, int(self.max_tokens) - int(self.tokens_used))

    def remaining_cost_usd(self) -> Optional[float]:
        if self.max_cost_usd is None:
            return None
        return max(0.0, float(self.max_cost_usd) - float(self.cost_usd))

    def remaining(self) -> dict[str, Any]:
        return {
            "steps": self.remaining_steps(),
            "tokens": self.remaining_tokens(),
            "cost_usd": self.remaining_cost_usd(),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "steps_used": self.steps_used,
            "tokens_used": self.tokens_used,
            "cost_usd": round(float(self.cost_usd), 6),
            "hard": self.hard,
            "soft_stop": self.soft_stop,
            "soft_reason": self.soft_reason,
            "remaining": self.remaining(),
            "exhausted": self.exhausted_kind() is not None,
            "exhausted_kind": self.exhausted_kind(),
        }

    def exhausted_kind(self) -> Optional[str]:
        """Return which dimension is at capacity (no further spend allowed).

        At-capacity means ``used >= limit``: the last allowed unit was consumed
        successfully; the *next* ``consume`` of that dimension will fail.
        """
        if self.max_steps is not None and self.steps_used >= self.max_steps:
            return "steps"
        if self.max_tokens is not None and self.tokens_used >= self.max_tokens:
            return "tokens"
        if self.max_cost_usd is not None and self.cost_usd >= self.max_cost_usd:
            return "cost"
        return None

    def exhausted(self) -> bool:
        return self.exhausted_kind() is not None

    # ── mutation ────────────────────────────────────────────────────────

    def _raise_or_soft(self, kind: str, used: float, limit: float) -> None:
        msg = f"run budget exhausted: {kind} used={used} limit={limit}"
        if self.hard:
            raise BudgetExhausted(msg, kind=kind, used=used, limit=limit)
        self.soft_stop = True
        self.soft_reason = msg

    def check(self) -> None:
        """Raise (or soft-mark) if already at capacity. No-op if room remains."""
        kind = self.exhausted_kind()
        if kind is None:
            return
        if kind == "steps":
            self._raise_or_soft("steps", self.steps_used, float(self.max_steps or 0))
        elif kind == "tokens":
            self._raise_or_soft("tokens", self.tokens_used, float(self.max_tokens or 0))
        else:
            self._raise_or_soft("cost", self.cost_usd, float(self.max_cost_usd or 0.0))

    def consume(
        self,
        *,
        steps: int = 0,
        tokens: int = 0,
        cost_usd: float = 0.0,
        check: bool = True,
    ) -> None:
        """Accrue usage. Caps are inclusive: exactly ``max_N`` units are allowed.

        When *check* is True, refuse *before* accruing if already at capacity
        (``used >= limit``), so the next batch after a full budget is never
        issued (cycgraph composite budget-guard discipline). Landing exactly
        on the cap does not raise.
        """
        steps = int(steps or 0)
        tokens = int(tokens or 0)
        cost_usd = float(cost_usd or 0.0)

        if check:
            # any dimension already at capacity blocks further consume
            if self.exhausted():
                self.check()
                if self.soft_stop:
                    # soft mode: still accrue so counters reflect reality
                    pass
                else:
                    return  # unreachable: hard mode raises

        if steps:
            self.steps_used = int(self.steps_used) + steps
        if tokens:
            self.tokens_used = int(self.tokens_used) + tokens
        if cost_usd:
            self.cost_usd = float(self.cost_usd) + cost_usd

    def would_exceed(
        self,
        *,
        steps: int = 0,
        tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> Optional[str]:
        """Predict which kind would be at capacity after this consume."""
        if self.max_steps is not None and int(self.steps_used) + int(steps) >= int(self.max_steps):
            if steps or self.steps_used >= self.max_steps:
                return "steps"
        if self.max_tokens is not None and int(self.tokens_used) + int(tokens) >= int(
            self.max_tokens
        ):
            if tokens or self.tokens_used >= self.max_tokens:
                return "tokens"
        if self.max_cost_usd is not None and float(self.cost_usd) + float(cost_usd) >= float(
            self.max_cost_usd
        ):
            if cost_usd or self.cost_usd >= self.max_cost_usd:
                return "cost"
        return None

    # ── serde ───────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunBudget":
        if not d:
            return cls()
        return cls(
            max_steps=_opt_int(d.get("max_steps")),
            max_tokens=_opt_int(d.get("max_tokens")),
            max_cost_usd=_opt_float(d.get("max_cost_usd")),
            steps_used=int(d.get("steps_used") or 0),
            tokens_used=int(d.get("tokens_used") or 0),
            cost_usd=float(d.get("cost_usd") or 0.0),
            hard=bool(d.get("hard", True)),
            soft_stop=bool(d.get("soft_stop", False)),
            soft_reason=str(d.get("soft_reason") or ""),
            extra={
                k: v
                for k, v in d.items()
                if k
                not in {
                    "max_steps",
                    "max_tokens",
                    "max_cost_usd",
                    "steps_used",
                    "tokens_used",
                    "cost_usd",
                    "hard",
                    "soft_stop",
                    "soft_reason",
                }
            },
        )


def _opt_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        n = int(v)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _opt_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        n = float(v)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def budget_from_env(
    *,
    prefix: str = "NEXUS_",
    hard: bool = True,
) -> RunBudget:
    """Build a RunBudget from process env (zero-config alive/mine caps).

    Recognized keys:
    - ``NEXUS_MAX_STEPS``
    - ``NEXUS_MAX_TOKENS`` / ``NEXUS_MAX_TOKENS_RUN``
    - ``NEXUS_MAX_COST`` / ``NEXUS_MAX_COST_USD``
    """
    return RunBudget(
        max_steps=_opt_int(os.environ.get(f"{prefix}MAX_STEPS")),
        max_tokens=_opt_int(
            os.environ.get(f"{prefix}MAX_TOKENS_RUN")
            or os.environ.get(f"{prefix}MAX_TOKENS")
        ),
        max_cost_usd=_opt_float(
            os.environ.get(f"{prefix}MAX_COST_USD") or os.environ.get(f"{prefix}MAX_COST")
        ),
        hard=hard,
    )


def budget_from_meta(meta: Optional[dict[str, Any]], *, hard: bool = True) -> RunBudget:
    """Resolve RunBudget from task.meta keys (and nested ``meta.budget``)."""
    meta = meta or {}
    nested = meta.get("budget") if isinstance(meta.get("budget"), dict) else {}
    # flat keys win over nested for explicit per-task overrides
    return RunBudget(
        max_steps=_opt_int(meta.get("max_steps", nested.get("max_steps"))),
        max_tokens=_opt_int(meta.get("max_tokens", nested.get("max_tokens"))),
        max_cost_usd=_opt_float(
            meta.get("max_cost_usd", meta.get("max_cost", nested.get("max_cost_usd")))
        ),
        steps_used=int(meta.get("steps_used") or nested.get("steps_used") or 0),
        tokens_used=int(
            meta.get("tokens_total")
            or meta.get("tokens_used")
            or nested.get("tokens_used")
            or 0
        ),
        cost_usd=float(meta.get("cost_usd") or nested.get("cost_usd") or 0.0),
        hard=hard if meta.get("budget_hard") is None else bool(meta.get("budget_hard")),
    )
