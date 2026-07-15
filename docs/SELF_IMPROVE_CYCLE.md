# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 · updated after First apply slice: board signal → gap board + preference pairs_

## Goal

Self-improve **nexus-core** from mined GitHub repos + arXiv multi-agent papers using Grok 4.5 for grading, reasoning, and hard apply. Prefer small, tested ports of **patterns** (not whole upstream trees). Keep `pytest` green.

## Loop (ordered)

1. **Research** — arXiv query → notes under `.nexus_state/arxiv_improve/`
2. **Mine** — scout repos → digests → Grok grades → `IMPROVE_OURS.md`
3. **Select** — FTS evidence rank + role gate (`nexus improve select|board|decide`)
4. **Decide** — terminal decision package (claims + evidence + confidence) **2511.15755**
5. **Signal** — board `continue|replan|stop` → PrincipledStop gap board (zenith / MAEBE)
6. **Prefer** — offline better>worse pairs (**2602.04518**) for later rank bias
7. **Apply** — worktree-isolated pattern apply; decision required by default
8. **Verify / promote** — skillpack validate; optional promote-to-main; independent verify
9. **Alive** — budgeted cycle; self_approve only after board signal **continue**

## Board signals → gap board

| Signal | Gap board effect |
|--------|------------------|
| `continue` | Close `board-replan` / `board-stop` (and reason-scoped children) |
| `replan` | Register `board-replan` (+ optional `board-replan:<reason>`) |
| `stop` | Register `board-stop`; hard stops (collusion/budget/principled) may **abort** so `alive watch` exits |

## Key modules

| Module | Role |
|--------|------|
| `apply_select.py` | select, gate, decision_package, board_signal, **sync_signal_to_stop** |
| `preference_pairs.py` | offline better>worse pairs + boost/brief |
| `worktree_apply.py` | isolated apply + pattern catalog (incl. cas-evidence-board-ops) |
| `alive.py` | cycle + self_approve decision gate + gap sync |
| `evidence_fts.py` | MCP SQLite FTS evidence |
| `durability/*` | budgets, taint, stop, verify_promote, eval_memory, gap_seed |

## Hard rules

- No force-push; no secrets; no vendoring whole trees
- Prefer patterns from `.nexus_workspaces/scout_repos/`
- Update `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md` on behavior change
- `PYTHONPATH=src python3 -m pytest -q` must stay green

## Commands

```bash
nexus improve board --sync-gaps
nexus improve prefer list
nexus improve decide --repo wshobson/agents
nexus improve apply --mode sandbox
nexus alive once   # self_approve only if alive.json apply+self_approve and board continues
make test
```
