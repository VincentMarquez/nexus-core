# Latest improve plan (from full self-improve cycle)

_Generated 2026-07-16 · Grok 4.5 hard-apply worker_

Model: `grok-4.5` · sources: IMPROVE_OURS top repos + arXiv tool-use / multi-agent stack  
Prior landings: improve_spine dual-write · work_ledger gates · preference→context_pack

---

## 1. Goal

Close the **next open** items after spine wire + dual-write:

1. **Spine-aware board ranking** — durable `improve_spine` grades boost select/board rank and can surface repos missing from offline fixtures.
2. **OpenRouter research pattern** — pattern-catalog skill for circuit-breaker protected research/grade loops (no tree vendor).
3. Keep live Grok judge **opt-in / gated** (env-configured; unit tests stay offline).

## 2. Evidence (repos + papers)

| Source | Score / id | Pattern to port |
|--------|------------|-----------------|
| codingagentsystem/cas | 15+ | SQLite context + board rank inputs |
| choihyunsus/soul | 14–15 | Immutable grade presence on operator surfaces |
| wheattoast11/openrouter-deep-research-mcp | 15 | Circuit breakers on research/grade |
| labsai/EDDI | 17 | Config-driven routing (already landed) |
| builderz-labs/mission-control | 15 | Operator board / spend gates |
| arXiv 2604.03350 | multi-stage | Prefer checkpointed grades over re-ingest |
| arXiv 2510.13343 | AOAD-MAT | Ordered mine→grade→apply decisions |
| arXiv 2508.08322 | context eng | Board as compact operator context |
| arXiv 2602.04518 | preference | Prefer pairs still bias rank (orthogonal to spine) |

## 3. Non-goals

- No vendoring of openrouter / EDDI / cas monorepos.
- No live network in unit tests; Grok judge remains env-gated.
- No auto-promote to main without explicit flags.

## 4. Landed this cycle (First apply slice)

| Item | Module | Status |
|------|--------|--------|
| Spine boost in `rank_score` / `select_candidates` | `src/nexus/apply_select.py` | ✅ |
| Board + CLI `--no-spine` / `--run-id` | `cli.py`, `format_board` | ✅ |
| Pattern `openrouter-research-ops` | `src/nexus/worktree_apply.py` | ✅ |
| Tests | `test_apply_select.py`, `test_worktree_apply.py` | ✅ |

### Success criteria (checked)

- [x] Candidate with spine grade ranks higher than same grade without spine.
- [x] `use_spine=False` disables boost (fail-open for fixtures-only demos).
- [x] Board text shows `spine=` for on-spine candidates.
- [x] `openrouter-research-ops` validates offline in worktree sandbox.
- [x] `pytest` green for touched modules; full suite green.

## 5. First apply slice (this session)

```
mine digests / fixtures
  → improve_spine grades (durable)
  → select_candidates(use_spine=True)
      rank = score + evidence + preference + spine_boost
  → improve board / decide / worktree apply gates
  → optional pattern apply: openrouter-research-ops
```

## 6. Next open

- Gated live Grok judge integration test (skip without API key).
- More pattern catalog (MisterSmith supervised runtime, solace mesh events).
- Prefer spine method metadata in decision_package evidence_refs.

## 7. Commands

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_apply_select.py tests/test_worktree_apply.py
PYTHONPATH=src python3 -m nexus.cli improve board --fixture fixtures/mine_eval/grades_with_claims.json
PYTHONPATH=src python3 -m nexus.cli improve apply --mode sandbox --pattern openrouter-research-ops --no-require-decision
```
