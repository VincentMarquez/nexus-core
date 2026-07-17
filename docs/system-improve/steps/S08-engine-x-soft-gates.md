# S08 — Engine / X soft gates on REAL

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P2 |
| Risk | Low–med (publish only) |
| Primary files | `src/nexus/alive.py` (`_real_input_health`) |
| Tests | `tests/test_real_input_health.py` |

## Problem

`required_on_real` is labeled mandatory but implement continues when engine/X fail.

## Goal

Soft first: record health; **block publish** (not research) when X or engine failed unless override. Optional later: block implement.

## Non-goals

Hard-stop entire cycle on first flake without flags. **Not** publish baseline harden (S11).

## Landed

- `_real_input_health(report, cfg)` → `x_ok`, `engine_ok`, `publish_allowed`
- Step `real_input_health` recorded every REAL cycle
- If `push_github` and not `publish_allowed` → skip publish with clear reason
- Research + implement **still run** (soft)
- Flags:
  - `real_gate_publish` default **true**
  - `real_gate_override` default **false**

## Override

```json
"real_gate_override": true
```

or disable gate:

```json
"real_gate_publish": false
```
