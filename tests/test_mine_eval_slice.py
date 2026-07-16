"""Tests for First apply slice (docs/LATEST_IMPROVE_PLAN.md §5)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nexus.mine_eval_slice import (
    DEFAULT_MIN_SCORE,
    SLICE_STAGES,
    ClaimResult,
    ImmutableError,
    SliceLedger,
    SliceRunner,
    StageOrderError,
    assert_transition,
    can_transition,
    classify_apply_candidates,
    dry_run_worktree_apply,
    format_demo_report,
    load_fixture_grade,
    migrate,
    pattern_for_repo,
    run_demo_slice,
    verify_claims,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mine_eval_sample.json"


def test_ledger_append_immutable(tmp_path: Path):
    """Second write with same content does not mutate first row."""
    migrate(tmp_path)
    with SliceLedger.open(tmp_path) as led:
        first = led.append(
            repo_or_paper_id="wshobson/agents",
            score=16.0,
            idea=8.0,
            skill=8.0,
            method="grok:grok-4.5",
            causal_note="score=16 because skill marketplace generate/validate/smoke",
            artifact_path=".nexus_workspaces/scout_repos/wshobson__agents",
            run_id="r1",
        )
        second = led.append(
            repo_or_paper_id="wshobson/agents",
            score=16.0,
            idea=8.0,
            skill=8.0,
            method="grok:grok-4.5",
            causal_note="score=16 because skill marketplace generate/validate/smoke",
            artifact_path=".nexus_workspaces/scout_repos/wshobson__agents",
            run_id="r1",
        )
        assert first["id"] == second["id"]
        assert first["created_at"] == second["created_at"]
        assert first["causal_note"].startswith("score=16")
        assert led.count(run_id="r1") == 1

        # SQLite triggers reject UPDATE/DELETE
        with pytest.raises(sqlite3.IntegrityError):
            led.conn.execute(
                "UPDATE grades SET score=0 WHERE id=?", (first["id"],)
            )
            led.conn.commit()
        led.conn.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            led.conn.execute("DELETE FROM grades WHERE id=?", (first["id"],))
            led.conn.commit()
        led.conn.rollback()
        assert led.count(run_id="r1") == 1


def test_claim_verifier_threshold_and_tests():
    """score≥threshold + tests_ok → pass; low score → fail with reason."""
    good = {
        "repo": "wshobson/agents",
        "score": 16.0,
        "idea": 8.0,
        "skill": 8.0,
        "path": "x",
    }
    ok = verify_claims(good, test_exit_code=0, min_score=14.0)
    assert isinstance(ok, ClaimResult)
    assert ok.ok is True
    assert ok.apply_candidate is True
    assert ok.reasons == []

    low = verify_claims(
        {**good, "score": 13.0}, test_exit_code=0, min_score=14.0
    )
    assert low.ok is False
    assert low.apply_candidate is False
    assert any("below min_score" in r for r in low.reasons)

    fail_tests = verify_claims(good, test_exit_code=1, min_score=14.0)
    assert fail_tests.ok is False
    assert any("tests not ok" in r for r in fail_tests.reasons)


def test_action_order_mined_to_apply_without_graded_raises():
    """MINED → APPLY_CANDIDATE without GRADED raises."""
    assert can_transition(None, "MINED")
    assert can_transition("mined", "GRADED")
    assert not can_transition("mined", "APPLY_CANDIDATE")
    with pytest.raises(StageOrderError, match="illegal transition"):
        assert_transition("mined", "APPLY_CANDIDATE")
    with pytest.raises(StageOrderError, match="illegal transition"):
        runner = SliceRunner()
        runner.advance("MINED")
        runner.advance("APPLY_CANDIDATE")

    runner = SliceRunner()
    runner.advance("mined")
    runner.advance("graded")
    runner.advance("claim_ok")
    runner.advance("apply_candidate")
    assert runner.is_done()
    assert runner.completed == list(SLICE_STAGES)


def test_migration_guard_second_is_noop(tmp_path: Path):
    """migrate twice → second is no-op / guarded."""
    first = migrate(tmp_path)
    assert first["ok"] is True
    assert first["already_migrated"] is False
    second = migrate(tmp_path)
    assert second["ok"] is True
    assert second["already_migrated"] is True
    assert second["guard"] == "refuse_double_migrate"
    assert Path(first["path"]).is_file()


def test_demo_slice_wshobson_exits_ok(tmp_path: Path):
    """Demo against fixture grade for wshobson/agents (score 16.0) exits ok."""
    # copy fixture into tmp workdir layout
    fix_dir = tmp_path / "tests" / "fixtures"
    fix_dir.mkdir(parents=True)
    dest = fix_dir / "mine_eval_sample.json"
    dest.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    report = run_demo_slice(
        tmp_path,
        fixture=str(dest),
        repo="wshobson/agents",
        min_score=14.0,
        test_exit_code=0,
    )
    assert report["ok"] is True
    assert report["apply_candidate"] is True
    assert report["grade"]["score"] == 16.0
    assert "wshobson" in str(report["grade"]["repo_or_paper_id"])
    assert report["ledger_row"] is not None
    assert report["ledger_row"]["causal_note"]
    assert report["completed"] == list(SLICE_STAGES)
    assert "apply_candidate=YES" in report["kanban"]
    # APPLY_CANDIDATE now runs sandbox worktree dry-run
    wt = report.get("worktree_apply") or {}
    assert wt.get("ok") is True, wt
    assert wt.get("pattern") == "markdown-skill-sot-validator"
    assert wt.get("cache_hit") is False
    text = format_demo_report(report)
    assert "pass:             YES" in text or "pass:" in text and "YES" in text
    assert "worktree.ok" in text


def test_demo_slice_plan_reuse_cache_hit(tmp_path: Path):
    """Second plan-slice for same grade hits plan-reuse cache."""
    fix_dir = tmp_path / "tests" / "fixtures"
    fix_dir.mkdir(parents=True)
    dest = fix_dir / "mine_eval_sample.json"
    dest.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    r1 = run_demo_slice(
        tmp_path,
        fixture=str(dest),
        repo="wshobson/agents",
        run_id="slice-cache-1",
        min_score=14.0,
    )
    assert r1["ok"] is True
    assert (r1.get("worktree_apply") or {}).get("cache_hit") is False

    r2 = run_demo_slice(
        tmp_path,
        fixture=str(dest),
        repo="wshobson/agents",
        run_id="slice-cache-2",
        min_score=14.0,
    )
    assert r2["ok"] is True
    wt2 = r2.get("worktree_apply") or {}
    assert wt2.get("cache_hit") is True, wt2
    assert wt2.get("ok") is True
    assert "cache=hit" in (r2.get("kanban") or "")


def test_pattern_for_repo_hints():
    assert pattern_for_repo("wshobson/agents") == "markdown-skill-sot-validator"
    assert pattern_for_repo("codingagentsystem/cas") == "cas-evidence-board-ops"
    assert pattern_for_repo("unknown/thing").startswith("markdown")


def test_eval_classify_three_grades():
    """Fixture set of 3 EVIDENCE grades (16, 15, 13) classifies candidates."""
    grades = [
        {"repo": "wshobson/agents", "score": 16.0, "idea": 8.0, "skill": 8.0},
        {"repo": "codingagentsystem/cas", "score": 15.0, "idea": 7.0, "skill": 8.0},
        {"repo": "swarmclawai/swarmclaw", "score": 13.0, "idea": 6.0, "skill": 7.0},
    ]
    rows = classify_apply_candidates(grades, min_score=14.0)
    assert len(rows) == 3
    by_repo = {r["repo_or_paper_id"]: r for r in rows}
    assert by_repo["wshobson/agents"]["apply_candidate"] is True
    assert by_repo["codingagentsystem/cas"]["apply_candidate"] is True
    assert by_repo["swarmclawai/swarmclaw"]["apply_candidate"] is False
    assert by_repo["swarmclawai/swarmclaw"]["ok"] is False


def test_load_fixture_grade_prefers_wshobson():
    grade = load_fixture_grade(
        FIXTURE.parent.parent.parent,  # tests/ → repo root-ish; use absolute fixture
        fixture=str(FIXTURE),
        repo="wshobson/agents",
    )
    assert grade["repo"] == "wshobson/agents"
    assert float(grade["score"]) == 16.0


def test_cli_plan_slice(tmp_path: Path, monkeypatch):
    """nexus improve plan-slice against fixture exits 0."""
    from nexus import cli as nexus_cli

    fix_dir = tmp_path / "tests" / "fixtures"
    fix_dir.mkdir(parents=True)
    dest = fix_dir / "mine_eval_sample.json"
    dest.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    # Invoke via cmd_improve shape
    import argparse

    args = argparse.Namespace(
        improve_cmd="plan-slice",
        path=str(tmp_path),
        workdir=str(tmp_path),
        fixture=str(dest),
        repo="wshobson/agents",
        run_id="cli-slice-1",
        min_score=14.0,
        test_exit_code=0,
        json=False,
        project_root=str(tmp_path),
        no_dry_run=False,
        no_worktree=False,
        no_plan_cache=False,
        pattern=None,
    )
    # cmd_improve uses root from args / cwd
    code = nexus_cli.cmd_improve(args)
    assert code == 0
