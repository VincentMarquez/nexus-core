# Self-improve cycle — Grok 4.5

_Updated 2026-07-15 (hard-apply P1.3)_

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

## This cycle — First apply: P1.3 consensus grading

| Deliverable | Path |
|-------------|------|
| Consensus module (findings, trust, aggregate) | `src/nexus/consensus.py` |
| Engine multi-grader + journal + export | `src/nexus/engine.py`, `src/nexus/config.py` |
| Operator CLI | `nexus task consensus` in `src/nexus/cli.py` |
| Tests | `tests/test_consensus.py`, `tests/test_task_cli.py` |

**Evidence drivers**

- Mine: gossipcat-ai (consensus + trust), mission-control / routa (operator export), IMPROVE_OURS top 20  
- arXiv: communication survey **2203.08975**, principles **2502.07165**, context pack **2508.08322** (next)  
- Prior landed: P0 improve-apply FSM, P1.1 ops spend, P1.2 task DAG, durability package  

**Commands**

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m nexus.cli task consensus <id> --findings
```

**Next open:** P1.4 context pack stage

---

## Cycle hygiene

- Prefer small, tested changes; `make test` / `pytest` green.  
- Restore plan docs if a full-cycle job truncates them.  
- Append every hard-apply to `docs/ALIVE_IMPROVEMENTS.md`.
