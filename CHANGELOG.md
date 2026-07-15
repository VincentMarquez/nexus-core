# Changelog

## 0.7.1 — 2026-07-15

### Added
- **Community response loop**: on human replies / PR commits → run install + pytest + smoke → post results → repeat
- CLI: `nexus github loop <n> [--dry-run] [--force] [--workdir PATH]`
- Actions job `response_loop` (issue comments, PR synchronize, opens)
- Loop marker `<!-- nexus-community-loop sha=… -->` (dedupe per commit); `/skip-loop` opt-out
- README + docs updated for the continuous test/share loop

## 0.7.0 — 2026-07-15

### Added
- **GitHub community one-stop shop**: `nexus github inbox|draft|reply|auto|status`
- **Actions bot**: `.github/workflows/community-bot.yml` auto first-replies on issues/PRs and on `@nexus` / `/triage` comments
- Heuristic drafts (bug / feature / PR checklist) + optional `--llm` via NEXUS bus
- Docs: `docs/GITHUB_COMMUNITY.md`, cookbook 09; README **GitHub community** section
- Bot marker `<!-- nexus-community-bot -->` prevents double-posts
- `nexus github do` keeps the repair-job path; bare `nexus github owner/repo` still works

## 0.6.0 — 2026-07-15

### Added
- **arXiv**: `nexus arxiv search|get`, `nexus research` job (abstracts, brief, report, optional PDF)
- **Procurement intelligence**: `nexus.procurement` engine (scorecard, TCO, scenarios, policy) + expert lenses (Incoterms / Legal / Engineering)
- **CLI**: `nexus procure demo|persona`
- Agent personas: `docs/agents/PROCUREMENT.md`, `docs/agents/RESEARCH_ARXIV.md`
- Cookbooks 07–08

## 0.5.1 — 2026-07-15

### Changed
- Positioning: specialized durable software orchestration (not “does anything”)
- README + COMPARE: Cursor complementarity; LangGraph / CrewAI / AutoGen table
- Elevator pitch: reliability & verifiability + GitHub-native workflows
- Banner + Show HN draft aligned to the same message

## 0.5.0 — 2026-07-15

### Added
- **`nexus do <github-url>`** / **`nexus github`**: clone → detect stack → install → run checks → agent/heuristic fix loop → `NEXUS_REPORT.md`
- **`./run https://github.com/owner/repo`**: zero-config path that starts the stack then runs the job
- Accept bare `owner/repo` slugs; durable job state under `.nexus_state/github_jobs/`
- Command allowlist + workdir jail for safe automated fixes
- Cookbook 06: GitHub URL → fix

## 0.4.2 — 2026-07-15

### Changed
- **Zero-config start**: `./run` creates venv, installs package, starts stack
- **Agents auto-on** when CLI tools are installed (claude / codex / gemini); mock otherwise
- **Auto-pull** a safe Ollama model by default
- Bare `nexus` / `make` → automatic start
- First-contact smoke message so the dashboard shows agent activity

### Added
- Flags: `--no-cli`, `--no-pull`, `--no-smoke` to opt out of automation

## 0.4.1 — 2026-07-15

### Fixed
- MkDocs `--strict` build (Pages deploy): externalize links outside `docs/`
- Stop tracking MkDocs `site/` build artifact; ignore in git
- PyPI distribution name: **`nexus-multi-agent`** (`nexus-core` is taken by an unrelated package)

### Added
- Full cookbooks on the docs site under `docs/cookbook/`
- Clear trusted-publisher setup for PyPI in `docs/PYPI.md`

## 0.4.0 — 2026-07-15

### Added
- Workspace MCP server (`nexus mcp` / `--http`) with project jail
- MkDocs Material docs site + GitHub Pages workflow
- Five cookbooks under `cookbook/`
- PyPI packaging docs + trusted-publish workflow
- `pip`-oriented install path

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
