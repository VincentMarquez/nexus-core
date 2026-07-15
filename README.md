<p align="center">
  <img src="docs/assets/banner.svg" alt="NEXUS Core — multi-agent tasks that resume after a crash" width="100%">
</p>

<p align="center">
  <a href="https://github.com/VincentMarquez/nexus-core/actions/workflows/ci.yml"><img src="https://github.com/VincentMarquez/nexus-core/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://vincentmarquez.github.io/nexus-core/"><img src="https://img.shields.io/badge/docs-GitHub%20Pages-indigo" alt="Docs"></a>
  <a href="https://pypi.org/project/nexus-multi-agent/"><img src="https://img.shields.io/badge/PyPI-nexus--multi--agent-blue" alt="PyPI"></a>
  <a href="https://github.com/VincentMarquez/nexus-core/releases"><img src="https://img.shields.io/github/v/release/VincentMarquez/nexus-core?display_name=tag&sort=semver" alt="Release"></a>
  <a href="https://github.com/VincentMarquez/nexus-core/stargazers"><img src="https://img.shields.io/github/stars/VincentMarquez/nexus-core?style=social" alt="Stars"></a>
</p>

<p align="center">
  <b>Multi-agent tasks that resume after a crash</b> — with a judge that checks real success criteria, not “the model said OK.”
</p>

<p align="center">
  <a href="https://vincentmarquez.github.io/nexus-core/"><b>Docs</b></a> ·
  <a href="https://vincentmarquez.github.io/nexus-core/getting-started/"><b>Get started</b></a> ·
  <a href="https://vincentmarquez.github.io/nexus-core/cookbooks/"><b>Cookbooks</b></a> ·
  <a href="#architecture"><b>Architecture</b></a> ·
  <a href="https://github.com/VincentMarquez/nexus-core/releases"><b>Releases</b></a>
</p>

---

## Quick start (zero config)

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
./run
```

That’s it. **`./run` installs the package if needed and starts everything automatically.**

### Paste a GitHub repo — NEXUS does the rest

```bash
./run https://github.com/owner/repo
./run owner/repo --goal "make the tests pass and fix whatever is broken"
# same after install:
nexus do https://github.com/owner/repo
nexus do owner/repo -g "run checks and repair failures"
```

| Step | What NEXUS does |
|------|-----------------|
| Start | Brings up bus + agents if needed |
| Clone | Shallow clone into `.nexus_workspaces/` |
| Detect | Python / Node / Go / Rust (install + test commands) |
| Install | pip / npm / yarn / pnpm / go / cargo / make (allowlisted) |
| Check | pytest, npm test, go test, cargo test, … |
| Fix | Up to 3 rounds of agent/heuristic patches + re-run |
| Report | `NEXUS_REPORT.md` in the workdir (resumable job state) |

| What `./run` alone does | Detail |
|-------------------------|--------|
| Python venv | Created at `.venv` if missing |
| Package install | `pip install -e .` |
| Hardware detect | CPU / RAM / GPU / tools |
| Ollama | Starts if installed; **auto-pulls** a safe small model |
| Event bus + dashboard | Opens in your browser |
| Agents | **Uses real CLIs when installed** (claude / codex / gemini); mocks otherwise |
| First contact | Short smoke message so you see an agent reply |

Same stack start: `make` · `make start` · `nexus` · `nexus start`

```bash
# after PyPI publish:
pip install nexus-multi-agent && nexus start

# opt-outs:
./run --no-cli
./run --no-pull
nexus do owner/repo --heuristic-only   # no LLM, rules only
nexus do owner/repo --no-start         # use existing stack
```

Then:

```bash
make demo          # crash → resume proof
nexus status
nexus stop
```

> If this saves you a failed overnight agent run, a star helps others find it.

---

## Crash → resume (the point)

<p align="center">
  <img src="docs/assets/demo-flow.svg" alt="Crash → resume flow: steps, kill -9, state on disk, resume completed" width="100%">
</p>

<p align="center">
  <img src="docs/assets/demo.gif" alt="Crash → resume demo animation" width="100%">
</p>

```bash
make install && make start && make demo && make demo-judge && make smoke
```

---

## Why it exists

| Failure mode | NEXUS Core response |
|--------------|---------------------|
| Process dies mid-task | **Durable checkpoints** + resume |
| “Validator” only checks that someone replied | **Rubric judge** on criteria + artifacts |
| Agents thrash context opening random files | **Cascade index** (shallow map first) |
| Background loops burn tokens | **Autonomy default OFF** |
| Cloud-only agent wiring | **Event bus + CLI / Ollama bridges** |

---

## CLI cheatsheet

| Command | Does |
|---------|------|
| `./run` | **Preferred** — install + auto start + agents |
| `./run https://github.com/…` | Start stack **and** clone/install/fix that repo |
| `nexus do owner/repo` | GitHub → workdir → checks → fix loop |
| `nexus` / `nexus start` | Stack only (after install) |
| `nexus doctor` | Hardware + tool detection |
| `nexus start --no-cli` | Stack without real CLI agents |
| `nexus status` / `nexus stop` | Status / tear down |
| `nexus demo` | Crash → resume demo |
| `nexus mcp` / `nexus mcp --http` | Workspace MCP |

