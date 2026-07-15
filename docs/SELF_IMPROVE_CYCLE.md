# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 18:32 UTC · hard-apply P6 by Grok 4.5 CLI worker_

Model: `grok-4.5` · repos=10 · arXiv=10

---

## Evidence (this cycle)

### Mined repos (score ≥ 10, local clones under `.nexus_workspaces/scout_repos/`)

| Repo | Score | Pattern to port |
|------|------:|-----------------|
| wshobson/agents | 16 | multi-harness validate/smoke tooling |
| phodal/routa | 16 | workspace board: goals/tasks/traces/**evidence** |
| builderz-labs/mission-control | 15 | tasks, spend, **export**, operator inspect |
| IBM/AssetOpsBench | 15 | eval harness + multi-agent evidence |
| labsai/EDDI | 15 | config-driven orchestration + audit |
| MattMagg/MisterSmith | 15 | supervision, CLI/HTTP operator surface |
| AgenticGoKit/AgenticGoKit | 14 | workflows, multi-LLM, observability |
| StreetLamb/rojak | 14 | Temporal durability + HITL resume |
| parijatmukherjee/openclaw-hawkins | 14 | durable state + decay memory |
| wmcmahan/cycgraph | 14 | budgets, zero-trust slices, eval gates |

### arXiv papers (job `rx-b98ae48d28` + prior ledger)

Notable for apply:

- **2603.13189** — LLM Constitutional Multi-Agent Governance → norms / gates
- **1709.02018** — Normative MAS (Kelsenian / NorMAS) → structured constraints
- **nlin/0611054** — Trust-based recommendation → trust already on path
- **2412.20138** — TradingAgents multi-agent society → role audit trail
- Prior: PROV-AGENT, CEMA, context engineering, plan-replay, call-graph, budgets

## Already landed (P0–P5)

- **P0** atomic checkpoints + JSONL journal + decay memory
- **P1** handoff / review veto / journal context / `nexus task list|show|events`
- **P2** `replay` + `explain` + `why` on step_complete
- **P3** `cost` rollup + score/tokens/thresholds
- **P4** `provenance` + `verify` integrity
- **P5** `max_tokens` hard-stop + `graph` call-graph / mermaid

## First apply slice (this session) — **P6 evidence pack + norms**

**Goal:** one portable operator document that answers “what happened, under which rules, is it delivery-ready?” without re-running agents.

| Piece | Where | Shape |
|-------|--------|--------|
| `task_norms(task)` | `src/nexus/engine.py` | parse `require:` / `deny:` / `must:` / `max_tokens=` + meta → rules |
| `engine.evidence(id)` | `src/nexus/engine.py` | `nexus.evidence/v1` pack: task, norms, gates, story, cost, verify, timeline, prov, graph |
| `nexus task evidence` | `src/nexus/cli.py` | human summary · `--json` · `--compact` · `--out PATH` |
| tests | `tests/test_engine.py`, `tests/test_task_cli.py` | norms parse, ready/not-ready, CLI write |

### Readiness gates (routa Entrix-inspired)

- `integrity_ok` — `verify().ok`
- `budget_ok` — not budget-exhausted
- `has_timeline` — journal non-empty
- `completed` / `terminal` / `no_veto`
- `ready` — completed ∧ integrity ∧ budget ∧ timeline

### Patterns (not vendored trees)

- routa evidence board / delivery readiness
- mission-control search-and-export
- AssetOpsBench evaluation evidence
- NorMAS + constitutional multi-agent governance (structured norms, not SDL)

## P0 / deferred (next cycles)

1. **HITL CLI** — engine already has `waiting_human` + `resume(approve=)`; expose `nexus task resume --approve|--reject` (rojak).
2. **Norm enforcement** — optional fail-closed on `require:` / `deny:` at step boundaries (constitutional gate).
3. **Trust-weighted agent resolve** — use `TrustLog` scores when multiple agents can run a step.
4. **Wall-clock budget** — `max_wall_s` alongside `max_tokens` (cycgraph multi-budget).
5. **Plan reuse** — arXiv 2512.21309 style: cache successful step plans by objective hash.

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q
nexus task evidence <id>
nexus task evidence <id> --json
nexus task evidence <id> --compact --out /tmp/pack.json
```

## Done criteria

- [x] First apply slice implemented with tests
- [x] `pytest` green
- [x] `docs/LATEST_IMPROVE_PLAN.md` + `docs/ALIVE_IMPROVEMENTS.md` updated
- [ ] No force-push / no secrets / no vendored upstream trees
