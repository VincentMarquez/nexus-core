"""Tests: FutureWeaver × mission-control budget plane hybrid."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.budget_alloc import BudgetAllocator, AllocationExhausted
from nexus.budget_plane import (
    SCHEMA,
    PAPER,
    SOURCE_PATTERN,
    BudgetPlane,
    BudgetPlaneError,
    agent_source,
    agent_spend_report,
    dispatch,
    format_operator_table,
    parse_agent_source,
)
from nexus.ops_store import OpsStore


def test_agent_source_helpers():
    assert agent_source("implementer") == "agent:implementer"
    assert parse_agent_source("agent:planner") == "planner"
    assert parse_agent_source("grok") is None


def test_agent_spend_report_with_plan(tmp_path: Path):
    alloc = BudgetAllocator.plan(
        ["a", "b"], total_tokens=100, strategy="equal", hard=True
    )
    rows = [
        {"tokens": 10, "cost": 0.0, "source": "agent:a", "meta": {}},
        {"tokens": 5, "cost": 0.0, "source": "agent:b", "meta": {"agent": "b"}},
        {"tokens": 3, "cost": 0.0, "source": "manual", "meta": {}},
    ]
    rep = agent_spend_report(rows, alloc=alloc)
    assert rep["schema"] == SCHEMA
    assert rep["paper"] == PAPER
    assert rep["source_pattern"] == SOURCE_PATTERN
    assert rep["agents"]["a"]["tokens_used"] == 10
    assert rep["agents"]["a"]["planned_max_tokens"] == 50
    assert rep["agents"]["b"]["tokens_used"] == 5
    assert rep["unattributed"]["total_tokens"] == 3
    assert rep["summary"]["total_tokens"] == 18


def test_plan_bind_record_hard_limit(tmp_path: Path):
    with OpsStore.open(tmp_path) as store:
        plane = BudgetPlane(store)
        out = plane.plan(
            "job-bp-1",
            total_tokens=100,
            strategy="equal",
            agents=["a", "b"],
            title="hybrid budget",
            goal="track compute",
        )
        assert out["bound"] is True
        assert out["budget_alloc"]["total_tokens"] == 100
        job = store.get("job-bp-1")
        assert job is not None
        assert job["status"] == "running"
        assert "budget_alloc" in (job.get("meta") or {})
        agents = (job["meta"]["budget_alloc"]).get("agents") or {}
        assert set(agents.keys()) == {"a", "b"}

        share = int(agents["a"]["max_tokens"])
        r1 = plane.record("job-bp-1", "a", tokens=share // 2)
        assert r1["receipt"]["ok"] is True
        assert r1["spend"]["tokens"] == share // 2
        assert r1["spend"]["source"] == "agent:a"

        plane.record("job-bp-1", "a", tokens=share - share // 2)
        with pytest.raises(BudgetPlaneError) as ei:
            plane.record("job-bp-1", "a", tokens=1)
        assert ei.value.code == "budget_exhausted"

        # durable: reload allocator from SQLite
        alloc2 = plane.load_alloc("job-bp-1")
        assert alloc2.agents["a"].tokens_used == share


def test_modular_finish_rebalance_on_plane(tmp_path: Path):
    with OpsStore.open(tmp_path) as store:
        plane = BudgetPlane(store)
        plane.plan(
            "mod-1",
            total_tokens=200,
            strategy="modular",
            agents=["planner", "implementer"],
        )
        plane.record("mod-1", "planner", tokens=5)
        out = plane.record(
            "mod-1", "planner", tokens=0, finish=True, rebalance=True
        )
        assert out["finish"]["finished"] is True
        assert out["finish"]["reclaimed_tokens"] >= 0
        impl = out["budget_alloc"]["agents"]["implementer"]
        # implementer should still be active; residual may have been given
        assert impl["finished"] is False
        st = plane.status("mod-1")
        assert "planner" in st["agent_report"]["agents"]
        assert st["brief"]
        table = format_operator_table(st)
        assert "agent spend board" in table or "compute budget" in table


def test_dispatch_plan_only_and_bound(tmp_path: Path):
    pure = dispatch(
        "plan",
        workdir=tmp_path,
        total_tokens=90,
        strategy="weighted",
        agents="planner,implementer",
    )
    assert pure["bound"] is False
    assert pure["budget_alloc"]["total_tokens"] == 90
    assert "implementer" in pure["budget_alloc"]["agents"]

    bound = dispatch(
        "plan",
        workdir=tmp_path,
        job_id="d1",
        total_tokens=90,
        strategy="equal",
        agents=["x", "y"],
    )
    assert bound["bound"] is True
    assert bound["job_id"] == "d1"

    rec = dispatch(
        "record",
        workdir=tmp_path,
        job_id="d1",
        agent="x",
        tokens=10,
    )
    assert rec["receipt"]["ok"] is True

    st = dispatch("status", workdir=tmp_path, job_id="d1")
    assert st["budget_alloc"]["tokens_used"] == 10
    assert st["agent_report"]["agents"]["x"]["tokens_used"] == 10

    rep = dispatch("report", workdir=tmp_path, job_id="d1")
    assert rep["agents"]["x"]["tokens_used"] == 10


def test_dispatch_unknown_action(tmp_path: Path):
    with pytest.raises(BudgetPlaneError) as ei:
        dispatch("explode", workdir=tmp_path)
    assert ei.value.code == "unknown_action"


def test_orchestrator_uses_full_budget_on_ops(tmp_path: Path, monkeypatch):
    """When compute_budget is planned, ops job meta gets full allocator via plane."""
    from nexus.orchestrator import Orchestrator

    monkeypatch.setenv("NEXUS_ORCH_SYNC_FAKE", "1")
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "budget plane wire",
        task_id="bp-orch-1",
        agent_mode="fake",
        meta={
            "compute_budget": {
                "total_tokens": 120,
                "strategy": "equal",
                "agents": ["a", "b"],
            }
        },
        sync_fake=True,
    )
    assert out.get("compute_budget_planned") is True
    with OpsStore.open(tmp_path) as store:
        job = store.get("bp-orch-1")
        assert job is not None
        meta = job.get("meta") or {}
        # full agents dict (not just name list) after bind
        ba = meta.get("budget_alloc")
        assert isinstance(ba, dict)
        assert isinstance(ba.get("agents"), dict)
        assert "a" in ba["agents"]
        assert ba["agents"]["a"].get("max_tokens", 0) > 0

    # record via orchestrator still works; plane-compatible spend
    r = orch.record_agent_usage("bp-orch-1", "a", tokens=10)
    assert r["budget_alloc"]["agents"]["a"]["tokens_used"] == 10
    with OpsStore.open(tmp_path) as store:
        rows = store.spend_rows("bp-orch-1")
        assert any(r.get("source") == "agent:a" for r in rows)
        # ops meta still holds allocator (updated if plane path used)
        plane = BudgetPlane(store)
        # may load from ops if full dict present
        try:
            alloc = plane.load_alloc("bp-orch-1")
            assert "a" in alloc.agents
        except BudgetPlaneError:
            # acceptable if only envelope path updated; status via orch still ok
            st = orch.get_compute_budget("bp-orch-1")
            assert st["budget_alloc"]["agents"]["a"]["tokens_used"] == 10


def test_cli_ops_budget(tmp_path: Path, capsys):
    from nexus import cli as ncli
    import argparse

    ns = argparse.Namespace(
        ops_cmd="budget",
        budget_cmd="plan",
        path=str(tmp_path),
        job_id="cli-1",
        total_tokens=80,
        strategy="equal",
        agents="p,i",
        hard=True,
        title="cli",
        goal="g",
        kind="task",
        json=True,
        agent=None,
        tokens=0,
        steps=0,
        finish=False,
        rebalance=False,
        status=None,
        limit=100,
    )
    rc = ncli.cmd_ops(ns)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["bound"] is True
    assert out["job_id"] == "cli-1"

    ns2 = argparse.Namespace(
        ops_cmd="budget",
        budget_cmd="record",
        path=str(tmp_path),
        job_id="cli-1",
        agent="p",
        tokens=5,
        steps=0,
        finish=False,
        rebalance=False,
        json=True,
        total_tokens=0,
        strategy="equal",
        agents=None,
        hard=True,
        title="",
        goal="",
        kind="task",
        status=None,
        limit=100,
    )
    assert ncli.cmd_ops(ns2) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["receipt"]["ok"] is True


def test_mcp_compute_budget(tmp_path: Path, monkeypatch):
    from nexus import mcp_server as mcp

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))

    # list tools includes compute_budget
    names = [t["name"] for t in mcp._listed_tools()]
    assert "compute_budget" in names

    r = mcp.call_tool(
        "compute_budget",
        {
            "action": "plan",
            "job_id": "mcp-1",
            "total_tokens": 60,
            "strategy": "equal",
            "agents": "a,b",
        },
    )
    text = r["content"][0]["text"]
    data = json.loads(text)
    assert data["bound"] is True

    r2 = mcp.call_tool(
        "compute_budget",
        {"action": "record", "job_id": "mcp-1", "agent": "a", "tokens": 10},
    )
    data2 = json.loads(r2["content"][0]["text"])
    assert data2["receipt"]["ok"] is True

    r3 = mcp.call_tool(
        "compute_budget",
        {"action": "status", "job_id": "mcp-1"},
    )
    data3 = json.loads(r3["content"][0]["text"])
    assert data3["budget_alloc"]["tokens_used"] == 10
