# Self-improve system map

**One product flow. Lab is only a remote control.**

Confused by the tree? Read **[MAP.md](./MAP.md)** first (one page).  
Track git status of only this spine: `bash scripts/track_self_improve.sh`

| Layer | Location | Role |
|-------|----------|------|
| **Product core** | `~/nexus-core` → GitHub `VincentMarquez/nexus-core` | Research, engine+judge, apply, push |
| **Lab workspace** | `~/Desktop/Projects/research/security-lab` (`:5173` / bus `:3099`) | UI + chat that call product |
| **State / reports** | `~/nexus-core/docs/LATEST_*` + `.nexus_state/` | Cycle outputs (local) |
| **Runtime logs** | `/tmp/nexus-alive-watch.log` | Alive process log |

## Docs in this folder

| File | What |
|------|------|
| [MAP.md](./MAP.md) | **One-page layout** — start if code feels scattered |
| [FLOW.md](./FLOW.md) | DRY vs REAL flow, fix loop, quotas |
| [MODULES.md](./MODULES.md) | Which Python/JS file owns what |
| [RUNTIME.md](./RUNTIME.md) | Artifacts, paths, how to read a cycle |
| [TRACKING.md](./TRACKING.md) | Git / what to commit vs leave local |
| [INVENTORY.md](./INVENTORY.md) | File checklist + lab absolute paths |

## Start here (operator)

```text
DRY:  run self-improve          → probe only
REAL: run self-improve real     → GitHub≥5K + arXiv → engine+judge
                                 → portfolio (≥1 arXiv + ≥1 GitHub, max 10)
                                 → fix_loop until tests green
                                 → implement → exec review
Engine only: run review pipeline
```

## Code package (imports)

Prefer:

```python
from nexus.self_improve import cycle_once, run_canonical, build_portfolio
```

Legacy imports (`from nexus.alive import …`) still work.

## Related product docs (generated each REAL cycle)

| Artifact | Meaning |
|----------|---------|
| `docs/LATEST_IMPLEMENT_SUMMARY.md` | **Executive review** (hit rates, tokens, approvals) |
| `docs/LATEST_IDEA_PORTFOLIO.md` | Selected arXiv/GitHub/novel ideas |
| `docs/LATEST_GITHUB_REVIEW.md` | High-star mine list |
| `docs/LATEST_ARXIV_IMPROVE.md` | Latest arXiv note snapshot |
| `docs/LATEST_META_REVIEW.md` | Cycle meta verdict |
| `docs/LATEST_DUAL_REVIEW.md` | Merged research brief |
| `.nexus_state/alive.json` | Config |
| `.nexus_state/alive_state.json` | Last cycle report |
| `.nexus_state/LAST_IMPLEMENT_SUMMARY.json` | Metrics (machine) |
