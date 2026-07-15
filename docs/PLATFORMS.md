# Multi-platform agents + local LLM tool parity

NEXUS is the **hub**. Grok CLI (now), Cursor, Claude, Codex, Gemini, and **local LLMs** are **spokes**. Every spoke should use the **same tools** and hand off work through the same workspace.

## Goal

| Want | How |
|------|-----|
| Run a **local LLM inside Grok CLI** | `nexus platforms connect` registers Ollama as `[model.nexus-local]` + MCP tools |
| Auto-connect Grok / Cursor / Claude | `nexus platforms connect` |
| Agents from other products join the same job | Distinct `agent` ids + `send_to_workspace` / bus bridges |
| Local model uses **all** tools | MCP host (Grok/Cursor) executes tools; model only chooses them |

## One-time setup

```bash
cd /path/to/your/project
pip install -e ".[dev]"   # or make install
nexus platforms status
nexus platforms connect --start
```

What `connect` does:

1. **Grok CLI** — `mcp_servers.nexus-workspace` in `~/.grok/config.toml` (or `grok mcp add`)
2. **Grok local model** — optional `[model.nexus-local]` → `http://127.0.0.1:11434/v1` (Ollama)
3. **Cursor** — `.cursor/mcp.json` in the project
4. **Claude** — `connectors/examples/claude-desktop.nexus.json` (+ desktop config if found)
5. **`--start`** — `nexus start -y` so Ollama bridge agent `local` is on the event bus

## Shared tools (Workspace MCP)

| Tool | Purpose |
|------|---------|
| `list_project_files` | Tree under project jail |
| `read_project_file` / `write_to_project` | File IO |
| `send_to_workspace` / `read_workspace_chat` | Multi-agent handoff log |
| `nexus_status` | Root + runtime |
| `run_project_checks` | Evidence: install + pytest + smoke |
| `bus_status` | Which agents (local/claude/gpt/…) are online |
| `github_community_status` | `gh` + target repo |
| `list_platforms` | Detected clients on this machine |

## Agent flow

```text
Grok CLI (cloud or local model) ──MCP──┐
Cursor ──MCP────────────────────────────┤
Claude ──MCP / CLI bridge───────────────┼──► NEXUS hub
Codex / Gemini ──CLI bridge─────────────┤     · Workspace MCP tools
Ollama ──bus agent `local`──────────────┘     · event bus
                                              · durable jobs
                                              · github scout/loop
         ◄──── workspace chat handoff ────────┘
```

Agent ids (use consistently):

| Platform | `agent` id |
|----------|------------|
| Grok CLI | `grok_cli` |
| Cursor | `cursor` |
| Claude | `claude` |
| Codex | `gpt` |
| Gemini | `gemini` |
| Ollama / local | `local` |

## Grok CLI + local LLM

**Split of labor (recommended):**

| | Grok (cloud) | Local Ollama / `nexus-local` |
|--|---------------|------------------------------|
| Role | **Hard work + grading** | **Light work** |
| Used by | `mine evaluate`, `improve-ours --apply`, alive cycles | bus agent `local`, drafts, cheap turns |
| Config | `NEXUS_GROK_MODEL=grok-4.5` (optional) | `OLLAMA_MODEL` / platforms connect |

```bash
nexus platforms connect --model gemma2   # or your ollama tag
ollama serve                             # if not already
nexus start -y
# headless hard grade/work is automatic when mine/alive run with grader/worker=auto
grok
# in TUI: /model nexus-local   # light interactive
# MCP tools appear for that model the same as for grok-build
```

If you already use a custom Grok `[model.gemma4]` (or similar), keep it — `connect` only adds `nexus-workspace` MCP + optional `nexus-local`. **MCP tools attach to the session**, not to a single vendor model.

## Cursor / others later

Same MCP server command:

```json
{
  "mcpServers": {
    "nexus-workspace": {
      "command": "python3",
      "args": ["-m", "nexus.mcp_server"],
      "env": {
        "NEXUS_PROJECT_ROOT": "/absolute/path/to/project",
        "PYTHONPATH": "/absolute/path/to/nexus-core/src"
      }
    }
  }
}
```

`nexus platforms connect` writes this automatically for Cursor project scope.

## Safety

- Tools are **project-jailed** (`NEXUS_PROJECT_ROOT`)
- `connect` only writes config when you run it (opt-in)
- Local model still goes through the host’s permission UI (Grok/Cursor)
- Bus CLI bridges remain separate from MCP (both can run together)

## Local LLM on the bus (tool loop)

`nexus start` sets `NEXUS_OLLAMA_TOOLS=1`. The Ollama bridge runs
`bridge/bridges/ollama_tools.py`, which teaches the model:

```text
TOOL_CALL {"name": "run_project_checks", "arguments": {}}
```

Tools execute via `nexus.mcp_server.call_tool` — the **same** implementations
Grok CLI / Cursor use. Set `NEXUS_OLLAMA_TOOLS=0` to disable.

## Doctor

```bash
nexus platforms doctor
nexus platforms doctor --fix
```
