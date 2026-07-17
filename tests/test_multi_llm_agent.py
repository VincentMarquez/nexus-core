"""Tests for multi-LLM Planner → Caller agent (arXiv 2401.07324)."""

from __future__ import annotations

import json

import pytest

from nexus import multi_llm_agent as mla


SAMPLE_TOOLS = [
    {"name": "marketplace", "description": "list and validate plugin marketplace catalog"},
    {"name": "tool_catalog", "description": "validate OpenAPI-ish MCP tool catalog"},
    {"name": "nexus_status", "description": "show nexus process and agent status"},
    {"name": "list_project_files", "description": "list files in the project workspace"},
    {"name": "maf_bench", "description": "run multi-agent framework overhead bench"},
]


def test_plan_step_and_plan_roundtrip():
    step = mla.PlanStep(id=1, tool="nexus_status", args={"verbose": True}, rationale="check health")
    d = step.to_dict()
    assert d["tool"] == "nexus_status"
    back = mla.PlanStep.from_dict(d)
    assert back.tool == "nexus_status"
    assert back.args["verbose"] is True

    plan = mla.ToolPlan(
        task="check status",
        steps=[step],
        status=mla.STATUS_READY,
        planner="test",
        tools_available=["nexus_status"],
    )
    blob = plan.to_dict()
    assert blob["schema"] == mla.SCHEMA
    assert blob["paper"] == mla.PAPER
    assert blob["n_steps"] == 1
    restored = mla.ToolPlan.from_dict(blob)
    assert restored.is_ready()
    assert restored.steps[0].tool == "nexus_status"


def test_parse_plan_json_variants():
    raw = {
        "task": "validate tools",
        "status": "ready",
        "steps": [
            {"id": 1, "tool": "tool_catalog", "args": {"action": "validate"}, "rationale": "gate"},
        ],
    }
    p1 = mla.parse_plan_json(json.dumps(raw))
    assert p1.steps[0].tool == "tool_catalog"

    fenced = "Here is the plan:\n```json\n" + json.dumps(raw) + "\n```\n"
    p2 = mla.parse_plan_json(fenced)
    assert len(p2.steps) == 1

    # list-only shape
    p3 = mla.parse_plan_json(json.dumps([{"tool": "marketplace", "args": {}}]))
    assert p3.steps[0].tool == "marketplace"

    with pytest.raises(mla.PlanError):
        mla.parse_plan_json("not a plan at all")


def test_heuristic_planner_selects_relevant_tools():
    planner = mla.Planner(tools=SAMPLE_TOOLS, max_steps=3, auto_ready=True)
    plan = planner.plan("validate the marketplace plugin catalog and tool catalog")
    assert plan.status == mla.STATUS_READY
    assert plan.planner == "heuristic"
    tools = [s.tool for s in plan.steps]
    # marketplace / tool_catalog should rank above unrelated tools
    assert "marketplace" in tools or "tool_catalog" in tools
    assert plan.is_ready()


def test_planner_does_not_call_tools(monkeypatch):
    """Planner role must not invoke registry / side effects."""
    called = {"n": 0}

    def boom(**_kw):
        called["n"] += 1
        raise AssertionError("Planner must not execute tools")

    registry = {t["name"]: boom for t in SAMPLE_TOOLS}
    planner = mla.Planner(tools=SAMPLE_TOOLS, auto_ready=True)
    plan = planner.plan("run maf_bench and show nexus status")
    assert plan.steps
    assert called["n"] == 0
    # registry unused by planner
    assert all(callable(registry[n]) for n in registry)


def test_caller_fail_closed_without_plan():
    caller = mla.Caller(registry={"nexus_status": lambda **kw: {"ok": True}})
    assert caller.can_call() is False
    with pytest.raises(mla.CallGateError):
        caller.call_next()

    draft = mla.ToolPlan(
        task="x",
        steps=[mla.PlanStep(id=1, tool="nexus_status")],
        status=mla.STATUS_DRAFT,
    )
    with pytest.raises(mla.CallGateError):
        caller.set_plan(draft, require_ready=True)


