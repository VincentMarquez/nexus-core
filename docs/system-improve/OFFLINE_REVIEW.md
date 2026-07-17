# Offline review (other LLMs)

Use this when you want Claude, GPT, Gemini, etc. to review the **plan or a step** without going through the NEXUS bus / critique panel.

## What to give the reviewer

1. This folder’s `README.md` + `PRINCIPLES.md` (short context).
2. The **one** step file under review (`steps/Sxx-….md`).
3. Optional: `git diff` for that step only (if already implemented).
4. Optional: `BASELINE.md` if they need product context.

Do **not** dump entire `docs/LATEST_*` or full tree unless asked.

---

## Copy-paste review prompt

```text
You are reviewing a planned change to NEXUS Core (self-improving multi-agent product).

Rules for your review:
- Prefer non-breaking, additive, flag-gated changes.
- One step only — flag scope creep.
- Call out safety (path escape, publish blast radius, fail-open).
- Call out test gaps.
- Do not propose rewriting the whole architecture.
- Separate: (A) must-fix before merge, (B) nice-to-have, (C) out of scope.

Context files attached:
- docs/system-improve/PRINCIPLES.md
- docs/system-improve/steps/Sxx-….md
- (optional) git diff

Return:
1. Verdict: approve / approve-with-nits / request-changes
2. Risks (severity: high/med/low)
3. Missing tests
4. Simpler alternative if any
5. Exact checklist items to add to the step file
```

---

## Where to put review output

| Output | Where |
|--------|--------|
| Nits that change the step | Edit the step file “Review notes” section |
| Product-wide decision | `DECISIONS.md` |
| “Do later” | TRACKER status `later` + note |

Keep a short archive if you want:

```text
docs/system-improve/reviews/S03-claude-2026-07-17.md
```

(Create `reviews/` only when you store the first one.)

---

## What offline review is not

- Not a replacement for unit tests  
- Not automatic promotion into REAL  
- Not the multi-LLM critique panel (that’s product runtime)
