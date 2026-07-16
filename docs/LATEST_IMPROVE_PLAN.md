# Latest improve plan (from full self-improve cycle)

_Generated 2026-07-16 · Grok 4.5 hard-apply worker_

Model: `grok-4.5` · sources: IMPROVE_OURS top repos (EDDI / wshobson / soul / cas / mission-control / …) + arXiv notes under `.nexus_state/arxiv_improve/`

---

## Goal

Self-improve nexus-core from mined repos + arXiv using Grok 4.5 for grading, reasoning, and hard apply. Prefer small, tested pattern ports (not vendored trees). Keep `pytest` green.

## Evidence base

- **Mined repos** (score ≥ 10): see `.nexus_state/repo_mine/IMPROVE_OURS.md` (wshobson/agents, mission-control, soul, cas, EDDI, zenith, AssetOpsBench, …)
- **arXiv**: preference IRL **2602.04518**, context engineering **2508.08322**, decision package **2511.15755**, anti-collusion **2601.00360**, interleaved invariants **1301.6431**, CEMA **2302.10809**, Thucy **2512.03278**
- **Prior landed**: work_ledger dual-control + decision packet; decision→worktree_apply; board signals; grade ledger; durable context; skillpacks; MCP eval; preference pairs + rank boost

## Priority backlog

| ID | Item | Status |
|----|------|--------|
| P0.1 | Wire `work_ledger` accept into `worktree_apply` / alive `self_approve` | DONE (prior) |
| P0.2 | MCP `work_ledger` tools | DONE (prior) |
| P0.3 | Interleaving invariants on worker transitions | DONE (prior) |
| P1.1 | Preference brief → context_pack | **DONE this slice** |
| P1.2 | More pattern catalog entries from IMPROVE_OURS | **DONE this slice** (`soul-work-ledger-ops`) |
| P1.3 | Multi-worker interleaving stress | **DONE this slice** |
| P2 | Live Grok judge gated integration (no unit-test network) | open |
| P2.1 | alive auto `record_from_ranked` when board ranks | open |

## First apply slice (this session)

**Prove:** offline preference pairs inject into bounded context packs so apply/resume agents see value-system bias (arXiv 2602.04518) without a live IRL trainer.

### Landed

1. **`src/nexus/context_pack.py`**
   - `preference` section budget + priority (after grade, before research)
   - `load_preference_section()` — brief + optional focus `preference_boost` for grade repo
   - `build_context_pack(include_preference=True)` / `pack_from_grade(..., include_preference=True)`
   - empty store → section omitted (budget-friendly)
2. **`src/nexus/engine.py`** — `context_pack(..., include_preference=)`; task meta `context_preference` override
3. **`src/nexus/cli.py`** — `nexus task context --no-preference`; `nexus improve select --no-preference`
4. **`src/nexus/mcp_server.py`** — `context_pack` tool arg `preference` (default true)
5. **`src/nexus/worktree_apply.py`** — pattern catalog `soul-work-ledger-ops` (choihyunsus/soul)
6. **Tests:** preference→pack, multi-worker interleaving stress, soul pattern verify

### Success criteria

- [x] Preference pairs appear in `context_pack` section `preference` when store non-empty
- [x] Focus repo boost annotated when grade.repo matches pair leaderboard
- [x] `--no-preference` / `include_preference=False` omits section
- [x] Empty preference store omits section (no budget waste)
- [x] Pattern catalog includes `soul-work-ledger-ops` and validates in sandbox worktree
- [x] Two concurrent workers: dual-control accept ok; collusion + illegal jump fail
- [x] `pytest` green

### Non-goals

- No live IRL trainer / network preference learning
- No vendored monorepos
- No auto-promote without flags

## Patterns ported (shape only)

- arXiv 2602.04518 — preference / value-system brief into agent context
- arXiv 2508.08322 — bounded multi-source context engineering
- choihyunsus/soul — immutable work ledger operator skill pack
- codingagentsystem/cas / mission-control — catalog + CLI/MCP parity
- arXiv 1301.6431 — multi-worker interleaving refusal
- arXiv 2601.00360 — dual-control anti-collusion under concurrent appliers

## Next open

1. Alive auto `record_from_ranked` when board ranks with margin
2. Live Grok judge gated integration (opt-in, no unit-test network)
3. More pattern catalog (EDDI config middleware, openrouter breaker skill)
