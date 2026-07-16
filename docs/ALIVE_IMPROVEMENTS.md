# Alive improvement log

Auto-appended by `nexus alive` when self-improve runs. Safe to commit; no secrets.

## Cycle 2026-07-15 17:09:32Z
- goal: `test`
- mine: fetch=1 eval=1 used=1 plan=`None`

## Cycle 2026-07-15 17:13:44Z
- goal: `self-improve nexus-core: durability, demos, mine→apply→github publish`
- mine: fetch=3 eval=3 used=3 plan=`/path/to/nexus-core/.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=4 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-ad22656322.md`
- self_check: ok=True
- apply: {'status': 'completed', 'job_id': 'gh-VincentMarquez-nexus-core-8c645c3e', 'repo': 'VincentMarquez/nexus-core'}

## Cycle 2026-07-15 17:13:53Z
- goal: `self-improve nexus-core: durability, demos, mine→apply→github publish`
- mine: fetch=3 eval=3 used=3 plan=`/path/to/nexus-core/.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=4 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-ad22656322.md`
- self_check: ok=True
- apply: {'status': 'completed', 'job_id': 'gh-VincentMarquez-nexus-core-8c645c3e', 'repo': 'VincentMarquez/nexus-core'}
- publish: pushed=True sha=61a6a62d71a3 staged=['src/nexus/alive.py', 'docs/LATEST_ARXIV_IMPROVE.md', 'docs/LATEST_IMPROVE_PLAN.md']

## Cycle 2026-07-15 hard-apply (Grok 4.5, 10 repos + 10 arXiv)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch≈10 eval=10 used=10 plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=10 notes=`.nexus_state/arxiv_improve/improve-rx-ec0777735b.md`
- apply slice:
  - `src/nexus/persist.py` — atomic write-then-rename + JSONL event helpers
  - `src/nexus/engine.py` — atomic task checkpoints + append-only `*.events.jsonl` journal
  - `src/nexus/trust.py` — atomic trust flush
  - `src/nexus/memory_sqlite.py` — optional decay ranking + `ts` column (migration-safe)
  - tests: `tests/test_persist.py`, extended `tests/test_memory_sqlite.py`
- patterns: DurableMultiAgentTemplate / Rojak / DriftQ (atomic durability), edict / MisterSmith (audit), openclaw-hawkins (decay memory)
- docs: `docs/SELF_IMPROVE_CYCLE.md`, `docs/LATEST_IMPROVE_PLAN.md`

## Cycle 2026-07-15 17:35:09Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=10 used=10 plan=`None`
- arxiv: papers=10 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-ec0777735b.md`

## Cycle 2026-07-15 hard-apply P1 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: 10 used (wshobson/agents 16, MisterSmith 15, rojak/openclaw-hawkins 14, swarm/edict/…) plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=10 notes=`.nexus_state/arxiv_improve/improve-rx-62b77a6ce8.md` (and prior `rx-ec0777735b`)
- apply slice (P1 operator + multi-agent communication):
  - `src/nexus/engine.py` — swarm-style `handoff` events; edict review veto (`verdict` reject/veto/…); `journal_context()` injected on resume; `events(limit=)` is tail
  - `src/nexus/cli.py` — `nexus task list|show|events` operator surface
  - tests: `tests/test_engine.py` (handoff/veto/context), `tests/test_task_cli.py`, `tests/test_persist.py` tail limit
- patterns: openai/swarm (handoff), edict (veto), context engineering arXiv 2508.08322 (journal in prompt), MisterSmith/DriftQ (CLI inspect)
- docs: `docs/SELF_IMPROVE_CYCLE.md`, `docs/LATEST_IMPROVE_PLAN.md`

## Cycle 2026-07-15 17:48:45Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=10 used=10 plan=`None`
- arxiv: papers=10 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-62b77a6ce8.md`

## Cycle 2026-07-15 hard-apply P1 complete (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: 10 used (wshobson/agents 16 … swarm/edict 13) plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=10 notes=`.nexus_state/arxiv_improve/improve-rx-03b7641275.md` (+ prior rx-62b77a6ce8 / rx-ec0777735b)
- apply slice (P1 finish + operator board polish):
  - `src/nexus/cli.py` — `task` in known-commands allowlist (was remapped to `start`); list columns for last event/agent
  - `src/nexus/engine.py` — handoff + veto + journal_context (already staged); `list_tasks` returns `last_event`/`last_agent`
  - tests: `tests/test_task_cli.py`, `tests/test_engine.py`, `tests/test_persist.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; cookbook crash-resume inspect
- patterns: openai/swarm (handoff), edict (veto/audit), MisterSmith/threadwork (task board), arXiv 2508.08322 (journal context)
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 95 passed

## Cycle 2026-07-15 17:56:31Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=10 used=10 plan=`None`
- arxiv: papers=10 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-03b7641275.md`

## Cycle 2026-07-15 hard-apply P2 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: 10 used (mission-control / solace-agent-mesh / maestro-flow / EDDI / open-multi-agent / nocturne / …) plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=10 notes=`.nexus_state/arxiv_improve/improve-rx-703f35888a.md` (+ prior rx-03b7641275 / rx-62b77a6ce8 / rx-ec0777735b)
- apply slice (P2 operator observability — First apply this session):
  - `src/nexus/engine.py` — `replay()` timeline; `explain()` causal chain; `why` on `step_complete`; journal context includes why
  - `src/nexus/cli.py` — `nexus task replay|explain` (+ `--json`)
  - tests: `tests/test_engine.py` (why/replay/explain), `tests/test_task_cli.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; cookbook crash-resume inspect
- patterns: open-multi-agent (plan-replay), arXiv CEMA 2302.10809 (causal explain), mission-control/MisterSmith (operator inspect), 2511.15755 (deterministic audit)
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 98 passed

## Cycle 2026-07-15 18:04:21Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=10 used=10 plan=`None`
- arxiv: papers=10 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-703f35888a.md`

## Cycle 2026-07-15 hard-apply P3 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: 10 used (mission-control / MisterSmith / wshobson/agents / EDDI / maestro-flow / rojak / …) plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=10 notes=`.nexus_state/arxiv_improve/improve-rx-5b885ba84d.md` (+ prior rx-703f35888a / rx-03b7641275 / …)
- apply slice (P3 task cost + value thresholds — First apply this session):
  - `src/nexus/engine.py` — `cost()` rollup; `score`/`tokens`/`thresholds` on `step_complete`; cost brief in `explain()`
  - `src/nexus/usage.py` — `by_task()` / `summarize_records()` ledger rollup
  - `src/nexus/judge.py` — `PASS_THRESHOLD` / `REVISE_THRESHOLD` / `decision_thresholds()` on Verdict
  - `src/nexus/cli.py` — `nexus task cost` (+ `--json`); explain/replay show score/tokens
  - tests: `tests/test_engine.py`, `tests/test_task_cli.py`, `tests/test_usage_alive.py`, `tests/test_judge.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; cookbook cost inspect
- patterns: mission-control task-costs, arXiv value systems (2602.04518), CEMA score trail
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 101 passed

## Cycle 2026-07-15 18:12:24Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=10 used=10 plan=`None`
- arxiv: papers=10 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-5b885ba84d.md`

