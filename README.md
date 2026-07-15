<p align="center">
  <img src="docs/assets/banner.svg" alt="NEXUS Core — durable multi-agent software tasks" width="100%">
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
  <b>Durable multi-agent execution for real software work.</b><br>
  Take a GitHub repo, run agents across crashes, and only finish when a <b>rubric judge</b> confirms success — not when the model says “done.”
</p>

<p align="center">
  <a href="https://vincentmarquez.github.io/nexus-core/"><b>Docs</b></a> ·
  <a href="https://vincentmarquez.github.io/nexus-core/getting-started/"><b>Get started</b></a> ·
  <a href="https://vincentmarquez.github.io/nexus-core/COMPARE/"><b>vs other tools</b></a> ·
  <a href="https://vincentmarquez.github.io/nexus-core/cookbooks/"><b>Cookbooks</b></a> ·
  <a href="#what-this-is-not">What this is not</a>
</p>

---

## Elevator pitch

> **nexus-core** is a durable multi-agent system for real software tasks. It can take a GitHub repo, work on it across process crashes, and only deliver when a rubric judge confirms it *actually* succeeded — not just when the model claims it did.

Two pillars:

1. **Reliability & verifiability** — checkpoints + resume, rubric judge, adversarial pipeline  
2. **Practical engineering workflows** — `nexus do owner/repo`, local LLMs/CLIs, observable bus  

It is **not** “an AI that does anything.” It is a **specialized orchestration engine** for long-running, checkable jobs across three domains:

| Domain | Entry | What you get |
|--------|-------|----------------|
| **Software** | `nexus do owner/repo` | Clone → install → test → fix loop |
| **Research** | `nexus research "…"` / `nexus arxiv` | arXiv search, abstracts, brief, report |
| **Procurement** | `nexus procure demo` | Deterministic scorecard, TCO, expert lenses |

---

## What makes it different

| Capability | What it does | Why it matters |
|------------|--------------|----------------|
| **Durable execution** | Checkpoints after each step; resume after `kill -9` | Overnight agent runs usually die and lose everything |
| **Rubric judge** | Scores **your** success criteria + artifacts | Most stacks treat “model replied” as success |
| **Adversarial pipeline** | Goal → plan → **challenge** → implement → test → review → meta-review | Built-in pushback before shipping |
| **Hybrid / LLM-optional** | Heuristic-only mode **or** Ollama / Claude / Codex / Gemini | Cost control + runs when models are down |
| **GitHub-native jobs** | `nexus do owner/repo --goal "fix failing tests"` | URL → clone → install → check → fix loop |
| **arXiv research** | `nexus research "topic"` / `nexus arxiv search` | Public API → abstracts → brief (no key) |
| **Procurement agents** | Engine + Incoterms/Legal/Engineering lenses | **Numbers from code, not the model** |
| **Event bus + dashboard** | Live multi-agent status | Not a black box |
| **Workspace MCP** | Project-jail tools for desktop/phone AI clients | Safe external control of the workspace |

---

## Quick start

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
./run
```

Creates a venv, installs the package, starts bus + dashboard, wires **Ollama and installed CLIs automatically** (mocks if missing).

### Paste a GitHub repo — autonomous repair loop

```bash
./run https://github.com/owner/repo
./run owner/repo --goal "make the tests pass and fix whatever is broken"
nexus do owner/repo -g "run checks and repair failures"
```

| Step | Action |
|------|--------|
| Start | Bring up bus + agents if needed |
| Clone | Shallow clone → `.nexus_workspaces/` |
| Detect | Python / Node / Go / Rust |
| Install | Allowlisted pip / npm / yarn / pnpm / go / cargo / make |
| Check | pytest, npm test, go test, cargo test, … |
| Fix | Up to 3 agent/heuristic rounds + re-run |
| Report | `NEXUS_REPORT.md` (job state is resumable) |

```bash
# stack only
./run --no-cli
# rules only (no LLM)
nexus do owner/repo --heuristic-only --no-start
# proof of durability
make demo && make demo-judge

