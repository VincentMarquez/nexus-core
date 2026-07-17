# Principles (do not break the system)

These rules apply to every step in this plan. Offline reviewers should flag any step that violates them.

## 1. One step at a time

- Only one `steps/Sxx-*.md` is **in progress**.
- No “while we’re here” refactors across unrelated modules.
- Prefer a small commit that is easy to revert.

## 2. Prefer additive gates over rewiring the spine

Safe order of change:

1. **Observe** (log / ledger / metric)
2. **Soft gate** (warn, demote, skip optional path)
3. **Hard gate** (block implement/publish) only with override flag

Never flip REAL to fail-closed on three axes at once.

## 3. Default flags preserve current behavior

New behavior should be:

- **opt-in** via config/env, or
- **opt-out** only when tests prove the old path was clearly wrong (e.g. whole dirty tree as critique slice)

Example: cycle-scoped publish is correct-by-default for safety of *what ships*; if something needs “stage everything dirty,” that becomes an explicit override.

## 4. Tests before claiming done

Minimum for any code step:

```bash
# From repo root, with project venv
.venv/bin/python -m pytest -q tests/test_<module>.py
# Plus a cheap import smoke if the step touches alive/portfolio/publish:
.venv/bin/python -c "from nexus import alive, idea_portfolio, publish, critique_panel; print('ok')"
```

Do not require a full multi-hour REAL cycle to mark a step done.

## 5. Do not fight a live REAL process

- If `nexus alive once` is running, **do not** restart it to “pick up” half-landed edits unless the operator explicitly wants that.
- Document “takes effect next process.”
- Avoid large renames while Grok is editing the same files.

## 6. Unit of work is a delta

- Critique review unit = idea delta, not whole dirty tree.
- Publish unit = cycle delta, not whole dirty tree.
- Portfolio unit = ideas not recently completed.

## 7. Independent review is offline

- Other LLMs review **this folder + a small diff**, not via the product bus as a new self-improve phase (unless we later add that as an explicit step).
- Review findings go into the step file or `DECISIONS.md`, not only chat.

## 8. Owner remains the authority

- No self-granted permissions, budgets, or force-push.
- Creation of a candidate (portfolio idea, worktree, pack) ≠ activation/ship.
- High-risk: human (or explicit flag) before raise of autonomy.

## 9. North star stays SWE-Pro / coding excellence

Self-infra improvements must serve **better coding agent behavior** (tests, recovery, scoped apply, honest metrics)—not endless re-port of the same high-star GitHub repo.

## 10. When unsure, stop and write a decision

If a step has two valid designs, add a row to `DECISIONS.md` and pick one. Do not implement both “just in case.”
