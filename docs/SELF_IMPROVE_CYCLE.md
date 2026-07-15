# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 23:40 UTC_

Model: `grok-4.5` · repos=20 · arXiv=20

---

I'll read the full offloaded prompt to extract all evidence, then write the plan from that only.Reading the full offloaded prompt for complete evidence.Trying filesystem access to load the full offloaded prompt.# NEXUS Self-Improvement Plan  
**Target:** `/path/to/nexus-core`  
**Method:** Grok 4.5 grade → reason → hard-apply patterns (not whole trees)  
**Evidence constraints:** Only papers/repos present in EVIDENCE. One paper title was mid-truncated in the prompt payload; id is kept, title is marked incomplete.

---

## Executive summary

- **Close the loop:** Treat mine → Grok grade → improve → re-mine as a durable workflow with checkpoint/resume, immutable grade ledgers, and public retention of weak scores (not only winners).
- **Steal orchestration, not frameworks:** Highest-value ports are ops patterns—domain MCP servers + eval CLI (AssetOpsBench), workspace board for goals/tasks/traces (routa), cross-session memory/handoffs (soul), supervised durability (MisterSmith/rojak), worktree isolation (cas/forge).
- **MCP as the integration spine:** Memory, research, team orchestration, and domain tools should attach as MCP servers with circuit breakers, budgets, and shared state—not ad-hoc LLM glue.
- **Durability first, then demos:** Checkpoint/resume and idempotent apply steps unlock long-horizon alive/mine loops; demos and Kanban/control-plane UX ride on that foundation.
- **First proof PR:** Smallest end-to-end slice = immutable mine-eval grade ledger + eval CLI + “keep weak scores” policy, wired into existing Grok grading output under `.nexus_workspaces/mine_eval/`.

---

## 10 arXiv papers — what to steal for this codebase

| # | arXiv id | Idea (from EVIDENCE) | Concrete NEXUS change |
|---|----------|----------------------|------------------------|
| 1 | **2510.13343** | AOAD-MAT: ordered multi-agent action decisions (query: durable multi-agent workflow checkpoint/resume; report score 29) | Encode **explicit action-order policies** in mine/alive orchestrators (who acts when under shared state); persist order + partial results for resume after crash. |
| 2 | **2604.03350** | Multi-stage workflow: model-based screening → data-driven surrogates (query: durable multi-agent workflow checkpoint/resume; score 28) | Split mine/alive into **staged pipelines** (screen → deep-eval → apply) with stage checkpoints so expensive Grok grading is not repeated. |
| 3 | **2508.08322** | Present in research report path `rx-1bccfca000` (score 22); **title truncated in EVIDENCE** | Re-read local `NEXUS_RESEARCH_REPORT.md` before apply; treat as high-signal durable-orchestration paper once title/body available. |
| 4 | **2512.03278** | Thucy: multi-agent claim verification over relational DBs (query: multi-agent communication/coordination; score 20) | Add a **claim-verify agent** over durable store (SQLite/Postgres): “this repo scored X / this PR applied pattern Y” with DB-backed audit for grading demos. |
| 5 | **2602.04518** | Learn agent value systems via preference / inverse RL (score 14) | Use Grok grades as **preference signals** to tune mine ranking weights (idea vs skill) instead of hard-coded score thresholds only. |
| 6 | **2303.16641** | Hierarchical game-theoretic decisions under adversarial agents (score 14) | Model **supervisor vs worker** (and adversarial/noisy tool output) with hierarchical policies + budgets/guardrails in the control plane. |
| 7 | **2506.03053** | MAEBE: multi-agent emergent behavior framework (score 13) | Instrument alive loops for **emergent failure modes** (premature stop, thrash, collusion); log metrics for stopping discipline. |
| 8 | **2511.15755** | Multi-agent LLM orchestration for deterministic incident-response decision support (score 8) | For ops demos: **deterministic playbooks** (template workflows) over free-form chat for incident-style mine/apply failures. |
| 9 | **2603.20143** | Multi-agent orchestration: perception + generative recomposition for expert inspection (score 8) | Structure research demos as **perceive (mine digest) → recompose (improve plan) → inspect (grade again)**. |
| 10 | **2302.10809** | Causal explanations for sequential multi-agent decisions (score 7) | Attach **causal decision audits** to grade/apply steps (why this repo/pattern was chosen)—pairs with lumen-style decision audit. |

