# Latest improve plan (from full self-improve cycle)

_Hard-apply session: Grok 4.5 CLI · 2026-07-15 · P6_

Model: `grok-4.5` · repos=10 · arXiv=10 (see `docs/SELF_IMPROVE_CYCLE.md`)

## First apply slice — **DONE (P6)**

Portable **evidence pack** + structured **norms** from mined repos and arXiv:

1. `task_norms(task)` — NorMAS/constitutional light parse of constraints + meta
2. `DurableEngine.evidence(task_id, *, compact=False)` — `nexus.evidence/v1`
3. CLI: `nexus task evidence <id> [--json] [--compact] [--out PATH]`
4. Tests: norms, ready/not-ready packs, CLI write path

### Files

- `src/nexus/engine.py` — norms + evidence composition
- `src/nexus/cli.py` — `task evidence` subcommand
- `tests/test_engine.py` — unit coverage
- `tests/test_task_cli.py` — CLI coverage
- `cookbook/01_crash_resume.md` — inspect docs

### Sources

- **routa** — goals/tasks/traces/**evidence** delivery board
- **mission-control** — JSON export + spend/timeline inspect
- **AssetOpsBench** — multi-agent evaluation evidence
- **arXiv 2603.13189 / 1709.02018** — constitutional / normative MAS
- Prior P0–P5 surfaces composed (replay, explain, cost, prov, verify, graph)

## Status of prior slices

| Slice | Status |
|-------|--------|
| P0 durability + decay memory | done |
| P1 handoff / veto / task CLI | done |
| P2 replay / explain | done |
| P3 cost / thresholds | done |
| P4 provenance / verify | done |
| P5 budget / graph | done |
| **P6 evidence / norms** | **done this session** |

## Next (P7 candidates)

1. HITL `nexus task resume --approve|--reject` (rojak; engine ready)
2. Optional norm enforcement gates at step start
3. Trust-weighted agent routing
4. Wall-clock budget (`max_wall_s`)
