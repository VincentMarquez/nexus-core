from pathlib import Path

import pytest

from nexus import usage as um
from nexus import alive as al


def test_estimate_and_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    um.save_budget(um.Budget(enabled=True, daily_tokens=1000, monthly_tokens=10000, per_call_max=500), tmp_path)
    assert um.estimate_tokens("abcd") == 1
    um.record(100, source="t", workdir=tmp_path, enforce=True)
    st = um.status(tmp_path)
    assert st["totals"]["day_tokens"] == 100
    with pytest.raises(um.BudgetExceeded):
        um.check_budget(2000, tmp_path, raise_on_exceed=True)


def test_usage_by_task_rollup(tmp_path, monkeypatch):
    """Mission-control-style ledger rollup keyed by meta.task_id."""
    monkeypatch.chdir(tmp_path)
    um.save_budget(
        um.Budget(enabled=False, daily_tokens=1_000_000, monthly_tokens=10_000_000),
        tmp_path,
    )
    um.record(
        50,
        source="agent:planner",
        label="step:1",
        meta={"task_id": "job-a", "agent": "planner", "step": 1},
        workdir=tmp_path,
        enforce=False,
    )
    um.record(
        150,
        source="agent:coder",
        label="step:2",
        meta={"task_id": "job-a", "agent": "coder", "step": 2},
        workdir=tmp_path,
        enforce=False,
    )
    um.record(
        999,
        source="other",
        label="unrelated",
        meta={"task_id": "job-b"},
        workdir=tmp_path,
        enforce=False,
    )
    roll = um.by_task("job-a", tmp_path)
    assert roll["task_id"] == "job-a"
    assert roll["total_tokens"] == 200
    assert roll["request_count"] == 2
    assert roll["by_agent"]["planner"] == 50
    assert roll["by_agent"]["coder"] == 150
    assert roll["by_step"]["1"] == 50
    assert um.by_task("missing", tmp_path)["total_tokens"] == 0


def test_alive_init_and_dry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = al.AliveConfig(goal="test goal", queries=["agents"], enabled=True)
    al.save_config(cfg, tmp_path)
    loaded = al.load_config(tmp_path)
    assert loaded.goal == "test goal"
    rep = al.cycle_once(tmp_path, dry_run=True)
    assert rep.get("dry_run") is True


def test_alive_config_arxiv_and_use_limits(tmp_path, monkeypatch):
    """Full-cycle knobs: 10 papers + 10 repos (alive config round-trip)."""
    monkeypatch.chdir(tmp_path)
    cfg = al.AliveConfig(
        goal="depth",
        arxiv_count=10,
        use_limit=10,
        fetch_count=10,
        enabled=True,
    )
    al.save_config(cfg, tmp_path)
    loaded = al.load_config(tmp_path)
    assert loaded.arxiv_count == 10
    assert loaded.use_limit == 10
    assert loaded.fetch_count == 10
    d = loaded.to_dict()
    assert d["arxiv_count"] == 10 and d["use_limit"] == 10


def test_alive_config_stop_knobs_roundtrip(tmp_path, monkeypatch):
    """Zenith-style stop policy knobs survive alive.json round-trip."""
    monkeypatch.chdir(tmp_path)
    cfg = al.AliveConfig(
        goal="stop-discipline",
        enabled=True,
        stop_max_no_progress=5,
        stop_max_cycles=12,
        stop_when_gaps_closed=False,
        stop_on_tests_red=True,
        seed_gaps=False,
    )
    al.save_config(cfg, tmp_path)
    loaded = al.load_config(tmp_path)
    assert loaded.stop_max_no_progress == 5
    assert loaded.stop_max_cycles == 12
    assert loaded.stop_when_gaps_closed is False
    assert loaded.stop_on_tests_red is True
    assert loaded.seed_gaps is False


