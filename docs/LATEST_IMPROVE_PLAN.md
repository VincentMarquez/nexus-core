# Latest improve plan (from full self-improve cycle)

The full prompt was truncated in the message; I'll load the offloaded file so the plan uses only the complete EVIDENCE.I'll load the full offloaded prompt next so the plan can cite only papers and repos actually present in the evidence.# NEXUS Self-Improvement Plan  
**Source:** mined repos (Grok 4.5 grades) + arXiv research hits in EVIDENCE only  
**Target:** `/path/to/nexus-core`  
**Loop:** mine → grade (Grok 4.5) → reason → hard-apply → demo/alive verify  

---

## 1. Executive summary

- **Highest-leverage steal is ops durability, not new agent algorithms:** score-15 repos (`mission-control`, `MisterSmith`, `lumen`, `routa`, `rojak`-class patterns) and paper **2510.13343** (checkpoint/resume, ordered decisions) push NEXUS toward crash-safe multi-agent workflows with explicit resume and action-order control.
- **MCP is the integration spine:** reuse patterns from `AssetOpsBench` (domain MCP servers + eval CLIs), `AgenticGoKit` / `EDDI` / `swarmclaw` (MCP + multi-provider), and `zenith` (MCP/ACP long-horizon harness) to harden NEXUS MCP surfaces, tool catalogs, and alive-loop tool invocation.
- **Mine/alive loops should copy “honest eval + premature-stop defense”:** `lumen` (agent-decision audit, public evals), `zenith` (premature completion as primary failure mode; adaptive workers/testers/skills/replanning/stopping), and `IBM/AssetOpsBench` (benchmark packaging) map directly onto NEXUS mine_eval grading and alive demos.
- **Control-plane and delivery UX patterns are portable product glue:** `mission-control` (SQLite tasks/spend/adapters, CLI/MCP/TUI, contract tests), `routa` (goals/tasks/traces/evidence/review board), `Hermes-Studio` (cron, approvals, memory ops) → NEXUS fleet/ops surfaces and demo dashboards without forking whole monorepos.
- **First hard-apply slice must be PR-sized and loop-proving:** one durable checkpoint+resume path for mine/alive + one Grok grading artifact contract + one MCP tool registration test—prove “mine → grade → apply → re-eval” before broader backports from the top-10 repos/papers.

---

## 2. 10 arXiv papers — what to steal for this codebase

Selected from EVIDENCE only (ids + titles + scores present). Prefer higher research scores and themes: durable multi-agent workflow / checkpoint-resume / LLM orchestration.

| # | arXiv id | Idea (from EVIDENCE) | Concrete NEXUS change |
|---|----------|----------------------|------------------------|
| 1 | **2510.13343** | AOAD-MAT: ordered action decisions in multi-agent RL; EVIDENCE tags *durable multi agent workflow checkpoint resume* (score **13**) | Add **ordered agent step scheduler** + **checkpoint at decision boundaries** in the multi-agent runtime; resume must restore “who acts next” not only state blobs. |
| 2 | **2508.08322** | Present in research index with score **10** (title not fully present in visible EVIDENCE; report: `rx-5536a7eec8/NEXUS_RESEARCH_REPORT.md`) | Ingest findings only from that report into a **NEXUS research→backlog mapper** (paper id → proposed module patch); do not invent mechanisms beyond the stored report. |
| 3 | **2512.03278** | Thucy: LLM multi-agent claim verification across relational DBs (score **8**); *multi agent communication coordination* | Port **cross-source claim/verify handoff**: mine/grade claims must cite evidence rows (repo digests, eval scores) with a verifier agent before “hard apply”. |
| 4 | **2602.04518** | Learning agent value systems via preference + inverse RL (score **6**) | Map Grok grade dimensions (`idea`, `skill`, composite) into an explicit **preference vector** used by mine ranking and alive “keep vs drop” decisions. |
| 5 | **2303.16641** | Hierarchical game-theoretic decisions under adversarial agents (score **6**) | Add **adversarial/skeptic role** in grading and apply review: one agent proposes port, one attacks portability/safety before merge. |
| 6 | **2506.03053** | MAEBE: multi-agent emergent behavior framework (score **5**) | Instrument **emergent-behavior metrics** in multi-agent runs (loops, thrash, premature stop, tool storms) for alive demos and mine_eval dashboards. |
| 7 | **2511.15755** | Multi-agent LLM orchestration for deterministic, high-quality incident-response decisions (score **4**) | Codify **deterministic orchestration playbooks** for incident-like failures (stuck mine, MCP timeout, resume corruption): fixed role order + audit trail. |
| 8 | **2603.20143** | Multi-agent orchestration for expert-level inspection via perception + generative recomposition (score **4**) | Split **inspect vs recompose** in code review/port loops: inspect mined pattern → recompose into NEXUS-shaped module + tests. |
| 9 | **2604.03350** | Multi-stage workflow: model-based screening → data-driven surrogates for stochastic agent-based models; *durable multi agent workflow checkpoint resume* | Implement **multi-stage mine pipeline**: cheap screen → deep Grok grade → surrogate score cache → resume-able stages with artifacts per stage. |
| 10 | **2302.10809** | Causal explanations for sequential multi-agent decisions (score **3**) | Emit **causal step explanations** in grade/apply traces (“accepted because skill≥8 and durability pattern matches checkpoint module”) for demos and human audit. |

