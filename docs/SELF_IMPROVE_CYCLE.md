# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 (hard-apply completion)_

Model: `grok-4.5` · repos=10 · arXiv=10

---

## Executive summary

- NEXUS already has crash→resume tasks, mine/alive loops, Grok grading, and heartbeat recovery; the gap is **operator-grade durability** (atomic checkpoints, audit/replay) and **memory recency**.
- Top mined sources (MisterSmith, Rojak, edict, DriftQ, DurableMultiAgentTemplate, openclaw-hawkins, Swarm) agree: durable state + audit trails beat prompt-only orchestration.
- arXiv signals that matter here: **context engineering** (2508.08322), **multi-agent communication/conventions** (2203.08975, 2412.06333), **multi-LLM tool routing** (2401.07324), not deep RL training loops.
- **First apply slice (landed):** atomic write-then-rename checkpoints + append-only task event journal + optional decay-aware SQLite memory.
- Keep apply scope small; prove with `pytest`; do not vendor upstream trees.

## 10 arXiv papers — what to steal for this codebase

| id | idea | concrete NEXUS change |
|----|------|------------------------|
| 2203.08975 | Communication coordinates agents | Structured step events / handoff messages (journal) |
| 1311.5108 | Multi-level validation methodology | Layered checks: structural gate → judge → tests |
| 2412.06333 | Conventions improve cooperation | Fixed event schema (`event`, `step`, `agent`, `status`) |
| 2508.08322 | Context engineering for multi-file agents | Cascade index + journal summary as shallow context |
| 2512.03278 | Multi-agent claim verification over DBs | Rubric judge with artifact evidence (existing); journal for audit |
| 2602.04518 | Learn value systems / preferences | Prefer scored mine results + human approval gates |
| 2510.13343 | Order of action decisions | Ordered `StepPolicy` pipeline (existing); journal records order |
| 2401.07324 | Small LLMs weak tools → multi-LLM | Grok hard path + Ollama light fallback (existing) |
| 2410.12532 | Information fusion across agents | Trust provenance + multi-agent panel outputs |
| 2103.04480 | Distributed stabilizing controllers | Heartbeat dead-man + recovery (existing resilience) |

## 10 GitHub repos — portable patterns

| repo | score | pattern | where to port |
|------|-------|---------|---------------|
| MattMagg/MisterSmith | 15.0 | Supervised execution + operator surfaces | Event journal + task list events count |
| openai/swarm | 14.2 | Lightweight handoffs | Future: explicit handoff agent field on events |
| Yeachan-Heo/oh-my-claudecode | 14.0 | Productized agents/hooks | Keep CLI hooks small; no vendor |
| cft0808/edict | 14.0 | Full audit trails | `*.events.jsonl` who/when/what |
| StreetLamb/rojak | 14.0 | Durable workflow state / HITL | Atomic checkpoints + waiting_human events |
| wshobson/agents | 13.0 | Multi-harness marketplace | Worker/grader selection (grok/ollama) |
| 07JP27/DurableMultiAgentTemplate | 13.0 | Orchestrator-workers + durable functions | write-then-rename checkpoints |
| jvogan/symphony-claude-lane | 13.0 | Long-horizon harness | Resume + journal across sessions |
| 0xAddict/threadwork | 13.0 | SQLite task board / memory | SQLite memory + task sidecars |
| mkhilari/agentic-code-migration-orchestrator | 13.0 | On-disk workflow + fail-closed gates | Autonomy off + structural pre-gate |

Also used: **parijatmukherjee/openclaw-hawkins** decay-aware memory → optional `decay_half_life_days` on `SqliteMemory`.

## Prioritized engineering backlog

### P0 (this cycle)

1. **Atomic checkpoints** — `nexus.persist.atomic_write_json` used by `DurableEngine.save` and `TrustLog`.
2. **Append-only task event journal** — `tasks/<id>.events.jsonl` with step_start/complete/failed/resume/completed.
3. **Decay-aware memory (opt-in)** — `SqliteMemory(decay_half_life_days=…)` + `ts` column + migration.

### P1 (next)

1. CLI: `nexus task events <id>` pretty-print journal.
2. Swarm-style handoff field on step outputs when panel routes change mid-run.
3. Inject last N journal lines into cascade/context for long resumes (context engineering paper).
4. Alive config already supports `arxiv_count` / `use_limit` = 10 — document in ALIVE.md.

### P2

1. Prometheus/OTel hooks (DriftQ lean observability) behind optional extra.
2. Dashboard surface for event timeline (edict-inspired).
3. Preference/value logging for judge thresholds.

## First apply slice

**Goal:** Prove durability loop with a PR-sized change.

| Item | Files | Tests |
|------|-------|-------|
| `persist.py` helpers | `src/nexus/persist.py` | `tests/test_persist.py` |
| Engine journal + atomic save | `src/nexus/engine.py` | `tests/test_persist.py`, `tests/test_engine.py` |
| Trust atomic flush | `src/nexus/trust.py` | covered via engine |
| Memory decay + ts | `src/nexus/memory_sqlite.py` | `tests/test_memory_sqlite.py` |
| Plans / log | `docs/SELF_IMPROVE_CYCLE.md`, `docs/LATEST_IMPROVE_PLAN.md`, `docs/ALIVE_IMPROVEMENTS.md` | — |

```bash
PYTHONPATH=src python3 -m pytest -q
# or: make test
```
