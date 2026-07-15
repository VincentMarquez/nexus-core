# Latest improve plan (from full self-improve cycle)

Model: Grok 4.5 · 10 repos graded · 10 arXiv papers · hard apply

## First apply slice (implement now)

1. **Atomic durable checkpoints** (`os.replace` write-then-rename) for task state and trust log — Durable Functions / Temporal shape from DurableMultiAgentTemplate, Rojak, DriftQ.
2. **Append-only task event journal** (`tasks/<id>.events.jsonl`) — edict audit trail + MisterSmith operator surface, filesystem-only.
3. **Optional decay-aware SQLite memory** — openclaw-hawkins decay pattern; default off so existing scores stay stable.

## P0 backlog

| Priority | Change | Module |
|----------|--------|--------|
| P0 | Atomic JSON writes | `nexus.persist` |
| P0 | Engine event journal + `events()` API | `nexus.engine` |
| P0 | Trust log atomic flush | `nexus.trust` |
| P0 | Memory `ts` + optional decay | `nexus.memory_sqlite` |
| P1 | CLI `task events` | `nexus.cli` |
| P1 | Journal snippet in cascade context | `nexus.cascade` / engine |
| P1 | Explicit swarm-style handoff metadata | `nexus.agents` |

## Evidence sources

- **Repos:** MattMagg/MisterSmith (15), openai/swarm (14.2), oh-my-claudecode (14), edict (14), rojak (14), plus DurableMultiAgentTemplate, threadwork, migration-orchestrator, symphony-claude-lane, CasperCLI.
- **arXiv:** multi-agent communication survey, context engineering for code agents, multi-LLM tool agents, conventions for cooperation, claim verification, stabilizing controllers (maps to heartbeat).

## Done criteria

- `pytest` green
- Full pipeline still completes and resumes mid-run
- Journal file appears after `engine.run`
- No vendored upstream trees; no secrets committed

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q
# optional full cycle (mine + arxiv + reason + apply):
# PYTHONPATH=src NEXUS_GROK_MODEL=grok-4.5 python3 scripts/full_self_improve_cycle.py
```
