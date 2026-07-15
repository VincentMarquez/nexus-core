"""Per-run durability safety primitives (cycgraph + zenith pattern ports).

Small modules only — budgets, taint labels, zero-trust state slices,
eval-gated memory writes, principled stop, gap-board plan seed,
independent verify-before-promote, and a thin DurableAgent step wrapper.
Not a full monorepo copy.

Evidence drivers:
- wmcmahan/cycgraph — budgets, zero-trust state, taint tracking, eval-gated retention
- Intelligent-Internet/zenith — gap review, stopping discipline, independent verify
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
from .stop import (
    REASON_ABORT,
    REASON_BUDGET,
    REASON_CONTINUE,
    REASON_GAPS_CLOSED,
    REASON_MAX_CYCLES,
    REASON_NO_PROGRESS,
    REASON_TESTS_RED,
    REASON_USER,
    GapItem,
    PrincipledStop,
    StopDecision,
    StopPolicy,
    cycle_progressed,
    default_stop_path,
)
from .gap_seed import (
    SCHEMA as GAP_SEED_SCHEMA,
    board_snapshot,
    collect_plan_gaps,
    parse_plan_gaps,
    seed_gap_board,
)
from .verify_promote import (
    DEFAULT_VERIFY_MIN_SCORE,
    IndependentVerify,
    VerifyError,
    VerifyResult,
    promote_memory_verified,
    promote_taint_verified,
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
    "REASON_ABORT",
    "REASON_BUDGET",
    "REASON_CONTINUE",
    "REASON_GAPS_CLOSED",
    "REASON_MAX_CYCLES",
    "REASON_NO_PROGRESS",
    "REASON_TESTS_RED",
    "REASON_USER",
    "GapItem",
    "PrincipledStop",
    "StopDecision",
    "StopPolicy",
    "cycle_progressed",
    "default_stop_path",
    "GAP_SEED_SCHEMA",
    "board_snapshot",
    "collect_plan_gaps",
    "parse_plan_gaps",
    "seed_gap_board",
    "DEFAULT_VERIFY_MIN_SCORE",
    "IndependentVerify",
    "VerifyError",
    "VerifyResult",
    "promote_memory_verified",
    "promote_taint_verified",
]
