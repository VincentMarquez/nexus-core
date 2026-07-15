# Latest improve plan (from full self-improve cycle)

Model: Grok 4.5 · 10 repos graded · 10 arXiv papers · hard apply

## Status

| Slice | Status |
|-------|--------|
| **P0 First apply** — atomic checkpoints + event journal + opt-in memory decay | **Landed** |
| **P1** — operator CLI + handoff events + journal context + review veto | **Landed** |
| **P2** — replay timeline + causal explain + `why` on step_complete | **Landed** |
| **P3 First apply** — task cost rollup + judge value thresholds | **Landed** (this session) |
| **P4** — OTel / dashboard timeline | Backlog |

## First apply slice (this session — P3)

**Goal:** Operator-grade spend + value-system audit per task (no re-run).

Patterns: mission-control **task-costs** / cost-tracker, arXiv **value systems** (2602.04518), CEMA score trail, usage ledger `meta.task_id` rollup.

1. **`DurableEngine.cost(task_id)`** — journal-based token + score rollup (`by_agent`, `by_step`, thresholds).
2. **`score` / `tokens` / `thresholds` on `step_complete`** — value-system cutoffs + estimated spend.
3. **`usage.by_task(task_id)`** — optional global ledger rollup when `meta.task_id` is set.
4. **CLI** — `nexus task cost` (+ `--json`); explain/replay show score/tokens.
5. **Judge** — `PASS_THRESHOLD` / `REVISE_THRESHOLD` + `decision_thresholds()` on Verdict.

## Prior slices (already in tree)

### P0

1. Atomic durable checkpoints (`os.replace` write-then-rename).
2. Append-only task event journal (`tasks/<id>.events.jsonl`).
3. Optional decay-aware SQLite memory.

### P1

1. `nexus task list|show|events`.
2. Swarm-style handoff events.
3. Journal snippet on resume.
4. Edict review veto (fail-closed).
5. `events(limit=N)` is tail.

### P2

1. `engine.replay` / `engine.explain`.
2. `why` on `step_complete`.
3. CLI `nexus task replay|explain`.

## File map (P3)

| Item | Files | Tests |
|------|-------|-------|
| cost / score / tokens | `src/nexus/engine.py` | `tests/test_engine.py` |
| by_task rollup | `src/nexus/usage.py` | `tests/test_usage_alive.py` |
| thresholds | `src/nexus/judge.py` | `tests/test_judge.py` |
| CLI | `src/nexus/cli.py` | `tests/test_task_cli.py` |
| Plans / log | this file, `docs/SELF_IMPROVE_CYCLE.md`, `docs/ALIVE_IMPROVEMENTS.md` | — |
| Cookbook | `cookbook/01_crash_resume.md` | — |

## Next (P4 backlog)

| Priority | Change | Module |
|----------|--------|--------|
| P4 | Optional Prometheus/OTel counters | `nexus.usage` / extra |
| P4 | Dashboard event timeline | `bridge/dashboard` |
| P4 | Preference learning over judge thresholds | `nexus.judge` |
| P4 | Real provider usage injection (not estimate) | `nexus.usage` + bridges |

## Evidence sources (this cycle)

- **Repos:** mission-control (task costs), solace-agent-mesh, AssetOpsBench, routa, maestro-flow, EDDI, MisterSmith, openclaw-hawkins, rojak, wshobson/agents.
- **arXiv:** value systems / preference RL (2602.04518), CEMA (2302.10809), multi-agent orchestration audit (2511.15755), context engineering (2508.08322), communication survey (2203.08975).

## Done criteria

- `pytest` green
- Full pipeline still completes and resumes mid-run
- `step_complete` rows include `score`, `tokens`, `thresholds`
- `nexus task cost` works (not remapped to `start`)
- No vendored upstream trees; no secrets committed

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q
nexus task list
nexus task cost <task_id>
nexus task cost <task_id> --json
nexus task explain <task_id>
nexus task replay <task_id>
```
