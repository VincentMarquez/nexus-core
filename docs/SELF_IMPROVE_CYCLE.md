# Self-improve cycle — Grok 4.5

_Generated 2026-07-16_

Model: `grok-4.5` · repos from IMPROVE_OURS (≥10.0) · arXiv research notes under `.nexus_state/arxiv_improve/`

---

## Reasoning plan (this cycle)

1. **Read** `IMPROVE_OURS.md`, latest arXiv improve notes, and `ALIVE_IMPROVEMENTS.md` “next open”.
2. **Prioritize** small, tested ports — no vendored trees, no force-push, no secrets.
3. **First apply slice** (landed): spine-aware board ranking + openrouter research pattern.
4. **Verify** with `pytest`; update `LATEST_IMPROVE_PLAN.md` + this log’s companion `ALIVE_IMPROVEMENTS.md`.

## Why spine-aware ranking

Improve spine already gates hard apply (`require_spine`). Without board awareness, operators still rank stale fixture digests above durable Grok grades. Porting cas/soul “durable context on the board” makes select/board prefer checkpointed grades (papers 2604.03350 / 2510.13343).

## Why openrouter research pattern

`wheattoast11/openrouter-deep-research-mcp` (score 15) contributes circuit-breaker research loops. Nexus already has `circuits.CircuitBreaker`; the skillpack pattern documents operator usage without vendoring the MCP tree.

## Apply order

```
P0 spine board rank  →  P0 openrouter pattern  →  (next) gated live judge
```

## Evidence commands

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m nexus.cli improve select --no-preference
PYTHONPATH=src python3 -m nexus.cli improve board
```