## Cycle 2026-07-15 hard-apply P4 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: 10 used (mission-control / MisterSmith / routa / EDDI / AgenticGoKit / maestro-flow / …) plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=10 notes=`.nexus_state/arxiv_improve/improve-rx-beb4144b26.md` (+ prior rx-5b885ba84d / rx-703f35888a / …)
- apply slice (P4 provenance + integrity — First apply this session):
  - `src/nexus/engine.py` — `provenance()` PROV-style export; `verify()` checkpoint↔journal integrity; list board `tokens`
  - `src/nexus/cli.py` — `nexus task prov|verify` (+ `--json`); list TOK column
  - tests: `tests/test_engine.py` (prov/verify), `tests/test_task_cli.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; cookbook crash-resume inspect
- patterns: PROV-AGENT (2508.02866), fault-tolerant checkpointing (2310.12670), mission-control timeline, routa traces, MisterSmith/EDDI audit
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 104 passed

## Cycle 2026-07-15 18:21:25Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=10 used=10 plan=`None`
- arxiv: papers=10 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-beb4144b26.md`

## Cycle 2026-07-15 hard-apply P5 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: 10 used (cycgraph / mission-control / open-multi-agent / MisterSmith / routa / rojak / …) plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=10 notes=`.nexus_state/arxiv_improve/improve-rx-7afb87b115.md` (+ prior rx-beb4144b26 / rx-5b885ba84d / …)
- apply slice (P5 task budget hard-stop + call-graph — First apply this session):
  - `src/nexus/engine.py` — `task_max_tokens()`; pre/post `max_tokens` gate; journal `budget` event; `graph()` nodes/edges/sequence/mermaid; cost budget fields
  - `src/nexus/cli.py` — `nexus task graph` (+ `--json` / `--mermaid`); cost shows budget line
  - tests: `tests/test_engine.py` (budget + graph), `tests/test_task_cli.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; cookbook budget/graph inspect
- patterns: cycgraph/open-multi-agent maxTokenBudget, mission-control spend, MisterSmith hard-cap, MAS call-graph/space-time papers, routa traces
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 266 passed

## Cycle 2026-07-15 18:28:53Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=10 used=10 plan=`None`
- arxiv: papers=10 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-7afb87b115.md`

## Cycle 2026-07-15 hard-apply P6 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: 10 used (wshobson/agents / routa / mission-control / AssetOpsBench / EDDI / MisterSmith / …) plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=10 notes=`.nexus_state/arxiv_improve/improve-rx-b98ae48d28.md` (+ prior rx-7afb87b115 / …)
- apply slice (P6 evidence pack + norms — First apply this session):
  - `src/nexus/engine.py` — `task_norms()`; `evidence()` pack `nexus.evidence/v1` (timeline/cost/prov/verify/graph + readiness gates)
  - `src/nexus/cli.py` — `nexus task evidence` (+ `--json` / `--compact` / `--out`)
  - tests: `tests/test_engine.py` (norms + evidence), `tests/test_task_cli.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; cookbook evidence inspect
- patterns: routa evidence board, mission-control export, AssetOpsBench eval, NorMAS / constitutional governance (2603.13189, 1709.02018)
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 266 passed

## Cycle 2026-07-15 18:35:55Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=10 used=10 plan=`None`
- arxiv: papers=10 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-b98ae48d28.md`

## Cycle 2026-07-15 18:42:14Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=10 used=10 plan=`None`
- arxiv: papers=10 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-bef427f9a3.md`

## Cycle 2026-07-15 18:49:46Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=10 used=10 plan=`None`
- arxiv: papers=10 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-2b3131c793.md`

## Cycle 2026-07-15 hard-apply P10 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: cycgraph (primary) + IMPROVE_OURS top repos plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers=10 notes under `.nexus_state/arxiv_improve/` (adversarial hierarchy 2303.16641, anti-collusion 2601.00360)
- apply slice (P10 durability budgets + taint — **First apply slice** from LATEST_IMPROVE_PLAN):
  - `src/nexus/durability/budgets.py` — `RunBudget` (max_steps/tokens/cost), `BudgetExhausted`, env/meta helpers
  - `src/nexus/durability/taint.py` — `TaintLevel` (trusted|user|mined|external_mcp|derived), `TaintSet` stamp/require/promote/propagate
  - `src/nexus/durability/durable_agent.py` — pre-step budget gate + post-write taint stamp
  - `src/nexus/engine.py` — `task_max_steps()`, `task_run_budget()`; `meta.max_steps` hard-stop (fail-closed)
  - tests: `tests/durability/test_budgets.py`, `test_taint.py`, `test_durable_agent.py`, `test_engine.py::test_task_max_steps_hard_stop`
  - docs: `docs/LATEST_IMPROVE_PLAN.md`, this log
- patterns: wmcmahan/cycgraph budgets + taint (pattern only, no tree vendor)
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 266 passed

## Cycle 2026-07-15 19:07:33Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-48104de82f.md`

## Cycle 2026-07-15 hard-apply P11 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: cycgraph (primary) + IMPROVE_OURS top repos (routa, mission-control, MisterSmith, EDDI, …) plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (communication attacks 2502.14847, adversarial hierarchy 2303.16641, coordination survey 2203.08975)
- apply slice (P11 zero-trust state slice — **First apply slice** this session):
  - `src/nexus/durability/state_slice.py` — `StateSlice` (`read_keys`/`write_keys`, fail-closed empty default, `*` system wildcard, protected `_` keys)
  - `src/nexus/durability/durable_agent.py` — enforce slice on read/write/`run_step`; `view()`; opt-in `from_meta`
  - `src/nexus/durability/__init__.py` — export `StateSlice` / `SliceError` / `slice_from_step`
  - tests: `tests/durability/test_state_slice.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`
- patterns: wmcmahan/cycgraph permission-scoped state (pattern only, no tree vendor)
- next open: P0.3 eval-gated memory · P0.4 zenith principled stop · P0.5 independent verify before promote
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 266 passed

## Cycle 2026-07-15 19:15:48Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-bda446f48d.md`

## Cycle 2026-07-15 hard-apply P0.3 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: cycgraph (primary) + IMPROVE_OURS top repos (mission-control, routa, soul, lumen, …) plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-d6df1c0e2b.md`; durable workflows / progressive crystallization)
- apply slice (P0.3 eval-gated memory write — **First apply slice** this session):
  - `src/nexus/durability/eval_memory.py` — `EvalGate` (min_score=PASS_THRESHOLD), `GatedMemoryWriter`, trial vs retained namespaces, `promote` / `record_outcome`, `MemoryWriteDenied`
  - `src/nexus/durability/__init__.py` — export eval-memory surface
  - tests: `tests/durability/test_eval_memory.py` (spine + sqlite + meta + history)
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`
- patterns: wmcmahan/cycgraph eval-gated retention / verified lessons (pattern only, no tree vendor)
- next open: P0.4 zenith principled stop · P0.5 independent verify before promote
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 266 passed


## Cycle 2026-07-15 19:23:53Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-d6df1c0e2b.md`

