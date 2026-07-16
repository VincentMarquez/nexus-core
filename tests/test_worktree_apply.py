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


def test_pattern_catalog_has_cas_evidence_board(tmp_path: Path):
    """Second catalog entry: cas/mission-control evidence board skill."""
    rows = wta.list_patterns()
    assert any(r["id"] == "cas-evidence-board-ops" for r in rows)
    p = wta.get_pattern("cas-evidence-board-ops")
    assert p["repo"] == "codingagentsystem/cas"
    assert p["pack_id"] == "evidence-board-ops"
    meta = wta.create_worktree(tmp_path, job_id="ev-board-1", mode="sandbox")
    wt = Path(meta["path"])
    applied = wta.apply_pattern_files(wt, "cas-evidence-board-ops", job_id="ev-board-1")
    assert any("evidence-board-ops" in f for f in applied["files_written"])
    assert (wt / "skillpacks" / "evidence-board-ops" / "APPLY_META.json").is_file()
    ver = wta.verify_in_worktree(wt, "cas-evidence-board-ops")
    assert ver["ok"] is True, ver


def test_pattern_catalog_has_mission_control_spend(tmp_path: Path):
    """Third catalog entry: mission-control spend / ops skill."""
    rows = wta.list_patterns()
    assert any(r["id"] == "mission-control-spend-ops" for r in rows)
    p = wta.get_pattern("mission-control-spend-ops")
    assert p["repo"] == "builderz-labs/mission-control"
    assert p["pack_id"] == "mission-control-spend-ops"
    meta = wta.create_worktree(tmp_path, job_id="spend-1", mode="sandbox")
    wt = Path(meta["path"])
    applied = wta.apply_pattern_files(
        wt, "mission-control-spend-ops", job_id="spend-1"
    )
    assert any("mission-control-spend-ops" in f for f in applied["files_written"])
    assert (
        wt / "skillpacks" / "mission-control-spend-ops" / "APPLY_META.json"
    ).is_file()
    skill = (wt / "skillpacks" / "mission-control-spend-ops" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "ops spend" in skill.lower() or "nexus ops" in skill.lower()
    ver = wta.verify_in_worktree(wt, "mission-control-spend-ops")
    assert ver["ok"] is True, ver


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
    assert report["decision"] is not None
    assert report["decision"]["ok"] is True
    assert report["signal"] == "continue"
    assert report["verify"]["ok"] is True
    assert report["main_untouched"]["ok"] is True
    assert report["cleanup"]["removed"] is True
    # Main never received the pack
    assert not (tmp_path / "skillpacks" / "markdown-sot-demo").exists()
    assert (tmp_path / "MAIN_MARKER").read_text(encoding="utf-8") == "do-not-touch\n"

    with DecisionLedger.open(tmp_path) as led:
        rows = led.list_run("e2e-apply-1")
        agents = [r["agent"] for r in rows]
        assert agents == [
            "mine",
            "grade",
            "claim_verify",
            "decide",
            "work_ledger",
            "plan_apply",
            "apply",
        ]
        assert led.count(run_id="e2e-apply-1") == 7
        assert (report.get("work_ledger") or {}).get("accepted") is True


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


def test_run_apply_decision_denies_collusion(tmp_path: Path):
    """require_decision fail-closes when grader==implementer==verifier."""
    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        run_id="collude-1",
        mode="sandbox",
        cleanup=True,
        require_decision=True,
        grader="same",
        implementer="same",
        verifier="same",
        require_distinct_roles=True,
    )
    assert report["ok"] is False
    assert report.get("decision") is not None
    assert report["decision"]["ok"] is False
    err = report.get("error") or ""
    assert "decision" in err.lower() or "collusion" in err.lower() or "signal" in err.lower()
    # Isolation: no pack on main
    assert not (tmp_path / "skillpacks" / "markdown-sot-demo").exists()


def test_run_apply_can_skip_decision_gate(tmp_path: Path):
    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        run_id="skip-dec-1",
        mode="sandbox",
        cleanup=True,
        require_decision=False,
        grader="same",
        implementer="same",
        verifier="same",
        require_distinct_roles=True,
    )
    # collusion recorded but not required → apply still proceeds
    assert report["ok"] is True, report.get("error")
    assert report.get("decision") is not None
    # work ledger follows require_decision default → off when decision skipped
    assert report.get("require_work_ledger") is False


def test_run_apply_records_work_ledger_accept(tmp_path: Path):
    """require_work_ledger (default with decision) dual-control accept before plan."""
    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        repo="wshobson/agents",
        run_id="wl-wire-1",
        mode="sandbox",
        cleanup=True,
        require_decision=True,
        require_work_ledger=True,
        grader="grok:grade",
        implementer="worker:apply",
        verifier="judge:verify",
    )
    assert report["ok"] is True, report.get("error")
    wl = report.get("work_ledger") or {}
    assert wl.get("accepted") is True, wl
    assert "apply_accepted" in (wl.get("event_types") or [])
    # ledger persisted under workdir
    db = tmp_path / ".nexus_workspaces" / "work_ledger" / "work.sqlite"
    assert db.is_file()


