# S10 — gitignore `.nexus/` hygiene

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P0 |
| Risk | Trivial |

## Problem

`.gitignore` line:

```gitignore
.nexus/                 # runtime workspace chat (not source)
```

Mid-line `#` is not a comment → `.nexus/` may not be ignored (`git check-ignore` fails).

## Goal

```gitignore
# runtime workspace chat (not source)
.nexus/
```

## Verify

```bash
git check-ignore -v .nexus/workspace/chat.jsonl
```

## Non-goals

Ignore policy redesign for all state dirs.
