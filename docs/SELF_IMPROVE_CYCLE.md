# Self-improve cycle — Grok 4.5

_Generated / restored 2026-07-15 (P1.4 hard-apply session)_

Model: `grok-4.5` · repos≥10 · arXiv≥10

---

## Reasoning plan (how this worker applies)

1. **Read evidence** — `IMPROVE_OURS.md`, latest `USE_LATEST.md`, newest `.nexus_state/arxiv_improve/improve-rx-*.md`.
2. **Pick first open slice** — from `docs/LATEST_IMPROVE_PLAN.md` status table (P0 → P1.x in order).
3. **Port patterns only** — small modules + tests from scout clones under `.nexus_workspaces/scout_repos/`; never vendor whole trees.
4. **Hard apply** — implement, wire CLI/MCP when operator-facing, keep `pytest` green.
5. **Document** — update `docs/LATEST_IMPROVE_PLAN.md` + append `docs/ALIVE_IMPROVEMENTS.md`.

---

## This session — First apply slice: **P1.4 context pack stage**

Prior sessions landed P0 durability, improve-apply FSM, ops plane (P1.1), task DAG (P1.2), consensus grading (P1.3). **P1.4** formalizes the bounded multi-source context pack used by improve-apply and task operators.

### Evidence drivers

| Source | Signal |
|--------|--------|
| arXiv **2508.08322** | Context engineering for multi-agent LLM code assistants |
| arXiv **2203.08975** / **2512.03278** | Communication + evidence-linked claims |
| IMPROVE_OURS top repos | routa traces, mission-control export, zenith replan context, wshobson digests |
| Scout: Denis2054 Context-Engineering… | Sectioned context shape (pattern only) |

### Implementation summary

- New module `src/nexus/context_pack.py` (`nexus.context_pack/v1`)
- improve_apply `context_packed` phase uses formal builder
- `DurableEngine.context_pack()` + `nexus task context` + MCP `context_pack`
- Tests in `tests/test_context_pack.py`

### Commands

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m nexus.cli task context <id> --prompt --research --repos
```

See `docs/LATEST_IMPROVE_PLAN.md` for acceptance checklist and next open items.
