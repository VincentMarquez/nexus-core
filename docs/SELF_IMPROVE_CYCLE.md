# Self-improve cycle — backlog & status

_Restored manual review (Grok cycles + human fix-all). Model: grok-4.5._

## Executive summary

- NEXUS product (`VincentMarquez/nexus-core`) self-improves via mine → arXiv → Grok grade/reason/apply → push if tests green.
- **Landed (P0–P9):** atomic checkpoints, event journal, handoffs, replay/explain, cost, provenance, verify, graph, evidence, HITL resume, wall budget, opt-in norm enforcement.
- **False “apply fail”:** Grok CLI often exited `rc=1` after max-turns while still writing code; pytest green → still pushed.
- **This fix-all pass:** restore plans/docs, HITL demo, evidence in alive log, DAG steps, skill packs, community security gate, optional metrics.

## Operator CLI (production audit)

```bash
nexus task list
nexus task show <id>
nexus task events <id>
nexus task replay <id>
nexus task explain <id>
nexus task cost <id>
nexus task prov <id>
nexus task verify <id>
nexus task graph <id> [--mermaid]
nexus task evidence <id> [--out file.json]
nexus task resume <id> [--approve|--reject]
```

Cookbook: [cookbook/12_task_operator.md](../cookbook/12_task_operator.md)

## Priority backlog

| ID | Item | Status |
|----|------|--------|
| P0 | Atomic checkpoints + journal | **done** |
| P1 | Handoffs + journal context on resume | **done** |
| P2 | `replay` / `explain` / why | **done** |
| P3 | `cost` + judge thresholds | **done** |
| P4 | `prov` / `verify` | **done** |
| P5 | token budget + `graph` | **done** |
| P6 | `evidence` + norms pack | **done** |
| P7 | HITL `resume --approve/--reject` | **done** (+ demo) |
| P8 | wall-clock budget | **done** |
| P9 | enforce_norms deny/require | **done** |
| A | Plan docs + task cookbook | **this pass** |
| B | HITL demo script | **this pass** |
| C | Evidence export in alive/publish log | **this pass** |
| D | DAG / depends_on steps | **this pass** |
| E | Skill-pack layout | **this pass** |
| F | Community reply security gate | **this pass** |
| G | Optional OTel/Prometheus metrics | **this pass** |

## Top mined patterns (reuse, don’t vendor)

| Score | Repo | Pattern |
|------:|------|---------|
| 16 | phodal/routa | Evidence / delivery board |
| 15 | mission-control | Ops cost + quality gates |
| 15 | MisterSmith | Supervised runtime + MCP |
| 15 | wshobson/agents | Multi-harness skill packs |
| 14 | cycgraph | Multi-budget safety |
| 13 | rojak | Temporal + HITL |

## First apply slice (manual fix-all)

Implement A–G above with tests green; push to GitHub.
