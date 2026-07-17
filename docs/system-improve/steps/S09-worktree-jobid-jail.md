# S09 — worktree job_id path jail

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P3 |
| Risk | Low (safety) |
| Primary files | `src/nexus/worktree_apply.py` |
| Tests | `tests/test_worktree_apply.py::test_job_id_traversal_rejected` |

## Problem

`job_id` concatenated into path without `safe_path`; `../` can escape; `rmtree` follows.

## Goal

Sanitize id + resolve under worktrees root (reuse `improve_apply.safe_path`).

## Non-goals

Redesign worktree feature set.

## Landed

- `sanitize_job_id()` — `[\w.\-]+` only, no `/`, `\`, `..`
- `worktree_path_for()` — `safe_path(worktrees_dir, jid)` + parent check
- `create_worktree` / `cleanup_worktree` / `resolve_worktree` use jail
- cleanup refuses rmtree outside root
