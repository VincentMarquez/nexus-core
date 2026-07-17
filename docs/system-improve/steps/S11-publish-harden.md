# S11 — Publish P0: baseline fail-closed + pre-staged

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P0 |
| Risk | Low–med (safer publish) |
| Primary files | `src/nexus/publish.py`, `alive.py` |
| Tests | `tests/test_publish.py` (S11 cases) |

## Problem (from Codex S04 review)

1. Failed `git status` for baseline collapsed to empty → staged **all** dirty allowlisted paths.  
2. Pre-staged unrelated files could ride into `git commit`.

## Landed

- `status_porcelain_checked()` → `(lines, ok)`  
- Alive baseline uses checked API; on failure sets `fail_closed` and **refuses publish**  
- `commit_and_maybe_push(..., require_cycle_scope=True)` from alive  
- Cycle-scoped path: `git reset HEAD` then stage only cycle deltas; drop any extra cached paths before commit  

## Not changed

Force-push still forbidden; allowlist deny list unchanged.
