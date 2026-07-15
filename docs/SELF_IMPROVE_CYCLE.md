# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 21:58 UTC_

Model: `grok-4.5` · repos=20 · arXiv=20

---

The full evidence was truncated in the message; reading the offloaded prompt for the complete papers, repos, and NEXUS context.Reading the offloaded full prompt for complete evidence.# NEXUS Self-Improvement Plan  
**Source:** Grok 4.5 graded mine + arXiv research (EVIDENCE only)  
**Target:** `/path/to/nexus-core` — multi-agent durability, MCP, mine/alive loops, grading, demos

---

## 1. Executive summary

- **Close the loop, don’t clone trees:** Port *patterns* (durable memory, worktree isolation, MCP session ledgers, consensus review, Markdown SoT skills, eval CLI) from top-scored repos into small NEXUS modules with tests—not full monorepos.
- **Paper → control plane, not theory dump:** Steal action-order scheduling, claim-verification audit trails, deterministic multi-agent incident orchestration, causal decision logs, and hierarchical/adversarial guardrails; wire them into mine/alive, grading, and durability—not into greenfield research code.
- **P0 is proof of the self-improve loop:** One PR-sized slice (immutable agent decision ledger + Grok grade hook + smoke test) that demonstrates mine → grade → apply → re-grade before any large refactors.
- **MCP + SQLite/session durability is the shared spine** across cas, soul, mission-control, rojak, MisterSmith, and EDDI—NEXUS should unify session memory, handoffs, and idempotent task builds on that spine.
- **Demos and grading stay first-class:** AssetOpsBench-style eval CLI, gossipcat consensus review, and wshobson Markdown SoT generators make the self-improve story measurable and demoable.

---

## 2. 10 arXiv papers — what to steal for this codebase

Selected from EVIDENCE (highest research scores / clearest multi-agent orchestration signal). Titles and scores only where present in EVIDENCE; no invented IDs.

| # | arXiv id | Idea (from EVIDENCE) | Concrete NEXUS change |
|---|----------|----------------------|------------------------|
| 1 | **2510.13343** (score 20) | AOAD-MAT: order-of-action decisions among agents (transformer MARL) | In the alive/mine orchestrator, add an explicit **action-order policy** (who acts when: scout → grade → apply → verify) instead of free-for-all parallel workers; encode as a scheduler config + unit tests on ordering invariants. |
| 2 | **2508.08322** (score 16) | Multi-agent communication / coordination (query: multi agent communication coordination LLM) | Introduce a **typed inter-agent message schema** (goal, evidence refs, grade, apply patch) on the control plane so mine workers and graders communicate via durable messages, not ad-hoc prompts. |
| 3 | **2512.03278** (score 14) | Thucy: LLM multi-agent claim verification across relational DBs | Add a **claim-verify step** after mine/grade: every “portable pattern” or paper steal must be grounded against repo evidence (files, scores) stored in SQLite; reject ungrounded apply suggestions. |
| 4 | **2602.04518** (score 10) | Learning agent value systems via preference / inverse RL | Map Grok grades (`idea`, `skill`, composite `score`) into a **preference weight table** used by the apply prioritizer (e.g. prefer skill≥8 patterns for P0 ports). |
| 5 | **2303.16641** (score 10) | Hierarchical game-theoretic decisions under adversarial agents | Add a **supervisor vs worker trust tier**: apply patches only after a hostile “adversarial reviewer” agent (or rule pack) fails to find critical defects; log accept/reject. |
| 6 | **2506.03053** (score 9) | MAEBE: multi-agent emergent behavior framework | Instrument mine/alive runs with **emergent-behavior metrics** (premature stop, thrash, duplicate work, handoff loops); feed into demos and stop-control (zenith-aligned). |
| 7 | **2511.15755** (score 6) | Multi-agent LLM orchestration for deterministic, high-quality incident response | Make the self-improve pipeline **deterministic where possible**: fixed stage graph, seedable grading prompts, replayable apply from ledger—demo as “incident-style” recovery of a failed mine run. |
| 8 | **2603.20143** (score 6) | Multi-agent orchestration: perception + generative recomposition (expert inspection) | Split mine into **perceive (digest/score) → recompose (patch plan) → inspect (tests)** stages with an evidence board (routa-style) for demos. |
| 9 | **2302.10809** (score 5) | Causal explanations for sequential multi-agent decisions | Persist a **causal decision log** per run: why agent A graded B, why apply chose pattern X; surface in CLI/TUI and demo UI. |
| 10 | **1301.6431** (score 5) | Automatic verification of parameterised interleaved multi-agent systems | Add lightweight **interleaving invariants** tests: concurrent workers on worktrees must not violate isolation (no shared dirty main tree, no double-apply same PR slice). |

