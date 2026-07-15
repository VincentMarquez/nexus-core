# Self-improve cycle — Grok 4.5

_Updated 2026-07-15 (hard-apply P1.2)_

Model: `grok-4.5` · mine: IMPROVE_OURS top repos · arXiv notes under `.nexus_state/arxiv_improve/`

---

## Reasoning plan (operator)

1. **Read evidence** — `docs/LATEST_IMPROVE_PLAN.md`, `.nexus_state/repo_mine/IMPROVE_OURS.md`, latest arXiv improve notes.  
2. **Pick first apply slice** — smallest PR-sized change with tests; prefer P0/P1 open rows.  
3. **Port patterns only** — from `.nexus_workspaces/scout_repos/`; do not vendor trees.  
4. **Hard apply** — code + tests; keep `pytest` green.  
5. **Document** — update this file, `docs/LATEST_IMPROVE_PLAN.md`, `docs/ALIVE_IMPROVEMENTS.md`.  
6. **Do not** force-push, commit secrets, or expand scope into P2 packaging unless asked.

---

## This cycle — First apply: P1.2 multi-agent task DAG

| Deliverable | Path |
|-------------|------|
| DAG helpers + snapshot | `src/nexus/steps.py` |
| Dependency-aware engine schedule + `action_order` + `dag()` | `src/nexus/engine.py` |
| Operator CLI | `nexus task dag` in `src/nexus/cli.py` |
| Tests | `tests/test_steps_dag.py`, `tests/test_engine.py`, `tests/test_task_cli.py` |

**Evidence drivers**

- Mine: open-multi-agent (task DAG), mission-control / routa (operator export)  
- arXiv: AOAD-MAT **2510.13343** (action order), context pack **2508.08322** (next), communication survey **2203.08975**  
- Prior landed: P0 improve-apply FSM, P1.1 ops spend plane, durability package  

**Commands**

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m nexus.cli task dag <id> --mermaid
```

**Next open:** P1.3 consensus grading · P1.4 context pack stage

---

## Cycle hygiene

- Prefer small, tested changes; `make test` / `pytest` green.  
- Restore plan docs if a full-cycle job truncates them.  
- Append every hard-apply to `docs/ALIVE_IMPROVEMENTS.md`.
