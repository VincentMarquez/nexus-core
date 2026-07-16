"""First apply slice: improve_spine work_ledger + grade_records + resume + MCP + CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.improve_spine import (
    STAGE_APPLY_PENDING,
    STAGE_GRADED,
    STAGE_SCOUTED,
    ImmutableError,
    ImproveSpine,
    format_status,
    ingest_mine_eval,
    load_checkpoint,
    mcp_grade_get,
    mcp_ledger_append,
    mcp_ledger_list,
    run_first_slice,
    status,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mine_eval_sample.json"


# ---------------------------------------------------------------------------
# Unit: ledger append is immutable
# ---------------------------------------------------------------------------


def test_ledger_append_immutable(tmp_path: Path):
    with ImproveSpine.open(tmp_path) as store:
        a = store.append(
            run_id="r1",
            stage=STAGE_SCOUTED,
            agent="scout:mine",
            action="ingest",
            payload={"n": 1},
        )
        assert a["id"]
        assert a["stage"] == STAGE_SCOUTED

        with pytest.raises(ImmutableError):
            store.try_update_ledger_forbidden(a["id"])
        with pytest.raises(ImmutableError):
            store.try_delete_ledger_forbidden(a["id"])

        # second distinct append gets new id
        b = store.append(
            run_id="r1",
            stage=STAGE_GRADED,
            agent="grok:grade",
            action="record_grade",
            payload={"score": 15.0},
            parent_id=a["id"],
        )
        assert b["id"] != a["id"]
        assert store.count_ledger(run_id="r1") == 2

        # identical content is idempotent (same content_hash → same id)
        a2 = store.append(
            run_id="r1",
            stage=STAGE_SCOUTED,
            agent="scout:mine",
            action="ingest",
            payload={"n": 1},
        )
        assert a2["id"] == a["id"]
        assert store.count_ledger(run_id="r1") == 2


# ---------------------------------------------------------------------------
# Unit: grade record round-trip (Grok shape)
# ---------------------------------------------------------------------------


def test_grade_record_round_trip(tmp_path: Path):
    with ImproveSpine.open(tmp_path) as store:
        g = store.record_grade(
            repo_or_paper_id="codingagentsystem/cas",
            score=15.0,
            idea=7.0,
            skill=8.0,
            method="grok:grok-4.5",
            summary="Supervisor/workers in git worktrees + MCP/SQLite",
            path=".nexus_workspaces/mine_eval/codingagentsystem__cas",
            run_id="demo-cas",
        )
        assert g["repo_or_paper_id"] == "codingagentsystem/cas"
        assert g["score"] == 15.0
        assert g["idea"] == 7.0
        assert g["skill"] == 8.0
        assert g["method"] == "grok:grok-4.5"
        assert "worktrees" in g["summary"] or "MCP" in g["summary"]

        got = store.get_grade("codingagentsystem/cas", run_id="demo-cas")
        assert got is not None
        assert got["id"] == g["id"]
        assert got["score"] == 15.0
        assert got["path"].endswith("codingagentsystem__cas")

        # weak scores retained
        weak = store.record_grade(
            repo_or_paper_id="example/weak",
            score=3.0,
            idea=1.0,
            skill=2.0,
            run_id="demo-cas",
        )
        assert weak["score"] == 3.0
        assert store.count_grades(run_id="demo-cas") == 2


# ---------------------------------------------------------------------------
# Unit: checkpoint resume does not duplicate grade
# ---------------------------------------------------------------------------


def test_checkpoint_resume_no_duplicate_grade(tmp_path: Path):
    # Copy fixture into tmp so ingest is fully offline under tmp_path
    fix = tmp_path / "mine.json"
    fix.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    first = ingest_mine_eval(
        tmp_path,
        run_id="demo-cas",
        source=fix,
        repo="codingagentsystem/cas",
        advance_to_apply_pending=False,
    )
    assert first["ok"]
    assert first["stage"] == STAGE_GRADED
    assert first["ingested"] == 1
    assert first["resumed"] is False
    assert load_checkpoint("demo-cas", workdir=tmp_path)["stage"] == STAGE_GRADED
    n_grades = first["grades"][0]["id"]

    second = ingest_mine_eval(
        tmp_path,
        run_id="demo-cas",
        source=fix,
        repo="codingagentsystem/cas",
        advance_to_apply_pending=True,
    )
    assert second["ok"]
    assert second["resumed"] is True
    assert second["ingested"] == 0
    assert second["stage"] == STAGE_APPLY_PENDING
    assert len(second["grades"]) == 1
    assert second["grades"][0]["id"] == n_grades

    with ImproveSpine.open(tmp_path) as store:
        assert store.count_grades(run_id="demo-cas") == 1


# ---------------------------------------------------------------------------
# Integration: ingest fixture
# ---------------------------------------------------------------------------


def test_ingest_fixture_cas(tmp_path: Path):
    fix = tmp_path / "mine.json"
    fix.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    report = ingest_mine_eval(
        tmp_path,
        run_id="demo-cas",
        source=fix,
        repo="codingagentsystem/cas",
    )
    assert report["ok"]
    assert report["stage"] == STAGE_APPLY_PENDING
    g = report["grades"][0]
    assert g["repo_or_paper_id"] == "codingagentsystem/cas"
    assert float(g["score"]) >= 10.0
    assert g["method"] == "grok:grok-4.5"
    events = report["ledger"]
    stages = [e["stage"] for e in events]
    assert STAGE_SCOUTED in stages
    assert STAGE_GRADED in stages
    assert STAGE_APPLY_PENDING in stages


def test_run_first_slice_wshobson(tmp_path: Path):
    fix = tmp_path / "mine.json"
    fix.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    report = run_first_slice(
        tmp_path,
        run_id="demo-wsh",
        source=fix,
        repo="wshobson/agents",
    )
    assert report["ok"]
    assert float(report["grades"][0]["score"]) >= 10.0


# ---------------------------------------------------------------------------
# Integration: MCP tools
# ---------------------------------------------------------------------------


def test_mcp_ledger_list_after_ingest(tmp_path: Path):
    fix = tmp_path / "mine.json"
    fix.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    ingest_mine_eval(
        tmp_path,
        run_id="demo-cas",
        source=fix,
        repo="codingagentsystem/cas",
    )
    listed = mcp_ledger_list(tmp_path, run_id="demo-cas", limit=20)
    assert listed["count"] >= 2
    assert any(e["run_id"] == "demo-cas" for e in listed["events"])

    g = mcp_grade_get(tmp_path, repo_or_paper_id="codingagentsystem/cas", run_id="demo-cas")
    assert g["found"] is True
    assert g["grade"]["score"] >= 10.0

    # ledger.append
    row = mcp_ledger_append(
        tmp_path,
        run_id="demo-cas",
        stage=STAGE_APPLY_PENDING,
        agent="worker:apply",
        action="note",
        payload={"msg": "mcp ok"},
    )
    assert row["action"] == "note"
    listed2 = mcp_ledger_list(tmp_path, run_id="demo-cas")
    assert listed2["count"] == listed["count"] + 1


def test_mcp_server_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nexus import mcp_server as ms

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    fix = tmp_path / "mine.json"
    fix.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    ingest_mine_eval(
        tmp_path,
        run_id="demo-cas",
        source=fix,
        repo="codingagentsystem/cas",
    )

    # tools/list should expose plan tools
    names = {t["name"] for t in ms.TOOLS}
    assert "ledger_append" in names
    assert "ledger_list" in names
    assert "grade_get" in names

    listed = ms.call_tool(
        "ledger_list",
        {"run_id": "demo-cas", "limit": 10},
    )
    assert not listed.get("isError")
    text = listed["content"][0]["text"]
    body = json.loads(text)
    assert body["count"] >= 1

    got = ms.call_tool(
        "grade_get",
        {"repo_or_paper_id": "codingagentsystem/cas", "run_id": "demo-cas"},
    )
    assert not got.get("isError")
    gbody = json.loads(got["content"][0]["text"])
    assert gbody["found"] is True
    assert float(gbody["grade"]["score"]) >= 10.0


# ---------------------------------------------------------------------------
# Smoke CLI: improve status
# ---------------------------------------------------------------------------


def test_cli_improve_status_and_ingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nexus.cli import main

    monkeypatch.chdir(tmp_path)
    fix = tmp_path / "mine.json"
    fix.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    rc = main(
        [
            "improve",
            "ingest",
            "--path",
            str(tmp_path),
            "--run-id",
            "demo-cas",
            "--repo",
            "codingagentsystem/cas",
            "--fixture",
            str(fix),
            "--json",
        ]
    )
    assert rc == 0

    rc2 = main(
        [
            "improve",
            "status",
            "--path",
            str(tmp_path),
            "--run",
            "demo-cas",
            "--json",
        ]
    )
    assert rc2 == 0

    report = status(tmp_path, run_id="demo-cas")
    assert report["ok"]
    assert report["stage"] == STAGE_APPLY_PENDING
    assert report["last_grade"] is not None
    assert float(report["last_grade"]["score"]) >= 10.0
    text = format_status(report)
    assert "demo-cas" in text
    assert "score=" in text