**Lower priority (EVIDENCE only; do not block P0):**  
`1301.6431` (parameterised interleaved MAS verification), `2008.06604` (hierarchical decomposition/control), `2601.00360` (anti-collusion mechanisms)—useful later for formal checks and collusion-resistant multi-agent grading, scores 1–3.

---

## 3. 10 GitHub repos — portable patterns

Top **10** by Grok score from EVIDENCE (ties broken by idea score / NEXUS fit: durability, MCP, mine/alive, grading, demos). Port **patterns**, not trees.

| Repo | Score | Portable pattern | Where to port in NEXUS |
|------|------:|------------------|------------------------|
| **builderz-labs/mission-control** | 15.0 | SQLite-backed agent control plane: tasks, spend, adapters; CLI/MCP/TUI; API contract checks; lint/typecheck/unit/e2e gate | Fleet/ops control plane; task + spend ledger for mine/alive runs; contract tests around MCP/CLI |
| **ahmedEid1/lumen** | 15.0 | Durable multi-agent loop (brief → build → citation RAG tutor); **agent-decision audit**; honest public evals; migration-phase ops discipline | Mine→grade→apply loop structure; decision-audit log; public eval report for demos |
| **IBM/AssetOpsBench** | 15.0 | Reusable **MCP domain servers**, multi-framework agent CLIs, evaluation tooling | NEXUS MCP domain servers for mine/grade/apply; CLI eval harness; benchmark-style fixtures |
| **phodal/routa** | 15.0 | Workspace-first board: **goals, tasks, traces, evidence, review state** | Delivery board / demo UI for self-improve runs; evidence attached to every apply PR |
| **labsai/EDDI** | 15.0 | Config-driven multi-agent middleware; MCP/A2A/OpenAPI/OAuth; Docker + high test/coverage discipline | Config schema for agent graphs; enterprise-grade packaging/tests for MCP surfaces |
| **MattMagg/MisterSmith** | 15.0 | Supervision + durable store + **MCP** + operator surfaces; modular runtime substrate | Durability substrate (supervision, durable events/state); operator hooks for alive |
| **wshobson/agents** | 15.0 | One Markdown plugin source → multi-harness artifacts; **generate/validate/test + drift** tooling | Skill/plugin catalog for NEXUS tools; drift checks so mine-generated skills stay valid |
| **Intelligent-Internet/zenith** | 14.0 | Long-horizon harness: **premature completion = core failure**; adaptive workers/testers/skills/replanning/stopping over MCP/ACP | Alive-loop stopping criteria; replan/tester roles; anti-early-exit in demos |
| **JPeetz/Hermes-Studio** | 14.0 | Self-hosted studio: multi-agent orchestration, **cron, approvals, memory** tooling; modern test setup | Approvals gate before hard-apply; scheduled mine/alive; memory/ops UI patterns |
| **AgenticGoKit/AgenticGoKit** | 14.0 | Streaming-first APIs; sequential/parallel/**DAG/loop** orchestration; memory/RAG; MCP; OpenTelemetry | DAG/loop orchestrator patterns; OTel traces for multi-agent durability demos |

**Strong alternates (score ≥14, port later):**  
`gossipcat-ai/gossipcat-ai` (consensus code review + adaptive trust), `Mybono/ai-orchestrator` (dependency-ordered execution, file-mediated handoffs, fix loops, outcome-driven skill learning), `fancy1108/Clutch` (local-first control plane shell), `SolaceLabs/solace-agent-mesh` (event-driven test matrix—hygiene patterns only unless bus adopted).

**Useful but lower priority (13.x):**  
`claude-plugins` / catalog install surface, `AgentLoom` (YAML agents + checkpoints), `forge` (worktree isolation + MCP hooks), `swarmclaw` (self-hosted runtime product), `rojak` (Temporal-style durable orchestration), `openai/swarm` (Agent+handoff API as educational pattern only).

---

## 4. Prioritized engineering backlog

Paths below use EVIDENCE workspace layout and conventional NEXUS concerns (multi-agent durability, MCP, mine/alive, grading, demos). Touch the real modules that own those concerns in-repo; do not vendor whole mined trees.

### P0 — Prove the self-improve loop (durability + grade + MCP)

| Item | Intent | Files / modules to touch |
|------|--------|---------------------------|
| **P0.1 Ordered durable steps** | Checkpoint at agent decision boundaries; restore action order (paper **2510.13343**, MisterSmith/rojak durability patterns) | Multi-agent runtime / workflow engine; checkpoint store; resume API; tests for crash-mid-handoff |
| **P0.2 Grade artifact contract** | Persist Grok grades (`idea`, `skill`, composite, method) + evidence pointers (Thucy-style verify; lumen audit) | Mine eval pipeline under `.nexus_workspaces/mine_eval/`; grade schema; writer/reader; unit tests for schema stability |
| **P0.3 MCP tool surface for mine/grade/apply** | Minimal MCP server(s): list candidates, get grade, enqueue apply, query run status (`AssetOpsBench`, `mission-control`, `EDDI`, `AgenticGoKit`) | MCP server package; tool registry; contract tests (request/response golden files) |
| **P0.4 Anti-premature-completion guard** | Alive/mine loops must not mark success without tests + grade threshold (`zenith`) | Alive loop controller; stop predicates; demo assertion helpers |
| **P0.5 Decision audit trail** | Every apply decision: who/what/why + citations (`lumen`, paper **2302.10809**) | Audit log module; attach to PR/demo report |

### P1 — Control plane, board, catalog, quality gates

| Item | Intent | Files / modules to touch |
|------|--------|---------------------------|
| **P1.1 Task/spend/ops control plane** | SQLite (or existing store) tasks + adapters + spend for agent fleets (`mission-control`) | Control-plane service; CLI; MCP adapters; API contract tests |
| **P1.2 Goals/tasks/traces/evidence board** | Surface self-improve runs for demos (`routa`) | Demo/ops UI or CLI board; trace viewer hooks |
| **P1.3 Plugin/skill catalog + drift** | Markdown→validated skills; generate/validate/test (`wshobson/agents`, claude-plugins catalog idea) | Skills/plugins tree; generator; drift CI job |
| **P1.4 Approvals + cron for mine/alive** | Human/policy gate before hard-apply; scheduled loops (`Hermes-Studio`) | Approval gate; scheduler entrypoints; config |
| **P1.5 Multi-stage mine pipeline** | Screen → deep grade → cache/surrogate (`2604.03350`); dependency-ordered handoffs (`Mybono/ai-orchestrator`) | Mine orchestrator stages; artifact dirs under `.nexus_workspaces/` |
| **P1.6 Observability** | Streaming + OpenTelemetry-style traces (`AgenticGoKit`); emergent metrics (`MAEBE`) | Tracing middleware; metrics for thrash/early-stop/tool storms |

### P2 — Hardening, adversarial grade, packaging

| Item | Intent | Files / modules to touch |
|------|--------|---------------------------|
| **P2.1 Adversarial/skeptic reviewer** | Hierarchical oppose-before-merge (`2303.16641`, gossipcat consensus/trust) | Review agent role; trust weights; integration tests |
| **P2.2 Preference-vector ranking** | Use idea/skill preference learning (`2602.04518`) for mine ranking | Ranker module; config for weight vectors |
| **P2.3 Worktree-isolated apply** | Git worktree isolation for apply experiments (`automagik-dev/forge`) | Apply runner; worktree lifecycle tests |
| **P2.4 Event-driven hygiene** | Broad test matrix / dep hygiene without adopting Solace bus (`solace-agent-mesh`) | CI matrix; dependency policy docs/tests |
| **P2.5 Deterministic incident playbooks** | Fixed orchestration for stuck runs (`2511.15755`) | Playbook configs; runbooks in demos |
| **P2.6 Enterprise packaging bar** | Docker/standalone + coverage culture (`EDDI`, `mission-control`) | Dockerfile(s), e2e smoke, coverage thresholds |
| **P2.7 Inspect→recompose ports** | Pattern extraction workflow (`2603.20143`) | Port cookbook + template PR for mined patterns |

---

## 5. First apply slice (smallest PR that proves the loop)

### Goal
One PR that demonstrates: **mine candidate → Grok grade artifact → durable multi-agent step with checkpoint/resume → MCP-readable status → no premature success**.

### Scope (do / don’t)

**Do**
1. **Grade artifact I/O** — canonical JSON (or existing store format) for `{repo, score, idea, skill, method, path}` matching mined evidence fields; round-trip test.
2. **Checkpoint boundary** — single orchestrated two-agent (or two-step) workflow: `grade_read` → `apply_plan`; checkpoint after step 1; kill/resume restores “next actor = apply_plan”.
3. **MCP tools (3–4 max)** — e.g. `list_graded_candidates`, `get_grade`, `get_run_checkpoint`, `get_run_status`.
4. **Stop rule** — success only if: checkpoint resume test green **and** grade.score ≥ threshold **and** audit row written (`zenith` + `lumen` patterns).
5. **Demo script** — CLI or script that runs the slice and prints board-style lines: goal, tasks, evidence path, review=pass (`routa`-lite).

**Don’t**
- Vendor `mission-control` / `MisterSmith` / `routa` monorepos.
- Build full TUI/desktop (`Clutch`, Hermes UI).
- Implement preference IRL, game-theoretic adversarial stack, or Temporal bus.

### Suggested PR title
`feat(self-improve): durable grade→checkpoint slice with MCP status + audit`

### Likely touch set
- Multi-agent / workflow runtime (checkpoint + ordered next-step).
- Mine eval grade schema + loader (compatible with `.nexus_workspaces/mine_eval/*` digests).
- MCP server tool registration + contract tests.
- Alive/stop predicates (anti-premature-completion).
- Decision audit writer.
- Demo CLI/script + one short markdown demo note.

### Tests to run
1. **Unit:** grade artifact parse/validate (all required fields; reject partial).
2. **Unit:** checkpoint serialize/deserialize preserves `next_agent` / step order (**2510.13343**).
3. **Integration:** simulate crash after grade step → resume → apply_plan runs once (no double-apply).
4. **MCP contract:** tool schemas + golden request/response (mission-control-style contract check).
5. **Alive/demo assertion:** run finishes `status=success` only when tests + audit + threshold satisfied; forced early `complete` must fail the guard (`zenith`).
6. **Regression:** existing mine_eval path still loads score-15 fixtures (`wshobson__agents`, `builderz-labs__mission-control`, `ahmedEid1__lumen`, etc.) without schema break.

### Acceptance criteria (loop proof)
- [x] From a graded mine_eval digest on disk, system loads score/idea/skill without network. (`grade_artifact.list_graded_candidates` / `get_grade`)
- [x] Workflow can be killed and resumed with correct next action. (`OrderedLoopRun` next_agent=apply_plan after grade_read)
- [x] MCP client can query grade + run status. (`list_graded_candidates`, `get_grade`, `get_run_checkpoint`, `get_run_status`)
- [x] Audit log explains accept/reject with evidence path. (decision_audit.json + cause_chain)
- [x] Demo script produces a one-screen proof for humans. (`nexus demo grade-loop` / `format_board`)
- [x] CI subset above is green. (`tests/test_grade_artifact.py` + full pytest)

### Landed this cycle (First apply slice)
- `src/nexus/grade_artifact.py` — `nexus.grade/v1` contract, offline list/get, ordered `grade_read`→`apply_plan` checkpoint, zenith success_guard
- `src/nexus/mcp_server.py` — four MCP tools for grade + run status
- `src/nexus/improve_apply.py` — grade fixture path field + status `next_agent` mapping
- `src/nexus/cli.py` — `nexus demo grade-loop`
- `tests/test_grade_artifact.py`

### Immediate follow-on (still small, post-slice)
- Wire **P0** stop guard into production alive loop.
- Port **mission-control** contract-test style to all MCP tools.
- Add **lumen**-style public eval markdown emitted after each mine batch.

---

### Mapping: evidence → loop roles

| Loop stage | Primary paper ideas | Primary repo patterns |
|------------|--------------------|------------------------|
| **Mine** | 2604.03350 multi-stage screen | AssetOpsBench eval CLIs; wshobson generate/validate |
| **Grade (Grok 4.5)** | 2602.04518 preferences; 2512.03278 verify claims | lumen honest evals; gossipcat trust (later) |
| **Reason / plan apply** | 2302.10809 causal explain; 2603.20143 inspect→recompose | Mybono handoffs; routa evidence board |
| **Hard apply** | 2510.13343 ordered decisions + checkpoint | MisterSmith durability; forge worktrees (P2); mission-control tasks |
| **Alive / demo** | zenith premature-stop; 2511.15755 deterministic IR playbooks | Hermes approvals/cron; Clutch/routa surfaces; AgenticGoKit traces |

---

*Constraint honored: every paper id and repo name above appears in the provided EVIDENCE; no invented ids. Where arXiv **2508.08322** title text was truncated in the offloaded middle, only the id, score (10), and research report path were used.*