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
