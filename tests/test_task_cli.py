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


def test_task_prov_and_verify_cli(tmp_path: Path, capsys):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="cli4",
        objective="cli prov verify",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    state = str(settings.state_dir)

    rc = main(["task", "prov", "cli4", "--state-dir", state])
    assert rc == 0
    out = capsys.readouterr().out
    assert "provenance cli4" in out
    assert "agents:" in out
    assert "activities:" in out
    assert "relations:" in out or "entities:" in out

    rc = main(["task", "prov", "cli4", "--state-dir", state, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"schema"' in out
    assert "nexus.prov/v1" in out
    assert "cli4" in out

    rc = main(["task", "verify", "cli4", "--state-dir", state])
    assert rc == 0
    out = capsys.readouterr().out
    assert "verify cli4" in out
    assert "OK" in out
    assert "checks:" in out

    rc = main(["task", "verify", "cli4", "--state-dir", state, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"ok"' in out
    assert "true" in out.lower()

    rc = main(["task", "prov", "missing", "--state-dir", state])
    assert rc == 1
    rc = main(["task", "verify", "missing", "--state-dir", state])
    assert rc == 1


def test_task_graph_and_budget_cost_cli(tmp_path: Path, capsys):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="cli5",
        objective="cli graph budget",
        success_criteria=["artifact contains DEMO_OK"],
        meta={"max_tokens": 500_000},  # high enough to complete
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    state = str(settings.state_dir)

    rc = main(["task", "graph", "cli5", "--state-dir", state])
    assert rc == 0
    out = capsys.readouterr().out
    assert "graph cli5" in out
    assert "nodes:" in out
    assert "sequence:" in out or "edges:" in out

    rc = main(["task", "graph", "cli5", "--state-dir", state, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"schema"' in out
    assert "nexus.graph/v1" in out
    assert "cli5" in out

    rc = main(["task", "graph", "cli5", "--state-dir", state, "--mermaid"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "mermaid:" in out
    assert "flowchart" in out

    rc = main(["task", "cost", "cli5", "--state-dir", state])
    assert rc == 0
    out = capsys.readouterr().out
    assert "budget:" in out
    assert "max=500000" in out or "max=500_000" in out or "500000" in out

    rc = main(["task", "graph", "missing", "--state-dir", state])
    assert rc == 1


def test_task_evidence_cli(tmp_path: Path, capsys):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="cli6",
        objective="cli evidence pack",
        success_criteria=["artifact contains DEMO_OK"],
        constraints=["require:tests", "deny:network"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    state = str(settings.state_dir)

    rc = main(["task", "evidence", "cli6", "--state-dir", state])
    assert rc == 0
    out = capsys.readouterr().out
    assert "evidence cli6" in out
    assert "READY" in out or "gates:" in out
    assert "norms:" in out
    assert "require" in out.lower() or "tests" in out

    rc = main(["task", "evidence", "cli6", "--state-dir", state, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"schema"' in out
    assert "nexus.evidence/v1" in out
    assert "cli6" in out

    out_file = tmp_path / "pack.json"
    rc = main(
        [
            "task",
            "evidence",
            "cli6",
            "--state-dir",
            state,
            "--compact",
            "--out",
            str(out_file),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "wrote evidence pack" in out or "written:" in out
    assert out_file.is_file()
    import json as _json

    data = _json.loads(out_file.read_text(encoding="utf-8"))
    assert data["schema"] == "nexus.evidence/v1"
    assert data["task_id"] == "cli6"
    assert data["compact"] is True
    assert data.get("ready") is True

    rc = main(["task", "evidence", "missing", "--state-dir", state])
    assert rc == 1
