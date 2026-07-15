# Latest improve plan (from full self-improve cycle)

Reading the full offloaded prompt so the plan uses complete evidence only.Reading the full offloaded prompt for complete evidence.The interactive prompt failed; reading the offloaded evidence file next so the plan stays complete and accurate.# NEXUS Self-Improvement Plan  
**Research + engineering apply from mined repos + arXiv (Grok 4.5 graded)**  
Target: `/path/to/nexus-core` · Scope: multi-agent durability, MCP, mine/alive loops, grading, demos

---

## Executive summary

- **Port patterns, not trees.** Highest-leverage sources are config-driven orchestration (EDDI), Markdown agent/plugin marketplace (wshobson/agents), SQLite control/ops plane (mission-control), worktree supervisor+workers (cas/forge), and MCP memory/ledger (soul) — all score ≥15 and map onto NEXUS mine/alive + MCP surfaces.
- **Papers drive invariants, not features.** Steal verification of interleaved agents, deterministic multi-agent orchestration for incident-style decisions, claim-verification grading, causal decision audit, anti-collusion/governance, and order-of-action scheduling — wire them into durable loops and Grok grading, not new product UI.
- **Close the self-improve loop first.** Smallest proof is: mine → grade (Grok 4.5) → backlog item → hard-apply PR → alive re-eval — with immutable ledger + circuit breakers so failed applies do not corrupt state.
- **P0 is durability + observability.** SQLite (or existing store) work ledger, handoffs, circuit breakers on MCP/research calls, and an agent-decision audit trail before broad adapter/marketplace work.
- **Demos = honest public evals.** Lumen-style agent-decision audit + AssetOpsBench-style evaluation harness + mission-control OpenAPI-parity ops views; demos must show graded mine results and one applied improvement with tests green.

---

## 10 arXiv papers — what to steal for this codebase

| # | arXiv id | Idea (from evidence) | Concrete NEXUS change |
|---|----------|----------------------|------------------------|
| 1 | **2511.15755** | Multi-agent LLM orchestration for **deterministic, high-quality decision support** (incident response) | Make mine/alive **apply decisions** structured and replayable: fixed role prompts + scoring rubric + deterministic merge of agent votes before hard-apply; log decision packet for demos. |
| 2 | **2512.03278** | **Thucy**: multi-agent **claim verification** over relational data | Treat mined-repo “ideas/claims” as claims against workspace evidence: claim → evidence rows → pass/fail grade; feed Grok 4.5 grading with structured claim/evidence pairs. |
| 3 | **1301.6431** | **Automatic verification** of parameterised **interleaved multi-agent** systems | Add a lightweight **interleaving invariant checker** for concurrent worker/supervisor steps (worktrees, MCP tools): forbid illegal state transitions in durable orchestration. |
| 4 | **2302.10809** | **Causal explanations** for sequential multi-agent decisions | Persist **why** each agent step ran (parent goal, prior tool result, grade delta) in the work ledger; surface in demos/audit as causal chains, not just logs. |
| 5 | **2506.03053** | **MAEBE**: multi-agent **emergent behavior** framework | Instrument alive loop for emergent failure modes (thrash, premature stop, ping-pong handoffs); grade runs on emergent metrics, not only task success. |
| 6 | **2601.00360** | Map **human anti-collusion** mechanisms into multi-agent AI | Prevent mine graders / apply agents from **rubber-stamping** each other: independent Grok grade vs apply agent, dual-control on hard-apply, separation of mine score vs merge authority. |
| 7 | **2303.16641** | Hierarchical game-theoretic decisions under **adversarial** agents | Model “bad mine” / poisoned plugin as adversarial: hierarchical gate (scout → grade → quarantine → apply); adversarial-resistant ranking for score≥threshold sources. |
| 8 | **2510.13343** | **AOAD-MAT**: order of **action decisions** among agents | Explicit **action-order policy** for supervisor/workers (e.g. grade before apply, test before merge, ledger write before handoff); encode order as config, not ad-hoc code. |
| 9 | **2602.04518** | Learn agent **value systems** via preference / inverse RL | Align Grok grading weights (idea/skill/method) with observed preference labels from successful applies; store preference traces for rubric iteration. |
| 10 | **2008.06604** | **Decomposition + hierarchical approximation** for multi-agent control | Decompose improve tasks into hierarchy: research slice → port pattern → module PR → demo; hierarchical backlog matching P0/P1/P2 with local controllers per layer. |

