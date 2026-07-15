# 10 — Multi-platform agents + local LLM full tools

**Goal:** Grok CLI (now), Cursor, Claude, and a **local LLM** all share the same NEXUS tools and hand off work.

## Connect once

```bash
cd ~/nexus-core   # or your project
make install
nexus platforms status
nexus platforms connect --force --start
nexus platforms doctor
```

## Grok CLI (cloud or local model)

```bash
grok
# MCP server: nexus-workspace should be enabled
# /model gemma4          # or nexus-local / any local endpoint
# Ask: "list platforms and run project checks"
```

The host (Grok) executes tools; the model only selects them — local models get **full tool parity**.

## Local LLM on the NEXUS bus (not only inside Grok)

```bash
nexus start -y
# Ollama agent `local` uses bridge/bridges/ollama_tools.py
# NEXUS_OLLAMA_TOOLS=1  (default) → TOOL_CALL loop → mcp_server.call_tool
```

Disable tools on bus only if needed:

```bash
NEXUS_OLLAMA_TOOLS=0 nexus start -y
```

## Cursor

Project file `.cursor/mcp.json` is written by `platforms connect`. Enable MCP in Cursor settings.

## Agent handoff

```text
Grok  → send_to_workspace(agent="grok_cli", message="…")
local → bus step / send_to_workspace(agent="local")
Cursor → agent="cursor"
```

## Prove the mesh

```bash
nexus platforms doctor --fix
# tool from python:
python -c "from nexus.mcp_server import call_tool; print(call_tool('list_platforms',{}))"
```

Full docs: [docs/PLATFORMS.md](../docs/PLATFORMS.md)
