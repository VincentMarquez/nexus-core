"""Tests for marketplace-aware Planner (arXiv 2401.07324 × wshobson/agents)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import marketplace_planner as mplan
from nexus import multi_llm_agent as mla
from nexus.cli import main as cli_main


def _write_plugin(
    root: Path,
    plugin_id: str = "demo-plugin",
    *,
    privilege: str = "read",
    agent_name: str | None = None,
    skill_name: str = "demo-skill",
    command_name: str = "demo-cmd",
    description: str = "Demo plugin for planner tests",
    agent_body: str = "Inspect durable tasks and evidence packs.",
) -> Path:
    d = root / "plugins" / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    man = {
        "name": plugin_id,
        "version": "0.1.0",
        "description": description,
        "category": "test",
        "privilege": privilege,
        "tags": ["test", "durable", "marketplace"],
    }
    (d / "plugin.json").write_text(json.dumps(man, indent=2), encoding="utf-8")

    aname = agent_name or f"{plugin_id}-agent"
    agents = d / "agents"
    agents.mkdir(exist_ok=True)
    (agents / f"{aname}.md").write_text(
        f"---\nname: {aname}\ndescription: {agent_body}\n---\n\n"
        f"# Agent {aname}\n\n{agent_body}\n",
        encoding="utf-8",
    )

    commands = d / "commands"
    commands.mkdir(exist_ok=True)
    (commands / f"{command_name}.md").write_text(
        f"---\nname: {command_name}\n---\n\n# /{command_name}\n\n"
        "Run operator board command.\n",
        encoding="utf-8",
    )

    skill = d / "skills" / skill_name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {skill_name}\n---\n\n# Skill {skill_name}\n\n"
        "## When to use\n\n- unit tests\n- durable board inspect\n\n"
        "## Success\n\n- ok\n",
        encoding="utf-8",
    )
    return d


# ── catalog ─────────────────────────────────────────────────────────────────


def test_component_tool_id_roundtrip():
    tid = mplan.component_tool_id("agent", "durable-operator", plugin_id="nexus-durable")
    assert tid == "agent:durable-operator@nexus-durable"
    parsed = mplan.parse_component_tool_id(tid)
    assert parsed["kind"] == "agent"
    assert parsed["name"] == "durable-operator"
    assert parsed["plugin_id"] == "nexus-durable"

    simple = mplan.component_tool_id("skill", "demo-skill")
    assert simple == "skill:demo-skill"
    p2 = mplan.parse_component_tool_id(simple)
    assert p2["kind"] == "skill" and p2["name"] == "demo-skill"


def test_marketplace_as_tools(tmp_path: Path):
    _write_plugin(tmp_path, "ops-board", agent_name="durable-operator")
    tools = mplan.marketplace_as_tools(tmp_path)
    names = {t["name"] for t in tools}
    assert any(n.startswith("agent:durable-operator") for n in names)
    assert any(n.startswith("skill:demo-skill") for n in names)
    assert any(n.startswith("command:demo-cmd") for n in names)
    summary = mplan.catalog_summary(tools)
    assert summary["n_tools"] == 3
    assert summary["n_plugins"] == 1
    assert summary["by_kind"]["agent"] == 1
    assert summary["by_kind"]["skill"] == 1
    assert summary["by_kind"]["command"] == 1
    # every entry stamped with marketplace source pattern
    assert all(t.get("marketplace") is True for t in tools)
    assert all(t.get("source") == mplan.SOURCE_PATTERN for t in tools)


def test_marketplace_as_tools_kinds_filter(tmp_path: Path):
    _write_plugin(tmp_path)
    agents_only = mplan.marketplace_as_tools(tmp_path, kinds=["agent"])
    assert agents_only
    assert all(t["kind"] == "agent" for t in agents_only)


def test_marketplace_as_tools_empty_dir(tmp_path: Path):
    tools = mplan.marketplace_as_tools(tmp_path)
    assert tools == []
    assert mplan.catalog_summary(tools)["n_tools"] == 0


# ── Planner (no side effects) ───────────────────────────────────────────────


def test_plan_from_marketplace_selects_relevant(tmp_path: Path):
    _write_plugin(
        tmp_path,
        "nexus-durable",
        agent_name="durable-operator",
        skill_name="durable-operator-board",
        command_name="task-board",
        description="Durable operator board crash-safe tasks evidence",
        agent_body="Inspect crash-safe multi-agent tasks and evidence packs",
    )
    plan = mplan.plan_from_marketplace(
        "inspect durable operator board and task evidence packs",
        workdir=tmp_path,
        max_steps=3,
    )
    assert plan.paper == mla.PAPER
    assert plan.meta.get("schema") == mplan.SCHEMA
    assert plan.meta.get("source_pattern") == mplan.SOURCE_PATTERN
    assert plan.planner.startswith("marketplace")
    assert plan.is_ready()
    assert plan.steps
    tools = [s.tool for s in plan.steps]
    # Should rank durable / operator / board components
    joined = " ".join(tools)
    assert "durable" in joined or "task-board" in joined or "operator" in joined
    # Step args carry marketplace identity
    for s in plan.steps:
        assert s.args.get("kind") in ("agent", "skill", "command")
        assert s.args.get("component")


def test_planner_does_not_execute_components(tmp_path: Path, monkeypatch):
    """Planner role must never invoke marketplace side effects."""
    _write_plugin(tmp_path, agent_name="safe-agent")
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("must not execute")

    # Even if someone patches orchestrator, plan_from_marketplace alone is pure
    monkeypatch.setattr(
        "nexus.orchestrator.Orchestrator.run_task", boom, raising=False
    )
    plan = mplan.plan_from_marketplace(
        "run safe agent demo skill",
        workdir=tmp_path,
        max_steps=2,
    )
    assert plan.steps
    assert called["n"] == 0


def test_plan_from_injected_llm_text(tmp_path: Path):
    _write_plugin(tmp_path, "alpha", agent_name="alpha-agent")
    tools = mplan.marketplace_as_tools(tmp_path)
    assert tools
    tool_name = tools[0]["name"]
    text = json.dumps(
        {
            "task": "use marketplace agent",
            "status": "ready",
            "steps": [
                {
                    "id": 1,
                    "tool": tool_name,
                    "args": {},
                    "rationale": "primary agent",
                }
            ],
        }
    )
    plan = mplan.plan_from_marketplace(
        "use marketplace agent",
        workdir=tmp_path,
        plan_text=text,
    )
    assert plan.is_ready()
    assert plan.steps[0].tool == tool_name
    assert plan.planner == "marketplace-injected"


def test_empty_marketplace_fails_closed_on_handoff(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    report = mplan.plan_and_handoff(
        "do complex multi-agent work",
        workdir=tmp_path,
        max_steps=2,
        agent_mode="fake",
        task_id="mplan-empty",
        require_ready=True,
    )
    assert report["ok"] is False
    assert report["phase"] == "plan"
    assert report["error"] == "planner_produced_no_ready_plan"
    assert report["orchestrator"] is None
    assert report["schema"] == mplan.SCHEMA
    assert report["source_pattern"] == mplan.SOURCE_PATTERN


def test_plan_and_handoff_to_orchestrator(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    _write_plugin(
        tmp_path,
        "nexus-durable",
        agent_name="durable-operator",
        skill_name="durable-operator-board",
        description="Durable operator evidence and task board",
        agent_body="Inspect durable tasks evidence board",
    )
    report = mplan.plan_and_handoff(
        "inspect durable operator board and evidence",
        workdir=tmp_path,
        max_steps=3,
        agent_mode="fake",
        task_id="mplan-ho-1",
        sync_fake=True,
        require_ready=True,
    )
    assert report["paper"] == mplan.PAPER
    assert report["schema"] == mplan.SCHEMA
    assert report["phase"] == "orchestrator"
    assert report["ok"] is True
    assert report["plan"]["n_steps"] >= 1
    orch = report["orchestrator"]
    assert orch is not None
    assert orch["task_id"] == "mplan-ho-1"
    assert orch["status"] == "completed"
    assert orch.get("pre_planned") is True
    assert report["catalog"]["n_tools"] >= 1


def test_prompt_block_mentions_marketplace(tmp_path: Path):
    _write_plugin(tmp_path, agent_name="prompt-agent")
    planner = mplan.MarketplacePlanner(workdir=tmp_path)
    block = planner.prompt_block("validate durable board")
    assert "Marketplace" in block or "marketplace" in block
    assert "Do NOT" in block
    assert mplan.PAPER in block or "2401.07324" in block
    assert "agent:prompt-agent" in block or "prompt-agent" in block


def test_format_market_plan(tmp_path: Path):
    _write_plugin(tmp_path, agent_name="fmt-agent")
    plan = mplan.plan_from_marketplace("use fmt agent", workdir=tmp_path, max_steps=1)
    text = mplan.format_market_plan(plan)
    assert mplan.SCHEMA in text
    assert mplan.SOURCE_PATTERN in text
    assert "fmt-agent" in text or "agent:" in text


# ── module + nexus CLI ──────────────────────────────────────────────────────


def test_module_cli_catalog_and_plan(tmp_path: Path, capsys):
    _write_plugin(tmp_path, agent_name="cli-agent")
    rc = mplan.main(
        ["catalog", "--workdir", str(tmp_path), "--json"]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == mplan.SCHEMA
    assert data["summary"]["n_tools"] >= 1

    rc2 = mplan.main(
        [
            "plan",
            "use cli agent skill for durable tests",
            "--workdir",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc2 == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["status"] == mla.STATUS_READY
    assert plan["n_steps"] >= 1
    assert plan["meta"]["schema"] == mplan.SCHEMA


def test_module_cli_handoff(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    _write_plugin(
        tmp_path,
        agent_name="ho-agent",
        description="handoff durable board inspect",
        agent_body="handoff durable board inspect",
    )
    rc = mplan.main(
        [
            "handoff",
            "inspect durable board with ho agent",
            "--workdir",
            str(tmp_path),
            "--task-id",
            "cli-mho-1",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["phase"] == "orchestrator"
    assert data["orchestrator"]["pre_planned"] is True


def test_nexus_cli_market_plan(tmp_path: Path, capsys):
    _write_plugin(
        tmp_path,
        agent_name="nx-agent",
        description="nexus cli durable operator",
        agent_body="nexus cli durable operator board",
    )
    rc = cli_main(
        [
            "tool-agent",
            "market-plan",
            "use nx agent for durable operator board",
            "--workdir",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == mla.SCHEMA
    assert data["meta"]["schema"] == mplan.SCHEMA
    assert data["status"] == mla.STATUS_READY
    assert data["n_steps"] >= 1


def test_nexus_cli_market_catalog(tmp_path: Path, capsys):
    _write_plugin(tmp_path)
    rc = cli_main(
        [
            "tool-agent",
            "market-catalog",
            "--workdir",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == mplan.SCHEMA
    assert data["summary"]["n_tools"] == 3


def test_nexus_cli_market_handoff(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    _write_plugin(
        tmp_path,
        agent_name="mho-agent",
        description="market handoff durable inspect",
        agent_body="market handoff durable inspect evidence",
    )
    rc = cli_main(
        [
            "tool-agent",
            "market-handoff",
            "inspect durable evidence with mho agent",
            "--workdir",
            str(tmp_path),
            "--task-id",
            "nx-mho-1",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == mplan.SCHEMA
    assert data["orchestrator"]["status"] == "completed"
    assert data["orchestrator"]["pre_planned"] is True