*Present in evidence but deferred (not in top 10 apply set):* 2508.08322 (tool-use multi-LLM / Claude Code context — title truncated in evidence), 2603.20143 (expert multi-agent inspection orchestration), 2604.03350 (multi-stage stochastic ABM workflow). Use later for demo scenarios / multi-stage screening of mine candidates.

---

## 10 GitHub repos — portable patterns

Selected from Grok-graded mine + IMPROVE_OURS (score ≥13); top portable patterns for NEXUS — not full trees.

| Repo | Score | Pattern to port | Where to port in NEXUS |
|------|------:|-----------------|-------------------------|
| **labsai/EDDI** | 17.0 | Config-driven orchestration middleware: routing, memory, API orchestration, MCP/A2A/OpenAPI without custom glue | Control-plane config for agent routing + MCP tool registry; replace ad-hoc agent wiring with declarative routes/memory policies |
| **wshobson/agents** | 16.0 | Single Markdown source for agents/plugins + validate/test/generate tooling; multi-harness adapters | Mine/alive agent definitions as Markdown; generator + validator for Claude/Codex/Cursor-style harnesses used by NEXUS workers |
| **builderz-labs/mission-control** | 15.0 | Self-hosted SQLite control plane: task, observe, govern; install/deploy/test + OpenAPI parity | Ops surface for mine/alive runs: task table, status API, governance flags; OpenAPI contract tests for control endpoints |
| **codingagentsystem/cas** | 15.0 | Supervisor/workers in **git worktrees** + SQLite/MCP **persistent memory** | Isolate hard-apply PRs in worktrees under `.nexus_workspaces/`; SQLite memory for cross-worker state |
| **choihyunsus/soul** | 15.0 | MCP cross-session **memory, handoffs, immutable work ledger** (SQLite/vector) | MCP server (or extension) for handoffs between mine/grade/apply agents; append-only work ledger for durability demos |
| **wheattoast11/openrouter-deep-research-mcp** | 15.0 | Production MCP: **circuit breakers**, embedding model routing, key rotation, pglite persistence | Harden research/MCP clients used in arXiv + mine paths; circuit breaker + key rotation around Grok/provider calls |
| **automagik-dev/forge** | 15.0 | Productized multi-agent task platform: worktree isolation + MCP/agent orchestration | Demo CLI/workflow: goal → workers in worktrees → MCP tools; mirror NEXUS improve slice UX |
| **ahmedEid1/lumen** | 15.0 | One-sentence goal → loop with **agent-decision audit**, **honest public evals**, phased-migration durability | Grading demos: public eval report of mine scores; decision audit on apply; phased migration for schema/ledger changes |
| **IBM/AssetOpsBench** | 15.0 | Domain **MCP servers** + multi-provider runners + **evaluation harness** | Modular domain MCP packages (mine, grade, apply, research) + shared eval harness for Grok grades vs ground truth |
| **Jovancoding/Network-AI** | 15.0 | TS multi-agent control plane: dual packaging, **security exports**, CLI/MCP, framework adapters | Governance/coordination layer over heterogeneous stack; security exports for tool allowlists; CLI/MCP for demos |

**Honorable (same evidence band; pull selectively):** MattMagg/MisterSmith (supervised exec + durable state + MCP), StreetLamb/rojak (Temporal-style durable workflows/HITL), SolaceLabs/solace-agent-mesh (Makefile multi-layer tests, CVE-pinned deps), phodal/routa (workspace board: goals/tasks/traces/review), Intelligent-Internet/zenith (anti-premature-completion / replanning), openai/swarm (clean handoff primitive), 7836246/claude-team-mcp (workflow templates + roles).