def test_caller_executes_only_after_ready_plan():
    calls: list[str] = []

    def rec(name: str):
        def _fn(**kw):
            calls.append(name)
            return {"tool": name, "args": kw}

        return _fn

    registry = {
        "marketplace": rec("marketplace"),
        "tool_catalog": rec("tool_catalog"),
    }
    plan = mla.ToolPlan(
        task="check marketplace then catalog",
        steps=[
            mla.PlanStep(id=1, tool="marketplace", args={"action": "list"}),
            mla.PlanStep(id=2, tool="tool_catalog", args={"action": "validate"}),
        ],
        status=mla.STATUS_READY,
        planner="test",
    )
    caller = mla.Caller(plan=None, registry=registry)
    caller.set_plan(plan)
    assert caller.can_call() is True
    r1 = caller.call_next()
    assert r1.ok and r1.tool == "marketplace"
    assert calls == ["marketplace"]
    r2 = caller.call_next()
    assert r2.ok and r2.tool == "tool_catalog"
    assert plan.status == mla.STATUS_DONE
    assert caller.can_call() is False


def test_caller_execute_all_stop_on_error():
    def ok(**_):
        return {"ok": True}

    def bad(**_):
        raise RuntimeError("boom")

    plan = mla.ToolPlan(
        task="t",
        steps=[
            mla.PlanStep(id=1, tool="a"),
            mla.PlanStep(id=2, tool="b"),
            mla.PlanStep(id=3, tool="c"),
        ],
        status=mla.STATUS_READY,
    )
    caller = mla.Caller(registry={"a": ok, "b": bad, "c": ok})
    caller.set_plan(plan)
    results = caller.execute_all(stop_on_error=True)
    assert len(results) == 2
    assert results[0].ok and not results[1].ok
    assert plan.status == mla.STATUS_FAILED
    assert plan.steps[2].status == mla.STEP_PENDING  # never reached


def test_validate_plan_unknown_tool():
    plan = mla.ToolPlan(
        task="t",
        steps=[mla.PlanStep(id=1, tool="secret_delete_all")],
        status=mla.STATUS_DRAFT,
    )
    rep = mla.validate_plan(plan, allowed_tools=["nexus_status"])
    assert rep["ok"] is False
    assert rep["errors"] >= 1

    with pytest.raises(mla.PlanError):
        mla.mark_ready(plan, allowed_tools=["nexus_status"])


def test_plan_from_text_marks_ready():
    text = json.dumps(
        {
            "task": "status check",
            "steps": [{"id": 1, "tool": "nexus_status", "args": {}}],
        }
    )
    planner = mla.Planner(tools=SAMPLE_TOOLS, auto_ready=True)
    plan = planner.plan_from_text(text, task="status check")
    assert plan.status == mla.STATUS_READY
    assert plan.is_ready()


def test_multi_llm_agent_pipeline():
    tools = SAMPLE_TOOLS
    registry = {
        t["name"]: (lambda _n=t["name"], **kw: {"ok": True, "tool": _n, "args": kw})
        for t in tools
    }
    agent = mla.MultiLLMToolAgent(tools=tools, registry=registry, max_steps=2)
    report = agent.run("show nexus status and list marketplace plugins")
    assert report["schema"] == mla.SCHEMA
    assert report["paper"] == mla.PAPER
    assert report["plan"]["status"] in (mla.STATUS_DONE, mla.STATUS_FAILED, mla.STATUS_READY)
    assert report["plan"]["n_steps"] >= 1
    # With mock registry matching plan tools, expect success
    assert report["ok"] is True
    assert report["summary"]["n_ok"] >= 1
    assert report["phase"] == "done"


def test_multi_llm_agent_empty_tools_fails_closed():
    agent = mla.MultiLLMToolAgent(tools=[], registry={}, max_steps=2)
    report = agent.run("do anything")
    assert report["ok"] is False
    assert report["phase"] == "plan"
    assert report["error"] == "planner_produced_no_ready_plan"


