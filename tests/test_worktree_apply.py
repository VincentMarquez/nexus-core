"""P0.5 worktree-isolated apply + Markdown skill SoT pattern tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.decision_ledger import DecisionLedger
from nexus.improve_apply import PathSafetyError, safe_path
from nexus.stages import APPLY_STAGES, StageOrderError, StageRunner
from nexus import worktree_apply as wta


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mine_eval_sample.json"


def test_pattern_catalog_has_wshobson_sot():
    rows = wta.list_patterns()
    assert any(r["id"] == wta.DEFAULT_PATTERN for r in rows)
    p = wta.get_pattern(wta.DEFAULT_PATTERN)
    assert p["repo"] == "wshobson/agents"
    assert "skillpacks/markdown-sot-demo/SKILL.md" in p["files"]


def test_unknown_pattern_raises():
    with pytest.raises(wta.WorktreeApplyError, match="unknown pattern"):
        wta.get_pattern("not-a-real-pattern")


def test_apply_stages_order():
    r = StageRunner.apply_slice()
    assert list(r.stages) == list(APPLY_STAGES)
    with pytest.raises(StageOrderError):
        r.mark_complete("plan_apply")
    for s in ("mine", "grade", "claim_verify"):
        r.mark_complete(s)
    r.mark_complete("plan_apply")
    r.mark_complete("apply")
    assert r.is_done()


def test_create_sandbox_worktree_isolation(tmp_path: Path):
    # Seed a sentinel on "main" that must not change
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("main-clean\n", encoding="utf-8")
    before = sentinel.read_text(encoding="utf-8")

    meta = wta.create_worktree(tmp_path, job_id="job-sandbox-1", mode="sandbox")
    assert meta["mode"] == "sandbox"
    wt = Path(meta["path"])
    assert wt.is_dir()
    assert (wt / ".nexus_apply_meta.json").is_file()
    # Nested under apply_worktrees
    assert ".nexus_workspaces" in str(wt)
    assert "apply_worktrees" in str(wt)

    applied = wta.apply_pattern_files(wt, wta.DEFAULT_PATTERN, job_id="job-sandbox-1")
    assert "skillpacks/markdown-sot-demo/SKILL.md" in applied["files_written"]
    assert (wt / "skillpacks" / "markdown-sot-demo" / "SKILL.md").is_file()
    assert (wt / "skillpacks" / "markdown-sot-demo" / "manifest.json").is_file()

    # Main sentinel untouched; pattern not on main
    assert sentinel.read_text(encoding="utf-8") == before
    assert not (tmp_path / "skillpacks" / "markdown-sot-demo" / "SKILL.md").exists()

    ver = wta.verify_in_worktree(wt, wta.DEFAULT_PATTERN)
    assert ver["ok"] is True, ver

    cleaned = wta.cleanup_worktree(tmp_path, "job-sandbox-1", meta=meta)
    assert cleaned["removed"] is True
    assert not wt.exists()


def test_path_jail_rejects_escape(tmp_path: Path):
    meta = wta.create_worktree(tmp_path, job_id="jail-1", mode="sandbox")
    wt = Path(meta["path"])
    with pytest.raises(PathSafetyError):
        safe_path(wt, "../escape.txt")
    wta.cleanup_worktree(tmp_path, "jail-1", meta=meta)


def test_run_apply_end_to_end_sandbox(tmp_path: Path):
    # Place a marker file that isolation must preserve
    (tmp_path / "MAIN_MARKER").write_text("do-not-touch\n", encoding="utf-8")

    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        run_id="e2e-apply-1",
        mode="sandbox",
        cleanup=True,
    )
    assert report["ok"] is True, report.get("error")
    assert report["completed"] == [
        "mine",
        "grade",
        "claim_verify",
        "plan_apply",
        "apply",
    ]
    assert report["grade"]["repo"] == "wshobson/agents"
    assert report["grade"]["score"] == 16.0
    assert report["verify"]["ok"] is True
    assert report["main_untouched"]["ok"] is True
    assert report["cleanup"]["removed"] is True
    # Main never received the pack
    assert not (tmp_path / "skillpacks" / "markdown-sot-demo").exists()
    assert (tmp_path / "MAIN_MARKER").read_text(encoding="utf-8") == "do-not-touch\n"

    with DecisionLedger.open(tmp_path) as led:
        rows = led.list_run("e2e-apply-1")
        agents = [r["agent"] for r in rows]
        assert agents == ["mine", "grade", "claim_verify", "plan_apply", "apply"]
        assert led.count(run_id="e2e-apply-1") == 5


def test_run_apply_keeps_worktree_when_requested(tmp_path: Path):
    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        run_id="keep-1",
        mode="sandbox",
        cleanup=False,
    )
    assert report["ok"] is True, report.get("error")
    wt = Path(report["worktree"]["path"])
    assert wt.is_dir()
    assert (wt / "skillpacks" / "markdown-sot-demo" / "APPLY_META.json").is_file()
    wta.cleanup_worktree(tmp_path, "keep-1", meta=report["worktree"])


def test_run_apply_refuses_bad_grade(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"repo": "x/y", "idea": 1, "skill": 1}), encoding="utf-8")
    report = wta.run_apply(tmp_path, fixture=bad, mode="sandbox")
    assert report["ok"] is False
    assert report["error"]


def test_cli_main_apply(tmp_path: Path, capsys):
    code = wta.main(
        [
            "--path",
            str(tmp_path),
            "--fixture",
            str(FIXTURE),
            "--mode",
            "sandbox",
            "--run-id",
            "cli-apply-1",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "YES" in out or "ok" in out.lower()
    assert "wshobson" in out or "markdown" in out.lower()


def test_cli_list_patterns(capsys):
    code = wta.main(["--list-patterns"])
    assert code == 0
    out = capsys.readouterr().out
    assert wta.DEFAULT_PATTERN in out


def test_cli_nexus_improve_apply(tmp_path: Path, capsys):
    from nexus.cli import main as cli_main

    code = cli_main(
        [
            "improve",
            "apply",
            "--path",
            str(tmp_path),
            "--fixture",
            str(FIXTURE),
            "--mode",
            "sandbox",
            "--json",
        ]
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["pattern"] == wta.DEFAULT_PATTERN


def test_format_report_contains_pass(tmp_path: Path):
    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        mode="sandbox",
        run_id="fmt-1",
    )
    text = wta.format_report(report)
    assert "pass:" in text.lower() or "YES" in text
    assert "worktree" in text.lower()
