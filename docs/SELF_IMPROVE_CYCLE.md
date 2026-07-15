# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 · hard-apply session_

Model: `grok-4.5` · repos from IMPROVE_OURS (≥10) · arXiv under `.nexus_state/arxiv_improve/`

---

## Reasoning plan (this cycle)

1. **Read evidence** — `docs/SELF_IMPROVE_CYCLE.md`, `docs/LATEST_IMPROVE_PLAN.md`,
   `.nexus_state/repo_mine/IMPROVE_OURS.md`, latest arXiv improve notes
   (`improve-rx-0a75f9514d` + prior).
2. **Grade backlog** — Prefer next open items from prior cycle, not re-ports of done work.
3. **First apply slice** — Small, tested modules; patterns only from
   `.nexus_workspaces/scout_repos/`; no tree vendor; no secrets; no force-push.
4. **Verify** — `PYTHONPATH=src python3 -m pytest -q` green.
5. **Document** — Update `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md`.

## Prior cycle next-open (source of this apply)

From hard-apply P2.3 + P3:

- JSON scenario packs
- optional LLM-as-judge scorer
- improve_apply promote gate wiring

## This session First apply slice

| Item | Module | Pattern source |
|------|--------|----------------|
| P2.4 JSON scenario packs | `mcp_eval.py` + CLI/MCP | IBM/AssetOpsBench `scenarios/*.json` |
| P2.5 pluggable llm_judge | `mcp_eval.py` scorers | AssetOpsBench static_json / judge; offline fallback |
| P3.1 improve_apply promote | `improve_apply.py` | zenith IndependentVerify + cycgraph promote gate |

## Guardrails

- Prefer small, tested changes; keep make test / pytest green.
- Do **not** force-push; do **not** commit secrets; do **not** vendor whole upstream trees.
- Port **patterns** from local clones under `.nexus_workspaces/scout_repos/`.
