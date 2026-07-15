"""Integration smoke: mine → grade → claim_verify + ledger (First apply slice)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.decision_ledger import DecisionLedger
from nexus.improve_smoke import format_report, main as smoke_main, run_smoke
from nexus.load_mine_eval import load_fixture_file, load_one
from nexus.stages import StageOrderError, StageRunner


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mine_eval_sample.json"


def test_fixture_loads_wshobson():
    grades = load_fixture_file(FIXTURE)
    assert len(grades) >= 1
    top = grades[0]
    assert top["repo"] == "wshobson/agents"
    assert top["score"] == 16.0
    assert top["idea"] == 8.0
    assert top["skill"] == 8.0
    assert top["path"]


def test_run_smoke_end_to_end(tmp_path: Path):
    report = run_smoke(tmp_path, fixture=FIXTURE, run_id="smoke-test-1")
    assert report["ok"] is True, report.get("error")
    assert report["completed"] == ["mine", "grade", "claim_verify"]
    assert report["grade"]["repo"] == "wshobson/agents"
    assert report["grade"]["score"] == 16.0
    assert report["claim"]["ok"] is True
    assert len(report["ledger_tail"]) == 3

    # Ledger durable + queryable
    with DecisionLedger.open(tmp_path) as led:
        rows = led.list_run("smoke-test-1")
        assert [r["agent"] for r in rows] == ["mine", "grade", "claim_verify"]
        # Idempotent re-append via second smoke with same run/content would not
        # double-count distinct stages (different claims/actions).
        assert led.count(run_id="smoke-test-1") == 3

    text = format_report(report)
    assert "pass:" in text.lower() or "YES" in text
    assert "wshobson" in text


def test_smoke_fails_on_bad_fixture(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"repo": "x/y", "idea": 1, "skill": 1}), encoding="utf-8")
    # missing score + path → load or claim fails
    report = run_smoke(tmp_path, fixture=bad)
    assert report["ok"] is False
    assert report["error"]


def test_stage_order_still_enforced_inside_runner():
    r = StageRunner.smoke()
    with pytest.raises(StageOrderError):
        r.mark_complete("grade")


def test_cli_main_fixture(tmp_path: Path, capsys):
    # Use absolute fixture; workdir = tmp so ledger is isolated
    code = smoke_main(
        ["--path", str(tmp_path), "--fixture", str(FIXTURE), "--run-id", "cli-1"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "wshobson" in out
    assert "YES" in out or "ok" in out.lower()


def test_cli_main_json(tmp_path: Path, capsys):
    code = smoke_main(
        [
            "--path",
            str(tmp_path),
            "--fixture",
            str(FIXTURE),
            "--json",
        ]
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["grade"]["score"] == 16.0


def test_load_one_prefers_fixture(tmp_path: Path):
    g = load_one(tmp_path, fixture=FIXTURE, repo="codingagentsystem/cas")
    assert g["repo"] == "codingagentsystem/cas"
    assert g["score"] == 15.0
