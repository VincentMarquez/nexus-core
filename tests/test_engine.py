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
