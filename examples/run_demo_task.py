#!/usr/bin/env python3
"""Run (or resume) a demo task through the durable engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# allow running without install
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexus import DurableEngine, Settings, Task


def main() -> int:
    ap = argparse.ArgumentParser(description="NEXUS Core demo task")
    ap.add_argument("--resume", metavar="TASK_ID", help="resume an existing task id")
    ap.add_argument("--task-id", default="demo-task-1")
    ap.add_argument("--kill-after", type=int, default=0, help="stop after N new steps (simulate crash)")
    ap.add_argument("--no-auto-approve", action="store_true", help="stop at human approval step")
    ap.add_argument("--sqlite-memory", action="store_true", help="use SQLite FTS memory")
    args = ap.parse_args()

    settings = Settings(autonomy=False, state_dir=Path(".nexus_state"))
    memory = None
    if args.sqlite_memory:
        from nexus.memory_sqlite import SqliteMemory

        memory = SqliteMemory.demo(settings.state_dir / "memory.db")
    engine = DurableEngine(
        settings=settings,
        auto_approve=not args.no_auto_approve,
        memory=memory,
    )

    if args.resume:
        task = engine.resume(args.resume)
    else:
        task = Task(
            task_id=args.task_id,
            objective="Write a tiny artifact that proves the durable pipeline works",
            success_criteria=["artifact contains DEMO_OK"],
            namespace="proj/demo",
        )
        # fresh run: remove old checkpoint if reusing id
        p = settings.state_dir / "tasks" / f"{args.task_id}.json"
        if p.exists() and not args.resume:
            # continue if exists unless user wants fresh — default overwrite only if step 0
            existing = engine.load(args.task_id)
            if existing.status.value == "completed":
                print(f"task {args.task_id} already completed; use a new --task-id or delete .nexus_state")
                print(json.dumps(existing.to_dict(), indent=2)[:800])
                return 0
            task = existing
        max_steps = args.kill_after if args.kill_after > 0 else None
        task = engine.run(task, max_steps=max_steps)

    print("=== task result ===")
    print(f"id:     {task.task_id}")
    print(f"status: {task.status.value}")
    print(f"step:   {task.current_step}/10")
    if task.meta.get("error"):
        print(f"error:  {task.meta['error']}")
    print(f"checkpoint: {settings.state_dir / 'tasks' / (task.task_id + '.json')}")
    # short output summary
    for n, out in sorted(task.outputs.items()):
        v = (out.get("_verdict") or {}).get("decision")
        print(f"  step {n}: keys={list(k for k in out if k != '_verdict')[:5]} verdict={v}")
    # intentional partial run (kill-after) exits 0 so demos/scripts can chain to --resume
    if task.status.value == "running" and args.kill_after > 0:
        return 0
    return 0 if task.status.value == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
