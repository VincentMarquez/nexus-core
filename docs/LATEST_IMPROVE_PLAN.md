# Latest improve plan (from full self-improve cycle)

# NEXUS Self-Improvement Plan  
**Grok 4.5 hard-apply loop — papers + mined repos → durable multi-agent core**

---

## Landed this session (First apply slice — 2026-07-15)

### Prior slice (claims + FTS) — still green

| Pass criterion | Status |
|----------------|--------|
| Invalid grades (missing claims / out-of-range scores) fail validation | ✅ `grade_artifact.validate_grade(require_claims=…, check_ranges=…)` |
| MCP search returns wshobson “Markdown marketplace” claim | ✅ `evidence_fts.search_evidence` / MCP `search_evidence` |
| MCP search returns arXiv **2511.15755** “deterministic decision package” | ✅ fixture `fixtures/mine_eval/grades_with_claims.json` |
| Quality gates offline (no live Grok API) | ✅ `make grade-validate` · `make mcp-smoke` · `make test-quality` |

### This session — P1.2/P1.3: FTS apply select + role gate + board

| Pass criterion | Status |
|----------------|--------|
| Rank apply candidates by grade score + FTS evidence | ✅ `apply_select.select_candidates` |
| Fail closed without evidence when required | ✅ skipped rows + `require_evidence` |
| Role separation grader ≠ implementer ≠ verifier | ✅ `check_roles` / `RoleCollusionError` (anti-collusion **2601.00360**) |
| Decision package with confidence + evidence_refs | ✅ `decision_package` / `gate_apply` (**2511.15755**) |
| Optional RunBudget hard-stop before apply | ✅ `gate_apply(budget=…)` |
| routa-lite board CLI + MCP | ✅ `nexus improve board` · MCP `improve_board` |
| pytest green | ✅ 418 passed |

**Modules:** `src/nexus/apply_select.py`, CLI `select|board|decide`, MCP `apply_select` / `improve_board`, `tests/test_apply_select.py`.

**Next PRs:** wire `decision_package` into `worktree_apply` / alive `self_approve` · adaptive stop signals on board · preference pairs for rubric learning.

---

## Executive summary

- **Close the research→mine→grade→apply loop** by treating Grok-graded repos (scores 13–16) and arXiv multi-agent papers as *pattern sources*, not vendored trees: port small modules + tests into `nexus-core` durability, MCP, mine/alive, and grading surfaces.
- **P0 durability substrate** comes from MisterSmith (supervised runtime + durable stores), cas (worktree isolation + MCP SQLite/FTS), rojak-style checkpointing patterns (via tiger_cowork/forge), and papers on interleaved verification + hierarchical control — make long-running agent jobs crash-safe and replayable.
- **P0 control plane + grading** ports mission-control (spend/runtime governance, OpenAPI parity, quality gates), Network-AI (adapters/guardrails/budgets), wshobson/agents (Markdown single-source plugins + generate/validate), and Thucy/incident-orchestration papers (claim verification, deterministic multi-agent decision support) into mine_eval scoring and alive demos.
- **P1 MCP + memory + handoffs** reuses soul (cross-session ledger/memory MCP), EDDI (config-driven MCP/A2A middleware), AssetOpsBench (domain MCP + eval harness), swarmclaw (skills/delegation/schedules), and anti-collusion/causal-explanation papers for auditable multi-agent coordination.
- **First apply slice** is deliberately PR-sized: Markdown skill/plugin manifest + Grok grade schema hardening + one MCP FTS context tool + quality-gate tests — proves the self-improve loop without a monorepo rewrite. **(Landed: grade claims + FTS evidence MCP + make gates.)**

---

## 10 arXiv papers — what to steal for this codebase

