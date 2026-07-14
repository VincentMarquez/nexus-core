#!/usr/bin/env python3
"""Human approval CLI for tasks waiting at step 9.

Usage:
  python examples/run_demo_task.py --task-id needs-you --no-auto-approve   # if we add flag
  python examples/approve_task.py needs-you --approve
  python examples/approve_task.py needs-you --reject
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexus import DurableEngine, Settings
from nexus.engine import TaskStatus


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task_id")
    ap.add_argument("--state-dir", default=".nexus_state")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--approve", action="store_true")
    g.add_argument("--reject", action="store_true")
    args = ap.parse_args()

    settings = Settings(state_dir=Path(args.state_dir))
    engine = DurableEngine(settings=settings, auto_approve=False)
    task = engine.load(args.task_id)
    print(f"loaded {task.task_id} status={task.status.value} step={task.current_step}")
    if task.status != TaskStatus.waiting_human:
        print("not waiting_human — nothing to approve (continuing resume anyway)")

    task = engine.resume(args.task_id, approve=bool(args.approve) and not args.reject)
    if args.reject and task.status != TaskStatus.completed:
        # mark rejected
        task.status = TaskStatus.failed
        task.meta["error"] = "rejected by human"
        engine.save(task)

    print(f"result status={task.status.value} step={task.current_step}")
    if task.meta.get("error"):
        print("error:", task.meta["error"])
    return 0 if task.status == TaskStatus.completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
