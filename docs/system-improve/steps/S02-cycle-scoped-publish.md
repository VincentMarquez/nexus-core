# S02 — Cycle-scoped publish

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P0 |
| Risk | Low–med (changes what gets committed) |
| Primary files | `src/nexus/publish.py`, `src/nexus/alive.py` |
| Tests | `tests/test_publish.py` |

## Problem

`stage_allowed` staged every dirty allowlisted path → one push could ship prior WIP.

## Solution landed

- Capture porcelain baseline at start of `cycle_once`  
- `stage_allowed(..., baseline_status=…)` skips paths dirty at baseline  
- Only newly dirty allowlisted paths stage/commit  

## Verify

```bash
.venv/bin/python -m pytest -q tests/test_publish.py
```

## Takes effect

Next `alive once` that runs publish with `push_github`.

## Override later (if needed)

If ops need “stage all dirty allowlisted,” add explicit flag in a future step—do not silently revert S02.

## Review notes

—  
