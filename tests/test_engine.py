from pathlib import Path

from nexus import DurableEngine, Settings, Task
from nexus.engine import TaskStatus


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
