# Changelog

## 0.3.4 — 2026-07-14

### Added
- Hero figure: CLI multi-agent + crash resume + rubric judge (README)

## 0.3.3 — 2026-07-14

### Added
- Research-style architecture figures (multi-agent, MCP mesh, GLM-5.2, pipeline)
- docs/FIGURES.md catalog

## 0.3.2 — 2026-07-14

### Added
- **GLM-5.2 / colibrì integration**: `docs/GLM52.md`, `examples/glm52_nexus.md`
- Bus bridge `bridge/bridges/colibri-glm.sh` (OpenAI-compatible `coli serve` + optional CLI)

## 0.3.1 — 2026-07-14

### Added
- **Connectors docs**: how ChatGPT / Claude / Grok / phone MCP attach (no personal URLs)
- `docs/CONNECTORS.md`, `docs/MCP_SETUP.md`
- `connectors/examples/*` JSON and env templates + architecture SVG

## 0.3.0 — 2026-07-14

### Added
- **`nexus` CLI**: `start` / `stop` / `status` / `doctor` / `demo`
- Hardware auto-detect (CPU, RAM, GPU/unified, Ollama, CLI tools)
- Auto Ollama serve + model pick/pull (safe defaults; heavy models avoided on low RAM)
- Auto start JS bus + open dashboard in browser
- Auto local LLM bridge; CLI bridges only with `--with-cli` or interactive approve
- `make start` / `make stop` / `make doctor`

## 0.2.1 — 2026-07-14

### Added
- Launch pack: VIDEO_SCRIPT, COMPARE, SOCIAL_POSTS, LAUNCH_CHECKLIST
- Soft star CTA in README
- Positioning docs for distribution

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
