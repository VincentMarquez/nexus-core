# Latest improve plan (from full self-improve cycle)

**Applied this session (Grok 4.5 CLI hard-apply):** First apply slice from the cycle plan.

## First apply slice — DONE (P11)

**Title:** `durability: zero-trust state slicing (cycgraph read_keys / write_keys)`

| Deliverable | Path |
|-------------|------|
| StateSlice (view / merge / protect `_` keys) | `src/nexus/durability/state_slice.py` |
| DurableAgent slice enforce + `view()` | `src/nexus/durability/durable_agent.py` |
| Package exports | `src/nexus/durability/__init__.py` |
| Tests | `tests/durability/test_state_slice.py` |
| Engine module doc (P11) | `src/nexus/engine.py` |

### Acceptance

- [x] Empty `read_keys` / `write_keys` → deny-all (zero-trust default)
- [x] Declared keys filter `view()`; undeclared writes raise `SliceError`
- [x] Protected keys (`_…`, `_taint_registry`) never agent-writable (even with `*`)
- [x] Default `DurableAgent` stays backward-compatible (open-all except protected)
- [x] Opt-in via `meta.read_keys` / `meta.write_keys` / `meta.state_slice`
- [x] Existing durability + engine tests still pass

### Evidence drivers

- **Mine:** `wmcmahan/cycgraph` — permission-scoped state (`read_keys`/`write_keys` default `[]`)
- **Also ranked:** mission-control quality gates, routa evidence board, MisterSmith audit
- **Papers:** 2502.14847 (communication attacks → least privilege), 2303.16641 (adversarial hierarchy)
- **Pattern only** — no vendored upstream tree

### Immediate next PR

| ID | Item | Notes |
|----|------|-------|
| P0.3 | Eval-gated memory write | Promote API exists; gate `MemorySpine` / sqlite writes on score |
| P0.4 | Principled stopping (zenith) | Gap review + stop discipline in alive loop |
| P0.5 | Independent verify before promote | Separate judge path before taint→trusted |

---

## Prioritized backlog

### P0 — Prove the loop

| Item | Status |
|------|--------|
| P0.1 Budgets | **done** (`durability/budgets.py` + engine max_steps/tokens/wall) |
| P0.2 Taint labels | **done** (`durability/taint.py`) |
| P0.2b Zero-trust state slice | **done this session** (`durability/state_slice.py`) |
| P0.3 Eval-gated memory write | open (promote API exists; wire memory path) |
| P0.4 Principled stopping | open (zenith) |
| P0.5 Independent verify on apply | open |

### P1–P10 operator / durability (landed)

See `docs/SELF_IMPROVE_CYCLE.md` for full status. Atomic checkpoints, handoffs, replay/explain, cost, prov/verify, graph, evidence, HITL resume, wall budget, norms, RunBudget/Taint/DurableAgent are **done**.

---

*Hard-apply session: 2026-07-15 · Grok 4.5 CLI · pytest green*
