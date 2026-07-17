# S06 — Quarantine → promote for portfolio

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P3 |
| Risk | Medium (opt-in; falls back to main) |
| Primary files | `src/nexus/portfolio_quarantine.py`, `idea_portfolio.py`, `alive.py` |
| Tests | `tests/test_portfolio_quarantine.py` |

## Problem

REAL portfolio hard-applies on main; failures and cross-idea dirt accumulate.

## Goal

Optional mode: implement in worktree/sandbox; promote allowlisted delta after tests (reuse `worktree_apply` patterns).

## Non-goals

Force all paths through worktree on day one; replace Grok.

## Landed

- `portfolio_quarantine.quarantine_apply()` — git worktree → Grok → promote allowlisted paths → cleanup
- Default **OFF**: `implement_quarantine: false`
- On worktree failure → **fallback to main** apply (fail-open with metadata)
- Promote uses `safe_path` + publish allowlist; refuses outside `apply_worktrees/`

## Enable

```json
"implement_quarantine": true
```