**Also present but lower priority (not in top 10 apply set):** `1301.6431` (parameterised interleaved MAS verification), `2008.06604` (hierarchical control decomposition), `2601.00360` (anti-collusion mechanisms)—use later for formal checks / anti-gaming of grades.

---

## 10 GitHub repos — portable patterns

Selected from IMPROVE_OURS / Grok-graded list (highest scores, port patterns not trees).

| Repo | Score | Pattern to steal | Where to port in NEXUS |
|------|------:|------------------|------------------------|
| **IBM/AssetOpsBench** | 16.0 | Domain MCP servers + multi-backend runners + **evaluation CLI** as installable package | `mine_eval` / grading package: eval CLI over Grok grades; modular MCP surfaces for domain tools |
| **phodal/routa** | 16.0 | Externalize **goals, tasks, traces, review** onto a workspace board; dual-backend monorepo discipline | Alive/mine control board UI + durable task/trace store; monorepo crate/package splits |
| **wshobson/agents** | 15.0 | Single-source **agent/plugin marketplace** + multi-harness generators + validation | Prompt/plugin catalog for mine/alive roles; generators + schema validation gates |
| **builderz-labs/mission-control** | 15.0 | SQLite control plane: **tasks, spend, runtimes, webhooks**; OpenAPI parity; Vitest/Playwright | Ops layer: spend/runtime budgets for Grok calls; webhook hooks for mine completion |
| **SolaceLabs/solace-agent-mesh** | 15.0 | Event-driven multi-agent mesh; **CVE-aware pins**; mature Makefile/test surface | Event bus between mine/alive/grade workers; Makefile CI targets; dependency pinning hygiene |
| **labsai/EDDI** | 15.0 | **Config-driven** routing, memory, MCP/A2A/OpenAPI/OAuth middleware | Declarative agent routing config (not hard-coded graphs); MCP + OpenAPI integration style |
| **ahmedEid1/lumen** | 15.0 | Durable **idempotent** build loop; decision audit; phased migration guards; **public evals keep weak scores** | Idempotent improve-apply; migration guards for schema; grade store retains low scores |
| **Jovancoding/Network-AI** | 15.0 | Control plane: shared **state, budgets, guardrails**; dual packaging; CLI/MCP | Shared budget/guardrail module for heterogeneous agents; CLI + MCP dual entrypoints |
| **choihyunsus/soul** | 15.0 | MCP **cross-session memory**: KV, entity/core memory, handoffs, **immutable ledger**; SQLite/vector | Session memory MCP for mine→alive handoff; immutable grade/apply ledger |
| **MattMagg/MisterSmith** | 15.0 | Rust multi-crate **supervised execution** + NATS/Postgres durability + MCP + operator surfaces | Supervisor runtime for workers; durable job queue; operator APIs for demos |

**Honorable ports (next wave, still in EVIDENCE):**  
`codingagentsystem/cas` & `automagik-dev/forge` (git worktree isolation), `StreetLamb/rojak` (Temporal durable workflows + HITL), `openai/swarm` (lightweight handoff semantics), `Intelligent-Internet/zenith` (stopping discipline / anti-premature-completion), `wheattoast11/openrouter-deep-research-mcp` (circuit breakers, key rotation), `7836246/claude-team-mcp` (workflow templates / expert teams).

---

## Prioritized engineering backlog

### P0 — Prove durability + grading loop (must ship first)

| Item | Touch areas (modules / paths under nexus-core) |
|------|--------------------------------------------------|
| **P0.1 Immutable grade ledger** (soul + lumen) | `mine_eval` store; SQLite (or existing workspace DB); append-only grades with idea/skill/method fields already produced by Grok |
| **P0.2 Keep weak scores public** (lumen) | Grade retention policy; filters that currently drop low scores; mine_eval report generators |
| **P0.3 Evaluation CLI** (AssetOpsBench) | New thin CLI (e.g. `nexus grade report|compare|export`) over ledger; CI-friendly exit codes |
| **P0.4 Stage checkpoints** (papers 2510.13343, 2604.03350) | Mine pipeline stages: scout → digest → Grok grade → IMPROVE_OURS plan → apply; checkpoint after each stage under `.nexus_workspaces/` |
| **P0.5 Idempotent apply markers** (lumen) | Improve-apply path: content-addressed “pattern already ported” markers so re-runs don’t double-apply |

