# Self-improve cycle — Grok 4.5

_Generated 2026-07-16_

Model: `grok-4.5` · repos≥10 · arXiv≈20

## Reasoning plan (this cycle)

1. **Read evidence** — `IMPROVE_OURS.md` (top mined clones), latest arXiv notes (`improve-rx-2a3280d550`, `rx-00eb6c8e07`), and prior `ALIVE_IMPROVEMENTS` open items.
2. **Pick First apply slice** — close the last cycle’s open list with small, tested code:
   - APPLY_CANDIDATE → worktree dry-run
   - plan-reuse cache
   - more sample packs
   - alive auto preference pairs from ranked mine results
3. **Hard apply** — implement modules + tests; keep `pytest` green; no force-push; no secrets; no vendored trees.
4. **Document** — update `LATEST_IMPROVE_PLAN.md` + append this cycle to `ALIVE_IMPROVEMENTS.md`.

## Evidence → engineering map

| Source | Pattern (shape only) | Landed |
|--------|----------------------|--------|
| wshobson/agents | Markdown SoT skillpack validate | worktree pattern dry-run |
| cas / forge | Worktree isolation | APPLY_CANDIDATE sandbox apply |
| multi-stage ABM 2604.03350 | Plan reuse across stages | `plan_reuse` cache |
| context eng 2508.08322 | Bounded reusable context | plan fingerprint reuse |
| preference IRL 2602.04518 | Offline better>worse | alive `record_from_ranked` after mine |
| AssetOpsBench / mission-control | Scenario pack smoke | `improve_board_smoke.json` |
| Thucy 2512.03278 | Claim gate before apply | existing mine_eval_slice claims |
| AOAD-MAT 2510.13343 | Ordered stages | MINED→…→APPLY_CANDIDATE |

## First apply slice (session result)

See `docs/LATEST_IMPROVE_PLAN.md` — **landed**.

Prove with:

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m nexus.cli improve plan-slice --repo wshobson/agents
# second call should show worktree cache_hit=true
```
