# Runtime paths & how to read a cycle

## Logs

| Path | Content |
|------|---------|
| `/tmp/nexus-alive-watch.log` | Alive process stdout (START/END, summary dump) |
| `/tmp/nexus-alive-once.pid` | PID while REAL/DRY once is running |
| `/tmp/workspace-chat-log.jsonl` | Lab chat (includes LOCAL implement summary) |

## After REAL — read these in order

1. **`docs/LATEST_IMPLEMENT_SUMMARY.md`** — executive review (% hit rates, tokens, approvals)
2. **`docs/LATEST_IDEA_PORTFOLIO.md`** — which arXiv/GitHub/novel ideas were selected
3. **`docs/LATEST_META_REVIEW.md`** — cycle meta verdict
4. **`.nexus_state/alive_state.json`** — full step machine dump
5. **`.nexus_state/LAST_IMPLEMENT_SUMMARY.json`** — metrics for tooling

## MCP

```text
http://127.0.0.1:8765/mcp
  tools: canonical_pipeline, github_mine, run_task, …
```

Lab agents TOOL_CALL the **same names** (product MCP first).

## Ports (lab)

| Port | Service |
|------|---------|
| 5173 | UI |
| 3099 | Event bus |
| 8765 | Product MCP |
| 11434 | Ollama (local) |

## Commands

```bash
# product CLI
cd ~/nexus-core
.venv/bin/nexus alive once --dry-run
.venv/bin/nexus alive once              # REAL
.venv/bin/nexus alive status

# lab chat (via bus)
# "run self-improve" | "run self-improve real" | "run review pipeline"
```
