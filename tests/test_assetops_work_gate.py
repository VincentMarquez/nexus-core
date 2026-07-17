"""Cedar × AssetOpsBench work promote gate (arXiv 2606.26649 × IBM/AssetOpsBench)."""

from __future__ import annotations

from nexus import assetops_planner as aop
from nexus import assetops_work_gate as awg
from nexus import multi_llm_agent as mla
from nexus.cedar_policy import SCHEMA as CEDAR_SCHEMA, CedarDecision
from nexus.consensus import ConsensusVerdict, Finding, aggregate_findings, promote_decision
from nexus.judge import decision_thresholds


def _pass_finding(grader: str = "reviewer", score: float = 0.85, weight: float = 1.0) -> Finding:
    return Finding(
        grader=grader,
        vendor="xai",
        decision="pass",
        score=score,
        dims={
            "meets_success_criteria": score,
            "correctness_evidence": score,
            "artifact_actually_produced": 1.0,
            "no_banned_approach": 1.0,
            "coherence": score,
        },
        weight=weight,
    )


def test_schema_and_policy_text():
    text = awg.default_assetops_promote_cedar_text()
    assert awg.SCHEMA.split("/")[0] in text or "assetops" in text.lower()
    assert "forbid" in text and "permit" in text
    assert "has_iot" in text or "forbid-write-without-iot" in text or "has_write" in text
    pols = awg.default_assetops_promote_policies()
    ids = {p.policy_id for p in pols}
    assert "forbid-unready-plan" in ids
    assert "forbid-write-without-iot" in ids
    assert "forbid-write-without-fmsr" in ids
    assert "permit-healthy-domain-pass" in ids


def test_resource_from_diagnostic_plan():
    plan = aop.diagnostic_workflow_plan(
        "diagnose chiller failure",
        include_vibration=True,
        include_workorder_write=False,
    )
    res = awg.resource_from_work(plan)
    assert res["type"] == "AssetOpsWorkDecision"
    assert res["plan_ready"] is True
    assert res["n_steps"] >= 5
    assert res["has_iot"] is True
    assert res["has_fmsr"] is True
    assert res["has_tsfm"] is True
    assert res["has_wo"] is True
    assert res["has_write"] is False
    assert res["workflow"] == "diagnostic"
    assert res["min_domains_met"] is True
    assert aop.SERVER_IOT in res["servers"]
    assert res["source_pattern"] == aop.SOURCE_PATTERN


def test_write_tools_detected():
    plan = aop.diagnostic_workflow_plan(
        "diagnose and raise work order",
        include_workorder_write=True,
    )
    writes = awg.write_tools_from_plan(plan)
    assert any("create_workorder" in w for w in writes)
    res = awg.resource_from_work(plan)
    assert res["has_write"] is True
    assert res["has_iot"] is True
    assert res["has_fmsr"] is True


def test_promote_healthy_diagnostic_allowed():
    plan = aop.diagnostic_workflow_plan(
        "diagnose chiller asset failure and list work orders",
        include_vibration=True,
    )
    d = awg.validate_work_promote(plan)
    assert isinstance(d, CedarDecision)
    assert d.allowed is True
    assert d.decision == "permit"
    report = awg.promote_work_decision(plan)
    assert report["schema"] == awg.PROMOTE_SCHEMA
    assert report["ok"] is True
    assert report["paper"] == awg.PAPER
    assert report["source_pattern"] == awg.SOURCE_PATTERN
    assert report["n_servers_touched"] >= 3


def test_promote_write_with_evidence_allowed():
    plan = aop.diagnostic_workflow_plan(
        "diagnose and create work order",
        include_workorder_write=True,
    )
    report = awg.promote_work_decision(plan)
    assert report["ok"] is True
    assert report["has_write"] is True


def test_forbid_write_without_iot():
    """Bare work-order create without IoT/FMSR evidence must deny."""
    plan = mla.ToolPlan(
        task="blind work order",
        steps=[
            mla.PlanStep(
                id=1,
                tool=aop.tool_id("wo", "create_workorder"),
                args={
                    "server": "wo",
                    "domain_tool": "create_workorder",
                    "title": "blind",
                },
                rationale="unsafe write",
            )
        ],
        status=mla.STATUS_DRAFT,
        planner="test",
        tools_available=[aop.tool_id("wo", "create_workorder")],
        meta={"workflow": "custom", "n_servers_touched": 1},
    )
    mla.mark_ready(
        plan,
        allowed_tools=[aop.tool_id("wo", "create_workorder")],
        require_steps=True,
    )
    res = awg.resource_from_work(plan)
    assert res["has_write"] is True
    assert res["has_iot"] is False
    d = awg.validate_work_promote(plan)
    assert d.allowed is False
    assert d.decision == "forbid"
    assert any("iot" in m or "write" in m for m in d.matched) or any(
        "iot" in r.lower() or "write" in r.lower() for r in d.reasons
    )


def test_forbid_unready_plan():
    plan = mla.ToolPlan(
        task="not ready",
        steps=[
            mla.PlanStep(
                id=1,
                tool=aop.tool_id("iot", "sites"),
                args={"server": "iot"},
            )
        ],
        status=mla.STATUS_DRAFT,  # not ready
        planner="test",
        meta={"workflow": "custom"},
    )
    d = awg.validate_work_promote(plan)
    assert d.allowed is False
    assert "forbid-unready-plan" in d.matched or d.decision in {"forbid", "deny_default"}


