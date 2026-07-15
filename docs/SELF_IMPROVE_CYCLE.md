# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 (P0–P4 hard-apply)_

Model: `grok-4.5` · repos=10 · arXiv=10

---

## Executive summary

- NEXUS already has crash→resume tasks, mine/alive loops, Grok grading, and heartbeat recovery.
- Prior slices landed **durability** (P0), **multi-agent communication + operator board** (P1), **post-hoc replay/explain** (P2), and **task cost + value thresholds** (P3).
- This session’s sources (PROV-AGENT arXiv, mission-control timeline, routa traces, fault-tolerant checkpointing, MisterSmith/EDDI audit) point at **unified provenance export + checkpoint↔journal integrity**.
- **P4 First apply (this session):** `engine.provenance`, `engine.verify`, CLI `nexus task prov|verify`, list board tokens column.
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
| 2508.02866 | PROV-AGENT unified provenance for agent workflows | `engine.provenance` agents/activities/entities/relations |
| 2310.12670 | Fault-tolerant checkpoint integrity | `engine.verify` checkpoint↔journal checks |
| 2506.17266 | Firewall / secure agentic workflows | Integrity gate before resume/export trust |
| 2606.14130 | Contract-based compositional shielding | Fail-closed verify issues (error vs warn) |
| 2203.08975 | Communication coordinates agents | Handoff relations in provenance |
| 2508.08322 | Context engineering for multi-file agents | Journal context on resume (P1) |
| 2302.10809 | Causal explanations for sequential MAS | `engine.explain` + `why` (P2) |
| 2511.15755 | Multi-agent orchestration audit | Deterministic `replay` timeline (P2) |
| 2602.04518 | Value systems / preference learning | Judge thresholds + score on events (P3) |
| 2102.08370 | Diversity / generalization in multi-agent | Board inspect across tasks |

## 10 GitHub repos — portable patterns

| repo | score | pattern | where ported |
|------|-------|---------|--------------|
| builderz-labs/mission-control | 15.0 | Activity timeline + cost board | `task list` tokens + prov/verify |
| MattMagg/MisterSmith | 16.0 | Supervised execution + operator surfaces | Event journal + task CLI |
| phodal/routa | 15.0 | Board-visible goals/tasks/traces | `provenance` export |
| wshobson/agents | 16.0 | Multi-harness marketplace | Worker/grader selection |
| labsai/EDDI | 15.0 | Production audit / MCP | Append-only events + verify |
| AgenticGoKit/AgenticGoKit | 14.0 | OTel / metrics-minded APIs | Structured prov schema |
| catlog22/maestro-flow | 14.0 | Adaptive lifecycle + knowledge graph | Ordered activities chain |
| SolaceLabs/solace-agent-mesh | 15.0 | Event-driven multi-agent mesh | Structured journal events |
| IBM/AssetOpsBench | 15.0 | Eval CLI / multi-backend runners | Operator inspect surfaces |
| bobmatnyc/claude-mpm | 15.0 | Multi-agent packaging | Small scoped port, not vendor |

Also: DurableMultiAgentTemplate / DriftQ / Rojak write-then-rename → `nexus.persist`.

## Prioritized engineering backlog

### P0–P3 (landed)

Atomic checkpoints, event journal, decay memory, task CLI, handoffs, veto, journal context, replay, explain, `why`, cost, score/tokens/thresholds, `usage.by_task`.

### P4 (this session — First apply)

1. **`engine.provenance(task_id)`** — PROV-style agents, activities, entities, relations.
2. **`engine.verify(task_id)`** — checkpoint ↔ journal integrity (ok / issues / checks).
3. **CLI `nexus task prov|verify`** (+ `--json`); list board shows tokens.
4. **Tests** — healthy run passes verify; status drift fails closed.

### P5 (next)

1. Optional Prometheus/OTel counters (AgenticGoKit shape).
2. Dashboard HTML event timeline (mission-control widget pattern).
3. Preference learning over judge thresholds.
4. Real provider token injection (bridges) instead of estimates.
5. Wire `verify` into resume path as optional hard gate.

## First apply slice → evidence (P4)

| Item | Files | Tests |
|------|-------|-------|
| provenance + verify | `src/nexus/engine.py` | `tests/test_engine.py` |
| task prov/verify CLI | `src/nexus/cli.py` | `tests/test_task_cli.py` |
| Plans / log | this file, `docs/LATEST_IMPROVE_PLAN.md`, `docs/ALIVE_IMPROVEMENTS.md` | — |
| Cookbook | `cookbook/01_crash_resume.md` | — |

```bash
PYTHONPATH=src python3 -m pytest -q
nexus task prov <id> --state-dir .nexus_state
nexus task verify <id>
nexus task list
```
