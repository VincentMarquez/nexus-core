# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 (P0 + P1 + P2 hard-apply)_

Model: `grok-4.5` · repos=10 · arXiv=10

---

## Executive summary

- NEXUS already has crash→resume tasks, mine/alive loops, Grok grading, and heartbeat recovery; earlier gaps were **operator-grade durability**, **multi-agent communication**, and **context on resume** (P0/P1 landed).
- This cycle’s mined sources (mission-control, solace-agent-mesh, maestro-flow, EDDI, open-multi-agent, nocturne, MisterSmith, …) and arXiv (CEMA causal explanations, multi-agent orchestration for incident response, context engineering) point at **post-hoc decision observability**: replay timelines + causal “why” without re-running agents.
- **P0 (landed):** atomic write-then-rename checkpoints + append-only task event journal + optional decay-aware SQLite memory.
- **P1 (landed):** `nexus task list|show|events`, swarm handoffs, journal context on resume, edict review veto.
- **P2 First apply (this session):** `engine.replay` / `engine.explain`, `why` on `step_complete`, CLI `nexus task replay|explain`.
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
| 2508.08322 | Context engineering for multi-file agents | Cascade + journal summary as shallow context |
| 2302.10809 | Causal explanations for sequential MAS decisions | `engine.explain` + `why` on step_complete |
| 2511.15755 | Multi-agent orchestration for incident response | Deterministic audit timeline (`replay`) |
| 2401.07324 | Small LLMs weak tools → multi-LLM | Grok hard path + Ollama light fallback |
| 2412.06333 | Conventions improve cooperation | Fixed event schema (`event`, `step`, `agent`, `why`) |
| 2606.09832 | Agent identity as collaboration interface | `last_agent` / handoff from/to fields |
| 2506.03053 | Emergent multi-agent behavior eval | Journal as evidence for post-run analysis |
| 2601.00360 | Anti-collusion / trust mechanisms | Trust provenance + review veto |
| 2103.04480 | Distributed stabilizing controllers | Heartbeat dead-man + recovery |

## 10 GitHub repos — portable patterns

| repo | score | pattern | where ported |
|------|-------|---------|--------------|
| wshobson/agents | 16.0 | Multi-harness marketplace | Worker/grader selection (grok/ollama) |
| builderz-labs/mission-control | 15.0 | Fleet ops / inspect surfaces | `nexus task *` board + explain |
| MattMagg/MisterSmith | 15.0 | Supervised execution + operator surfaces | Event journal + task CLI |
| open-multi-agent/open-multi-agent | 13–15 | Plan-replay dashboard | `engine.replay` / `task replay` |
| muhamadjawdatsalemalakoum/nocturne | 15.0 | Durable checkpoints | Atomic checkpoints + resume |
| parijatmukherjee/openclaw-hawkins | 15.0 | Decay-aware shared memory | `SqliteMemory(decay_half_life_days=…)` |
| catlog22/maestro-flow | 15.0 | Adaptive lifecycle + knowledge graph | Ordered steps + journal story |
| labsai/EDDI | 15.0 | Production audit / MCP | Append-only events + explain |
| openai/swarm | 13.0 | Lightweight handoffs | `handoff` journal events |
| cft0808/edict | 13.0 | Full audit + review veto | `*.events.jsonl` + veto fail-closed |

Also: DurableMultiAgentTemplate / DriftQ / Rojak write-then-rename → `nexus.persist`.

## Prioritized engineering backlog

### P0 (landed)

1. **Atomic checkpoints** — `nexus.persist.atomic_write_json` used by `DurableEngine.save` and `TrustLog`.
2. **Append-only task event journal** — `tasks/<id>.events.jsonl`.
3. **Decay-aware memory (opt-in)** — `SqliteMemory(decay_half_life_days=…)`.

### P1 (landed)

1. CLI: `nexus task list|show|events`.
2. Swarm-style handoff events.
3. Journal snippet on resume (context engineering).
4. Edict-style review veto.
5. `events(limit=)` returns the **tail**.

### P2 (this session — First apply)

1. **`engine.replay(task_id)`** — normalized timeline from journal (no re-run).
2. **`engine.explain(task_id)`** — causal decision chain (steps, handoffs, vetoes, story).
3. **`why` on `step_complete`** — short judge rationale for audit.
4. CLI: `nexus task replay|explain` (+ `--json`).

### P3 (next)

1. Optional Prometheus/OTel counters (DriftQ lean observability).
2. Dashboard event timeline surface (edict / mission-control board).
3. Preference/value logging for judge thresholds (arXiv value systems).
4. Task-level usage/cost rollup (mission-control costs).

## First apply slice → evidence (P2)

| Item | Files | Tests |
|------|-------|-------|
| replay + explain + why | `src/nexus/engine.py` | `tests/test_engine.py` |
| task replay/explain CLI | `src/nexus/cli.py` | `tests/test_task_cli.py` |
| Plans / log | `docs/SELF_IMPROVE_CYCLE.md`, `docs/LATEST_IMPROVE_PLAN.md`, `docs/ALIVE_IMPROVEMENTS.md` | — |
| Cookbook inspect | `cookbook/01_crash_resume.md` | manual |

```bash
PYTHONPATH=src python3 -m pytest -q
nexus task list --state-dir .nexus_state
nexus task replay <id> --limit 20
nexus task explain <id>
nexus task explain <id> --json
```
