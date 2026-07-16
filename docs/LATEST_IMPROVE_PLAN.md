# Latest improve plan (from full self-improve cycle)

_Generated 2026-07-16 · Grok 4.5 hard-apply worker_

Model: `grok-4.5` · sources: IMPROVE_OURS top repos + arXiv multi-agent communication stack  
Prior landings: spine board rank · openrouter pattern · improve_spine dual-write

---

## 1. Goal

Close the **next open** items after spine-aware board ranking:

1. **Spine method on decision_package evidence_refs** — durable grader method/run_id cited in apply decisions (2511.15755 + Thucy).
2. **Pattern catalog: MisterSmith + Solace mesh** — supervised runtime hard-caps + event journal/eval mesh skills (pattern only).
3. **Gated live Grok judge integration test** — offline by default; enable with `NEXUS_LIVE_GROK_JUDGE=1`.

## 2. Evidence (repos + papers)

| Source | Score / id | Pattern to port |
|--------|------------|-----------------|
| MattMagg/MisterSmith | 14–16 | Supervised actors, hard caps, CLI inspect |
| SolaceLabs/solace-agent-mesh | 15 | Event mesh, handoff, eval matrix |
| codingagentsystem/cas | 15 | Durable grade on operator board |
| choihyunsus/soul | 14–15 | Immutable method/run evidence |
| wheattoast11/openrouter-deep-research-mcp | 15 | Circuit breakers (already landed) |
| labsai/EDDI | 17 | Config routing (already landed) |
| arXiv 2511.15755 | decision package | Method + path evidence package |
| arXiv 2512.03278 | Thucy | Path-anchored claims + method provenance |
| arXiv 2510.13343 | AOAD-MAT | Ordered grade→decide→apply |
| arXiv 2401.07324 | multi-LLM tools | Opt-in live judge path |
| arXiv 2203.08975 | communication survey | Mesh handoff / journal events |

## 3. Non-goals

- No vendoring of MisterSmith / solace-agent-mesh monorepos.
- No live network in default unit tests; Grok judge remains env-gated.
- No auto-promote to main without explicit flags.

## 4. Landed this cycle (First apply slice)

| Item | Module | Status |
|------|--------|--------|
| `spine_evidence_refs()` + candidate spine_method | `src/nexus/apply_select.py` | ✅ |
| Decision package evidence_refs cite method/run | `gate_apply` / `decision_for_grade` | ✅ |
| Pattern `mistersmith-runtime-ops` | `src/nexus/worktree_apply.py` | ✅ |
| Pattern `solace-mesh-events-ops` | `src/nexus/worktree_apply.py` | ✅ |
| Live Grok judge gated test | `tests/test_mcp_eval.py` | ✅ |
| Tests | `test_apply_select`, `test_worktree_apply`, `test_mcp_eval` | ✅ |

### Success criteria (checked)

- [x] Candidate with spine grade exposes `spine_method` / `spine_run_id` on select rows.
- [x] `gate_apply` evidence_refs include `spine:method:…` and `spine:run:…` when on spine.
- [x] Offline fixtures without spine still produce path-only evidence_refs.
- [x] `mistersmith-runtime-ops` and `solace-mesh-events-ops` validate offline in sandbox.
- [x] Live Grok judge test skips without `NEXUS_LIVE_GROK_JUDGE=1`.
- [x] `pytest` green: **498 passed, 1 skipped**.

## 5. First apply slice (this session)

```
mine digests / fixtures
  → improve_spine grades (method + run_id)
  → select_candidates(use_spine=True)
      row.spine_method / spine_run_id
  → gate_apply / decision_package
      evidence_refs += spine:method:… spine:run:…
  → optional pattern apply:
      mistersmith-runtime-ops | solace-mesh-events-ops
  → optional: NEXUS_LIVE_GROK_JUDGE=1 pytest …live_grok…
```

## 6. Next open

- Wire `decision_package(use_spine=…)` CLI flag through select defaults.
- Prefer spine method in `format_board` / `format_selection` text lines.
- Optional live Grok judge in `make eval-samples` nightly (not default CI).
- More pattern catalog (agent-fleet / zenith gap board skill).

## 7. Commands

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m pytest -q tests/test_apply_select.py tests/test_worktree_apply.py tests/test_mcp_eval.py
PYTHONPATH=src python3 -m nexus.cli improve apply --mode sandbox --pattern mistersmith-runtime-ops --no-require-decision
PYTHONPATH=src python3 -m nexus.cli improve apply --mode sandbox --pattern solace-mesh-events-ops --no-require-decision
# live (opt-in):
NEXUS_LIVE_GROK_JUDGE=1 PYTHONPATH=src python3 -m pytest -q tests/test_mcp_eval.py::test_live_grok_judge_gated_integration
```