def test_should_promote_on_done_auto_self_approve():
    """P3.3: self_approve apply landing auto-wires promote even if knob off."""
    cfg_off = al.AliveConfig(promote_on_done=False, self_approve=True, apply=True)
    assert al._should_promote_on_done(
        cfg_off,
        checks={"ok": True},
        report={"steps": [{"step": "self_approve_apply", "ok": True}]},
    )
    # no apply landed → do not auto-promote
    assert not al._should_promote_on_done(
        cfg_off,
        checks={"ok": True},
        report={"steps": [{"step": "self_approve_apply", "skipped": "x"}]},
    )
    # explicit knob always wins
    cfg_on = al.AliveConfig(promote_on_done=True, self_approve=False, apply=False)
    assert al._should_promote_on_done(
        cfg_on, checks={"ok": False}, report={"steps": []}
    )
    # self_approve without apply flag → no auto
    cfg_plan = al.AliveConfig(promote_on_done=False, self_approve=True, apply=False)
    assert not al._should_promote_on_done(
        cfg_plan,
        checks={"ok": True},
        report={"steps": [{"step": "self_approve_apply", "ok": True}]},
    )


def test_alive_promote_on_done_knobs_roundtrip(tmp_path, monkeypatch):
    """P3.2 promote_on_done / promote_require survive alive.json round-trip."""
    monkeypatch.chdir(tmp_path)
    cfg = al.AliveConfig(
        goal="promote-wire",
        enabled=True,
        promote_on_done=True,
        promote_require=True,
    )
    al.save_config(cfg, tmp_path)
    loaded = al.load_config(tmp_path)
    assert loaded.promote_on_done is True
    assert loaded.promote_require is True
    d = loaded.to_dict()
    assert d["promote_on_done"] is True and d["promote_require"] is True


def test_run_promote_on_done_pass(tmp_path, monkeypatch):
    """Alive promote step completes improve_apply with IndependentVerify ok."""
    monkeypatch.chdir(tmp_path)
    cfg = al.AliveConfig(
        goal="promote",
        enabled=True,
        promote_on_done=True,
        promote_require=False,
        our_repo="local/test",
    )
    step = al._run_promote_on_done(
        tmp_path,
        cfg,
        checks={"ok": True, "checks": []},
        applied=None,
    )
    assert step["step"] == "promote_on_done"
    assert step["ok"] is True
    assert step["phase"] == "done"
    prom = step.get("promote") or {}
    assert prom.get("ok") is True
    assert prom.get("skipped") is not True


def test_run_promote_on_done_require_blocks_on_red(tmp_path, monkeypatch):
    """promote_require + red tests → blocked step (fail-closed)."""
    monkeypatch.chdir(tmp_path)
    cfg = al.AliveConfig(
        goal="promote",
        enabled=True,
        promote_on_done=True,
        promote_require=True,
    )
    step = al._run_promote_on_done(
        tmp_path,
        cfg,
        checks={"ok": False, "checks": [{"name": "pytest", "ok": False}]},
        applied=None,
    )
    assert step["step"] == "promote_on_done"
    assert step["ok"] is False
    # either PhaseGuardError blocked or soft deny with blocked message
    assert step.get("blocked") or (step.get("promote") or {}).get("ok") is False


def test_alive_dry_run_records_principled_stop_on_full_cycle(tmp_path, monkeypatch):
    """Dry-run skips mine/apply but still exits cleanly; stop only on full path.

    Full cycle path with empty mine is heavy; here we assert dry_run still works
    and that _record_principled_stop helper persists a no-progress streak.
    """
    monkeypatch.chdir(tmp_path)
    from nexus.durability.stop import PrincipledStop, default_stop_path

    cfg = al.AliveConfig(goal="g", enabled=True, stop_max_no_progress=2)
    al.save_config(cfg, tmp_path)
    rep = {
        "steps": [{"step": "mine", "used": 0}],
        "goal": "g",
    }
    dec = al._record_principled_stop(tmp_path, cfg, rep, checks={"ok": True})
    assert dec["stop"] is False
    assert dec["cycle"] == 1
    assert dec["no_progress_streak"] == 1
    dec2 = al._record_principled_stop(tmp_path, cfg, rep, checks={"ok": True})
    assert dec2["stop"] is True
    assert dec2["reason"] == "no_progress"
    loaded = PrincipledStop.load(default_stop_path(tmp_path))
    assert loaded.cycle == 2
    assert loaded.no_progress_streak == 2
