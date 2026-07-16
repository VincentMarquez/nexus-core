# Latest improve plan (from full self-improve cycle)

_Generated 2026-07-16 · Grok 4.5 hard-apply worker_

Model: `grok-4.5` · repos≥10 (IMPROVE_OURS) · arXiv≈20 (rx-2a3280d550 / rx-00eb6c8e07)

## Goal

Self-improve nexus-core from mined repos + arXiv using Grok for grading, reasoning, and hard apply. Prefer small, tested patterns from `.nexus_workspaces/scout_repos/` — never vendor whole trees.

## Landed (prior cycles)

| ID | Slice | Status |
|----|-------|--------|
| P0–P1 | Durability, journal, handoff, veto, cost, provenance, DAG, consensus, context pack | done |
| P2 | Skillpacks, tool catalog, MCP eval packs, Grok/ollama judge | done |
| P3 | Promote gate, work_ledger dual-control, improve_spine, board rank | done |
| First | mine_eval_slice MINED→GRADED→CLAIM_OK→APPLY_CANDIDATE | done (flag-only) |

## First apply slice (this session)

**Close prior open:** plan-slice APPLY_CANDIDATE → worktree_apply dry-run · plan-reuse cache · more sample packs · alive auto `record_from_ranked`

### Implementation

1. **`src/nexus/plan_reuse.py`** — `nexus.plan_reuse/v1` cache under `.nexus_workspaces/plan_reuse/`; fingerprint `(repo, pattern, score_band, method)`; success-only store; `get_or_compute`.
2. **`src/nexus/mine_eval_slice.py`** — APPLY_CANDIDATE runs sandbox `worktree_apply` dry-run (decision/spine/ledger gates off); plan-reuse hit skips rematerialise; `pattern_for_repo` maps IMPROVE_OURS top repos.
3. **`src/nexus/worktree_apply.py`** — pack_id-aware SKILL.md presence check (not hardcoded markdown-sot-demo).
4. **`src/nexus/alive.py`** — auto `record_from_ranked` after mine when ≥2 scored repos (not only self_approve gate).
5. **`fixtures/mcp_eval/packs/improve_board_smoke.json`** — board / apply_select / work_ledger sample scenarios.
6. **CLI** — `nexus improve plan-slice` gains `--no-worktree` / `--no-plan-cache` / `--pattern`.

### Success criteria

- [x] `run_demo_slice` on wshobson/agents → stages complete + worktree dry-run ok
- [x] Second identical slice → `cache_hit=true`
- [x] Pytest green for new modules + existing suite
- [x] No vendored trees; dry-run never promotes to main

### Patterns (shape only)

- wshobson/agents Markdown SoT validate
- cas/forge worktree isolation
- multi-stage plan reuse (arXiv 2604.03350) + context eng (2508.08322)
- preference IRL offline pairs (2602.04518)
- mission-control / AssetOpsBench sample pack smoke

### Non-goals

- No live Grok in unit tests
- No auto-promote without flags
- No Temporal/NATS/full UI

### Next open

- Wire plan-reuse stats into `nexus improve board` / ops spend
- Optional `nexus improve plan-cache` CLI (list/clear)
- Live Grok re-grade after successful worktree dry-run (gated)
- More pattern catalog (routa / apex-accelerator)