### P1 — MCP + multi-agent durability

| Item | Touch areas |
|------|-------------|
| **P1.1 Memory/handoff MCP** (soul) | MCP server package: KV + handoff + ledger tools for alive/mine session continuity |
| **P1.2 Supervisor + worktree workers** (cas, forge, MisterSmith) | Orchestrator: supervisor assigns worktrees; workers isolated; status events back to control plane |
| **P1.3 Shared budgets & guardrails** (Network-AI, mission-control) | Central budget (tokens/spend/time) + guardrail middleware around Grok and tool calls |
| **P1.4 Config-driven routing** (EDDI) | YAML/JSON agent routes: role → model → tools → memory scope |
| **P1.5 Event mesh between loops** (solace-agent-mesh pattern, not Solace lock-in) | Internal pub/sub: `mine.completed`, `grade.ready`, `apply.started`, `alive.tick` |
| **P1.6 Causal / decision audit trail** (lumen + paper 2302.10809) | Structured “why this pattern” records next to grades and apply commits |

### P2 — Marketplace, demos, hardening

| Item | Touch areas |
|------|-------------|
| **P2.1 Agent/plugin catalog** (wshobson/agents) | Single-source role prompts + validation schemas for mine/alive/grader agents |
| **P2.2 Workspace board UX** (routa) | Goals/tasks/traces/review board for demos of live improve loops |
| **P2.3 Ops surfaces** (mission-control) | Tasks, spend, runtimes, webhooks; OpenAPI parity for control plane |
| **P2.4 Workflow templates / teams** (claude-team-mcp, openai/swarm handoffs) | Named expert teams + handoff protocol for research vs coding vs review |
| **P2.5 Stopping discipline** (zenith + MAEBE) | Alive-loop anti-premature-completion + thrash detectors |
| **P2.6 Circuit breakers / key rotation** (openrouter-deep-research-mcp) | Research MCP resilience when calling external model APIs |
| **P2.7 Preference-tuned ranking** (paper 2602.04518) | Learn ranking weights from historical Grok grades |
| **P2.8 Claim-verify over DB** (Thucy / 2512.03278) | Demo: multi-agent verification of “improve applied correctly” claims |

---

## First apply slice  
*(smallest PR-sized change that proves the self-improve loop)*

### Goal
Prove **mine → Grok grade → durable retain → report** without yet porting full orchestration.

### Status: **LANDED** (2026-07-15) — see `docs/LATEST_IMPROVE_PLAN.md` for files/tests.

Operator proof::

```bash
nexus grade ingest --fixture tests/fixtures/mine_eval_sample.json
nexus grade top -n 10
nexus grade weak --max-score 14
nexus grade export --format md
# alias: nexus-eval top --n 10
```

### Scope (landed)

1. **Append-only grade ledger** — SQLite under `.nexus_workspaces/mine_eval/ledger/`; weak scores retained; no UPDATE/DELETE.  
2. **Eval CLI** — `nexus grade` / `nexus-eval` list|top|weak|export|ingest|checkpoint.  
3. **Checkpoint helper** — `checkpoint_stage` / `load_checkpoint`; mine `step_evaluate` resume skip.  
4. **Decision audit stub** — `why_selected` on export (CEMA / lumen).

### Explicit non-goals for this PR
- No full MCP server yet  
- No worktree supervisor  
- No UI board  
- No Temporal/NATS  
- No hard-apply of foreign repo code trees  

### Immediate next PR (P0.5 / P1.1 preview)
Wire ledger export into an **idempotent apply plan** consumer (markers only), then add soul-style MCP handoff so alive loop reads the same ledger.

---

### Apply order after first slice
1. P0 complete (ledger + CLI + checkpoints + weak-score policy)  
2. P1.1 memory/handoff MCP + P1.2 worktree supervisor  
3. P1.3–P1.6 budgets, routing, events, audit  
4. P2 demos (routa board, mission-control ops, plugin catalog)

### Evidence hygiene
- Do **not** invent paper ids or repos beyond EVIDENCE.  
- Re-open truncated research payload / `NEXUS_RESEARCH_REPORT.md` for full title of **2508.08322** before citing it in product docs.  
- Prefer pattern extraction from local clones under `.nexus_workspaces/scout_repos/` and `.nexus_workspaces/mine_eval/` over vendoring entire trees.