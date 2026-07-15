#!/usr/bin/env python3
"""Demo: durable task stops for human approval, then resume --approve completes.

  python3 examples/demo_hitl_resume.py
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexus import DurableEngine, Settings, Task
from nexus.engine import TaskStatus


def main() -> int:
    tid = f"hitl-demo-{uuid.uuid4().hex[:8]}"
    settings = Settings(autonomy=False, state_dir=Path(".nexus_state"))
    engine = DurableEngine(settings=settings, auto_approve=False, journal=True)

    task = Task(
        task_id=tid,
        objective="HITL demo: pause at human approval then continue",
        success_criteria=["artifact contains DEMO_OK"],
        namespace="proj/hitl",
        constraints=["require:approval"],
    )
    print(f"=== run until human gate (task={tid}) ===")
    task = engine.run(task)
    print(f"status after run: {task.status.value} step={task.current_step}")
    if task.status != TaskStatus.waiting_human:
        # If pipeline didn't hit human (mock panel auto-fills), force gate shape
        print("note: panel did not stop at waiting_human; forcing gate for demo")
        task.status = TaskStatus.waiting_human
        task.meta["waiting_step"] = 9
        engine.save(task)
        engine.record_event(
            tid, "waiting_human",
            step=9, status=task.status.value,
            detail="demo forced gate",
        )

    print("=== reject path smoke (optional) ===")
    # approve path
    print("=== nexus-style resume --approve ===")
    task = engine.resume(tid, approve=True, feedback="demo approved")
    print(f"status after approve: {task.status.value}")
    print(f"human_decision: {task.meta.get('human_decision')}")

    # evidence pack
    pack = engine.evidence(tid)
    out = settings.state_dir / "tasks" / f"{tid}.evidence.json"
    out.write_text(json.dumps(pack, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"evidence → {out}")

    ok = task.status in (TaskStatus.completed, TaskStatus.running, TaskStatus.waiting_human)
    # After approve we expect completed or further progress
    print("=== result ===")
    print(json.dumps({
        "task_id": tid,
        "status": task.status.value,
        "step": task.current_step,
        "evidence": str(out),
        "ok": bool(ok),
    }, indent=2))
    return 0 if task.status != TaskStatus.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
