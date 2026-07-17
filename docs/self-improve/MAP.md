# One-page map — where everything lives

```text
┌─────────────────────────────────────────────────────────────────────┐
│  OPERATOR (you)                                                     │
│   lab chat UI :5173  ·  "run self-improve real"  ·  MCP tools       │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ remote control only
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LAB  ~/Desktop/Projects/research/security-lab                      │
│   bridge/server.js          chat intercepts → product               │
│   bridge/product_control.js  spawns nexus alive / waits summary     │
│   src/ProductSelfImprove.jsx  DRY / REAL / mine buttons             │
│   src/CerfMultiAgent.jsx      multi-LLM seats + TOOL_CALL           │
│   docs/self-improve/          → points here (product)               │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ CLI + MCP :8765
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PRODUCT  ~/nexus-core   ← GitHub: VincentMarquez/nexus-core        │
│                                                                     │
│  Clean import:  from nexus.self_improve import cycle_once, …        │
│                                                                     │
│  ┌─ orchestration ─────────────────────────────────────────────┐    │
│  │ alive.py              REAL/DRY cycle, fix_loop, exec summary │    │
│  │ unified_pipeline.py   research brief → engine+judge          │    │
│  │ idea_portfolio.py     ≥1 arXiv + ≥1 GitHub, max 10, novels  │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  ┌─ research input ────────────────────────────────────────────┐    │
│  │ github_autonomy.py / repo_mine.py   GitHub ≥5K★             │    │
│  │ paper_improve.py / arxiv_*          arXiv notes + grades    │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  ┌─ engine ────────────────────────────────────────────────────┐    │
│  │ engine.py · judge.py · consensus.py · grok_worker.py        │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  ┌─ surface ───────────────────────────────────────────────────┐    │
│  │ mcp_server.py · tool_catalog.py · cli (nexus alive)         │    │
│  │ self_improve/   package facade (re-exports)                 │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  ┌─ tracking docs (this folder) ───────────────────────────────┐    │
│  │ README · FLOW · MODULES · RUNTIME · TRACKING · INVENTORY    │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  ┌─ runtime (local only, not "the code") ──────────────────────┐    │
│  │ .nexus_state/   config + last cycle                         │    │
│  │ docs/LATEST_*   regenerated every REAL                      │    │
│  └──────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

## Mental model (3 places)

| Place | Track as | Rewrite often? |
|-------|----------|----------------|
| **Product source** `src/nexus/*` | GitHub commits | No — code of record |
| **Lab UI/bus** `security-lab/*` | Lab monorepo (messy; keep thin) | Only intercepts/UI |
| **Runtime artifacts** `.nexus_state/`, `docs/LATEST_*` | Local disk | Yes — every cycle |

## Do not confuse

| Looks like product logic | Actually |
|--------------------------|----------|
| Lab multi-agent free chat | Discussion only — not the implement system of record |
| `run review pipeline` | Engine+judge only (no alive push / full portfolio) |
| `run self-improve` (no real) | DRY probe — no mine, no apply |
| `docs/LATEST_*.md` | Outputs, not source |
| Flat `src/nexus/*.py` (64 modules) | Whole product; **self-improve spine** is the ~10 files in [MODULES.md](./MODULES.md) |
