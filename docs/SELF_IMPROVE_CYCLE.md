# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 (P0 + P1 hard-apply)_

Model: `grok-4.5` · repos=10 · arXiv=10

---

## Executive summary

- NEXUS already has crash→resume tasks, mine/alive loops, Grok grading, and heartbeat recovery; the gap was **operator-grade durability** (atomic checkpoints, audit/replay), **multi-agent communication** (handoffs / veto), and **context on resume**.
- Top mined sources (MisterSmith, Rojak, edict, DriftQ, DurableMultiAgentTemplate, openclaw-hawkins, Swarm) agree: durable state + audit trails beat prompt-only orchestration.
- arXiv signals that matter here: **context engineering** (2508.08322), **multi-agent communication/conventions** (2203.08975, 2412.06333), **multi-LLM tool routing** (2401.07324), not deep RL training loops.
- **P0 First apply slice (landed):** atomic write-then-rename checkpoints + append-only task event journal + optional decay-aware SQLite memory.
- **P1 slice (landed this session):** `nexus task list|show|events`, swarm-style handoff events, journal context injection on resume, edict-style review veto, tail-limited event reads.
- Keep apply scope small; prove with `pytest`; do not vendor upstream trees.

## Reasoning plan (how to run a cycle)

1. **Mine** — fetch ~10 repos, Grok-grade idea/skill, write `IMPROVE_OURS.md` (patterns only, no stars/follows).
2. **arXiv** — research 10 papers; skip ids already in `docs/ARXIV_LEDGER.csv`.
3. **Reason** — write this file + `LATEST_IMPROVE_PLAN.md` with a PR-sized **First apply slice**.
4. **Hard apply** — implement slice with tests; keep `make test` / `pytest` green.
5. **Publish** — optional allowlisted push after checks (never force-push; never commit secrets).

```bash
PYTHONPATH=src NEXUS_GROK_MODEL=grok-4.5 python3 scripts/full_self_improve_cycle.py
# or manual hard-worker session against LATEST_IMPROVE_PLAN.md
```

## 10 arXiv papers — what to steal for this codebase

| id | idea | concrete NEXUS change |
|----|------|------------------------|
| 2203.08975 | Communication coordinates agents | Structured step events / handoff messages (journal) |
| 1311.5108 | Multi-level validation methodology | Layered checks: structural gate → judge → tests |
| 2412.06333 | Conventions improve cooperation | Fixed event schema (`event`, `step`, `agent`, `status`) |
| 2508.08322 | Context engineering for multi-file agents | Cascade index + journal summary as shallow context |
| 2512.03278 | Multi-agent claim verification over DBs | Rubric judge with artifact evidence; journal for audit |
| 2602.04518 | Learn value systems / preferences | Prefer scored mine results + human approval gates |
| 2510.13343 | Order of action decisions | Ordered `StepPolicy` pipeline; journal records order |
| 2401.07324 | Small LLMs weak tools → multi-LLM | Grok hard path + Ollama light fallback |
| 2410.12532 | Information fusion across agents | Trust provenance + multi-agent panel outputs |
| 2103.04480 | Distributed stabilizing controllers | Heartbeat dead-man + recovery |

## 10 GitHub repos — portable patterns

| repo | score | pattern | where ported |
|------|-------|---------|--------------|
| wshobson/agents | 16.0 | Multi-harness marketplace | Worker/grader selection (grok/ollama) |
| MattMagg/MisterSmith | 15.0 | Supervised execution + operator surfaces | Event journal + `nexus task *` |
| parijatmukherjee/openclaw-hawkins | 15.0 | Decay-aware shared memory | `SqliteMemory(decay_half_life_days=…)` |
| Yeachan-Heo/oh-my-claudecode | 15.0 | Productized agents/hooks | Keep CLI hooks small; no vendor |
| muhamadjawdatsalemalakoum/nocturne | 15.0 | Durable checkpoints / wait-out limits | Atomic checkpoints + resume |
| StreetLamb/rojak | 14.0 | Durable workflow state / HITL | Atomic checkpoints + waiting_human events |
| openai/swarm | 13.0 | Lightweight handoffs | `handoff` journal events + `from_agent`/`to_agent` |
| cft0808/edict | 13.0 | Full audit trails + review veto | `*.events.jsonl` + review fail-closed |
| jvogan/symphony-claude-lane | 13.0 | Long-horizon harness | Resume + journal across sessions |
| 0xAddict/threadwork | 13.0 | SQLite task board / memory | SQLite memory + task sidecars |

Also: DurableMultiAgentTemplate / DriftQ write-then-rename checkpoints → `nexus.persist`.

## Prioritized engineering backlog

### P0 (landed)

1. **Atomic checkpoints** — `nexus.persist.atomic_write_json` used by `DurableEngine.save` and `TrustLog`.
2. **Append-only task event journal** — `tasks/<id>.events.jsonl` with step_start/complete/failed/resume/completed.
3. **Decay-aware memory (opt-in)** — `SqliteMemory(decay_half_life_days=…)` + `ts` column + migration.

### P1 (landed this session)

1. CLI: `nexus task list|show|events <id>` pretty-print journal.
2. Swarm-style handoff field when panel routes change mid-run.
3. Inject last N journal lines into step prompts on resume (context engineering).
4. Edict-style review veto (fail-closed on reject/veto/…).
5. `events(limit=)` returns the **tail** (operator timeline).

### P2 (next)

1. Prometheus/OTel hooks (DriftQ lean observability) behind optional extra.
2. Dashboard surface for event timeline (edict-inspired).
3. Preference/value logging for judge thresholds.
4. Cookbook page for crash-resume + task journal inspect.

## First apply slice → evidence

**Goal:** Prove durability + communication loop with PR-sized changes.

| Item | Files | Tests |
|------|-------|-------|
| `persist.py` helpers | `src/nexus/persist.py` | `tests/test_persist.py` |
| Engine journal + handoff/veto/context | `src/nexus/engine.py` | `tests/test_engine.py`, `tests/test_persist.py` |
| Trust atomic flush | `src/nexus/trust.py` | covered via engine |
| Memory decay + ts | `src/nexus/memory_sqlite.py` | `tests/test_memory_sqlite.py` |
| Task CLI | `src/nexus/cli.py` | `tests/test_task_cli.py` |
| Plans / log | `docs/SELF_IMPROVE_CYCLE.md`, `docs/LATEST_IMPROVE_PLAN.md`, `docs/ALIVE_IMPROVEMENTS.md` | — |

```bash
PYTHONPATH=src python3 -m pytest -q
nexus task list --state-dir .nexus_state
nexus task events <id> --limit 20
```
