# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 · updated after First apply slice: decision package → apply + board signals_

## Goal

Self-improve **nexus-core** from mined GitHub repos + arXiv multi-agent papers using Grok 4.5 for grading, reasoning, and hard apply. Prefer small, tested ports of **patterns** (not whole upstream trees). Keep `pytest` green.

## Loop (ordered)

1. **Research** — arXiv query → notes under `.nexus_state/arxiv_improve/`
2. **Mine** — scout repos → digests → Grok grades → `IMPROVE_OURS.md`
3. **Select** — FTS evidence rank + role gate (`nexus improve select|board|decide`)
4. **Decide** — terminal decision package (claims + evidence + confidence) **2511.15755**
5. **Apply** — worktree-isolated pattern apply; decision required by default
6. **Verify / promote** — skillpack validate; optional promote-to-main; independent verify
7. **Alive** — budgeted cycle; self_approve only after board signal **continue**

## Board signals (zenith / MAEBE)

| Signal | Meaning |
|--------|---------|
| `continue` | Decision allow + roles ok → hard apply permitted |
| `replan` | No candidates / soft deny / low confidence → do not apply; adjust backlog |
| `stop` | Role collusion / budget / principled stop → halt apply thrash |

## Key modules

| Module | Role |
|--------|------|
| `apply_select.py` | select, gate, decision_package, board_signal |
| `worktree_apply.py` | isolated apply + decision gate + promote |
| `alive.py` | cycle + self_approve decision gate |
| `evidence_fts.py` | MCP SQLite FTS evidence |
| `grade_artifact.py` | Thucy claims + grade schema |
| `durability/*` | budgets, taint, stop, verify_promote, eval_memory |

## Hard rules

- No force-push; no secrets; no vendoring whole trees
- Prefer patterns from `.nexus_workspaces/scout_repos/`
- Update `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md` on behavior change
- `PYTHONPATH=src python3 -m pytest -q` must stay green

## Commands

```bash
nexus improve board
nexus improve decide --repo wshobson/agents
nexus improve apply --mode sandbox
nexus alive once   # self_approve only if alive.json apply+self_approve and board continues
make test
```
