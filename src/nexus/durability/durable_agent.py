"""Thin durable step wrapper: budget pre-check + taint post-write.

Port of cycgraph runner discipline (budget before LLM/tool; taint on external
writes) without vendoring the monorepo. Safe to unit-test offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .budgets import BudgetExhausted, RunBudget, budget_from_env, budget_from_meta
from .taint import TaintError, TaintLevel, TaintSet, infer_source_level


@dataclass
class StepResult:
    """Outcome of one DurableAgent-guarded step."""

    ok: bool
    output: Any = None
    error: str = ""
    budget_exhausted: bool = False
    budget_kind: str = ""
    taint_stamped: list[str] = field(default_factory=list)
    budget_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "budget_exhausted": self.budget_exhausted,
            "budget_kind": self.budget_kind,
            "taint_stamped": list(self.taint_stamped),
            "budget_snapshot": dict(self.budget_snapshot),
        }


class DurableAgent:
    """Guards a step loop with per-run budgets and state taint labels.

    Typical use::

        agent = DurableAgent(budget=RunBudget(max_steps=5))
        agent.write("digest", blob, source="scout_repos/foo")
        agent.require_trusted("digest")  # raises TaintError
        agent.taint.promote("digest", gate="human-review")
        result = agent.run_step(lambda: do_work())
    """

    def __init__(
        self,
        *,
        budget: Optional[RunBudget] = None,
        taint: Optional[TaintSet] = None,
        state: Optional[dict[str, Any]] = None,
        agent_id: str = "durable",
        stop_on_budget: bool = True,
    ) -> None:
        self.budget = budget if budget is not None else RunBudget()
        self.taint = taint if taint is not None else TaintSet()
        self.state: dict[str, Any] = state if state is not None else {}
        self.agent_id = agent_id
        self.stop_on_budget = stop_on_budget
        self.steps_completed: int = 0
        # restore taint registry if embedded in state
        if "_taint_registry" in self.state and not taint:
            self.taint = TaintSet.extract(self.state)

    # ── factories ───────────────────────────────────────────────────────

    @classmethod
    def from_meta(
        cls,
        meta: Optional[dict[str, Any]] = None,
        *,
        agent_id: str = "durable",
        use_env: bool = True,
    ) -> "DurableAgent":
        """Build from task.meta (+ optional env defaults for unset caps)."""
        b = budget_from_meta(meta)
        if use_env:
            env_b = budget_from_env()
            if b.max_steps is None:
                b.max_steps = env_b.max_steps
            if b.max_tokens is None:
                b.max_tokens = env_b.max_tokens
            if b.max_cost_usd is None:
                b.max_cost_usd = env_b.max_cost_usd
        taint = TaintSet()
        if meta and isinstance(meta.get("_taint_registry"), dict):
            taint = TaintSet.from_dict(meta["_taint_registry"])
        return cls(budget=b, taint=taint, agent_id=agent_id)

    # ── budget gates ────────────────────────────────────────────────────

    def before_step(self) -> None:
        """Pre-step gate: refuse work when already exhausted; reserve one step.

        Raises :class:`BudgetExhausted` when a hard cap is already at capacity.
        Soft budgets set ``budget.soft_stop`` instead of raising.
        """
        # refuse if already at capacity before issuing the next step
        self.budget.check()
        if self.budget.soft_stop:
            return
        # reserve the step slot (landing on max_steps is allowed)
        self.budget.consume(steps=1, check=False)

    def record_usage(self, *, tokens: int = 0, cost_usd: float = 0.0) -> None:
        """Post-call token/cost accrual (raises only if already at capacity)."""
        self.budget.consume(tokens=tokens, cost_usd=cost_usd, check=True)

    # ── state + taint ───────────────────────────────────────────────────

    def write(
        self,
        key: str,
        value: Any,
        *,
        source: str = "",
        level: Optional[TaintLevel | str] = None,
        agent_id: str = "",
    ) -> Any:
        """Write *key* into state and stamp taint from source/level."""
        self.state[key] = value
        if level is None:
            level = infer_source_level(source) if source else TaintLevel.TRUSTED
        self.taint.stamp(
            key,
            level,
            source=source,
            agent_id=agent_id or self.agent_id,
        )
        self.taint.embed(self.state)
        return value

    def read(self, key: str, *, require_trusted: bool = False) -> Any:
        """Read state; optionally refuse untrusted keys."""
        if require_trusted:
            self.taint.require_trusted(key)
        return self.state.get(key)

    def require_trusted(self, key: str) -> Any:
        """Read *key* only if labeled trusted (or default trusted)."""
        self.taint.require_trusted(key)
        return self.state.get(key)

    def promote(self, key: str, *, gate: str) -> None:
        self.taint.promote(key, gate=gate, agent_id=self.agent_id)
        self.taint.embed(self.state)

    # ── step runner ─────────────────────────────────────────────────────

    def run_step(
        self,
        fn: Callable[[], Any],
        *,
        write_key: str = "",
        source: str = "",
        level: Optional[TaintLevel | str] = None,
        tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> StepResult:
        """Execute *fn* under budget pre-check; optional taint stamp on result.

        On budget exhaustion returns a controlled :class:`StepResult` when
        ``stop_on_budget`` is True; otherwise re-raises.
        """
        stamped: list[str] = []
        try:
            self.before_step()
        except BudgetExhausted as e:
            if self.stop_on_budget:
                return StepResult(
                    ok=False,
                    error=str(e),
                    budget_exhausted=True,
                    budget_kind=e.kind,
                    budget_snapshot=self.budget.snapshot(),
                )
            raise

        if self.budget.soft_stop:
            return StepResult(
                ok=False,
                error=self.budget.soft_reason or "budget soft-stop",
                budget_exhausted=True,
                budget_kind=self.budget.exhausted_kind() or "soft",
                budget_snapshot=self.budget.snapshot(),
            )

        try:
            out = fn()
        except BudgetExhausted as e:
            if self.stop_on_budget:
                return StepResult(
                    ok=False,
                    error=str(e),
                    budget_exhausted=True,
                    budget_kind=e.kind,
                    budget_snapshot=self.budget.snapshot(),
                )
            raise
        except Exception as e:  # noqa: BLE001 — surface as step failure
            return StepResult(
                ok=False,
                error=f"{type(e).__name__}: {e}",
                budget_snapshot=self.budget.snapshot(),
            )

        usage_err = ""
        usage_kind = ""
        try:
            if tokens or cost_usd:
                self.record_usage(tokens=tokens, cost_usd=cost_usd)
        except BudgetExhausted as e:
            # already at capacity before this usage — surface but keep work output
            usage_err = str(e)
            usage_kind = e.kind
            if not self.stop_on_budget:
                raise

        if write_key:
            self.write(write_key, out, source=source, level=level)
            stamped.append(write_key)

        self.steps_completed += 1
        kind = usage_kind or (self.budget.exhausted_kind() or "")
        return StepResult(
            ok=True,
            output=out,
            error=usage_err,
            budget_exhausted=bool(usage_err) or self.budget.exhausted(),
            budget_kind=kind,
            taint_stamped=stamped,
            budget_snapshot=self.budget.snapshot(),
        )

    def meta_patch(self) -> dict[str, Any]:
        """Fragment suitable for merging into ``task.meta``."""
        return {
            "run_budget": self.budget.snapshot(),
            "_taint_registry": self.taint.to_dict(),
            "durable_agent_id": self.agent_id,
            "durable_steps_completed": self.steps_completed,
        }
