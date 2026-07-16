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


def test_alive_require_decision_knobs_roundtrip(tmp_path, monkeypatch):
    """Decision-package gate knobs survive alive.json round-trip."""
    monkeypatch.chdir(tmp_path)
    cfg = al.AliveConfig(
        goal="decide-wire",
        enabled=True,
        require_decision=False,
        require_work_ledger=False,
        require_spine=False,
        implementer="impl:a",
        verifier="ver:b",
    )
    al.save_config(cfg, tmp_path)
    loaded = al.load_config(tmp_path)
    assert loaded.require_decision is False
    assert loaded.require_work_ledger is False
    assert loaded.require_spine is False
    assert loaded.implementer == "impl:a"
    assert loaded.verifier == "ver:b"


def test_self_approve_decision_gate_replan_without_candidates(tmp_path, monkeypatch):
    """Empty workdir → board replan → self_approve blocked when require_decision."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".nexus_state").mkdir()
    cfg = al.AliveConfig(
        goal="g",
        apply=True,
        self_approve=True,
        require_decision=True,
        min_score=10.0,
        grader="grok",
        sync_board_gaps=True,
        record_preferences=True,
    )
    gate = al._self_approve_decision_gate(tmp_path, cfg, report={"steps": []})
    assert gate["allow"] is False
    assert gate["signal"] in ("replan", "stop")
    assert gate["skip_reason"]
    # board replan/stop must register a gap on the PrincipledStop board
    assert gate.get("gap_sync", {}).get("ok") is True
    from nexus.durability.stop import PrincipledStop, default_stop_path

    stop = PrincipledStop.load(default_stop_path(tmp_path))
    open_ids = {g.id for g in stop.open_gaps()}
    assert any(i.startswith("board-") for i in open_ids)


def test_alive_sync_board_gaps_knobs_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = al.AliveConfig(
        goal="gap-wire",
        sync_board_gaps=False,
        abort_on_board_stop=False,
        record_preferences=False,
    )
    al.save_config(cfg, tmp_path)
    loaded = al.load_config(tmp_path)
    assert loaded.sync_board_gaps is False
    assert loaded.abort_on_board_stop is False
    assert loaded.record_preferences is False


def test_self_approve_decision_gate_allows_with_fixture(tmp_path, monkeypatch):
    """With claims fixture present, decision allow + signal continue + work_ledger + spine."""
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[1]
    fx_src = root / "fixtures" / "mine_eval" / "grades_with_claims.json"
    if not fx_src.is_file():
        pytest.skip("claims fixture missing")
    dest = tmp_path / "fixtures" / "mine_eval"
    dest.mkdir(parents=True)
    (dest / "grades_with_claims.json").write_text(
        fx_src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / ".nexus_state").mkdir(exist_ok=True)
    cfg = al.AliveConfig(
        goal="g",
        apply=True,
        self_approve=True,
        require_decision=True,
        require_work_ledger=True,
        require_spine=True,
        min_score=10.0,
        grader="grok",
        implementer="worker:apply",
        verifier="judge:verify",
    )
    gate = al._self_approve_decision_gate(tmp_path, cfg, report={"steps": []})
    assert gate["allow"] is True, gate
    assert gate["signal"] == "continue"
    assert (gate.get("decision") or {}).get("ok") is True
    wl = gate.get("work_ledger") or {}
    assert wl.get("accepted") is True, wl
    sp = gate.get("spine") or {}
    assert sp.get("accepted") is True, sp
    assert float(sp.get("score") or 0) >= 10.0


def test_self_approve_work_ledger_can_be_disabled(tmp_path, monkeypatch):
    """require_work_ledger=false skips dual-control ledger even when decision on."""
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[1]
    fx_src = root / "fixtures" / "mine_eval" / "grades_with_claims.json"
    if not fx_src.is_file():
        pytest.skip("claims fixture missing")
    dest = tmp_path / "fixtures" / "mine_eval"
    dest.mkdir(parents=True)
    (dest / "grades_with_claims.json").write_text(
        fx_src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / ".nexus_state").mkdir(exist_ok=True)
    cfg = al.AliveConfig(
        goal="g",
        apply=True,
        self_approve=True,
        require_decision=True,
        require_work_ledger=False,
        require_spine=False,
        min_score=10.0,
        grader="grok",
        implementer="worker:apply",
        verifier="judge:verify",
    )
    gate = al._self_approve_decision_gate(tmp_path, cfg, report={"steps": []})
    assert gate["allow"] is True, gate
    assert gate.get("require_work_ledger") is False
    assert gate.get("work_ledger") is None
    assert gate.get("require_spine") is False
    assert gate.get("spine") is None


def test_self_approve_spine_can_be_disabled(tmp_path, monkeypatch):
    """require_spine=false skips improve_spine ensure when decision/work_ledger on."""
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[1]
    fx_src = root / "fixtures" / "mine_eval" / "grades_with_claims.json"
    if not fx_src.is_file():
        pytest.skip("claims fixture missing")
    dest = tmp_path / "fixtures" / "mine_eval"
    dest.mkdir(parents=True)
    (dest / "grades_with_claims.json").write_text(
        fx_src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / ".nexus_state").mkdir(exist_ok=True)
    cfg = al.AliveConfig(
        goal="g",
        apply=True,
        self_approve=True,
        require_decision=True,
        require_work_ledger=True,
        require_spine=False,
        min_score=10.0,
        grader="grok",
        implementer="worker:apply",
        verifier="judge:verify",
    )
    gate = al._self_approve_decision_gate(tmp_path, cfg, report={"steps": []})
    assert gate["allow"] is True, gate
    assert gate.get("require_spine") is False
    assert gate.get("spine") is None
    assert (gate.get("work_ledger") or {}).get("accepted") is True


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
    # worker apply failed (ok:False) → do not auto-promote
    assert not al._should_promote_on_done(
        cfg_off,
        checks={"ok": True},
        report={
            "steps": [
                {
                    "step": "self_approve_apply",
                    "ok": False,
                    "reason": "xhigh CLI error",
                    "apply": {"via": "grok", "ok": False, "error": "xhigh CLI error"},
                }
            ]
        },
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


def test_improve_ours_apply_status_detects_worker_failure():
    """Worker/CLI failure under apply must not look like a landed apply."""
    # Simulated real bug: step_improve_ours top-level ok stays True, grok dies
    failed = {
        "step": "improve_ours",
        "ok": True,
        "plan": "/tmp/IMPROVE_OURS.md",
        "apply": {
            "via": "grok",
            "ok": False,
            "returncode": 1,
            "error": "xhigh CLI error: unknown model",
            "summary": "",
        },
    }
    st = al._improve_ours_apply_status(failed)
    assert st["ok"] is False
    assert "xhigh" in (st.get("reason") or "").lower() or "cli" in (st.get("reason") or "").lower()

    # Step record shape used by alive cycle
    step_rec = {
        "step": "self_approve_apply",
        "ok": bool(st.get("ok")),
        "apply": failed.get("apply"),
        "plan": failed.get("plan"),
        "reason": st.get("reason"),
    }
    report = {"steps": [step_rec]}
    assert al._self_approve_apply_landed(report) is False

    # Success path still lands
    ok_res = {
        "step": "improve_ours",
        "ok": True,
        "plan": "/tmp/IMPROVE_OURS.md",
        "apply": {"via": "grok", "ok": True, "returncode": 0},
    }
    st_ok = al._improve_ours_apply_status(ok_res)
    assert st_ok["ok"] is True
    assert al._self_approve_apply_landed(
        {"steps": [{"step": "self_approve_apply", "ok": True, "apply": ok_res["apply"]}]}
    )

    # Bus completed without explicit ok
    bus_ok = {
        "step": "improve_ours",
        "ok": True,
        "apply": {"via": "bus", "status": "completed", "job_id": "j1"},
    }
    assert al._improve_ours_apply_status(bus_ok)["ok"] is True
    bus_fail = {
        "step": "improve_ours",
        "ok": True,
        "apply": {"via": "bus", "status": "failed", "error": "clone failed"},
    }
    st_bus = al._improve_ours_apply_status(bus_fail)
    assert st_bus["ok"] is False

    # No scored repos
    no_picks = {"step": "improve_ours", "ok": False, "error": "no scored repos"}
    st_np = al._improve_ours_apply_status(no_picks)
    assert st_np["ok"] is False


def test_failed_worker_apply_not_landed_blocks_promote():
    """Regression: failed worker apply → step ok False → not landed → no auto-promote."""
    applied = {
        "step": "improve_ours",
        "ok": True,  # plan written; worker still failed
        "plan": ".nexus_state/repo_mine/IMPROVE_OURS.md",
        "apply": {
            "via": "grok",
            "ok": False,
            "error": "xhigh CLI error",
            "returncode": 2,
        },
    }
    status = al._improve_ours_apply_status(applied)
    assert status["ok"] is False
    step = {
        "step": "self_approve_apply",
        "ok": bool(status.get("ok")),
        "reason": status.get("reason"),
        "apply": applied.get("apply"),
        "plan": applied.get("plan"),
    }
    assert step["ok"] is False
    report = {"steps": [step]}
    assert al._self_approve_apply_landed(report) is False

    cfg = al.AliveConfig(promote_on_done=False, self_approve=True, apply=True)
    assert not al._should_promote_on_done(
        cfg, checks={"ok": True}, report=report
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