def test_forbid_thin_diagnostic():
    plan = mla.ToolPlan(
        task="thin diagnostic",
        steps=[
            mla.PlanStep(
                id=1,
                tool=aop.tool_id("utilities", "current_date_time"),
                args={"server": "utilities"},
            ),
            mla.PlanStep(
                id=2,
                tool=aop.tool_id("iot", "sites"),
                args={"server": "iot"},
            ),
        ],
        status=mla.STATUS_DRAFT,
        planner="test",
        meta={"workflow": "diagnostic", "n_servers_touched": 2},
    )
    mla.mark_ready(
        plan,
        allowed_tools=[s.tool for s in plan.steps],
        require_steps=True,
    )
    d = awg.validate_work_promote(plan, min_domains=3)
    assert d.allowed is False
    assert "forbid-thin-diagnostic" in d.matched or d.decision == "forbid"


def test_consensus_hybrid_gate():
    plan = aop.diagnostic_workflow_plan("diagnose pump", include_vibration=True)
    findings = [
        _pass_finding("reviewer", 0.9),
        _pass_finding("adversary", 0.88, 1.25),
        _pass_finding("tester", 0.86),
    ]
    v = aggregate_findings(
        findings,
        implementer="implementer",
        implementer_vendor="openai",
        min_graders=2,
    )
    assert v.promote_allowed is True  # plain consensus cedar
    hybrid = awg.consensus_with_work_gate(v, plan, min_graders=2)
    assert hybrid["ok"] is True
    assert hybrid["hybrid"] is True
    assert hybrid["schema"] == awg.PROMOTE_SCHEMA
    assert hybrid["cedar_schema"] == CEDAR_SCHEMA


def test_promote_decision_domain_plan_hook():
    plan = aop.diagnostic_workflow_plan("diagnose motor bearing")
    findings = [
        _pass_finding("reviewer", 0.9),
        _pass_finding("adversary", 0.85, 1.25),
    ]
    v = aggregate_findings(
        findings,
        implementer="implementer",
        implementer_vendor="openai",
        min_graders=2,
    )
    report = promote_decision(v, domain_plan=plan, min_graders=2)
    assert report["ok"] is True
    assert report.get("domain_plan") is True
    assert report.get("hybrid") is True
    assert "servers" in report


def test_promote_decision_fail_verdict_denies_even_with_good_plan():
    plan = aop.diagnostic_workflow_plan("diagnose chiller")
    thr = decision_thresholds()
    v = ConsensusVerdict(
        decision="fail",
        score=0.2,
        dims={d: 0.2 for d in (
            "meets_success_criteria",
            "correctness_evidence",
            "artifact_actually_produced",
            "no_banned_approach",
            "coherence",
        )},
        judge_agent="consensus",
        judge_vendor="multi",
        implementer="implementer",
        implementer_vendor="openai",
        degraded=False,
        rationale="fail test",
        thresholds=thr,
        findings=[],
        agreement_ratio=1.0,
        n_graders=3,
    )
    report = promote_decision(v, domain_plan=plan, min_graders=2)
    assert report["ok"] is False


def test_gate_plan_for_handoff():
    plan = aop.diagnostic_workflow_plan("troubleshoot sensor anomaly")
    report = awg.gate_plan_for_handoff(plan)
    assert report["ok"] is True
    assert report["plan_ready"] is True


def test_plan_and_run_cedar_gate_allows_healthy():
    report = aop.plan_and_run(
        "diagnose chiller asset failure and list work orders",
        use_diagnostic=True,
        cedar_gate=True,
        include_vibration=True,
    )
    assert report["ok"] is True
    assert report.get("work_gate", {}).get("ok") is True
    assert report["phase"] == "run"


def test_plan_and_run_cedar_gate_denies_thin(monkeypatch):
    """Force a thin plan through plan_from_assetops to exercise deny path."""
    thin = mla.ToolPlan(
        task="thin",
        steps=[
            mla.PlanStep(
                id=1,
                tool=aop.tool_id("iot", "sites"),
                args={"server": "iot"},
            )
        ],
        status=mla.STATUS_DRAFT,
        planner="test-thin",
        meta={"workflow": "diagnostic", "n_servers_touched": 1, "schema": aop.SCHEMA},
    )
    mla.mark_ready(thin, allowed_tools=[thin.steps[0].tool], require_steps=True)

    monkeypatch.setattr(
        aop,
        "plan_from_assetops",
        lambda *a, **k: thin,
    )
    report = aop.plan_and_run("thin diagnostic", cedar_gate=True, min_domains=3)
    assert report["ok"] is False
    assert report["error"] == "cedar_work_gate_denied"
    assert report["phase"] == "cedar_gate"
    assert report.get("work_gate", {}).get("ok") is False


def test_cli_check_diagnostic():
    rc = awg.main(["check-diagnostic", "diagnose chiller", "--json"])
    assert rc == 0
    rc2 = awg.main(["policies"])
    assert rc2 == 0
