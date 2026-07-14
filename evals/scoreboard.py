#!/usr/bin/env python3
"""Scoreboard over durable task checkpoints (.nexus_state/tasks/*.json)."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load_tasks(state_dir: Path) -> list[dict]:
    d = state_dir / "tasks"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def summarize(tasks: list[dict]) -> dict:
    by_status = Counter(t.get("status") for t in tasks)
    n = len(tasks)
    completed = by_status.get("completed", 0)
    failed = by_status.get("failed", 0)
    running = by_status.get("running", 0)
    waiting = by_status.get("waiting_human", 0)
    steps = [int(t.get("current_step") or 0) for t in tasks]
    avg_step = sum(steps) / n if n else 0.0
    return {
        "n_tasks": n,
        "completed": completed,
        "failed": failed,
        "running": running,
        "waiting_human": waiting,
        "completion_rate": (completed / n) if n else 0.0,
        "avg_step": avg_step,
        "by_status": dict(by_status),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=".nexus_state")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    tasks = load_tasks(Path(args.state_dir))
    s = summarize(tasks)
    if args.json:
        print(json.dumps(s, indent=2))
    else:
        print("NEXUS scoreboard")
        print(f"  tasks:      {s['n_tasks']}")
        print(f"  completed:  {s['completed']}  ({100*s['completion_rate']:.1f}%)")
        print(f"  failed:     {s['failed']}")
        print(f"  running:    {s['running']}")
        print(f"  waiting:    {s['waiting_human']}")
        print(f"  avg step:   {s['avg_step']:.1f}/10")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
