# S05 — Accept predicate (evidence-gated ok)

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P2 |
| Risk | Low (soft observe only) |
| Primary files | `src/nexus/accept_predicate.py`, `idea_portfolio.py`, `alive.py` |
| Tests | `tests/test_accept_predicate.py` |

## Problem

`ok=True` often means worker finished, not “quality improved under held-out or proxy.”

## Goal

Soft Accept first: record `accept: true/false` + reasons (tests, optional proxy). Later: hard block promote/push when accept false (flag).

## Non-goals

Full SWE-Pro suite every idea (too slow); weight training; changing worker `ok`.

## Landed

- `evaluate_accept()` — worker ok, panel status notes, scope forbidden hits, py_compile on slice py files, optional contract success_check when paths exist
- Soft only: **does not rewrite** `entry["ok"]`
- Default **on** (`accept_predicate_enable: true`) — observation only
- Summary on portfolio result: `accept_predicate: {evaluated, accepted, rejected, accept_rate}`
- Config: `AliveConfig.accept_predicate_enable`

## Disable

```json
"accept_predicate_enable": false
```

## Future (not S05)

- `accept_hard_block_publish` when accept_rate low or any reject
- Held-out SWE-Pro proxy suite
