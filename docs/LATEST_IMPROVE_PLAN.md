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
| P1.3 | Consensus / multi-grader path (gossipcat) | **done** (`consensus.py`) |
| **P1.4** | **Formal context pack stage (arXiv 2508.08322)** | **done this session** |
| P1.5+ | Vault, agent single-source, supervised alive, board traces | open |
| P2 | Packaging, OpenAPI, anti-collusion, domain MCP demos | later |

---

## First apply slice this session — P1.4 context pack stage

**Goal:** Bound research notes + repo digests + grade + journal/memory into a single hard-budgeted pack *before* apply / mid-run prompts (context engineering, not full-tree dumps).

### Landed

| Surface | What |
|---------|------|
| `src/nexus/context_pack.py` | Sections, char budgets, total trim, research/repo loaders, `build_context_pack`, `prompt_block`, `nexus.context_pack/v1` |
| `src/nexus/improve_apply.py` | `ensure_context_packed` uses formal builder; writes `context_pack.json` + `.prompt.md` |
| `src/nexus/engine.py` | `context_pack(task_id)`; mid-run prompt inject when journal/meta set |
| `src/nexus/cli.py` | `nexus task context [--json\|--prompt\|--research\|--repos\|--out]` |
| `src/nexus/mcp_server.py` | tool `context_pack` |
| tests | `tests/test_context_pack.py` |

### Acceptance

- [x] Multi-source pack: goal / grade / research / repo_digest / journal / memory / prior
- [x] Per-section + total char budgets (default 10k chars) with truncate markers
- [x] IMPROVE_OURS + USE_LATEST digest parsers
- [x] Latest arXiv improve notes loader
- [x] improve_apply phase reuses builder; flat grade fields preserved
- [x] Operator CLI + JSON + prompt export
- [x] MCP parity tool
- [x] Full pytest green

### Patterns (no tree vendor)

- **arXiv 2508.08322** — context engineering for multi-agent LLM assistants
- **Denis2054/Context-Engineering-for-Multi-Agent-Systems** — sectioned context shape
- **phodal/routa** — evidence/context board export
- **Intelligent-Internet/zenith** — bound context before replan
- **wshobson/agents** — digests as reusable building blocks
- **mission-control** — operator inspect + export

### Demo

```bash
PYTHONPATH=src python3 -m nexus.cli task context <task_id>
PYTHONPATH=src python3 -m nexus.cli task context <task_id> --json
PYTHONPATH=src python3 -m nexus.cli task context <task_id> --prompt --research --repos
PYTHONPATH=src python3 -m nexus.cli demo self-improve-slice --fixture
```

---

## Next open (after this slice)

1. **P1.5** Secrets vault / supervised alive stop board auto-seed from IMPROVE_OURS  
2. Modularize MCP domains + eval CLI (AssetOpsBench)  
3. Packaging / OpenAPI (P2)

---

## Non-goals (still)

- No vendoring of scout_repos trees  
- No force-push / secrets in commits  
- No full mission-control UI rewrite  
- No unbounded dump of full paper PDFs or entire repos into prompts

---

*All patterns are ports of ideas from graded repos and arXiv notes, not wholesale dependency on foreign trees.*
