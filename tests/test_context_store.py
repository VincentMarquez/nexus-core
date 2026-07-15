"""Tests for SQLite MCP context store + verify-before-done demo loop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.context_store import (
    ContextStore,
    ContextStoreError,
    StageOrderError,
    VerifyError,
    can_advance,
    format_demo_report,
    run_demo_loop,
)


def test_context_kv_crud(tmp_path: Path):
    with ContextStore.open(tmp_path) as store:
        run = store.create_run(goal="kv test", run_id="r-kv")
        assert run["id"] == "r-kv"
        store.context_set("r-kv", "session.agent", "mine", agent="mine")
        got = store.context_get("r-kv", "session.agent")
        assert got is not None
        assert got["value"] == "mine"
        store.context_set("r-kv", "grade.last", {"total": 15.0}, agent="grade")
        parsed = store.context_get("r-kv", "grade.last")
        assert parsed["value"]["total"] == 15.0
        full = store.context_get("r-kv")
        assert "session.agent" in full
        assert "grade.last" in full


def test_handoff_across_agents(tmp_path: Path):
    with ContextStore.open(tmp_path) as store:
        store.create_run(run_id="r-ho")
        body = store.handoff(
            "r-ho",
            from_agent="research",
            to_agent="mine",
            summary="papers ready",
            payload={"n": 10},
        )
        assert body["from"] == "research"
        assert body["to"] == "mine"
        last = store.context_get("r-ho", "handoff.last")
        assert last["value"]["summary"] == "papers ready"
        mine = store.context_get("r-ho", "handoff.mine")
        assert mine["value"]["from"] == "research"
        dec = store.list_decisions("r-ho")
        assert any("handoff" in d["why"] for d in dec)


def test_illegal_stage_jump(tmp_path: Path):
    with ContextStore.open(tmp_path) as store:
        store.create_run(run_id="r-ord")
        with pytest.raises(StageOrderError):
            store.mark_stage("r-ord", "apply")
        store.mark_stage("r-ord", "research_ingest")
        store.mark_stage("r-ord", "mine_rank")
        assert store.next_stage("r-ord") == "plan_item"


def test_done_rejected_without_verify_and_grade(tmp_path: Path):
    with ContextStore.open(tmp_path) as store:
        store.create_run(run_id="r-done")
        for s in (
            "research_ingest",
            "mine_rank",
            "plan_item",
            "apply",
            "verify",
            "grade",
        ):
            store.mark_stage("r-done", s)
        with pytest.raises(StageOrderError, match="verified claim"):
            store.mark_done("r-done")

        # claim without verify still fails
        store.add_claim(
            "r-done",
            "x",
            evidence_paths=["missing.txt"],
            verified=False,
        )
        with pytest.raises(StageOrderError, match="verified claim"):
            store.mark_done("r-done")

        # verified claim but no grade
        c = store.add_claim(
            "r-done",
            "loop proved",
            evidence_paths=[],
            verified=True,
        )
        assert c["verified"] is True
        with pytest.raises(StageOrderError, match="grade"):
            store.mark_done("r-done")

        store.add_grade("r-done", total=15.0, idea=7.0, skill=8.0, method="test")
        out = store.mark_done("r-done")
        assert out["ok"] is True
        assert store.get_run("r-done")["status"] == "done"


def test_verify_claims_paths(tmp_path: Path):
    evidence = tmp_path / ".nexus_workspaces" / "demo_loop" / "ev.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("ok\n", encoding="utf-8")
    rel = ".nexus_workspaces/demo_loop/ev.txt"

    with ContextStore.open(tmp_path) as store:
        store.create_run(run_id="r-v")
        store.add_claim("r-v", "exists", evidence_paths=[rel], verified=False)
        rep = store.verify_claims("r-v")
        assert rep["ok"] is True
        assert rep["n_verified"] == 1
        assert store.list_claims("r-v")[0]["verified"] is True

        store.add_claim("r-v", "missing", evidence_paths=["no/such/file"], verified=False)
        rep2 = store.verify_claims("r-v")
        assert rep2["ok"] is False


def test_demo_loop_full(tmp_path: Path):
    report = run_demo_loop(tmp_path, run_id="demo-1")
    assert report["ok"] is True
    assert report["status"] == "done"
    assert report["run_id"] == "demo-1"
    assert "verify" in report["stages_completed"]
    assert "grade" in report["stages_completed"]
    assert report["grade"] is not None
    assert float(report["grade"]["total"]) == 15.0
    assert any(c.get("verified") for c in report["claims"])
    text = format_demo_report(report)
    assert "demo-loop" in text
    assert "YES" in text

    # DB artifact exists
    db = tmp_path / ".nexus_state" / "context" / "context.sqlite"
    assert db.is_file()


def test_demo_loop_restart_resume(tmp_path: Path):
    mid = run_demo_loop(tmp_path, run_id="demo-resume", stop_after="apply")
    assert mid["ok"] is True
    assert mid["status"] != "done"
    assert "apply" in mid["stages_completed"]
    assert "verify" not in mid["stages_completed"]

    fin = run_demo_loop(tmp_path, run_id="demo-resume")
    assert fin["ok"] is True
    assert fin["resumed"] is True
    assert fin["status"] == "done"
    assert "verify" in fin["stages_completed"]
    assert "grade" in fin["stages_completed"]


def test_can_advance_helper():
    assert can_advance("research_ingest", "research_ingest", completed=[]) is True
    assert can_advance("research_ingest", "apply", completed=[]) is False
    assert (
        can_advance(
            "mine_rank",
            "mine_rank",
            completed=["research_ingest"],
        )
        is True
    )


def _tool_text(res: dict) -> str:
    parts = res.get("content") or []
    if parts and isinstance(parts[0], dict):
        return str(parts[0].get("text") or "")
    return json.dumps(res, default=str)


def test_mcp_context_tools(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    from nexus import mcp_server as ms

    names = {t["name"] for t in ms.TOOLS}
    assert "context_get" in names
    assert "context_set" in names
    assert "handoff" in names
    assert "demo_loop" in names

    out = ms.call_tool(
        "demo_loop", {"run_id": "mcp-demo", "stop_after": "plan_item"}
    )
    text = _tool_text(out)
    assert "mcp-demo" in text
    assert out.get("isError") is not True

    r2 = ms.call_tool(
        "context_set",
        {"run_id": "mcp-demo", "key": "foo", "value": "bar", "agent": "test"},
    )
    assert "bar" in _tool_text(r2)

    r3 = ms.call_tool("context_get", {"run_id": "mcp-demo", "key": "foo"})
    assert "bar" in _tool_text(r3)

    r4 = ms.call_tool(
        "handoff",
        {
            "run_id": "mcp-demo",
            "from_agent": "a",
            "to_agent": "b",
            "summary": "hi",
        },
    )
    ht = _tool_text(r4)
    assert "a" in ht and "b" in ht


def test_cli_demo_loop(tmp_path: Path):
    from nexus.cli import main

    rc = main(
        [
            "improve",
            "demo-loop",
            "--path",
            str(tmp_path),
            "--run-id",
            "cli-demo",
            "--json",
        ]
    )
    assert rc == 0
    db = tmp_path / ".nexus_state" / "context" / "context.sqlite"
    assert db.is_file()


def test_tool_privilege_map_has_context_tools():
    from nexus.tool_catalog import TOOL_PRIVILEGE

    assert TOOL_PRIVILEGE.get("context_get") == "read"
    assert TOOL_PRIVILEGE.get("context_set") == "write"
    assert TOOL_PRIVILEGE.get("handoff") == "write"
    assert TOOL_PRIVILEGE.get("demo_loop") == "ops"
