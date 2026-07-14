# Feature map (v0.2)

Quick index of capabilities landed in this repository.

| Area | Module / path |
|------|----------------|
| SQLite FTS memory | `nexus.memory_sqlite.SqliteMemory` |
| Circuit breakers | `nexus.circuits.CircuitBreaker` (used by `BusClient`) |
| Vendor + routing tables | `data/vendor_map.json`, `data/routing_table.json` |
| Bus SSE + task list API | `bridge/server.js` → `/api/events`, `/api/tasks` |
| Minimal dashboard | `bridge/dashboard/index.html` → `/dashboard` |
| Human approve CLI | `examples/approve_task.py` + `--no-auto-approve` |
| Smoke evals | `evals/smoke.py` |
| Scoreboard | `evals/scoreboard.py` |
| Local LLM + bus engine | `ollama-http.sh`, `run_with_bus.py` |

## Prove it

```bash
pytest -q
python evals/smoke.py
python examples/run_demo_task.py --sqlite-memory
python evals/scoreboard.py

cd bridge && NEXUS_STATE_DIR=../.nexus_state npm start
# open http://127.0.0.1:3099/dashboard
```

Further ideas: [ROADMAP.md](ROADMAP.md)
