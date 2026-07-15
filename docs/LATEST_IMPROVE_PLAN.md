# Latest improve plan (from full self-improve cycle)

**Applied this session (Grok 4.5 CLI hard-apply):** First apply slice from the cycle plan.

## First apply slice — DONE (P0.3)

**Title:** `durability: eval-gated memory write (cycgraph verified-lessons)`

| Deliverable | Path |
|-------------|------|
| EvalGate + GatedMemoryWriter + trial/retained ns | `src/nexus/durability/eval_memory.py` |
| Package exports | `src/nexus/durability/__init__.py` |
| Tests (spine + sqlite + promote/outcome) | `tests/durability/test_eval_memory.py` |
| Cycle docs | `docs/SELF_IMPROVE_CYCLE.md`, this file, `docs/ALIVE_IMPROVEMENTS.md` |

### Acceptance

- [x] Score ≥ `PASS_THRESHOLD` (0.7) → retained memory (`kind=lesson`)
- [x] Score below min → trial namespace (`…/trial`, `kind=trial`) when `allow_trial`
- [x] `allow_trial=False` → soft deny or `MemoryWriteDenied` (raise_on_deny)
- [x] Missing score fails closed by default
- [x] `promote(gate_reason=…)` force-retains with audit reason (mirrors taint.promote)
- [x] `record_outcome` re-checks score and may promote trial → retained
- [x] Works with both `MemorySpine` and `SqliteMemory`
- [x] `EvalGate.from_meta` / nested `eval_gate` for task.meta opt-in
- [x] Existing durability + engine tests still pass

### Evidence drivers

- **Mine:** `wmcmahan/cycgraph` — eval-gated retention (verified lessons; poisoned facts evicted on outcome)
- **Also ranked:** mission-control quality gates, routa evidence, soul/praktor hybrid memory, lumen durability
- **Judge alignment:** `nexus.judge.PASS_THRESHOLD` / `REVISE_THRESHOLD`
- **Pattern only** — no vendored upstream tree

### Immediate next PR

| ID | Item | Notes |
|----|------|-------|
| P0.4 | Principled stopping (zenith) | Gap review + stop discipline in alive loop |
| P0.5 | Independent verify before promote | Separate judge path before taint→trusted / memory promote |

---

## Prioritized backlog

### P0 — Prove the loop

| Item | Status |
|------|--------|
| P0.1 Budgets | **done** (`durability/budgets.py` + engine max_steps/tokens/wall) |
| P0.2 Taint labels | **done** (`durability/taint.py`) |
| P0.2b Zero-trust state slice | **done** (`durability/state_slice.py`) |
| P0.3 Eval-gated memory write | **done this session** (`durability/eval_memory.py`) |
| P0.4 Principled stopping | open (zenith) |
| P0.5 Independent verify on apply | open |

### P1–P11 operator / durability (landed)

See `docs/SELF_IMPROVE_CYCLE.md` for full status. Atomic checkpoints, handoffs, replay/explain, cost, prov/verify, graph, evidence, HITL resume, wall budget, norms, RunBudget/Taint/DurableAgent/StateSlice are **done**.

---

*Hard-apply session: 2026-07-15 · Grok 4.5 CLI · pytest green*