## Cycle 2026-07-15 hard-apply P0.4 + P0.5 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: zenith (primary) + cycgraph + IMPROVE_OURS top repos (mission-control, routa, MisterSmith, …) plan=`.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-feabc6cebc.md`; principles 2502.07165, adversarial hierarchy 2303.16641)
- apply slice (P0.4 principled stop + P0.5 independent verify — **First apply slice** this session):
  - `src/nexus/durability/stop.py` — `PrincipledStop`, `StopPolicy`, `GapItem`, gap board, no-progress thrash, max_cycles/budget/abort, `cycle_progressed`
  - `src/nexus/durability/verify_promote.py` — `IndependentVerify`, `VerifyError`, `promote_taint_verified`, `promote_memory_verified`
  - `src/nexus/alive.py` — stop knobs in `AliveConfig`; record/persist each cycle; `watch` exits on principled stop
  - `src/nexus/durability/__init__.py` — exports
  - tests: `tests/durability/test_stop.py`, `test_verify_promote.py`, `tests/test_usage_alive.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`
- patterns: Intelligent-Internet/zenith (gap review + stop discipline + independent validation); cycgraph promote gate (pattern only, no tree vendor)
- next open: auto-register IMPROVE_OURS backlog ids into gap board; optional engine review→promote hook
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 266 passed

## Cycle 2026-07-15 19:33:23Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-feabc6cebc.md`

## Cycle 2026-07-15 hard-apply P0 first-apply-slice (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: lumen (primary) + tiger_cowork path safety + Network-AI/mission-control MCP/CLI parity; plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: AOAD-MAT action order **2510.13343**, Thucy evidence links **2512.03278**, CEMA causal lite **2302.10809**, context pack **2508.08322**
- apply slice (P0.1–P0.5 **First apply slice** from LATEST_IMPROVE_PLAN):
  - `src/nexus/improve_apply.py` — idempotent phase FSM (`briefed→context_packed→applying→audited→done`), migration-phase guards, decision audit (`repo/score/idea/skill/method/pattern/files_touched/action_order/evidence_refs`), workspace path jail, durable state under `.nexus_workspaces/improve_apply/`
  - `src/nexus/cli.py` — `nexus demo self-improve-slice [--fixture] [--show-audit] [--run-id]`
  - `src/nexus/mcp_server.py` — tool `apply_phase` (advance=all|one|status)
  - tests: `tests/test_improve_apply.py` (FSM, audit orphans, path safety, integration, MCP, CLI)
  - docs: `docs/LATEST_IMPROVE_PLAN.md` success criteria checked; this log
- patterns: ahmedEid1/lumen (phase guards + decision audit), Sompote/tiger_cowork (path safety), Network-AI/mission-control (MCP+CLI)
- non-goals kept: no vault, no multi-grader, no vendored trees
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 212 passed

## Cycle 2026-07-15 19:43:57Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-7bb7c48716.md`

## Cycle 2026-07-15 hard-apply P1.1 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: mission-control (primary) + IMPROVE_OURS top repos (lumen, Network-AI, routa, AssetOpsBench, …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-999cc7be06.md`; communication survey 2203.08975, context pack 2508.08322)
- note: P0 first-apply slice (improve_apply FSM) already landed; this session implements **P1.1 task/spend control plane**
- apply slice (P1.1 ops plane — **First apply this session**):
  - `src/nexus/ops_store.py` — SQLite jobs + spend (`nexus.ops/v1`), calculate_stats, ledger ingest, alive/improve note helpers
  - `src/nexus/usage.py` — dual-write spend to ops on `meta.task_id` (`_ops_skip` anti-loop)
  - `src/nexus/improve_apply.py` / `alive.py` — register runs/cycles on ops board
  - `src/nexus/cli.py` — `nexus ops list|show|spend|record|status|ingest|set-status`
  - `src/nexus/mcp_server.py` — tool `ops_control`
  - tests: `tests/test_ops_store.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: builderz-labs/mission-control task-costs + status (pattern only, no tree vendor)
- next open: P1.2 task DAG · P1.3 consensus grading · P1.4 context pack stage
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 266 passed

## Cycle 2026-07-15 19:54:34Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-999cc7be06.md`

## Cycle 2026-07-15 hard-apply P1.2 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: open-multi-agent (primary) + IMPROVE_OURS top repos (mission-control, routa, EDDI, …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-9df4f8edff.md`; AOAD-MAT 2510.13343, communication 2203.08975)
- apply slice (P1.2 multi-agent task DAG — **First apply slice** this session):
  - `src/nexus/steps.py` — DAG helpers: `completed_set`, `validate`, `next_ready`, `blocked`, `prior_keys`, `mermaid`, `dag_snapshot` (`nexus.dag/v1`)
  - `src/nexus/engine.py` — schedule via `policy.ready(completed)`; `meta.action_order[]`; deps-scoped prior; fail-closed invalid/deadlock; `dag(task_id)`
  - `src/nexus/cli.py` — `nexus task dag` (+ `--json` / `--mermaid`)
  - tests: `tests/test_steps_dag.py`, `tests/test_engine.py` (diamond + invalid), `tests/test_task_cli.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; cookbook crash-resume dag inspect
- patterns: open-multi-agent task DAG; AOAD-MAT explicit action order; mission-control/routa operator export (pattern only, no tree vendor)
- next open: P1.3 consensus grading · P1.4 context pack stage
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 230 passed

## Cycle 2026-07-15 20:05:30Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-9df4f8edff.md`

## Cycle 2026-07-15 hard-apply P1.3 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: gossipcat-ai (primary) + IMPROVE_OURS top repos (mission-control, routa, wshobson/agents, …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-6b7f9afae8.md`; communication 2203.08975, principles 2502.07165, context 2508.08322)
- apply slice (P1.3 consensus grading — **First apply slice** this session):
  - `src/nexus/consensus.py` — multi-grader findings, role lenses, trust weights, weighted aggregate, agreement signals (`nexus.consensus/v1`)
  - `src/nexus/config.py` — `consensus_judge` / min/max graders knobs (default on)
  - `src/nexus/engine.py` — ConsensusJudge path; journal `consensus` events; `consensus(task_id)` export
  - `src/nexus/cli.py` — `nexus task consensus` (+ `--json` / `--findings`)
  - tests: `tests/test_consensus.py`, `tests/test_task_cli.py::test_task_consensus_cli`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`
- patterns: gossipcat independent findings + adaptive trust; swarm multi-agent; arXiv communication/principles (pattern only, no tree vendor)
- next open: P1.4 context pack stage
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 238 passed

## Cycle 2026-07-15 20:15:38Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-6b7f9afae8.md`

