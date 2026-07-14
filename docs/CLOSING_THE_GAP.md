# Closing the gap (public kit vs full lab)

Your private NEXUS is a full research OS. This repo is the **shareable spine**.

## Now in public (v0.2)

| Area | Module / path |
|------|----------------|
| SQLite FTS memory | `nexus.memory_sqlite.SqliteMemory` |
| Circuit breakers | `nexus.circuits.CircuitBreaker` (used by `BusClient`) |
| Vendor + routing tables | `data/vendor_map.json`, `data/routing_table.json` |
| Bus SSE + task list API | `bridge/server.js` → `/api/events`, `/api/tasks` |
| Minimal dashboard | `bridge/dashboard/index.html` → `/dashboard` |
| Human approve CLI | `examples/approve_task.py` + `--no-auto-approve` |
| Smoke evals | `evals/smoke.py` (complete, kill-resume, autonomy, human gate) |
| Scoreboard | `evals/scoreboard.py` |
| Local LLM + bus engine | `ollama-http.sh`, `run_with_bus.py` |

## Still private / not ported

| Area | Why |
|------|-----|
| Production `server.js` (MCP, real bridges, circuits store) | Host-specific + huge |
| React multi-panel dashboard | Product UI |
| LangGraph SqliteSaver | Optional heavy dep — JSON checkpoints here |
| Dense embeddings + graphify walk | Needs models + private graphs |
| Domain tools (email, clinical, …) | Secrets / privacy |
| systemd watchdog units | Ops, not architecture kit |

## Commands that prove the spine

```bash
pytest -q
python evals/smoke.py
python examples/run_demo_task.py --sqlite-memory
python evals/scoreboard.py

# bus + UI
cd bridge && NEXUS_STATE_DIR=../.nexus_state npm start
# open http://127.0.0.1:3099/dashboard
```
