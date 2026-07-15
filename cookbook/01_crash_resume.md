# 01 — Crash → resume

**Goal:** Prove a multi-agent task survives process death.

```bash
make install
make demo
```

What happens:

1. Steps 1–3 run and checkpoint to `.nexus_state/tasks/*.json`  
2. Simulated crash (`--kill-after 3`)  
3. Resume continues 4→10 and finishes **completed**

Manual variant:

```bash
python examples/run_demo_task.py --task-id my-job --kill-after 4
python examples/run_demo_task.py --resume my-job
```

**Success:** status `completed`, step `10/10`.

## Inspect checkpoints + event journal

After a run (or mid-resume), the operator surface reads the same durable state:

```bash
nexus task list
nexus task show my-job
nexus task events my-job --limit 20
nexus task events my-job --json   # raw JSONL-as-array
```

Expect: `step_start` / `step_complete` rows, optional `handoff` when agents change,
`resume` after a crash, and `completed` when finished. Journal path:
`.nexus_state/tasks/<id>.events.jsonl`.

### Replay + causal explain (P2)

Post-hoc audit without re-running agents (open-multi-agent plan-replay + CEMA-style why):

```bash
nexus task replay my-job              # normalized timeline
nexus task replay my-job --json
nexus task explain my-job             # steps, handoffs, vetoes, story
nexus task explain my-job --json
```

`step_complete` events carry `decision` + short `why` (judge rationale) for the story line.

### Cost + value thresholds (P3)

Mission-control-style spend rollup and explicit judge cutoffs (value-system audit):

```bash
nexus task cost my-job                # tokens by agent/step + avg score
nexus task cost my-job --json
nexus task explain my-job             # includes cost: tokens=… avg_score=…
```

`step_complete` rows also carry `score`, estimated `tokens`, and `thresholds`
(`pass` / `revise` cutoffs). Optional global ledger rollup: record usage with
`meta.task_id` and `usage.by_task(task_id)` aggregates it.

### Provenance + integrity (P4)

Unified PROV-style export (PROV-AGENT) and checkpoint↔journal durability checks:

```bash
nexus task prov my-job                # agents / activities / entities / relations
nexus task prov my-job --json         # schema nexus.prov/v1
nexus task verify my-job              # OK or FAIL with issue codes
nexus task verify my-job --json
nexus task list                       # board includes TOK column
```

`verify` is read-only: it flags missing journals, step/status drift, and soft
agent/token mismatches without re-running agents.

### Multi-agent task DAG (P1.2)

Policy dependency graph + explicit action order (open-multi-agent plan shape,
AOAD-MAT). Distinct from `task graph` (agent handoff call-graph):

```bash
nexus task dag my-job                 # nodes ready/blocked/completed + action_order
nexus task dag my-job --json          # schema nexus.dag/v1
nexus task dag my-job --mermaid       # pasteable flowchart TD (depends_on edges)
```

The engine schedules the next **ready** step (lowest number among deps-satisfied
steps), records `meta.action_order[]`, and fail-closes on invalid or deadlocked
DAGs. Default 10-step policy declares `depends_on` (e.g. meta_review waits on
review + log).

### Task budget + call-graph (P5)

Per-task hard spend cap (cycgraph / open-multi-agent `maxTokenBudget`) and agent
call-graph / space-time profile from the journal:

```bash
# set before run via task.meta["max_tokens"] or constraint "max_tokens=5000"
nexus task cost my-job                # shows budget: max=… remaining=… ok|EXHAUSTED
nexus task graph my-job               # nodes, handoff edges, sequence
nexus task graph my-job --json        # schema nexus.graph/v1
nexus task graph my-job --mermaid     # pasteable flowchart LR
```

When spend exceeds `max_tokens`, the engine records a `budget` event and fails
closed (may overshoot by one completed step). Unlimited when the cap is unset.

### Evidence pack + norms (P6)

One portable audit document for delivery boards / eval harnesses (routa evidence
+ mission-control export shape). Composes timeline, cost, provenance, verify,
call-graph, and structured norms from task constraints:

```bash
nexus task evidence my-job              # human summary + readiness gates
nexus task evidence my-job --json       # schema nexus.evidence/v1
nexus task evidence my-job --compact    # summary counts (smaller)
nexus task evidence my-job --out pack.json
```

Constraints like `require:tests`, `deny:network`, `must:review`, and
`max_tokens=5000` become typed norms. Gates report `integrity_ok`, `budget_ok`,
`has_timeline`, `completed`, and overall `ready` for delivery-ready runs.

### Context pack stage (P1.4)

Bounded multi-source context for agents and operators (arXiv 2508.08322 context
engineering). Assembles goal, constraints, journal, memory, and optionally
research notes + mined repo digests under a hard char budget:

```bash
nexus task context my-job                 # section sizes + budget
nexus task context my-job --json          # schema nexus.context_pack/v1
nexus task context my-job --prompt        # markdown for agent injection
nexus task context my-job --research      # include .nexus_state/arxiv_improve
nexus task context my-job --repos         # include IMPROVE_OURS / USE_LATEST digests
nexus task context my-job --out pack.json
```

`improve_apply` phase `context_packed` writes the same schema under
`.nexus_workspaces/improve_apply/<run>/context_pack.json` (+ `.prompt.md`).
Set `meta.context_pack=true` (and optional `context_research` / `context_repos`)
to inject the pack into mid-run step prompts.
