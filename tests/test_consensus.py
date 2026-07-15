"""P1.3 multi-grader consensus — independent findings + trust weights."""

from pathlib import Path

from nexus import DurableEngine, Settings, Task
from nexus.agents import AgentPanel
from nexus.consensus import (
    SCHEMA,
    AgentTrust,
    ConsensusJudge,
    Finding,
    aggregate_findings,
    apply_lens,
    evidence_base_dims,
    pick_graders,
    score_from_dims,
)
from nexus.engine import TaskStatus
from nexus.steps import StepPolicy


def test_evidence_and_lenses_diverge(tmp_path: Path):
    art = tmp_path / "a.txt"
    art.write_text("DEMO_OK\n", encoding="utf-8")
    step = StepPolicy.default().get(5)  # implement
    task = {"success_criteria": ["artifact contains DEMO_OK"]}
    out = {"artifacts": [str(art)], "pass_fail": "pass"}
    base = evidence_base_dims(step=step, task=task, output=out)
    adv = apply_lens(base, "adversary")
    tester = apply_lens(base, "tester")
    # Adversary is harsher on criteria; tester boosts artifact dim
    assert adv["meets_success_criteria"] <= base["meets_success_criteria"]
    assert tester["artifact_actually_produced"] >= base["artifact_actually_produced"]
    assert score_from_dims(adv) <= score_from_dims(tester) + 0.2


def test_pick_graders_cross_vendor():
    panel = AgentPanel.demo()
    graders = pick_graders(panel, implementer="implementer", max_graders=3)
    assert len(graders) >= 2
    assert "implementer" not in graders
    # Prefer different vendors when available
    imp_v = panel.vendor_of["implementer"]
    assert any(panel.vendor_of.get(g) != imp_v for g in graders)


def test_aggregate_weighted_majority():
    findings = [
        Finding(
            grader="reviewer",
            vendor="anthropic",
            decision="pass",
            score=0.85,
            dims={
                "meets_success_criteria": 0.9,
                "correctness_evidence": 0.9,
                "artifact_actually_produced": 1.0,
                "no_banned_approach": 1.0,
                "coherence": 0.8,
            },
            weight=1.0,
        ),
        Finding(
            grader="adversary",
            vendor="xai",
            decision="pass",
            score=0.78,
            dims={
                "meets_success_criteria": 0.7,
                "correctness_evidence": 0.8,
                "artifact_actually_produced": 1.0,
                "no_banned_approach": 1.0,
                "coherence": 0.7,
            },
            weight=1.25,
        ),
        Finding(
            grader="tester",
            vendor="openai",
            decision="revise",
            score=0.55,
            dims={
                "meets_success_criteria": 0.5,
                "correctness_evidence": 0.5,
                "artifact_actually_produced": 1.0,
                "no_banned_approach": 1.0,
                "coherence": 0.5,
            },
            weight=1.0,
        ),
    ]
    v = aggregate_findings(
        findings,
        implementer="implementer",
        implementer_vendor="openai",
        min_graders=2,
    )
    assert v.schema == SCHEMA
    assert v.n_graders == 3
    assert v.decision in {"pass", "revise", "fail"}
    assert 0.0 <= v.score <= 1.0
    assert v.agreement_ratio > 0
    assert sum(v.counts.values()) >= v.n_graders  # n + signals
    d = v.to_dict()
    assert d["consensus"] is True
    assert len(d["findings"]) == 3
    assert any(f["signal"] for f in d["findings"])


def test_consensus_judge_evaluate(tmp_path: Path):
    art = tmp_path / "ok.txt"
    art.write_text("DEMO_OK\n", encoding="utf-8")
    panel = AgentPanel.demo()
    judge = ConsensusJudge(panel, min_graders=2, max_graders=3)
    step = StepPolicy.default().get(6)  # test
    task = {"success_criteria": ["artifact contains DEMO_OK"], "objective": "x"}
    out = {"pass_fail": "pass", "evidence": [str(art)]}
    v = judge.evaluate(step=step, task=task, output=out, implementer="implementer")
    assert v.n_graders >= 2
    assert v.decision in {"pass", "revise"}
    assert v.score >= 0.45
    assert not v.degraded
    assert len(v.findings) == v.n_graders
    # Adaptive trust updated
    assert judge.trust.weight_of("reviewer") > 0


def test_agent_trust_nudge():
    t = AgentTrust.default()
    before = t.weight_of("reviewer")
    t.record_outcome("reviewer", agreed=True)
    assert t.weight_of("reviewer") >= before
    t.record_outcome("reviewer", agreed=False)
    # Still bounded
    assert 0.2 <= t.weight_of("reviewer") <= 1.8


def test_engine_consensus_journal_and_export(tmp_path: Path):
    settings = Settings(
        state_dir=tmp_path / "state",
        autonomy=False,
        consensus_judge=True,
        consensus_min_graders=2,
        consensus_max_graders=3,
    )
    engine = DurableEngine(settings=settings, auto_approve=True)
    assert isinstance(engine.judge, ConsensusJudge)
    task = Task(
        task_id="cons1",
        objective="consensus demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed

    events = engine.events("cons1")
    cons = [e for e in events if e.get("event") == "consensus"]
    assert cons, "expected consensus journal events"
    for e in cons:
        assert e.get("n_graders", 0) >= 1
        assert e.get("graders")

    # Step outputs carry multi-grader findings
    found_verdict = False
    for out in task.outputs.values():
        if not isinstance(out, dict):
            continue
        v = out.get("_verdict") or {}
        if v.get("findings"):
            found_verdict = True
            assert v.get("schema") == SCHEMA or v.get("consensus") is True
            break
    assert found_verdict

    pack = engine.consensus("cons1")
    assert pack["found"] is True
    assert pack["schema"] == SCHEMA
    assert pack["n_rounds"] >= 1
    assert pack["enabled"] is True
    assert pack["totals"]["avg_agreement_ratio"] is not None


def test_engine_can_disable_consensus(tmp_path: Path):
    settings = Settings(
        state_dir=tmp_path / "state",
        autonomy=False,
        consensus_judge=False,
    )
    engine = DurableEngine(settings=settings, auto_approve=True)
    from nexus.judge import RubricJudge

    assert isinstance(engine.judge, RubricJudge)
    task = Task(
        task_id="single1",
        objective="single judge",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task, max_steps=3)
    assert task.status == TaskStatus.running
    cons = [e for e in engine.events("single1") if e.get("event") == "consensus"]
    assert not cons
