# 10 — Multi-platform agents + local LLM tools

**Goal:** Connect supported model clients and a local LLM to registered NEXUS
tools, then hand work between configured agent slots.

## Inspect first

```bash
export NEXUS_PROJECT_ROOT="${NEXUS_PROJECT_ROOT:-$PWD}"
cd "$NEXUS_PROJECT_ROOT"
make install
source .venv/bin/activate
nexus platforms status
nexus platforms doctor
```

`status` and `doctor` are read-only. `platforms connect` writes client
configuration and may place absolute local paths into project example files.
Review the diff and generated config before committing or sharing it.

To connect selected clients after that review:

```bash
nexus platforms connect --path "$NEXUS_PROJECT_ROOT"
```

Use `--force` only when you intend to overwrite existing MCP entries. Add
`--start` only when you also want to start the local runtime.

## Grok CLI (cloud or local model)

```bash
grok
# MCP server: nexus-workspace should be enabled
# /model gemma4          # or nexus-local / any local endpoint
# Ask: "list platforms and run project checks"
```

The host executes registered tools; the model selects among tools exposed by
that client. Available capabilities depend on client MCP/tool-call support, the
enabled NEXUS catalog, host permissions, and whether the model emits valid tool
requests. Do not assume universal tool parity.

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

## Diagnose the mesh

```bash
nexus platforms doctor
# tool from python:
python -c "from nexus.mcp_server import call_tool; print(call_tool('list_platforms',{}))"
```

`nexus platforms doctor --fix` reruns `connect --force`; inspect existing
configuration before using it.

Full docs: [docs/PLATFORMS.md](../PLATFORMS.md)
