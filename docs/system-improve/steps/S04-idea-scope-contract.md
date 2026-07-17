# S04 — Idea / cycle scope contract

| Field | Value |
|-------|--------|
| Status | **done** (2026-07-17) |
| Phase | P2 |
| Risk | Medium → low after dual review (opt-in default false) |
| Depends on | S01, S03 — done |
| Primary files | `src/nexus/scope_contract.py`, `idea_portfolio.py`, `critique_panel.py`, `alive.py` |
| Tests | `tests/test_scope_contract.py` |

---

## Problem

Ideas lack a **machine-readable contract**. Grok and the panel only get free text (“concrete change”), so:

- Scope drifts (whole dirty tree was one symptom — S01 fixed the *diff* side)
- Non-goals are forgotten mid-session
- Success is “worker returned,” not “contract met”
- Publish cannot intersect “what this idea was allowed to touch”

This is the same *kind* of problem you solved in **Bubbles** and **NEXUS DNA**: every agent had mandatory structure / preamble — not optional vibes.

---

## Lineage (your prior designs)

### A. Bubbles network — structural DNA

Every agent subclassed **`UniversalBubble`** (`bubbles_core.py`). Constructor **required**:

| Required | Role |
|----------|------|
| `object_id: str` | Identity (non-empty) |
| `SystemContext` | Shared bus: dispatcher, resources, chat |
| Event queue + loop | `handle_event` / `autonomous_step` / start-stop |
| Registration | `context.register_bubble(self)` |

You could not spawn a random free-form agent without that DNA. Specialists (PPO, RAG, QFD, …) **inherited** it.

### B. NEXUS AGENT DNA — prompt DNA (D*=0)

File: `lab workspace/AGENT_DNA.md`  
Injection: `nexus_dna_patch.py` + `patch_dna_into_runpy.py`

| Rule | Meaning |
|------|---------|
| First in every prompt | `<NEXUS_DNA>…</NEXUS_DNA>` before spectral memory / RAG |
| Every agent, no exceptions | Single source of truth |
| Must read `~/nexus_index.json` | Navigate by index cascade (D*=1 → …) |
| Last peeled | Highest survival in attention |

Boot order you designed:

1. NEXUS DNA  
2. Spectral Memory (banned approaches, lessons)  
3. Graph RAG  
4. Exec context  
5. Cascade index  
6. D* scorecard  

### C. SARSI — contract DNA (paper)

Every agent has: **goal contract, scope, tool registry, benchmarks, autonomy, self-model**.  
Promotion is evidence-gated. Design paper, not your code — but same *shape*: mandatory fields, not optional prose.

### How S04 fits

| Prior art | S04 analogue |
|-----------|----------------|
| UniversalBubble required fields | Idea **scope contract** JSON required before implement |
| AGENT_DNA preamble | Contract block prepended to Grok implement + panel pack |
| SARSI goal/scope | `mission`, `allowed_prefixes`, `non_goals`, `success_check` |
| Register bubble | Write contract into critique `MANIFEST.json` + optional ledger field |

S04 is **not** re-building Bubbles. It is **porting the discipline**: every implement unit carries mandatory DNA fields.

---

## Goal (this step only)

Per portfolio **idea** (and thin **cycle** wrapper):

```json
{
  "schema": "nexus.scope_contract/v1",
  "idea_id": "arxiv:2606.07412v1",
  "source": "arxiv",
  "mission": "one sentence",
  "allowed_prefixes": ["src/nexus/", "tests/", "docs/"],
  "forbidden_prefixes": [".venv/", ".nexus_state/", ".env"],
  "non_goals": ["vendor upstream tree", "force-push", "re-implement cooled seed"],
  "success_check": {
    "type": "pytest_paths",
    "paths": ["tests/test_<module>.py"]
  },
  "max_files": 12,
  "max_new_files": 4,
  "owner": "alive_real",
  "created_ts": 0
}
```

Wire:

1. **Build** contract when portfolio idea is selected / at implement start (defaults from source type).  
2. **Inject** into Grok implement goal (DNA block first — Bubbles/NEXUS style).  
3. **Write** into critique pack `MANIFEST.json` + `CONTRACT.json`.  
4. **Intersect** panel slice / optional publish allow with `allowed_prefixes` (soft: warn if outside; hard later with flag).  
5. **Do not** implement full SARSI G0–G4 signing or foundry.

---

## Non-goals

- Full SARSI goal stack / legal signatures  
- Replacing UniversalBubble runtime  
- Requiring human sign-off every idea  
- Blocking implement if contract missing (default: generate defaults — fail-open)  
- Changing portfolio selection (S03 owns cooldown)

---

## Proposed design (for offline review)

### Module

Prefer small pure helper: `src/nexus/scope_contract.py`

| Function | Behavior |
|----------|----------|
| `default_contract(idea) -> dict` | Fill mission from title/concrete; prefixes by source |
| `validate_contract(c) -> list[str]` | Missing fields → warnings (not exceptions by default) |
| `format_dna_block(c) -> str` | Markdown/XML for prompt injection |
| `paths_in_scope(paths, c) -> (ok, out)` | Filter for panel/publish soft gate |
| `write_contract(pack_dir, c)` | CONTRACT.json |

