# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 · model `grok-4.5` · repos=10 · arXiv=10_

## Cycle goal

Self-improve nexus-core from mined multi-agent repos and arXiv papers: grade patterns, reason a scoped plan, hard-apply small tested slices, keep pytest green.

## Inputs

1. **Repo mine** — `.nexus_state/repo_mine/IMPROVE_OURS.md` + `USE_LATEST.md`  
   Top patterns: mission-control (spend/ops), cycgraph (token budgets), open-multi-agent (`maxTokenBudget`), MisterSmith (budget hard-cap), routa (traces), rojak (durability), AgenticGoKit (telemetry).
2. **arXiv** — latest `improve-rx-7afb87b115` (tool-use / MAS profiling / plan reuse) plus prior durability, CEMA, PROV-AGENT, value-system papers.
3. **Prior hard-apply** — P0–P4 already on main path (journal → handoff/veto → replay/explain → cost → provenance/verify).

## Reasoning summary

| Gap | Pattern source | Decision |
|-----|----------------|----------|
| Cost is observe-only | cycgraph / OMA maxTokenBudget / mission-control | P5 per-task `max_tokens` hard-stop |
| No agent interaction view | MAS call-graph + space-time papers; routa traces | P5 `graph()` + mermaid |
| Plan reuse / least-privilege tools | arXiv 2512.21309 / 2606.20023 | Defer to P6 (larger surface) |

## First apply slice (landed)

- `src/nexus/engine.py`
  - `task_max_tokens()` from `meta.max_tokens` or constraint `max_tokens=N`
  - Pre-step and post-step budget gates; journal `budget` + `failed` events
  - `cost()` exposes `max_tokens` / `remaining_tokens` / `budget_exhausted`
  - `graph(task_id)` → nodes, handoff edges, space-time sequence, mermaid (`nexus.graph/v1`)
- `src/nexus/cli.py` — `nexus task graph [--json] [--mermaid]`; cost budget line
- Tests: budget hard-stop, graph profile, CLI graph/cost budget
- Docs: `LATEST_IMPROVE_PLAN.md`, this file, `ALIVE_IMPROVEMENTS.md`, cookbook `01_crash_resume.md`

## Verify

```bash
PYTHONPATH=src python3 -m pytest -q
```

## Next cycle candidates

1. Soft budget / downgrade policy (MisterSmith SoftCap)  
2. Plan skeleton reuse after successful completes  
3. Tool privilege tier on agent panels (least privilege)  
