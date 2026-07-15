# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 · hard-apply worker session_

Model: `grok-4.5` · repos≈20 · arXiv≈20

---

## Reasoning plan (this cycle)

1. **Read evidence** — `.nexus_state/repo_mine/IMPROVE_OURS.md` (top scored clones under `.nexus_workspaces/scout_repos/`) + latest arXiv improve notes under `.nexus_state/arxiv_improve/`.
2. **Prefer open P0 from prior plan** — last landed slice was P0.1–P0.4+P0.6 (ledger / stages / claim_verify / smoke). **Next was P0.5**: worktree-isolated apply of one Markdown skill SoT validator pattern from **wshobson/agents**.
3. **Port patterns only** — cas/forge worktree isolation; wshobson Markdown SoT + validate; lumen/soul ledger; never vendor whole trees.
4. **First apply slice** — implement P0.5 with tests; keep `pytest` green; update `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md`.
5. **Finish cleanly** — summarize files changed; no force-push; no secrets.

## First apply slice (executed)

| Piece | Path |
|-------|------|
| Worktree apply worker | `src/nexus/worktree_apply.py` |
| APPLY_STAGES | `src/nexus/stages.py` |
| CLI | `nexus improve apply` in `src/nexus/cli.py` |
| Tests | `tests/test_worktree_apply.py` (+ stage order) |

### Operator commands

```bash
# Offline smoke (prior slice)
PYTHONPATH=src python3 -m nexus.cli improve smoke --fixture tests/fixtures/mine_eval_sample.json

# P0.5 isolated apply
PYTHONPATH=src python3 -m nexus.cli improve apply \
  --fixture tests/fixtures/mine_eval_sample.json --mode sandbox

PYTHONPATH=src python3 -m pytest -q
```

## Success criteria

- Claim-verify gates apply.
- Pattern files write only under `.nexus_workspaces/apply_worktrees/`.
- Main fingerprint unchanged for watched paths.
- Ledger rows for plan_apply + apply.
- Tests green.