## Cycle 2026-07-15 hard-apply P1.4 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (routa / mission-control / zenith / wshobson / EDDI / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-a2984ea421.md`; context engineering **2508.08322**, communication **2203.08975**, Thucy **2512.03278**)
- apply slice (P1.4 formal context pack stage — **First apply slice** this session):
  - `src/nexus/context_pack.py` — bounded multi-source pack (`nexus.context_pack/v1`): goal/grade/research/repo_digest/journal/memory/prior; per-section + total char budgets; IMPROVE_OURS + USE_LATEST parsers; arxiv_improve loader; `prompt_block()`
  - `src/nexus/improve_apply.py` — `ensure_context_packed` uses formal builder; writes `context_pack.json` + `context_pack.prompt.md`
  - `src/nexus/engine.py` — `context_pack(task_id)`; mid-run prompt inject when journal / `meta.context_pack`
  - `src/nexus/cli.py` — `nexus task context` (+ `--json` / `--prompt` / `--research` / `--repos` / `--out`)
  - `src/nexus/mcp_server.py` — tool `context_pack`
  - tests: `tests/test_context_pack.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; cookbook crash-resume context inspect
- patterns: arXiv 2508.08322 context engineering; routa/mission-control export; zenith bound context; wshobson digests (pattern only, no tree vendor)
- next open: P1.5 vault / supervised alive · AssetOpsBench domain MCP · packaging/OpenAPI
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 250 passed

## Cycle 2026-07-15 20:24:24Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-a2984ea421.md`

## Cycle 2026-07-15 hard-apply P1.5 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (zenith / mission-control / lumen / routa / MisterSmith / EDDI / wshobson / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-5536a7eec8.md`; communication **2203.08975**, principles **2502.07165**, context **2508.08322**)
- apply slice (P1.5 vault + supervised gap-board auto-seed — **First apply slice** this session):
  - `src/nexus/durability/gap_seed.py` — plan parsers + `seed_gap_board` / `collect_plan_gaps` / `board_snapshot` (`nexus.gap_seed/v1`)
  - `src/nexus/alive.py` — `seed_gaps` config; auto-seed in `_record_principled_stop`; `seed_gaps` / `gap_board` / `close_gap` helpers
  - `src/nexus/vault.py` — env + `.nexus_state/vault.local.json`; presence-only status; `redact` / `mask_mapping`
  - `src/nexus/cli.py` — `nexus alive gaps [--seed|--close]`; `nexus vault status|check|redact`
  - `src/nexus/mcp_server.py` — tools `gap_board`, `vault_status`
  - tests: `tests/durability/test_gap_seed.py`, `tests/test_vault.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: zenith gap board; mission-control/lumen env secrets (pattern only, no tree vendor)
- next open: P2 packaging/OpenAPI · AssetOpsBench domain MCP · wshobson skillpack generators
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 266 passed

## Cycle 2026-07-15 20:35:53Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-5536a7eec8.md`

## Cycle 2026-07-15 hard-apply First apply slice (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (mission-control / lumen / AssetOpsBench / MisterSmith / wshobson / zenith / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: AOAD-MAT ordered decisions **2510.13343**, Thucy evidence **2512.03278**, CEMA causal lite **2302.10809**, context **2508.08322**
- apply slice (**First apply slice** from LATEST_IMPROVE_PLAN §5):
  - `src/nexus/grade_artifact.py` — `nexus.grade/v1` `{repo,score,idea,skill,method,path}`; offline list/get from IMPROVE_OURS; ordered `grade_read`→`apply_plan` with `next_agent` checkpoint; zenith `success_guard` (score+audit+resume_ok); routa-lite `format_board`
  - `src/nexus/mcp_server.py` — tools `list_graded_candidates`, `get_grade`, `get_run_checkpoint`, `get_run_status`
  - `src/nexus/improve_apply.py` — grade path field + status `next_agent` mapping
  - `src/nexus/cli.py` — `nexus demo grade-loop [--repo] [--run-id]`
  - tests: `tests/test_grade_artifact.py` (schema, resume, MCP contract, premature-stop)
  - docs: `docs/LATEST_IMPROVE_PLAN.md` acceptance criteria checked; this log
- patterns: lumen honest grades + audit; zenith anti-premature complete; mission-control MCP contract; routa board; AOAD-MAT next actor restore (pattern only, no tree vendor)
- non-goals kept: no vendored monorepos, no full TUI, no preference IRL
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 276 passed

## Cycle 2026-07-15 20:48:25Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-f732b12d4d.md`

## Cycle 2026-07-15 hard-apply P2.1 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: wshobson/agents (primary) + IMPROVE_OURS top repos (mission-control / AssetOpsBench / lumen / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-406cb98836.md`; over-privileged tools **2606.20023**, context **2508.08322**, communication **2203.08975**)
- apply slice (P2.1 skillpack multi-harness generate/validate/drift — **First apply slice** this session):
  - `src/nexus/skillpacks.py` — list/validate/generate/drift; harness adapters grok/cursor/claude/codex/local; privilege ladder + max_privilege filter; atomic emit to `.nexus_state/generated_skillpacks/`
  - `src/nexus/cli.py` — `nexus skillpacks list|validate|generate|drift`
  - `src/nexus/mcp_server.py` — tool `skillpacks`
  - `skillpacks/durable-operator/manifest.json` — `privilege: ops`
  - tests: `tests/test_skillpacks.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: wshobson/agents one-source multi-harness; 2389-research plugin layout; arXiv 2606.20023 least-privilege (pattern only, no tree vendor)
- next open: P2.2 OpenAPI tool catalog · P2.3 AssetOpsBench domain MCP eval smoke
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 289 passed

## Cycle 2026-07-15 20:59:55Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-406cb98836.md`

## Cycle 2026-07-15 hard-apply P2.2 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: mission-control (primary) + IMPROVE_OURS top repos (AssetOpsBench / Network-AI / wshobson / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-36f52aff73.md`; communication **2203.08975**, context **2508.08322**, deterministic audit **2511.15755**)
- apply slice (P2.2 OpenAPI-ish MCP tool catalog — **First apply slice** this session):
  - `src/nexus/tool_catalog.py` — `nexus.tool_catalog/v1` + OpenAPI 3.1 export; privilege ladder; validate; export under `.nexus_state/tool_catalog/`
  - `src/nexus/cli.py` — `nexus tools list|validate|catalog|openapi|export`
  - `src/nexus/mcp_server.py` — tool `tool_catalog`; HTTP `GET /openapi.json` + `/catalog.json`
  - tests: `tests/test_tool_catalog.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: builderz-labs/mission-control openapi export; arXiv 2606.20023 least-privilege; AssetOpsBench validate-as-smoke (pattern only, no tree vendor)
- next open: P2.3 domain MCP eval smoke · P3 review→promote hook
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 300 passed

## Cycle 2026-07-15 21:08:48Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-36f52aff73.md`

