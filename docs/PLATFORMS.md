# Multi-platform agents + local LLM tools

NEXUS is the **hub**. Grok CLI, Cursor, Claude, Codex, Gemini, and **local LLMs** are **spokes**. Compatible clients can register the same host tools and hand off work through the same workspace. Actual tool use depends on client support and whether the selected model reliably emits valid tool calls.

## Optional recorded setup: Spark / GB10

This section records one operator deployment. Model IDs, server commands, load times, and memory use are examples, not `nexus-core` requirements.

| Priority | Grok model id | Backend | When to use |
|----------|---------------|---------|-------------|
| **Primary** | **`gemma4`** | **vLLM NVFP4** `http://127.0.0.1:8000/v1` · recorded served name `gemma4-nvfp4-interactive2` | Interactive Grok + registered workspace MCP tools in the recorded setup |
| Secondary | `nexus-local` | Ollama `gemma4:26b` `:11434` | Light turns / bus agent when NVFP4 is stopped |
| Speed option | (Ollama) `e2b-fast` | ~100 tok/s Q4 | Fast drafts only — not the NVFP4 26B quality path |

**Start primary local (NVFP4):**

```bash
export NEXUS_LOCAL_MODEL_ROOT=/path/to/your/local-model-runtime
cd "$NEXUS_LOCAL_MODEL_ROOT"
# Start its OpenAI-compatible server using that runtime's documented command.
```

In the recorded setup, the server cold-loaded in approximately 2–3 minutes and used approximately 80–90 GiB of unified memory. Measure your deployment before co-loading another large model.

**Small-model tool calling:** install the cheat sheet so Gemma actually *uses* Grok’s tools:

```bash
cp -a skillpacks/gemma-local-tools ~/.grok/skills/gemma-local-agent
```

See [LOCAL_LLM_TOOL_CALLING.md](LOCAL_LLM_TOOL_CALLING.md) and the [gemma-local-tools skill pack](https://github.com/VincentMarquez/nexus-core/tree/main/skillpacks/gemma-local-tools).

## Goal

| Want | How |
|------|-----|
| Run **NVFP4 Gemma4** inside Grok + workspace MCP | `[model.gemma4]` → `:8000` (already default); keep `mcp_servers.nexus-workspace` enabled |
| Run a **light Ollama** model in Grok | `nexus platforms connect` registers `[model.nexus-local]` + same MCP |
| Auto-connect Grok / Cursor / Claude | `nexus platforms connect` |
| Agents from other products join the same job | Distinct `agent` ids + `send_to_workspace` / bus bridges |
| Local model uses registered tools | MCP host (Grok/Cursor) executes tools; a compatible model chooses them and emits valid requests |

## One-time setup

```bash
cd /path/to/your/project
pip install -e ".[dev]"   # or make install
nexus platforms status
nexus platforms connect --start
```

What `connect` does:

1. **Grok CLI** — `mcp_servers.nexus-workspace` in `~/.grok/config.toml` (or `grok mcp add`)
2. **Grok local model (Ollama secondary)** — optional `[model.nexus-local]` → `http://127.0.0.1:11434/v1`
3. **Does not overwrite** an existing `[model.gemma4]` **NVFP4 / vLLM** entry — keep that as primary interactive local
4. **Cursor** — `.cursor/mcp.json` in the project
5. **Claude** — `connectors/examples/claude-desktop.nexus.json` (+ desktop config if found)
6. **`--start`** — `nexus start -y` so Ollama bridge agent `local` is on the event bus (optional; not required for NVFP4-in-Grok)

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
Grok CLI + model gemma4 (NVFP4 vLLM :8000) ──MCP──┐
Grok CLI + model nexus-local (Ollama) ─────────────┤
Cursor ──MCP───────────────────────────────────────┼──► NEXUS hub
Claude ──MCP / CLI bridge──────────────────────────┤     · Workspace MCP tools
Codex / Gemini ──CLI bridge────────────────────────┤     · event bus (optional)
Ollama bus agent `local` (ollama_tools loop) ──────┘     · durable jobs
         ◄──── workspace chat handoff ──────────────────┘
```

Agent ids (use consistently):

| Platform | `agent` id |
|----------|------------|
| Grok CLI (cloud or **NVFP4 gemma4**) | `grok_cli` |
| Cursor | `cursor` |
| Claude | `claude` |
| Codex | `gpt` |
| Gemini | `gemini` |
| Ollama bus / light local | `local` |

## Grok CLI + local LLM

**Split of labor (recommended on Spark):**

| | **Local NVFP4 `gemma4`** | Grok (cloud) | Ollama `nexus-local` / bus |
|--|--------------------------|--------------|----------------------------|
| Role | **Default interactive + workspace MCP** | Hard grading / when NVFP down | Light bus turns, drafts |
| Backend | vLLM `nvfp4-interactive2` `:8000` | xAI | Ollama `:11434` |
| Memory | Approximately 80–90 GiB in the recorded run | Network-backed | Deployment-specific |

```bash
# Primary path — NVFP4 Gemma4 + workspace tools
export NEXUS_LOCAL_MODEL_ROOT=/path/to/your/local-model-runtime
cd "$NEXUS_LOCAL_MODEL_ROOT"
# Start the server using that runtime's documented command.
# Then configure your Grok client with a supported local model identifier.
grok
# /model gemma4   if needed
# Prompt: talk to workspace via send_to_workspace / read_workspace_chat

# Secondary — Ollama only when NVFP is stopped
# ./manage.sh nvfp4-interactive2 stop
nexus platforms connect --model gemma4:26b
ollama serve
# /model nexus-local
```

**MCP tools attach to the Grok session**, not to a single vendor model. A selected local model can use those registered tools when the client supports tool calls and the model emits valid requests. `platforms connect` does not replace an existing `[model.gemma4]` block.

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
