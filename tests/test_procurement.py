from nexus.procurement import (
    build_demo_analysis,
    run_demo,
    ExpertPanel,
    ProcurementAnalysis,
)


def test_demo_ranks_three_suppliers():
    an = build_demo_analysis()
    ranked = an.ranked()
    assert len(ranked) == 3
    assert all(0 <= score <= 10 for _, score in ranked)
    md = an.full_report_md(baseline_name="Crest Supply")
    assert "Weighted" in md or "Scorecard" in md or "TCO" in md
    assert "Acme" in md


def test_tco_and_policy():
    an = build_demo_analysis()
    t = an.tco(an.suppliers[0])
    assert t["TOTAL TCO"] > 0
    flags = an.policy_flags()
    assert "Borealis Mfg" in flags  # long lead / no ISO likely flagged


def test_expert_panel():
    an = build_demo_analysis()
    panel = ExpertPanel()
    findings = panel.review(
        an.suppliers, reference={"part_number": "WID-100", "revision": "C"}
    )
    assert isinstance(findings, list)
    md = panel.report_md()
    assert "Expert Panel" in md


def test_run_demo_writes_report(tmp_path):
    path = run_demo(tmp_path / "out")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Procurement" in text
    assert "Expert panel" in text
