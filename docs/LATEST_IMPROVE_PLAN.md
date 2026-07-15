# Latest improve plan (from full self-improve cycle)

Model: Grok 4.5 · 10 repos graded · 10 arXiv papers · hard apply

## Status

| Slice | Status |
|-------|--------|
| **P0 First apply** — atomic checkpoints + event journal + opt-in memory decay | **Landed** |
| **P1** — operator CLI + handoff events + journal context + review veto | **Landed** |
| **P2 First apply** — replay timeline + causal explain + `why` on step_complete | **Landed** (this session) |
| **P3** — OTel / dashboard timeline / judge prefs / cost rollup | Backlog |

## First apply slice (this session — P2)

**Goal:** Operator-grade post-hoc observability without re-running agents.

Patterns: open-multi-agent **plan-replay**, arXiv **CEMA** causal explanations (2302.10809), mission-control / MisterSmith **inspect**, incident-response multi-agent audit (2511.15755).

1. **`DurableEngine.replay(task_id)`** — normalized timeline from `*.events.jsonl` (no agent re-execution).
2. **`DurableEngine.explain(task_id)`** — causal chain: steps, handoffs, vetoes, failures, one-line `story`.
3. **`why` field on `step_complete`** — truncated judge rationale for audit + journal context.
4. **CLI** — `nexus task replay|explain` with `--json` / `--state-dir` / optional `--limit` on replay.

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

## File map (P2)

| Item | Files | Tests |
|------|-------|-------|
| replay / explain / why | `src/nexus/engine.py` | `tests/test_engine.py` |
| CLI | `src/nexus/cli.py` | `tests/test_task_cli.py` |
| Plans / log | this file, `docs/SELF_IMPROVE_CYCLE.md`, `docs/ALIVE_IMPROVEMENTS.md` | — |
| Cookbook | `cookbook/01_crash_resume.md` | — |

## Next (P3 backlog)

| Priority | Change | Module |
|----------|--------|--------|
| P3 | Optional Prometheus/OTel counters | `nexus.usage` / extra |
| P3 | Dashboard event timeline | `bridge/dashboard` |
| P3 | Preference / value logging for judge thresholds | `nexus.judge` |
| P3 | Task-level usage/cost rollup | `nexus.engine` + `nexus.usage` |

## Evidence sources (this cycle)

- **Repos:** mission-control, solace-agent-mesh, AssetOpsBench, routa, maestro-flow, EDDI, open-multi-agent, nocturne, MisterSmith, openclaw-hawkins, swarm/edict (prior).
- **arXiv:** CEMA causal explanations (2302.10809), multi-agent incident orchestration (2511.15755), context engineering (2508.08322), agent identity ASAF (2606.09832), communication survey (2203.08975).

## Done criteria

- `pytest` green
- Full pipeline still completes and resumes mid-run
- `step_complete` rows include `why` (and `decision`)
- `nexus task replay|explain` work (not remapped to `start`)
- No vendored upstream trees; no secrets committed

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q
nexus task list
nexus task events <task_id> --limit 20
nexus task replay <task_id>
nexus task explain <task_id>
nexus task explain <task_id> --json
```
