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
