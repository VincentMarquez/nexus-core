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

Post-hoc audit without re-running agents:

```bash
nexus task replay my-job
nexus task replay my-job --json
nexus task explain my-job
nexus task explain my-job --json
```

`step_complete` events carry `decision` and short `why` fields for the story line.

### Cost + value thresholds (P3)

Roll up spend and inspect explicit judge cutoffs:

```bash
nexus task cost my-job
nexus task cost my-job --json
nexus task explain my-job
```

`step_complete` rows also carry `score`, estimated `tokens`, and `thresholds`
(`pass` / `revise` cutoffs). When usage is recorded with `meta.task_id`,
`usage.by_task(task_id)` provides an optional ledger rollup.

### Provenance + integrity (P4)

Export provenance and check checkpoint/journal consistency:

```bash
nexus task prov my-job
nexus task prov my-job --json
nexus task verify my-job
nexus task verify my-job --json
nexus task list
```

`verify` is read-only. It reports missing journals, step/status drift, and soft
agent/token mismatches without rerunning agents.

### Multi-agent task DAG

Inspect the policy dependency graph and action order. This differs from
`task graph`, which shows agent handoffs:

```bash
nexus task dag my-job
nexus task dag my-job --json
nexus task dag my-job --mermaid
```

The engine schedules the lowest-numbered ready step whose dependencies are
satisfied, records `meta.action_order[]`, and fails closed on invalid or
deadlocked DAGs.

### Task budget + call graph (P5)

Apply a per-task token cap and inspect agent handoffs:

```bash
# Set task.meta["max_tokens"] or constraint "max_tokens=5000" before the run.
nexus task cost my-job
nexus task graph my-job
nexus task graph my-job --json
nexus task graph my-job --mermaid
```

When spend exceeds `max_tokens`, the engine records a `budget` event and fails
closed. The limit is disabled when no cap is configured.

### Evidence pack + norms (P6)

Create one portable audit document containing the timeline, cost, provenance,
integrity result, call graph, and structured constraints:

```bash
nexus task evidence my-job
nexus task evidence my-job --json
nexus task evidence my-job --compact
nexus task evidence my-job --out pack.json
```

Constraints such as `require:tests`, `deny:network`, `must:review`, and
`max_tokens=5000` become typed norms. Readiness gates report `integrity_ok`,
`budget_ok`, `has_timeline`, `completed`, and overall `ready`.

### Context pack stage

Assemble bounded goal, constraint, journal, memory, research, and repo context:

```bash
nexus task context my-job
nexus task context my-job --json
nexus task context my-job --prompt
nexus task context my-job --research
nexus task context my-job --repos
nexus task context my-job --out pack.json
```

The `improve_apply` `context_packed` phase writes the same schema under
`.nexus_workspaces/improve_apply/<run>/context_pack.json` and a prompt Markdown
file. Set `meta.context_pack=true` with optional `context_research` /
`context_repos` to inject it into mid-run prompts.
