# Self-improve cycle — Grok 4.5

_Generated 2026-07-16_

Model: `grok-4.5` · repos from IMPROVE_OURS (≥10.0) · arXiv research notes under `.nexus_state/arxiv_improve/`

---

## Reasoning plan (this cycle)

1. **Read** `IMPROVE_OURS.md`, latest arXiv improve notes (`improve-rx-997436d67e`), and `ALIVE_IMPROVEMENTS.md` “next open”.
2. **Prioritize** small, tested ports — no vendored trees, no force-push, no secrets.
3. **First apply slice** (landed): spine method on decision_package evidence_refs + MisterSmith/solace patterns + gated live Grok judge test.
4. **Verify** with `pytest`; update `LATEST_IMPROVE_PLAN.md` + companion `ALIVE_IMPROVEMENTS.md`.

## Why spine method on evidence_refs

Spine-aware ranking already boosts select/board, but decision packages only cited filesystem claim paths. Operators and dual-control gates need to know *which durable method/run* produced the grade (papers 2511.15755 decision package, Thucy 2512.03278). Porting soul/cas “method on the ledger surface” into `evidence_refs` closes that audit gap without network calls.

## Why MisterSmith + Solace patterns

- **MattMagg/MisterSmith** — supervised multi-agent runtime with hard token/step caps; maps to Nexus `RunBudget` + task cost/graph inspect.
- **SolaceLabs/solace-agent-mesh** — event-driven mesh + eval matrix; maps to task journal handoff events + offline MCP eval smoke.

Both land as skillpack catalog entries (validate offline); no tree vendoring.

## Why gated live Grok judge

`make_grok_judge` already falls back offline. A single integration test, skipped unless `NEXUS_LIVE_GROK_JUDGE=1` and `grok` is on PATH, proves the live path without breaking default CI (arXiv 2401.07324 multi-LLM tooling).

## Apply order

```
P0 spine evidence_refs  →  P0 MisterSmith/solace patterns  →  P0 gated live judge test
```

## Evidence commands

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m nexus.cli improve board
PYTHONPATH=src python3 -m nexus.cli improve apply --list-patterns
```
