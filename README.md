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
  <b>Many LLMs talk and reason together on hard problems.</b><br>
  Claude · GPT/Codex · Gemini · Grok · Ollama · GLM — on one bus, challenging each other,<br>
  surviving crashes, finishing only when a <b>rubric judge</b> sees real evidence.
</p>

<p align="center">
  <a href="https://vincentmarquez.github.io/nexus-core/"><b>Docs</b></a> ·
  <a href="#llms-that-reason-together"><b>Multi-LLM panel</b></a> ·
  <a href="https://vincentmarquez.github.io/nexus-core/getting-started/"><b>Get started</b></a> ·
  <a href="https://vincentmarquez.github.io/nexus-core/COMPARE/"><b>vs other tools</b></a> ·
  <a href="https://vincentmarquez.github.io/nexus-core/cookbooks/"><b>Cookbooks</b></a>
</p>

<p align="center">
  <img src="docs/assets/arch-llms-reason-together.svg" alt="Multiple LLMs talk and reason together through the NEXUS bus" width="100%">
</p>

---

## Elevator pitch

> **One model is a smart intern. A panel that argues, checks, and resumes is a team.**  
> **nexus-core** wires heterogeneous LLMs so they **plan, challenge, implement, test, and meta-review together** on hard work — software repos, research, procurement — with **durable checkpoints** and a **rubric judge** that ignores “looks good to me.”

Three pillars:

1. **Collective reasoning** — different models in different roles; adversary + meta-review, not a single chat  
2. **Reliability & verifiability** — resume after crash; success = criteria + artifacts  
3. **Practical jobs** — `nexus do`, `nexus research`, `nexus procure`  

| Domain | Entry | What you get |
|--------|-------|----------------|
| **Software** | `nexus do owner/repo` | Multi-agent clone → install → test → fix |
| **Research** | `nexus research "…"` | arXiv + multi-model brief |
| **Procurement** | `nexus procure demo` | Engine math + expert lenses (+ LLM extract) |

---

## LLMs that reason together

Hard problems need **more than one voice**. NEXUS is built so models **talk through a shared bus**, keep a durable task state, and only ship when evidence holds.

<p align="center">
  <img src="docs/assets/arch-multi-agent.svg" alt="Multi-agent research panel — heterogeneous model vendors" width="100%">
</p>

| Role in the panel | Typical model | What it does on hard problems |
|-------------------|---------------|-------------------------------|
| **Planner** | Claude / GPT | Frames approach, risks, steps |
| **Adversary** | Grok / local / second vendor | Attacks the plan before code |
| **Implementer** | Codex / Claude / GLM | Writes patches and artifacts |
| **Tester** | Local / fast model | Runs checks, returns evidence |
| **Reviewer** | Cross-vendor if possible | Verdict on quality |
| **Meta-review** | **Several agents at once** | Panel vote — not one monologue |
| **Judge** | Separate rubric path | Scores **your** success criteria |

```text
  Claude ──┐                    ┌── challenge plan
  Codex  ──┼──►  NEXUS bus  ────┼── implement + test
  Gemini ──┤     + durable   ───┼── meta-review (panel)
  Grok   ──┤     checkpoints ───┼── rubric judge
  Ollama ──┤                    └── human gate (optional)
  GLM    ──┘
```

**Why this matters for hard problems**

- **Disagreement is a feature** — the adversary step and meta-review force pushback  
- **Vendor diversity** — one model’s blind spot is another’s strength  
- **Shared memory + cascade** — they don’t thrash the same files blindly  
- **Crash-safe** — a 2-hour multi-agent debate doesn’t die with one process  
- **Observable** — dashboard + SSE so you see who said what  

Wire whatever you already pay for / run locally:

```bash
./run                          # auto-detects claude, codex, gemini, ollama
nexus start -y                 # same
# map roles explicitly when running the engine over the bus:
python examples/run_with_bus.py --map planner=claude,implementer=gpt,tester=local,adversary=local
```

---

## What makes it different

| Capability | What it does | Why it matters |
|------------|--------------|----------------|
| **Multi-LLM panel** | Heterogeneous models on one bus, role-mapped | Hard problems get debate, not monologue |
| **Meta-review** | Multiple agents vote / cross-check | Catches single-model overconfidence |
| **Adversarial pipeline** | Goal → plan → **challenge** → implement → test → review | Pushback *before* shipping |
| **Durable execution** | Checkpoints after each step; resume after `kill -9` | Long multi-agent runs survive crashes |
| **Rubric judge** | Scores **your** criteria + artifacts | “Model said OK” is not success |
| **Hybrid / LLM-optional** | Heuristic-only **or** any mix of CLIs/local | Cost control; degrades gracefully |
| **GitHub / arXiv / procurement** | Real job entrypoints | Panel applied to concrete work |
| **Event bus + dashboard** | Live multi-agent status | Not a black box |
| **Workspace MCP** | Jail for desktop/phone AI clients | External models join the same workspace |

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
  <img src="docs/assets/arch-llms-reason-together.svg" alt="LLMs reason together" width="100%">
</p>

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
