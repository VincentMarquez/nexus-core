"""Tests for unified agent interaction protocol (arXiv 2602.22953 × wshobson)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import agent_protocol as ap
from nexus import multi_llm_agent as mla


def _write_plugin(
    root: Path,
    plugin_id: str = "demo-plugin",
    *,
    agent_name: str = "durable-operator",
    skill_name: str = "demo-skill",
    command_name: str = "demo-cmd",
) -> Path:
    d = root / "plugins" / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_id,
                "version": "0.1.0",
                "description": "Protocol test plugin",
                "privilege": "read",
                "tags": ["test", "protocol", "durable"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    agents = d / "agents"
    agents.mkdir(exist_ok=True)
    (agents / f"{agent_name}.md").write_text(
        f"---\nname: {agent_name}\ndescription: Inspect durable board\n---\n\n"
        f"# {agent_name}\n",
        encoding="utf-8",
    )
    commands = d / "commands"
    commands.mkdir(exist_ok=True)
    (commands / f"{command_name}.md").write_text(
        f"---\nname: {command_name}\n---\n\n# /{command_name}\n",
        encoding="utf-8",
    )
    skill = d / "skills" / skill_name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {skill_name}\n---\n\n# Skill {skill_name}\n",
        encoding="utf-8",
    )
    return d


# ── target / tool_id ────────────────────────────────────────────────────────


def test_protocol_target_tool_id_roundtrip():
    t = ap.ProtocolTarget(
        surface="agent", name="durable-operator", plugin_id="nexus-durable"
    )
    assert t.tool_id == "agent:durable-operator@nexus-durable"
    back = ap.ProtocolTarget.from_dict({"tool_id": t.tool_id})
    assert back.surface == "agent"
    assert back.name == "durable-operator"
    assert back.plugin_id == "nexus-durable"

    cli_t = ap.ProtocolTarget(surface="cli", name="pytest")
    assert cli_t.tool_id == "cli:pytest"
    tool_t = ap.ProtocolTarget(surface="tool", name="nexus_status")
    assert tool_t.tool_id == "nexus_status"

    with pytest.raises(ap.ProtocolError):
        ap.ProtocolTarget(surface="nope", name="x")
    with pytest.raises(ap.ProtocolError):
        ap.ProtocolTarget(surface="tool", name="")


def test_parse_tool_id_variants():
    p = ap.parse_tool_id("skill:demo@plug")
    assert p == {
        "surface": "skill",
        "name": "demo",
        "plugin_id": "plug",
        "tool_id": "skill:demo@plug",
    }
    bare = ap.parse_tool_id("list_project_files")
    assert bare["surface"] == "tool" and bare["name"] == "list_project_files"
    mcp = ap.parse_tool_id("mcp:tool_catalog")
    assert mcp["surface"] == "mcp" and mcp["name"] == "tool_catalog"


# ── dialect normalizers ─────────────────────────────────────────────────────


def test_from_openai_tool_call():
    raw = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "nexus_status",
            "arguments": '{"verbose": true}',
        },
    }
    msg = ap.from_openai_tool_call(raw)
    assert msg.kind == ap.KIND_INVOKE
    assert msg.source_format == ap.FMT_OPENAI
    assert msg.target.surface == ap.SURFACE_TOOL
    assert msg.target.name == "nexus_status"
    assert msg.args["verbose"] is True
    assert msg.id == "call_1"

    oai = ap.to_openai_tool_call(msg)
    assert oai["type"] == "function"
    assert oai["function"]["name"] == "nexus_status"
    assert json.loads(oai["function"]["arguments"])["verbose"] is True


def test_from_anthropic_tool_use():
    raw = {
        "type": "tool_use",
        "id": "tu_1",
        "name": "marketplace",
        "input": {"action": "list"},
    }
    msg = ap.from_anthropic_tool_use(raw)
    assert msg.source_format == ap.FMT_ANTHROPIC
    assert msg.target.name == "marketplace"
    assert msg.args["action"] == "list"
    ant = ap.to_anthropic_tool_use(msg)
    assert ant["type"] == "tool_use" and ant["input"]["action"] == "list"


def test_from_mcp_and_cli():
    mcp = ap.from_mcp_call({"name": "tool_catalog", "arguments": {"action": "validate"}})
    assert mcp.target.surface == ap.SURFACE_MCP
    assert mcp.target.tool_id == "mcp:tool_catalog"
    assert ap.to_mcp_call(mcp)["name"] == "tool_catalog"

    cli = ap.from_cli("pytest -q tests/test_agent_protocol.py")
    assert cli.target.surface == ap.SURFACE_CLI
    assert cli.target.name == "pytest"
    assert cli.args["argv"][0] == "pytest"
    argv = ap.to_cli_argv(cli)
    assert argv[0] == "pytest" and "-q" in argv

    cli2 = ap.from_cli(["python", "-m", "nexus.agent_protocol", "catalog"])
    assert cli2.target.name == "python"
    assert "catalog" in cli2.args["argv"]


def test_from_marketplace_and_plan_step():
    msg = ap.from_marketplace(
        "agent",
        "durable-operator",
        plugin_id="demo-plugin",
        args={"focus": "board"},
    )
    assert msg.source_format == ap.FMT_MARKETPLACE
    assert msg.target.tool_id == "agent:durable-operator@demo-plugin"
    assert msg.meta.get("source_pattern") == ap.SOURCE_PATTERN

    step = mla.PlanStep(
        id=3,
        tool="skill:demo-skill@demo-plugin",
        args={"x": 1},
        rationale="use skill",
        status=mla.STEP_PENDING,
    )
    pmsg = ap.from_plan_step(step)
    assert pmsg.source_format == ap.FMT_PLAN_STEP
    assert pmsg.target.surface == "skill"
    assert pmsg.target.name == "demo-skill"
    back = ap.to_plan_step(pmsg, step_id=3)
    assert back.tool == "skill:demo-skill@demo-plugin"
    assert back.args["x"] == 1
    assert back.rationale == "use skill"


def test_normalize_autodetect():
    oai = ap.normalize(
        {
            "type": "function",
            "function": {"name": "a", "arguments": "{}"},
        }
    )
    assert oai.source_format == ap.FMT_OPENAI

    ant = ap.normalize(
        {"type": "tool_use", "name": "b", "input": {"k": 1}}
    )
    assert ant.source_format == ap.FMT_ANTHROPIC

    cli = ap.normalize("ls -la")
    assert cli.source_format == ap.FMT_CLI

    mcp = ap.normalize({"name": "c", "arguments": {"z": 2}})
    assert mcp.source_format == ap.FMT_MCP

    mkt = ap.normalize(
        {
            "kind": "command",
            "name": "demo-cmd",
            "plugin_id": "p",
            "marketplace": True,
        }
    )
    assert mkt.source_format == ap.FMT_MARKETPLACE
    assert mkt.target.surface == "command"

    # Round-trip protocol envelope
    env = ap.normalize(oai.to_dict())
    assert env.target.name == "a"
    assert env.schema == ap.SCHEMA


def test_normalize_unknown_raises():
    with pytest.raises(ap.ProtocolError):
        ap.normalize({"foo": "bar"})


def test_message_roundtrip_json():
    msg = ap.invoke("tool", "nexus_status", args={"verbose": True})
    blob = msg.to_dict()
    assert blob["schema"] == ap.SCHEMA
    assert blob["paper"] == ap.PAPER
    back = ap.ProtocolMessage.from_dict(blob)
    assert back.target.name == "nexus_status"
    assert back.args["verbose"] is True
    assert back.kind == ap.KIND_INVOKE


def test_to_result_message():
    inv = ap.invoke("mcp", "nexus_status", args={})
    ok = ap.to_result_message(inv, result={"status": "ok"})
    assert ok.kind == ap.KIND_RESULT
    assert ok.role == "tool"
    assert ok.meta["in_reply_to"] == inv.id
    err = ap.to_result_message(inv, error="boom")
    assert err.kind == ap.KIND_ERROR
    assert err.error == "boom"


# ── validate ────────────────────────────────────────────────────────────────


def test_validate_message_allowed_set():
    msg = ap.invoke("tool", "nexus_status")
    ok = ap.validate_message(msg, allowed_tool_ids=["nexus_status", "marketplace"])
    assert ok["ok"] is True

    bad = ap.validate_message(msg, allowed_tool_ids=["marketplace"])
    assert bad["ok"] is False
    assert any("not in allowed" in f["message"] for f in bad["findings"])


# ── marketplace catalog targets ─────────────────────────────────────────────


def test_marketplace_targets(tmp_path: Path):
    _write_plugin(tmp_path)
    targets = ap.marketplace_targets(tmp_path)
    ids = {t.tool_id for t in targets}
    assert any(i.startswith("agent:durable-operator") for i in ids)
    assert any(i.startswith("skill:demo-skill") for i in ids)
    assert any(i.startswith("command:demo-cmd") for i in ids)
    summary = ap.catalog_summary(targets)
    assert summary["n_targets"] == 3
    assert summary["by_surface"]["agent"] == 1
    assert summary["source_pattern"] == ap.SOURCE_PATTERN
    assert summary["paper"] == ap.PAPER


def test_targets_from_catalog_mixed():
    tools = [
        {
            "name": "agent:a@p",
            "kind": "agent",
            "component": "a",
            "plugin_id": "p",
            "description": "agent a",
        },
        {"name": "nexus_status", "description": "status tool"},
        {"name": "mcp:tool_catalog", "mcp": True},
        {"name": "cli:pytest"},
    ]
    targets = ap.targets_from_catalog(tools)
    surfaces = {t.surface for t in targets}
    assert "agent" in surfaces
    assert "tool" in surfaces
    assert "mcp" in surfaces
    assert "cli" in surfaces


# ── transcript + plan bridge ────────────────────────────────────────────────


def test_protocol_transcript_eval_log():
    tr = ap.ProtocolTranscript(task="inspect durable board")
    tr.append(
        {
            "type": "function",
            "function": {"name": "marketplace", "arguments": '{"action":"list"}'},
        }
    )
    tr.append("pytest -q")
    tr.append(
        ap.from_marketplace("agent", "durable-operator", plugin_id="demo")
    )
    tr.append(ap.to_result_message(tr.messages[-1], result={"ok": True}))

    s = tr.summary()
    assert s["n_messages"] == 4
    assert "tool" in s["surfaces"] or "agent" in s["surfaces"]
    assert "cli" in s["surfaces"]
    assert "openai" in s["source_formats"]
    assert "cli" in s["source_formats"]
    assert "marketplace" in s["source_formats"]

    rep = tr.validate()
    assert rep["ok"] is True

    blob = tr.to_dict()
    assert blob["schema"] == ap.SCHEMA
    restored = ap.ProtocolTranscript.from_dict(blob)
    assert len(restored.messages) == 4
    assert restored.task == "inspect durable board"


def test_messages_to_plan_and_back():
    msgs = [
        ap.invoke("tool", "marketplace", args={"action": "list"}),
        ap.from_marketplace("skill", "demo-skill", plugin_id="p", args={}),
        ap.from_cli(["pytest", "-q"]),
    ]
    plan = ap.messages_to_plan(msgs, task="mixed protocol plan")
    assert plan.schema == mla.SCHEMA
    assert plan.paper == ap.PAPER
    assert plan.is_ready()
    assert len(plan.steps) == 3
    tools = [s.tool for s in plan.steps]
    assert "marketplace" in tools
    assert any(t.startswith("skill:demo-skill") for t in tools)
    assert any(t.startswith("cli:pytest") for t in tools)
    assert plan.meta["protocol_schema"] == ap.SCHEMA

    back = ap.plan_to_messages(plan)
    assert len(back) == 3
    assert back[0].target.name == "marketplace"


def test_plan_step_failed_maps_to_error_kind():
    step = mla.PlanStep(
        id=1, tool="nexus_status", status=mla.STEP_FAILED, error="timeout"
    )
    msg = ap.from_plan_step(step)
    assert msg.kind == ap.KIND_ERROR
    assert msg.error == "timeout"


# ── CLI module ──────────────────────────────────────────────────────────────


def test_module_cli_catalog(tmp_path: Path, capsys):
    _write_plugin(tmp_path)
    rc = ap.main(["catalog", "--workdir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "agent:durable-operator" in out or "targets=" in out


def test_module_cli_normalize_and_to_plan(tmp_path: Path, capsys):
    payload = {
        "type": "function",
        "function": {"name": "nexus_status", "arguments": "{}"},
    }
    f = tmp_path / "payload.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    rc = ap.main(["normalize", "--file", str(f), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["target"]["name"] == "nexus_status"
    assert data["schema"] == ap.SCHEMA

    multi = tmp_path / "multi.json"
    multi.write_text(
        json.dumps(
            [
                payload,
                {"name": "marketplace", "arguments": {"action": "list"}},
            ]
        ),
        encoding="utf-8",
    )
    rc2 = ap.main(["to-plan", "--file", str(multi), "--task", "t", "--json"])
    assert rc2 == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["n_steps"] == 2
    assert plan["status"] == "ready"


def test_module_cli_validate(tmp_path: Path, capsys):
    msg = ap.invoke("tool", "nexus_status")
    f = tmp_path / "msg.json"
    f.write_text(msg.to_json(), encoding="utf-8")
    rc = ap.main(["validate", "--file", str(f), "--json"])
    assert rc == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["ok"] is True


def test_module_cli_transcript(tmp_path: Path, capsys):
    items = [
        {"name": "a", "arguments": {}},
        "echo hello",
    ]
    f = tmp_path / "tr.json"
    f.write_text(json.dumps(items), encoding="utf-8")
    rc = ap.main(["transcript", "--file", str(f), "--task", "eval", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["n_messages"] == 2
    assert data["task"] == "eval"
    assert data["paper"] == ap.PAPER
