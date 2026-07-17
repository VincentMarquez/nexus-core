# SARSI → Nexus (design map)

Paper: [arXiv:2607.12254](https://arxiv.org/abs/2607.12254)  
**Type:** position / systems-design (not a working implementation).

Use as a **checklist**, not a rewrite target.

## Core SARSI ideas we care about

| Idea | Meaning | Nexus gap | Plan step |
|------|---------|-----------|-----------|
| Goal stack / contract | Safety > mission > owner > improve > task | Soft goals in alive.json only | S04 |
| Scope contract | What may be touched | Slice/publish partly fixed | S01, S02, S04 |
| Evidence-gated Accept | Promote only if held-out improves + safe | `ok` often means worker returned | S05 |
| External governance | Policy/eval outside agent write path | Fragments (Cedar, budgets) | later |
| Self-model / history | What we did / can / failed | Logs exist; selection ignores them | S03, S07 |
| Creation ≠ activation | Candidates quarantine | Portfolio lands on main | S06 |
| Auto-Index modes | interactive / hybrid / autonomous | dry / REAL / flags | keep as-is |
| Safety invariants | No self-grant authority, rollback, etc. | Partial | PRINCIPLES + S09 |

## Do not implement from SARSI yet

- Personal Singularity OS  
- Weight / meta-level self-improvement (their stage 8)  
- Full agent foundry with multi-parent recombination  
- Claiming “self-aware” product marketing

## Staging reminder (their roadmap, compressed)

1. Registry / router / contracts  
2. Self-model  
3. Tool registry + benchmarks  
4–5. Specialists + memory  
6. Improvement manager (quarantine + accept)  
7. Foundry  
8. Weights last  

Nexus is already jumping around stages 1+6+7 in REAL. This plan **slows the thrash** and adds **memory + accept** before more self-edit volume.