## Cycle 2026-07-15 hard-apply P2.3 + P3 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IBM/AssetOpsBench (primary) + IMPROVE_OURS top repos (mission-control / zenith / MisterSmith / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-b6536eed67.md`; communication **2203.08975**, deterministic audit **2511.15755**, context **2508.08322**)
- apply slice (P2.3 domain MCP eval smoke + P3 review→promote — **First apply slice** this session):
  - `src/nexus/mcp_eval.py` — AssetOpsBench-shaped scenarios → MCP trajectories → code scorers → `nexus.mcp_eval/v1` report/export
  - `src/nexus/cli.py` — `nexus eval list|smoke|run`
  - `src/nexus/mcp_server.py` — tool `mcp_eval`
  - `src/nexus/tool_catalog.py` — privilege tag for `mcp_eval`
  - `src/nexus/engine.py` — opt-in `_maybe_promote_after_review` (`meta.promote_on_review`, journal promote/promote_denied, optional taint keys, `promote_require` fail-closed)
  - tests: `tests/test_mcp_eval.py`, promote cases in `tests/test_engine.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: IBM/AssetOpsBench eval pipeline; mission-control CLI/MCP parity; zenith/cycgraph independent verify-before-promote (pattern only, no tree vendor)
- next open: JSON scenario packs · optional LLM-as-judge scorer · improve_apply promote gate wiring
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 313 passed

## Cycle 2026-07-15 21:20:12Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-b6536eed67.md`

## Cycle 2026-07-15 hard-apply P2.4 + P2.5 + P3.1 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IBM/AssetOpsBench (primary) + zenith / cycgraph promote + IMPROVE_OURS top repos plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: papers≈20 notes under `.nexus_state/arxiv_improve/` (latest `improve-rx-0a75f9514d.md`; communication **2203.08975**, deterministic audit **2511.15755**, checkpoint **2310.12670**)
- apply slice (P2.4 JSON packs + P2.5 llm_judge + P3.1 improve_apply promote — **First apply slice** this session):
  - `src/nexus/mcp_eval.py` — `nexus.scenario_pack/v1` load/write/merge/discover; pack aliases; `heuristic_judge` / `llm_judge` (pluggable, offline fallback); `static_json` alias
  - `src/nexus/cli.py` — `nexus eval packs`; `--pack` / `--no-builtin` / `--discover-packs`
  - `src/nexus/mcp_server.py` — `mcp_eval` pack args + action `packs`
  - `src/nexus/improve_apply.py` — `_promote_gate()` before done (`promote_on_done` / `promote_require`); timeline promote events
  - tests: `tests/test_mcp_eval.py`, `tests/test_improve_apply.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: IBM/AssetOpsBench scenario JSON packs + static/judge scorers; zenith/cycgraph independent verify-before-promote (pattern only, no tree vendor)
- next open: scenario pack fixtures under `.nexus_state/mcp_eval/packs/` in-repo sample · wire promote_on_done from alive cycle · optional real LLM judge adapter
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 323 passed


## Cycle 2026-07-15 21:30:48Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-0a75f9514d.md`

## Cycle 2026-07-15 hard-apply P2.6 + P2.5 + P3.2 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (AssetOpsBench / mission-control / zenith / lumen / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: tool-use multi-LLM **2401.07324**, context **2508.08322**, over-privileged tools **2606.20023**, communication **2203.08975** (notes `improve-rx-3c113dc2aa` + priors)
- apply slice (**First apply slice** — close prior open items):
  - `fixtures/mcp_eval/packs/` — in-repo sample packs (`operator_smoke.json`, `privilege_safety.json`)
  - `src/nexus/mcp_eval.py` — `bundled_packs_dir` / `ensure_sample_packs` / `make_ollama_judge` / `configure_llm_judge_from_env`
  - `src/nexus/alive.py` — `promote_on_done` + `promote_require` knobs; `_run_promote_on_done` wires IndependentVerify via improve_apply
  - `src/nexus/cli.py` — `nexus eval packs --install-samples`; smoke `--install-samples` / `--llm-judge`
  - tests: `tests/test_mcp_eval.py` (samples + ollama fallback + CLI install), `tests/test_usage_alive.py` (promote knobs + gate)
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: IBM/AssetOpsBench scenario packs + judge; zenith/cycgraph promote; mission-control CLI parity (pattern only, no tree vendor)
- next open: Grok judge adapter · CI job for `--tag sample` · enable promote_on_done in full-cycle demos when self_approve applies
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 331 passed

## Cycle 2026-07-15 21:42:28Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-3c113dc2aa.md`

## Cycle 2026-07-15 hard-apply P2.7 + P3.3 + CI (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (AssetOpsBench / mission-control / zenith / wshobson / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: multi-LLM tool agents **2401.07324**, deterministic audit **2511.15755**, communication **2203.08975**, context **2508.08322** (notes `improve-rx-ae18c1bce0` + priors)
- apply slice (**First apply slice** — close prior open items):
  - `src/nexus/mcp_eval.py` — `make_grok_judge` + shared judge prompt/parse; `configure_llm_judge_from_env` supports `grok|auto|ollama|1`
  - `src/nexus/alive.py` — `_should_promote_on_done` auto-wires promote when `self_approve` apply lands
  - `src/nexus/cli.py` — `--llm-judge` help covers grok/auto/ollama
  - `.github/workflows/ci.yml` + `Makefile` (`eval-samples`) — offline sample pack smoke
  - tests: `tests/test_mcp_eval.py` (grok fallback/parse/env), `tests/test_usage_alive.py` (auto promote)
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: AssetOpsBench judge; multi-LLM (2401.07324); zenith/cycgraph promote; mission-control CI parity (pattern only, no tree vendor)
- next open: live Grok judge gated integration test · demo `--llm-judge auto` · more sample pack scenarios
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 335 passed; sample packs 7/7 PASS

## Cycle 2026-07-15 21:51:00Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-ae18c1bce0.md`

## Cycle 2026-07-15 hard-apply First apply slice P0.1–P0.4+P0.6 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: wshobson/agents (16.0 primary fixture) + cas/lumen/soul patterns; plan=`docs/LATEST_IMPROVE_PLAN.md` §5 + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: AOAD-MAT action order **2510.13343**, Thucy claim-verify **2512.03278**, value/preference grades **2602.04518**
- apply slice (**First apply slice** from LATEST_IMPROVE_PLAN §5 — prove mine→grade→claim_verify loop):
  - `src/nexus/decision_ledger.py` — append-only SQLite `agent_decisions` (`nexus.decision_ledger/v1`), content_hash idempotent append, `tail`/`list_run`
  - `src/nexus/stages.py` — fixed order `DEFAULT_STAGES` + smoke `mine→grade→claim_verify`; out-of-order refused
  - `src/nexus/load_mine_eval.py` — offline loader for fixtures / IMPROVE_OURS digests
  - `src/nexus/claim_verify.py` — require score/idea/skill/path; soft `verify_or_report`
  - `src/nexus/improve_smoke.py` — end-to-end smoke + ledger writes
  - `src/nexus/cli.py` — `nexus improve smoke|ledger`
  - tests: `tests/test_ledger.py`, `test_stage_order.py`, `test_claim_verify.py`, `test_improve_smoke.py`
  - fixture: `tests/fixtures/mine_eval_sample.json` (wshobson/agents 16.0, codingagentsystem/cas 15.0)
  - docs: `docs/LATEST_IMPROVE_PLAN.md` (landed table + §5 checked); this log
