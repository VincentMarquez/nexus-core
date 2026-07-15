# Latest improve plan (from full self-improve cycle)

The request was truncated; I'll load the full offloaded prompt so the plan stays grounded only in the provided evidence.Reading the full offloaded prompt for complete evidence.Trying to load the full offloaded prompt so paper IDs and the rest of the evidence aren't incomplete.# NEXUS self-improvement plan (papers + mined repos → hard apply)

Grounded only in the EVIDENCE below. Patterns are ported; whole trees are not. Focus: multi-agent durability, MCP, mine/alive loops, Grok grading, demos.

---

## Executive summary

- **Close the self-improve loop end-to-end**: research (arXiv) + mine (repos graded by Grok 4.5) → ranked backlog → small PR apply → re-grade, so each cycle leaves durable artifacts (SQLite/state, traces, eval scores), not just notes.
- **Highest-leverage repo patterns** (score ≥ 15): `codingagentsystem/cas` (worktree supervisor + SQLite MCP context), `Intelligent-Internet/zenith` (anti–premature-completion control loops), `IBM/AssetOpsBench` (modular MCP tool servers + eval CLI), `gossipcat-ai/gossipcat-ai` (consensus review + adaptive trust), `builderz-labs/mission-control` / `phodal/routa` (ops board: tasks, spend, traces, evidence).
- **Highest-leverage paper ideas**: deterministic multi-agent orchestration for high-stakes flows (2511.15755), claim/evidence verification across structured stores (2512.03278), order-of-action and hierarchical control (2510.13343, 2008.06604), causal explanations of agent decisions (2302.10809), anti-collusion / trust between agents (2601.00360), emergent-behavior observation (2506.03053).
- **Port rules**: small modules + tests; SQLite-first durability before NATS/Postgres/Temporal-class substrates; MCP as the tool/memory boundary; Grok grading stays the scorer for mine_eval and apply quality.
- **First prove the loop** with one PR-sized slice: SQLite-backed MCP persistent context for mine/alive (from cas) + independent verification gate before “done” (from zenith), with unit tests and a demo path that prints grade deltas.

---

## 10 arXiv papers — what to steal for this codebase

| # | arXiv id | Idea to steal | Concrete NEXUS change |
|---|----------|---------------|------------------------|
| 1 | **2511.15755** | Multi-agent LLM orchestration for **deterministic, high-quality** decision support (incident-style) | Add a **deterministic orchestration mode** for mine/apply/grade: fixed role graph, ordered tool allowlists, reproducible run manifests under `.nexus_workspaces/` so the same scout/mine inputs yield comparable Grok grades. |
| 2 | **2512.03278** (Thucy) | Multi-agent **claim verification** over relational data | After mine/apply, require agents to emit **claims + evidence refs** (paths, test names, grade fields) verified against SQLite/run DB before status=`done`; fails closed if evidence missing. |
| 3 | **2508.08322** | Multi-LLM **tool-use code assistant** workflow (research → notebook → agents) | Formalize the existing research path (`NEXUS_RESEARCH_REPORT.md` → backlog → apply) as a **staged pipeline** with handoffs between research, mine_eval, and engineering agents (not one mega-prompt). |
| 4 | **2510.13343** (AOAD-MAT) | **Order of action decisions** matters in multi-agent systems | Make alive/mine schedulers **order-aware**: research → grade → plan → apply → verify → re-grade; encode action order in durable job state so restarts resume the correct stage. |
| 5 | **2302.10809** | **Causal explanations** for sequential multi-agent decisions | Persist a lightweight **decision log** (why this repo/paper was selected, why this backlog item applied) next to grades; surface in demos and review boards. |
| 6 | **2008.06604** | **Decomposition + hierarchical approximation** for multi-agent control | Split long self-improve runs into **supervisor goals** vs **worker tasks** (worktree-isolated applies), with hierarchical status rollup instead of flat job lists. |
| 7 | **2303.16641** | Hierarchical game-theoretic decisions under **adversarial** agents | Treat low-trust / conflicting agent outputs (e.g. review disagreement) as **adversarial inputs**: require consensus or human/HITL gate before merge; wire into grading trust weights. |
| 8 | **2506.03053** (MAEBE) | Framework for observing **emergent multi-agent behavior** | Instrument mine/alive loops with **behavior metrics** (retry storms, premature done, tool thrash, grade flip-flops) and fail or replan when emergent failure modes appear. |
| 9 | **2601.00360** | Map **anti-collusion** mechanisms into multi-agent AI | In consensus grading/review, enforce **independent votes** (isolated contexts, no shared draft) before aggregation—stop agents from rubber-stamping each other’s scores. |
| 10 | **1301.6431** | **Automatic verification** of interleaved multi-agent systems | Add a **static/schedule checker** for concurrent mine workers (worktrees, shared SQLite locks, stage interleaving) so illegal interleavings are rejected before run. |

