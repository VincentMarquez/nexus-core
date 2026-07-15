from pathlib import Path

from nexus.agents import AgentPanel
from nexus.judge import (
    PASS_THRESHOLD,
    REVISE_THRESHOLD,
    RubricJudge,
    decision_thresholds,
)
from nexus.steps import StepPolicy


def test_judge_passes_with_evidence(tmp_path: Path):
    art = tmp_path / "a.txt"
    art.write_text("DEMO_OK\n", encoding="utf-8")
    panel = AgentPanel.demo()
    judge = RubricJudge(panel)
    step = StepPolicy.default().get(5)
    task = {"success_criteria": ["artifact contains DEMO_OK"], "objective": "x"}
    out = {"pass_fail": "pass", "evidence": [str(art)], "stdout": "ok"}
    v = judge.evaluate(step=step, task=task, output=out, implementer="implementer")
    assert v.decision in {"pass", "revise"}
    assert v.score >= 0.45
    # cross-vendor preferred: implementer=openai mock, reviewer=anthropic
    assert v.judge_agent in panel.agents
    # value-system thresholds are explicit for audit
    assert v.thresholds == decision_thresholds()
    assert v.thresholds["pass"] == PASS_THRESHOLD
    assert v.thresholds["revise"] == REVISE_THRESHOLD
    d = v.to_dict()
    assert "thresholds" in d