- patterns: soul/lumen immutable ledger + content_hash idempotency; AOAD-MAT ordered stages; Thucy grounded claims (pattern only, no tree vendor)
- non-goals kept: no worktree apply (P0.5 next), no MCP server, no consensus multi-reviewer, no vendored trees
- next open: P0.5 worktree-isolated apply of one Markdown skill SoT validator from wshobson/agents
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 363 passed; `nexus improve smoke` → pass YES for wshobson/agents

## Cycle 2026-07-15 22:02:51Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-3b40f6266f.md`

## Cycle 2026-07-15 hard-apply P0.5 (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: wshobson/agents (16.0 primary pattern) + cas/forge worktree isolation; plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: AOAD-MAT ordered stages **2510.13343**, Thucy claim-verify **2512.03278**, fault-tolerant checkpoint **2310.12670**, deterministic audit **2511.15755** (notes `improve-rx-fb9207372a` + priors)
- apply slice (P0.5 worktree-isolated apply — **First apply slice** this session):
  - `src/nexus/worktree_apply.py` — sandbox/git isolation under `.nexus_workspaces/apply_worktrees/`; pattern catalog `markdown-skill-sot-validator` (wshobson shape); skillpack validate in-worktree; main fingerprint isolation proof; ledger plan_apply+apply
  - `src/nexus/stages.py` — `APPLY_STAGES` + `StageRunner.apply_slice()`
  - `src/nexus/cli.py` — `nexus improve apply` (+ `--mode` / `--pattern` / `--keep` / `--list-patterns`)
  - tests: `tests/test_worktree_apply.py`, `tests/test_stage_order.py` apply runner
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: cas/forge worktree isolation; wshobson Markdown SoT validate; soul/lumen ledger (pattern only, no tree vendor)
- non-goals kept: no promote-to-main yet; no nested git worktree required (sandbox default); no vendored trees
- next open: promote verified pack from worktree → main; more pattern catalog entries; wire apply into alive self_approve
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 376 passed; `nexus improve apply --mode sandbox` → pass YES for wshobson/agents

## Cycle 2026-07-15 22:12:59Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-fb9207372a.md`

## Cycle 2026-07-15 hard-apply First apply slice — durable MCP context + verify-before-done (Grok 4.5 CLI)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: codingagentsystem/cas (16.0 primary — SQLite MCP context) + zenith (verify-before-done) + lumen (migrations) + soul (handoff); plan=`docs/LATEST_IMPROVE_PLAN.md` First apply slice + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: AOAD-MAT order **2510.13343**, deterministic orchestration **2511.15755**, Thucy claims **2512.03278**, CEMA decision log **2302.10809**
- apply slice (**First apply slice** from LATEST_IMPROVE_PLAN — prove durable loop):
  - `src/nexus/context_store.py` — SQLite `nexus.context_store/v1` tables `runs/stages/context_kv/claims/grades/decisions`; LOOP_STAGES `research_ingest→mine_rank→plan_item→apply→verify→grade→done`; reject done without verified claim + grade; `context_get/set` + `handoff`; `run_demo_loop` restart-safe (`stop_after` resume)
  - `src/nexus/cli.py` — `nexus improve demo-loop` (+ `--run-id` / `--stop-after` / `--grade-total` / `--json`)
  - `src/nexus/mcp_server.py` — tools `context_get`, `context_set`, `handoff`, `demo_loop`
  - `src/nexus/tool_catalog.py` — privilege map for new tools
  - tests: `tests/test_context_store.py` (CRUD, illegal stage jump, done gate, path verify, restart, MCP, CLI)
  - docs: `docs/LATEST_IMPROVE_PLAN.md` success criteria checked; this log
- patterns: cas SQLite MCP context; zenith anti-premature done; lumen schema migration; soul handoff; mission-control/routa CLI surface (pattern only, no tree vendor)
- non-goals kept: no worktree pool, no multi-reviewer consensus, no event bus, no vendored trees
- next open: P0.1 deeper worktree promote-to-main · Grok re-grade of real mined apply · wire demo-loop into alive cycle
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 387 passed; `nexus improve demo-loop` → status=done + grade stub

## Cycle 2026-07-15 22:25:42Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-aa3fa1d262.md`

## Cycle 2026-07-15 hard-apply P0.1 promote-to-main (Grok 4.5 CLI worker)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: cas / forge / zenith / wshobson / lumen / tiger_cowork + IMPROVE_OURS top repos; plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: AOAD-MAT order **2510.13343**, Thucy claims **2512.03278**, deterministic audit **2511.15755**, checkpoint **2310.12670**, CEMA **2302.10809** (notes `improve-rx-f79aa74b58` + priors)
- apply slice (**First apply slice** this session — close prior open: promote worktree → main):
  - `src/nexus/worktree_apply.py` — `promote_to_main` (allowlist + path jail + idempotent same + force overwrite + main re-verify); `run_promote`; `run_apply(promote=True)`; CLI `--promote` / `--promote-only`
  - `src/nexus/stages.py` — `PROMOTE_STAGES` + `StageRunner.promote_slice()`
  - `src/nexus/cli.py` — `nexus improve apply --promote`; `nexus improve promote --job-id`
  - tests: `tests/test_worktree_apply.py` (e2e promote, idempotent, refuse conflict, force, path jail, CLI), `tests/test_stage_order.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: cas/forge worktree boundary; zenith/cycgraph verify-before-promote; wshobson SoT pack; tiger_cowork path safety (pattern only, no tree vendor)
- non-goals kept: no vendored trees; no auto-promote without flag; no force-push
- next open: wire improve apply/promote into alive self_approve · more pattern catalog · Grok re-grade after promote
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 395 passed

## Cycle 2026-07-15 22:35:43Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-f79aa74b58.md`

## Cycle 2026-07-15 hard-apply First apply slice — grade claims + MCP FTS evidence (Grok 4.5 CLI)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: wshobson/agents (16) + cas (MCP SQLite/FTS) + soul ledger simplicity + mission-control quality gates; plan=`docs/LATEST_IMPROVE_PLAN.md` First apply slice + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: Thucy claim-verify **2512.03278**, deterministic decision package **2511.15755**, CEMA **2302.10809**
- apply slice (**First apply slice** from LATEST_IMPROVE_PLAN — prove mine→grade→claims→FTS→gate loop):
  - `src/nexus/grade_artifact.py` — Thucy claims `{statement,path,quote?}`; score/idea/skill range checks; `require_claims` quality gate
  - `src/nexus/evidence_fts.py` — SQLite FTS5 `index_workspace` / `search_evidence` / `grade_validate_fixtures` / `smoke_search`
  - `src/nexus/mcp_server.py` — MCP tools `index_workspace`, `search_evidence`
  - `src/nexus/load_mine_eval.py` — claims passthrough from fixtures
  - `src/nexus/tool_catalog.py` — privilege map for new tools
  - `Makefile` — `grade-validate`, `mcp-smoke`, `test-quality` (wshobson/mission-control style gates)
  - fixture: `fixtures/mine_eval/grades_with_claims.json` (wshobson Markdown marketplace + arXiv 2511.15755 decision package)
  - tests: `tests/test_evidence_fts.py`
  - docs: `docs/LATEST_IMPROVE_PLAN.md` pass criteria checked; this log