---

## Prioritized engineering backlog

### P0 — Prove durable self-improve loop (must ship first)

| Item | Steal from | Files / modules to touch (concrete) |
|------|------------|-------------------------------------|
| **P0.1 Immutable work ledger + handoffs** | soul, cas, mission-control | MCP/memory layer; SQLite schema for `work_events` (append-only), `handoffs`, `agent_session`; wire into mine → grade → apply state machine |
| **P0.2 Deterministic apply decision packet** | 2511.15755, EDDI, lumen | Orchestration config + decision recorder: roles, scores, vote merge, audit JSON; reject apply without packet |
| **P0.3 Circuit breakers on MCP/LLM/research** | openrouter-deep-research-mcp | MCP client / provider router: breaker state, key rotation hooks, fail-open vs fail-closed for mine/alive |
| **P0.4 Anti-collusion dual control** | 2601.00360, wshobson/agents | Separate **grader** path (Grok 4.5) from **applier** path; hard-apply requires grade_id + independent threshold; no self-grade merges |
| **P0.5 Interleaving invariants for workers** | 1301.6431, cas, forge | Supervisor/worktree coordinator: legal transitions only (e.g. `graded → applying → testing → merged|aborted`); unit tests for illegal sequences |

### P1 — Mine/grade quality + observability

| Item | Steal from | Files / modules to touch |
|------|------------|--------------------------|
| **P1.1 Claim-verification grading** | Thucy 2512.03278, AssetOpsBench eval harness | Grader module: claim + evidence refs from clone path; structured grade schema (idea/skill already used — add claim_pass rate) |
| **P1.2 Causal step explanations** | 2302.10809, lumen audit | Ledger enrichment: `cause_of` / `because_of_event_id`; demo renderer for causal chains |
| **P1.3 Markdown agent/plugin marketplace pattern** | wshobson/agents | `agents/` or `plugins/` Markdown sources + `validate`/`generate` scripts; adapters for harnesses NEXUS already shells out to |
| **P1.4 Action-order policy config** | AOAD-MAT 2510.13343, EDDI | Declarative order: research → mine → grade → plan → apply → alive; enforce in orchestrator, not docs only |
| **P1.5 SQLite control plane API + OpenAPI parity** | mission-control | Task/observe/govern HTTP or internal API; OpenAPI spec + contract tests for status of mine_eval / improve runs |
| **P1.6 Emergent-behavior metrics in alive** | MAEBE 2506.03053, zenith (secondary) | Alive loop counters: replan count, premature-stop detections, handoff thrash; feed re-grade |

### P2 — Productization, demos, scale patterns

| Item | Steal from | Files / modules to touch |
|------|------------|--------------------------|
| **P2.1 Domain MCP package split** | AssetOpsBench, Network-AI | Separate MCP servers/packages: research, mine, grade, apply; security exports / tool allowlists |
| **P2.2 Preference / value-system traces** | 2602.04518 | Store human or Grok preference labels on apply outcomes; periodic rubric weight suggestion (offline) |
| **P2.3 Hierarchical improve decomposition** | 2008.06604, routa board patterns | Backlog DAG: goal → tasks → traces → review; workspace board fields if UI exists, else CLI report |
| **P2.4 Release/test engineering** | solace-agent-mesh, phodal/routa, lumen | Multi-layer Makefile/test targets; phased migration for ledger schema; CVE-pin discipline in deps |
| **P2.5 Handoff primitive cleanup** | openai/swarm, claude-team-mcp | Minimal Agent+handoff API for templates/roles in improve workflows |
| **P2.6 Adversarial / quarantine gate** | 2303.16641, EDDI routing | Quarantine low-trust mines; hierarchical approve path before code lands outside worktree |

---

## First apply slice  
**(smallest PR-sized change that proves the loop)**

### Goal
Prove **mine → Grok grade → durable ledger event → gated hard-apply decision** without porting a full product.

