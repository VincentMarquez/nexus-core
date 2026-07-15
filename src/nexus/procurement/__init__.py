"""Procurement Intelligence domain for NEXUS.

Deterministic scoring / TCO / policy engine + expert review lenses.
LLM (when present) extracts quotes; numbers always come from the engine.
"""

from .engine import (
    CostLine,
    ProcurementAnalysis,
    Supplier,
    DEFAULT_POLICY,
    DEFAULT_WEIGHTS,
)
from .experts import ExpertPanel, Finding, IncotermsExpert, LegalExpert, TechnicalExpert
from .demo import build_demo_analysis, run_demo

__all__ = [
    "CostLine",
    "ProcurementAnalysis",
    "Supplier",
    "DEFAULT_POLICY",
    "DEFAULT_WEIGHTS",
    "ExpertPanel",
    "Finding",
    "IncotermsExpert",
    "LegalExpert",
    "TechnicalExpert",
    "build_demo_analysis",
    "run_demo",
]
