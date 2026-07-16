# Self-improve cycle — Grok 4.5

_Generated 2026-07-16 00:24 UTC_

Model: `grok-4.5` · repos=20 · arXiv=20

---

The full evidence was truncated; reading the complete offloaded prompt so the plan only uses listed papers and repos.Looking for a way to load the full offloaded evidence so the plan stays grounded.# NEXUS Self-Improvement Plan  
**Target:** `/path/to/nexus-core`  
**Sources:** Grok 4.5–graded mined repos + arXiv research digests in EVIDENCE only  
**Focus:** multi-agent durability, MCP, mine/alive loops, grading, demos

---

## 1. Executive summary

- **Close the research→apply loop:** treat Grok-graded mine/eval outputs and arXiv digests as first-class inputs to a small, testable “hard apply” path—not more scout code dumps.
- **Durability first:** port worktree isolation + SQLite/ledger memory + checkpoint/resume patterns (cas, forge, soul, MisterSmith, rojak, AOAD-MAT / multi-stage workflow papers) so mine/alive runs survive restarts and partial failures.
- **MCP as the integration spine:** standardize durable shared memory, research backends, and multi-expert orchestration behind MCP (soul, openrouter-deep-research-mcp, claude-team-mcp, Network-AI, EDDI patterns)—not ad-hoc process glue.
- **Grading becomes product surface:** make Grok 4.5 idea/skill scoring, decision audits, traces/evidence, and eval harnesses (lumen, routa, mission-control, AssetOpsBench, wshobson/agents validate tooling) the gate for “alive” promotion.
- **First win is a PR-sized slice:** one durable mine-eval grade record + immutable work ledger entry + one demo path that proves checkpoint → resume → grade → promote, then stack the rest of the backlog on that spine.

---

## 2. 10 arXiv papers — what to steal for this codebase

| # | arXiv id | Idea (from EVIDENCE) | Concrete NEXUS change |
|---|----------|----------------------|------------------------|
| 1 | **2510.13343** | AOAD-MAT: action *order* matters in multi-agent RL; research tag *durable multi agent workflow checkpoint resume* | Encode explicit **agent action ordering** in the mine/alive scheduler; persist ordered step logs so resume never reorders completed worker steps after checkpoint. |
| 2 | **2604.03350** | Multi-stage workflow: model-based screening → data-driven surrogates for stochastic agent models; tag *durable multi agent workflow checkpoint resume* | Split mine/alive into **stages** (scout → grade → hard-apply → verify) with per-stage checkpoints and cheap “surrogate” grade caches so full Grok re-grade is optional on resume. |
| 3 | **2508.08322** | High research score (24) in multi-agent communication digests (`rx-f993cb901b`) | Treat as **comm protocol** input: formalize inter-agent message schemas + durable inbox for supervisor↔worker (pair with cas/forge worktree messaging). |
| 4 | **2512.03278** | Thucy: multi-agent claim verification across relational DBs; tag *multi agent communication coordination LLM* | Add a **claim/evidence verifier** agent over SQLite (or Postgres) stores: every mine “improvement claim” must cite ledger rows / test outputs before promote. |
| 5 | **2602.04518** | Preference-based + inverse RL for agent value systems; tag *tool use multi LLM agent systems* | Fit Grok grade dimensions (idea/skill) into a **preference model**: promote policies that maximize historical high-skill patterns; demote pure novelty without skill. |
| 6 | **2303.16641** | Hierarchical game-theoretic decisions under adversarial agents | Add a **supervisor game layer**: adversarial “skeptic” worker that tries to break apply patches; only promote if skeptic fails (fits alive self-improve safety). |
| 7 | **2506.03053** | MAEBE: multi-agent emergent behavior framework | Instrument mine/alive with **emergent-behavior metrics** (handoff loops, thrash, premature completion); feed into grading alongside idea/skill. |
| 8 | **2511.15755** | Multi-agent LLM orchestration for deterministic, high-quality incident-response decisions | Port **deterministic orchestration templates** for “incident-like” failure modes in the loop (failed tests, bad apply, MCP timeout)—scripted multi-agent playbooks, not free-form chat. |
| 9 | **2302.10809** | Causal explanations for sequential multi-agent decisions | Persist **causal decision traces** (why agent A was chosen, why tool X) next to grades—demo-friendly audit trail for hard-apply reviews. |
| 10 | **1301.6431** | Automatic verification of parameterised interleaved multi-agent systems | Add a **static interleaving checker** for concurrent worktree workers: detect illegal concurrent edits / racey handoffs before merge. |

