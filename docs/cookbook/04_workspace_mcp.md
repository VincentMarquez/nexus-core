# 04 — Workspace MCP (AI clients)

**Goal:** Expose project-jail tools to Claude Desktop / local clients.

## HTTP demo API (easiest)

```bash
export NEXUS_PROJECT_ROOT="$PWD"
nexus mcp --http --port 8765
```

In another terminal:

```bash
curl -s http://127.0.0.1:8765/health | jq .
curl -s -X POST http://127.0.0.1:8765/tools/call \
  -H 'content-type: application/json' \
  -d '{"name":"list_project_files","arguments":{"path":"docs"}}' | jq .
curl -s -X POST http://127.0.0.1:8765/tools/call \
  -H 'content-type: application/json' \
  -d '{"name":"send_to_workspace","arguments":{"agent":"cookbook","message":"hello from recipe 04"}}' | jq .
curl -s -X POST http://127.0.0.1:8765/tools/call \
  -H 'content-type: application/json' \
  -d '{"name":"read_workspace_chat","arguments":{"count":5}}' | jq .
```

## Claude Desktop (stdio MCP)

Add to Claude Desktop config (paths absolute on **your** machine):

```json
{
  "mcpServers": {
    "nexus-workspace": {
      "command": "nexus",
      "args": ["mcp"],
      "env": {
        "NEXUS_PROJECT_ROOT": "/absolute/path/to/nexus-core"
      }
    }
  }
}
```

Tools: `list_project_files`, `read_project_file`, `write_to_project`,  
`send_to_workspace`, `read_workspace_chat`, `nexus_status`.

See [docs/MCP_SETUP.md](../MCP_SETUP.md) and [docs/CONNECTORS.md](../CONNECTORS.md).
