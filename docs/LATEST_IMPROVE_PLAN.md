# Latest improve plan (from full self-improve cycle)

I'll read the full offloaded prompt so the plan is grounded only in the complete evidence.Reading the full offloaded prompt for complete paper and repo evidence.# NEXUS Self-Improvement Plan  
**From 10 arXiv papers + 10 mined repos · Grok 4.5 grading · hard apply**  
**Target:** `/path/to/nexus-core`  
**Constraint:** patterns only (not full trees); prefer tests + small modules

---

## 1. Executive summary

- **Close the durability gap first.** NEXUS’s mine/alive loops need crash-safe state (SQLite/ledger + optional Temporal-style checkpoints), not more chat glue—pull patterns from *cas*, *soul*-class memory, *rojak*-style HITL durability, and *mission-control* task governance.
- **Make MCP a first-class control surface.** Treat research, memory, and domain tools as modular MCP servers (AssetOpsBench domain servers, openrouter-deep-research plan/parallelize/synthesize, EDDI MCP/A2A routing) with circuit breakers, key rotation, and validation tooling (apex-accelerator).
- **Stop premature “done.”** Zenith’s adaptive workers/testers/replanning/stopping is the highest-signal fix for uncontrolled agent loops; pair it with MAEBE-style emergent-behavior observation and AOAD-MAT-style ordered action decisions in the orchestrator.
- **Industrialize the self-improve loop.** wshobson/agents’ generate → validate → smoke-test adapters + Grok 4.5 grading (already used at scores 13–16) become the standard pipeline for mined repos and paper-derived patches before any hard apply.
- **Ship one PR-sized prove-the-loop slice.** Smallest win: immutable mine-eval grade ledger + smoke harness for one MCP tool path + demo script that re-runs a graded mine artifact—proves research → grade → apply without boiling the ocean.

---

## 2. 10 arXiv papers — what to steal for this codebase

Only IDs present in EVIDENCE. Concrete changes map to multi-agent durability, MCP, mine/alive, grading, demos.

| # | arXiv id | Idea (from title / research tags) | Concrete NEXUS change |
|---|----------|-----------------------------------|------------------------|
| 1 | **2511.15755** | Multi-agent LLM orchestration for **deterministic**, high-quality decision support (incident response) | Add a **deterministic orchestration mode** for mine/alive: fixed role order, frozen tool allowlists, replayable decision logs under `.nexus_workspaces/`; demo “incident-style” self-heal of a failed mine job. |
| 2 | **1301.6431** | **Automatic verification** of parameterised interleaved multi-agent systems | Formalize interleaved agent steps as a small **state machine + invariants** (no double-apply, no lost grade); property tests that concurrent mine workers cannot corrupt shared SQLite/workspace state. |
| 3 | **2302.10809** | **Causal explanations** for sequential multi-agent decisions | Attach **why-this-grade / why-this-apply** causal chains to Grok grade records (`idea`, `skill`, `method=grok:grok-4.5`) and surface them in research reports and demos. |
| 4 | **2506.03053** | **MAEBE**: multi-agent **emergent behavior** framework | Instrument mine/alive for emergent failure modes (ping-pong handoffs, score inflation, thrash); alert or replan when behavior drifts outside expected envelopes. |
| 5 | **2512.03278** | **Thucy**: LLM multi-agent **claim verification** over relational DBs | Treat “paper/repo says X improves NEXUS” as **claims** verified against workspace SQLite (tests green, score thresholds, file diffs) before hard apply. |
| 6 | **2601.00360** | Map human **anti-collusion** mechanisms into multi-agent AI | Separate **grader vs implementer vs proposer** roles; prevent self-grade loops and collusive high scores among mine agents (split keys, independent Grok grade channel). |
| 7 | **2303.16641** | Hierarchical **game-theoretic** decisions under **adversarial** agents | Model flaky tools / malicious or wrong MCP responses as adversaries; hierarchical supervisor can demote tools, force replan, or stop (links to zenith stopping). |
| 8 | **2604.03350** | Multi-stage workflow: model-based screening → **data-driven surrogates** | Structure research pipeline: cheap screen of arXiv/repos → expensive Grok deep grade only on top-K → surrogate score cache in mine_eval to cut cost. |
| 9 | **2510.13343** | **AOAD-MAT**: multi-agent RL with **order of action decisions** | Explicit **action-order policy** in orchestrator (research → grade → plan → apply → test → demo), not free-form parallel tool spam; log order as first-class state. |
| 10 | **2603.20143** | Multi-agent orchestration for **expert-level** perception + generative recomposition | Split long tasks into **perceive (mine/research) → recompose (IMPROVE_OURS plan) → expert review (Grok grade)** stages with explicit handoff artifacts under `.nexus_workspaces/research/` and `mine_eval/`. |

