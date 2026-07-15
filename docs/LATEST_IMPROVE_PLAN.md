# Latest improve plan (from full self-improve cycle)

_Generated 2026-07-15 · Grok 4.5 hard-apply worker · 10 repos + 10 arXiv_

## Evidence

| Source | Path / notes |
|--------|----------------|
| Repo mine plan | `.nexus_state/repo_mine/IMPROVE_OURS.md` (mission-control, cycgraph, rojak, MisterSmith, routa, AgenticGoKit, …) |
| Latest USE | `.nexus_state/repo_mine/USE_LATEST.md` |
| arXiv (tool-use / MAS) | `.nexus_state/arxiv_improve/improve-rx-7afb87b115.md` |
| Prior papers (durability/CEMA/PROV) | `improve-rx-beb4144b26`, `rx-5b885ba84d`, `rx-703f35888a`, … |
| Prior slices landed | P0 atomic journal → P1 handoff/veto/CLI → P2 replay/explain → P3 cost/thresholds → P4 prov/verify |

## Graded priorities

### P0 — already shipped (durability core)
Atomic write-then-rename checkpoints, JSONL event journal, trust flush, optional memory decay.

### P1 — already shipped (multi-agent communication)
Handoff events, review veto, journal context on resume, `nexus task list|show|events`.

### P2 — already shipped (operator observability)
`replay()`, `explain()`, `why` on step_complete.

### P3 — already shipped (cost + value)
`cost()`, score/tokens/thresholds on journal, judge threshold constants.

### P4 — already shipped (provenance + integrity)
`provenance()` PROV-AGENT export, `verify()` checkpoint↔journal gate.

### P5 — First apply this session (budget hard-stop + call-graph)
**Why:** mined repos (cycgraph budgets, open-multi-agent `maxTokenBudget`, mission-control spend caps, MisterSmith budget enforcer) + arXiv (call-graph / space-time profiling for MAS; governed reward / tool privilege themes). Cost rollup (P3) was observational only — production agents need a per-task hard stop and a readable agent interaction graph.

| Change | Detail |
|--------|--------|
| `task.meta["max_tokens"]` / constraint `max_tokens=N` | Hard-fail after step when spend exceeds cap (may overshoot by one step) |
| Journal `budget` event | Audit row with phase pre_step/post_step |
| `cost()` budget fields | `max_tokens`, `remaining_tokens`, `budget_exhausted` |
| `graph(task_id)` | Nodes/edges/sequence + mermaid flowchart (`nexus.graph/v1`) |
| CLI | `nexus task graph [--json] [--mermaid]`; cost shows budget line |

### P6 — later (do not expand this session)
- Least-privilege tool selection gate (arXiv 2606.20023)
- Plan reuse store for successful step skeletons (arXiv 2512.21309)
- Soft budget / model downgrade (MisterSmith SoftCap)

## First apply slice (this session)

1. `src/nexus/engine.py` — `task_max_tokens()`, pre/post budget gates, `graph()`, cost budget fields  
2. `src/nexus/cli.py` — `nexus task graph`  
3. Tests — `tests/test_engine.py`, `tests/test_task_cli.py`  
4. Docs — this plan, `SELF_IMPROVE_CYCLE.md`, `ALIVE_IMPROVEMENTS.md`, cookbook crash-resume  

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q
nexus task cost <id>
nexus task graph <id> --mermaid
```

## Out of scope

- Vendoring scout_repos trees  
- Force-push / secrets  
- Global usage budget rewrite (already in `usage.py` / `alive`)  
