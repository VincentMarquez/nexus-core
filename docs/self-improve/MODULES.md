# Module ownership map

## Product — `~/nexus-core` (source of truth)

| Module | Path | Owns |
|--------|------|------|
| **alive cycle** | `src/nexus/alive.py` | REAL/DRY orchestration, fix_loop, executive summary |
| **engine + judge** | `src/nexus/engine.py`, `judge.py`, `consensus.py` | Step graph, pass/revise/fail |
| **unified entry** | `src/nexus/unified_pipeline.py` | One call: research brief → engine |
| **idea portfolio** | `src/nexus/idea_portfolio.py` | ≥1 arXiv + ≥1 GitHub, max 10, cross-pattern |
| **GitHub mine** | `src/nexus/repo_mine.py`, `github_autonomy.py` | High-star search, grade, improve-ours |
| **arXiv** | `src/nexus/paper_improve.py`, arxiv client | Paper rank → PAPER_IMPROVE |
| **MCP tools** | `src/nexus/mcp_server.py` | `canonical_pipeline`, `github_mine`, `run_task`, … |
| **tool privileges** | `src/nexus/tool_catalog.py` | Privilege map for MCP |
| **worker** | `src/nexus/grok_worker.py` | Grok hard improve / fix loop |
| **package facade** | `src/nexus/self_improve/` | Clean imports for the above |

### Product state (not source)

| Path | Role |
|------|------|
| `.nexus_state/alive.json` | Live config |
| `.nexus_state/alive_state.json` | Last cycle JSON |
| `.nexus_state/repo_mine/` | Mine DB, IMPROVE_OURS, high-star notes |
| `.nexus_state/arxiv_improve/` | Notes, abstracts, grades |
| `docs/LATEST_*.md` | Operator-facing cycle reports |

## Lab — remote control only

**Root:** ``$NEXUS_LAB_ROOT` (lab workspace)`  
(sits inside a large research monorepo — keep product logic out of it)

| Module | Path | Owns |
|--------|------|------|
| **bus / chat** | `bridge/server.js` | Intercepts self-improve & pipeline chat, SSE |
| **product control** | `bridge/product_control.js` | Spawns `nexus alive`, github mine, waits for implement summary |
| **UI tab** | `src/ProductSelfImprove.jsx` | Buttons DRY/REAL/mine/pipeline |
| **multi-agent UI** | `src/CerfMultiAgent.jsx` | Seats, TOOL_CALL fan-out to product MCP |
| **lab docs** | `docs/self-improve/README.md` | Points back at product map |

Lab must not implement product logic. It calls product CLI/MCP.

## Import preference

```python
# preferred
from nexus.self_improve import cycle_once, run_canonical, build_portfolio

# still valid (legacy)
from nexus.alive import cycle_once
from nexus.unified_pipeline import run_canonical
```
