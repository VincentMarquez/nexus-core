# Latest improve plan (from full self-improve cycle)

**Target:** `/path/to/nexus-core`  
**Focus:** multi-agent durability, MCP, mine/alive loops, grading, demos  
**Sources:** Grok-graded mined repos (IMPROVE_OURS) + arXiv research notes under `.nexus_state/arxiv_improve/`  
**Worker:** Grok 4.5 CLI · 2026-07-15

---

## Status snapshot (2026-07-15)

| Tier | Item | Status |
|------|------|--------|
| P0 | Improve-apply phase FSM + decision audit + path jail | **done** (`improve_apply.py`) |
| P0.x | Budgets, taint, state slice, eval memory, stop, verify-promote | **done** (`durability/`) |
| P1.1 | Task/spend ops plane | **done** (`ops_store.py` + `nexus ops`) |
| P1.2 | Multi-agent task DAG | **done** (`steps.py` / `engine.dag`) |
| P1.3 | Consensus / multi-grader path (gossipcat) | **done** (`consensus.py`) |
| P1.4 | Formal context pack stage (arXiv 2508.08322) | **done** (`context_pack.py`) |
| **P1.5** | **Secrets vault + supervised alive gap-board auto-seed** | **done this session** |
| P2 | Packaging, OpenAPI, domain MCP demos (AssetOpsBench) | open |

---

## First apply slice this session — P1.5 vault + gap seed

**Goal:** Supervised *alive* only stops for `gaps_closed` when gaps are registered. Auto-seed the board from plan docs, and give operators an env-first secrets vault that never prints values.

### Landed

| Surface | What |
|---------|------|
| `src/nexus/durability/gap_seed.py` | Parse status tables + Next open; `seed_gap_board` / `collect_plan_gaps` / `board_snapshot` (`nexus.gap_seed/v1`) |
| `src/nexus/alive.py` | `seed_gaps` config (default on); auto-seed in `_record_principled_stop`; helpers `seed_gaps` / `gap_board` / `close_gap` |
| `src/nexus/vault.py` | Env + optional `.nexus_state/vault.local.json`; presence-only `status`; `redact` / `mask_mapping` |
| `src/nexus/cli.py` | `nexus alive gaps [--seed\|--close]`; `nexus vault status\|check\|redact` |
| `src/nexus/mcp_server.py` | tools `gap_board`, `vault_status` (booleans only) |
| tests | `tests/durability/test_gap_seed.py`, `tests/test_vault.py` |

### Acceptance

- [x] Parse open/done rows from `docs/LATEST_IMPROVE_PLAN.md` status table
- [x] Parse **Next open** numbered lists + inline `next open:` trails
- [x] Seed does not reopen operator-closed gaps (unless `--reopen`)
- [x] Plan `done` rows can close matching open board gaps
- [x] Alive cycle auto-seeds when `seed_gaps=true`
- [x] Vault status never embeds secret values
- [x] Redaction masks known values and `KEY=value` patterns
- [x] CLI + MCP parity
- [x] Full pytest green

### Patterns (no tree vendor)

- **Intelligent-Internet/zenith** — gap board + supervised stop (not premature / not infinite)
- **builderz-labs/mission-control** — ops presence / env spend keys
- **ahmedEid1/lumen** — operational shell + env secrets
- **arXiv 2502.07165 / 2203.08975** — principle + communication discipline for multi-agent loops
- **IMPROVE_OURS** top repos (routa / MisterSmith / EDDI) — operator inspect surfaces

### Demo

```bash
PYTHONPATH=src python3 -m nexus.cli alive gaps --seed
PYTHONPATH=src python3 -m nexus.cli alive gaps
PYTHONPATH=src python3 -m nexus.cli alive gaps --close P1.5 --evidence "landed + tests green"
PYTHONPATH=src python3 -m nexus.cli vault status
PYTHONPATH=src python3 -m nexus.cli vault check OPENAI_API_KEY
PYTHONPATH=src python3 -m pytest -q
```

---

## Next open (after this slice)

1. **P2** Packaging / OpenAPI surface for core modules
2. Modularize MCP domains + eval CLI (AssetOpsBench pattern)
3. Agent single-source skillpack marketplace (wshobson/agents generators — pattern only)
4. Board traces / routa-style evidence export polish (already partial via `task evidence`)

---

## Non-goals (still)

- No vendoring of scout_repos trees  
- No force-push / secrets in commits  
- No full mission-control UI rewrite  
- No unbounded dump of full paper PDFs or entire repos into prompts  
- Vault never returns secret *values* over MCP

---

*All patterns are ports of ideas from graded repos and arXiv notes, not wholesale dependency on foreign trees.*
