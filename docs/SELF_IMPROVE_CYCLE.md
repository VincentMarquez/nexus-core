# Self-improve cycle — Grok 4.5

_Generated 2026-07-16 · hard-apply worker_

Model: `grok-4.5` · repos from IMPROVE_OURS · arXiv notes under `.nexus_state/arxiv_improve/`

---

## Reasoning plan (this cycle)

1. **Read evidence** — `IMPROVE_OURS.md`, latest arXiv improve notes, `ALIVE_IMPROVEMENTS.md` next-open.
2. **Pick First apply slice** — close prior open: wire work_ledger into apply paths + MCP + transition invariants.
3. **Port patterns, not trees** — soul ledger, dual-control, cas/mission-control operator surface.
4. **Hard apply** — small modules + tests; fail-closed gates.
5. **Verify** — `PYTHONPATH=src python3 -m pytest -q`.
6. **Document** — `LATEST_IMPROVE_PLAN.md`, `ALIVE_IMPROVEMENTS.md`.

## First apply slice (landed)

| Surface | Change |
|---------|--------|
| `work_ledger.py` | LEGAL_SUCCESSORS, `ensure_apply_gate`, status helper |
| `worktree_apply.py` | require work_ledger accept before plan_apply |
| `alive.py` | `require_work_ledger` + gate in self_approve |
| `mcp_server.py` | tool `work_ledger` |
| tests | transitions, gate, e2e apply, alive, MCP |

## Commands

```bash
# offline proof of dual-control loop
PYTHONPATH=src python3 -m nexus.cli improve work-loop --repo wshobson/agents
# worktree apply (decision + work_ledger gates on by default)
PYTHONPATH=src python3 -m nexus.cli improve apply --mode sandbox --repo wshobson/agents
# inspect ledger
PYTHONPATH=src python3 -m nexus.cli improve work-ledger --limit 10
# tests
PYTHONPATH=src python3 -m pytest -q
```

## Safety

- No force-push; no secrets; no vendored upstream trees.
- Autonomy apply/push remain opt-in (`self_approve`, `push_github`).