| # | arXiv id | Idea (from evidence) | Concrete NEXUS change |
|---|----------|----------------------|------------------------|
| 1 | **2511.15755** | Multi-agent LLM orchestration for **deterministic, high-quality incident-style decision support** | Add a fixed role graph (triage → investigator → verifier → decider) in alive/orchestrator loops; require a terminal “decision package” artifact (claims + evidence refs + confidence) before mark-complete. Wire into grading as a *determinism* rubric dimension. |
| 2 | **2512.03278** | **Thucy**: multi-agent **claim verification** over structured stores | Port claim→evidence→verdict pipeline into mine_eval/grading: every mined repo score must cite file/path evidence; store claims in SQLite/FTS (cas-style) so Grok grades are auditable, not free-form prose only. |
| 3 | **2506.03053** | **MAEBE**: multi-agent **emergent behavior** framework | Instrument mine/alive loops with emergent-behavior telemetry (unexpected handoffs, thrash, premature stop); feed into alive “stop/replan” policy inspired by zenith-style control loops. |
| 4 | **2510.13343** | **AOAD-MAT**: order of **action decisions** among agents | Explicit **action-order scheduler** in multi-agent runs (who acts when); serialize critical sections (git worktree writes, grade commits) to avoid racey concurrent applies. |
| 5 | **2302.10809** | **Causal explanations** for sequential multi-agent decisions | Persist causal chain records on every supervisor decision (why worker A, why replan, why fail); surface in board/trace UI (routa pattern) and in Grok grade rationales. |
| 6 | **1301.6431** | **Automatic verification** of parameterised interleaved multi-agent systems | Lightweight **interleaving safety checks** for durable workflows: forbid illegal concurrent tool use (e.g. two writers same worktree); property tests over mine→grade→apply state machine. |
| 7 | **2303.16641** | Hierarchical game-theoretic decisions under **adversarial agents** | Guardrail budgets + adversarial mine inputs: treat untrusted mined code as adversarial; sandbox + quota + path hardening (tiger_cowork/lumen patterns) before apply. |
| 8 | **2602.04518** | Learning **value systems** via preference / inverse RL | Make Grok grading preference-explicit: store preference pairs (better/worse apply candidates) and evolve rubric weights for idea/skill scores used in mine_eval. |
| 9 | **2601.00360** | Map human **anti-collusion** mechanisms to multi-agent AI | Split grader vs implementer roles; require independent verifier agent before merge of self-improve patches; log collusion-risk signals (same model path grading its own apply without separation). |
| 10 | **2603.20143** | Multi-agent orchestration: **perception → generative recomposition** for expert inspection | Two-phase mine loop: (1) perception/scout digest, (2) recompose into NEXUS-specific port plan + PR slice — already half-present in IMPROVE_OURS; formalize as a durable workflow stage pair. |

*(Also present in evidence but deferred to P2 research: **2008.06604** hierarchical decomposition control; **2604.03350** multi-stage stochastic ABM workflow; **2602**/other lower-signal IDs.)*

---

## 10 GitHub repos — portable patterns

Top scored sources from IMPROVE_OURS / mine_eval (patterns only, not whole trees):

| Repo | Score | Pattern to port | Where to port in NEXUS |
|------|------:|-----------------|------------------------|
| **wshobson/agents** | 16.0 | Single Markdown source → generate adapters; Makefile generate/validate/test; installable skills/agents marketplace | `skills/` or `plugins/` + `Makefile` targets; multi-harness adapters for Claude/Codex/Cursor/Grok CLIs; feed mine_eval “skill” score |
| **builderz-labs/mission-control** | 15.0 | Control plane for **tasks, spend, runtimes**; OpenAPI parity checks; CLI/MCP/TUI; full quality-gate tests | Operator surface over alive/mine jobs; budget/spend counters next to Grok calls; CI quality-gate parity tests |
| **IBM/AssetOpsBench** | 15.0 | Domain **MCP server + multi-backend eval/bench** harness | `mcp/` eval servers; standardized bench suite for mine_eval and self-improve demos |
| **phodal/routa** | 15.0 | **Board-first** goals/tasks/traces/evidence; dual-backend monorepo discipline | Demo board for improve backlog; every apply produces goal→task→trace→evidence row |
| **labsai/EDDI** | 15.0 | Config-driven multi-agent middleware; **MCP/A2A/OpenAPI/OAuth**; strong CI/security tests | Config schemas for agent graphs; MCP+OpenAPI packaging; security test hooks for untrusted mine inputs |
| **codingagentsystem/cas** | 15.0 | Supervisor/worker coding factory; **isolated git worktrees**; **MCP SQLite/FTS** context layer | Worktree-isolated apply PRs; MCP context DB for research digests + grade evidence |
| **ahmedEid1/lumen** | 15.0 | Goal→brief→**idempotent** build→citation RAG→**decision audit**; migration guards; quotas; MCP packaging | Idempotent mine/apply stages; decision audit log; quota on LLM/grade calls; phased migration flags |
| **Jovancoding/Network-AI** | 15.0 | Heterogeneous **framework adapters**; **guardrails/budgets**; dual packaging; strong CI | Adapter layer over agent CLIs; per-run budgets in alive; guardrail middleware before tools |
| **MattMagg/MisterSmith** | 15.0 | Supervised multi-agent **runtime OS**; durable store; **MCP**; operator surfaces | Long-running supervised workers for mine/alive; crash recovery; operator health endpoints |
| **swarmclawai/swarmclaw** | 14.0 | Memory, MCP, **skills, delegation, schedules**, multi-provider product packaging | Skills registry + scheduled re-mine/re-grade jobs; delegation graph for self-improve roles |

