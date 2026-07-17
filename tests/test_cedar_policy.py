"""Cedar policy-as-code gate (arXiv 2606.26649) — offline subset + promote."""

from nexus.cedar_policy import (
    SCHEMA,
    CedarDecision,
    PolicyStatement,
    authorize,
    default_promote_cedar_text,
    default_promote_policies,
    evaluate_policies,
    make_request,
    parse_cedar_text,
    resource_from_consensus,
    validate_promote,
)
from nexus.consensus import (
    ConsensusVerdict,
    Finding,
    aggregate_findings,
    promote_decision,
    validate_promote as consensus_validate_promote,
)
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


def test_schema_and_default_policies_text():
    text = default_promote_cedar_text()
    assert SCHEMA.split("/")[0] in text or "cedar" in text
    assert "permit" in text and "forbid" in text
    assert 'Action::"promote"' in text
    pols = default_promote_policies()
    assert any(p.effect == "forbid" for p in pols)
    assert any(p.effect == "permit" for p in pols)


def test_forbid_beats_permit():
    policies = [
        PolicyStatement(
            effect="permit",
            action="promote",
            policy_id="allow-all",
            when=[],
        ),
        PolicyStatement(
            effect="forbid",
            action="promote",
            policy_id="no-fail",
            when=[("resource.decision", "==", "fail")],
        ),
    ]
    req = make_request(
        principal="reviewer",
        action="promote",
        resource={"decision": "fail", "score": 0.9},
    )
    d = evaluate_policies(policies, req)
    assert d.allowed is False
    assert d.decision == "forbid"
    assert "no-fail" in d.matched


def test_default_deny_without_permit():
    policies = [
        PolicyStatement(
            effect="forbid",
            action="promote",
            when=[("resource.decision", "==", "fail")],
        ),
    ]
    d = authorize(
        principal="r",
        action="promote",
        resource={"decision": "revise", "score": 0.5},
        policies=policies,
    )
    assert d.allowed is False
    assert d.decision == "deny_default"


def test_validate_promote_healthy_pass():
    verdict = {
        "decision": "pass",
        "score": 0.88,
        "agreement_ratio": 0.9,
        "degraded": False,
        "n_graders": 3,
    }
    d = validate_promote(verdict, principal="consensus")
    assert isinstance(d, CedarDecision)
    assert d.allowed is True
    assert d.decision == "permit"
    assert d.schema == SCHEMA


def test_validate_promote_forbids_fail_and_degraded():
    fail = validate_promote(
        {"decision": "fail", "score": 0.9, "agreement_ratio": 1.0, "degraded": False, "n_graders": 3}
    )
    assert fail.allowed is False
    deg = validate_promote(
        {"decision": "pass", "score": 0.9, "agreement_ratio": 1.0, "degraded": True, "n_graders": 1}
    )
    assert deg.allowed is False
    low = validate_promote(
        {"decision": "pass", "score": 0.4, "agreement_ratio": 1.0, "degraded": False, "n_graders": 3}
    )
    assert low.allowed is False


def test_parse_cedar_text_roundtrip():
    text = """
    // sample
    forbid (
      principal,
      action == Action::"promote",
      resource
    ) when { resource.decision == "fail" };

    permit (
      principal,
      action == Action::"promote",
      resource
    ) when {
      resource.decision == "pass" &&
      resource.score >= 0.7
    };
    """
    stmts = parse_cedar_text(text)
    assert len(stmts) == 2
    assert stmts[0].effect == "forbid"
    assert stmts[1].effect == "permit"
    d = authorize(
        principal="x",
        resource={"decision": "pass", "score": 0.8},
        policies=stmts,
    )
    assert d.allowed is True


def test_aggregate_attaches_cedar_gate():
    findings = [
        _pass_finding("reviewer", 0.9, 1.0),
        _pass_finding("adversary", 0.85, 1.25),
        _pass_finding("tester", 0.8, 1.0),
    ]
    v = aggregate_findings(
        findings,
        implementer="implementer",
        implementer_vendor="openai",
        min_graders=2,
    )
    assert isinstance(v, ConsensusVerdict)
    assert v.promote_allowed is True
    assert isinstance(v.cedar_policy, dict)
    assert v.cedar_policy.get("allowed") is True
    d = v.to_dict()
    assert d["promote_allowed"] is True
    assert d["cedar_policy"]["schema"] == SCHEMA


def test_promote_decision_audit_blob():
    findings = [
        _pass_finding("reviewer", 0.9),
        _pass_finding("adversary", 0.88, 1.25),
    ]
    v = aggregate_findings(
        findings,
        implementer="implementer",
        implementer_vendor="openai",
        min_graders=2,
    )
    report = promote_decision(v, principal="reviewer", min_graders=2)
    assert report["schema"] == "nexus.consensus.promote/v1"
    assert report["ok"] is True
    assert report["cedar_schema"] == SCHEMA
    assert "permit" in (report.get("policy_text_preview") or "")


def test_consensus_validate_promote_alias():
    thr = decision_thresholds()
    v = ConsensusVerdict(
        decision="pass",
        score=0.9,
        dims={
            "meets_success_criteria": 0.9,
            "correctness_evidence": 0.9,
            "artifact_actually_produced": 1.0,
            "no_banned_approach": 1.0,
            "coherence": 0.9,
        },
        judge_agent="consensus",
        judge_vendor="multi",
        implementer="implementer",
        implementer_vendor="openai",
        degraded=False,
        rationale="test",
        thresholds=thr,
        findings=[],
        agreement_ratio=1.0,
        n_graders=3,
    )
    d = consensus_validate_promote(v, principal="consensus", min_graders=2)
    assert d.allowed is True


def test_resource_from_consensus_single_judge_shape():
    res = resource_from_consensus(
        {"decision": "pass", "score": 0.8}  # no n_graders → treated as single
    )
    assert res["type"] == "ConsensusDecision"
    assert res["n_graders"] == 1
    assert res["agreement_ratio"] == 1.0
