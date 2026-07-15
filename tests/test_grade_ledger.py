"""Tests for append-only grade ledger + checkpoint + eval CLI (First apply slice)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nexus.grade_ledger import (
    DEFAULT_METHOD,
    GradeLedger,
    ImmutableLedgerError,
    checkpoint_stage,
    graded_repos_from_checkpoint,
    ingest_grades,
    load_checkpoint,
    record_evaluate_results,
    why_selected,
)
from nexus.grade_cli import main as eval_main


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mine_eval_sample.json"


def test_append_immutable_and_weak_retained(tmp_path: Path):
    with GradeLedger.open(tmp_path) as led:
        strong = led.append(
            run_id="r1",
            repo="IBM/AssetOpsBench",
            score=16.0,
            idea=8.0,
            skill=8.0,
            method=DEFAULT_METHOD,
            path=".nexus_workspaces/mine_eval/IBM__AssetOpsBench",
            summary="domain MCP + eval CLI",
        )
        weak = led.append(
            run_id="r1",
            repo="swarmclawai/swarmclaw",
            score=13.0,
            idea=6.0,
            skill=7.0,
            method=DEFAULT_METHOD,
            path=".nexus_workspaces/mine_eval/swarmclawai__swarmclaw",
            summary="weak but retained",
        )
        assert strong["repo"] == "IBM/AssetOpsBench"
        assert weak["score"] == 13.0
        assert led.count(run_id="r1") == 2

        # Weak scores appear in list and weak()
        all_rows = led.list(run_id="r1")
        assert any(r["score"] == 13.0 for r in all_rows)
        weak_rows = led.weak(max_score=14.0, run_id="r1")
        assert any(r["repo"] == "swarmclawai/swarmclaw" for r in weak_rows)

        # API-level update/delete rejected
        with pytest.raises(ImmutableLedgerError):
            led.update(strong["id"], score=99)
        with pytest.raises(ImmutableLedgerError):
            led.delete(strong["id"])

        # SQLite trigger rejects raw UPDATE/DELETE
        with pytest.raises(sqlite3.IntegrityError):
            led.conn.execute(
                "UPDATE grades SET score=0 WHERE id=?", (strong["id"],)
            )
            led.conn.commit()
        led.conn.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            led.conn.execute("DELETE FROM grades WHERE id=?", (strong["id"],))
            led.conn.commit()
        led.conn.rollback()
        assert led.count(run_id="r1") == 2


def test_idempotent_no_duplicate_run_repo_method(tmp_path: Path):
    with GradeLedger.open(tmp_path) as led:
        a = led.append(
            run_id="run-x",
            repo="phodal/routa",
            score=16.0,
            idea=8.0,
            skill=8.0,
            method=DEFAULT_METHOD,
        )
        b = led.append(
            run_id="run-x",
            repo="phodal/routa",
            score=16.0,
            idea=8.0,
            skill=8.0,
            method=DEFAULT_METHOD,
        )
        assert a["id"] == b["id"]
        assert led.count(run_id="run-x") == 1


def test_checkpoint_stage_round_trip(tmp_path: Path):
    rec = checkpoint_stage(
        "run-grade-1",
        "grade",
        {"repos": ["IBM/AssetOpsBench", "phodal/routa"], "count": 2},
        workdir=tmp_path,
    )
    assert rec["run_id"] == "run-grade-1"
    assert rec["stage"] == "grade"
    loaded = load_checkpoint("run-grade-1", "grade", workdir=tmp_path)
    assert loaded is not None
    assert loaded["payload"]["count"] == 2
    assert set(loaded["payload"]["repos"]) == {
        "IBM/AssetOpsBench",
        "phodal/routa",
    }
    assert graded_repos_from_checkpoint("run-grade-1", workdir=tmp_path) == {
        "IBM/AssetOpsBench",
        "phodal/routa",
    }


def test_record_evaluate_no_duplicate_on_rerun(tmp_path: Path):
    results = [
        {
            "repo": "IBM/AssetOpsBench",
            "idea": 8.0,
            "skill": 8.0,
            "score": 16.0,
            "method": DEFAULT_METHOD,
            "path": "/tmp/IBM__AssetOpsBench",
            "description": "eval CLI",
        },
        {
            "repo": "weak/example",
            "idea": 6.0,
            "skill": 7.0,
            "score": 13.0,
            "method": DEFAULT_METHOD,
            "path": "/tmp/weak",
        },
    ]
    first = record_evaluate_results(results, run_id="eval-1", workdir=tmp_path)
    assert set(first["written"]) == {"IBM/AssetOpsBench", "weak/example"}
    second = record_evaluate_results(results, run_id="eval-1", workdir=tmp_path)
    assert second["written"] == []
    assert set(second["skipped_duplicate"]) == {
        "IBM/AssetOpsBench",
        "weak/example",
    }
    with GradeLedger.open(tmp_path) as led:
        assert led.count(run_id="eval-1") == 2
        weak = led.weak(max_score=14)
        assert any(r["repo"] == "weak/example" for r in weak)


def test_ingest_fixture_and_export_md(tmp_path: Path):
    # Copy fixture into tmp workdir layout for offline ingest
    fix = tmp_path / "tests" / "fixtures" / "mine_eval_sample.json"
    fix.parent.mkdir(parents=True)
    fix.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    report = ingest_grades(tmp_path, run_id="ingest-1", fixture=str(fix))
    assert report["ingested"] >= 1
    assert "wshobson/agents" in report["repos"]

    with GradeLedger.open(tmp_path) as led:
        md = led.export_md(n=10, run_id="ingest-1")
        assert "wshobson/agents" in md or "codingagentsystem/cas" in md
        assert "why_selected" in md
        top = led.top(n=5, run_id="ingest-1")
        assert top
        assert "selected" in why_selected(top[0])


def test_export_contains_evidence_repos(tmp_path: Path):
    with GradeLedger.open(tmp_path) as led:
        for repo, score, idea, skill in (
            ("IBM/AssetOpsBench", 16.0, 8.0, 8.0),
            ("phodal/routa", 16.0, 8.0, 8.0),
            ("Intelligent-Internet/zenith", 13.0, 7.0, 6.0),
        ):
            led.append(
                run_id="ev",
                repo=repo,
                score=score,
                idea=idea,
                skill=skill,
                method=DEFAULT_METHOD,
            )
        md = led.export_md(n=10, run_id="ev")
        assert "IBM/AssetOpsBench" in md
        assert "phodal/routa" in md
        # weak retained section
        assert "zenith" in md or "Retained weak" in md


def test_cli_ingest_top_weak_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    fix = tmp_path / "fix.json"
    fix.write_text(
        json.dumps(
            {
                "grades": [
                    {
                        "repo": "IBM/AssetOpsBench",
                        "score": 16.0,
                        "idea": 8.0,
                        "skill": 8.0,
                        "method": DEFAULT_METHOD,
                        "path": ".nexus_workspaces/mine_eval/IBM__AssetOpsBench",
                    },
                    {
                        "repo": "phodal/routa",
                        "score": 16.0,
                        "idea": 8.0,
                        "skill": 8.0,
                        "method": DEFAULT_METHOD,
                        "path": ".nexus_workspaces/mine_eval/phodal__routa",
                    },
                    {
                        "repo": "weak/kept",
                        "score": 13.0,
                        "idea": 6.0,
                        "skill": 7.0,
                        "method": DEFAULT_METHOD,
                        "path": ".nexus_workspaces/mine_eval/weak__kept",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    rc = eval_main(
        [
            "ingest",
            "--path",
            str(tmp_path),
            "--fixture",
            str(fix),
            "--run-id",
            "cli-1",
        ]
    )
    assert rc == 0

    rc = eval_main(["top", "--path", str(tmp_path), "-n", "2", "--run-id", "cli-1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "IBM/AssetOpsBench" in out or "phodal/routa" in out

    rc = eval_main(
        ["weak", "--path", str(tmp_path), "--max-score", "14", "--run-id", "cli-1"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "weak/kept" in out

    out_md = tmp_path / "export.md"
    rc = eval_main(
        [
            "export",
            "--path",
            str(tmp_path),
            "--format",
            "md",
            "--run-id",
            "cli-1",
            "--out",
            str(out_md),
        ]
    )
    assert rc == 0
    text = out_md.read_text(encoding="utf-8")
    assert "IBM/AssetOpsBench" in text or "phodal/routa" in text
    assert "why_selected" in text


def test_method_default_grok(tmp_path: Path):
    with GradeLedger.open(tmp_path) as led:
        row = led.append(
            run_id="m",
            repo="x/y",
            score=10.0,
            idea=5.0,
            skill=5.0,
        )
        assert row["method"] == "grok:grok-4.5"