**Honorable patterns (P1–P2, still in evidence):**  
soul (14) cross-session memory + immutable ledger MCP; tiger_cowork (14) atomic stores/path hardening/checkpoint cleanup; forge (14) HITL kanban + worktrees; zenith (13) adaptive stop/replan; rojak (14) Temporal-style durable workflows + HITL; AgenticGoKit (14) OTel streaming agents; openai/swarm (13) clean handoff primitive.

---

## Prioritized engineering backlog

### P0 — Prove the self-improve loop (durability + grade + MCP context)

| Item | Touch files / modules (concrete targets) |
|------|------------------------------------------|
| **P0.1 Worktree-isolated apply** (cas, forge) | `src/` or `nexus/` apply runner; git worktree helper module; fail closed if dirty tree; unit tests for isolation |
| **P0.2 Durable job state** (MisterSmith, tiger_cowork, lumen) | Job/run store (SQLite or existing PG); atomic status transitions (`pending→running→graded→applied|failed`); checkpoint + cleanup hooks |
| **P0.3 Grok grade schema + evidence claims** (Thucy paper, wshobson validate, mission-control gates) | Grade JSON schema (`idea`, `skill`, `total`, `method=grok:grok-4.5`, `claims[]` with path anchors); reject grades without evidence; golden fixtures from mine_eval digests |
| **P0.4 MCP SQLite/FTS context** (cas, soul, AssetOpsBench) | MCP server package: index research reports + repo digests; tools `search_context`, `get_claim_evidence`; package + smoke test |
| **P0.5 Quality-gate CI** (mission-control, Network-AI, EDDI) | `make validate` / `make test-quality`: schema validate, OpenAPI/MCP surface parity if APIs exist, unit+integration for mine→grade dry-run |

### P1 — Control plane, budgets, board, anti-collusion

| Item | Touch files / modules |
|------|----------------------|
| **P1.1 Spend/runtime budgets** (Network-AI, mission-control, lumen quotas) | Budget middleware around LLM/grade calls; per-job caps; demos show budget exhaustion path |
| **P1.2 Board/trace/evidence UI or CLI** (routa, Hermes-Studio patterns) | CLI or minimal board: goals, tasks, traces, evidence links for each self-improve run |
| **P1.3 Role separation grader ≠ applier** (2601.00360, 2511.15755) | Pipeline config: distinct roles + handoff records; verifier stage before merge |
| **P1.4 Markdown skills marketplace** (wshobson/agents, swarmclaw) | `skills/*.md` → generated adapters; validate/test pipeline; 3–5 NEXUS skills (mine, grade, apply, demo, mcp-index) |
| **P1.5 Adaptive stop/replan** (zenith, MAEBE, AOAD-MAT) | Alive loop policy: max steps, thrash detector, replan trigger, ordered action schedule |
| **P1.6 Causal decision log** (2302.10809, lumen audit) | Append-only decision audit (why promote score, why skip repo, why apply slice) |

### P2 — Platform polish & research depth

| Item | Touch files / modules |
|------|----------------------|
| **P2.1 Config-driven agent graphs** (EDDI, AgenticGoKit) | YAML/JSON agent graph + MCP wiring; A2A-style handoff primitive (openai/swarm simplicity) |
| **P2.2 OTel / streaming traces** (AgenticGoKit) | Trace export for multi-agent runs; correlate with board evidence |
| **P2.3 Preference-based rubric learning** (2602.04518) | Store pairwise preferences over applies; optional weight update offline |
| **P2.4 Domain bench pack** (AssetOpsBench) | NEXUS self-improve bench: N papers + M repos → graded backlog → apply success metrics |
| **P2.5 HITL approval gate** (forge, rojak, Hermes-Studio) | Optional human approval before hard-apply on main |
| **P2.6 Hierarchical / adversarial sims** (2303.16641, 2008.06604) | Stress tests: malicious digests, concurrent writers, hierarchical supervisor decomposition |

---

## First apply slice  
### Smallest PR-sized change that proves the loop

