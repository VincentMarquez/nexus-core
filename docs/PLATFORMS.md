# Multi-platform agents + local LLM tools

NEXUS is the **hub**. Grok CLI, Cursor, Claude, Codex, Gemini, and
**local LLMs** are **spokes**. Compatible clients can connect to the same
Workspace MCP server and request tools from its enabled catalog. The host,
configuration, and selected model determine which tools are available and
whether calls succeed.

## Local model configuration

NEXUS does not require a particular model, accelerator, runtime, or server
address. Start an OpenAI-compatible or Ollama runtime using its own
documentation, then configure the client with a supported model identifier and
base URL. Keep machine-specific endpoints in user-level configuration or
environment variables rather than tracked project files.

**Small-model tool calling:** install the prompt guide to help a compatible
local model discover and request enabled host tools. The skill pack does not
grant tools or permissions:

```bash
mkdir -p ~/.grok/skills
cp -a skillpacks/gemma-local-tools ~/.grok/skills/gemma-local-tools
```

See [LOCAL_LLM_TOOL_CALLING.md](LOCAL_LLM_TOOL_CALLING.md) and the
[gemma-local-tools skill pack](https://github.com/VincentMarquez/nexus-core/tree/main/skillpacks/gemma-local-tools).

## Goal

| Want | How |
|------|-----|
| Use a local OpenAI-compatible model in Grok | Configure a model identifier and base URL supported by the installed client; configure Workspace MCP separately |
| Run an Ollama model in Grok | `nexus platforms connect --model YOUR_OLLAMA_MODEL` registers `[model.nexus-local]` and reuses the configured `nexus-workspace` MCP entry |
| Auto-connect Grok / Cursor / Claude | `nexus platforms connect` |
| Connect Codex / Gemini | Start their optional CLI bridges with the NEXUS runtime |
| Agents from other products join the same job | Use distinct `agent` ids with `send_to_workspace` and the bus bridges |
| Let a local model request registered tools | Use a compatible MCP host or the optional Ollama tool loop; the model must emit valid tool requests |

## One-time setup

```bash
export NEXUS_PROJECT_ROOT=/path/to/your/nexus-core-checkout
cd "$NEXUS_PROJECT_ROOT"
make install
source .venv/bin/activate
nexus platforms status
nexus platforms doctor
nexus platforms connect --path "$NEXUS_PROJECT_ROOT"
```

`status` and `doctor` are read-only unless `doctor --fix` is used.
`doctor --fix` reruns `connect --force` and may rewrite client configuration.
Run `connect` only after reviewing which client configuration it will write.
`--force` overwrites existing MCP entries, and `--start` also launches the
source-checkout runtime.

What `connect` does:

1. **Grok CLI** — `mcp_servers.nexus-workspace` in `~/.grok/config.toml`
2. **Grok local model** — optionally registers `[model.nexus-local]` for a local Ollama runtime
3. **Other Grok models** — leaves unrelated `[model.*]` entries unchanged
4. **Cursor** — `.cursor/mcp.json` in the project
5. **Claude** — `connectors/examples/claude-desktop.nexus.json` (+ desktop config if found)
6. **`--start`** — runs `nexus start -y` so optional bridge agents join the event bus

Codex and Gemini participate through their CLI bridges. `platforms connect`
does not install MCP configuration for those clients.

## Shared tools (Workspace MCP)

| Tool | Purpose |
|------|---------|
| `list_project_files` | Tree under configured project root |
| `read_project_file` / `write_to_project` | File IO |
| `send_to_workspace` / `read_workspace_chat` | Multi-agent handoff log |
| `nexus_status` | Root + runtime |
| `run_project_checks` | Runs configured install, test, and smoke checks; may execute repository-controlled code |
| `bus_status` | Which agents (local/claude/gpt/…) are online |
| `github_community_status` | `gh` + target repo |
| `list_platforms` | Detected clients on this machine |

## Agent flow

```text
Grok CLI + configured cloud/local model ──MCP─────┐
Cursor ──MCP───────────────────────────────────────┤
Claude ──MCP / CLI bridge──────────────────────────┼──► NEXUS hub
Codex / Gemini ──CLI bridge────────────────────────┤     · Workspace MCP tools
Ollama bus agent `local` (optional tool loop) ─────┘     · event bus (optional)
         ◄──── workspace chat handoff ──────────────────┘     · durable jobs
```

Agent ids (use consistently):

| Platform | `agent` id |
|----------|------------|
| Grok CLI (cloud or local model) | `grok_cli` |
| Cursor | `cursor` |
| Claude | `claude` |
| Codex | `gpt` |
| Gemini | `gemini` |
| Ollama bus / light local | `local` |

## Grok CLI + local LLM

Start the selected local runtime separately, using its documented server
command. Then configure Grok with a supported local model identifier and base
URL. Workspace MCP configuration is independent of the selected model.

```bash
# Connect Workspace MCP.
nexus platforms connect --no-local-model

# Start the local runtime separately, then configure its model identifier and
# base URL in the client without committing machine-specific values.
grok
# Select the configured local model if needed.
# Prompt: talk to workspace via send_to_workspace / read_workspace_chat

# Optional Ollama integration.
nexus platforms connect --model YOUR_OLLAMA_MODEL
ollama serve
# In Grok, select nexus-local if needed.
```

**MCP tools attach to the Grok session**, not to a single vendor model. A
selected local model can request registered tools when the client supports tool
calls, the tool is enabled, and the model emits a valid request.

## Cursor / others later

Same MCP server command:

```json
{
  "mcpServers": {
    "nexus-workspace": {
      "command": "/absolute/path/to/nexus-core/.venv/bin/python",
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

- Direct file tools reject paths outside `NEXUS_PROJECT_ROOT`; this is a
  guardrail, not a complete capability sandbox.
- The catalog also contains write and operational tools. Privilege labels are
  descriptive and do not enforce authorization at call time.
- `connect` is opt-in, but it writes client configuration and may place
  absolute machine-local paths in `.cursor/mcp.json` and other client
  configuration. Inspect the diff before committing or sharing it.
- Keep private network addresses, hostnames, tunnel URLs, and credentials out
  of tracked configuration and documentation.
- Client permission prompts vary by host and configuration; do not assume that
  every tool call receives an interactive approval.
- Bus CLI bridges remain separate from MCP, and both can run together with the
  permissions of the host account.

See [security and trust boundaries](SECURITY.md).

## Local LLM on the bus (tool loop)

`nexus start` sets `NEXUS_OLLAMA_TOOLS=1`. The Ollama bridge runs
`bridge/bridges/ollama_tools.py`, which teaches the model:

```text
TOOL_CALL {"name": "run_project_checks", "arguments": {}}
```

Tools execute via `nexus.mcp_server.call_tool`, the same handler implementations
used by Grok CLI and Cursor. Host profiles and permissions may expose different
tool catalogs. Set `NEXUS_OLLAMA_TOOLS=0` to disable.

## Doctor

```bash
nexus platforms doctor
nexus platforms doctor --fix
```
