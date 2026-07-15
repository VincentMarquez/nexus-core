# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 · hard-apply worker_

Model: `grok-4.5` · repos from `.nexus_state/repo_mine/IMPROVE_OURS.md` · arXiv under `.nexus_state/arxiv_improve/`

---

## Cycle method

1. **Mine** — graded repos in IMPROVE_OURS (score ≥ 10); local clones under `.nexus_workspaces/scout_repos/`.
2. **Research** — arXiv improve notes (`improve-rx-*.md`); map ideas → failing tests / missing modules.
3. **Plan** — write `docs/LATEST_IMPROVE_PLAN.md` with a **First apply slice** and non-goals.
4. **Apply** — small modules + tests; patterns only (no vendored trees); no force-push; no secrets.
5. **Verify** — `PYTHONPATH=src python3 -m pytest -q` green.
6. **Log** — append `docs/ALIVE_IMPROVEMENTS.md`; keep this file + LATEST plan coherent.

## This session First apply slice

**P2.2 OpenAPI-ish MCP tool catalog export** (mission-control pattern + privilege ladder from arXiv 2606.20023).

| Deliverable | Path |
|-------------|------|
| Core | `src/nexus/tool_catalog.py` |
| CLI | `nexus tools …` in `src/nexus/cli.py` |
| MCP | tool `tool_catalog` in `src/nexus/mcp_server.py` |
| HTTP | `GET /openapi.json`, `GET /catalog.json` |
| Tests | `tests/test_tool_catalog.py` |
| Docs | this file, `docs/LATEST_IMPROVE_PLAN.md`, `docs/ALIVE_IMPROVEMENTS.md` |

## Guardrails

- Prefer small, tested changes; keep make test / pytest green.
- Do **not** force-push; do **not** commit secrets; do **not** vendor whole upstream trees.
- Port patterns from `.nexus_workspaces/scout_repos/` only.
- Fail closed on unmapped tools (default privilege `ops`) and invalid schemas.

## Prior this cycle (already landed)

P0 durability · P1 operator board · improve_apply FSM · grade loop · ops_store · DAG · consensus · context pack · vault/gap seed · **P2.1 skillpacks**.

## Next after P2.2

- P2.3 Domain MCP eval smoke (AssetOpsBench) — extend catalog validate into domain fixtures
- P3 Optional engine review→promote hook (zenith / cycgraph)
- Optional: wire OpenAPI export into packaging / docs site

## Quick commands

```bash
nexus tools list --max-privilege read
nexus tools validate
nexus tools export && ls .nexus_state/tool_catalog/
PYTHONPATH=src python3 -m pytest -q
```
