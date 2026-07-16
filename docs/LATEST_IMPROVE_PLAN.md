# Latest improve plan (from full self-improve cycle)

_Generated 2026-07-16 · Grok 4.5 hard-apply worker_

Model: `grok-4.5` · sources: IMPROVE_OURS top repos (EDDI / wshobson / soul / cas / mission-control / …) + arXiv notes under `.nexus_state/arxiv_improve/`

---

## Goal

Self-improve nexus-core from mined repos + arXiv using Grok 4.5 for grading, reasoning, and hard apply. Prefer small, tested pattern ports (not vendored trees). Keep `pytest` green.

## Evidence base

- **Mined repos** (score ≥ 10): see `.nexus_state/repo_mine/IMPROVE_OURS.md` (wshobson/agents, mission-control, soul, cas, EDDI, zenith, AssetOpsBench, …)
- **arXiv**: communication **2203.08975**, decision package **2511.15755**, anti-collusion **2601.00360**, interleaved invariants **1301.6431**, CEMA **2302.10809**, Thucy **2512.03278**, AOAD-MAT **2510.13343**
- **Prior landed**: work_ledger dual-control + decision packet; decision→worktree_apply; board signals; grade ledger; durable context; skillpacks; MCP eval

## Priority backlog

| ID | Item | Status |
|----|------|--------|
| P0.1 | Wire `work_ledger` accept into `worktree_apply` / alive `self_approve` | **DONE this slice** |
| P0.2 | MCP `work_ledger` tools (status/tail/chain/gate/first_slice) | **DONE this slice** |
| P0.3 | P0.5 interleaving invariants on worker transitions | **DONE this slice** |
| P1.1 | Preference brief → context_pack | open |
| P1.2 | More pattern catalog entries from IMPROVE_OURS | open |
| P2 | Live Grok judge gated integration (no unit-test network) | open |

## First apply slice (this session)

**Prove:** mine → grade → work_ledger dual-control accept → worktree apply / alive self_approve fail-closed without accept.

### Landed

1. **`src/nexus/work_ledger.py`**
   - `LEGAL_SUCCESSORS` + `assert_legal_transition` (illegal interleaving refused)
   - `ensure_apply_gate()` resume-safe mine→grade→decision→propose→accept|reject
   - `work_ledger_status()` for operator/MCP
2. **`src/nexus/worktree_apply.py`**
   - `require_work_ledger` (default follows `require_decision`)
   - after decision package, require work_ledger `apply_accepted` before plan_apply
3. **`src/nexus/alive.py`**
   - `require_work_ledger` knob; `_self_approve_work_ledger_gate` in decision gate
4. **`src/nexus/mcp_server.py`** + **`tool_catalog.py`**
   - MCP tool `work_ledger` (status|tail|chain|gate|first_slice|transitions), privilege `ops`
5. **Tests:** `test_work_ledger`, `test_worktree_apply`, `test_usage_alive`

### Success criteria

- [x] Illegal `mine → apply_accepted` raises `TransitionError`
- [x] `run_apply` records work_ledger accept for wshobson/agents
- [x] Colluding grader==applier denies work_ledger even when decision skipped
- [x] Alive self_approve gate accepts with fixture + work_ledger; knobs round-trip
- [x] MCP tool listed and chain/status callable
- [x] `pytest` green

### Non-goals

- No vendored monorepos
- No auto-promote without flags
- No live network in unit tests

## Patterns ported (shape only)

- choihyunsus/soul — immutable work ledger
- codingagentsystem/cas / mission-control — SQLite control plane + CLI/MCP
- arXiv 2601.00360 — dual-control anti-collusion
- arXiv 1301.6431 — illegal transition refusal
- arXiv 2511.15755 — deterministic decision packet
- zenith — fail-closed before hard apply

## Next open

1. Preference brief injection into `context_pack`
2. Wire board replan signal volume into improve gap seed docs
3. Optional real multi-worker interleaving stress (two appliers)