Dashboard URL is printed after start (auto port if 3099 is busy).

---

## Connect AI apps & phone (MCP)

| Doc | Contents |
|-----|----------|
| [docs/CONNECTORS.md](docs/CONNECTORS.md) | Remote MCP · machine MCP · phone · bus |
| [docs/MCP_SETUP.md](docs/MCP_SETUP.md) | ChatGPT / Claude / Grok recipes |
| [connectors/](connectors/) | JSON/env **templates** (placeholders only) |

```text
ChatGPT / Grok  ──HTTPS MCP──►  tunnel  ──►  workspace tools
Claude Desktop  ──stdio MCP──►  nexus mcp ──►  files (project jail)
Phone (optional)──HTTPS MCP──►  tunnel  ──►  personal memory
Ollama / CLIs   ──event bus──►  nexus start
GLM-5.2 colibrì ──event bus──►  colibri-glm bridge
```

**GLM-5.2:** [docs/GLM52.md](docs/GLM52.md) · [examples/glm52_nexus.md](examples/glm52_nexus.md)

---

## Architecture

<p align="center">
  <img src="docs/assets/arch-overview.svg" alt="NEXUS Core system overview" width="100%">
</p>

<p align="center">
  <img src="docs/assets/arch-cli-judge-resume.svg" alt="CLI multi-agent + crash resume + rubric judge" width="100%">
</p>

<details>
<summary><b>More diagrams</b> (multi-agent panel, MCP mesh, GLM-5.2, 10-step pipeline)</summary>

<br>

![Multi-agent research panel](docs/assets/arch-multi-agent.svg)

![MCP connector mesh](docs/assets/arch-mcp-mesh.svg)

![GLM-5.2 / colibrì with NEXUS](docs/assets/arch-glm-pipeline.svg)

![10-step adversarial pipeline](docs/assets/arch-pipeline-10.svg)

</details>

Full catalog: [docs/FIGURES.md](docs/FIGURES.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [PIPELINE](docs/PIPELINE.md) · [BRIDGES](docs/BRIDGES_AND_BUS.md)

### 10-step pipeline

| # | Step | Role |
|---|------|------|
| 1 | goal | objective + success criteria |
| 2 | plan | approach |
| 3 | challenge | adversarial review |
| 4 | implement | artifacts |
| 5 | test | evidence |
| 6 | review | verdict |
| 7 | log | snapshot |
| 8 | meta_review | panel review |
| 9 | **approval** | **human gate** |
| 10 | deliver | handoff |

---

## Cookbooks

1. [Crash → resume](cookbook/01_crash_resume.md)
2. [Judge vs presence](cookbook/02_judge_vs_presence.md)
3. [Local LLM (Ollama)](cookbook/03_local_llm_ollama.md)
4. [Workspace MCP](cookbook/04_workspace_mcp.md)
5. [GLM-5.2 / colibrì](cookbook/05_glm52_colibri.md)

Docs site: **https://vincentmarquez.github.io/nexus-core/**

---

## Features

| | |
|--|--|
| Durable engine + resume | ✅ |
| Rubric-style judge | ✅ |
| Mock agents (zero setup) | ✅ |
| SQLite FTS memory | ✅ |
| Circuit breakers | ✅ |
| Event bus + SSE + task API | ✅ |
| Minimal dashboard | ✅ |
| Ollama + CLI bridges | ✅ |
| Workspace MCP (`nexus mcp`) | ✅ |
| **GitHub URL → clone / run / fix** (`nexus do`) | ✅ |
| Human approve CLI | ✅ |
| Smoke evals + scoreboard | ✅ |
| Docker Compose bus | ✅ |
| GitHub Actions CI + Pages | ✅ |

---

## Install

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
make install    # python venv + editable install
make test
```

**Python 3.10+**. Node 18+ optional (bus/dashboard). Ollama optional (local models).

```
src/nexus/     engine, judge, memory, bus client, MCP, circuits
bridge/        event bus, bridges, dashboard
examples/      demos
evals/         smoke suite + scoreboard
cookbook/      copy-paste recipes
docs/          architecture + launch notes
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Design principles: **presence ≠ success**, **resume over hope**, **autonomy opt-in**.

```bash
make test && make smoke
```

---

## Learn more

| Doc | Purpose |
|-----|---------|
| [docs/COMPARE.md](docs/COMPARE.md) | vs DIY / chat agents / graph runners |
| [docs/SHOW_HN.md](docs/SHOW_HN.md) | Ready-to-post Show HN |
| [docs/SOCIAL_POSTS.md](docs/SOCIAL_POSTS.md) | X / LinkedIn / Reddit copy |
| [docs/LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md) | Launch day checklist |
| [docs/GROWTH.md](docs/GROWTH.md) | How high-star repos grow |
| [docs/PYPI.md](docs/PYPI.md) | Publish `nexus-multi-agent` |

## Citation

```text
Vincent Marquez, NEXUS Core, 2026
https://github.com/VincentMarquez/nexus-core
```

## License

MIT — [LICENSE](LICENSE)