**Also in evidence (backlog fodder, not top-10 apply):**  
`2602.04518` (preference/IRL value systems → grade rubric learning), `2008.06604` (hierarchical decomposition/control → supervisor/worker hierarchy), `2508.08322` (present in research CSV under tool-use multi-LLM agents; title truncated in EVIDENCE—do not invent; re-read local `NEXUS_RESEARCH_REPORT.md` before citing title).

---

## 3. 10 GitHub repos — portable patterns

Top-scored, IMPROVE_OURS-aligned. Port **patterns**, not trees.

| Repo | Score | Pattern to steal | Where to port in NEXUS |
|------|------:|------------------|------------------------|
| **wshobson/agents** | 16.0 | Single-source agent/skill catalog + **generate / validate / smoke-test** adapters | Mine/alive packaging: every extracted skill or agent patch gets generate→validate→smoke before merge; CI target for self-improve adapters. |
| **builderz-labs/mission-control** | 15.0 | SQLite control plane: **task governance, spend tracking**, adapters, Docker deploy | Ops layer for mine jobs: task table, budget/spend caps on Grok grades, adapter registry for providers. |
| **SolaceLabs/solace-agent-mesh** | 15.0 | **Event-driven** multi-agent hygiene: CVE-pinned deps, broad unit/integration/**eval**/migration tests | Test matrix for mine/alive + MCP: unit + integration + eval + migration targets; pin security-sensitive deps. |
| **IBM/AssetOpsBench** | 15.0 | Modular **MCP domain servers**, multi-SDK runners, **evaluation harness** | Split NEXUS MCP into domain servers (research, mine, grade, apply); shared eval harness for paper/repo claims. |
| **phodal/routa** | 15.0 | Goals/tasks/**traces/reviews on kanban**, not chat; monorepo CLI/crates surfaces | Demo + operator UI: mine/improve board (goal → task → trace → review) instead of chat-only; CLI entrypoints for each stage. |
| **labsai/EDDI** | 15.0 | Config-driven routing, memory, **MCP/A2A/OpenAPI**, production tests/security/Docker | Config schemas for agent routes and MCP mounts; security defaults for tool exposure. |
| **Intelligent-Internet/zenith** | 15.0 | Adaptive workers/testers/skills, **replanning + stopping** for long coding tasks | Alive loop core: stop criteria, replan on failed tests, dedicated tester role—kills premature completion. |
| **codingagentsystem/cas** | 15.0 | Rust-style **modular multi-agent factory** + **SQLite/MCP persistent context** | Orchestrator + memory crate/module boundaries; workspace-scoped SQLite context for worktree-isolated agents. |
| **ahmedEid1/lumen** | 15.0 | **Idempotent builds**, phased **migration guards**, decision auditability, Docker Makefile | Apply path: idempotent hard-apply, migration guards for schema/workspace upgrades, audit log of apply decisions. |
| **wheattoast11/openrouter-deep-research-mcp** | 15.0 | MCP research: **plan / parallelize / synthesize**, embedding routing, **circuit breakers**, key rotation, vector persistence | Research MCP backend for arXiv/mine deep-dives; circuit breakers + key rotation around Grok/OpenRouter calls. |

**Honorable mentions (use in P1/P2, still in EVIDENCE):**  
*jonathan-vella/apex-accelerator* (MCP/docs/agent validation tooling), *MattMagg/MisterSmith* (supervision + MCP multi-crate runtime), *StreetLamb/rojak* (Temporal crash-safe durability + HITL + MCP), *choihyunsus/soul* (MCP memory/session, immutable ledger, handoffs), *automagik-dev/forge* (git worktree isolation + MCP), *escapeboy/agent-fleet-o* (HITL/DAG mission control—watch AGPL).

---

## 4. Prioritized engineering backlog

### P0 — Prove durability + grade integrity (blocks self-improve)

| Item | Touch (modules / areas) | Source signal |
|------|-------------------------|---------------|
| **P0.1 Immutable grade ledger** | SQLite schema under `.nexus_workspaces/mine_eval/`; grade writer used by Grok path (`idea`, `skill`, `score`, `method=grok:grok-4.5`); append-only / immutable rows | soul ledger; cas SQLite context; mission-control task store; anti-collusion (2601.00360) |
| **P0.2 Action-order orchestrator** | Central mine→grade→plan→apply→test→demo state machine; reject out-of-order applies | AOAD-MAT (2510.13343); 2511.15755 deterministic orchestration |
| **P0.3 Alive stop + replan** | Alive loop: tester role, stop predicates (tests fail / score gate / max steps), replan hook | zenith; MAEBE (2506.03053); adversarial hierarchy (2303.16641) |
| **P0.4 Claim-gate before hard apply** | Verifier: “diff + tests + grade threshold” as claims against DB; no apply without pass | Thucy (2512.03278); lumen idempotent apply; causal explain (2302.10809) |
| **P0.5 MCP research backend hardening** | Research MCP: plan/parallelize/synthesize; circuit breaker + key rotation on LLM calls | openrouter-deep-research-mcp; AssetOpsBench domain MCP |

### P1 — Ops, packaging, eval surface

| Item | Touch | Source signal |
|------|-------|---------------|
| **P1.1 Skill/agent adapter pipeline** | generate → validate → smoke-test for every ported pattern; CI job | wshobson/agents |
| **P1.2 Spend + task governance** | Per-job budget, grade call accounting, task states | mission-control |
| **P1.3 Eval + migration test matrix** | `unit` / `integration` / `eval` / `migration` targets for mine_eval schema and MCP | solace-agent-mesh; lumen migration guards |
| **P1.4 Config-driven routing** | YAML/JSON agent routes, MCP mounts, tool allowlists | EDDI; apex validation patterns |
| **P1.5 Worktree-isolated apply** | Optional git worktree per apply (cas/forge pattern); merge only after smoke | cas; automagik-dev/forge |
| **P1.6 Kanban/trace demo surface** | CLI or minimal UI: goals, tasks, traces, reviews for one improve cycle | routa; Clutch control-plane UX (reference only) |

### P2 — Depth, preference, platform polish

| Item | Touch | Source signal |
|------|-------|---------------|
| **P2.1 Preference-tuned grade rubric** | Learn weights on idea/skill from human accepts/rejects of applies | 2602.04518 |
| **P2.2 Hierarchical supervisor** | Decomposition + hierarchical approximation of long research goals | 2008.06604; MisterSmith supervision |
| **P2.3 Optional Temporal/HITL path** | Crash-safe long jobs + approval gates for hard apply | rojak |
| **P2.4 Event-bus optional path** | Decouple mine workers via events if monolith pain appears | solace-agent-mesh (pattern only; avoid hard Solace lock-in) |
| **P2.5 Full monorepo packaging** | CLI + desktop/VS Code later | routa; forge packaging hygiene |
| **P2.6 Re-resolve truncated paper 2508.08322** | From local `NEXUS_RESEARCH_REPORT.md` only—no invented title | evidence gap |

---

## 5. First apply slice (smallest PR that proves the loop)

### Goal
Prove **research/mine artifact → Grok-shaped grade → claim verify → durable ledger → smoke**, without porting a full agent framework.

### Scope (one PR)

1. **Schema + ledger module**  
   - Append-only table for mine grades: `repo_or_paper_id`, `score`, `idea`, `skill`, `method`, `causal_note`, `created_at`, `artifact_path`.  
   - Paths rooted at `.nexus_workspaces/mine_eval/`.  
   - Migration with guard (refuse double-migrate)—lumen-style.

2. **Claim verifier (pure functions + tests)**  
   - Inputs: grade row, optional test exit code, score threshold (e.g. ≥ 14.0 for apply candidacy).  
   - Outputs: `ClaimResult{ok, reasons[]}` (Thucy-style claim verification).  
   - **No network** in unit tests.

3. **Action-order guard**  
   - Enum stages: `MINED → GRADED → CLAIM_OK → APPLY_CANDIDATE` (apply itself can be dry-run in this PR).  
   - Illegal transitions raise hard errors (1301.6431-style invariant).

4. **Smoke adapter**  
   - wshobson-style: given one already-graded local clone path from EVIDENCE (e.g. `wshobson__agents` or `codingagentsystem__cas` under `.nexus_workspaces/mine_eval/` or `scout_repos/`), write ledger row + run claim verifier + print kanban-ish one-line status.

5. **Demo script**  
   - `demo_self_improve_slice` (or equivalent under existing demos/):  
     - Load one graded repo from EVIDENCE  
     - Persist grade  
     - Verify claims  
     - Emit causal one-liner (“score=16 because skill marketplace generate/validate/smoke”)  
     - Exit 0 only if ledger + claims pass  

### Explicitly out of scope for this PR
- Full Temporal, NATS, Azure Copilot, Solace, or e-learning stacks  
- Live OpenRouter/Grok network calls (stub or use precomputed grades from EVIDENCE)  
- Desktop UI (routa/Clutch)—CLI status line only  
- Actual code mutation of nexus-core from a mined tree (dry-run candidate flag only)

### Tests to run

| Test | Asserts |
|------|---------|
| Unit: ledger append | Second write with same id does not mutate first row (immutability) |
| Unit: claim verifier | score≥threshold + tests_ok → pass; low score → fail with reason |
| Unit: action-order | `MINED → APPLY_CANDIDATE` without `GRADED` raises |
| Unit: migration guard | migrate twice → second is no-op or guarded error |
| Integration/smoke | Demo script against fixture grade for `wshobson/agents` (score 16.0) exits 0 |
| Eval (optional light) | Fixture set of 3 EVIDENCE grades (16, 15, 13) classifies apply-candidates correctly |

### Success criteria (loop proven)
- A developer can run **one command** and see: durable grade in SQLite → claim gate → ordered stage transition → demo artifact.  
- CI runs pure unit tests without API keys.  
- Next PR can swap dry-run for real hard-apply behind the same claim gate (zenith stop/replan + worktree isolation).

### Landed (2026-07-16 Grok 4.5 hard apply)

| Plan item | Module / surface | Status |
|-----------|------------------|--------|
| Schema + ledger + `causal_note` + migration guard | `src/nexus/mine_eval_slice.py` → `.nexus_workspaces/mine_eval/slice/grades.sqlite` | ✅ |
| `ClaimResult{ok, reasons[]}` + score/tests gate | `verify_claims` / `classify_apply_candidates` | ✅ |
| Action-order `MINED→GRADED→CLAIM_OK→APPLY_CANDIDATE` | `SliceRunner` / `assert_transition` | ✅ |
| Smoke + kanban one-liner | `run_demo_slice` / `format_kanban` | ✅ |
| Demo / CLI / MCP | `nexus improve plan-slice` · MCP tool `mine_eval_slice` | ✅ |
| Tests | `tests/test_mine_eval_slice.py` (ledger, claims, order, migrate, demo, eval-3, CLI) | ✅ |

**One command:**

```bash
PYTHONPATH=src python3 -m nexus.cli improve plan-slice --repo wshobson/agents
# or: python -m nexus.mine_eval_slice --repo wshobson/agents
```

Also closed next-open: MCP `apply_select` now passes `use_spine` / `use_preference` / `run_id` and prefixes operator text with `spine/method:`.

**Next open:** wire plan-slice APPLY_CANDIDATE → worktree_apply dry-run · plan-reuse cache · more sample packs

---

### Suggested sequencing after the first slice

```text
P0 ledger+claims+order  →  P0 alive stop/replan  →  P0 MCP research breakers
        →  P1 adapter smoke CI  →  P1 spend governance  →  P1 worktree apply
        →  P2 preference rubric / HITL / richer demos
```

### Hard rules for all applies
1. **Port patterns, not whole repos** (IMPROVE_OURS).  
2. **Do not invent** paper IDs or repos outside EVIDENCE.  
3. **Grok 4.5** remains the grade method of record (`method=grok:grok-4.5`).  
4. **No hard apply** without claim verification + smoke.  
5. Prefer **tests + small modules** over framework rewrites.

---

This plan is intentionally biased toward **durability, MCP, mine/alive control, grading integrity, and a demoable loop**—the failure modes called out by zenith, mission-control, soul/cas persistence, and the deterministic/verification papers—rather than bolting on another generic multi-agent chat stack.