**Goal:** One mergeable PR that (1) hardens Grok grades into structured, evidence-backed artifacts, (2) exposes them via MCP FTS search, (3) validates with tests — without rewriting orchestration.

### Scope (do this only)

1. **Grade schema module**  
   - Define `GradeResult` / claims schema matching existing mine_eval fields: `score`, `idea`, `skill`, `method`, plus `claims: [{statement, path, quote?}]`.  
   - Loader that reads graded digests under `.nexus_workspaces/mine_eval/*` and validates.

2. **MCP context tool (minimal)**  
   - SQLite + FTS index over: research report snippets + top-10 IMPROVE_OURS repo digests.  
   - Tools: `index_workspace`, `search_evidence(query)`.  
   - Pattern source: **cas** MCP SQLite/FTS + **soul** ledger simplicity.

3. **Validate/generate Makefile targets** (wshobson/agents style)  
   - `make grade-validate` — schema check on fixtures.  
   - `make mcp-smoke` — index + one search.

4. **One demo fixture**  
   - Frozen fixture from evidence: e.g. `wshobson__agents` score=16 and paper `2511.15755` claim row → searchable after index.

5. **Explicit non-goals for this PR**  
   - No full worktree apply engine, no board UI, no Temporal, no vendoring entire repos.

### Files / modules likely to touch
- `src/.../grading/` or `nexus/grade/` — schema + validate  
- `src/.../mcp/context/` or `mcp/nexus_context/` — SQLite/FTS MCP server  
- `tests/grading/` + `tests/mcp/` — unit + smoke  
- `Makefile` or `scripts/quality_gate.sh` — validate targets  
- `fixtures/mine_eval/` — 1–2 sanitized grade JSON samples from evidence  
- Brief note in `docs/self-improve.md` (only if docs already exist; otherwise PR description only)

### Tests to run
```text
# unit
pytest tests/grading -q          # or cargo test / go test per stack
pytest tests/mcp/test_context -q

# quality gates
make grade-validate
make mcp-smoke

# regression (existing suite)
make test                        # or project’s default CI entry
```

**Pass criteria:**  
- Invalid grades (missing claims / out-of-range scores) fail validation. ✅  
- MCP search returns the wshobson/agents “Markdown marketplace” claim and the 2511.15755 “deterministic decision package” claim from fixtures. ✅  
- CI green; no dependency on live Grok API for unit tests (fixtures only). ✅  

### Landed files (this slice)
- `src/nexus/grade_artifact.py` — `claims[{statement,path,quote?}]`, score range checks, `require_claims`
- `src/nexus/evidence_fts.py` — `index_workspace`, `search_evidence`, `grade_validate_fixtures`, `smoke_search`
- `src/nexus/mcp_server.py` — tools `index_workspace`, `search_evidence`
- `src/nexus/load_mine_eval.py` — passthrough claims from fixtures
- `fixtures/mine_eval/grades_with_claims.json` — wshobson/agents 16 + paper 2511.15755
- `Makefile` — `grade-validate`, `mcp-smoke`, `test-quality`
- `tests/test_evidence_fts.py`

### Why this slice proves the loop
It binds **mine_eval grades (Grok 4.5)** → **auditable claims (Thucy-style)** → **MCP-retrievable context (cas/soul)** → **quality gate (mission-control)** — the same data path a later P0.1 worktree apply will consume when hard-applying prioritized backlog items.

---

### Suggested next PRs after first slice
1. Worktree-isolated apply runner + idempotent stage machine (cas + lumen). ✅ (prior cycles)  
2. Budget + role-separated verifier before apply (Network-AI + anti-collusion paper). ✅ **this session**  
3. Board CLI for goal/task/trace/evidence (routa) + adaptive stop/replan (zenith/MAEBE). ✅ board CLI; stop/replan polish still open  

### Landed files (this session — apply select + board)
- `src/nexus/apply_select.py` — select / gate / decision_package / improve_board
- `src/nexus/cli.py` — `nexus improve select|board|decide`
- `src/nexus/mcp_server.py` — tools `apply_select`, `improve_board`
- `src/nexus/tool_catalog.py` — privilege tags (read)
- `tests/test_apply_select.py` — 14 offline tests

```bash
nexus improve select --query "Markdown marketplace" --json
nexus improve board
nexus improve decide --repo wshobson/agents --json
PYTHONPATH=src python3 -m pytest -q
```

---

*Sources restricted to EVIDENCE: Grok-graded mine_eval repos, IMPROVE_OURS shortlist, and arXiv IDs present in research export. No invented paper IDs or repos.*