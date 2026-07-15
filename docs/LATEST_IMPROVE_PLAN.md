# Latest improve plan (from full self-improve cycle)

**Applied this session (Grok 4.5 CLI hard-apply):** First apply slice from the cycle plan — P0.4 + P0.5.

## First apply slice — DONE (P0.4 + P0.5)

**Title:** `durability: principled stop (zenith) + independent verify before promote`

| Deliverable | Path |
|-------------|------|
| PrincipledStop + gap board + no-progress thrash | `src/nexus/durability/stop.py` |
| IndependentVerify + promote_taint/memory_verified | `src/nexus/durability/verify_promote.py` |
| Alive stop knobs + cycle record + watch exit | `src/nexus/alive.py` |
| Package exports | `src/nexus/durability/__init__.py` |
| Tests | `tests/durability/test_stop.py`, `test_verify_promote.py`, `tests/test_usage_alive.py` |
| Cycle docs | `docs/SELF_IMPROVE_CYCLE.md`, this file, `docs/ALIVE_IMPROVEMENTS.md` |

### Acceptance

- [x] Register / close / reopen gaps; empty board does **not** premature-stop
- [x] Stop on all gaps closed (when ≥1 gap registered)
- [x] Stop after `max_no_progress` consecutive cycles without progress
- [x] Stop on max_cycles / budget / abort; optional tests-red
- [x] Persist stop board to `.nexus_state/alive_stop.json`
- [x] `cycle_progressed` heuristic for alive reports
- [x] Independent verifier must differ from implementer (unless degraded allowed)
- [x] Score ≥ PASS_THRESHOLD + optional decision/evidence gates
- [x] `promote_taint_verified` / `promote_memory_verified` refuse when verify fails
- [x] Gate audit string `verify:<gate>:<verifier>`
- [x] Existing durability + engine + alive tests still pass

### Evidence drivers

- **Mine:** `Intelligent-Internet/zenith` — gap-finding, stopping discipline, independent validation
- **Also ranked:** cycgraph (eval-gate / promote), mission-control / routa / MisterSmith (ops)
- **arXiv:** adversarial hierarchy 2303.16641; principle-based multi-agent 2502.07165
- **Pattern only** — no vendored upstream tree

### Immediate next PR

| ID | Item | Notes |
|----|------|-------|
| P1.x | Wire gap board from IMPROVE_OURS backlog ids | Auto-register open P0 rows into `PrincipledStop` |
| P1.x | Engine step hook for `IndependentVerify` on review→promote | Optional meta flag |
| P2.x | Multi-harness skillpack export (wshobson/agents) | Docs/skill only |

---

## Prioritized backlog

### P0 — Prove the loop

| Item | Status |
|------|--------|
| P0.1 Budgets | **done** (`durability/budgets.py` + engine max_steps/tokens/wall) |
| P0.2 Taint labels | **done** (`durability/taint.py`) |
| P0.2b Zero-trust state slice | **done** (`durability/state_slice.py`) |
| P0.3 Eval-gated memory write | **done** (`durability/eval_memory.py`) |
| P0.4 Principled stopping | **done this session** (`durability/stop.py` + alive) |
| P0.5 Independent verify on promote | **done this session** (`durability/verify_promote.py`) |

### P1–P11 operator / durability (landed)

See `docs/SELF_IMPROVE_CYCLE.md` for full status. Atomic checkpoints, handoffs, replay/explain, cost, prov/verify, graph, evidence, HITL resume, wall budget, norms, RunBudget/Taint/DurableAgent/StateSlice/EvalMemory are **done**.

---

*Hard-apply session: 2026-07-15 · Grok 4.5 CLI · pytest green*