def test_run_apply_work_ledger_collusion_denies(tmp_path: Path):
    """Even if decision roles look fine, same grader/applier fails work_ledger."""
    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        repo="wshobson/agents",
        run_id="wl-collude-1",
        mode="sandbox",
        cleanup=True,
        require_decision=False,  # skip board decision so we hit work_ledger only
        require_work_ledger=True,
        grader="same-agent",
        implementer="same-agent",
        verifier="judge:verify",
        require_distinct_roles=False,
    )
    assert report["ok"] is False
    err = (report.get("error") or "").lower()
    assert "work_ledger" in err or "dual" in err
    wl = report.get("work_ledger") or {}
    assert wl.get("accepted") is not True


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


def test_promote_to_main_after_apply(tmp_path: Path):
    """P0.1: verified worktree pack lands on main only at promote."""
    (tmp_path / "MAIN_MARKER").write_text("do-not-touch\n", encoding="utf-8")

    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        run_id="prom-e2e-1",
        mode="sandbox",
        cleanup=True,
        promote=True,
    )
    assert report["ok"] is True, report.get("error")
    assert report["completed"] == [
        "mine",
        "grade",
        "claim_verify",
        "plan_apply",
        "apply",
        "promote",
    ]
    assert report["main_untouched"]["ok"] is True  # isolation during apply
    prom = report["promote"]
    assert prom["ok"] is True
    assert prom["verify_main"]["ok"] is True
    # Pack now on main
    pack = tmp_path / "skillpacks" / "markdown-sot-demo"
    assert (pack / "SKILL.md").is_file()
    assert (pack / "manifest.json").is_file()
    assert (pack / "APPLY_META.json").is_file()
    assert (pack / "PROMOTE_META.json").is_file()
    assert (tmp_path / "MAIN_MARKER").read_text(encoding="utf-8") == "do-not-touch\n"

    with DecisionLedger.open(tmp_path) as led:
        rows = led.list_run("prom-e2e-1")
        agents = [r["agent"] for r in rows]
        assert agents[-1] == "promote"
        assert "promote" in agents
        assert "decide" in agents
        assert "work_ledger" in agents
        assert led.count(run_id="prom-e2e-1") == 8


def test_promote_idempotent_same_content(tmp_path: Path):
    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        run_id="prom-idemp-1",
        mode="sandbox",
        cleanup=False,
        promote=True,
    )
    assert report["ok"] is True, report.get("error")
    # Second promote of same kept worktree (force not needed — identical)
    again = wta.run_promote(
        tmp_path,
        job_id="prom-idemp-1",
        force=False,
        cleanup=True,
    )
    assert again["ok"] is True, again.get("error")
    skipped = again["promote"]["skipped_same"]
    assert any("SKILL.md" in p for p in skipped) or not again["promote"]["copied"]


def test_promote_refuses_dirty_main_without_force(tmp_path: Path):
    # Pre-seed conflicting content on main
    dest = tmp_path / "skillpacks" / "markdown-sot-demo"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("conflicting local skill\n", encoding="utf-8")
    (dest / "manifest.json").write_text("{}", encoding="utf-8")
    (dest / "APPLY_META.json").write_text("{}\n", encoding="utf-8")

    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        run_id="prom-conflict-1",
        mode="sandbox",
        cleanup=True,
        promote=True,
        promote_force=False,
    )
    assert report["ok"] is False
    assert report["error"]
    assert "promote refused" in report["error"] or "different" in report["error"]


def test_promote_force_overwrites(tmp_path: Path):
    dest = tmp_path / "skillpacks" / "markdown-sot-demo"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("old\n", encoding="utf-8")
    (dest / "manifest.json").write_text("{}", encoding="utf-8")
    (dest / "APPLY_META.json").write_text("{}\n", encoding="utf-8")

    report = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        run_id="prom-force-1",
        mode="sandbox",
        cleanup=True,
        promote=True,
        promote_force=True,
    )
    assert report["ok"] is True, report.get("error")
    skill = (dest / "SKILL.md").read_text(encoding="utf-8")
    assert "old" not in skill or "Markdown skill SoT" in skill
    assert "Markdown skill SoT" in skill


def test_promote_refuses_path_outside_worktrees(tmp_path: Path):
    outsider = tmp_path / "not_a_worktree"
    outsider.mkdir()
    (outsider / "skillpacks" / "markdown-sot-demo").mkdir(parents=True)
    with pytest.raises(wta.WorktreeApplyError, match="not under"):
        wta.promote_to_main(tmp_path, outsider, require_verify=False)


def test_cli_promote_flag(tmp_path: Path, capsys):
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
            "--promote",
            "--json",
        ]
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["promote"]["ok"] is True
    assert (tmp_path / "skillpacks" / "markdown-sot-demo" / "SKILL.md").is_file()


def test_cli_promote_subcommand(tmp_path: Path, capsys):
    from nexus.cli import main as cli_main

    # Keep worktree, then promote via subcommand
    r = wta.run_apply(
        tmp_path,
        fixture=FIXTURE,
        run_id="prom-cli-job",
        mode="sandbox",
        cleanup=False,
        promote=False,
    )
    assert r["ok"] is True, r.get("error")
    assert not (tmp_path / "skillpacks" / "markdown-sot-demo" / "SKILL.md").exists()

    code = cli_main(
        [
            "improve",
            "promote",
            "--path",
            str(tmp_path),
            "--job-id",
            "prom-cli-job",
            "--json",
        ]
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert (tmp_path / "skillpacks" / "markdown-sot-demo" / "SKILL.md").is_file()
