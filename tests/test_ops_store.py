"""Tests for mission-control-style ops plane (P1.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.ops_store import (
    JOB_STATUSES,
    OpsError,
    OpsStore,
    calculate_stats,
    note_alive_cycle,
    note_improve_run,
)
from nexus import usage as um
from nexus import improve_apply as ia
from nexus import mcp_server


def test_calculate_stats_empty():
    s = calculate_stats([])
    assert s["total_tokens"] == 0
    assert s["request_count"] == 0


def test_upsert_list_spend(tmp_path: Path):
    with OpsStore.open(tmp_path) as store:
        j = store.upsert_job(
            "job-1",
            kind="mine",
            title="evaluate lumen",
            status="running",
            goal="grade repos",
        )
        assert j["id"] == "job-1"
        assert j["kind"] == "mine"
        assert j["status"] == "running"

        r1 = store.record_spend(
            "job-1", 100, source="grok", label="grade", dual_write_usage=False
        )
        assert r1["tokens"] == 100
        r2 = store.record_spend(
            "job-1", 50, source="ollama", label="rewrite", dual_write_usage=False
        )
        assert r2["job"]["tokens"] == 150

        rows = store.list_jobs(kind="mine")
        assert len(rows) == 1
        assert rows[0]["tokens"] == 150

        rep = store.spend_report("job-1")
        assert rep["summary"]["total_tokens"] == 150
        assert rep["summary"]["request_count"] == 2
        assert "grok" in rep["by_source"]

        store.set_status("job-1", "completed")
        assert store.get("job-1")["status"] == "completed"


def test_invalid_status(tmp_path: Path):
    with OpsStore.open(tmp_path) as store:
        with pytest.raises(OpsError):
            store.upsert_job("x", status="not-a-status")


def test_ensure_job_idempotent(tmp_path: Path):
    with OpsStore.open(tmp_path) as store:
        a = store.ensure_job("e1", kind="task", title="first", status="running")
        b = store.ensure_job("e1", kind="task", title="ignored", status="completed")
        assert a["id"] == b["id"]
        # ensure does not clobber status
        assert store.get("e1")["status"] == "running"
        assert store.get("e1")["title"] == "first"


def test_usage_dual_write_to_ops(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    um.save_budget(
        um.Budget(enabled=False, daily_tokens=1_000_000, monthly_tokens=10_000_000),
        tmp_path,
    )
    gate = um.record(
        80,
        source="agent:coder",
        label="step",
        meta={"task_id": "t-ops-1", "kind": "task", "agent": "coder"},
        workdir=tmp_path,
        enforce=False,
    )
    assert gate.get("ops_job_id") == "t-ops-1"
    with OpsStore.open(tmp_path) as store:
        job = store.get("t-ops-1")
        assert job is not None
        assert job["tokens"] == 80
        assert store.spend_report("t-ops-1")["summary"]["total_tokens"] == 80


def test_ops_dual_write_usage_no_double_count(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    um.save_budget(
        um.Budget(enabled=False, daily_tokens=1_000_000, monthly_tokens=10_000_000),
        tmp_path,
    )
    with OpsStore.open(tmp_path) as store:
        store.record_spend(
            "t-dual",
            40,
            source="ops",
            label="manual",
            dual_write_usage=True,
            ensure=True,
            kind="task",
        )
        assert store.get("t-dual")["tokens"] == 40
    # usage ledger has one row; ops should not have doubled
    roll = um.by_task("t-dual", tmp_path)
    assert roll["total_tokens"] == 40
    with OpsStore.open(tmp_path) as store:
        assert store.get("t-dual")["tokens"] == 40


def test_ingest_usage_ledger(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    um.save_budget(um.Budget(enabled=False), tmp_path)
    # write ledger without going through ops (simulate old rows)
    # use _ops_skip so record doesn't also hit ops
    um.record(
        25,
        source="old",
        label="pre",
        meta={"task_id": "legacy-1", "_ops_skip": True},
        workdir=tmp_path,
        enforce=False,
    )
    with OpsStore.open(tmp_path) as store:
        assert store.get("legacy-1") is None
        res = store.ingest_usage_ledger()
        assert res["imported"] == 1
        assert "legacy-1" in res["jobs_touched"]
        assert store.get("legacy-1")["tokens"] == 25
        # second ingest is idempotent
        res2 = store.ingest_usage_ledger()
        assert res2["imported"] == 0
        assert store.get("legacy-1")["tokens"] == 25


def test_note_helpers(tmp_path: Path):
    j = note_improve_run(tmp_path, "ia-abc", phase="briefed", repo="ahmedEid1/lumen")
    assert j is not None
    assert j["kind"] == "improve"
    j2 = note_improve_run(
        tmp_path, "ia-abc", phase="done", repo="ahmedEid1/lumen", status="completed"
    )
    assert j2["status"] == "completed"
    a = note_alive_cycle(tmp_path, {"ok": True, "goal": "self-improve", "cycle": 3})
    assert a is not None
    assert a["kind"] == "alive"


def test_improve_apply_registers_ops_job(tmp_path: Path):
    run = ia.start_run(tmp_path, dry_run=True)
    with OpsStore.open(tmp_path) as store:
        job = store.get(run.run_id)
        assert job is not None
        assert job["kind"] == "improve"
        assert job["status"] == "running"
    run.run_to_done()
    with OpsStore.open(tmp_path) as store:
        job = store.get(run.run_id)
        assert job["status"] == "completed"
        assert job["meta"].get("phase") == "done"


def test_cli_ops_list_and_record(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from nexus.cli import main

    rc = main(
        [
            "ops",
            "record",
            "cli-job",
            "--tokens",
            "12",
            "--kind",
            "mine",
            "--title",
            "cli test",
            "--path",
            str(tmp_path),
        ]
    )
    assert rc == 0
    capsys.readouterr()  # drop record output
    rc = main(["ops", "list", "--json", "--path", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert any(r["id"] == "cli-job" and r["tokens"] == 12 for r in rows)

    rc = main(["ops", "status", "--path", str(tmp_path)])
    assert rc == 0


def test_mcp_ops_control(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    # record via MCP
    res = mcp_server.call_tool(
        "ops_control",
        {
            "action": "record",
            "job_id": "mcp-1",
            "tokens": 7,
            "kind": "alive",
            "source": "test",
        },
    )
    assert not res.get("isError")
    res2 = mcp_server.call_tool("ops_control", {"action": "list", "kind": "alive"})
    assert not res2.get("isError")
    body = res2["content"][0]["text"]
    rows = json.loads(body)
    assert any(r["id"] == "mcp-1" for r in rows)
    res3 = mcp_server.call_tool("ops_control", {"action": "status"})
    assert not res3.get("isError")


def test_job_statuses_cover_plane():
    assert "running" in JOB_STATUSES
    assert "completed" in JOB_STATUSES
    assert "blocked" in JOB_STATUSES