*Also present in EVIDENCE but deprioritized for the top-10 apply list:* `2008.06604` (hierarchical decomposition control), `2601.00360` (anti-collusion, score 2), `2604.03350` (multi-stage stochastic ABM workflow—line truncated).

---

## 3. 10 GitHub repos — portable patterns

Top IMPROVE_OURS / highest-scored portable sources from EVIDENCE (patterns only, not whole trees).

| Repo | Score | Pattern to port | Where in NEXUS |
|------|------:|-----------------|----------------|
| **wshobson/agents** | 16.0 | Single Markdown source-of-truth for agents/skills/commands + harness-native generators + validation/smoke tests | `skills/` or `nexus/skills_marketplace/`: SoT MD → generators for Grok/Claude/Codex adapters; CI smoke that regenerated artifacts match |
| **builderz-labs/mission-control** | 15.0 | Self-hosted ops control plane: tasks, spend, adapters, SQLite; API parity checks; CLI/MCP/TUI quality gates | `nexus/ops/` or control-plane package: task+spend tables, MCP surface parity test, Docker/quality gate scripts |
| **IBM/AssetOpsBench** | 15.0 | Modular MCP domain servers + multi-backend agents + **evaluation CLI** scaffold | `nexus/eval/` + MCP domain stubs for mine/grade/apply; `nexus eval` CLI mirroring AssetOpsBench packaging (hatch/uv-style if Python path exists) |
| **gossipcat-ai/gossipcat-ai** | 15.0 | Multi-agent **consensus code review** with cross-checks and adaptive trust | Post-apply **review orchestrator** before merge: N reviewers, trust-weighted accept; hook into grading |
| **codingagentsystem/cas** | 15.0 | Rust-style multi-crate: supervisor/workers in **git worktrees** + MCP/SQLite persistent memory | Mine/alive workers: one worktree per apply job; SQLite memory for session; supervisor process model |
| **automagik-dev/forge** | 15.0 | Human-in-the-loop Kanban tasks on isolated worktrees + multi-agent/MCP hooks + solid CI/ops | HITL gate on P0 applies; Kanban status for mine→grade→apply; CI scaffolding patterns |
| **ahmedEid1/lumen** | 15.0 | Durable/idempotent builds + **agent-decision audit** + phased migration ops | Idempotent apply keys (content-hash of pattern); decision audit table; phased migration for SQLite schema |
| **Jovancoding/Network-AI** | 15.0 | Dual packaging discipline, security/adapters exports, CLI/MCP tooling, broad adapters | MCP adapter layer + security export surface; CLI entrypoints consistency |
| **phodal/routa** | 15.0 | Workspace-first coordination + **traces / evidence board** | Demo: evidence board for paper+repo steals; run traces linked to grades |
| **labsai/EDDI** *or* **choihyunsus/soul** | 15.0 / 14.0 | EDDI: config-driven orchestration + MCP/A2A + massive test discipline; soul: MCP durable session memory, handoffs, entity/core memory, **immutable ledger** on SQLite/vec | Config-driven stage graphs; MCP session memory + immutable ledger for handoffs (prefer soul’s ledger shape for P0) |

