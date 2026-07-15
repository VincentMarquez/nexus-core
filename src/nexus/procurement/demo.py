"""Synthetic 3-supplier demo (no private quotes)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .engine import CostLine, ProcurementAnalysis, Supplier
from .experts import ExpertPanel


def build_demo_analysis() -> ProcurementAnalysis:
    CL = CostLine
    A = Supplier(
        name="Acme Components",
        scores={
            "Technical Fit & Quality": {
                "Spec compliance": {"score": 9, "evidence": "meets all 14 specs, MTC+COC"},
                "Quality system": {"score": 8, "evidence": "ISO 9001 + AS9100"},
            },
            "Commercial Terms & Risk": {
                "Terms": {"score": 7, "evidence": "Net 45"},
                "Termination": {"score": 6, "evidence": "30d for cause"},
            },
            "Cost & TCO": {"Unit price": {"score": 6, "evidence": "$2.85/kg"}},
            "Delivery / Lead Time / Capacity": {
                "Lead time": {"score": 8, "evidence": "14 days"}
            },
            "Compliance / ESG / Reputation": {
                "ESG": {"score": 7, "evidence": "EcoVadis Silver"}
            },
        },
        payment_terms_days=45,
        price_validity_days=60,
        price_escalation_pct=3.0,
        warranty_months=24,
        lead_time_days=14,
        iso9001=True,
        other_certs=["AS9100"],
        auto_renew=False,
        termination_clause="30d for cause",
        ip_ownership="Buyer owns tooling",
        cost_lines=[
            CL("Widget", 5000, 2.85, recurring=False),
            CL("Annual support", 1, 12000, recurring=True),
        ],
        implementation_cost=8000,
        annual_ops_cost=4000,
        annual_maintenance_cost=3000,
        disposal_cost=2000,
        sources=["Acme quote Q-1192 p.2-3"],
        attrs={
            "incoterm": "DAP",
            "part_number": "WID-100",
            "revision": "C",
            "liability_cap": "12 months fees",
            "governing_law": "Delaware",
        },
    )
    B = Supplier(
        name="Borealis Mfg",
        scores={
            "Technical Fit & Quality": {
                "Spec compliance": {"score": 7, "evidence": "2 specs partial"},
                "Quality system": {"score": 5, "evidence": "ISO pending"},
            },
            "Commercial Terms & Risk": {
                "Terms": {"score": 9, "evidence": "Net 60"},
                "Termination": {"score": 5, "evidence": "auto-renew 30d notice"},
            },
            "Cost & TCO": {"Unit price": {"score": 9, "evidence": "$1.20/kg"}},
            "Delivery / Lead Time / Capacity": {
                "Lead time": {"score": 4, "evidence": "35 days"}
            },
            "Compliance / ESG / Reputation": {"ESG": {"score": 5, "evidence": "no rating"}},
        },
        payment_terms_days=60,
        price_validity_days=30,
        price_escalation_pct=7.0,
        warranty_months=12,
        lead_time_days=35,
        iso9001=False,
        auto_renew=True,
        auto_renew_notice_days=30,
        termination_clause="auto-renew, 30d notice",
        ip_ownership="Supplier retains tooling",
        cost_lines=[
            CL("Widget", 5000, 1.20, recurring=False),
            CL("Annual support", 1, 9000, recurring=True),
        ],
        implementation_cost=6000,
        annual_ops_cost=3500,
        annual_maintenance_cost=2500,
        disposal_cost=2500,
        sources=["Borealis email 2026-06-15"],
        attrs={
            "incoterm": "EXW",
            "part_number": "WID-100",
            "revision": "B",
            "auto_renew": True,
            "liability_cap": "fees paid",
        },
    )
    C = Supplier(
        name="Crest Supply",
        scores={
            "Technical Fit & Quality": {
                "Spec compliance": {"score": 8, "evidence": "full compliance"},
                "Quality system": {"score": 8, "evidence": "ISO 9001"},
            },
            "Commercial Terms & Risk": {
                "Terms": {"score": 6, "evidence": "Net 30"},
                "Termination": {"score": 8, "evidence": "90d, no auto-renew"},
            },
            "Cost & TCO": {"Unit price": {"score": 7, "evidence": "$2.10/kg"}},
            "Delivery / Lead Time / Capacity": {
                "Lead time": {"score": 7, "evidence": "18 days"}
            },
            "Compliance / ESG / Reputation": {
                "ESG": {"score": 8, "evidence": "EcoVadis Gold"}
            },
        },
        payment_terms_days=30,
        price_validity_days=90,
        price_escalation_pct=2.0,
        warranty_months=36,
        lead_time_days=18,
        iso9001=True,
        auto_renew=False,
        auto_renew_notice_days=90,
        termination_clause="90d, no auto-renew",
        ip_ownership="Buyer owns tooling",
        cost_lines=[
            CL("Widget", 5000, 2.10, recurring=False),
            CL("Annual support", 1, 10000, recurring=True),
        ],
        implementation_cost=7000,
        annual_ops_cost=3800,
        annual_maintenance_cost=2800,
        disposal_cost=2000,
        sources=["Crest proposal CR-88"],
        attrs={
            "incoterm": "DDP",
            "part_number": "WID-100",
            "revision": "C",
            "governing_law": "New York",
            "liability_cap": "fees in 12 months",
        },
    )
    return ProcurementAnalysis([A, B, C], years=3)


def run_demo(outdir: Optional[Path] = None) -> Path:
    """Write demo report (+ expert panel) under outdir; return report path."""
    outdir = Path(outdir or Path(".nexus_state") / "procurement_demo")
    outdir.mkdir(parents=True, exist_ok=True)
    an = build_demo_analysis()
    sc1 = an.scenario("Best case: -10% negotiated", price_mult=0.90)
    sc2 = an.scenario(
        "Worst case: +14d delay, 8% escalation",
        lead_delta_days=14,
        escalation_override=8.0,
    )
    report = an.full_report_md(baseline_name="Crest Supply", scenarios=[sc1, sc2])

    panel = ExpertPanel()
    panel.review(an.suppliers, reference={"part_number": "WID-100", "revision": "C"})
    expert_md = panel.report_md()

    ranked = an.ranked()
    winner = ranked[0][0].name
    header = (
        f"# Procurement Intelligence Demo (NEXUS)\n\n"
        f"**Synthetic quotes only** — replace with real Supplier objects from your RFQ.\n\n"
        f"**Engine rank #1:** {winner} ({ranked[0][1]:.2f}/10)\n\n"
        f"Persona prompt: `docs/agents/PROCUREMENT.md`\n\n---\n\n"
    )
    full = header + report + "\n\n## Expert panel\n\n" + expert_md
    path = outdir / "report.md"
    path.write_text(full, encoding="utf-8")

    # optional charts
    try:
        from .engine import HAS_MPL

        if HAS_MPL:
            plots = outdir / "plots"
            plots.mkdir(exist_ok=True)
            an.weighted_bar().savefig(plots / "weighted_bar.png", dpi=120)
            an.radar_chart().savefig(plots / "radar.png", dpi=120)
            an.tco_waterfall(winner).savefig(plots / "tco_waterfall.png", dpi=120)
            import matplotlib.pyplot as plt

            plt.close("all")
    except Exception:
        pass

    return path