**Supporting (not in top 10 but usable later):** 2008.06604 (hierarchical decomposition), 2601.00360 (anti-collusion → anti-agent-collusion in grading), 2603.20143 (perception→recomposition multi-agent stages).

---

## 3. 10 GitHub repos — portable patterns

Top-scoring / highest-leverage from EVIDENCE (prefer IMPROVE_OURS ≥15, then MCP/durability specialists).

| Repo | Score | Pattern to port | Where to port in NEXUS |
|------|------:|-----------------|-------------------------|
| **wshobson/agents** | 16.0 | Single Markdown skill source → multi-harness artifacts + generate/validate/test | Skill/catalog layer for mine→alive demos; one skill MD becomes Claude/Codex/Cursor/Grok harness adapters + CI validate |
| **labsai/EDDI** | 16.0 | Config-driven multi-agent middleware; MCP/A2A/OpenAPI; heavy test surface / OpenSSF hygiene | Config schema for agent graphs; MCP export surface; quality-gate bar for “production” loops |
| **builderz-labs/mission-control** | 15.0 | SQLite control plane: task/spend/ops; API parity checks; full quality gate; multi-config e2e | Ops/demo dashboard + spend/task accounting for mine/alive; Playwright-style e2e for control plane |
| **SolaceLabs/solace-agent-mesh** | 15.0 | Event-driven collaboration; broad unit/integration/eval/migration tests; CVE-aware pins | Optional broker-backed handoffs for long-running alive; eval+migration test pattern for durable state |
| **phodal/routa** | 15.0 | Delivery board with **traces + evidence** + CLI packaging | Demo board: each improve PR shows trace/evidence; CLI for operators |
| **automagik-dev/forge** | 15.0 | Kanban + **git worktree isolation** + MCP multi-tool orchestration | Mine/alive worker isolation in `.nexus_workspaces/*`; task board states |
| **codingagentsystem/cas** | 15.0 | Supervisor/workers in worktrees + **MCP/SQLite context** | Core orchestration substrate for durable coding agents |
| **ahmedEid1/lumen** | 15.0 | brief → durable build → cited RAG tutor; **decision audit**; phase-gated migrations, quotas, encryption | Decision audit on grades/applies; phase-gated schema migrations for ledgers |
| **Jovancoding/Network-AI** | 15.0 | Dual packaging, modular security/adapters, **CLI/MCP tooling**, cross-framework glue | MCP CLI adapters; modular security exports around tool use |
| **MattMagg/MisterSmith** | 15.0 | Supervision, durable messaging (NATS/JetStream), Postgres, MCP, multi-surface operators | Durable runtime substrate; supervision trees; multi-surface ops (CLI/API/demo) |

**Honorable high-value ports (use in P1/P2):**  
- **choihyunsus/soul** (14): durable shared memory, handoffs, **immutable work ledger**, entity/core memory via SQLite/vector  
- **StreetLamb/rojak** (13): Temporal-style durable workflows + HITL + MCP  
- **wheattoast11/openrouter-deep-research-mcp** (13): plan/parallelize/synthesize research MCP + circuit breakers + key rotation + PGlite  
- **Intelligent-Internet/zenith** (14): gap-finding, verification, skill registration, **stopping discipline** (anti premature completion)  
- **IBM/AssetOpsBench** (14): domain MCP servers + **evaluation harness**  
- **openai/swarm** (12): lightweight Agents + handoffs (educational pattern only)

