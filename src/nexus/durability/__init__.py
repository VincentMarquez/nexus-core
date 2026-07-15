"""Per-run durability safety primitives (cycgraph pattern port).

Small modules only — budgets, taint labels, zero-trust state slices,
eval-gated memory writes, and a thin DurableAgent step wrapper.
Not a full monorepo copy.

Evidence drivers:
- wmcmahan/cycgraph — budgets, zero-trust state, taint tracking, eval-gated retention
- arXiv 2303.16641 — adversarial hierarchy (untrusted mined input)
"""

from .budgets import BudgetExhausted, RunBudget, budget_from_env, budget_from_meta
from .taint import TaintError, TaintLevel, TaintMeta, TaintSet
from .state_slice import SliceError, StateSlice, is_protected_key, slice_from_step
from .durable_agent import DurableAgent, StepResult
from .eval_memory import (
    DEFAULT_MIN_SCORE,
    EvalGate,
    GatedMemoryWriter,
    MemoryWriteDenied,
    WriteResult,
    retained_namespace,
    trial_namespace,
)

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
    "DEFAULT_MIN_SCORE",
    "EvalGate",
    "GatedMemoryWriter",
    "MemoryWriteDenied",
    "WriteResult",
    "retained_namespace",
    "trial_namespace",
]
