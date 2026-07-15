"""Thin durable step wrapper: budget pre-check + taint post-write + state slice.

Port of cycgraph runner discipline (budget before LLM/tool; taint on external
writes; permission-scoped state) without vendoring the monorepo. Safe to
unit-test offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .budgets import BudgetExhausted, RunBudget, budget_from_env, budget_from_meta
from .state_slice import SliceError, StateSlice
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
    slice_denied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "budget_exhausted": self.budget_exhausted,
            "budget_kind": self.budget_kind,
            "taint_stamped": list(self.taint_stamped),
            "budget_snapshot": dict(self.budget_snapshot),
            "slice_denied": self.slice_denied,
        }


class DurableAgent:
    """Guards a step loop with budgets, taint labels, and zero-trust state slices.

    Typical use::

        agent = DurableAgent(
            budget=RunBudget(max_steps=5),
            slice=StateSlice.from_keys(read_keys=["goal"], write_keys=["plan"]),
        )
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
        slice: Optional[StateSlice] = None,
        agent_id: str = "durable",
        stop_on_budget: bool = True,
        enforce_slice: bool = True,
    ) -> None:
        self.budget = budget if budget is not None else RunBudget()
        self.taint = taint if taint is not None else TaintSet()
        self.state: dict[str, Any] = state if state is not None else {}
        self.agent_id = agent_id
        self.stop_on_budget = stop_on_budget
        self.enforce_slice = enforce_slice
        # None = open-all (backward compatible); empty StateSlice = zero-trust deny
        if slice is None:
            self.slice = StateSlice.open_all(agent_id=agent_id)
            self._slice_explicit = False
        else:
            self.slice = slice
            if not self.slice.agent_id:
                self.slice.agent_id = agent_id
            self._slice_explicit = True
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
        # only apply slice when meta declares read_keys/write_keys/state_slice
        slice_obj: Optional[StateSlice] = None
        if meta and (
            meta.get("read_keys") is not None
            or meta.get("write_keys") is not None
            or isinstance(meta.get("state_slice"), dict)
        ):
            slice_obj = StateSlice.from_meta(meta, agent_id=agent_id)
        return cls(budget=b, taint=taint, slice=slice_obj, agent_id=agent_id)

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

    # ── state + taint + slice ───────────────────────────────────────────

    def view(self) -> dict[str, Any]:
        """Permission-scoped snapshot of state (zero-trust read filter)."""
        return self.slice.view(self.state)

    def write(
        self,
        key: str,
        value: Any,
        *,
        source: str = "",
        level: Optional[TaintLevel | str] = None,
        agent_id: str = "",
        strict_slice: Optional[bool] = None,
    ) -> Any:
        """Write *key* into state under slice permissions; stamp taint."""
        enforce = self.enforce_slice if strict_slice is None else strict_slice
        if enforce and self._slice_explicit:
            self.slice.require_write(key)
        elif enforce and not self.slice.can_write(key):
            # open_all still blocks protected keys
            self.slice.require_write(key)
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

    def read(
        self,
        key: str,
        *,
        require_trusted: bool = False,
        enforce_slice: Optional[bool] = None,
    ) -> Any:
        """Read state; optionally refuse untrusted or out-of-slice keys."""
        check = self.enforce_slice if enforce_slice is None else enforce_slice
        if check and self._slice_explicit:
            self.slice.require_read(key)
        if require_trusted:
            self.taint.require_trusted(key)
        return self.state.get(key)

    def require_trusted(self, key: str) -> Any:
        """Read *key* only if labeled trusted (or default trusted)."""
        if self.enforce_slice and self._slice_explicit:
            self.slice.require_read(key)
        self.taint.require_trusted(key)
        return self.state.get(key)

    def promote(self, key: str, *, gate: str) -> None:
        self.taint.promote(key, gate=gate, agent_id=self.agent_id)
        self.taint.embed(self.state)

    def merge_writes(
        self,
        patch: dict[str, Any],
        *,
        source: str = "",
        strict: bool = True,
    ) -> dict[str, Any]:
        """Apply a multi-key patch under write_keys; stamp each key's taint."""
        applied = self.slice.merge_writes(self.state, patch, strict=strict)
        level = infer_source_level(source) if source else TaintLevel.TRUSTED
        for k in patch:
            if k in applied and (strict or self.slice.can_write(k)):
                if self.slice.can_write(k):
                    self.taint.stamp(k, level, source=source, agent_id=self.agent_id)
        self.taint.embed(self.state)
        return {k: self.state[k] for k in patch if k in self.state and self.slice.can_write(k)}

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
        ``stop_on_budget`` is True; otherwise re-raises. Slice denials on
        ``write_key`` are returned as controlled failures (not raised).
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
            try:
                self.write(write_key, out, source=source, level=level)
                stamped.append(write_key)
            except SliceError as e:
                return StepResult(
                    ok=False,
                    output=out,
                    error=str(e),
                    slice_denied=True,
                    taint_stamped=stamped,
                    budget_snapshot=self.budget.snapshot(),
                )

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
        patch: dict[str, Any] = {
            "run_budget": self.budget.snapshot(),
            "_taint_registry": self.taint.to_dict(),
            "durable_agent_id": self.agent_id,
            "durable_steps_completed": self.steps_completed,
        }
        if self._slice_explicit:
            patch["state_slice"] = self.slice.to_dict()
        return patch

