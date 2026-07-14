# NEXUS Core

**A clean, public architecture kit for multi-agent research workflows.**

NEXUS Core is a **from-scratch, dependency-light reference implementation** of ideas developed in a larger personal research system. It is **not** a dump of that private codebase.

It demonstrates:

1. **Cascade navigation** — read a shallow index before deep files (attention / D* style)
2. **10-step adversarial task pipeline** — plan → challenge → implement → test → review → human gate → deliver
3. **Durable engine** — checkpointed steps that **resume** after interruption
4. **Cross-vendor rubric judge** — score against real success criteria (not mere “did something reply?”)
5. **Memory spine** — hybrid retrieval (lexical + optional dense + graph hop) with **namespaces**
6. **Autonomy default OFF** — reactive by default; no unattended token burn

Author of this public kit: **Vincent Marquez**  
Original private research system: personal lab (not published here)

---

## Why this exists

Large multi-agent systems rot into:

- fragile validators that fail good work  
- lost work when a process dies mid-task  
- blind file navigation that wastes context  
- memory that is “chat history” only  

NEXUS Core packages the **architectural answers** as small, testable modules + docs you can read in one sitting.

---

## Install

```bash
cd nexus-core
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python evals/smoke.py          # durability + human gate + autonomy
python examples/run_demo_task.py
python evals/scoreboard.py
```

Python **3.10+**. No cloud API keys required for the demo (mock agents).

### Closing the gap (v0.2)

Beyond the original spine, this public kit now also includes:

- **SQLite FTS memory** (`--sqlite-memory`)
- **Circuit breakers** on bus calls
- **SSE events** + **task list** on the bus
- **Minimal dashboard** at `http://127.0.0.1:3099/dashboard`
- **Human approve** path (`--no-auto-approve` + `examples/approve_task.py`)
- **Smoke evals + scoreboard**
- **Vendor / routing tables** under `data/`

What’s still only in a private lab (and stays out of git): production MCP bus, full React UI, domain tools, personal data. See [docs/CLOSING_THE_GAP.md](docs/CLOSING_THE_GAP.md).

---

## Quick demo

```bash
python examples/run_demo_task.py
# kill -9 mid-run, then:
python examples/run_demo_task.py --resume demo-task-1
```

You should see the task **resume from the last completed step**.

---

## Architecture (one picture)

```
┌──────────────────────────────────────────────────────────┐
│  Surface (your UI / CLI)                                 │
│  promote chat → Task{objective, success_criteria, ns}    │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│  Durable engine  (nexus.engine)                          │
│  checkpoint after each step · resume · kill-safe         │
│  wraps StepRunner  (does NOT reimplement step bodies)    │
└───────┬─────────────────────┬────────────────────────────┘
        │                     │
┌───────▼────────┐   ┌────────▼─────────┐   ┌──────────────┐
│ Multi-agent    │   │ Rubric judge     │   │ Memory spine │
│ panel + health │   │ cross-"vendor"   │   │ RRF hybrid   │
│ + fallbacks    │   │ vs criteria      │   │ + namespaces │
└────────────────┘   └──────────────────┘   └──────────────┘
        │
┌───────▼──────────────────────────────────────────────────┐
│  Cascade index  (nexus.cascade)                          │
│  D* shallow map first → branch → file  (never navigate   │
│  blind into deep context)                                │
└──────────────────────────────────────────────────────────┘
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## 10-step pipeline (default policy)

| # | Name | Role (generic) | Human gate? |
|---|------|----------------|-------------|
| 1 | goal | operator defines objective + success criteria | |
| 2 | plan | planner proposes approach | |
| 3 | challenge | adversary attacks the plan | optional |
| 4 | implement | implementer produces artifacts | |
| 5 | test | tester validates artifacts | |
| 6 | review | reviewer verdict | |
| 7 | log | logger snapshots state | |
| 8 | meta_review | multi-agent review | |
| 9 | approval | **human** approve/reject | **yes** |
| 10 | deliver | finalize report / handoff | |

Policy table: [docs/PIPELINE.md](docs/PIPELINE.md)

---

## Design laws (non-negotiable)

| Law | Meaning |
|-----|---------|
| **Execute contract stable** | Step *bodies* are pluggable; the engine wraps them, doesn’t fork their semantics |
| **Presence ≠ success** | Structural checks are a pre-gate; the **judge** scores real criteria + evidence |
| **Cross-vendor prefer** | Judge prefers a different “vendor” than the implementer |
| **Fail open on memory** | Retrieval outage must not freeze the pipeline |
| **Autonomy opt-in** | Background goal loops stay **OFF** unless explicitly enabled |
| **Namespaces** | Memory is partitioned (`proj/<id>`); sensitive tenants stay isolated |
| **Cascade first** | Agents read the shallow index before deep files |

---

## Package layout

```
src/nexus/          # Python architecture (engine, judge, memory, …)
bridge/             # HOWTO stubs: event bus + file-drop bridges (no keys)
  server.js
  bridges/mock-bridge.sh
  bridges/cli-bridge.sh
docs/
  BRIDGES_AND_BUS.md   # how to wire real CLIs without committing secrets
examples/
tests/
```

### Multi-agent bus + CLI bridges (no secrets)

The durable Python engine works offline with **mock agents**.  
To learn how a **real** multi-CLI lab wires agents:

1. Read **[docs/BRIDGES_AND_BUS.md](docs/BRIDGES_AND_BUS.md)**  
2. Run the stubs:

```bash
cd bridge && npm start          # terminal 1 — bus on :3099
./bridges/mock-bridge.sh claude # terminal 2 — fake agent
python ../examples/call_bus.py  # terminal 3 — smoke call
```

Real CLIs: use `./bridges/cli-bridge.sh claude claude --print` **on your machine**  
(auth via your local CLI login / env — **never commit API keys**).

**Local LLM (Ollama):** [examples/ollama_local.md](examples/ollama_local.md)

```bash
# terminal 1–2: bus + ollama bridge
cd bridge && npm start
./bridges/ollama-http.sh local gemma2

# optional: engine uses the bus (falls back to mocks if a slot is offline)
python examples/run_with_bus.py --task-id ollama-demo
```

Python bus helper: `nexus.bus_client.BusClient` · panel: `AgentPanel.from_bus(...)`.

---

## What is *not* in this repo

- Private medical / family research data  
- Email / Gmail automation  
- Live API keys, MCP bridges, host paths  
- Production dashboards, systemd units, personal chat logs  

Those belong in a **private** lab. This kit is the **shareable architecture**.

---

## License

MIT — [LICENSE](LICENSE)

---

## Citation

```text
Vincent Marquez, NEXUS Core — multi-agent research workflow architecture (public kit), 2026
https://github.com/VincentMarquez/nexus-core
```
