# Latest improve plan (from full self-improve cycle)

**Source:** Grok 4.5 graded mine + arXiv research (EVIDENCE)  
**Target:** `/path/to/nexus-core`  
**Generated / hard-apply session:** 2026-07-15 (Grok 4.5 CLI worker)

---

## Landed this session — First apply slice **promote-to-main (P0.1 deepen)**

| Item | Module | Status |
|------|--------|--------|
| Prior: durable MCP context + verify-before-done | `context_store.py` / `demo-loop` | **done** (prior) |
| Prior: worktree-isolated apply (P0.5) | `worktree_apply.py` | **done** (prior) |
| **Promote verified pack worktree → main** | `worktree_apply.promote_to_main` | **done this session** |
| PROMOTE_STAGES | `stages.py` | **done** |
| CLI | `nexus improve apply --promote` · `nexus improve promote` | **done** |
| Tests | `tests/test_worktree_apply.py` (+ stage order) | **done** |

### What promote-to-main does

1. After worktree apply + structural verify, optional **promote** stage copies **only allowlisted** pattern files onto main.
2. Fail-closed: worktree must verify; worktree path must sit under `.nexus_workspaces/apply_worktrees/`; refuses overwrite of differing main content unless `--force` / `--promote-force`.
3. Identical content is **idempotent** (skipped_same).
4. **Re-verifies on main** after copy (independent verify-before-promote — zenith/cycgraph pattern).
5. Writes `skillpacks/<pack>/PROMOTE_META.json` audit marker; ledger row `agent=promote` / `action=promote_to_main`.
6. Isolation invariant still holds **during** apply (`main_untouched`); main only changes at the explicit promote step.

### Acceptance

- [x] Apply without `--promote` never writes pack onto main
- [x] `--promote` lands pack + PROMOTE_META; main re-verify ok
- [x] Conflicting main content denied without force
- [x] Force overwrite works; idempotent re-promote of same content ok
- [x] Promote refused for paths outside apply_worktrees root
- [x] Stages: cannot promote before apply; PROMOTE_STAGES = APPLY + promote
- [x] No whole upstream tree vendored

### Commands

```bash
# Isolated apply only (main clean)
PYTHONPATH=src python3 -m nexus.cli improve apply \
  --fixture tests/fixtures/mine_eval_sample.json --mode sandbox

# Apply + promote onto main
PYTHONPATH=src python3 -m nexus.cli improve apply \
  --fixture tests/fixtures/mine_eval_sample.json --mode sandbox --promote

# Two-step: keep worktree, then promote
PYTHONPATH=src python3 -m nexus.cli improve apply --mode sandbox --keep --run-id job1
PYTHONPATH=src python3 -m nexus.cli improve promote --job-id job1

PYTHONPATH=src python3 -m pytest -q tests/test_worktree_apply.py tests/test_stage_order.py
```

---

## Evidence sources (this cycle)

### Mined repos (IMPROVE_OURS, score ≥ 10)

| Repo | Score | Pattern used |
|------|------:|--------------|
| codingagentsystem/cas | 15–16 | worktree isolation + promote boundary |
| automagik-dev/forge | 14–15 | worktree apply isolation |
| Intelligent-Internet/zenith | 15.0 | verify-before-done / promote |
| wshobson/agents | 16.0 | Markdown skill SoT pack (demo pattern) |
| ahmedEid1/lumen | 15.0 | audit / idempotent keys |
| Sompote/tiger_cowork | 13.0 | path safety jail |
| builderz-labs/mission-control | 15.0 | CLI operator surface |

### arXiv (control-plane steals)

| id | Idea → NEXUS |
|----|----------------|
| **2510.13343** | AOAD-MAT ordered stages (`PROMOTE_STAGES`) |
| **2512.03278** | Thucy claim/evidence before promote |
| **2511.15755** | deterministic audit / promote meta |
| **2310.12670** | checkpoint isolation before merge |
| **2302.10809** | decision log (ledger promote row) |

---

## Prioritized backlog (remaining)

### Done spine

- P0 ledger / stages / claim_verify / smoke / worktree apply / **promote-to-main**
- Durable context_store demo-loop + verify-before-done
- P1.x ops / DAG / consensus / context_pack / vault
- P2.x skillpacks / tool catalog / mcp_eval / promote gates

### Next open (small)

| Item | Notes |
|------|--------|
| **Wire improve apply/promote into alive** | When self_approve lands, optional promote with budget |
| **More pattern catalog entries** | cas supervisor marker, soul handoff stub (still no tree vendor) |
| **Grok re-grade of real mined apply** | After promote, re-score via mine_eval |
| **Git worktree outside repo** | Nested git worktree add still fragile; sandbox default |

### Explicit non-goals (still)

- No vendoring whole scout_repos trees
- No force-push / no secrets in ledger
- No full TUI / mission-control dashboard clone

---

## Loop mantra

*mine → grade (Grok) → claim-verify → ledger → worktree apply → **promote** → re-grade → demo.*

Every apply writes only inside an isolated worktree until an explicit promote step copies verified artifacts to main.
