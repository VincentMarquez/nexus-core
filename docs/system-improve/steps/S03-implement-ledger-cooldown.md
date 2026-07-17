# S03 — Implement ledger + portfolio cooldown

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P1 |
| Risk | Low (soft demote + fail-open) |
| Primary files | `src/nexus/idea_portfolio.py`, `src/nexus/alive.py` |
| Tests | `tests/test_implement_ledger.py` |

## Problem

Portfolio always picks top-scoring GitHub (e.g. `wshobson/agents`) as `required_github` every REAL run. No cross-cycle memory of “already ok.” Same for novels glued to that seed.

## Goal

After a successful implement of idea `id` (and optionally github seed), **demote** that id/seed for the next N cycles or M days unless override.

## Non-goals

- Full SARSI self-model  
- Blocking all github ideas  
- Changing max_ideas=10 quota structure  
- Deleting history  

## Proposed design (for offline review)

1. **Ledger file** (append-only or JSON):
   - path idea: `.nexus_state/implement_ledger.jsonl` (local) + optional short summary in docs later  
   - fields: `ts`, `id`, `source`, `seed` (repo or arxiv), `ok`, `cycle_id`  
2. **On implement success** (in `implement_portfolio` or alive after): append row.  
3. **On `select_portfolio` / `build_portfolio`**:
   - load recent ok ids/seeds within cooldown window (config: e.g. 3 cycles or 7 days)  
   - skip those for `required_github` / fill unless no alternative remains  
   - still allow if pool empty (fail-open to old behavior)  
4. **Config** in alive.json optional:
   - `portfolio_cooldown_days` or `portfolio_cooldown_cycles`  
   - `portfolio_cooldown_disable: true` escape hatch  

## Acceptance criteria

- [x] Unit test: after ok id in ledger, select_portfolio demotes when alternatives exist  
- [x] Unit test: if only that github exists, still picks something (cooldown_reuse)  
- [x] Default path boots without new env vars (`portfolio_cooldown_days=7`)  
- [x] TRACKER updated  

## Test plan

```bash
.venv/bin/python -m pytest -q tests/test_implement_ledger.py
```

## Rollback

Set `portfolio_cooldown_disable: true` in `.nexus_state/alive.json`, or `portfolio_cooldown_days: 0`.

## Review notes

Landed with operator stop of mid-run REAL; soft demote only.

## Implementation notes

- Ledger: `.nexus_state/implement_ledger.jsonl`
- `append_implement_ledger` after each portfolio idea in `implement_portfolio`
- `build_portfolio` bootstraps once from `alive_state.json` if ledger empty
- `select_portfolio(..., cooled_ids=)` via `order_with_cooldown` (hot first, cold tail)
- Config: `portfolio_cooldown_days` (default 7), `portfolio_cooldown_disable`

## Done checklist

- [x] Code  
- [x] Tests green  
- [x] TRACKER → done  
- [x] BASELINE append  

