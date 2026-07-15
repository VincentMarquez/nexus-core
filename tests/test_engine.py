from pathlib import Path

from nexus import DurableEngine, Settings, Task
from nexus.agents import AgentPanel, MockAgent
from nexus.engine import TaskStatus
from nexus.steps import StepDef, StepPolicy


def test_full_pipeline_completes(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="t1",
        objective="demo",
        success_criteria=["artifact contains DEMO_OK"],
        namespace="proj/demo",
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    assert task.current_step == 10
    assert (tmp_path / "state" / "tasks" / "t1.json").exists()


def test_resume_after_partial(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="t2",
        objective="demo resume",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task, max_steps=4)  # complete through step 4 only... wait
    # max_steps means stop when step.number > current + max_steps at start
    # After 0 completed, max_steps=4 allows steps 1..4
    assert task.current_step == 4
    assert task.status == TaskStatus.running
    task = engine.resume("t2")
    assert task.status == TaskStatus.completed
    assert task.current_step == 10


def test_autonomy_blocks_auto_created(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings)
    task = Task(task_id="auto1", objective="x", meta={"auto_created": True})
    task = engine.run(task)
    assert task.status == TaskStatus.failed
    assert "autonomy" in task.meta.get("error", "")


def test_handoff_events_when_agent_changes(tmp_path: Path):
    """Swarm-style handoff journal rows appear when resolve() switches agents."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="ho1",
        objective="handoff demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    events = engine.events("ho1")
    handoffs = [e for e in events if e.get("event") == "handoff"]
    assert handoffs, "expected at least one agent handoff in default pipeline"
    for h in handoffs:
        assert h.get("from_agent")
        assert h.get("to_agent")
        assert h["from_agent"] != h["to_agent"]


def test_journal_context_on_resume(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="jc1",
        objective="journal context",
        success_criteria=["artifact contains DEMO_OK"],
    )
    engine.run(task, max_steps=3)
    blk = engine.journal_context("jc1", limit=5)
    assert "RECENT TASK JOURNAL" in blk
    assert "step_start" in blk or "step_complete" in blk
    # limit 0 disables
    assert engine.journal_context("jc1", limit=0) == ""


def test_review_veto_fails_closed(tmp_path: Path):
    """Edict-style review reject hard-fails the task and records a veto event."""

    class RejectReviewer(MockAgent):
        def run(self, prompt: str, *, step, task):
            if step.name == "review":
                return {"findings": ["blocker"], "severity": "high", "verdict": "reject"}
            return super().run(prompt, step=step, task=task)

    panel = AgentPanel.demo()
    panel.agents["reviewer"] = RejectReviewer(name="reviewer", vendor="anthropic")
    panel.vendor_of["reviewer"] = "anthropic"

    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, panel=panel, auto_approve=True)
    task = Task(
        task_id="veto1",
        objective="should be vetoed",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.failed
    assert "veto" in task.meta.get("error", "").lower() or "reject" in task.meta.get("error", "")
    events = engine.events("veto1")
    assert any(e.get("event") == "veto" for e in events)
    assert any(e.get("event") == "failed" for e in events)
    # failed at review step (6), after implement+test
    assert task.current_step < 6 or 6 in task.outputs


def test_step_complete_records_why(tmp_path: Path):
    """Judge rationale is journaled as why on step_complete (CEMA audit)."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="why1",
        objective="why field demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task, max_steps=3)
    completes = [e for e in engine.events("why1") if e.get("event") == "step_complete"]
    assert completes, "expected step_complete events"
    # at least one complete should carry decision and/or why from the judge
    assert any(e.get("decision") for e in completes)
    # why may be empty for pure structural steps, but key must exist on judged steps
    with_why_key = [e for e in completes if "why" in e]
    assert with_why_key, "step_complete should include why field"


def test_replay_timeline_and_explain(tmp_path: Path):
    """replay() normalizes journal; explain() builds causal decision chain."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="rx1",
        objective="replay explain demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed

    timeline = engine.replay("rx1")
    assert timeline, "replay should return journal rows"
    assert timeline[0]["i"] == 0
    assert "event" in timeline[0]
    # completed marker present
    assert any(e.get("event") == "completed" for e in timeline)
    # handoff rows keep from/to
    handoff_rows = [e for e in timeline if e.get("event") == "handoff"]
    if handoff_rows:
        assert handoff_rows[0].get("from_agent")
        assert handoff_rows[0].get("to_agent")

    # limit tail works via events() path
    short = engine.replay("rx1", limit=3)
    assert len(short) <= 3

    rep = engine.explain("rx1")
    assert rep["found"] is True
    assert rep["status"] == "completed"
    assert rep["task_id"] == "rx1"
    assert rep["n_events"] >= 1
    assert rep["steps"], "explain should list completed steps"
    assert "COMPLETED" in rep["story"]
    # steps carry agent + decision when judged
    judged = [s for s in rep["steps"] if s.get("decision")]
    assert judged, "expected at least one judged step with decision"

    missing = engine.explain("does-not-exist")
    assert missing["found"] is False


def test_step_complete_score_tokens_and_cost(tmp_path: Path):
    """P3: judge score + token estimates journaled; cost() rolls them up."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="cost1",
        objective="cost rollup demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    assert int(task.meta.get("tokens_total") or 0) > 0

    completes = [e for e in engine.events("cost1") if e.get("event") == "step_complete"]
    assert completes
    with_tokens = [e for e in completes if e.get("tokens")]
    assert with_tokens, "step_complete should carry tokens"
    with_score = [e for e in completes if e.get("score") is not None]
    assert with_score, "step_complete should carry judge score"
    # value-system thresholds present on judged steps
    with_thr = [e for e in completes if isinstance(e.get("thresholds"), dict)]
    assert with_thr
    thr = with_thr[0]["thresholds"]
    assert thr.get("pass") == 0.7
    assert thr.get("revise") == 0.45

    rep = engine.cost("cost1")
    assert rep["found"] is True
    assert rep["total_tokens"] > 0
    assert rep["request_count"] >= 1
    assert rep["by_agent"]
    assert rep["avg_score"] is not None
    assert rep["thresholds"]["pass"] == 0.7

    explained = engine.explain("cost1")
    assert explained["cost"]["total_tokens"] == rep["total_tokens"]
    assert explained["cost"]["avg_score"] == rep["avg_score"]

    missing = engine.cost("nope")
    assert missing["found"] is False
