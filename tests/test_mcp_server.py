import json
from pathlib import Path

from nexus import mcp_server


def test_list_and_write_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "hello.txt").write_text("hi\n", encoding="utf-8")

    listed = mcp_server.call_tool("list_project_files", {"path": "."})
    assert "hello.txt" in listed["content"][0]["text"]

    read = mcp_server.call_tool("read_project_file", {"path": "hello.txt"})
    assert "hi" in read["content"][0]["text"]

    wrote = mcp_server.call_tool(
        "write_to_project", {"path": "out/note.md", "content": "from mcp\n"}
    )
    assert wrote["isError"] is False
    assert (tmp_path / "out" / "note.md").read_text() == "from mcp\n"

    mcp_server.call_tool(
        "send_to_workspace",
        {"agent": "test_agent", "message": "ping", "label": "test"},
    )
    chat = mcp_server.call_tool("read_workspace_chat", {"count": 5})
    assert "ping" in chat["content"][0]["text"]


def test_path_jail(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    bad = mcp_server.call_tool("read_project_file", {"path": "../outside.txt"})
    assert bad["isError"] is True


def test_initialize_rpc():
    resp = mcp_server.handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert resp["result"]["serverInfo"]["name"] == "nexus-workspace"
    tools = mcp_server.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in tools["result"]["tools"]]
    assert "list_project_files" in names
