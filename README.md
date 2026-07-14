# NEXUS Core

[![CI](https://github.com/VincentMarquez/nexus-core/actions/workflows/ci.yml/badge.svg)](https://github.com/VincentMarquez/nexus-core/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**Multi-agent tasks that resume after a crash — with a judge that checks real success criteria, not “the model said OK.”**

![Crash → resume demo](docs/assets/demo.gif)

![Crash → resume flow](docs/assets/demo-flow.svg)

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core && make install && make start
```

**What `make start` / `nexus start` does automatically:**

1. Detects CPU / RAM / GPU (and unified memory)  
2. Starts **Ollama** if installed and picks a safe local model (pulls one if you approve / `-y`)  
3. Starts the **JS event bus** + opens the **dashboard in your browser**  
4. Wires a **local LLM bridge** (or mock if Ollama is missing)  
5. Keeps real **CLI agents off** until you pass `--with-cli` or approve the prompt  

Then:

```bash
make demo          # crash → resume proof
nexus status       # what's running
nexus stop         # tear down
```

> If this saves you a failed overnight agent run, a star helps others find it.

---

## Why it exists

Multi-agent systems fail in the same boring ways:

| Failure mode | NEXUS Core response |
|--------------|---------------------|
| Process dies mid-task | **Durable checkpoints** + resume |
| “Validator” only checks that someone replied | **Rubric judge** on criteria + artifacts |
| Agents thrash context opening random files | **Cascade index** (shallow map first) |
| Background loops burn tokens | **Autonomy default OFF** |
| Cloud-only agent wiring | **Event bus + CLI / Ollama bridges** |

---

## 60-second proof

```bash
make install
make start         # hardware + bus + dashboard + local LLM
make demo          # crash → resume → completed
make demo-judge    # presence trap vs rubric judge
make smoke         # full eval suite
nexus stop
```

### CLI cheatsheet

| Command | Does |
|---------|------|
| `nexus doctor` | Print hardware + tool detection |
| `nexus start` | Full auto stack (prompts for model pull / CLI) |
| `nexus start -y` | Non-interactive defaults |
| `nexus start -y --with-cli` | Also enable installed CLIs (claude/codex/…) |
| `nexus start --model gemma4:e4b` | Force a model |
| `nexus status` | PIDs + bus health |
| `nexus stop` | Stop bus + bridges |
| `nexus demo` | Crash/resume demo |

Dashboard URL after start: **http://127.0.0.1:3099/dashboard**

---

## Architecture

```
Surface (CLI / dashboard)
        │
        ▼
Durable engine ── checkpoint · resume · human gate
        │
   ┌────┼────────────┐
   ▼    ▼            ▼
Agents  Judge      Memory (FTS / RRF)
   │
   ▼
Event bus · CLI bridges · Ollama
   │
   ▼
Cascade index (read the map first)
```

Docs: [ARCHITECTURE](docs/ARCHITECTURE.md) · [PIPELINE](docs/PIPELINE.md) · [MEMORY](docs/MEMORY.md) · [BRIDGES](docs/BRIDGES_AND_BUS.md) · [ROADMAP](docs/ROADMAP.md)

---

## 10-step pipeline

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
| Human approve CLI | ✅ |
| Smoke evals + scoreboard | ✅ |
| Docker Compose bus | ✅ |
| GitHub Actions CI | ✅ |

---

## Install

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
make install    # python venv + editable install
make test
```

**Python 3.10+**. Node 18+ optional (bus/dashboard). Ollama optional (local models).

---

## Repository layout

```
src/nexus/     engine, judge, memory, bus client, circuits
bridge/        event bus, bridges, dashboard
examples/      demos
evals/         smoke suite + scoreboard
data/          vendor map + routing table
docs/          architecture + growth notes
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Design principles stay stable: **presence ≠ success**, **resume over hope**, **autonomy opt-in**.

```bash
make test && make smoke
```

---

## Learn more

| Doc | Purpose |
|-----|---------|
| [docs/COMPARE.md](docs/COMPARE.md) | vs DIY / chat agents / graph runners |
| [docs/VIDEO_SCRIPT.md](docs/VIDEO_SCRIPT.md) | 60s product video + lab story video |
| [docs/SHOW_HN.md](docs/SHOW_HN.md) | Ready-to-post Show HN |
| [docs/SOCIAL_POSTS.md](docs/SOCIAL_POSTS.md) | X / LinkedIn / Reddit copy |
| [docs/LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md) | Launch day checklist |
| [docs/X_RELEASE.md](docs/X_RELEASE.md) | How to post on X (your account) |
| [docs/META_REVIEW.md](docs/META_REVIEW.md) | Launch readiness meta-review |
| [docs/GROWTH.md](docs/GROWTH.md) | Research on how high-star repos grow |

---

## Citation

```text
Vincent Marquez, NEXUS Core, 2026
https://github.com/VincentMarquez/nexus-core
```

## License

MIT — [LICENSE](LICENSE)