*Also in EVIDENCE (reserve / P2 research only, not in the primary 10):* 2602.04518 (value systems / preference learning → grade rubric evolution), 2603.20143 (expert multi-agent orchestration pattern for domain demos), 2604.03350 (multi-stage screening → surrogate evaluation for cheaper mine prefilters).

---

## 10 GitHub repos — portable patterns

Top tier from IMPROVE_OURS / Grok grades (score ≥ 14). Prefer patterns + tests, not wholesale vendors.

| Repo | Score | Pattern to port | Where to port in NEXUS |
|------|------:|-----------------|------------------------|
| **codingagentsystem/cas** | 16.0 | Supervisor/workers in **git worktrees** + **SQLite-backed MCP persistent context** | Orchestration core + agent memory: isolate each apply/mine worker; MCP context DB for handoffs across restarts. Paths: mine_eval clones under `.nexus_workspaces/`. |
| **Intelligent-Internet/zenith** | 15.0 | Long-running harness: **adaptive orchestration, independent verification, principled stopping** (anti–premature-completion) | Alive loop / run controller: “done” only after independent verify + grade threshold; multi-backend-friendly stop policies. |
| **IBM/AssetOpsBench** | 15.0 | **Modular MCP tool servers**, multi-backend runners, **evaluation CLI** | Grading & tool-eval harness: package MCP tools as small servers; CLI that scores agents the same way Grok mine_eval scores repos. |
| **gossipcat-ai/gossipcat-ai** | 15.0 | **Consensus code review**, source cross-checks, **adaptive agent trust** | Apply/review stage: multi-agent review of diffs; trust scores feed next mine priorities and grader weights. |
| **builderz-labs/mission-control** | 15.0 | Self-hosted control plane: **tasks, spend, runtimes, SQLite**, strong packaging | Ops surface for mine/alive: task board, cost/token spend, runtime inventory backed by SQLite. |
| **phodal/routa** | 15.0 | Workspace-first board: **goals, tasks, traces, evidence, review** | Demo + operator UX: expose self-improve goals/evidence/traces on a board; monorepo layout reference only. |
| **ahmedEid1/lumen** | 15.0 | Production durability/**migrations**, MCP exposure, **honest public evals** | Durability layer: migration discipline for SQLite schemas; public/local eval snapshots for grading honesty. |
| **wshobson/agents** | 15.0 | Multi-harness **plugin catalog** + generate/validate/**test adapters** | Agent/plugin registry for NEXUS skills (mine, research, apply, grade) with validate+test adapters per harness. |
| **SolaceLabs/solace-agent-mesh** | 15.0 | **Event-broker** multi-agent messaging, CVE-aware pins, broad test toolchain | Optional durable **event bus** between research/mine/apply (pattern only—avoid hard Solace lock-in; start with local queue/SQLite outbox). |
| **labsai/EDDI** | 15.0 | Config-driven routing/memory + **API/MCP/A2A**, strong test/security, Docker | Config-driven agent routing and MCP/A2A integration packaging; deploy/smoke profiles for demos. |

*Honorable same-score / next-slice (still in EVIDENCE):* MattMagg/MisterSmith (supervised Rust runtime, NATS/JetStream, Postgres, MCP), automagik-dev/forge (kanban + worktrees + MCP hooks), choihyunsus/soul (MCP agent-memory: handoffs, immutable ledger, entity memory), StreetLamb/rojak (Temporal durability + HITL + MCP), openai/swarm (minimal handoff API—learning reference only).

---

## Prioritized engineering backlog

### P0 — prove durability + stop-policy + grade loop

| Item | Change | Files / modules to touch (concrete targets) |
|------|--------|-----------------------------------------------|
| **P0.1 Worktree isolation for apply/mine workers** | Supervisor spawns workers in git worktrees (cas/forge pattern); no shared dirty tree | `src/` orchestration / worker runner; `.nexus_workspaces/` workspace manager; git worktree helpers |
| **P0.2 SQLite MCP persistent context** | MCP-facing context store: session, handoff, last grade, open claims | New module e.g. `mcp/context_store` or `persistence/mcp_context`; SQLite schema + migrations (lumen-style) |
| **P0.3 Principled stopping / anti–premature-done** | Done requires independent verification + min Grok score / test pass (zenith) | Alive/mine loop controller; status machine (`planned → running → verify → graded → done\|retry`) |
| **P0.4 Claim + evidence gate** | Thucy-style: each apply records claims → verified against tests/paths | Apply report schema; verifier hooked after PR-sized apply |
| **P0.5 Deterministic orchestration mode** | Fixed stage order + allowlisted tools for self-improve runs (2511.15755) | Run manifest JSON; stage scheduler (AOAD-MAT order-aware) |

### P1 — grading, consensus, ops visibility

| Item | Change | Files / modules to touch |
|------|--------|---------------------------|
| **P1.1 Grok grade adapters** | Unified grade schema (total/idea/skill/method) for repos **and** post-apply diffs | Mine_eval grader; shared `grading/` types; CLI entry for re-grade |
| **P1.2 Consensus review + adaptive trust** | Multi-agent review of apply diffs; trust updates (gossipcat) | Review agents; trust store in SQLite; feed into next mine ranking |
| **P1.3 Anti-collusion grading** | Independent grade contexts before aggregate (2601.00360) | Grader fan-out; no shared intermediate drafts |
| **P1.4 Mission-control lite** | Tasks, spend/tokens, runtime registry on SQLite | Ops DB tables; simple CLI/dashboard endpoints |
| **P1.5 Evidence board fields** | Goals / tasks / traces / evidence / review (routa) | Demo API or markdown export for self-improve runs |
| **P1.6 Emergent-behavior metrics** | Retry storms, grade flip-flops, tool thrash (MAEBE) | Metrics collector on alive loop; thresholds → replan |

### P2 — mesh, plugins, heavier substrate

| Item | Change | Files / modules to touch |
|------|--------|---------------------------|
| **P2.1 MCP tool server packaging** | AssetOpsBench-style modular MCP servers + eval CLI | `mcp/servers/*`; eval CLI wiring to Grok grades |
| **P2.2 Plugin/catalog adapters** | wshobson-style generate/validate/test for skills | Skill registry; harness adapters |
| **P2.3 Event outbox (broker-agnostic)** | solace-agent-mesh pattern without Solace lock-in | SQLite outbox → optional NATS later (MisterSmith) |
| **P2.4 Config-driven routing (EDDI)** | Declarative agent routes, memory, MCP/A2A | Config schema + router |
| **P2.5 Causal decision log** | Persist why paper/repo/item chosen (2302.10809) | Decision log table; demo surface |
| **P2.6 Interleaving / schedule checks** | Guard illegal concurrent worktree/SQLite interleavings (1301.6431) | Concurrency tests; lock protocol docs |
| **P2.7 Preference/value rubric evolution** | 2602.04518 later: learn grade weights from human preference | Grading rubric versioning only after P0/P1 stable |

---

## First apply slice (smallest PR-sized change that proves the loop)

### Goal
Ship the **minimum durable loop**: SQLite MCP context + ordered stages + independent verify-before-done, exercised on a no-op or docs-only apply, then **re-graded** by Grok so the loop is measurable.

### Scope (one PR)

1. **SQLite context store** (from **cas** + **lumen** migration discipline)
   - Tables: `runs`, `stages`, `context_kv`, `claims`, `grades`
   - MCP tools: `context_get` / `context_set` / `handoff` (minimal)
2. **Stage machine** (from **zenith** + paper **2510.13343** / **2511.15755**)
   - Stages: `research_ingest → mine_rank → plan_item → apply → verify → grade → done|retry`
   - Reject `done` unless verify pass + grade row present
3. **Independent verification hook** (from **zenith** + **Thucy 2512.03278**)
   - Verify = run a fixed test command + check claim paths exist
   - Emit claim records for “loop proved”
4. **Demo CLI** (from **mission-control** / **routa** surfaces, CLI-only)
   - `nexus improve demo-loop` (or existing entrypoint flag): create run → fake/small apply → verify → print grade stub → write decision log line

### Explicitly out of scope for this PR
Worktree pool, consensus multi-reviewer, event bus, full dashboard, Temporal/NATS/Postgres, plugin marketplace.

### Tests to run

| Layer | What |
|-------|------|
| **Unit** | Context store CRUD; stage transitions (illegal jumps fail); done rejected without verify/grade |
| **Integration** | Temp SQLite file; MCP context handoff across two “agents” (sequential processes or in-process roles) |
| **Loop smoke** | Demo command exits 0; produces `runs` row, `grades` row, claim evidence paths |
| **Regression** | Existing nexus-core test suite / CI target for core packages |
| **Manual demo** | Print before/after: stage timeline + grade fields; show restart resumes mid-stage from SQLite (kill after `apply`, restart → continues at `verify`) |

### Success criteria (proves the loop)

- [x] Restart-safe: process kill mid-run → resume from last durable stage (`--stop-after apply` then resume).
- [x] No silent success: cannot mark `done` without verify + grade.
- [x] Artifact trail under `.nexus_workspaces/` + `.nexus_state/context/context.sqlite`: run id, claims, grades, decision log.
- [x] Ready for **next PR**: cas worktree workers + Grok re-grade of a real mined pattern apply.

### Landed (2026-07-15 hard-apply, Grok 4.5 CLI)

| Path | Role |
|------|------|
| `src/nexus/context_store.py` | SQLite store (`runs/stages/context_kv/claims/grades/decisions`), ordered LOOP_STAGES, verify-before-done, `run_demo_loop` |
| `src/nexus/cli.py` | `nexus improve demo-loop` (+ `--run-id` / `--stop-after` / `--json`) |
| `src/nexus/mcp_server.py` | MCP tools `context_get`, `context_set`, `handoff`, `demo_loop` |
| `src/nexus/tool_catalog.py` | Privilege tags for new tools |
| `tests/test_context_store.py` | CRUD, illegal jumps, done gate, verify paths, restart resume, MCP, CLI |

**Evidence:** `PYTHONPATH=src python3 -m pytest -q` → 387 passed; `nexus improve demo-loop` → status=done, grade stub total=15.0.

### Suggested PR title / commit theme

`feat(improve): durable MCP context + verify-before-done for self-improve loop`

---

**Apply order after first slice:** P0.1 worktrees (deeper pool / promote-to-main) → P1.1–P1.3 Grok consensus re-grade of real apply → P1.4–P1.5 ops/demo board polish → P2 MCP servers & outbox. Always: port patterns from local clones under `.nexus_workspaces/scout_repos/` and `.nexus_workspaces/mine_eval/`, keep Grok 4.5 as the grade authority, and re-run mine_eval scores after each hard apply to quantify self-improvement.