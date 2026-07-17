# S04 offline review packet (copy to other LLMs)

Paste this whole file (or attach the linked paths) into Claude / GPT / Gemini **outside** the NEXUS bus.

---

## Reviewer prompt

```text
You are reviewing a planned change to NEXUS Core (self-improving multi-agent product).

Rules for your review:
- Prefer non-breaking, additive, flag-gated changes.
- One step only — flag scope creep.
- Call out safety (path escape, publish blast radius, fail-open).
- Call out test gaps.
- Do not propose rewriting the whole architecture.
- Separate: (A) must-fix before merge, (B) nice-to-have, (C) out of scope.
- Note: the author previously built a Bubbles multi-agent system where every agent
  subclassed UniversalBubble (required object_id + SystemContext), and a NEXUS DNA
  preamble injected into every prompt (AGENT_DNA.md / D*=0). SARSI paper is related
  inspiration. Judge S04 as "port that discipline," not "rebuild Bubbles."

Return:
1. Verdict: approve / approve-with-nits / request-changes
2. Risks (severity: high/med/low)
3. Missing tests
4. Simpler alternative if any
5. Exact checklist items to add to the step file
6. Whether the Bubbles/DNA analogy is used correctly (yes/no + one sentence)
```

---

## Attach / paste these (in order)

1. Principles (short):

```text
# From docs/system-improve/PRINCIPLES.md — summary
1. One step at a time
2. Observe → soft gate → hard gate
3. Defaults non-breaking
4. Tests before done
5. Don't fight live REAL
6. Unit of work = delta
7. Offline review independent of product bus
8. Owner remains authority
9. North star SWE-Pro / coding excellence
10. Write decisions when ambiguous
```

2. Full step: `docs/system-improve/steps/S04-idea-scope-contract.md`

3. Bubbles/DNA lineage: `docs/system-improve/references/BUBBLES_DNA_AND_SARSI.md`

4. Optional SARSI map: `docs/system-improve/references/SARSI_NEXUS.md`

---

## Where to put the model’s reply

Save as:

```text
docs/system-improve/reviews/S04-<model>-YYYY-MM-DD.md
```

Then paste a short summary into the **Review notes** section of `steps/S04-idea-scope-contract.md`.

---

## Grok review already on file

See step file § “Grok offline review (2026-07-17)” — **approve-with-nits**, soft-only v1.
