# Self-improve cycle — backlog & status

_Generated 2026-07-15 · Model: `grok-4.5` · hard-apply P0.4 + P0.5 (principled stop + independent verify)._

## Executive summary

- NEXUS (`VincentMarquez/nexus-core`) self-improves via mine → arXiv → Grok grade/reason/apply → keep tests green.
- **Landed (P0–P11 + P0.3–P0.5):** atomic checkpoints, event journal, handoffs, replay/explain, cost, provenance, verify, graph, evidence, HITL resume, wall budget, opt-in norm enforcement, RunBudget + TaintSet + DurableAgent, zero-trust StateSlice, eval-gated memory writes, **principled stop (zenith)**, **independent verify-before-promote**.
- **This session First apply:** zenith-style gap board + no-progress thrash stop for the alive loop; independent verifier required before taint→trusted / memory promote.
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
| P0.3 | Eval-gated memory write | **done** |
| P0.4 | Principled stopping (zenith) | **done this session** |
| P0.5 | Independent verify before promote | **done this session** |

## Top mined patterns (reuse, don’t vendor)

| Score | Repo | Pattern |
|------:|------|---------|
| 16 | wshobson/agents | Multi-harness skill packs |
| 15 | mission-control / routa / MisterSmith | Ops cost, evidence board, supervised runtime |
| 15 | cycgraph / EDDI / zenith | Multi-budget, taint, slice, eval-gated retention, **gap stop**, independent verify |
| 15 | lumen / tiger_cowork / openrouter-deep-research-mcp | Durability, atomic stores, circuit breakers |
| 14 | swarm / edict | Handoff + review veto |

## First apply slice (this session)

**P0.4 — Principled stopping (zenith)** + **P0.5 — Independent verify before promote**

1. `src/nexus/durability/stop.py` — `PrincipledStop`, `StopPolicy`, `GapItem`, `cycle_progressed`
2. `src/nexus/durability/verify_promote.py` — `IndependentVerify`, `promote_taint_verified`, `promote_memory_verified`
3. `src/nexus/alive.py` — stop knobs + record/persist on each cycle; `watch` exits on principled stop
4. Package exports in `src/nexus/durability/__init__.py`
5. Tests: `tests/durability/test_stop.py`, `test_verify_promote.py`, alive knobs in `tests/test_usage_alive.py`
6. Docs: this file + `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md`

### Usage sketch — principled stop

```python
from nexus.durability import PrincipledStop, StopPolicy

stop = PrincipledStop(policy=StopPolicy(max_no_progress=3))
stop.register_gap("P0.4", "principled stop module")
d = stop.record_cycle(progressed=True)
assert not d.stop
stop.close_gap("P0.4", evidence="landed + tests green")
d = stop.record_cycle(progressed=True)
assert d.stop and d.reason == "gaps_closed"
```

Alive knobs in `alive.json`: `stop_max_no_progress`, `stop_max_cycles`, `stop_when_gaps_closed`, `stop_on_tests_red`.
State persists at `.nexus_state/alive_stop.json`.

### Usage sketch — independent verify before promote

```python
from nexus.durability import IndependentVerify, TaintSet, TaintLevel, promote_taint_verified

t = TaintSet()
t.stamp("digest", level=TaintLevel.MINED, source="scout_repos/foo")
v = IndependentVerify()  # min_score=0.7, require cross-agent
ok = v.evaluate(implementer="coder", verifier="reviewer", score=0.9, decision="pass")
promote_taint_verified(t, "digest", gate="ops-board", verify=ok)
t.require_trusted("digest")  # ok
```

Same gate wraps memory via `promote_memory_verified(writer, text, ns=..., verify=ok, gate_reason=...)`.

## Reasoning plan (cycle discipline)

1. **Mine** top repos (score ≥ 10) under `.nexus_workspaces/scout_repos/`.
2. **arXiv** brief (ledger skips already-seen papers).
3. **Grade** patterns vs NEXUS gaps (durability, operator audit, memory trust).
4. **First apply** one small tested slice; keep `pytest` green.
5. **Log** in `ALIVE_IMPROVEMENTS.md` + refresh this plan.
6. **Stop** when gaps closed or no-progress thrash (principled stop) — do not loop forever.

## Commands

```bash
nexus github mine improve-ours --min-score 10.0
# hard apply with Grok
nexus github mine improve-ours --apply --worker grok
PYTHONPATH=src python3 -m pytest -q
```
