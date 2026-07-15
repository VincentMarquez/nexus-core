from pathlib import Path

from nexus.platforms import (
    agent_flow_map,
    connect_cursor,
    detect_platforms,
    format_status_table,
    mcp_server_command_fixed,
    write_grok_mcp_snippet,
)
from nexus.mcp_server import TOOLS, call_tool


def test_detect_platforms():
    plats = detect_platforms(project_root=Path.cwd())
    ids = {p.id for p in plats}
    assert "grok" in ids and "nexus" in ids and "ollama" in ids
    table = format_status_table(plats)
    assert "Grok" in table or "grok" in table.lower()


def test_mcp_spec_has_project_root(tmp_path):
    spec = mcp_server_command_fixed(tmp_path)
    assert "nexus.mcp_server" in " ".join(spec["args"])
    assert str(tmp_path.resolve()) in spec["env"]["NEXUS_PROJECT_ROOT"]


def test_grok_snippet():
    s = write_grok_mcp_snippet(Path("/tmp/proj"))
    assert "[mcp_servers.nexus-workspace]" in s
    assert "nexus.mcp_server" in s


def test_connect_cursor(tmp_path):
    res = connect_cursor(tmp_path, force=True)
    assert res["ok"] is True
    p = Path(res["config"])
    assert p.is_file()
    data = p.read_text(encoding="utf-8")
    assert "nexus-workspace" in data


def test_agent_flow_has_shared_tools():
    flow = agent_flow_map()
    assert "run_project_checks" in flow["shared_tools"]
    assert flow["ingress"]


def test_mcp_tools_include_parity():
    names = {t["name"] for t in TOOLS}
    for n in (
        "run_project_checks",
        "bus_status",
        "list_platforms",
        "github_community_status",
    ):
        assert n in names


def test_list_platforms_tool():
    r = call_tool("list_platforms", {})
    assert r.get("isError") is not True
    text = r["content"][0]["text"]
    assert "nexus" in text.lower() or "Grok" in text or "grok" in text
