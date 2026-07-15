# Latest improve plan (from full self-improve cycle)

**Target:** `/path/to/nexus-core`  
**Focus:** multi-agent durability, MCP, mine/alive loops, grading, demos  
**Sources:** Grok-graded mined repos (IMPROVE_OURS) + arXiv research notes under `.nexus_state/arxiv_improve/`

---

## Status snapshot (2026-07-15)

| Tier | Item | Status |
|------|------|--------|
| P0 | Improve-apply phase FSM + decision audit + path jail | **done** (`improve_apply.py`) |
| P0.x | Budgets, taint, state slice, eval memory, stop, verify-promote | **done** (`durability/`) |
| P1.1 | Task/spend ops plane | **done** (`ops_store.py` + `nexus ops`) |
| P1.2 | Multi-agent task DAG | **done** (`steps.py` / `engine.dag`) |
| **P1.3** | **Consensus / multi-grader path (gossipcat)** | **done this session** |
| P1.4 | Formal context pack stage (arXiv 2508.08322) | open |
| P1.5+ | Vault, agent single-source, supervised alive, board traces | open |
| P2 | Packaging, OpenAPI, anti-collusion, domain MCP demos | later |

---

## First apply slice this session — P1.3 consensus grading

**Goal:** Independent multi-grader findings with trust weights before hard-apply / step promote, gossipcat-style (patterns only).

### Landed

| Surface | What |
|---------|------|
| `src/nexus/consensus.py` | `Finding`, `AgentTrust`, `ConsensusVerdict`, `ConsensusJudge`, role lenses, weighted aggregate, agreement signals (`nexus.consensus/v1`) |
| `src/nexus/config.py` | `consensus_judge` (default on), `consensus_min_graders`, `consensus_max_graders` |
| `src/nexus/engine.py` | Uses `ConsensusJudge` when enabled; journal `consensus` events; `consensus(task_id)` export |
| `src/nexus/cli.py` | `nexus task consensus [--json] [--findings]` |
| tests | `tests/test_consensus.py`, `tests/test_task_cli.py::test_task_consensus_cli` |

### Acceptance

- [x] ≥2 independent graders when panel has capacity (else degraded flag)
- [x] Role lenses produce deterministic score divergence (adversary vs tester)
- [x] Trust weights nudge after agreement/disagreement
- [x] Step `_verdict` carries `findings` + `agreement_ratio` + `counts`
- [x] Operator `task consensus` + JSON pack
- [x] Opt-out via `Settings.consensus_judge=False` (single RubricJudge)
- [x] Full pytest green

### Patterns (no tree vendor)

- **gossipcat-ai/gossipcat-ai** — consensus signals, findings, adaptive trust
- **openai/swarm** — multi-agent coordination without shared brain
- **arXiv 2203.08975** — multi-agent communication / agreement
- **arXiv 2502.07165** — principle-based multi-agent prompting
- NEXUS cross-vendor judge preference

### Demo

```bash
PYTHONPATH=src python3 -m nexus.cli task list
# after any durable run:
PYTHONPATH=src python3 -m nexus.cli task consensus <task_id>
PYTHONPATH=src python3 -m nexus.cli task consensus <task_id> --json
PYTHONPATH=src python3 -m nexus.cli task consensus <task_id> --findings
```

---

## Next open (after this slice)

1. **P1.4** Context pack stage (bound research + digest + grades before apply)  
2. Modularize MCP domains + eval CLI (AssetOpsBench)  
3. Packaging / OpenAPI / secrets vault (P1.5 / P2)

---

## Non-goals (still)

- No vendoring of scout_repos trees  
- No force-push / secrets in commits  
- No full mission-control UI rewrite  
- No live multi-LLM call matrix in unit tests (offline role lenses)

---

*All patterns are ports of ideas from graded repos and arXiv notes, not wholesale dependency on foreign trees.*
