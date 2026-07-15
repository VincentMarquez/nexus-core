# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 (P0 + P1 + P2 + P3 hard-apply)_

Model: `grok-4.5` · repos=10 · arXiv=10

---

## Executive summary

- NEXUS already has crash→resume tasks, mine/alive loops, Grok grading, and heartbeat recovery.
- Prior slices landed **durability** (P0), **multi-agent communication + operator board** (P1), and **post-hoc replay/explain** (P2).
- This session’s sources (mission-control costs, value-systems arXiv, EDDI/MisterSmith audit) point at **task-level spend + judge value thresholds** for ops visibility.
- **P3 First apply (this session):** `engine.cost`, journal `score`/`tokens`/`thresholds`, `usage.by_task`, CLI `nexus task cost`.
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
| 2602.04518 | Value systems / preference learning | Explicit judge thresholds + score on events |
| 2412.06333 | Conventions improve cooperation | Fixed event schema (`score`, `tokens`, `thresholds`) |
| 2606.09832 | Agent identity as collaboration interface | `last_agent` / handoff + cost `by_agent` |
| 2506.03053 | Emergent multi-agent behavior eval | Journal as evidence for post-run analysis |
| 2601.00360 | Anti-collusion / trust mechanisms | Trust provenance + review veto |
| 2103.04480 | Distributed stabilizing controllers | Heartbeat dead-man + recovery |

## 10 GitHub repos — portable patterns

| repo | score | pattern | where ported |
|------|-------|---------|--------------|
| builderz-labs/mission-control | 15.0 | Task cost tracker / by-agent rollup | `engine.cost` + `usage.by_task` + `task cost` |
| MattMagg/MisterSmith | 16.0 | Supervised execution + operator surfaces | Event journal + task CLI |
| wshobson/agents | 16.0 | Multi-harness marketplace | Worker/grader selection (grok/ollama) |
| open-multi-agent/open-multi-agent | 13–15 | Plan-replay dashboard | `engine.replay` / `task replay` |
| parijatmukherjee/openclaw-hawkins | 14.0 | Decay-aware shared memory | `SqliteMemory(decay_half_life_days=…)` |
| catlog22/maestro-flow | 14–15 | Adaptive lifecycle + knowledge graph | Ordered steps + journal story |
| labsai/EDDI | 15.0 | Production audit / MCP | Append-only events + explain |
| StreetLamb/rojak | 14.0 | Durable orchestration + HITL | Atomic checkpoints + resume |
| SolaceLabs/solace-agent-mesh | 15.0 | Event-driven multi-agent mesh | Structured journal events |
| IBM/AssetOpsBench | 15.0 | Eval CLI / multi-backend runners | Operator inspect surfaces |

Also: DurableMultiAgentTemplate / DriftQ / Rojak write-then-rename → `nexus.persist`.

## Prioritized engineering backlog

### P0–P2 (landed)

Atomic checkpoints, event journal, decay memory, task CLI, handoffs, veto, journal context, replay, explain, `why`.

### P3 (this session — First apply)

1. **`engine.cost(task_id)`** — token + score rollup from journal.
2. **`score` / `tokens` / `thresholds` on `step_complete`**.
3. **`usage.by_task` / `summarize_records`**.
4. **CLI `nexus task cost`**; explain includes cost brief.
5. **Judge `PASS_THRESHOLD` / `REVISE_THRESHOLD`** explicit on Verdict.

### P4 (next)

1. Optional Prometheus/OTel counters.
2. Dashboard event timeline surface.
3. Preference learning over judge thresholds.
4. Real provider token injection (bridges) instead of estimates.

## First apply slice → evidence (P3)

| Item | Files | Tests |
|------|-------|-------|
| cost + score/tokens/thresholds | `src/nexus/engine.py` | `tests/test_engine.py` |
| by_task rollup | `src/nexus/usage.py` | `tests/test_usage_alive.py` |
| value thresholds | `src/nexus/judge.py` | `tests/test_judge.py` |
| task cost CLI | `src/nexus/cli.py` | `tests/test_task_cli.py` |
| Plans / log | this file, `docs/LATEST_IMPROVE_PLAN.md`, `docs/ALIVE_IMPROVEMENTS.md` | — |

```bash
PYTHONPATH=src python3 -m pytest -q
nexus task cost <id> --state-dir .nexus_state
nexus task explain <id>
```
