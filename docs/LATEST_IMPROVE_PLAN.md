# Latest improve plan (from full self-improve cycle)

The request was truncated; reading the full prompt file for complete evidence before writing the plan.Reading the full offloaded prompt for complete paper and repo evidence.# NEXUS Self-Improvement Plan  
**Source of truth:** Grok-graded mined repos + arXiv research rows in EVIDENCE only  
**Target:** `/path/to/nexus-core`  
**Focus:** multi-agent durability, MCP, mine/alive loops, grading, demos  

---

## Executive summary

- **Close the self-improve loop end-to-end:** research (arXiv) + mine (repos) → Grok 4.5 grade → prioritized port of *patterns* (not trees) → small PR with tests → demo that the alive/mine loop got better.
- **Steal durability first, features second:** lumen (idempotent build + migration-phase guards + decision audit), MisterSmith (supervised execution + durable state), praktor (atomic/isolated agents + vault), tiger_cowork (atomic stores + path/zip safety + session cleanup) are the highest-leverage reliability patterns for NEXUS workspaces and long-running agents.
- **Make MCP a first-class control surface:** Network-AI, mission-control, claude-team-mcp, EDDI, AssetOpsBench, and praktor all show modular MCP servers, CLI parity, and operator I/O—NEXUS should treat MCP as the stable API for mine/alive/grade/demo tools, not an afterthought adapter.
- **Harden grading and consensus:** gossipcat (independent findings + source-backed consensus + adaptive agent-trust), lumen (honest public evals + decision audit), AssetOpsBench (multi-framework eval CLIs), and cycgraph (evals + Postgres durability) map directly onto Grok grading, mine_eval scoring, and demo truthfulness.
- **Ship one PR-sized “first apply slice”** that proves the loop: durable/idempotent mine job state + migration-phase guards + a single decision-audit artifact, with unit tests and a demo script—before larger orchestration or monorepo packaging work.

---

## 10 arXiv papers — what to steal for this codebase

Selected from EVIDENCE research rows (ids and titles as given; ranked by report score then relevance to durable multi-agent orchestration). Do not treat low-score theory papers as implementation specs—extract only portable control/eval ideas.

| # | arXiv id | Idea (from title / topic) | Concrete NEXUS change |
|---|----------|---------------------------|------------------------|
| 1 | **2510.13343** (score 7) | AOAD-MAT: multi-agent decisions depend on **order of action** | In alive/mine orchestration, make agent turn order explicit and logged (scheduler policy + audit field `action_order[]`); add tests that reordering changes outcomes only when intended, never silently. |
| 2 | **2508.08322** (score 6) | **Context engineering** for multi-agent LLM code assistants (tooling stack of research → notes → code agents) | Formalize a “context pack” stage before mine/alive apply: pack repo digest, grade scores, and research report excerpts into a bounded prompt/context artifact; store packs under research/mine workspaces for replay. |
| 3 | **2412.06333** (score 6) | Multi-agent durable orchestration LLM (NEXUS research hit; full title truncated in EVIDENCE) | Use as **durability checklist**: checkpoint agent graphs mid-run; resume mine_eval jobs from last committed phase rather than full restart. |
| 4 | **2512.03278** (score 4) | Thucy: multi-agent **claim verification** over relational DBs | For Grok grading outputs, require claim→evidence links (repo path, score field, test name); reject “orphan” grade claims in demo/public evals. |
| 5 | **2602.04518** (score 4) | Learning agent **value systems** via preference / inverse RL | Extend mine grading beyond scalar `score/idea/skill`: optional preference pairs (“A more reusable than B”) stored with Grok method tag for later ranker tuning. |
| 6 | **2303.16641** (score 4) | Hierarchical game-theoretic decisions under **adversarial** agents | Add a “hostile workspace” demo path: sandbox path/zip safety + deny-by-default tool policy when mine_eval clones untrusted trees (aligns with tiger_cowork safety patterns). |
| 7 | **2511.15755** (score 3) | Multi-agent LLM orchestration for **deterministic** incident-response decisions | Alive-loop “incident” mode: fixed role graph (detect → isolate → fix → verify), deterministic handoffs, structured decision log suitable for demos. |
| 8 | **2506.03053** (score 3) | MAEBE: multi-agent **emergent behavior** framework | Instrument mine/alive runs for emergence metrics (unexpected tool use, loop thrash, consensus flip rate); surface in grading/demo dashboard, not only final score. |
| 9 | **2603.20143** (score 3) | Multi-agent orchestration: perception + generative recomposition (inspection domain) | Split mine pipeline into **perceive** (clone/digest) → **judge** (Grok grade) → **recompose** (IMPROVE_OURS plan → apply slice); keep phases idempotent and auditable. |
| 10 | **2302.10809** (score 2) | **Causal explanations** for sequential multi-agent decisions | Decision-audit records should support “why this port / why this agent” chains (cause edges from grade fields → chosen pattern → files touched)—feeds honest demos and lumen-style audits. |

