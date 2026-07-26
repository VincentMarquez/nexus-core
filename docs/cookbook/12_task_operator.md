# 12 — Task operator board (production audit)

Inspect durable tasks like an ops console: list, replay, cost, evidence, and resume human-in-the-loop work.

## Prerequisite

```bash
git clone https://github.com/VincentMarquez/nexus-core.git
cd nexus-core
make install
source .venv/bin/activate
```

## Run a durable task

```bash
python3 examples/run_demo_task.py --task-id op-demo-1
# Or crash mid-way and resume:
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
nexus task dag op-demo-1 --mermaid
nexus task consensus op-demo-1
nexus task context op-demo-1
nexus task evidence op-demo-1 --out /tmp/evidence.json
```

## Human in the loop

```bash
# Stop at approval; do not auto-approve.
python3 examples/run_demo_task.py --task-id hitl-1 --no-auto-approve
nexus task show hitl-1
nexus task resume hitl-1 --approve
# Or: nexus task resume hitl-1 --reject --feedback "needs tests"
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
| `replay` / `explain` | Post-hoc audit without rerunning agents |
| `cost` / `prov` / `verify` | Usage, provenance, and checkpoint/journal consistency |
| `graph` / `dag` | Agent handoffs and policy dependency/action order |
| `consensus` | Recorded multi-grader findings and trust weights |
| `context` | Bounded goal, constraint, journal, memory, research, and repository context |
| `evidence` | Portable pack for boards and CI |
| `resume --approve` | Human gate without losing checkpoint state |

These inspection commands read recorded state; they do not rerun agents. See
also [01 — Crash → resume](01_crash_resume.md) and
[Task evidence packs](../evidence/README.md).
