# Self-improve cycle — backlog & status

_Generated 2026-07-15 · Model: `grok-4.5` · hard-apply P11 (state slice)._

## Executive summary

- NEXUS (`VincentMarquez/nexus-core`) self-improves via mine → arXiv → Grok grade/reason/apply → keep tests green.
- **Landed (P0–P11):** atomic checkpoints, event journal, handoffs, replay/explain, cost, provenance, verify, graph, evidence, HITL resume, wall budget, opt-in norm enforcement, RunBudget + TaintSet + DurableAgent, **zero-trust StateSlice**.
- **This session First apply:** cycgraph-style `read_keys` / `write_keys` permission scoping (fail-closed empty defaults).
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
| P11 | Zero-trust StateSlice (`read_keys`/`write_keys`) | **done this session** |
| P0.3 | Eval-gated memory write | **open** |
| P0.4 | Principled stopping (zenith) | **open** |
| P0.5 | Independent verify before promote | **open** |

## Top mined patterns (reuse, don’t vendor)

| Score | Repo | Pattern |
|------:|------|---------|
| 16 | phodal/routa | Evidence / delivery board |
| 16 | wshobson/agents | Multi-harness skill packs |
| 15 | mission-control | Ops cost + quality gates |
| 15 | MisterSmith | Supervised runtime + MCP |
| 15 | cycgraph / EDDI / zenith | Multi-budget, taint, slice, adaptive stop |
| 14 | open-multi-agent | Goal → task DAG + plan-replay |
| 13 | swarm / edict | Handoff + review veto |

## First apply slice (this session)

**P11 — Zero-trust state slicing**

1. `src/nexus/durability/state_slice.py` — `StateSlice`, `SliceError`, `slice_from_step`
2. Wire into `DurableAgent.view` / `write` / `read` / `run_step` / `meta_patch`
3. Tests: `tests/durability/test_state_slice.py`
4. Docs: this file + `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md`

### Usage sketch

```python
from nexus.durability import DurableAgent, RunBudget, StateSlice

agent = DurableAgent(
    budget=RunBudget(max_steps=5),
    slice=StateSlice.from_keys(read_keys=["goal"], write_keys=["plan"]),
    state={"goal": "ship", "secret": "nope"},
)
assert agent.view() == {"goal": "ship"}
agent.write("plan", {"n": 3})          # ok
agent.write("secret", "leak")          # SliceError
```

Or opt-in from task meta: `{"read_keys": [...], "write_keys": [...]}`.

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