*Lower-score EVIDENCE papers (e.g. 1301.6431 verification, 2008.06604 hierarchical control, 2601.00360 anti-collusion) stay in the research corpus for later P2 theory spikes; not first-apply.*

---

## 10 GitHub repos — portable patterns

Top ten by Grok score from EVIDENCE (15.0 first, then 14.0). Port **patterns**, not whole trees; prefer tests + small modules.

| Repo | Score | Pattern to port | Where to port in NEXUS |
|------|------:|-----------------|------------------------|
| **ahmedEid1/lumen** | 15.0 | Brief → durable/idempotent build; **migration-phase guards**; decision audit; honest public evals | Mine/alive **apply pipeline** phases; grade→apply audit log; demo eval honesty gates |
| **Jovancoding/Network-AI** | 15.0 | Multi-agent **control plane**; security module; **CLI + MCP** tooling; adapter surface | MCP/CLI façade for orchestration; security boundary for tools; framework adapters for external agents |
| **mtzanidakis/praktor** | 15.0 | Isolated agent workers; hybrid memory; scheduling; **AES vault**; Mission Control–style I/O | Alive-loop isolation; secrets vault for API keys; scheduled mine re-grades |
| **builderz-labs/mission-control** | 15.0 | SQLite-backed **ops plane**: tasks, spend, adapters; MCP/CLI/TUI; OpenAPI parity; quality gate | Operator/task store for mine & alive jobs; spend/token accounting; quality-gate checklist in CI |
| **IBM/AssetOpsBench** | 15.0 | Modular **MCP domain servers** + multi-framework **eval CLIs** | Split MCP tools by domain (mine, grade, research, demo); shared eval CLI for Grok grades |
| **labsai/EDDI** | 15.0 | Config-driven routing/memory; OpenAPI/OAuth/**MCP/A2A**; enterprise test/security packaging | Config schemas for agent routing; auth on MCP; packaging/test discipline for release |
| **phodal/routa** | 15.0 | **Board-first** delivery; traces; review state | Demo/ops board for improve PRs; trace each grade→apply; review state machine before merge |
| **MattMagg/MisterSmith** | 15.0 | Supervised execution; durable state; modular boundaries; MCP | Supervisor for long-running alive agents; durable run state; crate/module boundaries for runtime |
| **wshobson/agents** | 15.0 | Single Markdown source → **multi-harness generators/adapters**; build/validation tooling | Generate agent/skill defs once; emit adapters for NEXUS CLI/MCP/demo harnesses; validation gate |
| **open-multi-agent/open-multi-agent** | 14.0 | Goal → multi-agent **task DAG**; core package + CI/coverage/e2e | IMPROVE_OURS backlog as DAG; e2e around first apply slice; coverage on orchestration core |

**Honorable mentions (use as secondary ports, not top-10 required):**  
gossipcat-ai (consensus + adaptive trust for multi-grader), Sompote/tiger_cowork (atomic stores, path/zip safety, session cleanup), wmcmahan/cycgraph (cyclic graphs + Postgres durability + evals), swarmclawai/swarmclaw (sandboxes + multi-provider MCP), 7836246/claude-team-mcp (team templates MCP), openai/swarm (Agent+handoff *design* only—copy pattern, do not depend).

---

## Prioritized engineering backlog

### P0 — Prove durable self-improve loop (blocks everything else)

| Item | Intent | Modules / surfaces to touch |
|------|--------|------------------------------|
| **P0.1 Idempotent mine/apply phases** | Resume-safe mine_eval → improve apply; no double-writes | Mine workspace runner; apply pipeline; phase state under `.nexus_workspaces/`; guards inspired by **lumen** migration-phase guards |
| **P0.2 Decision audit artifact** | Every grade→port choice leaves a structured audit (paper/repo id, score, pattern, files) | Grading output schema; IMPROVE_OURS writer; demo “why this change” reader (**lumen**, **2302.10809**, **Thucy**-style evidence links) |
| **P0.3 MCP tool surface for mine/grade/alive** | Stable tools: `mine.status`, `grade.record`, `alive.run`, `apply.phase` | MCP server module (**Network-AI**, **mission-control**, **AssetOpsBench** modular servers) |
| **P0.4 Path/workspace safety on clones** | Untrusted scout/mine trees cannot escape workspace | Clone/extract helpers; zip/path validation (**tiger_cowork**); sandbox policy for apply |
| **P0.5 First-apply tests + demo script** | CI-green proof the loop works offline | Unit tests for phase FSM + audit schema; demo script printing audit + grade table |

### P1 — Operator plane, grading depth, orchestration quality

| Item | Intent | Modules / surfaces |
|------|--------|-------------------|
| **P1.1 Task/spend control plane** | Track mine/alive jobs, tokens/cost, status | SQLite (or existing store) tasks + spend (**mission-control**); CLI list/show |
| **P1.2 Multi-agent task DAG** | Goal → ordered agent tasks with dependencies | Orchestration core (**open-multi-agent** DAG; **AOAD-MAT** explicit order) |
| **P1.3 Consensus / multi-grader path** | Optional second opinion + trust weights before hard apply | Grade aggregator (**gossipcat** independent findings + source-backed filter) |
| **P1.4 Context pack stage** | Bound context from research reports + digests before apply | Context engineering pack builder (**2508.08322**); research workspace readers |
| **P1.5 Secrets vault** | AES (or OS-keychain) for provider keys used by Grok/MCP | Config/secrets module (**praktor** vault pattern) |
| **P1.6 Agent definition single-source** | Markdown/YAML agents → NEXUS + demo harnesses | Generator/validation (**wshobson/agents**) |
| **P1.7 Supervised alive runs** | Crash/restart supervision, durable run state | Alive supervisor (**MisterSmith**); optional Postgres/SQLite run log (**cycgraph** durability idea) |
| **P1.8 Board + traces for improve PRs** | Visible review state for self-improve work | Trace/review state (**routa**); link to decision audit |

### P2 — Packaging, enterprise hard edges, research theory spikes

| Item | Intent | Modules / surfaces |
|------|--------|-------------------|
| **P2.1 Dual packaging / subpath exports** (if TS surface exists) | Clean library+CLI packaging | Package layout (**Network-AI**) |
| **P2.2 OpenAPI parity for control plane** | HTTP == MCP == CLI | OpenAPI gen + contract tests (**mission-control**, **EDDI**) |
| **P2.3 OAuth/A2A hooks** | Enterprise agent-to-agent | Auth middleware (**EDDI**) |
| **P2.4 Emergent-behavior metrics** | Loop thrash, consensus flips | Telemetry (**MAEBE**); optional OTel (**AgenticGoKit** if Go path exists) |
| **P2.5 Adversarial / anti-collusion policies** | Hardened multi-agent demos | Policy layer (**2303.16641**, later **2601.00360**) |
| **P2.6 Domain MCP servers for demos** | Showcase modular servers beyond core | Demo MCP packages (**AssetOpsBench** pattern) |
| **P2.7 CVE-aware dependency pins + Makefile matrix** | Ops maturity | Root CI/Makefile (**solace-agent-mesh** discipline, without Solace coupling) |
| **P2.8 Handoff primitive cleanup** | Minimal Agent+handoff API | Orchestration API design from **openai/swarm** (pattern only) |

---

## First apply slice  
*(smallest PR-sized change that proves the self-improve loop)*

### Goal
Prove: **grade artifact in → durable phase machine → decision audit out**, with tests and a demo—no full control plane rewrite.

### Scope (do this only)

1. **Phase FSM for improve-apply** (names illustrative; implement in existing mine/alive/apply modules):  
   `briefed → context_packed → applying → audited → done`  
   with **idempotent transitions** and **migration-phase guards** (refuse skip/backtrack except explicit resume). Pattern source: **ahmedEid1/lumen**.

2. **Decision audit record** (JSON or SQLite row) fields at minimum:  
   - `repo` / `arxiv_id` (from EVIDENCE only)  
   - `score`, `idea`, `skill`, `method` (e.g. `grok:grok-4.5`)  
   - `pattern` (one sentence)  
   - `files_touched[]`  
   - `action_order[]` (paper **2510.13343**)  
   - `evidence_refs[]` (paths under `.nexus_workspaces/…`)  
   Pattern sources: **lumen** audit, **Thucy**-style claim links, **2302.10809** causal chain lite.

3. **One MCP (or CLI) tool** that:  
   - starts/resumes an apply phase  
   - returns current phase + last audit  
   Pattern sources: **Network-AI** / **mission-control** MCP+CLI parity (minimal: CLI is enough if MCP already exists—add one tool either way).

4. **Workspace safety check** on any path written during apply (must stay under workspace root). Pattern: **tiger_cowork** path safety (minimal assert, not full zip stack).

### Explicit non-goals for this PR
- No full mission-control UI/TUI  
- No multi-grader consensus  
- No AES vault, NATS, or board UI  
- No vendoring of any mined repo tree  

### Tests to run

| Test | Asserts |
|------|---------|
| **Unit: phase FSM** | Valid transitions only; double-run of same phase is no-op (idempotent); illegal skip raises guard error |
| **Unit: audit schema** | Required fields present; `evidence_refs` must exist under `.nexus_workspaces/`; orphan claims fail validation |
| **Unit: path safety** | Write outside workspace rejected |
| **Integration (local)** | Fixture grade row (e.g. lumen score=15.0) → run apply slice dry-run → audit file/row produced → phase `done` |
| **Regression** | Existing mine_eval / grading / MCP smoke tests still pass |

### Demo (must be runnable in one command)

```text
# illustrative
nexus demo self-improve-slice \
  --fixture .nexus_workspaces/mine_eval/ahmedEid1__lumen \
  --show-audit
```

Demo output should show: Grok scores → chosen pattern (“idempotent phases + decision audit”) → phase timeline → audit path. That is the public proof the research→mine→grade→apply loop is real (**lumen** “honest public evals” spirit).

### Success criteria
- [x] PR is reviewable in &lt; ~300 LOC of core logic (+ tests) — landed in `src/nexus/improve_apply.py`  
- [x] Re-running the demo does not corrupt state (idempotent)  
- [x] Audit cites only EVIDENCE-backed repo/paper ids (default fixture: ahmedEid1/lumen + arXiv 2510.13343)  
- [x] CI: unit + integration tests green (`tests/test_improve_apply.py`)  
- [x] Clear follow-on ticket list for P1 (task store, DAG, consensus) without blocking merge  

### Landed (2026-07-15 hard-apply)

| Surface | What |
|---------|------|
| `src/nexus/improve_apply.py` | Phase FSM `briefed→context_packed→applying→audited→done`, decision audit schema, path jail, demo formatter |
| `src/nexus/cli.py` | `nexus demo self-improve-slice [--fixture …] [--show-audit] [--run-id …]` |
| `src/nexus/mcp_server.py` | MCP tool `apply_phase` (start/resume/status/one/all) |
| `tests/test_improve_apply.py` | FSM, audit orphans, path safety, integration, MCP, CLI |

**Demo:**
```bash
PYTHONPATH=src python3 -m nexus.cli demo self-improve-slice --show-audit
# or with fixture:
PYTHONPATH=src python3 -m nexus.cli demo self-improve-slice \
  --fixture .nexus_workspaces/mine_eval/ahmedEid1__lumen --show-audit
```

---

### Apply order after first slice
1. Merge first apply slice (P0.1–P0.5 core).  
2. Add mission-control-style task/spend store (P1.1) + DAG (P1.2).  
3. Modularize MCP domains + eval CLI (AssetOpsBench).  
4. Consensus grading (gossipcat) before any fully autonomous hard-apply.  
5. Packaging/security/OpenAPI (P2) once the loop is demo-stable.

---

*All repo names, scores, and arXiv ids above appear in the provided EVIDENCE. Patterns are ports of ideas, not wholesale dependency on foreign trees. Truncated EVIDENCE sections (full paper titles mid-list, swarmclaw mid-blurb) were not expanded with invented content.*