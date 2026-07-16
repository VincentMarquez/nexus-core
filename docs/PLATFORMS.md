# Multi-platform agents + local LLM tool parity

NEXUS is the **hub**. Grok CLI (now), Cursor, Claude, Codex, Gemini, and **local LLMs** are **spokes**. Every spoke should use the **same tools** and hand off work through the same workspace.

## Local LLMs on this machine (Spark / GB10)

| Priority | Grok model id | Backend | When to use |
|----------|---------------|---------|-------------|
| **Primary** | **`gemma4`** | **vLLM NVFP4** `http://127.0.0.1:8000/v1` · served name `gemma4-nvfp4-interactive2` | Interactive Grok + **full workspace MCP** (default in `~/.grok/config.toml`) |
| Secondary | `nexus-local` | Ollama `gemma4:26b` `:11434` | Light turns / bus agent when NVFP4 is stopped |
| Speed option | (Ollama) `e2b-fast` | ~100 tok/s Q4 | Fast drafts only — not the NVFP4 26B quality path |

**Start primary local (NVFP4):**

```bash
cd ~/gemma4-vllm && ./manage.sh nvfp4-interactive2 up   # ~2–3 min cold load; ~80–90 GiB unified mem
# Grok TUI: default model is already gemma4 — MCP tools attach to the session
# Ask: "Use send_to_workspace / read_workspace_chat to talk to the Nexus workspace"
```

Do **not** load heavy Ollama models at the same time as NVFP4 (same unified memory). Unload with `keep_alive: 0` or stop the vLLM container when switching.

**Small-model tool calling:** install the cheat sheet so Gemma actually *uses* Grok’s tools:

```bash
cp -a skillpacks/gemma-local-tools ~/.grok/skills/gemma-local-agent
```

See [LOCAL_LLM_TOOL_CALLING.md](LOCAL_LLM_TOOL_CALLING.md) and [`skillpacks/gemma-local-tools/`](../skillpacks/gemma-local-tools/).

## Goal

| Want | How |
|------|-----|
| Run **NVFP4 Gemma4** inside Grok + workspace MCP | `[model.gemma4]` → `:8000` (already default); keep `mcp_servers.nexus-workspace` enabled |
| Run a **light Ollama** model in Grok | `nexus platforms connect` registers `[model.nexus-local]` + same MCP |
| Auto-connect Grok / Cursor / Claude | `nexus platforms connect` |
| Agents from other products join the same job | Distinct `agent` ids + `send_to_workspace` / bus bridges |
| Local model uses **all** tools | MCP host (Grok/Cursor) executes tools; model only chooses them — **works for `gemma4` (NVFP4) and `nexus-local`** |

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
| Memory | ~80–90 GiB unified | network | small; don't dual-load with NVFP |

```bash
# Primary path — NVFP4 Gemma4 + workspace tools
cd ~/gemma4-vllm && ./manage.sh nvfp4-interactive2 up
# ~/.grok/config.toml already: default = "gemma4", mcp_servers.nexus-workspace enabled
grok
# /model gemma4   if needed
# Prompt: talk to workspace via send_to_workspace / read_workspace_chat

# Secondary — Ollama only when NVFP is stopped
# ./manage.sh nvfp4-interactive2 stop
nexus platforms connect --model gemma4:26b
ollama serve
# /model nexus-local
```

**MCP tools attach to the Grok session**, not to a single vendor model — so **`gemma4` (NVFP4) gets the same Nexus workspace tools as cloud Grok.** `platforms connect` must not replace your NVFP4 `[model.gemma4]` block.

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