**Honorable ports (P1/P2, still in EVIDENCE):**  
StreetLamb/rojak (Temporal-style durable workflows), MattMagg/MisterSmith (supervised runtime, NATS/JetStream, Postgres workflows), Intelligent-Internet/zenith (anti-premature-stop, gap-finding, replanning), openai/swarm (minimal handoff API as design inspiration), swarmclawai/swarmclaw (skills+schedules+MCP runtime).

---

## 4. Prioritized engineering backlog

### P0 — Prove the self-improve loop (durability + grade + apply)

| Item | Touch points (modules/files to create or extend) |
|------|--------------------------------------------------|
| **P0.1 Immutable decision ledger (soul + lumen)** | `nexus/memory/ledger.py` (or Rust crate if that is the runtime), SQLite schema `agent_decisions(id, run_id, agent, claim, evidence_refs, grade, action, content_hash, created_at)`; append-only API |
| **P0.2 Action-order scheduler (paper 2510.13343)** | `nexus/orchestrator/stages.py`: fixed order `scout → mine → grade → claim_verify → plan_apply → review → apply → regrade`; config YAML |
| **P0.3 Grok grade adapter + preference weights (paper 2602.04518)** | `nexus/grading/grok_grader.py`, weights from `idea`/`skill`/`score`; load mined JSON from `.nexus_workspaces/mine_eval/` |
| **P0.4 Claim verification against evidence DB (paper 2512.03278)** | `nexus/grading/claim_verify.py`: refuse apply if pattern lacks path/score/evidence row |
| **P0.5 Worktree-isolated apply worker (cas + forge)** | `nexus/workers/worktree_apply.py`: create worktree, apply patch, run tests, report; never dirty main |
| **P0.6 First smoke + unit tests** | `tests/test_ledger.py`, `tests/test_stage_order.py`, `tests/test_claim_verify.py`, `tests/test_worktree_isolation.py` |

### P1 — MCP, ops plane, review, demos

| Item | Touch points |
|------|----------------|
| **P1.1 MCP session memory + handoffs (soul, Network-AI, mission-control)** | `nexus/mcp/server.py`, session tools: `memory_get/set`, `handoff`, `ledger_append`; parity tests CLI↔MCP |
| **P1.2 Consensus review gate (gossipcat)** | `nexus/review/consensus.py`: multi-agent cross-check + adaptive trust threshold before apply lands |
| **P1.3 Markdown skills SoT + generators (wshobson/agents)** | `skills/**/*.md`, `nexus/skills/generate.py`, validation + smoke in CI |
| **P1.4 Ops control plane lite (mission-control)** | `nexus/ops/tasks.py`, spend/budget counters, SQLite task board; CLI `nexus ops` |
| **P1.5 Eval CLI scaffold (AssetOpsBench)** | `nexus/eval/cli.py`: run fixed mine fixtures, emit grade JSON, exit non-zero on regression |
| **P1.6 Evidence board + causal log UI/CLI (routa + paper 2302.10809)** | `nexus/demo/evidence_board.py`, CLI `nexus demo run-self-improve` |
| **P1.7 Idempotent apply + phased migrations (lumen)** | `nexus/apply/idempotency.py`, `migrations/` for ledger/ops schemas |

### P2 — Hardening, research control, enterprise patterns

