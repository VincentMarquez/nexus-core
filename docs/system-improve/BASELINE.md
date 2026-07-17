# Baseline — clean starting point

**Plan birth:** 2026-07-17  
**Repo:** `~/nexus-core` (product core)  
**Lab bus (ops):** `security-lab/bridge` on `:3099` (not this folder)

This document freezes “where we are” so later deep dives do not rewrite history in chat.

---

## What the product is (operator one-liner)

Research the world (GitHub ≥5K★, arXiv, live X) → engine+judge → idea portfolio → Grok hard-apply → multi-LLM critique panel → tests → optional publish. Lab UI is remote control. North star: coding excellence (SWE-Pro).

## Architecture ownership (do not confuse)

| Layer | Location | Role |
|-------|----------|------|
| Product | `~/nexus-core` | Code that self-improves |
| Lab bus | `security-lab/bridge` `:3099` | Seats / bridges |
| Product bus stub | `nexus-core/bridge/` | Not the live process by default |
| MCP | `:8765` `nexus.mcp_server` | Tools surface (restart after big code changes) |
| Cycle artifacts | `docs/LATEST_*`, `.nexus_state/` | Generated; not the plan |

## Known-good code changes already landed (this plan period)

| ID | Change | Modules | Tests |
|----|--------|---------|-------|
| S01 | Critique slice = strict dirty delta; synthesis-only revert | `critique_panel.py` | `tests/test_critique_panel.py` |
| S02 | Publish stages only paths dirty **after** cycle baseline | `publish.py`, `alive.py` | `tests/test_publish.py` |

**Caveat:** An `alive once` process that started **before** these edits keeps old behavior until it exits. Next process picks up S01/S02.

## Known issues (accepted as backlog, not chaos)

| Issue | Why it hurts | Planned step |
|-------|--------------|--------------|
| Portfolio re-selects top GitHub (e.g. `wshobson/agents`) every REAL | Stateless across runs | **S03** |
| No signed idea/cycle contract (scope, non-goals, success) | Scope creep | S04 |
| Implement `ok` ≠ held-out / proxy quality | Fake progress | S05 |
| REAL hard-applies on main often | Contamination | S06 |
| No cross-run lesson injection | Repeat same failure class | S07 |
| Engine / X fail-open on REAL | “Mandatory” not enforced | S08 |
| `worktree_apply` job_id path jail incomplete | Safety | S09 |
| `.gitignore` `.nexus/` mid-line comment | Hygiene | S10 |
| Panel quorum / timeout E2E | False confidence | later |
| multi_llm run/loop mock registry | Demo honesty | later |

## Explicitly out of scope for v0 of this plan

- Full SARSI Personal Singularity OS
- Weight training / meta-RSI (SARSI stage 8)
- Replacing lab bus with product bus mid-flight
- Auto-running this plan inside REAL

## How to re-baseline later

When a phase completes, add a short “Baseline update” section at the bottom of this file with date + what changed. Do not delete history—append.

### Baseline updates

- **2026-07-17:** Plan folder created; S01/S02 marked done on disk; S03 next.
- **2026-07-17 (later):** Mid-run REAL stopped by operator (~15:07 UTC). **S03** implement ledger + 7-day portfolio cooldown landed; **S10** `.gitignore` `.nexus/` fixed. Ledger path: `.nexus_state/implement_ledger.jsonl`. Next open: **S04**.
- **2026-07-17 (S04):** Dual offline review (Grok approve-with-nits; GPT request-changes). Landed **opt-in** `scope_contract_enable` (default **false**): `scope_contract.py`, DNA in idea goal + panel/synthesis, `CONTRACT.json`, classify without filtering slice. Next: S05/S07 as ready later.
- **2026-07-17 (S05+S07):** Soft accept predicate (`accept_predicate.py`, default on, does not rewrite worker ok). Cross-run lessons ledger + dual_review inject (`cross_run_lessons.py`, default on). Next: S08 / S09 / S11.
- **2026-07-17 (S08+S09):** Soft REAL input gate blocks **publish only** when X/engine not ok (`real_gate_publish` / `real_gate_override`). Worktree `job_id` path jail via `sanitize_job_id` + `safe_path`. **S11 publish harden deferred.**
- **2026-07-17 (S06+S11 — plan complete):** Opt-in `implement_quarantine` (git worktree → promote allowlisted). Publish harden: `status_porcelain_checked`, fail-closed if baseline missing, unstage pre-staged extras before cycle commit. **system-improve v1 spine S01–S11 done.**
- **2026-07-17 (Phase B designed):** Capability factory — **skills + tools**. S12 skill factory (novel procedures / code-review skills → skillpacks). S13 tool factory (new MCP/CLI callables agents can invoke). Creation ≠ activation; quarantine; privilege default read. See `references/SKILLS_AND_TOOLS_FACTORY.md`.
- **2026-07-17 (Phase B Wave A–C landed):** `capability_factory.py` + `factory_tools.py`. Golden skill `code-review-portfolio-slice` **activated** under `skillpacks/`. Read tools invokable: lesson_query, scope_check, skill_search, pack_validate, code_review. CLI: `python -m nexus.capability_factory`.
