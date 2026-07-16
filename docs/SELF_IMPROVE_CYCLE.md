# Self-improve cycle — Grok 4.5

_Generated 2026-07-16 · hard-apply worker session_

Model: `grok-4.5` · repos from `.nexus_state/repo_mine/IMPROVE_OURS.md` · arXiv notes under `.nexus_state/arxiv_improve/`

---

## Reasoning plan (this session)

1. **Read** `IMPROVE_OURS.md`, prior `ALIVE_IMPROVEMENTS` open items, latest arXiv brief (`improve-rx-4e382a3fbf` durable multi-agent workflow / checkpoint).
2. **Select First apply slice** from last cycle’s open list (small, testable, no tree vendor):
   - decide CLI spine flags
   - board spine method lines
   - zenith + agent-fleet pattern catalog
   - optional live Grok judge Makefile target
3. **Port patterns only** from scout clones (zenith stop discipline; agent-fleet dual-control/DAG) — do not vendor upstream trees.
4. **Test** offline fixtures; keep live Grok opt-in (`NEXUS_LIVE_GROK_JUDGE=1`).
5. **Document** in `docs/LATEST_IMPROVE_PLAN.md` + append `docs/ALIVE_IMPROVEMENTS.md`.

## Constraints

- Prefer small, tested changes; keep `make test` / pytest green
- Do **not** force-push; do **not** commit secrets; do **not** vendor whole upstream trees
- Port patterns from `.nexus_workspaces/scout_repos/` when useful

## First apply slice

See **First apply slice** in [`docs/LATEST_IMPROVE_PLAN.md`](LATEST_IMPROVE_PLAN.md).

Landed modules:

| Module | Change |
|--------|--------|
| `src/nexus/apply_select.py` | `decision_package(use_spine, use_preference, run_id)`; board/select text `method=` |
| `src/nexus/cli.py` | `improve decide --no-spine|--no-preference|--run-id` |
| `src/nexus/worktree_apply.py` | patterns `zenith-principled-stop-ops`, `agent-fleet-ops` |
| `Makefile` | `eval-live-judge` (opt-in nightly) |
| tests | `test_apply_select`, `test_worktree_apply` |

## Verify

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m nexus.cli improve board --limit 3
PYTHONPATH=src python3 -m nexus.cli improve decide --repo wshobson/agents --json | head
make eval-samples
```
