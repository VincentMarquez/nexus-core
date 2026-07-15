# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 · hard-apply session_

Model: `grok-4.5` · repos≥10 · arXiv≥10

---

## Reasoning plan (this cycle)

1. **Mine** — IMPROVE_OURS top clones under `.nexus_workspaces/scout_repos/` (no follow/star; no tree vendor).
2. **Research** — arXiv improve notes under `.nexus_state/arxiv_improve/` (communication, context, audit).
3. **Grade** — offline grades via `nexus.grade/v1` / IMPROVE_OURS scores.
4. **Plan** — `docs/LATEST_IMPROVE_PLAN.md` priority table + First apply slice.
5. **Apply** — smallest PR-sized change with tests; keep pytest green.
6. **Log** — append `docs/ALIVE_IMPROVEMENTS.md`.

## This session (First apply slice)

| Item | Status |
|------|--------|
| P2.3 Domain MCP eval smoke (AssetOpsBench shape) | **landed** |
| P3 Optional review→promote hook (zenith/cycgraph) | **landed (opt-in)** |

### Deliverables

- `src/nexus/mcp_eval.py` — scenarios → trajectories → code scorers → `nexus.mcp_eval/v1` report
- `nexus eval list|smoke|run` CLI
- MCP tool `mcp_eval`
- `engine._maybe_promote_after_review` (meta.promote_on_review)
- Tests: `tests/test_mcp_eval.py`, promote cases in `tests/test_engine.py`

### Patterns (shape only)

- **IBM/AssetOpsBench** — scenario / trajectory / scorer / pass-rate
- **mission-control** — CLI + MCP + export parity
- **zenith / cycgraph** — independent verify before promote
- **arXiv 2203.08975 / 2511.15755** — communication surface health + deterministic audit

### Commands

```bash
nexus eval smoke
nexus eval list --domain catalog
PYTHONPATH=src python3 -m pytest -q
```

### Next open

- Optional LLM-as-judge scorer family (still offline-default)
- Domain scenario packs loaded from JSON (AssetOpsBench groundtruth shape)
- Wire promote into improve_apply audited→done gate when meta requests it
