# Tracking changes (GitHub vs local)

## Two trees, two jobs

| Tree | GitHub? | What belongs there |
|------|---------|-------------------|
| **`~/nexus-core`** | Yes — [VincentMarquez/nexus-core](https://github.com/VincentMarquez/nexus-core) | alive, engine, portfolio, MCP, `docs/self-improve` |
| **``$NEXUS_LAB_ROOT` (lab workspace)`** | Research monorepo (messy) | UI/bus only; avoid dumping product logic here |

We **cannot** cleanly put the whole lab monorepo on the product GitHub.  
We **can** put the entire product self-improve spine on GitHub and treat the lab as a thin remote.

## Recommended product commit set (self-improve work)

**Include (source + map):**

```text
src/nexus/alive.py
src/nexus/unified_pipeline.py
src/nexus/idea_portfolio.py
src/nexus/github_autonomy.py
src/nexus/mcp_server.py
src/nexus/repo_mine.py
src/nexus/tool_catalog.py
src/nexus/paper_improve.py
src/nexus/self_improve/             # package facade
tests/test_usage_alive.py
tests/test_paper_improve.py
docs/self-improve/                  # this map
docs/SELF_IMPROVE.md                # root pointer
scripts/track_self_improve.sh       # spine status
```

**Usually leave uncommitted / gitignore-ish noise:**

```text
.nexus/                             # runtime workspace chat
docs/evidence/*demo*.json           # cycle demos unless you want them
docs/LATEST_*.md                    # regenerated every REAL (optional commit)
.nexus_state/                       # live config + last cycle (keep local)
fixtures/swe_pre/                   # optional large fixtures
src/nexus/comm_bench.py             # unrelated bench unless you want it
tests/test_comm_bench.py
```

`LATEST_*` reports: commit only if you want a historical snapshot; they rewrite every REAL.

## Lab tracking

```text
`$NEXUS_LAB_ROOT` (lab workspace)/docs/self-improve/README.md
  → points at product docs
```

Source of truth for flow remains **product** `docs/self-improve/`.

## Status snapshot command

```bash
bash ~/nexus-core/scripts/track_self_improve.sh
```

## GitHub workflow (product)

```bash
cd ~/nexus-core
bash scripts/track_self_improve.sh
# stage only the spine (script prints the list)
git add src/nexus/alive.py src/nexus/unified_pipeline.py ...
git commit -m "feat(self-improve): portfolio quotas, facade, operator map"
# push only when tests green and you intend to publish:
# git push origin main
```
