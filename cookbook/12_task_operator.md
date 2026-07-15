# 12 — Task operator board (production audit)

Inspect durable tasks like an ops console: list, replay, cost, evidence, HITL resume.

## Prereq

```bash
cd nexus-core
pip install -e ".[dev]"
export PYTHONPATH=src
```

## Run a durable task

```bash
python3 examples/run_demo_task.py --task-id op-demo-1
# or crash mid-way then resume:
python3 examples/run_demo_task.py --task-id op-demo-2 --kill-after 3
python3 examples/run_demo_task.py --resume op-demo-2
```

## Operator commands

```bash
nexus task list
nexus task show op-demo-1
nexus task events op-demo-1
nexus task replay op-demo-1
nexus task explain op-demo-1
nexus task cost op-demo-1
nexus task prov op-demo-1
nexus task verify op-demo-1
nexus task graph op-demo-1 --mermaid
nexus task evidence op-demo-1 --out /tmp/evidence.json
```

## Human-in-the-loop

```bash
# stop at approval (no auto-approve)
python3 examples/run_demo_task.py --task-id hitl-1 --no-auto-approve
# status should be waiting_human
nexus task show hitl-1
nexus task resume hitl-1 --approve
# or: nexus task resume hitl-1 --reject --feedback "needs tests"
```

Full scripted demo:

```bash
python3 examples/demo_hitl_resume.py
```

## What “production-like” means here

| Surface | Meaning |
|---------|---------|
| Checkpoint JSON | Crash-safe task state |
| `*.events.jsonl` | Append-only audit log |
| `replay` / `explain` | No re-run; post-hoc audit |
| `evidence` | Portable pack for boards / CI |
| `resume --approve` | HITL gate (rojak-style) |

See also: [01 crash → resume](01_crash_resume.md), README **Production-like durability**.
