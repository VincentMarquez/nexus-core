# Latest improve plan (from full self-improve cycle)

**Applied this session (Grok 4.5 CLI hard-apply):** First apply slice from the cycle plan.

## First apply slice — DONE

**Title:** `durability: per-run budgets + taint labels (cycgraph pattern)`

| Deliverable | Path |
|-------------|------|
| Run budget (steps/tokens/cost) | `src/nexus/durability/budgets.py` |
| Taint labels + promote gate | `src/nexus/durability/taint.py` |
| Step wrapper (pre-budget + post-taint) | `src/nexus/durability/durable_agent.py` |
| Engine wire: `meta.max_steps` hard-stop | `src/nexus/engine.py` (`task_max_steps`, `task_run_budget`) |
| Tests | `tests/durability/*`, `tests/test_engine.py::test_task_max_steps_hard_stop` |

### Acceptance

- [x] Exceeding `max_steps` raises `BudgetExhausted` (DurableAgent) or fail-closed task status (engine `meta.max_steps`)
- [x] Mined-path writes labeled `mined`; not readable as `trusted` without `promote(gate=…)`
- [x] Existing resume/checkpoint tests still pass
- [x] New tests green in isolation

### Evidence drivers

- **Mine:** `wmcmahan/cycgraph` (score 14.0) — budgets, taint, zero-trust state
- **Papers:** 2303.16641 (adversarial hierarchy), 2601.00360 (anti-collusion / independent verify later)
- **Pattern only** — no vendored upstream tree

### Env defaults

- `NEXUS_MAX_STEPS`, `NEXUS_MAX_TOKENS` / `NEXUS_MAX_TOKENS_RUN`, `NEXUS_MAX_COST` / `NEXUS_MAX_COST_USD`

### Immediate next PR

**P0.4 + P0.5:** zenith-style gap review / principled stop in `cli_alive` + independent verify before memory promote.

---

## Prioritized backlog (unchanged priorities)

### P0 — Prove the loop

| Item | Status |
|------|--------|
| P0.1 Budgets | **done** (`durability/budgets.py` + engine max_steps/tokens/wall) |
| P0.2 Taint labels | **done** (`durability/taint.py`); full zero-trust policy engine still open |
| P0.3 Eval-gated memory write | open (promote API exists; wire memory path) |
| P0.4 Principled stopping | open (zenith) |
| P0.5 Independent verify on apply | open |

### P1–P2

See `docs/SELF_IMPROVE_CYCLE.md` for full DAG/handoff/governance/evidence backlog.

---

*Hard-apply session: 2026-07-15 · Grok 4.5 CLI · pytest green*
