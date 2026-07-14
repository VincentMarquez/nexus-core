# Changelog

## 0.2.0 — 2026-07-14

### Added
- SQLite FTS memory (`SqliteMemory`, `--sqlite-memory`)
- Circuit breakers on bus client
- Event bus SSE (`/api/events`), task APIs, minimal dashboard
- Human approval path (`--no-auto-approve`, `examples/approve_task.py`)
- Ollama HTTP bridge + engine-over-bus example
- `BusClient`, `AgentPanel.from_bus`
- Smoke evals + scoreboard
- Vendor map + routing table under `data/`
- `make demo` killer crash/resume demo
- Judge vs presence demo
- Docker Compose bus stack
- Community docs: CONTRIBUTING, CoC, SECURITY, GROWTH, SHOW_HN

### Changed
- README rewritten for public product positioning

## 0.1.0 — 2026-07-14

### Added
- Initial architecture kit: cascade, 10-step policy, durable engine, judge, memory, mock agents
