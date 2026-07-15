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
| **P1.2** | **Multi-agent task DAG** | **done this session** |
| P1.3 | Consensus / multi-grader path (gossipcat) | open |
| P1.4 | Formal context pack stage (arXiv 2508.08322) | open |
| P1.5+ | Vault, agent single-source, supervised alive, board traces | open |
| P2 | Packaging, OpenAPI, anti-collusion, domain MCP demos | later |

---

## First apply slice this session — P1.2 multi-agent task DAG

**Goal:** Goal → ordered agent steps with real dependency scheduling, explicit action order, and operator inspect.

### Landed

| Surface | What |
|---------|------|
| `src/nexus/steps.py` | `completed_set`, `has_dag`, `validate`, `next_ready`, `blocked`, `pending`, `prior_keys`, `dependency_edges`, `mermaid`, `dag_snapshot` (`nexus.dag/v1`) |
| `src/nexus/engine.py` | Schedule via `policy.ready(completed)`; fail-closed on invalid/deadlocked DAG; `meta.action_order[]`; deps-scoped prior context; `dag(task_id)` |
| `src/nexus/cli.py` | `nexus task dag [--json] [--mermaid]` |
| tests | `tests/test_steps_dag.py`, `tests/test_engine.py` (diamond + invalid), `tests/test_task_cli.py::test_task_dag_cli` |

### Acceptance

- [x] Default 10-step policy validates (no unknown deps / cycles)
- [x] Diamond DAG runs in stable order (lowest-number ready first)
- [x] `action_order` persisted on task meta + `step_complete.depends_on`
- [x] Invalid policy fails closed at run start
- [x] Operator `task dag` + mermaid export
- [x] Full pytest green

### Patterns (no tree vendor)

- **open-multi-agent/open-multi-agent** — goal → task DAG, inspectable plan, deps-scoped memory
- **AOAD-MAT (arXiv 2510.13343)** — explicit logged action order
- **mission-control / routa** — operator board / export surfaces

### Demo

```bash
PYTHONPATH=src python3 -m nexus.cli task list
# after any durable run:
PYTHONPATH=src python3 -m nexus.cli task dag <task_id>
PYTHONPATH=src python3 -m nexus.cli task dag <task_id> --json
PYTHONPATH=src python3 -m nexus.cli task dag <task_id> --mermaid
```

---

## Next open (after this slice)

1. **P1.3** Consensus grading (gossipcat independent findings + trust weights) before fully autonomous hard-apply  
2. **P1.4** Context pack stage (bound research + digest + grades before apply)  
3. Modularize MCP domains + eval CLI (AssetOpsBench)  
4. Packaging / OpenAPI / secrets vault (P1.5 / P2)

---

## Non-goals (still)

- No vendoring of scout_repos trees  
- No force-push / secrets in commits  
- No full mission-control UI rewrite  
- No multi-grader consensus in this slice  

---

*All patterns are ports of ideas from graded repos and arXiv notes, not wholesale dependency on foreign trees.*