# domains
nexus research "multi agent orchestration" --heuristic-only
nexus arxiv get 1706.03762
nexus procure demo
```

> If this saves a failed overnight agent run, a star helps others find it.

---

## Domains

### Software (GitHub)

See [Quick start](#quick-start) and [cookbook 06](cookbook/06_github_do.md).

### Research (arXiv)

```bash
nexus arxiv search "retrieval augmented generation"
nexus research "durable multi-agent systems" --max 8
# optional PDFs:  nexus research "…" --pdf
```

Persona: [docs/agents/RESEARCH_ARXIV.md](docs/agents/RESEARCH_ARXIV.md) · cookbook [08](cookbook/08_arxiv_research.md)

### Procurement

Deterministic **scorecard / TCO / policy / expert panel**. The LLM extracts quotes; the engine owns every number.

```bash
nexus procure demo          # synthetic 3-supplier report
nexus procure persona       # system prompt for bus / Claude / local LLM
```

```python
from nexus.procurement import Supplier, CostLine, ProcurementAnalysis, ExpertPanel
```

Persona: [docs/agents/PROCUREMENT.md](docs/agents/PROCUREMENT.md) · cookbook [07](cookbook/07_procurement.md)

Optional charts: `pip install matplotlib` (or `pip install "nexus-multi-agent[charts]"` when published).

---

## Crash → resume (the point)

<p align="center">
  <img src="docs/assets/demo-flow.svg" alt="Crash → resume flow" width="100%">
</p>

<p align="center">
  <img src="docs/assets/demo.gif" alt="Crash → resume demo" width="100%">
</p>

```bash
make install && make start && make demo && make demo-judge && make smoke
```

---

## What this is not

| Not this | Actually this |
|----------|----------------|
| A Cursor / VS Code replacement | Complementary: Cursor helps **you** edit; NEXUS **runs** long jobs on repos |
| A general “do anything” AGI | Specialized in **software tasks** with evidence |
| An o1-style reasoning model | An **orchestrator** that structures models (or heuristics) |
| LangGraph / CrewAI / AutoGen clone | Same multi-agent space, different bet: **durability + rubric success** over chat graphs |

**Cursor** is excellent daily coding assistance.  
**nexus-core** is for *agents that must finish real work on repositories reliably over time*.

Use both.

---

## Why it exists

| Failure mode | NEXUS response |
|--------------|----------------|
| Process dies mid-task | **Durable checkpoints** + resume |
| “Done” = model said OK | **Rubric judge** on criteria + artifacts |
| Agents thrash random files | **Cascade index** (shallow map first) |
| Background loops burn tokens | **Autonomy default OFF** |
| Cloud-only glue | **Bus + CLI / Ollama bridges** |

Deeper comparison (Cursor, LangGraph, CrewAI, AutoGen): **[docs/COMPARE.md](docs/COMPARE.md)**

---

## CLI cheatsheet

| Command | Does |
|---------|------|
| `./run` | Install + auto start + agents |
| `./run https://github.com/…` | Start **and** GitHub job |
| `nexus do owner/repo` | Clone → install → check → fix |
| `nexus research "…"` | arXiv job → brief + report |
| `nexus arxiv search` / `get` | arXiv API helpers |
| `nexus procure demo` | Procurement engine + experts |
| `nexus start` / `stop` / `status` | Stack control |
| `nexus doctor` | Hardware + tools |
| `nexus demo` | Crash → resume proof |
| `nexus mcp` / `--http` | Workspace MCP |

---

## Connect AI apps & phone (MCP)

| Doc | Contents |
|-----|----------|
| [docs/CONNECTORS.md](docs/CONNECTORS.md) | Remote / machine / phone MCP |
| [docs/MCP_SETUP.md](docs/MCP_SETUP.md) | ChatGPT / Claude / Grok recipes |
| [connectors/](connectors/) | Templates only (no secrets) |

```text
ChatGPT / Grok  ──HTTPS MCP──►  tunnel  ──►  workspace tools
Claude Desktop  ──stdio MCP──►  nexus mcp ──►  files (project jail)
Ollama / CLIs   ──event bus──►  nexus start
```

---

## Architecture

<p align="center">
  <img src="docs/assets/arch-overview.svg" alt="System overview" width="100%">
</p>

<p align="center">
  <img src="docs/assets/arch-cli-judge-resume.svg" alt="CLI + resume + judge" width="100%">
</p>

<details>
<summary><b>More diagrams</b></summary>

<br>

![Multi-agent panel](docs/assets/arch-multi-agent.svg)
![MCP mesh](docs/assets/arch-mcp-mesh.svg)
![GLM-5.2](docs/assets/arch-glm-pipeline.svg)
![10-step pipeline](docs/assets/arch-pipeline-10.svg)

</details>

[FIGURES](docs/FIGURES.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [PIPELINE](docs/PIPELINE.md) · [BRIDGES](docs/BRIDGES_AND_BUS.md)

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
6. [GitHub URL → fix](cookbook/06_github_do.md)  
7. [Procurement agents](cookbook/07_procurement.md)  
8. [arXiv research](cookbook/08_arxiv_research.md)  

Docs: **https://vincentmarquez.github.io/nexus-core/**

---

## Features

| | |
|--|--|
| Durable engine + resume | ✅ |
| Rubric-style judge | ✅ |
| Adversarial 10-step pipeline | ✅ |
| GitHub `nexus do` repair jobs | ✅ |
| arXiv search / research jobs | ✅ |
| Procurement engine + expert panel | ✅ |
| Heuristic-only (no LLM) mode | ✅ |
| Mock agents (zero setup) | ✅ |
| SQLite FTS memory | ✅ |
| Circuit breakers | ✅ |
| Event bus + SSE + dashboard | ✅ |
| Ollama + CLI bridges | ✅ |
| Workspace MCP | ✅ |
| Human approve gate | ✅ |
| Smoke evals + scoreboard | ✅ |
| GitHub Actions CI + Pages | ✅ |

---

## Install

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
make install && make test
# after PyPI trusted publish:
# pip install nexus-multi-agent && nexus start
```

**Python 3.10+**. Node 18+ for bus/dashboard. Ollama / CLIs optional.

```
src/nexus/     engine, judge, github jobs, MCP, bus client
bridge/        event bus, bridges, dashboard
cookbook/      copy-paste recipes
docs/          architecture + positioning
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Design laws: **presence ≠ success**, **resume over hope**, **autonomy opt-in**.

```bash
make test && make smoke
```

---

## Learn more

| Doc | Purpose |
|-----|---------|
| [docs/COMPARE.md](docs/COMPARE.md) | vs Cursor / LangGraph / CrewAI / AutoGen |
| [docs/SHOW_HN.md](docs/SHOW_HN.md) | Show HN draft |
| [docs/GROWTH.md](docs/GROWTH.md) | Distribution research |
| [docs/PYPI.md](docs/PYPI.md) | Publish `nexus-multi-agent` |

## Citation

```text
Vincent Marquez, NEXUS Core, 2026
https://github.com/VincentMarquez/nexus-core
```

## License

MIT — [LICENSE](LICENSE)
