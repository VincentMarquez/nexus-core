"""Tests for plugin marketplace list/validate/collisions/export (wshobson pattern)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import marketplace as mp
from nexus import mcp_server
from nexus.cli import main as cli_main


def _write_plugin(
    root: Path,
    plugin_id: str = "demo-plugin",
    *,
    privilege: str = "read",
    with_agent: bool = True,
    with_skill: bool = True,
    with_command: bool = True,
    agent_name: str | None = None,
    bad_manifest: bool = False,
    description: str = "Demo plugin for tests",
) -> Path:
    d = root / "plugins" / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    man = {
        "name": plugin_id,
        "version": "0.1.0",
        "description": description,
        "category": "test",
        "privilege": privilege,
        "tags": ["test", privilege],
    }
    if bad_manifest:
        (d / "plugin.json").write_text("{not json", encoding="utf-8")
    else:
        (d / "plugin.json").write_text(json.dumps(man, indent=2), encoding="utf-8")

    if with_agent:
        agents = d / "agents"
        agents.mkdir(exist_ok=True)
        aname = agent_name or f"{plugin_id}-agent"
        (agents / f"{aname}.md").write_text(
            f"---\nname: {aname}\n---\n\n# Agent {aname}\n\nDo useful work in tests.\n",
            encoding="utf-8",
        )
    if with_command:
        commands = d / "commands"
        commands.mkdir(exist_ok=True)
        (commands / "demo-cmd.md").write_text(
            "---\nname: demo-cmd\n---\n\n# /demo-cmd\n\nRun the demo.\n",
            encoding="utf-8",
        )
    if with_skill:
        skill = d / "skills" / "demo-skill"
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(
            "---\nname: demo-skill\n---\n\n# Skill demo\n\n"
            "## When to use\n\n- unit tests\n\n## Success\n\n- ok\n",
            encoding="utf-8",
        )
    return d


# ---------------------------------------------------------------------------
# Core library
# ---------------------------------------------------------------------------


def test_list_and_validate_ok(tmp_path: Path):
    _write_plugin(tmp_path)
    rows = mp.list_plugins(tmp_path, validate=True)
    assert len(rows) == 1
    assert rows[0].id == "demo-plugin"
    assert rows[0].privilege == "read"
    assert rows[0].valid is True
    assert len(rows[0].agents) == 1
    assert len(rows[0].skills) == 1
    assert len(rows[0].commands) == 1
    rep = mp.validate_all(tmp_path)
    assert rep["ok"] is True
    assert rep["errors"] == 0


def test_validate_missing_components(tmp_path: Path):
    d = tmp_path / "plugins" / "empty"
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(
        json.dumps(
            {
                "name": "empty",
                "version": "0.0.1",
                "description": "no components",
            }
        ),
        encoding="utf-8",
    )
    rep = mp.validate_plugin(d)
    assert rep.ok is False
    assert any("no agents" in f.message for f in rep.findings)


def test_validate_bad_privilege(tmp_path: Path):
    d = _write_plugin(tmp_path)
    man = json.loads((d / "plugin.json").read_text(encoding="utf-8"))
    man["privilege"] = "root"
    (d / "plugin.json").write_text(json.dumps(man), encoding="utf-8")
    rep = mp.validate_plugin(d)
    assert rep.ok is False
    assert any("privilege" in f.message for f in rep.findings)


def test_claude_plugin_layout(tmp_path: Path):
    d = tmp_path / "plugins" / "claude-layout"
    d.mkdir(parents=True)
    (d / ".claude-plugin").mkdir()
    (d / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "claude-layout",
                "version": "1.0.0",
                "description": "claude-plugin path",
                "privilege": "read",
            }
        ),
        encoding="utf-8",
    )
    agents = d / "agents"
    agents.mkdir()
    (agents / "helper.md").write_text(
        "---\nname: helper\n---\n\n# Helper\n\nEnough body for validation pass.\n",
        encoding="utf-8",
    )
    info = mp.plugin_info(d)
    assert info.id == "claude-layout"
    assert info.agents == ["helper"]
    assert mp.validate_plugin(d).ok is True


def test_least_privilege_filter(tmp_path: Path):
    _write_plugin(tmp_path, "read-plug", privilege="read")
    _write_plugin(tmp_path, "ops-plug", privilege="ops")
    _write_plugin(tmp_path, "admin-plug", privilege="admin")
    rows = mp.list_plugins(tmp_path, max_privilege="write")
    ids = {r.id for r in rows}
    assert "read-plug" in ids
    assert "ops-plug" not in ids
    assert "admin-plug" not in ids


def test_collisions_cross_plugin(tmp_path: Path):
    _write_plugin(tmp_path, "alpha", agent_name="shared-agent")
    _write_plugin(tmp_path, "beta", agent_name="shared-agent")
    rep = mp.collisions(tmp_path)
    assert rep["ok"] is False
    assert rep["cross_plugin"] >= 1
    names = {d["name"] for d in rep["collisions"] if d.get("cross_plugin")}
    assert "shared-agent" in names


def test_collisions_clean(tmp_path: Path):
    _write_plugin(tmp_path, "alpha", agent_name="alpha-agent")
    _write_plugin(tmp_path, "beta", agent_name="beta-agent")
    # demo-cmd / demo-skill collide across plugins — expected for shared fixture names
    # rewrite beta skill/command names
    beta = tmp_path / "plugins" / "beta"
    (beta / "commands" / "demo-cmd.md").unlink()
    (beta / "commands" / "beta-cmd.md").write_text(
        "---\nname: beta-cmd\n---\n\n# /beta-cmd\n\nBeta only.\n",
        encoding="utf-8",
    )
    skill = beta / "skills" / "demo-skill" / "SKILL.md"
    skill.write_text(
        "---\nname: beta-skill\n---\n\n# Beta skill\n\nUnique content for beta.\n",
        encoding="utf-8",
    )
    rep = mp.collisions(tmp_path)
    assert rep["ok"] is True
    assert rep["cross_plugin"] == 0


def test_export_registries(tmp_path: Path):
    _write_plugin(tmp_path)
    out = tmp_path / "out"
    rep = mp.export_registries(
        tmp_path, out_root=out, harnesses=["claude", "cursor", "codex", "local"]
    )
    assert rep["ok"] is True
    assert (out / "marketplace.json").is_file()
    assert (out / "MARKETPLACE.md").is_file()
    claude = json.loads(
        (out / "claude" / ".claude-plugin" / "marketplace.json").read_text(
            encoding="utf-8"
        )
    )
    assert claude["plugins"][0]["name"] == "demo-plugin"
    assert "source" in claude["plugins"][0]
    cursor = json.loads(
        (out / "cursor" / ".cursor-plugin" / "marketplace.json").read_text(
            encoding="utf-8"
        )
    )
    assert cursor["plugins"][0]["name"] == "demo-plugin"
    unified = json.loads((out / "marketplace.json").read_text(encoding="utf-8"))
    assert unified["totals"]["plugins"] == 1
    assert unified["totals"]["agents"] == 1


def test_export_refuses_invalid(tmp_path: Path):
    d = tmp_path / "plugins" / "bad"
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(
        json.dumps({"name": "bad", "version": ""}),
        encoding="utf-8",
    )
    with pytest.raises(mp.MarketplaceError):
        mp.export_registries(tmp_path, out_root=tmp_path / "out")


def test_build_catalog(tmp_path: Path):
    _write_plugin(tmp_path)
    cat = mp.build_catalog(tmp_path, name="test-market", include_skillpacks=False)
    assert cat["schema"] == mp.SCHEMA_VERSION
    assert cat["name"] == "test-market"
    assert cat["totals"]["plugins"] == 1
    assert cat["plugins"][0]["counts"]["skills"] == 1
    assert cat["plugins"][0]["origin"] == "plugin"


def _write_skillpack(
    root: Path,
    pack_id: str = "thin-skill",
    *,
    privilege: str = "read",
    with_skill: bool = True,
    with_manifest: bool = True,
) -> Path:
    d = root / "skillpacks" / pack_id
    d.mkdir(parents=True, exist_ok=True)
    if with_manifest:
        (d / "manifest.json").write_text(
            json.dumps(
                {
                    "id": pack_id,
                    "version": "0.2.0",
                    "name": f"Pack {pack_id}",
                    "privilege": privilege,
                    "tags": ["test", "skillpack"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    if with_skill:
        (d / "SKILL.md").write_text(
            f"---\nname: {pack_id}\n---\n\n# Skill {pack_id}\n\n"
            "## When to use\n\n- tests\n\n## Commands\n\n```bash\necho ok\n```\n\n"
            "## Rules\n\n1. Stay offline.\n\n## Success\n\n- green\n",
            encoding="utf-8",
        )
    return d


def test_thin_skillpack_index(tmp_path: Path):
    _write_plugin(tmp_path, "real-plugin")
    _write_skillpack(tmp_path, "thin-skill")
    # same id as real plugin is skipped when include_skillpacks
    _write_skillpack(tmp_path, "real-plugin")
    rows = mp.list_plugins(tmp_path, include_skillpacks=True)
    by_id = {r.id: r for r in rows}
    assert "real-plugin" in by_id
    assert by_id["real-plugin"].origin == "plugin"
    assert "thin-skill" in by_id
    assert by_id["thin-skill"].origin == "skillpack"
    assert by_id["thin-skill"].skills == ["thin-skill"]
    assert by_id["thin-skill"].source == "skillpacks/thin-skill"
    # only one real-plugin (skillpack twin skipped)
    assert sum(1 for r in rows if r.id == "real-plugin") == 1

    cat = mp.build_catalog(tmp_path, include_skillpacks=True)
    assert cat["totals"]["from_plugins_dir"] == 1
    assert cat["totals"]["from_skillpacks"] == 1
    assert cat["totals"]["plugins"] == 2


def test_self_check_ok(tmp_path: Path):
    _write_plugin(tmp_path, "alpha", agent_name="alpha-agent")
    # unique command/skill names to avoid collisions
    beta = _write_plugin(tmp_path, "beta", agent_name="beta-agent")
    (beta / "commands" / "demo-cmd.md").unlink()
    (beta / "commands" / "beta-cmd.md").write_text(
        "---\nname: beta-cmd\n---\n\n# /beta-cmd\n\nBeta only command body.\n",
        encoding="utf-8",
    )
    skill = beta / "skills" / "demo-skill" / "SKILL.md"
    skill.write_text(
        "---\nname: beta-skill\n---\n\n# Beta skill\n\n"
        "## When to use\n\n- unique beta\n\n## Success\n\n- ok\n",
        encoding="utf-8",
    )
    _write_skillpack(tmp_path, "thin-skill")
    rep = mp.self_check(tmp_path)
    assert rep["ok"] is True
    assert rep["validate"]["ok"] is True
    assert rep["collisions"]["ok"] is True
    assert rep["skillpacks"]["ok"] is True
    assert rep["skillpacks"]["count"] == 1
    assert rep["garden"] is not None
    assert rep["garden"]["ok"] is True
    assert rep["portability"] is not None
    assert rep["portability"]["mean_score"] is not None
    assert 0.0 <= float(rep["portability"]["mean_score"]) <= 1.0


# ---------------------------------------------------------------------------
# Capabilities / portability / garden (wshobson multi-harness)
# ---------------------------------------------------------------------------


def test_capabilities_matrix():
    matrix = mp.capabilities_matrix()
    assert matrix["kind"] == "harness_capabilities"
    assert matrix["count"] == len(mp.SUPPORTED_HARNESSES)
    by_id = {h["harness_id"]: h for h in matrix["harnesses"]}
    assert by_id["codex"]["commands_native"] is False
    assert by_id["codex"]["commands_map_to_skills"] is True
    assert by_id["codex"]["skill_body_max_bytes"] == mp.CODEX_SKILL_BODY_MAX_BYTES
    assert by_id["claude"]["plugin_marketplace"] is True
    assert mp.capability("codex").skill_body_max_bytes == 8 * 1024
    with pytest.raises(mp.MarketplaceError):
        mp.capability("not-a-harness")


def test_portability_commands_degrade_to_skills(tmp_path: Path):
    _write_plugin(tmp_path, "with-cmds")
    rep = mp.portability(
        tmp_path,
        include_skillpacks=False,
        harnesses=["claude", "codex", "copilot"],
    )
    assert rep["ok"] is True
    assert rep["plugin_count"] == 1
    row = rep["plugins"][0]
    assert row["id"] == "with-cmds"
    by_h = {h["harness"]: h for h in row["harnesses"]}
    assert by_h["claude"]["score"] == 1.0
    assert by_h["claude"]["degradations"] == []
    assert "commands→skills" in by_h["codex"]["degradations"]
    assert by_h["codex"]["score"] < 1.0
    assert "commands→skills" in by_h["copilot"]["degradations"]
    assert row["score"] < 1.0  # mean pulled down by codex/copilot remap


def test_garden_oversize_skill(tmp_path: Path):
    d = _write_plugin(tmp_path, "fat-plugin")
    skill = d / "skills" / "demo-skill" / "SKILL.md"
    # body larger than Codex 8 KiB
    fat = "---\nname: demo-skill\n---\n\n# Fat\n\n" + ("x" * 9000)
    skill.write_text(fat, encoding="utf-8")
    rep = mp.garden(tmp_path, include_skillpacks=False)
    assert rep["oversize_skills"] >= 1
    assert rep["ok"] is True  # warning by default
    kinds = {f["kind"] for f in rep["findings"]}
    assert "skill_oversize" in kinds
    strict = mp.garden(tmp_path, include_skillpacks=False, fail_on_oversize=True)
    assert strict["ok"] is False
    assert strict["errors"] >= 1

    port = mp.portability(
        tmp_path,
        include_skillpacks=False,
        harnesses=["codex", "claude"],
    )
    assert any(
        f.get("kind") == "skill_oversize" and f.get("harness") == "codex"
        for f in port["findings"]
    )
    # claude has no body cap — oversize finding only for codex
    assert not any(
        f.get("kind") == "skill_oversize" and f.get("harness") == "claude"
        for f in port["findings"]
    )


def test_self_check_fails_missing_skillpack_body(tmp_path: Path):
    _write_plugin(tmp_path)
    _write_skillpack(tmp_path, "broken", with_skill=False, with_manifest=True)
    rep = mp.self_check(tmp_path)
    assert rep["ok"] is False
    assert rep["skillpacks"]["errors"] >= 1
    assert any("SKILL.md" in f.get("path", "") for f in rep["skillpacks"]["findings"])


def test_export_plugin_stubs(tmp_path: Path):
    _write_plugin(tmp_path)
    _write_skillpack(tmp_path, "thin-skill")
    out = tmp_path / "out"
    rep = mp.export_registries(
        tmp_path,
        out_root=out,
        harnesses=["local", "claude"],
        with_stubs=True,
        include_skillpacks=True,
    )
    assert rep["ok"] is True
    assert rep["stubs"]["ok"] is True
    assert rep["stubs"]["plugin_count"] == 2
    stub = out / "stubs" / "local" / "demo-plugin" / "plugin.stub.json"
    assert stub.is_file()
    body = json.loads(stub.read_text(encoding="utf-8"))
    assert body["harness"] == "local"
    assert body["name"] == "demo-plugin"
    assert "agents" in body
    thin = out / "stubs" / "claude" / "thin-skill" / "plugin.stub.json"
    assert thin.is_file()
    thin_body = json.loads(thin.read_text(encoding="utf-8"))
    assert thin_body["origin"] == "skillpack"


# ---------------------------------------------------------------------------
# Real repo seed plugin
# ---------------------------------------------------------------------------


def test_repo_nexus_durable_validates():
    root = Path(__file__).resolve().parents[1]
    plugins = mp.list_plugins(root)
    ids = {p.id for p in plugins}
    assert "nexus-durable" in ids
    rep = mp.validate_all(root)
    assert rep["ok"] is True
    op = next(p for p in plugins if p.id == "nexus-durable")
    assert op.privilege == "ops"
    assert "durable-operator" in op.agents
    assert "durable-operator-board" in op.skills
    assert "task-board" in op.commands
    col = mp.collisions(root)
    assert col["ok"] is True
    # skillpacks indexed as thin plugins
    rows = mp.list_plugins(root, include_skillpacks=True)
    origins = {r.id: r.origin for r in rows}
    assert origins.get("nexus-durable") == "plugin"
    assert origins.get("durable-operator") == "skillpack"
    sc = mp.self_check(root)
    assert sc["ok"] is True
    assert sc["skillpacks"]["count"] >= 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_list_validate_export(tmp_path: Path, capsys):
    _write_plugin(tmp_path)
    _write_skillpack(tmp_path, "thin-skill")
    assert cli_main(["marketplace", "list", "--path", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "demo-plugin" in out

    assert (
        cli_main(
            [
                "marketplace",
                "list",
                "--path",
                str(tmp_path),
                "--include-skillpacks",
                "--json",
            ]
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 2

    assert (
        cli_main(["marketplace", "validate", "--path", str(tmp_path), "--json"]) == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True

    assert (
        cli_main(["marketplace", "catalog", "--path", str(tmp_path), "--json"]) == 0
    )
    cat = json.loads(capsys.readouterr().out)
    # default catalog includes skillpacks
    assert cat["totals"]["plugins"] == 2
    assert cat["totals"]["from_skillpacks"] == 1
    assert "codex_skill_body_max_bytes" in cat["metadata"]

    assert (
        cli_main(
            ["marketplace", "self-check", "--path", str(tmp_path), "--json"]
        )
        == 0
    )
    sc = json.loads(capsys.readouterr().out)
    assert sc["ok"] is True
    assert sc["garden"]["ok"] is True
    assert sc["portability"]["mean_score"] is not None

    assert cli_main(["marketplace", "capabilities", "--json"]) == 0
    caps = json.loads(capsys.readouterr().out)
    assert caps["count"] >= 1
    assert any(h["harness_id"] == "codex" for h in caps["harnesses"])

    assert (
        cli_main(
            [
                "marketplace",
                "portability",
                "--path",
                str(tmp_path),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    port = json.loads(capsys.readouterr().out)
    assert port["kind"] == "portability"
    assert port["plugin_count"] >= 1

    assert (
        cli_main(
            ["marketplace", "garden", "--path", str(tmp_path), "--json"]
        )
        == 0
    )
    g = json.loads(capsys.readouterr().out)
    assert g["kind"] == "garden"

    out_dir = tmp_path / "gen"
    rc = cli_main(
        [
            "marketplace",
            "export",
            "--path",
            str(tmp_path),
            "--out",
            str(out_dir),
            "--harness",
            "local",
            "--json",
        ]
    )
    assert rc == 0
    gen = json.loads(capsys.readouterr().out)
    assert gen["ok"] is True
    assert (out_dir / "marketplace.json").is_file()
    assert (out_dir / "stubs" / "local" / "demo-plugin" / "plugin.stub.json").is_file()

    assert (
        cli_main(
            ["marketplace", "collisions", "--path", str(tmp_path), "--json"]
        )
        == 0
    )


def test_cli_max_privilege(tmp_path: Path, capsys):
    _write_plugin(tmp_path, "ops-only", privilege="ops")
    assert (
        cli_main(
            [
                "marketplace",
                "list",
                "--path",
                str(tmp_path),
                "--max-privilege",
                "read",
                "--json",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["plugins"] == []


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------


def test_mcp_marketplace_tool(tmp_path: Path, monkeypatch):
    _write_plugin(tmp_path)
    _write_skillpack(tmp_path, "thin-skill")
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    r = mcp_server.call_tool("marketplace", {"action": "list"})
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["count"] == 1
    assert body["plugins"][0]["id"] == "demo-plugin"

    r = mcp_server.call_tool("marketplace", {"action": "validate"})
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["ok"] is True

    r = mcp_server.call_tool("marketplace", {"action": "catalog"})
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["totals"]["plugins"] == 2
    assert body["totals"]["from_skillpacks"] == 1

    r = mcp_server.call_tool("marketplace", {"action": "self_check"})
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["ok"] is True
    assert body["skillpacks"]["count"] == 1
    assert body["garden"]["ok"] is True
    assert body["portability"]["mean_score"] is not None

    r = mcp_server.call_tool("marketplace", {"action": "capabilities"})
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["kind"] == "harness_capabilities"
    assert body["count"] >= 1

    r = mcp_server.call_tool(
        "marketplace", {"action": "portability", "harness": "codex"}
    )
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["kind"] == "portability"

    r = mcp_server.call_tool("marketplace", {"action": "garden"})
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["kind"] == "garden"

    r = mcp_server.call_tool(
        "marketplace", {"action": "export", "harness": "local"}
    )
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["ok"] is True
    assert body.get("stubs", {}).get("plugin_count") == 2

    r = mcp_server.call_tool("marketplace", {"action": "collisions"})
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert "collisions" in body


def test_mcp_tool_registered():
    names = {t["name"] for t in mcp_server.TOOLS}
    assert "marketplace" in names
    mkt = next(t for t in mcp_server.TOOLS if t["name"] == "marketplace")
    desc = mkt["description"] + " " + mkt["inputSchema"]["properties"]["action"][
        "description"
    ]
    assert "portability" in desc
    assert "garden" in desc
    assert "capabilities" in desc
    assert "generate" in desc
    assert "validate_generated" in desc
    assert "round_trip" in desc


# ---------------------------------------------------------------------------
# Multi-harness adapters (generate + validate_generated)
# ---------------------------------------------------------------------------


def test_adapt_markdown_drops_claude_only_and_maps_model():
    src = (
        "---\nname: reviewer\nmodel: opus\ncolor: blue\ntools: Read, Grep\n---\n\n"
        "# Reviewer\n\nDo reviews.\n"
    )
    out, notes = mp.adapt_markdown(src, harness="codex", kind="agent")
    assert "color:" not in out
    assert "tools:" not in out
    assert "model: gpt-5.5" in out
    assert any(n.startswith("model:") for n in notes)
    assert any(n.startswith("drop:") for n in notes)
    # claude keeps fields
    claude, _ = mp.adapt_markdown(src, harness="claude", kind="agent")
    assert "color: blue" in claude
    assert "model: opus" in claude


def test_split_skill_for_cap():
    big_body = "x" * 9000
    content = f"---\nname: fat\n---\n\n# Fat skill\n\n{big_body}\n"
    skill, overflow, did = mp.split_skill_for_cap(
        content, mp.CODEX_SKILL_BODY_MAX_BYTES
    )
    assert did is True
    assert overflow is not None
    assert len(skill.encode("utf-8")) <= mp.CODEX_SKILL_BODY_MAX_BYTES
    assert "references/details.md" in skill
    small = "---\nname: thin\n---\n\n# Thin\n\nShort body.\n"
    s2, o2, d2 = mp.split_skill_for_cap(small, mp.CODEX_SKILL_BODY_MAX_BYTES)
    assert d2 is False
    assert o2 is None
    assert s2 == small


def test_generate_adapters_codex_maps_commands_to_skills(tmp_path: Path):
    _write_plugin(
        tmp_path,
        "demo-plugin",
        with_agent=True,
        with_skill=True,
        with_command=True,
    )
    # agent with model alias for transform notes
    agent = tmp_path / "plugins" / "demo-plugin" / "agents" / "demo-plugin-agent.md"
    agent.write_text(
        "---\nname: demo-plugin-agent\nmodel: opus\ncolor: red\n---\n\n# Agent\n",
        encoding="utf-8",
    )
    out = tmp_path / "adapters"
    rep = mp.generate_adapters(
        tmp_path,
        out_root=out,
        harnesses=["codex", "claude"],
        include_skillpacks=False,
    )
    assert rep["ok"] is True
    assert rep["plugin_count"] == 1
    assert rep["result_count"] == 2

    codex_plugin = out / "codex" / "plugins" / "demo-plugin"
    assert (codex_plugin / "plugin.meta.json").is_file()
    assert (codex_plugin / "adapter.index.json").is_file()
    # commands mapped to skills
    assert not (codex_plugin / "commands").exists() or not list(
        (codex_plugin / "commands").glob("*.md")
    )
    assert (codex_plugin / "skills" / "cmd-demo-cmd" / "SKILL.md").is_file()
    assert (codex_plugin / "skills" / "demo-skill" / "SKILL.md").is_file()
    agent_out = (codex_plugin / "agents" / "demo-plugin-agent.md").read_text(
        encoding="utf-8"
    )
    assert "model: gpt-5.5" in agent_out
    assert "color:" not in agent_out

    # claude keeps commands native
    claude_plugin = out / "claude" / "plugins" / "demo-plugin"
    assert (claude_plugin / "commands" / "demo-cmd.md").is_file()

    gate = mp.validate_generated(out, harnesses=["codex", "claude"])
    assert gate["ok"] is True
    assert gate["errors"] == 0
    assert gate["plugin_count"] == 2


def test_generate_adapters_skill_cap_split(tmp_path: Path):
    d = _write_plugin(tmp_path, "fat-plugin", with_command=False, with_agent=False)
    skill = d / "skills" / "demo-skill" / "SKILL.md"
    skill.write_text(
        "---\nname: demo-skill\n---\n\n# Big skill\n\n"
        + ("detail line\n" * 800),
        encoding="utf-8",
    )
    assert skill.stat().st_size > mp.CODEX_SKILL_BODY_MAX_BYTES
    out = tmp_path / "adapters"
    rep = mp.generate_adapters(
        tmp_path,
        out_root=out,
        harnesses=["codex"],
        include_skillpacks=False,
    )
    assert rep["ok"] is True
    skill_out = out / "codex" / "plugins" / "fat-plugin" / "skills" / "demo-skill"
    body = (skill_out / "SKILL.md").read_bytes()
    assert len(body) <= mp.CODEX_SKILL_BODY_MAX_BYTES
    assert (skill_out / "references" / "details.md").is_file()
    gate = mp.validate_generated(out, harnesses=["codex"])
    assert gate["ok"] is True


def test_generate_refuses_invalid(tmp_path: Path):
    d = tmp_path / "plugins" / "bad"
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(
        json.dumps({"name": "bad", "version": ""}),
        encoding="utf-8",
    )
    with pytest.raises(mp.MarketplaceError):
        mp.generate_adapters(tmp_path, out_root=tmp_path / "out")


def test_cli_generate_and_validate_generated(tmp_path: Path, capsys):
    _write_plugin(tmp_path)
    out = tmp_path / "adapters"
    rc = cli_main(
        [
            "marketplace",
            "generate",
            "--path",
            str(tmp_path),
            "--out",
            str(out),
            "--harness",
            "codex",
            "--harness",
            "local",
            "--no-skillpacks",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["kind"] == "generate_adapters"
    assert (out / "codex" / "plugins" / "demo-plugin" / "plugin.meta.json").is_file()

    rc = cli_main(
        [
            "marketplace",
            "validate-generated",
            "--out",
            str(out),
            "--harness",
            "codex",
            "--json",
        ]
    )
    assert rc == 0
    gate = json.loads(capsys.readouterr().out)
    assert gate["ok"] is True
    assert gate["kind"] == "validate_generated"


def test_mcp_marketplace_generate(tmp_path: Path, monkeypatch):
    _write_plugin(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    r = mcp_server.call_tool(
        "marketplace",
        {"action": "generate", "harness": "cursor", "plugin": "demo-plugin"},
    )
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["ok"] is True
    assert body["plugin_count"] == 1

    r = mcp_server.call_tool(
        "marketplace",
        {"action": "validate_generated", "harness": "cursor"},
    )
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["ok"] is True
    assert body["kind"] == "validate_generated"


def test_repo_nexus_durable_generate_adapters(tmp_path: Path):
    """Smoke: generate adapters for the in-tree seed plugin layout."""
    root = Path(__file__).resolve().parents[1]
    src = root / "plugins" / "nexus-durable"
    if not src.is_dir():
        pytest.skip("nexus-durable seed plugin missing")
    # Copy into isolated workdir so we don't write into the real tree
    import shutil

    dest_root = tmp_path
    shutil.copytree(src, dest_root / "plugins" / "nexus-durable")
    out = tmp_path / "adapters"
    rep = mp.generate_adapters(
        dest_root,
        out_root=out,
        harnesses=["claude", "codex", "copilot"],
        include_skillpacks=False,
    )
    assert rep["ok"] is True
    assert (out / "codex" / "plugins" / "nexus-durable" / "plugin.meta.json").is_file()
    # seed has a command → codex maps to skill
    assert (
        out / "codex" / "plugins" / "nexus-durable" / "skills"
    ).is_dir()
    gate = mp.validate_generated(
        out, harnesses=["claude", "codex", "copilot"]
    )
    assert gate["ok"] is True


# ---------------------------------------------------------------------------
# Round-trip integrity (wshobson test_round_trip shape)
# ---------------------------------------------------------------------------


def test_expected_counts_command_map():
    info = mp.PluginInfo(
        id="x",
        name="x",
        version="0.1.0",
        path="/tmp/x",
        agents=["a1"],
        skills=["s1"],
        commands=["c1", "c2"],
    )
    claude = mp.expected_counts_for_harness(info, "claude")
    assert claude == {"agents": 1, "skills": 1, "commands": 2}
    codex = mp.expected_counts_for_harness(info, "codex")
    assert codex == {"agents": 1, "skills": 3, "commands": 0}  # +2 mapped cmds
    copilot = mp.expected_counts_for_harness(info, "copilot")
    assert copilot == {"agents": 1, "skills": 3, "commands": 0}


def test_round_trip_ok(tmp_path: Path):
    _write_plugin(tmp_path, "demo-plugin")
    out = tmp_path / "adapters"
    rep = mp.round_trip(
        tmp_path,
        out_root=out,
        harnesses=["claude", "codex", "copilot"],
        include_skillpacks=False,
        clean=True,
    )
    assert rep["ok"] is True
    assert rep["kind"] == "round_trip"
    assert rep["errors"] == 0
    assert rep["counts"]["ok"] is True
    assert rep["counts"]["mismatches"] == 0
    assert rep["validate_generated"]["ok"] is True
    # claude keeps command; codex maps it to skill
    comps = {(c["harness"], c["plugin_id"]): c for c in rep["comparisons"]}
    assert comps[("claude", "demo-plugin")]["generated"]["commands"] == 1
    assert comps[("codex", "demo-plugin")]["generated"]["commands"] == 0
    assert comps[("codex", "demo-plugin")]["generated"]["skills"] == 2  # skill+cmd


def test_round_trip_detects_count_mismatch(tmp_path: Path):
    _write_plugin(tmp_path, "demo-plugin")
    out = tmp_path / "adapters"
    mp.generate_adapters(
        tmp_path,
        out_root=out,
        harnesses=["claude"],
        include_skillpacks=False,
    )
    # Sabotage: drop an agent so counts fail
    agent_dir = out / "claude" / "plugins" / "demo-plugin" / "agents"
    for f in agent_dir.glob("*.md"):
        f.unlink()
    counts = mp.check_round_trip_counts(
        tmp_path,
        out,
        harnesses=["claude"],
        include_skillpacks=False,
    )
    assert counts["ok"] is False
    assert counts["mismatches"] >= 1
    assert any("count mismatch" in (f.get("message") or "") for f in counts["findings"])


def test_cli_round_trip(tmp_path: Path, capsys):
    _write_plugin(tmp_path)
    out = tmp_path / "rt"
    rc = cli_main(
        [
            "marketplace",
            "round-trip",
            "--path",
            str(tmp_path),
            "--out",
            str(out),
            "--harness",
            "claude",
            "--harness",
            "codex",
            "--no-skillpacks",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["kind"] == "round_trip"
    assert data["counts"]["mismatches"] == 0


def test_mcp_marketplace_round_trip(tmp_path: Path, monkeypatch):
    _write_plugin(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    r = mcp_server.call_tool(
        "marketplace",
        {"action": "round_trip", "harness": "claude", "plugin": "demo-plugin"},
    )
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["ok"] is True
    assert body["kind"] == "round_trip"
    assert body["plugin_count"] == 1


def test_repo_smoke_round_trip(tmp_path: Path):
    """Seed plugin round-trip without writing into the real .nexus_state tree."""
    root = Path(__file__).resolve().parents[1]
    src = root / "plugins" / "nexus-durable"
    if not src.is_dir():
        pytest.skip("nexus-durable seed plugin missing")
    import shutil

    dest_root = tmp_path
    shutil.copytree(src, dest_root / "plugins" / "nexus-durable")
    rep = mp.round_trip(
        dest_root,
        out_root=tmp_path / "adapters",
        harnesses=list(mp.ROUND_TRIP_SMOKE_HARNESSES),
        include_skillpacks=False,
    )
    assert rep["ok"] is True
    assert rep["errors"] == 0
    # human format should not raise
    text = mp.format_round_trip(rep)
    assert "round-trip" in text
    assert "ok=True" in text