| Item | Touch points |
|------|----------------|
| **P2.1 Anti-premature-stop / replan (zenith + MAEBE metrics)** | `nexus/orchestrator/stop_control.py`, gap-finder, max-step + quality gates |
| **P2.2 Adversarial reviewer tier (paper 2303.16641)** | `nexus/review/adversarial.py` |
| **P2.3 Durable long-running workflows (rojak / MisterSmith patterns)** | Optional Temporal-like checkpoint API in `nexus/durability/workflow.py` (crash-safe resume of mine runs) |
| **P2.4 Hierarchical decomposition of control (paper 2008.06604)** | Supervisor/sub-goal tree in orchestrator |
| **P2.5 Packaging / dual adapters / quality gates (Network-AI, EDDI, solace-agent-mesh)** | CI pins, CVE-aware deps checklist, coverage gates, dual export surfaces where applicable |
| **P2.6 Deterministic incident-style recovery demo (paper 2511.15755)** | `demos/incident_self_heal/`: kill mid-run, resume from ledger, show deterministic finish |
| **P2.7 Handoff minimal API polish (openai/swarm inspiration)** | `nexus/agents/handoff.py` thin Agent+handoff types for demos/docs |

---

## 5. First apply slice (smallest PR that proves the loop)

### Goal
Ship a **single PR-sized vertical slice**: *mine digest → Grok-shaped grade record → immutable ledger append → claim-verify → ordered stage smoke*, with no production apply to main yet—proves grading + durability + ordering without multi-repo risk.

### Scope (do this, nothing more)

1. **SQLite append-only ledger** for agent decisions (soul/lumen pattern).  
2. **Stage order config** enforcing `mine → grade → claim_verify` (AOAD-MAT-inspired).  
3. **Loader** for existing Grok mine grades under `.nexus_workspaces/mine_eval/*` (use real digests, e.g. `wshobson__agents`, `codingagentsystem__cas`).  
4. **Claim verify**: grade row must include `score`, `idea`, `skill`, `path` or fail.  
5. **CLI**: `nexus improve smoke` (or script equivalent) runs the three stages and prints ledger tail + pass/fail.  
6. **Tests only**—no live network, no full worktree apply yet.

### Suggested files (new or minimal)

```
nexus/memory/ledger.py
nexus/memory/schema.sql
nexus/orchestrator/stages.py
nexus/grading/load_mine_eval.py
nexus/grading/claim_verify.py
nexus/cli/improve_smoke.py   # or scripts/improve_smoke.py
tests/test_ledger.py
tests/test_stage_order.py
tests/test_claim_verify.py
tests/fixtures/mine_eval_sample.json  # slimmed from real mine_eval digest
```

### Acceptance criteria

- Appending the same decision twice is either rejected or idempotent by `content_hash` (lumen).  
- Stages refuse to run out of order (paper 2510.13343).  
- Fake grade missing `path` or `score` fails claim_verify (Thucy-style).  
- Real fixture from `wshobson/agents` (score 16.0) passes end-to-end smoke.  
- Ledger rows queryable for demo (`SELECT` last N decisions).

### Tests to run

```bash
# Unit
pytest tests/test_ledger.py tests/test_stage_order.py tests/test_claim_verify.py -q

# Integration smoke (no network)
pytest tests/test_improve_smoke.py -q
# or
python -m nexus.cli.improve_smoke --fixture tests/fixtures/mine_eval_sample.json

# Optional hygiene if present in repo
ruff check nexus/memory nexus/grading nexus/orchestrator
mypy nexus/memory nexus/grading nexus/orchestrator  # if typed
```

### Explicit non-goals for this PR

- No worktree apply to real packages yet (P0.5 next PR).  
- No MCP server yet (P1.1).  
- No consensus multi-reviewer (P1.2).  
- No full mission-control dashboard.  
- No wholesale vendoring of any mined repo.

### Next PR after green smoke

Worktree-isolated apply of **one** ported pattern: e.g. “Markdown skill SoT validator” from **wshobson/agents** (highest score 16.0) into `skills/` + smoke test—still ledgered, claim-verified, ordered.

---

**Loop mantra:** *mine → grade (Grok) → claim-verify → ledger → ordered apply → re-grade → demo.*  
Every later P1/P2 item plugs into that spine; nothing ships without a test and a ledger entry.