### Scope (one PR)

1. **Append-only work ledger** (SQLite or existing NEXUS store) with events:
   - `mine_completed` (repo, score, path under `.nexus_workspaces/mine_eval/`)
   - `grade_recorded` (method=`grok:grok-4.5`, idea/skill/total)
   - `apply_proposed` / `apply_rejected` / `apply_accepted` (requires `grade_id`, dual-control check)
2. **Decision packet** (JSON): source repo, score ≥ threshold (e.g. 15.0), pattern name, target module path, tests to run — **no code apply yet beyond a stub “pattern note” or single config flag** if needed to keep PR small.
3. **Circuit breaker stub** around one external call path used by grade/research (open/half-open/closed states + test fakes).
4. **Invariant**: apply_accepted cannot occur without prior grade_recorded from a **different** agent role (anti-collusion minimal).

### Explicit non-goals for this PR
- No full EDDI/mission-control UI  
- No Temporal, NATS, Solace, or new language runtime  
- No 32-adapter Network-AI surface  
- No worktree swarm (cas/forge) yet — that is P0.5 follow-up if ledger lands clean

### Suggested touch points
- Durable state / MCP memory module (new or existing)
- Mine/alive orchestration entrypoints that already write to `.nexus_workspaces/`
- Grading path that already records `method=grok:grok-4.5`
- Tests next to those modules (prefer small pure tests + one integration test with temp SQLite)

### Tests to run
1. **Unit:** ledger append-only (no update/delete of events); illegal transition `apply_accepted` without `grade_recorded` fails  
2. **Unit:** dual-control: same role cannot grade and accept  
3. **Unit:** circuit breaker opens after N failures and blocks call  
4. **Integration:** fixture mine row (e.g. `labsai/EDDI` score 17.0 or `choihyunsus/soul` score 15.0 from evidence) → grade event → decision packet → `apply_proposed` with pattern “immutable work ledger” → accept/reject path  
5. **Regression:** existing mine_eval / research report paths still resolve under `.nexus_workspaces/`  
6. **Demo script (optional but recommended):** print causal chain for one improve decision (lumen-style audit) to stdout for demo credibility  

### Success criteria (loop proved)
- [x] One graded mined repo produces a ledger chain visible in demo  
- [x] Hard-apply gate refuses missing/self grade  
- [x] Breaker tests green without live network  
- [x] PR-sized: reviewable in &lt; ~400 LOC of core logic + tests  
- [x] Documents the **next** slice (P0.5 worktree isolation or P1.1 claim-verification grading) in the PR body  

### Landed this cycle (Grok 4.5 CLI worker)

| Piece | Module / surface |
|-------|------------------|
| Append-only `work_events` | `src/nexus/work_ledger.py` (`nexus.work_ledger/v1`) under `.nexus_workspaces/work_ledger/` |
| Events | `mine_completed` · `grade_recorded` · `decision_packet` · `apply_proposed` · `apply_rejected` · `apply_accepted` |
| Dual-control | `apply_accepted` requires prior `grade_recorded` from a **different** agent/role |
| Decision packet | `build_decision_packet` / `validate_decision_packet` (`nexus.decision_packet/v1`) |
| Circuit breaker | `protected_call` + existing `CircuitBreaker` on grade path |
| Causal chain | `causal_chain` / `format_causal_chain` (lumen-style demo audit) |
| CLI | `nexus improve work-loop` · `nexus improve work-ledger` |
| Tests | `tests/test_work_ledger.py` (15 cases) |

### Immediate next PR after slice
**P0.5 + cas/forge worktree apply:** wire `work_ledger` accept into `worktree_apply` / alive `self_approve` so a real pattern port lands only after ledger dual-control + grade threshold; optional MCP tools `work_ledger_tail` / `work_loop`.

---

*Sources constrained to EVIDENCE only: Grok-graded mined repos, IMPROVE_OURS plan (score ≥10), and arXiv ids/titles listed in the research harvest. No invented paper ids or repos.*