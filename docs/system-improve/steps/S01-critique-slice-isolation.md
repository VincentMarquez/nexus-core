# S01 — Critique slice isolation

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P0 |
| Risk | Low |
| Primary files | `src/nexus/critique_panel.py` |
| Tests | `tests/test_critique_panel.py` |

## Problem

Panel treated the whole dirty tree as the idea slice (`changed |= after`), so critics and synthesis saw unrelated WIP.

## Solution landed

- `list_slice_files` = strict porcelain delta only  
- Snapshot / revert = implement slice + synthesis delta (not all dirty product paths)  
- Pre-existing dirty outside slice left alone on revert  

## Verify

```bash
.venv/bin/python -m pytest -q tests/test_critique_panel.py
```

## Takes effect

Next Python process that imports `critique_panel` (next `alive once`).

## Review notes

—  
