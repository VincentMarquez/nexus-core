"""Per-run durability safety primitives (cycgraph pattern port).

Small modules only — budgets, taint labels, zero-trust state slices, and a
thin DurableAgent step wrapper. Not a full monorepo copy.

Evidence drivers:
- wmcmahan/cycgraph — budgets, zero-trust state, taint tracking
- arXiv 2303.16641 — adversarial hierarchy (untrusted mined input)
"""

from .budgets import BudgetExhausted, RunBudget, budget_from_env, budget_from_meta
from .taint import TaintError, TaintLevel, TaintMeta, TaintSet
from .state_slice import SliceError, StateSlice, is_protected_key, slice_from_step
from .durable_agent import DurableAgent, StepResult

__all__ = [
    "BudgetExhausted",
    "RunBudget",
    "budget_from_env",
    "budget_from_meta",
    "TaintError",
    "TaintLevel",
    "TaintMeta",
    "TaintSet",
    "SliceError",
    "StateSlice",
    "is_protected_key",
    "slice_from_step",
    "DurableAgent",
    "StepResult",
]
