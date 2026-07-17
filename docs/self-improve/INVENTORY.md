# Self-improve inventory

**How to refresh:** `bash scripts/track_self_improve.sh`

## Product files that define the system

| Path | Role | Git target |
|------|------|------------|
| `src/nexus/alive.py` | Cycle orchestrator | **commit** |
| `src/nexus/unified_pipeline.py` | Canonical engine entry | **commit** |
| `src/nexus/idea_portfolio.py` | Idea quotas + implement | **commit** |
| `src/nexus/github_autonomy.py` | High-star mine | **commit** |
| `src/nexus/repo_mine.py` | Mine grades / improve-ours | **commit** |
| `src/nexus/paper_improve.py` | arXiv improve notes | **commit** |
| `src/nexus/mcp_server.py` | MCP tools | **commit** |
| `src/nexus/tool_catalog.py` | Tool privileges | **commit** |
| `src/nexus/self_improve/` | Facade package | **commit** |
| `tests/test_usage_alive.py` | Alive tests | **commit** |
| `tests/test_paper_improve.py` | Paper tests | **commit** |
| `docs/self-improve/` | Human map | **commit** |
| `docs/SELF_IMPROVE.md` | Root pointer | **commit** |
| `scripts/track_self_improve.sh` | Status helper | **commit** |

## Related engine (usually already on GitHub)

| Path | Role |
|------|------|
| `src/nexus/engine.py` | Durable step graph |
| `src/nexus/judge.py` | Rubric / consensus scores |
| `src/nexus/consensus.py` | Multi-agent consensus |
| `src/nexus/grok_worker.py` | Hard improve / fix worker |
| `src/nexus/cli.py` | `nexus alive` entry |

## Local-only / noise (do not treat as source of truth)

| Path | Why |
|------|-----|
| `.nexus_state/` | Live config + last cycle |
| `.nexus/` | Runtime workspace chat |
| `docs/LATEST_*.md` | Regenerated every REAL |
| `docs/evidence/*demo*.json` | Demo artifacts |
| `fixtures/swe_pre/` | Optional large fixtures |
| `bridge/bridges/stdin_to_grok.py` | Bridge tweak (separate from cycle core) |

## Lab files (remote control — different tree)

Root: ``$NEXUS_LAB_ROOT` (lab workspace)`

| Path | Role | Note |
|------|------|------|
| `bridge/server.js` | Chat intercepts, TOOL_CALL → product | Keep thin |
| `bridge/product_control.js` | Spawns product, waits implement summary | Keep thin |
| `src/ProductSelfImprove.jsx` | UI buttons | Keep thin |
| `src/CerfMultiAgent.jsx` | Multi-LLM UI | Keep thin |
| `docs/self-improve/README.md` | Points at product map | Local docs |

Lab sits in a **large research monorepo**. Prefer **not** dumping product Python there. Track product on **GitHub `nexus-core`**.

## Why not one giant folder move?

Moving `alive.py` / `engine.py` under `self_improve/` would break CLI, tests, and MCP imports.  
**Current approach:** keep modules where they are; use:

1. `nexus.self_improve` **facade** for clean imports  
2. `docs/self-improve/` **map** for humans  
3. `scripts/track_self_improve.sh` for **git status of only the spine**
