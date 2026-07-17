"""Tests for search-based plane planner (arXiv 2407.01476 × wshobson/agents)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import multi_llm_agent as mla
from nexus import ops_store as ops
from nexus import search_plane_planner as spp
from nexus.cli import main as cli_main


def _write_plugin(
    root: Path,
    plugin_id: str = "demo-plugin",
    *,
    privilege: str = "read",
    agent_name: str | None = None,
    skill_name: str = "demo-skill",
    command_name: str = "demo-cmd",
    description: str = "Demo plugin for durable operator board inspect",
    agent_body: str = "Inspect durable tasks and evidence packs on the board.",
) -> Path:
    d = root / "plugins" / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    man = {
        "name": plugin_id,
        "version": "0.1.0",
        "description": description,
        "category": "test",
        "privilege": privilege,
        "tags": ["test", "durable", "marketplace", "search"],
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
        "Run operator board command for durable inspect.\n",
        encoding="utf-8",
    )

    skill = d / "skills" / skill_name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {skill_name}\n---\n\n# Skill {skill_name}\n\n"
        "## When to use\n\n- unit tests\n- durable board inspect\n"
        "- search planning\n\n"
        "## Success\n\n- ok\n",
        encoding="utf-8",
    )
    return d


# ── catalog ─────────────────────────────────────────────────────────────────


def test_hybrid_catalog_shape(tmp_path: Path):
    _write_plugin(tmp_path, "ops-board", agent_name="durable-operator")
    tools = spp.hybrid_catalog(tmp_path)
    names = {t["name"] for t in tools}
    assert any(n.startswith("agent:durable-operator") for n in names)
    assert any(n.startswith("skill:") for n in names)
    assert any(n.startswith("command:") for n in names)
    assert any(n.startswith("plane.") for n in names)
    summary = spp.catalog_summary(tools)
    assert summary["n_tools"] == len(tools)
    assert summary["by_family"]["marketplace"] >= 3
    assert summary["by_family"]["plane"] >= 1
    assert summary["source_pattern"] == spp.SOURCE_PATTERN
    assert summary["paper"] == spp.PAPER


def test_hybrid_catalog_no_plane(tmp_path: Path):
    _write_plugin(tmp_path)
    tools = spp.hybrid_catalog(tmp_path, include_plane=False)
    assert tools
    assert all(not str(t["name"]).startswith("plane.") for t in tools)
    assert all(t.get("search_family") == "marketplace" for t in tools)


def test_hybrid_catalog_empty(tmp_path: Path):
    tools = spp.hybrid_catalog(tmp_path, include_plane=False)
    assert tools == []
    assert spp.catalog_summary(tools)["n_tools"] == 0


# ── search algorithms ───────────────────────────────────────────────────────


def test_beam_search_selects_relevant(tmp_path: Path):
    _write_plugin(
        tmp_path,
        "nexus-durable",
        agent_name="durable-operator",
        description="Durable operator board for task inspect",
        agent_body="Inspect durable tasks, evidence, and board status.",
    )
    _write_plugin(
        tmp_path,
        "unrelated-math",
        agent_name="math-solver",
        description="Solve pure math equations",
        agent_body="Compute integrals and algebra only.",
        skill_name="integrate",
        command_name="math-cmd",
    )
    tools = spp.hybrid_catalog(tmp_path, include_plane=False)
    node, trace = spp.beam_search(
        "inspect durable operator board evidence tasks",
        tools,
        beam_width=3,
        max_depth=3,
    )
    assert node.path
    assert trace.algorithm == "beam"
    assert trace.expanded >= 1
    assert trace.generated >= 1
    path_s = " ".join(node.path)
    assert "durable" in path_s or "demo-skill" in path_s or "demo-cmd" in path_s
    assert "math-solver" not in path_s or "durable" in path_s


def test_astar_search_selects_relevant(tmp_path: Path):
    _write_plugin(
        tmp_path,
        "nexus-durable",
        agent_name="durable-operator",
        description="Durable operator board for task inspect",
        agent_body="Inspect durable tasks and evidence packs.",
    )
    tools = spp.hybrid_catalog(tmp_path, include_plane=False)
    node, trace = spp.astar_search(
        "inspect durable operator board evidence",
        tools,
        max_depth=3,
        max_expansions=32,
    )
    assert node.path
    assert trace.algorithm == "astar"
    assert any("durable" in p or "demo" in p for p in node.path)


def test_run_search_unknown_algorithm():
    with pytest.raises(spp.SearchPlanError, match="unknown algorithm"):
        spp.run_search("task", [{"name": "x", "description": "x"}], algorithm="dfs")


def test_beam_empty_catalog():
    node, trace = spp.beam_search("anything", [])
    assert node.path == ()
    assert "empty" in trace.notes


def test_step_cost_and_heuristic():
    assert spp.step_cost(0) == 1.0
    assert spp.step_cost(9) < spp.step_cost(1)
    tokens = {"durable", "board", "inspect"}
    h0 = spp.heuristic_h(tokens, frozenset(), remaining_actions=2)
    h1 = spp.heuristic_h(tokens, frozenset({"durable", "board"}), remaining_actions=1)
    assert h1 < h0
    assert h0 > 0


# ── plan construction ───────────────────────────────────────────────────────


def test_plan_from_search_ready_and_guides_plane(tmp_path: Path):
    _write_plugin(
        tmp_path,
        "nexus-durable",
        agent_name="durable-operator",
        description="Durable operator board",
        agent_body="Inspect durable tasks and evidence.",
    )
    plan = spp.plan_from_search(
        "inspect durable operator board evidence",
        workdir=tmp_path,
        algorithm="beam",
        beam_width=3,
        max_depth=3,
        guide_plane=True,
        job_id="job-search-1",
    )
    assert plan.paper == spp.PAPER
    assert plan.meta.get("schema") == spp.SCHEMA
    assert plan.meta.get("source_pattern") == spp.SOURCE_PATTERN
    assert plan.planner.startswith("search-plane-")
    assert plan.is_ready()
    tools = [s.tool for s in plan.steps]
    assert tools[0] == "plane.upsert_job"
    assert "plane.set_status" in tools
    assert "plane.record_spend" in tools
    assert tools[-1] in ("plane.spend_report", "plane.set_status")
    # at least one marketplace component between plane shell
    mid = [t for t in tools if not t.startswith("plane.")]
    assert mid, "expected marketplace steps from search"
    assert all(
        s.args.get("job_id") == "job-search-1"
        for s in plan.steps
        if s.tool.startswith("plane.") and s.tool != "plane.list_jobs"
    )
    search = plan.meta.get("search") or {}
    assert search.get("algorithm") == "beam"
    assert search.get("best_path")


def test_plan_from_search_astar_no_plane_guide(tmp_path: Path):
    _write_plugin(tmp_path, agent_name="durable-operator")
    plan = spp.plan_from_search(
        "inspect durable board",
        workdir=tmp_path,
        algorithm="astar",
        guide_plane=False,
        include_plane=False,
    )
    assert plan.is_ready()
    assert plan.planner == "search-plane-astar"
    assert all(not s.tool.startswith("plane.") for s in plan.steps)
    assert plan.steps


def test_plan_from_search_empty_catalog_no_side_effects(tmp_path: Path, monkeypatch):
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("must not open OpsStore during pure plan")

    monkeypatch.setattr(ops.OpsStore, "open", boom)
    plan = spp.plan_from_search(
        "anything",
        workdir=tmp_path,
        include_plane=False,
        guide_plane=False,
    )
    assert plan.steps == []
    assert plan.status == mla.STATUS_DRAFT
    assert called["n"] == 0


def test_plan_from_search_no_sqlite_on_plan(tmp_path: Path, monkeypatch):
    _write_plugin(tmp_path, agent_name="durable-operator")
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("plan must not open OpsStore")

    monkeypatch.setattr(ops.OpsStore, "open", boom)
    plan = spp.plan_from_search(
        "inspect durable board",
        workdir=tmp_path,
        guide_plane=True,
        job_id="pure-1",
    )
    assert plan.is_ready()
    assert called["n"] == 0


# ── guide control plane ─────────────────────────────────────────────────────


def test_plan_and_guide_writes_ops_meta(tmp_path: Path):
    _write_plugin(
        tmp_path,
        "nexus-durable",
        agent_name="durable-operator",
        description="Durable operator board",
        agent_body="Inspect durable tasks and evidence packs.",
    )
    report = spp.plan_and_guide(
        "inspect durable operator board evidence",
        workdir=tmp_path,
        algorithm="beam",
        job_id="guide-1",
        govern=True,
    )
    assert report["ok"] is True
    assert report["schema"] == spp.SCHEMA
    assert report["paper"] == spp.PAPER
    assert report["job_id"] == "guide-1"
    guide = report["guide"]
    assert guide and guide.get("ok")
    assert guide.get("n_plane_steps", 0) >= 3

    with ops.OpsStore.open(tmp_path) as store:
        job = store.get("guide-1")
        assert job is not None
        assert job["status"] == "completed"
        meta = job.get("meta") or {}
        assert meta.get("search_plane_schema") == spp.SCHEMA
        assert meta.get("paper") == spp.PAPER
        assert meta.get("search")
        assert meta.get("tool_plan")
        spend = store.spend_report("guide-1")
        assert int(spend["summary"].get("request_count") or 0) >= 1
        assert int(spend["summary"].get("total_tokens") or 0) >= 1


def test_plan_and_guide_without_govern_is_pure(tmp_path: Path, monkeypatch):
    _write_plugin(tmp_path, agent_name="durable-operator")
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("govern=False must not open OpsStore")

    monkeypatch.setattr(ops.OpsStore, "open", boom)
    report = spp.plan_and_guide(
        "inspect durable board",
        workdir=tmp_path,
        govern=False,
    )
    assert report["phase"] == "plan"
    assert report["guide"] is None
    assert called["n"] == 0
    assert (report.get("plan") or {}).get("steps")


# ── orchestrator handoff ────────────────────────────────────────────────────


def test_plan_and_handoff_orchestrator(tmp_path: Path):
    _write_plugin(
        tmp_path,
        "nexus-durable",
        agent_name="durable-operator",
        description="Durable operator board",
        agent_body="Inspect durable tasks.",
    )
    report = spp.plan_and_handoff(
        "inspect durable operator board",
        workdir=tmp_path,
        algorithm="beam",
        agent_mode="fake",
        task_id="hand-1",
        govern=True,
        sync_fake=True,
    )
    assert report["ok"] is True
    assert report["phase"] == "orchestrator"
    orch = report.get("orchestrator") or {}
    assert orch.get("task_id") == "hand-1"
    assert orch.get("status") not in (None, "failed")
    assert orch.get("pre_planned") or orch.get("with_plan")
    assert report.get("search")
    with ops.OpsStore.open(tmp_path) as store:
        job = store.get("hand-1")
        assert job is not None
        assert (job.get("meta") or {}).get("search_plane_schema") == spp.SCHEMA


# ── formatting / dispatch ───────────────────────────────────────────────────


def test_format_search_plan(tmp_path: Path):
    _write_plugin(tmp_path, agent_name="durable-operator")
    plan = spp.plan_from_search(
        "inspect durable board",
        workdir=tmp_path,
        job_id="fmt-1",
    )
    text = spp.format_search_plan(plan)
    assert spp.SCHEMA in text
    assert spp.PAPER in text
    assert "search:" in text
    assert "plane.upsert_job" in text


def test_module_main_plan(tmp_path: Path, capsys):
    _write_plugin(tmp_path, agent_name="durable-operator")
    rc = spp.main(
        [
            "plan",
            "inspect durable board",
            "--workdir",
            str(tmp_path),
            "--algorithm",
            "beam",
            "--job-id",
            "cli-1",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert spp.SCHEMA in out
    assert "plane.upsert_job" in out


def test_module_main_catalog_json(tmp_path: Path, capsys):
    _write_plugin(tmp_path)
    rc = spp.main(["catalog", "--workdir", str(tmp_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == spp.SCHEMA
    assert data["summary"]["n_tools"] >= 3


# ── CLI tool-agent surface ──────────────────────────────────────────────────


def test_cli_search_plan(tmp_path: Path, capsys):
    _write_plugin(tmp_path, agent_name="durable-operator")
    rc = cli_main(
        [
            "tool-agent",
            "search-plan",
            "inspect durable operator board",
            "--workdir",
            str(tmp_path),
            "--job-id",
            "cli-search-1",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "search-plane" in out or spp.SCHEMA in out or "plane.upsert_job" in out


def test_cli_search_plan_json(tmp_path: Path, capsys):
    _write_plugin(tmp_path, agent_name="durable-operator")
    rc = cli_main(
        [
            "tool-agent",
            "search-plan",
            "inspect durable board",
            "--workdir",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data.get("meta", {}).get("schema") == spp.SCHEMA or data.get("paper") == spp.PAPER
    assert data.get("steps")


def test_cli_search_catalog(tmp_path: Path, capsys):
    _write_plugin(tmp_path)
    rc = cli_main(
        [
            "tool-agent",
            "search-catalog",
            "--workdir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "tools=" in out or "agent:" in out