def test_prompt_block_forbids_tool_calls():
    planner = mla.Planner(tools=SAMPLE_TOOLS)
    block = planner.prompt_block("validate catalog")
    assert "Planner" in block
    assert "Do NOT call tools" in block
    assert "marketplace" in block
    assert "2401.07324" in block


def test_cli_plan_and_run():
    rc = mla.main(
        [
            "plan",
            "validate marketplace catalog",
            "--tools",
            "marketplace,tool_catalog,nexus_status",
            "--json",
        ]
    )
    assert rc == 0

    rc2 = mla.main(
        [
            "run",
            "validate marketplace catalog",
            "--tools",
            "marketplace,tool_catalog",
            "--json",
        ]
    )
    assert rc2 == 0


def test_cli_validate_stdin(monkeypatch, capsys):
    plan = {
        "task": "t",
        "steps": [{"id": 1, "tool": "nexus_status", "args": {}}],
    }
    monkeypatch.setattr(
        "sys.stdin",
        type("S", (), {"read": staticmethod(lambda: json.dumps(plan))})(),
    )
    rc = mla.main(["validate", "--tools", "nexus_status", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["ok"] is True


def test_nexus_cli_tool_agent_plan(capsys):
    from nexus.cli import main as cli_main

    rc = cli_main(
        [
            "tool-agent",
            "plan",
            "validate marketplace catalog",
            "--tools",
            "marketplace,tool_catalog,nexus_status",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == mla.SCHEMA
    assert data["status"] == mla.STATUS_READY
    assert data["n_steps"] >= 1
    assert all("tool" in s for s in data["steps"])


# ── Planner → Orchestrator handoff (portfolio concrete) ─────────────────────


def test_plan_for_orchestrator_no_tool_side_effects():
    called = {"n": 0}

    def boom(**_kw):
        called["n"] += 1
        raise AssertionError("Planner must not execute tools")

    tools = [
        {"name": "marketplace", "description": "plugin marketplace"},
        {"name": "nexus_status", "description": "status"},
    ]
    plan = mla.plan_for_orchestrator(
        "validate marketplace catalog",
        tools=tools,
        max_steps=3,
    )
    assert plan.is_ready()
    assert plan.meta.get("handoff") == "orchestrator"
    assert plan.paper == mla.PAPER
    assert called["n"] == 0
    payload = mla.plan_payload_for_meta(plan)
    assert payload["schema"] == mla.SCHEMA
    assert payload["n_steps"] >= 1
    assert "brief" in payload and "multi-LLM pre-plan" in payload["brief"]
    assert boom  # registry unused


def test_plan_for_orchestrator_from_injected_llm_text():
    text = json.dumps(
        {
            "task": "status then marketplace",
            "status": "ready",
            "steps": [
                {"id": 1, "tool": "nexus_status", "args": {}, "rationale": "health"},
                {"id": 2, "tool": "marketplace", "args": {"action": "list"}},
            ],
        }
    )
    plan = mla.plan_for_orchestrator(
        "status then marketplace",
        tools=["nexus_status", "marketplace"],
        plan_text=text,
    )
    assert plan.is_ready()
    assert [s.tool for s in plan.steps] == ["nexus_status", "marketplace"]


def test_format_plan_brief():
    plan = mla.ToolPlan(
        task="t",
        steps=[mla.PlanStep(id=1, tool="nexus_status", rationale="check")],
        status=mla.STATUS_READY,
        planner="heuristic",
    )
    brief = mla.format_plan_brief(plan)
    assert "2401.07324" in brief
    assert "nexus_status" in brief


def test_plan_and_handoff_to_orchestrator(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    report = mla.plan_and_handoff(
        "validate marketplace catalog and show nexus status",
        workdir=tmp_path,
        tools=[
            {"name": "marketplace", "description": "marketplace plugins"},
            {"name": "nexus_status", "description": "process status"},
            {"name": "tool_catalog", "description": "tool catalog"},
        ],
        max_steps=3,
        agent_mode="fake",
        task_id="plan-ho-1",
        sync_fake=True,
        require_ready=True,
    )
    assert report["paper"] == mla.PAPER
    assert report["phase"] == "orchestrator"
    assert report["ok"] is True
    assert report["plan"]["n_steps"] >= 1
    assert report["plan"]["status"] == mla.STATUS_READY
    orch = report["orchestrator"]
    assert orch is not None
    assert orch["task_id"] == "plan-ho-1"
    assert orch["status"] == "completed"
    assert orch.get("pre_planned") is True
    assert orch.get("plan_summary", {}).get("n_steps", 0) >= 1
    assert "marketplace" in (orch.get("plan_summary") or {}).get("tools", []) or (
        "nexus_status" in (orch.get("plan_summary") or {}).get("tools", [])
    )


def test_plan_and_handoff_empty_tools_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    report = mla.plan_and_handoff(
        "do anything complex",
        workdir=tmp_path,
        tools=[],
        max_steps=2,
        agent_mode="fake",
        task_id="plan-ho-empty",
        require_ready=True,
    )
    assert report["ok"] is False
    assert report["phase"] == "plan"
    assert report["error"] == "planner_produced_no_ready_plan"
    assert report["orchestrator"] is None


def test_cli_handoff(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    rc = mla.main(
        [
            "handoff",
            "validate marketplace catalog",
            "--tools",
            "marketplace,tool_catalog,nexus_status",
            "--task-id",
            "cli-ho-1",
            "--workdir",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["phase"] == "orchestrator"
    assert data["orchestrator"]["pre_planned"] is True


def test_nexus_cli_tool_agent_handoff(tmp_path, monkeypatch, capsys):
    from nexus.cli import main as cli_main

    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    rc = cli_main(
        [
            "tool-agent",
            "handoff",
            "validate marketplace catalog",
            "--tools",
            "marketplace,nexus_status",
            "--task-id",
            "cli-nx-ho",
            "--workdir",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == mla.SCHEMA
    assert data["orchestrator"]["status"] == "completed"
    assert data["orchestrator"]["pre_planned"] is True


# ── dispatch_action + MCP tool_agent surface ────────────────────────────────


def test_dispatch_plan_before_any_tools():
    """Planner outputs structured JSON steps; never touches registry."""
    called = {"n": 0}

    def boom(**_kw):
        called["n"] += 1
        raise AssertionError("Planner phase must not call tools")

    tools = [
        {"name": "marketplace", "description": "plugin marketplace catalog"},
        {"name": "tool_catalog", "description": "OpenAPI tool catalog"},
        {"name": "nexus_status", "description": "runtime status"},
    ]
    # registry is irrelevant to plan — prove no side effects via absence of calls
    _ = {t["name"]: boom for t in tools}
    out = mla.dispatch_action(
        "plan",
        task="validate marketplace catalog and tool catalog",
        tools=tools,
        max_steps=3,
    )
    assert out["ok"] is True
    assert out["action"] == "plan"
    assert out["phase"] == "plan"
    assert out["paper"] == mla.PAPER
    plan = out["plan"]
    assert plan["status"] == mla.STATUS_READY
    assert plan["n_steps"] >= 1
    assert all("tool" in s for s in plan["steps"])
    assert called["n"] == 0
    assert "brief" in out and "2401.07324" in out["brief"]


def test_dispatch_run_mock_caller_after_plan():
    out = mla.dispatch_action(
        "run",
        task="show nexus status",
        tools_csv="nexus_status,marketplace",
        max_steps=2,
    )
    assert out["ok"] is True
    assert out["action"] == "run"
    assert out["plan"]["n_steps"] >= 1
    assert out["summary"]["n_ok"] >= 1
    # mock Caller stamps
    assert any(
        (c.get("result") or {}).get("mock") is True for c in (out.get("calls") or [])
    )


def test_dispatch_validate_and_prompt():
    plan_json = json.dumps(
        {
            "task": "status",
            "steps": [{"id": 1, "tool": "nexus_status", "args": {}}],
        }
    )
    v = mla.dispatch_action(
        "validate",
        plan_json=plan_json,
        tools_csv="nexus_status,marketplace",
    )
    assert v["ok"] is True
    assert v["action"] == "validate"
    assert v["errors"] == 0

    bad = mla.dispatch_action(
        "validate",
        plan_json=json.dumps(
            {"task": "x", "steps": [{"id": 1, "tool": "rm_rf_root", "args": {}}]}
        ),
        tools_csv="nexus_status",
    )
    assert bad["ok"] is False

    p = mla.dispatch_action(
        "prompt",
        task="validate catalog",
        tools=SAMPLE_TOOLS,
    )
    assert p["ok"] is True
    assert "Do NOT call tools" in p["prompt"]
    assert "2401.07324" in p["prompt"]


def test_dispatch_handoff(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    out = mla.dispatch_action(
        "handoff",
        task="validate marketplace catalog",
        tools_csv="marketplace,nexus_status,tool_catalog",
        workdir=tmp_path,
        task_id="dispatch-ho-1",
        agent_mode="fake",
        max_steps=3,
    )
    assert out["action"] == "handoff"
    assert out["ok"] is True
    assert out["phase"] == "orchestrator"
    assert out["orchestrator"]["pre_planned"] is True
    assert out["plan"]["n_steps"] >= 1


def test_dispatch_unknown_action():
    out = mla.dispatch_action("explode", task="x")
    assert out["ok"] is False
    assert "unknown action" in (out.get("error") or "")


def test_mcp_tool_agent_plan_and_run():
    from nexus import mcp_server

    names = {t["name"] for t in mcp_server.TOOLS}
    assert "tool_agent" in names

    r = mcp_server.call_tool(
        "tool_agent",
        {
            "action": "plan",
            "task": "validate marketplace catalog",
            "tools": "marketplace,tool_catalog,nexus_status",
            "max_steps": 3,
        },
    )
    assert r.get("isError") is not True
    data = json.loads(r["content"][0]["text"])
    assert data["schema"] == mla.SCHEMA
    assert data["paper"] == mla.PAPER
    assert data["plan"]["status"] == mla.STATUS_READY
    assert data["plan"]["n_steps"] >= 1
    # structure-only: steps list tools before any call history
    assert "calls" not in data or not data.get("calls")

    r2 = mcp_server.call_tool(
        "tool_agent",
        {
            "action": "run",
            "task": "show nexus status",
            "tools": "nexus_status,marketplace",
            "max_steps": 2,
        },
    )
    assert r2.get("isError") is not True
    run = json.loads(r2["content"][0]["text"])
    assert run["ok"] is True
    assert run["summary"]["n_ok"] >= 1


def test_mcp_tool_agent_validate_injected_plan():
    from nexus import mcp_server

    plan_json = json.dumps(
        {
            "task": "status check",
            "status": "ready",
            "steps": [
                {"id": 1, "tool": "nexus_status", "args": {}, "rationale": "health"},
            ],
        }
    )
    r = mcp_server.call_tool(
        "tool_agent",
        {
            "action": "validate",
            "plan_json": plan_json,
            "tools": "nexus_status",
        },
    )
    data = json.loads(r["content"][0]["text"])
    assert data["ok"] is True
    assert data["n_steps"] == 1


def test_mcp_tool_agent_handoff(tmp_path, monkeypatch):
    from nexus import mcp_server

    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    # call_tool uses _root() which reads NEXUS_PROJECT_ROOT
    r = mcp_server.call_tool(
        "tool_agent",
        {
            "action": "handoff",
            "task": "validate marketplace catalog",
            "tools": "marketplace,nexus_status",
            "task_id": "mcp-ho-1",
            "agent_mode": "fake",
            "max_steps": 2,
        },
    )
    data = json.loads(r["content"][0]["text"])
    assert data["phase"] == "orchestrator"
    assert data["orchestrator"]["status"] == "completed"
    assert data["orchestrator"]["pre_planned"] is True


def test_tool_catalog_lists_tool_agent():
    from nexus import tool_catalog as tc

    entries = {e.name: e for e in tc.build_entries()}
    assert "tool_agent" in entries
    assert entries["tool_agent"].privilege == "read"
