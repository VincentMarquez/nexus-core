# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 · hard-apply session_

Model: `grok-4.5` · repos≥10 (IMPROVE_OURS top) · arXiv≥10 (`rx-3c113dc2aa` + priors)

## Reasoning plan (executed)

1. Read `docs/SELF_IMPROVE_CYCLE.md`, `docs/LATEST_IMPROVE_PLAN.md`, `.nexus_state/repo_mine/IMPROVE_OURS.md`, `docs/ALIVE_IMPROVEMENTS.md`.
2. Identify **next open** from prior hard-apply: sample MCP eval packs · wire `promote_on_done` from alive · optional LLM judge.
3. Port **patterns only** from AssetOpsBench (scenario packs), zenith/cycgraph (verify-before-promote), mission-control (CLI/MCP parity).
4. Land small modules + tests; keep `pytest` green.
5. Update `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md`.

## First apply slice (this session)

See `docs/LATEST_IMPROVE_PLAN.md` — **P2.6 sample packs + P2.5 Ollama judge + P3.2 alive promote_on_done**.

## Sources (high signal)

| Source | Pattern used |
|--------|----------------|
| IBM/AssetOpsBench | JSON scenario packs + judge scorer shape |
| Intelligent-Internet/zenith | independent verify / no premature complete |
| builderz-labs/mission-control | CLI install/list + ops status |
| ahmedEid1/lumen | improve_apply phase + decision audit |
| arXiv 2401.07324 / 2508.08322 / 2606.20023 | multi-LLM tools, context, least privilege |

## Proof

```bash
PYTHONPATH=src python3 -m pytest -q
nexus eval packs --install-samples
```
