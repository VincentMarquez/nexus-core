"""CLI operator surface: nexus task list|events|show|replay|explain."""

from pathlib import Path

from nexus import DurableEngine, Settings, Task
from nexus.cli import main
from nexus.engine import TaskStatus


def test_task_list_and_events_cli(tmp_path: Path, capsys):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="cli1",
        objective="cli journal demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task, max_steps=3)
    assert task.status == TaskStatus.running

    rc = main(["task", "list", "--state-dir", str(settings.state_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cli1" in out
    assert "running" in out
    assert "LAST" in out  # operator board columns

    rc = main(
        [
            "task",
            "events",
            "cli1",
            "--state-dir",
            str(settings.state_dir),
            "--limit",
            "20",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "events for cli1" in out
    assert "step_start" in out or "step_complete" in out

    rc = main(
        [
            "task",
            "events",
            "cli1",
            "--state-dir",
            str(settings.state_dir),
            "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert '"event"' in out

    rc = main(["task", "show", "cli1", "--state-dir", str(settings.state_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cli1" in out
    assert "cli journal demo" in out


def test_task_events_missing(tmp_path: Path, capsys):
    rc = main(["task", "events", "nope", "--state-dir", str(tmp_path / "empty")])
    assert rc == 1


def test_task_replay_and_explain_cli(tmp_path: Path, capsys):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="cli2",
        objective="cli replay explain",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    state = str(settings.state_dir)

    rc = main(["task", "replay", "cli2", "--state-dir", state])
    assert rc == 0
    out = capsys.readouterr().out
    assert "replay cli2" in out
    assert "step_start" in out or "step_complete" in out or "completed" in out

    rc = main(["task", "replay", "cli2", "--state-dir", state, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"event"' in out

    rc = main(["task", "explain", "cli2", "--state-dir", state])
    assert rc == 0
    out = capsys.readouterr().out
    assert "explain cli2" in out
    assert "story:" in out
    assert "completed" in out.lower() or "COMPLETED" in out

    rc = main(["task", "explain", "cli2", "--state-dir", state, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"task_id"' in out
    assert "cli2" in out

    rc = main(["task", "explain", "missing", "--state-dir", state])
    assert rc == 1


def test_task_cost_cli(tmp_path: Path, capsys):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="cli3",
        objective="cli cost rollup",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    state = str(settings.state_dir)

    rc = main(["task", "cost", "cli3", "--state-dir", state])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cost cli3" in out
    assert "total_tokens:" in out
    assert "by_agent:" in out or "steps:" in out

    rc = main(["task", "cost", "cli3", "--state-dir", state, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"task_id"' in out
    assert "cli3" in out
    assert "total_tokens" in out

    rc = main(["task", "cost", "missing", "--state-dir", state])
    assert rc == 1
