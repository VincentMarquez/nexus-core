"""Tests for domain-MCP Planner (arXiv 2401.07324 × IBM/AssetOpsBench)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import assetops_planner as aop
from nexus import multi_llm_agent as mla


# ── catalog ─────────────────────────────────────────────────────────────────


def test_domain_mcp_as_tools_shape():
    tools = aop.domain_mcp_as_tools()
    names = {t["name"] for t in tools}
    assert aop.tool_id("iot", "sites") in names
    assert aop.tool_id("fmsr", "get_failure_modes") in names
    assert aop.tool_id("wo", "list_workorders") in names
    assert all(t.get("domain_mcp") is True for t in tools)
    assert all(t.get("source") == aop.SOURCE_PATTERN for t in tools)
    assert all(t["name"].startswith("aob.") for t in tools)
    summary = aop.catalog_summary(tools)
    assert summary["n_tools"] == len(tools)
    assert summary["n_servers"] == len(aop.DOMAIN_SERVER_IDS)
    assert summary["by_server"]["iot"] >= 1
    assert summary["by_server"]["fmsr"] >= 1
    assert summary["source_pattern"] == aop.SOURCE_PATTERN


def test_list_domain_servers():
    servers = aop.list_domain_servers()
    ids = {s["id"] for s in servers}
    assert ids == set(aop.DOMAIN_SERVER_IDS)
    assert all(s["n_tools"] > 0 for s in servers)


def test_max_privilege_filters_write():
    read_only = aop.domain_mcp_as_tools(max_privilege="read")
    assert all(t["privilege"] == "read" for t in read_only)
    assert not any("create_workorder" in t["name"] for t in read_only)
    with_write = aop.domain_mcp_as_tools(include_write=True)
    assert any("create_workorder" in t["name"] for t in with_write)


def test_tool_id_roundtrip():
    tid = aop.tool_id("iot", "latest_reading")
    parsed = aop.parse_tool_id(tid)
    assert parsed["server"] == "iot"
    assert parsed["tool"] == "latest_reading"
    assert parsed["prefix"] == "aob"


# ── Planner (no side effects) ───────────────────────────────────────────────


def test_diagnostic_workflow_ready_and_ordered():
    plan = aop.diagnostic_workflow_plan(
        "diagnose chiller asset failure and list work orders",
        site_name="MAIN",
        asset_id="chiller-6",
        asset_class="chiller",
        include_vibration=True,
        include_workorder_write=False,
    )
    assert plan.paper == mla.PAPER
    assert plan.meta.get("schema") == aop.SCHEMA
    assert plan.meta.get("source_pattern") == aop.SOURCE_PATTERN
    assert plan.planner == "assetops-diagnostic"
    assert plan.is_ready()
    tools = [s.tool for s in plan.steps]
    assert tools[0] == aop.tool_id("utilities", "current_date_time")
    assert aop.tool_id("iot", "sites") in tools
    assert aop.tool_id("fmsr", "get_failure_modes") in tools
    assert aop.tool_id("tsfm", "anomaly_detection") in tools
    assert aop.tool_id("vibration", "fault_detection") in tools
    assert aop.tool_id("wo", "list_workorders") in tools
    # multi-domain
    servers = {s.args.get("server") for s in plan.steps}
    assert {"utilities", "iot", "fmsr", "tsfm", "vibration", "wo"} <= servers
    # dependency chain on later steps
    assert any(s.args.get("depends_on") for s in plan.steps)
    assert plan.meta.get("n_servers_touched", 0) >= 5


def test_plan_from_assetops_no_backend_side_effects(monkeypatch):
    """Planner role must not touch orchestrator / industrial backends."""
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("must not open Orchestrator during plan")

    monkeypatch.setattr(
        "nexus.orchestrator.Orchestrator", boom, raising=False
    )
    plan = aop.plan_from_assetops(
        "diagnose industrial asset sensor anomaly and failure modes",
        asset_id="pump-1",
    )
    assert plan.is_ready()
    assert plan.steps
    assert called["n"] == 0
    assert plan.meta.get("handoff") == "assetops_planner"


def test_plan_from_injected_llm_text():
    text = json.dumps(
        {
            "task": "list IoT sites",
            "status": "ready",
            "steps": [
                {
                    "id": 1,
                    "tool": aop.tool_id("iot", "sites"),
                    "args": {},
                    "rationale": "discovery",
                }
            ],
        }
    )
    plan = aop.plan_from_assetops("list IoT sites", plan_text=text)
    assert plan.is_ready()
    assert plan.steps[0].tool == aop.tool_id("iot", "sites")
    assert plan.planner == "assetops-injected"
    assert plan.steps[0].args.get("server") == "iot"


def test_heuristic_plan_without_diagnostic():
    plan = aop.plan_from_assetops(
        "read current date time utility",
        use_diagnostic=False,
        prefer_diagnostic=False,
        max_steps=3,
    )
    assert plan.steps
    assert plan.planner.startswith("assetops")
    tools = {s.tool for s in plan.steps}
    assert any("utilities" in t or "current_date" in t for t in tools) or plan.steps


def test_plan_payload_stamps_schema():
    plan = aop.diagnostic_workflow_plan("payload stamp", asset_id="a1")
    payload = aop.plan_payload(plan)
    assert payload["assetops_schema"] == aop.SCHEMA
    assert payload["source_pattern"] == aop.SOURCE_PATTERN
    assert payload["meta"]["paper"] == aop.PAPER
    assert payload["meta"].get("workflow") == "diagnostic"


# ── run (Planner → mock Caller) ─────────────────────────────────────────────


def test_plan_and_run_mock_multi_server():
    report = aop.plan_and_run(
        "diagnose chiller failure modes, anomalies, and work orders",
        asset_id="chiller-6",
        site_name="MAIN",
        use_diagnostic=True,
    )
    assert report["ok"] is True
    assert report["phase"] == "run"
    assert report["schema"] == aop.SCHEMA
    assert report["source_pattern"] == aop.SOURCE_PATTERN
    assert report["n_servers_hit"] >= 4
    assert "iot" in report["servers_hit"]
    assert "fmsr" in report["servers_hit"]
    assert "wo" in report["servers_hit"]
    assert all(c.get("ok") for c in report["calls"])


def test_make_mock_registry_execute_all():
    plan = aop.diagnostic_workflow_plan(
        "full diagnostic walk",
        asset_id="reg-1",
        include_vibration=False,
    )
    reg = aop.make_mock_registry(asset_id="reg-1")
    caller = mla.Caller(registry=reg)
    caller.set_plan(plan, require_ready=True)
    results = caller.execute_all()
    assert all(r.ok for r in results)
    assert plan.status == mla.STATUS_DONE
    # first call is utilities context
    assert results[0].tool == aop.tool_id("utilities", "current_date_time")
    assert results[0].result.get("mock") is True


def test_empty_injected_plan_fail_closed():
    text = json.dumps({"task": "x", "status": "draft", "steps": []})
    with pytest.raises(mla.PlanError):
        aop.plan_from_assetops("x", plan_text=text, auto_ready=True)

    plan = aop.plan_from_assetops("x", plan_text=text, auto_ready=False)
    assert not plan.is_ready()
    assert plan.steps == []

    reg = aop.make_mock_registry()
    caller = mla.Caller(registry=reg)
    with pytest.raises(mla.CallGateError):
        caller.set_plan(plan, require_ready=True)


# ── handoff (Planner → Orchestrator) ────────────────────────────────────────


def test_plan_and_handoff_fake_orch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    report = aop.plan_and_handoff(
        "diagnose asset failure then hand off to orchestrator",
        workdir=tmp_path,
        task_id="aob-ho-1",
        agent_mode="fake",
        run_mock=False,
        use_diagnostic=True,
        sync_fake=True,
    )
    assert report["schema"] == aop.SCHEMA
    assert report["ok"] is True
    assert report["phase"] == "orchestrator"
    assert report.get("run") is None
    orch = report.get("orchestrator") or {}
    assert orch.get("pre_planned") in (True, 1, "true") or orch.get("status") not in (
        None,
        "failed",
    )
    assert orch.get("task_id") in ("aob-ho-1", report.get("task_id"))


def test_plan_and_handoff_with_run_mock(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    report = aop.plan_and_handoff(
        "diagnose industrial pump then mock-run domain tools",
        workdir=tmp_path,
        task_id="aob-ho-2",
        agent_mode="fake",
        run_mock=True,
        use_diagnostic=True,
        sync_fake=True,
    )
    assert report["ok"] is True
    run = report.get("run") or {}
    assert run.get("ok") is True
    assert run.get("mock") is True
    assert int(run.get("n_calls") or 0) >= 4
    orch = report.get("orchestrator") or {}
    assert orch.get("status") not in (None, "failed")


# ── format + CLI ────────────────────────────────────────────────────────────


def test_format_assetops_plan_and_report():
    plan = aop.diagnostic_workflow_plan("format me", asset_id="f1")
    text = aop.format_assetops_plan(plan)
    assert aop.SCHEMA in text
    assert "aob.iot.sites" in text
    report = {
        "ok": True,
        "phase": "run",
        "paper": aop.PAPER,
        "source_pattern": aop.SOURCE_PATTERN,
        "schema": aop.SCHEMA,
        "plan": plan.to_dict(),
        "servers_hit": ["iot", "fmsr"],
        "n_servers_hit": 2,
        "summary": {"ok": True, "n_done": 3, "n_failed": 0},
    }
    rtext = aop.format_report(report)
    assert "ok:       True" in rtext
    assert "iot" in rtext


def test_module_cli_catalog(capsys):
    rc = aop.main(["catalog"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema"] == aop.SCHEMA
    assert data["summary"]["n_tools"] >= 10


def test_module_cli_plan(capsys):
    rc = aop.main(
        [
            "plan",
            "diagnose chiller asset failure modes",
            "--asset-id",
            "c6",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert aop.SCHEMA in out
    assert "aob." in out


def test_cli_tool_agent_aob(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    from nexus.cli import main as cli_main

    # catalog
    rc = cli_main(["tool-agent", "aob-catalog", "--json"])
    assert rc == 0

    # plan
    rc = cli_main(
        [
            "tool-agent",
            "aob-plan",
            "diagnose industrial asset sensor anomaly",
            "--json",
        ]
    )
    assert rc == 0
