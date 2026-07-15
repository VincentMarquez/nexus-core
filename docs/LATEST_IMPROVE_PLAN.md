# Latest improve plan (from full self-improve cycle)

Model: Grok 4.5 · 10 repos graded · 10 arXiv papers · hard apply

## Status

| Slice | Status |
|-------|--------|
| **P0 First apply** — atomic checkpoints + event journal + opt-in memory decay | **Landed** |
| **P1** — operator CLI + handoff events + journal context + review veto | **Landed** |
| **P2** — replay timeline + causal explain + `why` on step_complete | **Landed** |
| **P3** — task cost rollup + judge value thresholds | **Landed** |
| **P4 First apply** — provenance export + checkpoint/journal verify | **Landed** (this session) |
| **P5** — OTel counters / dashboard timeline / resume hard-gate | Backlog |

## First apply slice (this session — P4)

**Goal:** Operator-grade **unified provenance** and **durability integrity** without re-running agents.

Patterns: PROV-AGENT (2508.02866), fault-tolerant checkpointing (2310.12670), mission-control activity timeline, routa traces, MisterSmith/EDDI audit, AgenticGoKit structured telemetry schemas.

1. **`DurableEngine.provenance(task_id)`** — PROV-style document:
   - **agents** (id, vendor, steps, tokens)
   - **activities** (per-step name/decision/score/tokens/why)
   - **entities** (task, artifact, journal)
   - **relations** (`wasAssociatedWith`, `used`, `generated`, `wasInformedBy`, handoff `wasDerivedFrom`)
   - merges explain/cost + optional `trust.json` rows
2. **`DurableEngine.verify(task_id)`** — checkpoint ↔ journal consistency:
   - parseable checkpoint/journal
   - step alignment, status terminal events, agent/token soft checks
   - returns `ok`, `issues[]` (error|warn), `checks{}`
3. **CLI** — `nexus task prov` / `nexus task verify` (+ `--json`); `task list` shows **TOK** column.
4. **Tests** — healthy completed run is `ok`; injected status drift fails.

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

### P3

1. `engine.cost` + score/tokens/thresholds on events.
2. `usage.by_task` / judge threshold constants.
3. CLI `nexus task cost`.

## File map (P4)

| Item | Files | Tests |
|------|-------|-------|
| provenance / verify | `src/nexus/engine.py` | `tests/test_engine.py` |
| CLI | `src/nexus/cli.py` | `tests/test_task_cli.py` |
| Plans / log | this file, `docs/SELF_IMPROVE_CYCLE.md`, `docs/ALIVE_IMPROVEMENTS.md` | — |
| Cookbook | `cookbook/01_crash_resume.md` | — |

## Next (P5 backlog)

| Priority | Change | Module |
|----------|--------|--------|
| P5 | Optional Prometheus/OTel counters | `nexus.usage` / extra |
| P5 | Dashboard event timeline HTML | `bridge/dashboard` |
| P5 | Preference learning over judge thresholds | `nexus.judge` |
| P5 | Real provider usage injection (not estimate) | `nexus.usage` + bridges |
| P5 | Optional hard-gate: refuse resume if `verify` errors | `engine.resume` |

## Evidence sources (this cycle)

- **Repos:** mission-control, MisterSmith, routa, EDDI, AgenticGoKit, maestro-flow, solace-agent-mesh, AssetOpsBench, wshobson/agents, claude-mpm.
- **arXiv:** PROV-AGENT (2508.02866), fault-tolerant checkpointing (2310.12670), securing agentic workflows (2506.17266), compositional shielding (2606.14130), plus prior communication/CEMA/value-system papers.

## Done criteria

- `pytest` green
- Full pipeline still completes and resumes mid-run
- `nexus task prov` emits schema `nexus.prov/v1` with agents + relations
- `nexus task verify` returns OK on healthy completed task; non-zero on integrity errors
- No vendored upstream trees; no secrets committed

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q
nexus task list
nexus task prov <task_id>
nexus task prov <task_id> --json
nexus task verify <task_id>
nexus task verify <task_id> --json
nexus task cost <task_id>
nexus task explain <task_id>
nexus task replay <task_id>
```