---

## 4. Prioritized engineering backlog

### P0 — Durability + grade spine (unblocks the self-improve loop)

| Item | What | Files / modules to touch (concrete targets) |
|------|------|-----------------------------------------------|
| **P0.1** | Immutable **work ledger** (soul pattern): every mine/alive step append-only | `src/**/ledger*`, `src/**/memory*`, SQLite schema under `.nexus_workspaces/` or `data/`; migrations (lumen phase-gated) |
| **P0.2** | **Worktree-isolated workers** (cas + forge): supervisor spawns apply workers in git worktrees | `src/**/worktree*`, `src/**/orchestrat*`, `.nexus_workspaces/mine_eval/`, `.nexus_workspaces/scout_repos/` |
| **P0.3** | **Checkpoint / resume** for multi-stage workflows (papers 2510.13343, 2604.03350; rojak/MisterSmith ideas) | `src/**/checkpoint*`, `src/**/workflow*`, stage enum: `scout|grade|apply|verify|promote` |
| **P0.4** | Persist **Grok grades** (idea/skill/score/method) as first-class artifacts | `src/**/grade*`, `src/**/eval*`, mirror fields from mine_eval digests; write JSON/SQLite next to ledger |
| **P0.5** | MCP surface for **context + tools** used by workers (cas/soul/Network-AI) | `src/**/mcp*`, MCP server entrypoints, tool registry; wire ledger + grade + worktree tools |

### P1 — MCP research backend, audits, demos

| Item | What | Files / modules to touch |
|------|------|---------------------------|
| **P1.1** | Research MCP: plan / parallelize / synthesize + circuit breaker + key rotation (openrouter-deep-research-mcp) | `src/**/research*`, `src/**/mcp/research*`, config for provider keys |
| **P1.2** | **Decision audit** trail (lumen + paper 2302.10809): why grade, why apply, causal step links | `src/**/audit*`, `src/**/trace*`; demo renderer in routa-style board |
| **P1.3** | Skill marketplace pattern (wshobson/agents): one MD skill → validate/test/export | `skills/` or `plugins/`, `scripts/generate_skills*`, CI validate job |
| **P1.4** | Ops control plane surfaces: task/spend/status (mission-control) | `src/**/ops*`, `src/**/control*`, Docker/standalone packaging scripts |
| **P1.5** | Claim verification agent (Thucy 2512.03278): grade claims vs ledger + tests | `src/**/verify*`, `src/**/claim*`; tests that fail promote without evidence |
| **P1.6** | Stopping discipline / gap-finding (zenith): anti premature completion on long-horizon applies | `src/**/harness*`, completion criteria hooks in alive loop |

### P2 — Hardening, eval breadth, multi-runtime polish

| Item | What | Files / modules to touch |
|------|------|---------------------------|
| **P2.1** | Event-driven optional bus (solace-agent-mesh / MisterSmith NATS) for multi-host alive | `src/**/bus*`, `src/**/events*`; feature-flagged |
| **P2.2** | Eval harness expansion (AssetOpsBench + EDDI test-surface culture) | `tests/eval/`, migration tests, integration matrix |
| **P2.3** | Hierarchical / adversarial supervisor (paper 2303.16641) | `src/**/supervisor*`, skeptic agent profile |
| **P2.4** | Preference-shaped promotion policy (paper 2602.04518) using historical Grok grades | `src/**/policy*`, `src/**/promote*` |
| **P2.5** | Dual packaging / modular adapters (Network-AI, routa CLI) | package exports, CLI entrypoints, security adapter module |
| **P2.6** | Emergent-behavior metrics dashboard (MAEBE 2506.03053) | metrics collectors + demo board panels |
| **P2.7** | Interleaving / concurrency verification (1301.6431) for parallel worktrees | static checks in CI before merge-from-worktree |
| **P2.8** | Incident-response playbooks (2511.15755) for loop failures | `playbooks/` + deterministic multi-agent templates |

