# NEXUS Core

**Multi-agent research workflows that survive crashes, judge real criteria, and stay under control.**

NEXUS Core is a dependency-light architecture for running **adversarial, multi-step agent tasks** with:

1. **Cascade navigation** — agents read a shallow system index before deep files  
2. **10-step pipeline** — plan → challenge → implement → test → review → human gate → deliver  
3. **Durable engine** — checkpoint after each step; **resume** after kill or restart  
4. **Rubric judge** — score **success criteria + evidence**, not “did an agent reply?”  
5. **Memory spine** — namespaced retrieval (in-memory or SQLite FTS)  
6. **Event bus + bridges** — wire CLI agents and **local LLMs** (e.g. Ollama)  
7. **Autonomy default OFF** — reactive by default; no unattended token burn  

**Author:** [Vincent Marquez](https://github.com/VincentMarquez)  
**License:** MIT  

---

## Why it exists

Multi-agent systems often fail the same ways:

- validators accept empty or offline replies as success  
- a process death loses half a task  
- agents thrash context opening random files  
- memory is just chat scrollback  
- background loops burn tokens unattended  

NEXUS Core turns the answers into **small, testable modules** you can run, extend, or embed.

---

## Install

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python evals/smoke.py
```

Requires **Python 3.10+**. Demos run with **mock agents** (no cloud accounts required). Optional: **Node 18+** for the event bus / dashboard, **Ollama** for a local model.

---

## Quick start

### Offline engine (mocks)

```bash
python examples/run_demo_task.py
# simulate a crash after 3 steps, then resume:
python examples/run_demo_task.py --task-id demo-resume --kill-after 3
python examples/run_demo_task.py --resume demo-resume
```

### SQLite memory + scoreboard

```bash
python examples/run_demo_task.py --task-id mem-demo --sqlite-memory
python evals/scoreboard.py
```

### Human approval gate

```bash
python examples/run_demo_task.py --task-id need-you --no-auto-approve
python examples/approve_task.py need-you --approve
```

### Event bus + dashboard

```bash
cd bridge
NEXUS_STATE_DIR=../.nexus_state npm start
# open http://127.0.0.1:3099/dashboard
```

### Local LLM (Ollama)

```bash
# ollama serve && ollama pull gemma2
cd bridge && npm start                                          # terminal 1
./bridges/ollama-http.sh local gemma2                           # terminal 2
python examples/call_bus.py --agent local --prompt "Hello"      # terminal 3
python examples/run_with_bus.py --task-id ollama-demo            # engine over bus
```

Full guide: [examples/ollama_local.md](examples/ollama_local.md)

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Surface (CLI / dashboard / your UI)                     │
│  Task { objective, success_criteria, namespace }         │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│  Durable engine  (nexus.engine)                          │
│  checkpoint · resume · human interrupt                   │
└───────┬─────────────────────┬────────────────────────────┘
        │                     │
┌───────▼────────┐   ┌────────▼─────────┐   ┌──────────────┐
│ Multi-agent    │   │ Rubric judge     │   │ Memory spine │
│ panel + health │   │ criteria+evidence│   │ FTS / RRF    │
│ + fallbacks    │   │ cross-vendor     │   │ namespaces   │
└───────┬────────┘   └──────────────────┘   └──────────────┘
        │
┌───────▼──────────────────────────────────────────────────┐
│  Event bus (bridge/)  ·  CLI / Ollama workers            │
│  file-drop protocol · SSE events · task list API         │
└──────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────┐
│  Cascade index — shallow map first, deep files later     │
└──────────────────────────────────────────────────────────┘
```

More: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/PIPELINE.md](docs/PIPELINE.md) · [docs/MEMORY.md](docs/MEMORY.md) · [docs/BRIDGES_AND_BUS.md](docs/BRIDGES_AND_BUS.md)

---

## 10-step pipeline

| # | Name | Role | Human gate? |
|---|------|------|-------------|
| 1 | goal | define objective + success criteria | |
| 2 | plan | propose approach | |
| 3 | challenge | adversarial review of the plan | |
| 4 | implement | produce artifacts | |
| 5 | test | run checks / collect evidence | |
| 6 | review | reviewer verdict | |
| 7 | log | state snapshot | |
| 8 | meta_review | multi-agent review | |
| 9 | approval | human approve / reject | **yes** |
| 10 | deliver | finalize handoff | |

---

## Design principles

| Principle | Meaning |
|-----------|---------|
| **Stable execute contract** | The engine wraps step runners; it doesn’t reimplement step bodies |
| **Presence ≠ success** | Structural pre-gate first; the **judge** scores real criteria |
| **Prefer cross-vendor judges** | Judge seat prefers a different vendor than the implementer |
| **Fail open on memory** | Retrieval outage must not freeze the pipeline |
| **Autonomy is opt-in** | Background task generators default **off** |
| **Namespaced memory** | Isolation via `proj/<id>` |
| **Cascade first** | Read the shallow index before deep paths |
| **Circuit breakers** | Repeated agent failures open the circuit and skip until cooldown |

---

## Repository layout

```
src/nexus/           # engine, judge, memory, bus client, circuits
bridge/              # event bus, agent bridges, dashboard
  server.js
  bridges/           # mock, CLI, Ollama HTTP
  dashboard/
data/                # vendor_map + routing_table
docs/                # architecture guides
examples/            # demos
evals/               # smoke suite + scoreboard
tests/
```

---

## Features

| Area | Status |
|------|--------|
| Durable 10-step engine + resume | ✅ |
| Mock agents (zero setup) | ✅ |
| Rubric-style judge | ✅ |
| Cascade index | ✅ |
| In-memory + SQLite FTS memory | ✅ |
| Event bus + file-drop bridges | ✅ |
| Ollama local model bridge | ✅ |
| Engine over bus (`run_with_bus.py`) | ✅ |
| Circuit breakers | ✅ |
| SSE events + task API | ✅ |
| Minimal dashboard | ✅ |
| Human approval CLI | ✅ |
| Smoke evals + scoreboard | ✅ |
| Vendor / routing tables | ✅ |

Roadmap ideas (contributions welcome): denser retrieval backends, richer MCP tool surface, larger dashboards, optional LangGraph checkpointers. See [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Configuration tips

- **Bus port:** `NEXUS_BUS_PORT` (default `3099`)  
- **Bridge files:** `NEXUS_BRIDGE_DIR` (default OS temp `nexus-bridges`)  
- **Task state for dashboard:** `NEXUS_STATE_DIR` (point at your `.nexus_state`)  
- **Agent list:** `NEXUS_AGENTS=claude,gpt,local`  
- **Ollama:** `OLLAMA_HOST`, `OLLAMA_MODEL`  

Keep credentials in your environment or local CLI logins—not in the repo.

---

## Contributing

Issues and PRs are welcome. Prefer small, tested changes that preserve the design principles above.

```bash
pytest -q
python evals/smoke.py
```

---

## Citation

```text
Vincent Marquez, NEXUS Core — multi-agent research workflow architecture, 2026
https://github.com/VincentMarquez/nexus-core
```

---

## License

MIT — see [LICENSE](LICENSE)
