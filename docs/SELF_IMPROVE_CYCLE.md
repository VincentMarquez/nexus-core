# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 · hard-apply worker session_

Model: `grok-4.5` · repos≈20 · arXiv≈20

---

## Reasoning plan (this cycle)

1. **Read evidence** — `.nexus_state/repo_mine/IMPROVE_OURS.md` (top scored clones under `.nexus_workspaces/scout_repos/`) + latest arXiv improve notes under `.nexus_state/arxiv_improve/`.
2. **Prefer open P0 from prior plan** — last landed: durable MCP context + worktree-isolated apply. **Next open:** promote verified pack from worktree → main (P0.1 deepen).
3. **Port patterns only** — cas/forge worktree isolation; zenith/cycgraph verify-before-promote; wshobson Markdown SoT; lumen/soul ledger; never vendor whole trees.
4. **First apply slice** — implement promote-to-main with fail-closed re-verify + tests; keep `pytest` green; update `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md`.
5. **Finish cleanly** — summarize files changed; no force-push; no secrets.

## First apply slice (executed)

| Piece | Path |
|-------|------|
| `promote_to_main` / `run_promote` | `src/nexus/worktree_apply.py` |
| `PROMOTE_STAGES` + `StageRunner.promote_slice` | `src/nexus/stages.py` |
| CLI | `nexus improve apply --promote` · `nexus improve promote` |
| Tests | `tests/test_worktree_apply.py`, `tests/test_stage_order.py` |

### Operator commands

```bash
# Isolated apply (main clean)
PYTHONPATH=src python3 -m nexus.cli improve apply \
  --fixture tests/fixtures/mine_eval_sample.json --mode sandbox

# Apply + promote onto main
PYTHONPATH=src python3 -m nexus.cli improve apply \
  --fixture tests/fixtures/mine_eval_sample.json --mode sandbox --promote

# Promote a kept worktree
PYTHONPATH=src python3 -m nexus.cli improve promote --job-id <run_id>

PYTHONPATH=src python3 -m pytest -q
```

## Success criteria

- Claim-verify + worktree verify gate promote.
- Main only changes at explicit promote step.
- Differing main content denied without force; re-verify on main after copy.
- Ledger row for promote; PROMOTE_META audit on pack.
- Tests green.