---

## 5. First apply slice (smallest PR-sized change that proves the loop)

### Goal
Prove **research/mine → Grok grade → durable ledger → resume-safe stage → demo artifact** without rewriting the whole orchestrator.

### Scope (one PR)

1. **Schema + module:** append-only `work_ledger` table (SQLite) with columns at least:  
   `id, ts, run_id, stage, agent, action, payload_json, parent_id`  
   Plus `grade_records`:  
   `repo_or_paper_id, score, idea, skill, method, summary, path, created_at`  
   (mirror EVIDENCE fields: score/idea/skill/method=grok:grok-4.5).

2. **Ingest one path already on disk:**  
   Read a single mine_eval digest under  
   `.nexus_workspaces/mine_eval/`  
   (e.g. `codingagentsystem__cas` or `wshobson__agents`) and insert one ledger row + one grade row. No network.

3. **Stage machine stub:**  
   `scouted → graded → apply_pending` with **checkpoint file** (JSON) so a second process resumes from `graded` without re-ingesting.

4. **MCP tool (minimal):**  
   `ledger.append`, `ledger.list`, `grade.get` — enough for a worker/supervisor to share durable memory (soul/cas pattern, thin).

5. **Demo CLI:**  
   `nexus improve status --run <id>` prints stage, last grade, last ledger events (routa/mission-control “evidence” lite).

### Explicit non-goals for this PR
- No full worktree apply engine  
- No OpenRouter research backend  
- No Playwright e2e  
- No broker/NATS  
- No multi-harness skill export  

### Tests to run
| Test | Asserts |
|------|---------|
| Unit: ledger append is immutable | no update/delete API; second append gets new id |
| Unit: grade record round-trip | fields match Grok grade shape from EVIDENCE |
| Unit: checkpoint resume | kill after `graded`; resume does not duplicate grade row |
| Integration: ingest fixture | load one recorded mine_eval path from `.nexus_workspaces/mine_eval/*` |
| Integration: MCP tools | `ledger.list` returns the ingested run |
| Smoke CLI | `improve status` exits 0 and shows score ≥ 10 fixture |

### Suggested commands (adapt to repo’s real runner)
```bash
# unit + integration for the slice
pytest tests/unit/test_work_ledger.py tests/unit/test_grade_records.py -q
pytest tests/integration/test_mine_eval_ingest.py tests/integration/test_checkpoint_resume.py -q
# if MCP tests exist
pytest tests/mcp/test_ledger_tools.py -q
# CLI smoke
python -m nexus improve status --run demo-cas
```

### Definition of done
- One PR merges that: (a) persists a real Grok-graded mine hit, (b) resumes without re-grade, (c) exposes state via CLI + MCP, (d) green tests above.  
- That PR is the **hard-apply proof** for the self-improve loop; P0.2–P0.5 and P1 stack on top.

### Landed follow-on (2026-07-16 — spine wire)

| Item | Status |
|------|--------|
| Dual-write spine grades → `grade_ledger` | ✅ `dual_write_to_grade_ledger` on ingest |
| Wire spine into `worktree_apply` / alive self_approve | ✅ `require_spine` + `ensure_grade_for_apply` |
| EDDI routing pattern catalog | ✅ `eddi-routing-ops` skillpack pattern |

**Next open:** spine-aware board ranking · openrouter research pattern · live Grok judge (gated)

---

### Apply order after the first slice
1. Worktree isolation (cas/forge) → real hard-apply ✅ (+ spine wire)  
2. Decision audit + claim verifier (lumen/Thucy) → safe promote  
3. Research MCP + skill validate (openrouter-deep-research-mcp / wshobson) → richer mine  
4. Ops board + eval harness (mission-control / AssetOpsBench / EDDI discipline) → demos & CI bar  

**Principle:** port **patterns + tests**, not whole trees; every port must touch ledger/grade/MCP or the mine/alive stage machine.