# Roadmap (phased)

Order is **safety and trackability first**, then quality of self-edit, then optional hardness.

Inspired by (not copying): SARSI stages, AutoResearchClaw cross-run lessons, DGM accept-on-eval, Gas Town isolation. Details in `references/`.

---

## Phase P0 — Stabilize unit of work (foundation)

**Goal:** Stop reviewing and shipping the wrong files.

| Step | Title | Risk to live system |
|------|-------|---------------------|
| S01 | Critique slice isolation | Low (correctness) — **done** |
| S02 | Cycle-scoped publish | Low–med (changes what commits) — **done** |
| S10 | gitignore `.nexus/` hygiene | Trivial |

**Exit criteria:** Next REAL cycle shows narrow `files` in panel STATUS and publish stages only cycle-new paths (when push enabled).

---

## Phase P1 — Memory across runs (stop thrash)

**Goal:** Do not re-implement the same high-score idea every cycle.

| Step | Title | Risk |
|------|-------|------|
| **S03** | Implement ledger + portfolio cooldown | Low if soft demote first |
| S07 | Cross-run lessons (failures → next brief) | Low if inject-only |

**Exit criteria:** `wshobson/agents` (or any id) ok in last N cycles is demoted unless override; lessons file updates after REAL.

---

## Phase P2 — Contracts and accept (honest improvement)

**Goal:** Every apply has scope + success definition; “ok” means evidence.

| Step | Title | Risk |
|------|-------|------|
| S04 | Idea / cycle scope contract | Med (wire into implement) |
| S05 | Accept predicate (tests + optional proxy) | Med (soft then hard) |
| S08 | Engine / X soft gates on REAL | Med (flags required) |

**Exit criteria:** Portfolio entry records contract; implement report includes accept/fail-with-reason; REAL can soft-block push without killing research.

---

## Phase P3 — Isolation and promote (production-shaped)

**Goal:** Candidates quarantine; main only after promote.

| Step | Title | Risk |
|------|-------|------|
| S06 | Quarantine worktree → promote path for portfolio | Higher — do after P1/P2 |
| S09 | job_id path jail | Low, pure safety |

**Exit criteria:** Optional mode: implement lands in worktree; promote copies allowlisted delta after tests.

---

## Later (not scheduled until P0–P2 feel boring)

- Panel quorum (≥2 critics) before synthesis  
- multi_llm real registry opt-in  
- MCP restart / bus health pin in preflight  
- UI chips for panel / cycle scope  
- SARSI self-model document (structured)  
- Hidden SWE-Pro held-out for Accept()

---

## What “done” means for a phase

- All phase steps `done` or `wontfix` in TRACKER  
- Offline review notes captured  
- No open P0/P1 regressions in new REAL cycles  
- BASELINE.md append update