### Defaults by source

| Source | allowed_prefixes (start) |
|--------|---------------------------|
| arxiv / cross_pattern | `src/nexus/`, `tests/`, `docs/` |
| github | same + optionally `plugins/`, `skillpacks/` |
| always forbidden | `.venv/`, `.env`, `.nexus_state/`, secrets patterns |

### Integration points (minimal)

| Call site | Change |
|-----------|--------|
| `implement_portfolio` | Build contract; prepend DNA to `goal` |
| `critique_panel.write_review_pack` | Attach contract fields |
| Optional later | `publish.stage_allowed` ∩ cycle ∩ contract — **not** required for S04 v1 |

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `scope_contract_enable` | `true` | Generate + inject DNA |
| `scope_contract_soft_enforce` | `true` | Log out-of-scope; do not abort |
| `scope_contract_hard_enforce` | `false` | Abort implement if paths escape (future) |

---

## Acceptance criteria

- [ ] Unit tests: default_contract always has required keys  
- [ ] Unit tests: paths_in_scope filters correctly  
- [ ] Unit tests: format_dna_block non-empty and includes idea_id  
- [ ] Implement prompt contains DNA block when enabled  
- [ ] Critique pack writes `CONTRACT.json`  
- [ ] Default does not break implement when idea is sparse  
- [ ] TRACKER → done when landed  

---

## Test plan

```bash
.venv/bin/python -m pytest -q tests/test_scope_contract.py
.venv/bin/python -c "from nexus import scope_contract, idea_portfolio; print('ok')"
```

---

## Rollback

`scope_contract_enable: false` in alive.json, or remove inject call only.

---

## Offline review package

Give reviewers:

1. `docs/system-improve/PRINCIPLES.md`  
2. **This file**  
3. `docs/system-improve/references/BUBBLES_DNA_AND_SARSI.md`  
4. Optional: short SARSI map `references/SARSI_NEXUS.md`

Prompt: `docs/system-improve/OFFLINE_REVIEW.md` (replace Sxx with S04).

Store reviews under:

```text
docs/system-improve/reviews/S04-<model>-YYYY-MM-DD.md
```

---

## Review notes

### Grok offline review (2026-07-17)

**Verdict: approve-with-nits**

| # | Severity | Note |
|---|----------|------|
| 1 | med | Keep v1 **soft-only**; hard enforce is a later step |
| 2 | med | `success_check` pytest paths may not exist yet — allow `type: py_compile` or `manual` |
| 3 | low | Prefer new `scope_contract.py` over bloating `idea_portfolio.py` |
| 4 | low | DNA block should be **short** (≤40 lines) so it survives attention like D*=0 |
| 5 | low | Do not intersect publish in S04 — S02 already cycle-scopes; add intersection in S05/S06 if needed |

**Must-fix before merge (A):** required keys schema; tests; soft inject; CONTRACT.json in pack.  
**Nice (B):** source-specific prefix tables; max_files warning.  
**Out of scope (C):** SARSI signing, foundry, weight training.

### Codex offline review (2026-07-17)

**Verdict: request-changes (plan-level; direction approved)**

- Default `scope_contract_enable` to `false`; wire it through `AliveConfig`, `from_dict`, the REAL call site, and rollback tests.
- Keep allow/deny policy code-owned; normalize paths and bound/encode all untrusted idea data before prompt injection.
- Never filter or drop paths from the complete S01 slice; scope results are advisory observations only.
- Reuse the same contract for every editor claimed as covered, including synthesis, or explicitly narrow and report coverage.
- Keep `success_check` as `not_evaluated`; S04 must make no publish changes or enforcement claims.

Full review: [S04-codex-2026-07-17.md](../reviews/S04-codex-2026-07-17.md).

### Other LLM reviews

- **Grok:** `reviews/S04-grok-2026-07-17.md` — approve-with-nits  
- **GPT (bus):** `reviews/S04-gpt-2026-07-17.md` — **request-changes** (all A items addressed in land)

**Consensus land:**

| GPT must-fix | How we landed |
|---------------|---------------|
| No panel slice intersection | classify only; full `files` retained |
| Synthesis gets contract | `grok_synthesis(..., scope_contract=)` |
| Default enable false | `scope_contract_enable=False` |
| Safe path matching | `_norm_rel` (no `.lstrip("./")` bug); reject `..` |
| Fail-open | try/except → legacy path; never allow-all |
| AliveConfig wiring | field + from_dict + cycle_once pass-through |
| Untrusted text | `_bound` escapes delimiters |
| improve_ours | `contract_injected: false` |
| No publish change | untouched |

---

## Implementation notes

- Module: `src/nexus/scope_contract.py`  
- Enable: `.nexus_state/alive.json` → `"scope_contract_enable": true`  
- DNA is first in **idea goal**, not full worker prompt  

## Done checklist

- [x] Offline reviews (Grok + GPT)  
- [x] Code  
- [x] Tests green (27+ related)  
- [x] TRACKER → done  
- [x] BASELINE append  

