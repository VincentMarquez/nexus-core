"""Crash-safe persist helpers + task event journal."""

from pathlib import Path

from nexus.persist import (
    append_jsonl,
    atomic_write_json,
    atomic_write_text,
    event_row,
    read_jsonl,
)
from nexus import DurableEngine, Settings, Task
from nexus.engine import TaskStatus


def test_atomic_write_json_roundtrip(tmp_path: Path):
    p = tmp_path / "nested" / "state.json"
    atomic_write_json(p, {"a": 1, "b": ["x"]})
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert '"a": 1' in text
    # no leftover tmp files
    leftovers = list(tmp_path.rglob("*.tmp"))
    assert leftovers == []


def test_atomic_write_replaces(tmp_path: Path):
    p = tmp_path / "f.txt"
    atomic_write_text(p, "one")
    atomic_write_text(p, "two")
    assert p.read_text(encoding="utf-8") == "two"


def test_jsonl_append_and_read(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    append_jsonl(p, event_row("start", task_id="t1", step=1))
    append_jsonl(p, event_row("done", task_id="t1", step=1, agent="impl"))
    rows = read_jsonl(p)
    assert len(rows) == 2
    assert rows[0]["event"] == "start"
    assert rows[1]["agent"] == "impl"
    assert read_jsonl(p, limit=1)[0]["event"] == "start"
    assert read_jsonl(p, reverse=True, limit=1)[0]["event"] == "done"


def test_engine_atomic_checkpoint_and_journal(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="j1",
        objective="journal demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task, max_steps=3)
    assert task.current_step == 3
    assert task.status == TaskStatus.running
    ckpt = settings.state_dir / "tasks" / "j1.json"
    assert ckpt.is_file()
    events = engine.events("j1")
    assert events
    kinds = [e["event"] for e in events]
    assert "status" in kinds
    assert "step_start" in kinds
    assert "step_complete" in kinds
    assert "checkpoint" in kinds
    # resume finishes pipeline and journal grows
    n_before = len(events)
    task = engine.resume("j1")
    assert task.status == TaskStatus.completed
    events2 = engine.events("j1")
    assert len(events2) > n_before
    assert any(e["event"] == "resume" for e in events2)
    assert any(e["event"] == "completed" for e in events2)
    listed = engine.list_tasks()
    assert listed and listed[0]["task_id"] == "j1"
    assert listed[0]["events"] >= len(events2)


def test_engine_journal_can_disable(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True, journal=False)
    task = Task(task_id="noj", objective="x", success_criteria=["artifact contains DEMO_OK"])
    engine.run(task, max_steps=2)
    assert engine.events("noj") == []
    assert not (settings.state_dir / "tasks" / "noj.events.jsonl").exists()
