# How to execute a step without breaking the system

## 0. Preconditions

- [ ] Read `PRINCIPLES.md`
- [ ] Step is `ready` or you explicitly reprioritized in `TRACKER.md`
- [ ] No other step is `in_progress`
- [ ] Prefer no concurrent full REAL cycle editing the same files (or accept “next process”)

## 1. Pre-flight

1. Set TRACKER status → `in_progress`.
2. Open `steps/Sxx-….md` — scope, non-goals, test plan, rollback.
3. Optional: paste step file into another LLM using `OFFLINE_REVIEW.md`.
4. Resolve any review blockers in the step file or `DECISIONS.md` **before** coding.

## 2. Implement

- Touch **only** files listed in the step.
- Keep defaults non-breaking (opt-in hard gates).
- Add/adjust unit tests listed in the step.
- Do not expand portfolio size, rewrite engine, or “also fix” S0x+1.

## 3. Verify

Minimum:

```bash
cd ~/nexus-core
.venv/bin/python -m pytest -q <tests named in step>
.venv/bin/python -c "from nexus import alive, idea_portfolio, publish, critique_panel; print('import ok')"
```

If step touches CLI/MCP surfaces, add the step’s extra check.

## 4. Land

- Prefer one focused commit (message: `system-improve(Sxx): …`).
- Update step file status section → Done + date.
- Update `TRACKER.md`.
- If behavior is subtle, append to `BASELINE.md` “Baseline updates”.

## 5. Rollback

If something regresses:

```bash
git revert <commit>   # or restore the few files
# re-run the step’s tests
```

Document in `DECISIONS.md` what failed.

## 6. What not to do

- Do not start a 10-idea REAL to “validate” a pure unit-testable change.
- Do not merge lab bus and product bus as part of a small step.
- Do not mark done based only on chat agreement—tests + tracker update.
