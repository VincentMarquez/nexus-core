"""Per-run durability safety primitives (cycgraph pattern port).

Small modules only — budgets, taint labels, and a thin DurableAgent
step wrapper. Not a full zero-trust policy engine or monorepo copy.

Evidence drivers:
- wmcmahan/cycgraph — budgets, zero-trust state, taint tracking
- arXiv 2303.16641 — adversarial hierarchy (untrusted mined input)
"""

from .budgets import BudgetExhausted, RunBudget, budget_from_env, budget_from_meta
from .taint import TaintError, TaintLevel, TaintMeta, TaintSet
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
    "DurableAgent",
    "StepResult",
]