- patterns: cas MCP SQLite/FTS; soul ledger simplicity; Thucy path-anchored claims; wshobson Makefile validate; mission-control quality gates (pattern only, no tree vendor)
- non-goals kept: no full worktree apply engine rewrite, no board UI, no Temporal, no vendored trees
- next open: wire evidence FTS into alive apply selection · budget/role-separated verifier · board CLI
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 404 passed; `make grade-validate` + `make mcp-smoke` → OK

## Cycle 2026-07-15 22:47:31Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-bc3837bb82.md`

## Cycle 2026-07-15 hard-apply First apply slice — FTS select + roles + board (Grok 4.5 CLI)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (wshobson 16 / cas / mission-control / routa / Network-AI / zenith / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: anti-collusion **2601.00360**, decision package **2511.15755**, Thucy claims **2512.03278**, AOAD-MAT order **2510.13343**, CEMA **2302.10809** (notes `improve-rx-051972dbae` + priors)
- apply slice (**First apply slice** — close prior open: FTS→select · role verifier · board CLI):
  - `src/nexus/apply_select.py` — `select_candidates` (score+FTS rank), `check_roles`/`require_roles` (grader≠implementer≠verifier), `gate_apply` (IndependentVerify + RunBudget), `decision_package` (`nexus.decision_package/v1`), `improve_board` (`nexus.improve_board/v1`)
  - `src/nexus/cli.py` — `nexus improve select|board|decide`
  - `src/nexus/mcp_server.py` — tools `apply_select`, `improve_board`
  - `src/nexus/tool_catalog.py` — privilege map
  - tests: `tests/test_apply_select.py` (14 cases: collusion, rank, budget, CLI, MCP)
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: cas FTS rank; mission-control/Network-AI budgets; routa board; anti-collusion 2601.00360; decision package 2511.15755; zenith independent verify (pattern only, no tree vendor)
- non-goals kept: no auto-promote without flag; no vendored trees; no live Grok in unit tests
- next open: wire decision_package into worktree_apply / alive self_approve · board stop/replan signals · preference-pair rubric learning
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 418 passed; `nexus improve board` ranks wshobson/agents first

## Cycle 2026-07-15 22:58:56Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-051972dbae.md`

## Cycle 2026-07-15 hard-apply First apply slice — decision→apply + board signals (Grok 4.5 CLI)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (wshobson 16 / cas / mission-control / zenith / routa / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: decision package **2511.15755**, anti-collusion **2601.00360**, MAEBE **2506.03053**, Thucy **2512.03278**, preference IRL **2602.04518** (deferred), notes `improve-rx-27056d5405` + priors
- apply slice (**First apply slice** — close prior open: wire decision_package into worktree_apply / alive self_approve · board stop/replan):
  - `src/nexus/apply_select.py` — `candidate_from_grade` / `decision_for_grade`; `board_signal` (continue|replan|stop); board + decision_package expose signal
  - `src/nexus/worktree_apply.py` — after claim_verify, require decision package (default); ledger agent `decide`; fail-closed on deny/stop/replan
  - `src/nexus/alive.py` — `require_decision` / implementer / verifier knobs; `_self_approve_decision_gate` before hard apply
  - `src/nexus/cli.py` — `improve apply --no-require-decision` + role flags; board shows SIGNAL
  - tests: `tests/test_apply_select.py` (signals + decision_for_grade), `tests/test_worktree_apply.py` (collusion deny), `tests/test_usage_alive.py` (gate)
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: zenith stop/replan; 2511.15755 decision package; 2601.00360 roles; cas/forge worktree; routa board; mission-control operator gate (pattern only, no tree vendor)
- non-goals kept: no preference-pair learning yet; no vendored trees; no auto-promote without flags
- next open: preference-pair rubric learning · wire board signal into PrincipledStop gap board · more pattern catalog entries
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 430 passed


## Cycle 2026-07-15 23:10:24Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-27056d5405.md`

## Cycle 2026-07-15 hard-apply First apply slice — board→gaps + preferences (Grok 4.5 CLI)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (wshobson 16 / cas / mission-control / zenith / routa / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: preference IRL **2602.04518**, decision package **2511.15755**, anti-collusion **2601.00360**, MAEBE **2506.03053**, Thucy **2512.03278** (notes `improve-rx-a7bfdd595a` + priors)
- apply slice (**First apply slice** — close prior open: board signal→PrincipledStop · preference pairs · pattern catalog):
  - `src/nexus/apply_select.py` — `sync_signal_to_stop` (replan/stop→gaps, hard stop abort, continue closes)
  - `src/nexus/alive.py` — knobs `sync_board_gaps` / `abort_on_board_stop` / `record_preferences`; gate + principled stop wire
  - `src/nexus/preference_pairs.py` — offline better>worse JSONL + boost/brief (**2602.04518**)
  - `src/nexus/worktree_apply.py` — pattern `cas-evidence-board-ops`; APPLY_META by pack_id
  - `src/nexus/cli.py` — `improve board --sync-gaps|--record-pref`; `improve prefer list|record`
  - tests: `tests/test_apply_select.py`, `test_preference_pairs.py`, `test_usage_alive.py`, `test_worktree_apply.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: zenith stop/replan/gap; cas FTS board skill; mission-control/routa board; preference IRL offline pairs (pattern only, no tree vendor)
- non-goals kept: no live IRL trainer; no vendored trees; no auto-promote without flags
- next open: preference_boost in select rank · CI board --sync-gaps smoke · more pattern catalog
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 440 passed

## Cycle 2026-07-15 23:21:25Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-a7bfdd595a.md`

## Cycle 2026-07-15 hard-apply First apply slice — preference rank + board CI + spend pattern (Grok 4.5 CLI)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (EDDI 17 / wshobson 16 / MisterSmith 16 / mission-control 15 / cas 15 / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: communication **2203.08975**, context **2508.08322**, preference IRL **2602.04518**, decision package **2511.15755**, anti-collusion **2601.00360** (notes `improve-rx-1bccfca000` + priors)
- apply slice (**First apply slice** — close prior open: preference_boost in select · CI board-sync-gaps · pattern catalog):
  - `src/nexus/apply_select.py` — `rank_score(..., preference_delta=)`; `select_candidates(use_preference=True)` applies offline boost; rows expose `preference_boost`; `smoke_board_sync` CI helper; board/select format show `pref=`
  - `src/nexus/worktree_apply.py` — pattern `mission-control-spend-ops` (ops list/spend/status skill)
  - `Makefile` — `board-sync-gaps` target; `test-quality` includes it
  - `.github/workflows/ci.yml` — quality gates + sample MCP eval packs
  - tests: `tests/test_apply_select.py` (pref rank + smoke), `tests/test_worktree_apply.py` (spend pattern)
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: mission-control spend/ops; cas FTS board; wshobson SoT; zenith stop/replan; arXiv 2602.04518 preference bias (pattern only, no tree vendor)
- non-goals kept: no live IRL trainer; no vendored trees; no auto-promote without flags
- next open: preference brief → context_pack · CLI `--no-preference` · alive auto `record_from_ranked`
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 443 passed; `smoke_board_sync` → signal=continue

