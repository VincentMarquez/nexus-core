# Self-improve cycle — backlog & status

_Generated 2026-07-15 · Model: `grok-4.5` · hard-apply P0.3 (eval-gated memory)._

## Executive summary

- NEXUS (`VincentMarquez/nexus-core`) self-improves via mine → arXiv → Grok grade/reason/apply → keep tests green.
- **Landed (P0–P11 + P0.3):** atomic checkpoints, event journal, handoffs, replay/explain, cost, provenance, verify, graph, evidence, HITL resume, wall budget, opt-in norm enforcement, RunBudget + TaintSet + DurableAgent, zero-trust StateSlice, **eval-gated memory writes**.
- **This session First apply:** cycgraph-style eval-gated retention — lessons enter retained memory only when score ≥ judge pass threshold (else trial namespace / deny).
- Prefer patterns from `.nexus_workspaces/scout_repos/`; never vendor whole trees.

## Operator CLI (production audit)

```bash
nexus task list
nexus task show <id>
nexus task events <id>
nexus task replay <id>
nexus task explain <id>
nexus task cost <id>
nexus task prov <id>
nexus task verify <id>
nexus task graph <id> [--mermaid]
nexus task evidence <id> [--out file.json]
nexus task resume <id> [--approve|--reject]
```

Cookbook: [cookbook/01_crash_resume.md](../cookbook/01_crash_resume.md) · [cookbook/12_task_operator.md](../cookbook/12_task_operator.md) (if present)

## Priority backlog

| ID | Item | Status |
|----|------|--------|
| P0 | Atomic checkpoints + journal | **done** |
| P1 | Handoffs + journal context on resume | **done** |
| P2 | `replay` / `explain` / why | **done** |
| P3 | `cost` + judge thresholds | **done** |
| P4 | `prov` / `verify` | **done** |
| P5 | token budget + `graph` | **done** |
| P6 | `evidence` + norms pack | **done** |
| P7 | HITL `resume --approve/--reject` | **done** |
| P8 | wall-clock budget | **done** |
| P9 | enforce_norms deny/require | **done** |
| P10 | RunBudget + Taint + DurableAgent | **done** |
| P11 | Zero-trust StateSlice (`read_keys`/`write_keys`) | **done** |
| P0.3 | Eval-gated memory write | **done this session** |
| P0.4 | Principled stopping (zenith) | **open** |
| P0.5 | Independent verify before promote | **open** |

## Top mined patterns (reuse, don’t vendor)

| Score | Repo | Pattern |
|------:|------|---------|
| 16 | wshobson/agents | Multi-harness skill packs |
| 15 | mission-control / routa / MisterSmith | Ops cost, evidence board, supervised runtime |
| 15 | cycgraph / EDDI / zenith | Multi-budget, taint, slice, **eval-gated retention**, adaptive stop |
| 15 | lumen / tiger_cowork / openrouter-deep-research-mcp | Durability, atomic stores, circuit breakers |
| 14 | swarm / edict | Handoff + review veto |

## First apply slice (this session)

**P0.3 — Eval-gated memory write**

1. `src/nexus/durability/eval_memory.py` — `EvalGate`, `GatedMemoryWriter`, `MemoryWriteDenied`, trial/retained namespaces
2. Package exports in `src/nexus/durability/__init__.py`
3. Tests: `tests/durability/test_eval_memory.py` (MemorySpine + SqliteMemory)
4. Docs: this file + `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md`

### Usage sketch

```python
from nexus.durability import EvalGate, GatedMemoryWriter
from nexus.memory import MemorySpine

store = MemorySpine()
writer = GatedMemoryWriter(store=store, gate=EvalGate())  # min_score=0.7 (judge PASS)

r = writer.write("Prefer atomic rename", ns="proj/lessons", score=0.85, decision="pass")
assert r.retained  # kind=lesson in proj/lessons

r = writer.write("Skip tests always", ns="proj/lessons", score=0.2)
assert r.trial     # lands in proj/lessons/trial only

writer.promote("human-reviewed lesson", ns="proj/lessons", gate_reason="ops-board")
```

Opt-in from task meta: `memory_min_score`, `memory_require_pass`, `memory_allow_trial`, or nested `eval_gate`.

## Reasoning plan (cycle discipline)

1. **Mine** top repos (score ≥ 10) under `.nexus_workspaces/scout_repos/`.
2. **arXiv** brief (ledger skips already-seen papers).
3. **Grade** patterns vs NEXUS gaps (durability, operator audit, memory trust).
4. **First apply** one small tested slice; keep `pytest` green.
5. **Log** in `ALIVE_IMPROVEMENTS.md` + refresh this plan.

## Commands

```bash
nexus github mine improve-ours --min-score 10.0
# hard apply with Grok
nexus github mine improve-ours --apply --worker grok
PYTHONPATH=src python3 -m pytest -q
```
