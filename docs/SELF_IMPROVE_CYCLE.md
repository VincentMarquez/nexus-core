# Self-improve cycle — Grok 4.5

_Generated 2026-07-16 · hard-apply worker_

Model: `grok-4.5` · repos from IMPROVE_OURS (≥10) · arXiv under `.nexus_state/arxiv_improve/`

---

## Reasoning plan (this cycle)

1. **Evidence** — Read IMPROVE_OURS + latest arXiv improve notes + prior ALIVE_IMPROVEMENTS open items.
2. **Prioritize** — Prefer P0/P1 loop gaps over product UI. Next open after work_ledger wire was:
   - preference brief → context_pack
   - more pattern catalog
   - multi-worker interleaving stress
3. **First apply slice** — Inject offline preference pairs into `nexus.context_pack/v1` so apply/resume agents see value-system bias (arXiv 2602.04518) without a live trainer; add soul work-ledger skill pattern; stress dual-control under concurrent workers.
4. **Verify** — Focused + full `pytest`; keep fail-closed gates; no vendored trees; no secrets; no force-push.
5. **Document** — Update `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md`.

## Commands

```bash
# offline preference → pack
nexus improve prefer record --better wshobson/agents --worse openai/swarm
nexus task context <task_id> --json   # preference section when pairs exist
nexus task context <task_id> --no-preference
nexus improve select --no-preference  # disable rank boost

# pattern catalog
nexus improve apply --list-patterns
nexus improve apply --pattern soul-work-ledger-ops --mode sandbox

# work ledger dual-control
nexus improve work-loop --repo wshobson/agents
make test
```

## This session landed

| Piece | Module |
|-------|--------|
| Preference section in context pack | `src/nexus/context_pack.py` |
| Engine / CLI / MCP flags | `engine.py`, `cli.py`, `mcp_server.py` |
| soul-work-ledger-ops pattern | `src/nexus/worktree_apply.py` |
| Multi-worker interleaving stress | `tests/test_work_ledger.py` |

See `docs/LATEST_IMPROVE_PLAN.md` for backlog + success criteria.