## Cycle 2026-07-15 23:31:01Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-1bccfca000.md`

## Cycle 2026-07-15 hard-apply First apply slice — grade ledger + eval CLI (Grok 4.5 CLI)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (AssetOpsBench 16 / routa 16 / soul 15 / lumen 15 / …) plan=`docs/LATEST_IMPROVE_PLAN.md` First apply slice + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: AOAD-MAT ordered stages **2510.13343**, multi-stage checkpoints **2604.03350**, CEMA why_selected **2302.10809**
- apply slice (**First apply slice** from LATEST_IMPROVE_PLAN — prove mine→grade→retain→report):
  - `src/nexus/grade_ledger.py` — append-only SQLite `nexus.grade_ledger/v1` under `.nexus_workspaces/mine_eval/ledger/`; weak scores retained; UPDATE/DELETE forbidden (triggers + API); idempotent `(run_id, repo, method)`; `checkpoint_stage`/`load_checkpoint`; `ingest_grades`/`record_evaluate_results`; MD/JSON export with `why_selected`
  - `src/nexus/grade_cli.py` — `nexus-eval` entrypoint (AssetOpsBench shape)
  - `src/nexus/cli.py` — `nexus grade list|top|weak|export|ingest|checkpoint`
  - `src/nexus/repo_mine.py` — `step_evaluate` writes ledger + grade checkpoint; skips re-grade from checkpoint
  - `pyproject.toml` — script `nexus-eval`
  - tests: `tests/test_grade_ledger.py` (immutable, weak retain, checkpoint, no-dupe re-run, CLI export)
  - docs: `docs/LATEST_IMPROVE_PLAN.md` success criteria checked; this log
- patterns: soul immutable ledger; lumen keep-weak-scores; AssetOpsBench eval CLI; AOAD-MAT/2604.03350 stage checkpoints; CEMA decision audit (pattern only, no tree vendor)
- non-goals kept: no full MCP server, no worktree supervisor, no UI board, no Temporal/NATS, no vendored trees
- next open: P0.5 idempotent apply markers from ledger export · soul-style MCP handoff reading grade ledger · wire grade export into improve_apply brief
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 451 passed; `nexus grade ingest|top|export` on mine_eval_sample OK

## Cycle 2026-07-15 23:46:37Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-eee4f605c5.md`

## Cycle 2026-07-15 hard-apply First apply slice — work ledger + dual-control (Grok 4.5 CLI)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (EDDI 17 / wshobson 16 / soul 15 / cas 15 / openrouter-deep-research 15 / lumen 15 / …) plan=`docs/LATEST_IMPROVE_PLAN.md` First apply slice + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: deterministic decision package **2511.15755**, anti-collusion **2601.00360**, interleaved invariants **1301.6431**, CEMA causal **2302.10809**
- apply slice (**First apply slice** from LATEST_IMPROVE_PLAN — prove mine→grade→ledger→gated apply):
  - `src/nexus/work_ledger.py` — append-only SQLite `work_events` (`nexus.work_ledger/v1`); events mine_completed / grade_recorded / decision_packet / apply_*; dual-control refuse same agent/role; decision packet threshold; `protected_call` breaker; handoffs; causal chain demo
  - `src/nexus/cli.py` — `nexus improve work-loop` · `nexus improve work-ledger`
  - tests: `tests/test_work_ledger.py` (append-only, dual-control, breaker, integration, CLI)
  - docs: `docs/LATEST_IMPROVE_PLAN.md` success criteria checked; this log
- patterns: soul immutable ledger; openrouter-deep-research breaker; lumen decision audit; cas/mission-control SQLite; anti-collusion 2601.00360 (pattern only, no tree vendor)
- non-goals kept: no full EDDI/mission-control UI; no Temporal/NATS; no worktree swarm in this PR; no vendored trees
- next open: wire work_ledger accept into worktree_apply / alive self_approve · optional MCP work_ledger tools · P0.5 interleaving invariants on worker transitions
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 466 passed; `nexus improve work-loop --repo wshobson/agents` → apply_accepted + causal chain

## Cycle 2026-07-15 23:56:22Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=20 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-8c2205e729.md`

## Cycle 2026-07-16 hard-apply First apply slice — work_ledger wire + transitions (Grok 4.5 CLI)
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: IMPROVE_OURS top repos (EDDI / wshobson / soul / cas / mission-control / …) plan=`docs/LATEST_IMPROVE_PLAN.md` + `.nexus_state/repo_mine/IMPROVE_OURS.md`
- arxiv: decision package **2511.15755**, anti-collusion **2601.00360**, interleaving **1301.6431**, CEMA **2302.10809** (notes `improve-rx-8c2205e729` + priors)
- apply slice (**First apply slice** — close prior open: work_ledger→apply/alive · MCP · P0.5 transitions):
  - `src/nexus/work_ledger.py` — `LEGAL_SUCCESSORS` / `assert_legal_transition`; resume-safe `ensure_apply_gate`; `work_ledger_status`
  - `src/nexus/worktree_apply.py` — `require_work_ledger` (default=require_decision); dual-control accept before plan_apply
  - `src/nexus/alive.py` — `require_work_ledger` knob; `_self_approve_work_ledger_gate` in decision gate
  - `src/nexus/mcp_server.py` — tool `work_ledger` (status|tail|chain|gate|first_slice|transitions)
  - `src/nexus/tool_catalog.py` — privilege `ops` for `work_ledger`
  - tests: `tests/test_work_ledger.py`, `test_worktree_apply.py`, `test_usage_alive.py`
  - docs: restored `docs/SELF_IMPROVE_CYCLE.md` + `docs/LATEST_IMPROVE_PLAN.md`; this log
- patterns: soul immutable ledger; cas/mission-control MCP surface; dual-control 2601.00360; interleaving 1301.6431 (pattern only, no tree vendor)
- non-goals kept: no vendored trees; no auto-promote without flags; no live network in unit tests
- next open: preference brief → context_pack · more pattern catalog · multi-worker interleaving stress
- evidence: `PYTHONPATH=src python3 -m pytest -q` → 474 passed

## Cycle 2026-07-16 00:09:12Z
- goal: `self-improve nexus-core from 10 arXiv papers + 10 mined repos using Grok 4.5 for grading, reasoning, and hard apply`
- mine: fetch=None eval=20 used=20 plan=`None`
- arxiv: papers=0 notes=`/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-ebb5fe5b75.md`
