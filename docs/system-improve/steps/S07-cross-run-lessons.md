# S07 — Cross-run lessons injection

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P1 |
| Risk | Low |
| Primary files | `src/nexus/cross_run_lessons.py`, `alive.py` |
| Tests | `tests/test_cross_run_lessons.py` |

## Problem

Cycles repeat the same failure classes (timeouts, thrash, fail-open) with no structured memory.

## Goal

After REAL: write short lesson records; next dual_review / portfolio brief injects top lessons (AutoResearchClaw / MetaClaw-shaped).

## Non-goals

Auto skillpack generation; ML over lessons.

## Landed

- Ledger: `.nexus_state/cross_run_lessons.jsonl`
- `harvest_lessons_from_report()` after meta_review (X fail, engine fail, implement fail, panel fail, synthesis revert, accept reject, publish skip, cooldown reuse)
- `load_lessons` + `format_lessons_block` + inject into `_phase_dual_review` before section `## 1. GitHub`
- Default **on** (`cross_run_lessons_enable: true`)
- De-dupe by code+text; max age 30 days

## Disable

```json
"cross_run_lessons_enable": false
```

## Related

S03 cooldown (selection); S07 is narrative memory for the brief.
