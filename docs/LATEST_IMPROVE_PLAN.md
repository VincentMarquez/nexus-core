# Latest improve plan (from full self-improve cycle)

Model: Grok 4.5 · 10 repos graded · 10 arXiv papers · hard apply

## Status

| Slice | Status |
|-------|--------|
| **P0 First apply** — atomic checkpoints + event journal + opt-in memory decay | **Landed** |
| **P1** — operator CLI + handoff events + journal context + review veto | **Landed** (this session) |
| **P2** — observability / dashboard timeline / judge preference log | Backlog |

## First apply slice (P0 — done)

1. **Atomic durable checkpoints** (`os.replace` write-then-rename) for task state and trust log — Durable Functions / Temporal shape from DurableMultiAgentTemplate, Rojak, DriftQ.
2. **Append-only task event journal** (`tasks/<id>.events.jsonl`) — edict audit trail + MisterSmith operator surface, filesystem-only.
3. **Optional decay-aware SQLite memory** — openclaw-hawkins decay pattern; default off so existing scores stay stable.

## P1 apply slice (this session — done)

1. **CLI operator surface** — `nexus task list|show|events` (MisterSmith / DriftQ inspect).
2. **Swarm-style handoff events** when `panel.resolve()` switches agents mid-run.
3. **Journal snippet on resume** — last-N lines injected into step prompts (context engineering arXiv 2508.08322).
4. **Edict review veto** — fail-closed when review step `verdict` ∈ {reject, veto, fail, deny, blocked}.
5. **`events(limit=N)` is tail** — operator timeline shows most recent events.

## P0/P1 file map

| Item | Files | Tests |
|------|-------|-------|
| Persist helpers | `src/nexus/persist.py` | `tests/test_persist.py` |
| Engine journal + atomic save + handoff/veto/context | `src/nexus/engine.py` | `tests/test_engine.py`, `tests/test_persist.py` |
| Trust atomic flush | `src/nexus/trust.py` | covered via engine |
| Memory decay + ts | `src/nexus/memory_sqlite.py` | `tests/test_memory_sqlite.py` |
| Task CLI | `src/nexus/cli.py` | `tests/test_task_cli.py` |
| Plans / log | `docs/SELF_IMPROVE_CYCLE.md`, this file, `docs/ALIVE_IMPROVEMENTS.md` | — |

## Next (P2 backlog)

| Priority | Change | Module |
|----------|--------|--------|
| P2 | Optional Prometheus/OTel counters (DriftQ lean) | `nexus.usage` / extra |
| P2 | Dashboard event timeline surface (edict board) | `bridge/dashboard` |
| P2 | Preference / value logging for judge thresholds | `nexus.judge` |
| P2 | Cookbook + ALIVE docs for `nexus task *` | `docs/cookbook/` |

## Evidence sources

- **Repos:** wshobson/agents (16), MisterSmith / openclaw-hawkins / oh-my-claudecode / nocturne (15), rojak (14), swarm / edict / symphony-claude-lane / threadwork (13).
- **arXiv:** multi-agent communication survey (2203.08975), context engineering (2508.08322), multi-LLM tool agents (2401.07324), conventions (2412.06333), claim verification (2512.03278), stabilizing controllers → heartbeat (2103.04480).

## Done criteria

- `pytest` green
- Full pipeline still completes and resumes mid-run
- Journal file appears after `engine.run`; handoffs + veto recorded
- `nexus task list|events|show` works (not remapped to `start`)
- No vendored upstream trees; no secrets committed

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q
nexus task list
nexus task events <task_id> --limit 20
# optional full cycle (mine + arxiv + reason + apply):
# PYTHONPATH=src NEXUS_GROK_MODEL=grok-4.5 python3 scripts/full_self_improve_cycle.py
```
