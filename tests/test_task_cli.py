"""CLI operator surface: nexus task list|events|show."""

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
