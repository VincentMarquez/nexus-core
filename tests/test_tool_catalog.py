"""Tests for P2.2 OpenAPI-ish MCP tool catalog export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import mcp_server
from nexus import tool_catalog as tc
from nexus.cli import main as cli_main


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_TOOLS = [
    {
        "name": "alpha_read",
        "description": "Read something",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "x-nexus-privilege": "read",
    },
    {
        "name": "beta_write",
        "description": "Write something",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        "privilege": "write",
    },
    {
        "name": "gamma_ops",
        "description": "Ops side effect",
        "inputSchema": {"type": "object", "properties": {}},
        # no privilege → defaults to ops
    },
]


# ---------------------------------------------------------------------------
# Core library
# ---------------------------------------------------------------------------


def test_build_entries_privilege_and_filter():
    entries = tc.build_entries(SAMPLE_TOOLS)
    names = [e.name for e in entries]
    assert names == ["alpha_read", "beta_write", "gamma_ops"]
    by_name = {e.name: e for e in entries}
    assert by_name["alpha_read"].privilege == "read"
    assert by_name["beta_write"].privilege == "write"
    assert by_name["gamma_ops"].privilege == "ops"
    assert by_name["alpha_read"].required == ["path"]

    only_read = tc.build_entries(SAMPLE_TOOLS, max_privilege="read")
    assert [e.name for e in only_read] == ["alpha_read"]

    up_to_write = tc.build_entries(SAMPLE_TOOLS, max_privilege="write")
    assert [e.name for e in up_to_write] == ["alpha_read", "beta_write"]


def test_build_catalog_schema():
    cat = tc.build_catalog(
        SAMPLE_TOOLS,
        server_name="test-server",
        server_version="9.9.9",
    )
    assert cat["schema"] == tc.SCHEMA_VERSION
    assert cat["server"] == "test-server"
    assert cat["version"] == "9.9.9"
    assert cat["tool_count"] == 3
    assert cat["by_privilege"]["read"] == 1
    assert cat["by_privilege"]["write"] == 1
    assert cat["by_privilege"]["ops"] == 1
    assert len(cat["tools"]) == 3


def test_build_openapi_paths_and_privilege():
    doc = tc.build_openapi(
        SAMPLE_TOOLS,
        server_name="test-server",
        server_version="1.0.0",
    )
    assert doc["openapi"] == tc.OPENAPI_VERSION
    assert doc["info"]["title"].startswith("test-server")
    paths = doc["paths"]
    assert "/tools/alpha_read" in paths
    assert "/tools/beta_write" in paths
    assert "/tools/gamma_ops" in paths
    assert "/tools" in paths
    assert "/tools/call" in paths
    assert "/openapi.json" in paths
    post = paths["/tools/alpha_read"]["post"]
    assert post["operationId"] == "alpha_read"
    assert post["x-nexus-privilege"] == "read"
    assert post["tags"] == ["read"]
    body_schema = post["requestBody"]["content"]["application/json"]["schema"]
    assert "path" in body_schema["properties"]
    assert doc["x-nexus-catalog"]["tool_count"] == 3


def test_validate_ok_and_errors():
    rep = tc.validate_tools(SAMPLE_TOOLS)
    # gamma_ops has no explicit privilege → warning only
    assert rep.ok is True
    assert any(f.severity == "warning" and f.tool == "gamma_ops" for f in rep.findings)

    bad = [
        {
            "name": "broken",
            "description": "x",
            "inputSchema": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["missing_field"],
            },
        },
        {
            "name": "broken",  # duplicate
            "description": "y",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "no_schema",
            "description": "z",
        },
    ]
    rep2 = tc.validate_tools(bad)
    assert rep2.ok is False
    msgs = " ".join(f.message for f in rep2.findings)
    assert "duplicate" in msgs
    assert "not in properties" in msgs
    assert "missing inputSchema" in msgs


def test_export_writes_files(tmp_path: Path):
    result = tc.export_catalog(
        tmp_path,
        out_dir=".nexus_state/tool_catalog",
        tools=SAMPLE_TOOLS,
    )
    assert result["ok"] is True
    assert result["tool_count"] == 3
    cat_path = Path(result["files"]["catalog"])
    oas_path = Path(result["files"]["openapi"])
    assert cat_path.is_file()
    assert oas_path.is_file()
    cat = json.loads(cat_path.read_text(encoding="utf-8"))
    oas = json.loads(oas_path.read_text(encoding="utf-8"))
    assert cat["schema"] == tc.SCHEMA_VERSION
    assert oas["openapi"] == tc.OPENAPI_VERSION
    assert (tmp_path / ".nexus_state/tool_catalog/summary.md").is_file()


def test_live_mcp_tools_validate_and_export(tmp_path: Path):
    """Smoke against real mcp_server.TOOLS (AssetOpsBench-shaped eval smoke)."""
    rep = tc.validate_tools()
    assert rep.ok is True, tc.format_validate(rep)

    entries = tc.build_entries()
    names = {e.name for e in entries}
    assert "list_project_files" in names
    assert "tool_catalog" in names
    assert "skillpacks" in names

    # Every live tool gets an OpenAPI path
    oas = tc.build_openapi()
    for n in names:
        assert f"/tools/{n}" in oas["paths"]

    # Privilege map covers all live tools (no silent ops-default surprises for known set)
    unmapped = [
        e.name
        for e in entries
        if e.name not in tc.TOOL_PRIVILEGE and e.name != "tool_catalog"
    ]
    # tool_catalog is in TOOL_PRIVILEGE; unmapped should be empty for production tools
    assert unmapped == [], f"add TOOL_PRIVILEGE entries for: {unmapped}"

    result = tc.export_catalog(tmp_path)
    assert result["ok"] is True
    assert result["tool_count"] == len(mcp_server.TOOLS)


def test_format_list_and_summary():
    entries = tc.build_entries(SAMPLE_TOOLS)
    text = tc.format_list(entries)
    assert "alpha_read" in text
    assert "read" in text
    cat = tc.build_catalog(SAMPLE_TOOLS)
    md = tc.format_summary(cat)
    assert "nexus.tool_catalog" in md
    assert "`alpha_read`" in md


# ---------------------------------------------------------------------------
# MCP + CLI
# ---------------------------------------------------------------------------


def test_mcp_tool_catalog_actions(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))

    listed = mcp_server.call_tool("tool_catalog", {"action": "list", "max_privilege": "read"})
    assert listed["isError"] is False
    body = json.loads(listed["content"][0]["text"])
    assert body["schema"] == tc.SCHEMA_VERSION
    assert body["count"] >= 1
    assert all(t["privilege"] == "read" for t in body["tools"])

    val = mcp_server.call_tool("tool_catalog", {"action": "validate"})
    assert val["isError"] is False
    vbody = json.loads(val["content"][0]["text"])
    assert vbody["ok"] is True

    oas = mcp_server.call_tool("tool_catalog", {"action": "openapi"})
    assert oas["isError"] is False
    obody = json.loads(oas["content"][0]["text"])
    assert obody["openapi"] == tc.OPENAPI_VERSION

    exp = mcp_server.call_tool(
        "tool_catalog",
        {"action": "export", "out_dir": ".nexus_state/tool_catalog"},
    )
    assert exp["isError"] is False
    ebody = json.loads(exp["content"][0]["text"])
    assert ebody["ok"] is True
    assert (tmp_path / ".nexus_state/tool_catalog/openapi.json").is_file()

    # path jail: reject .. in out_dir
    bad = mcp_server.call_tool(
        "tool_catalog", {"action": "export", "out_dir": "../escape"}
    )
    assert bad["isError"] is True


def test_mcp_tools_list_includes_tool_catalog():
    resp = mcp_server.handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    names = [t["name"] for t in resp["result"]["tools"]]
    assert "tool_catalog" in names


def test_cli_tools_list_validate_export(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # list
    rc = cli_main(["tools", "list", "--json", "--max-privilege", "read"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema"] == tc.SCHEMA_VERSION
    assert data["count"] >= 1

    # validate (uses live TOOLS — not cwd dependent)
    rc = cli_main(["tools", "validate", "--json"])
    assert rc == 0
    v = json.loads(capsys.readouterr().out)
    assert v["ok"] is True

    # export under tmp project
    rc = cli_main(["tools", "export", "--path", str(tmp_path), "--json"])
    assert rc == 0
    exp = json.loads(capsys.readouterr().out)
    assert exp["ok"] is True
    assert Path(exp["files"]["openapi"]).is_file()

    # openapi to file
    out_oas = tmp_path / "my-openapi.json"
    rc = cli_main(
        ["tools", "openapi", "--path", str(tmp_path), "--out", str(out_oas)]
    )
    assert rc == 0
    assert out_oas.is_file()
    oas = json.loads(out_oas.read_text(encoding="utf-8"))
    assert oas["openapi"] == tc.OPENAPI_VERSION


def test_privilege_rank_helpers():
    assert tc.allowed_by_max("read", "read") is True
    assert tc.allowed_by_max("write", "read") is False
    assert tc.allowed_by_max("ops", "admin") is True
    assert tc.privilege_for("list_project_files") == "read"
    assert tc.privilege_for("write_to_project") == "write"
    assert tc.privilege_for("skillpacks") == "ops"
    assert tc.privilege_for("unknown_tool_xyz") == "ops"
    with pytest.raises(tc.CatalogError):
        tc._norm_privilege("superuser")
