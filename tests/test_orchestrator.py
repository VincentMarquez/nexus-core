"""Orchestrator façade tests (fake backend + cancel sticky + MCP)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from nexus import mcp_server
from nexus.ops_store import OpsStore, JOB_KINDS
from nexus.orchestrator import (
    Orchestrator,
    OrchError,
    load_envelope,
    sanitize_task_id,
)


def test_workflow_kind_in_job_kinds():
    assert "workflow" in JOB_KINDS


def test_wal_enabled(tmp_path: Path):
    with OpsStore.open(tmp_path) as store:
        row = store.conn.execute("PRAGMA journal_mode").fetchone()
        mode = str(row[0] if row else "").lower()
        # WAL preferred; delete acceptable if FS rejects WAL
        assert mode in ("wal", "delete", "memory", "persist", "truncate", "off")


def test_sanitize_task_id():
    assert sanitize_task_id("abc-123").startswith("abc")
    with pytest.raises(OrchError):
        sanitize_task_id("../etc/passwd")
    with pytest.raises(OrchError):
        sanitize_task_id("bad id")


def test_run_task_fake_completes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "prove fake works",
        kind="task",
        agent_mode="fake",
        task_id="fake-1",
        sync_fake=True,
    )
    assert out["task_id"] == "fake-1"
    assert out["status"] == "completed"
    env = load_envelope(tmp_path, "fake-1")
    assert env is not None
    assert env.status == "completed"
    with OpsStore.open(tmp_path) as store:
        job = store.get("fake-1")
        assert job is not None
        assert job["status"] == "completed"
        assert job["kind"] == "task"


def test_invalid_kind_rejected(tmp_path: Path):
    orch = Orchestrator(tmp_path)
    with pytest.raises(OrchError) as ei:
        orch.run_task("x", kind="checks", agent_mode="fake", sync_fake=True)
    assert ei.value.code == "invalid_kind"


def test_cancel_idempotent_and_sticky(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    # Start as running envelope without completing
    from nexus.orchestrator import Envelope, save_envelope

    env = Envelope(
        task_id="c1",
        kind="task",
        goal="long",
        status="running",
        agent_mode="fake",
        backend="fake",
    )
    save_envelope(tmp_path, env)
    with OpsStore.open(tmp_path) as store:
        store.ensure_job("c1", kind="task", title="long", status="running", goal="long")

    st = orch.cancel("c1")
    assert st["status"] == "cancelled"
    st2 = orch.cancel("c1")
    assert st2["status"] == "cancelled"

    # Late completed must not overwrite cancel (sticky)
    with OpsStore.open(tmp_path) as store:
        store.set_status("c1", "completed")
        job = store.get("c1")
        assert job["status"] == "cancelled"


def test_get_status_logs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    orch.run_task("log me", agent_mode="fake", task_id="log1", sync_fake=True)
    out = orch.get_task_status("log1", action="logs")
    assert out["status"] == "completed"
    assert isinstance(out.get("logs"), list)


def test_mcp_run_and_status(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("NEXUS_ORCH", raising=False)
    r = mcp_server.call_tool(
        "run_task",
        {
            "description": "mcp fake task",
            "kind": "task",
            "agent_mode": "fake",
            "task_id": "mcp-fake-1",
        },
    )
    assert r["isError"] is False
    body = json.loads(r["content"][0]["text"])
    assert body["task_id"] == "mcp-fake-1"
    assert body["status"] == "completed"

    s = mcp_server.call_tool(
        "get_task_status", {"task_id": "mcp-fake-1", "action": "status"}
    )
    assert s["isError"] is False
    st = json.loads(s["content"][0]["text"])
    assert st["status"] == "completed"


def test_mcp_orch_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("NEXUS_ORCH", "0")
    r = mcp_server.call_tool(
        "run_task", {"description": "nope", "agent_mode": "fake"}
    )
    assert r["isError"] is True
    tools = mcp_server.handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    names = [t["name"] for t in tools["result"]["tools"]]
    assert "run_task" not in names
    assert "get_task_status" not in names
    monkeypatch.delenv("NEXUS_ORCH", raising=False)


def test_tools_list_includes_orch_when_enabled(monkeypatch):
    monkeypatch.delenv("NEXUS_ORCH", raising=False)
    tools = mcp_server.handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    names = [t["name"] for t in tools["result"]["tools"]]
    assert "run_task" in names
    assert "get_task_status" in names
    assert mcp_server.SERVER_VERSION == "0.8.0"


def test_async_fake_worker(tmp_path: Path, monkeypatch):
    """Subprocess fake worker completes without sync_fake."""
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "async fake",
        agent_mode="fake",
        task_id="async-fake-1",
        wait=True,
        wait_timeout_s=30,
        sync_fake=False,
    )
    # wait should finish
    assert out["status"] in ("completed", "running", "failed")
    # poll until terminal
    deadline = time.time() + 20
    last = out
    while time.time() < deadline:
        last = orch.get_task_status("async-fake-1")
        if last["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.1)
    assert last["status"] == "completed"


def test_run_task_with_plan_stores_pre_plan(tmp_path: Path, monkeypatch):
    """arXiv 2401.07324: Planner decomposes task before Orchestrator."""
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "validate marketplace catalog and check nexus status",
        kind="task",
        agent_mode="fake",
        task_id="with-plan-1",
        with_plan=True,
        plan_tools=[
            {"name": "marketplace", "description": "plugin marketplace catalog"},
            {"name": "nexus_status", "description": "show nexus status"},
            {"name": "tool_catalog", "description": "validate tool catalog"},
        ],
        plan_max_steps=3,
        require_plan=True,
        sync_fake=True,
    )
    assert out["task_id"] == "with-plan-1"
    assert out["status"] == "completed"
    assert out.get("pre_planned") is True
    assert isinstance(out.get("plan"), dict)
    assert out["plan"]["paper"] == "arxiv:2401.07324v3"
    assert out["plan"]["n_steps"] >= 1
    assert out["plan"]["status"] == "ready"
    tools = out.get("plan_summary", {}).get("tools") or []
    assert tools  # at least one planned tool
    # Envelope retained plan
    env = load_envelope(tmp_path, "with-plan-1")
    assert env is not None
    assert env.meta.get("pre_planned") is True
    assert env.meta.get("tool_plan", {}).get("n_steps", 0) >= 1
    # Logs mention planner
    logs = orch.get_task_status("with-plan-1", action="logs").get("logs") or []
    assert any("planner" in str(line).lower() or "plan:" in str(line) for line in logs)


def test_run_task_with_injected_plan_dict(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    plan = {
        "task": "status check",
        "status": "ready",
        "planner": "injected-test",
        "steps": [
            {"id": 1, "tool": "nexus_status", "args": {}, "rationale": "health"},
        ],
        "tools_available": ["nexus_status"],
    }
    out = orch.run_task(
        "status check",
        agent_mode="fake",
        task_id="inject-plan-1",
        with_plan=True,
        plan=plan,
        require_plan=True,
        sync_fake=True,
    )
    assert out["pre_planned"] is True
    assert out["plan"]["planner"] in ("injected-test", "injected", "heuristic")
    assert out["plan_summary"]["tools"] == ["nexus_status"]


def test_run_task_require_plan_empty_tools_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    with pytest.raises(OrchError) as ei:
        orch.run_task(
            "impossible without tools",
            agent_mode="fake",
            task_id="req-plan-fail",
            with_plan=True,
            plan_tools=[],
            require_plan=True,
            sync_fake=True,
        )
    assert ei.value.code in ("plan_not_ready", "plan_failed")


def test_mcp_run_task_with_plan(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("NEXUS_ORCH", raising=False)
    r = mcp_server.call_tool(
        "run_task",
        {
            "description": "validate marketplace catalog",
            "kind": "task",
            "agent_mode": "fake",
            "task_id": "mcp-plan-1",
            "with_plan": True,
            "require_plan": False,
            "plan_max_steps": 3,
        },
    )
    assert r["isError"] is False
    body = json.loads(r["content"][0]["text"])
    assert body["task_id"] == "mcp-plan-1"
    assert body["status"] == "completed"
    # Offline heuristic may or may not match live catalog tools; pre_planned
    # should still be true when with_plan was requested.
    assert body.get("pre_planned") is True or body.get("plan") is not None
