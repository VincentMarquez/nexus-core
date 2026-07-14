#!/usr/bin/env python3
"""
Smoke eval suite — proves durability + autonomy gate + human wait path.

Cases:
  1. full_complete — 10/10 completed
  2. kill_resume  — stop after step 3, resume to completed
  3. autonomy_block — auto_created refused when autonomy off
  4. human_gate — waiting_human when auto_approve=False

Exit 0 only if all pass.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexus import DurableEngine, Settings, Task
from nexus.engine import TaskStatus


def _engine(tmp: Path, **kw) -> DurableEngine:
    settings = Settings(state_dir=tmp / "state", autonomy=False)
    return DurableEngine(settings=settings, **kw)


def case_full(tmp: Path) -> None:
    eng = _engine(tmp)
    t = eng.run(
        Task(
            task_id="smoke_full",
            objective="demo",
            success_criteria=["artifact contains DEMO_OK"],
        )
    )
    assert t.status == TaskStatus.completed, t.meta
    assert t.current_step == 10


def case_kill_resume(tmp: Path) -> None:
    eng = _engine(tmp)
    t = eng.run(
        Task(
            task_id="smoke_resume",
            objective="demo resume",
            success_criteria=["artifact contains DEMO_OK"],
        ),
        max_steps=3,
    )
    assert t.status == TaskStatus.running
    assert t.current_step == 3
    t2 = eng.resume("smoke_resume")
    assert t2.status == TaskStatus.completed
    assert t2.current_step == 10


def case_autonomy(tmp: Path) -> None:
    eng = _engine(tmp)
    t = eng.run(Task(task_id="smoke_auto", objective="x", meta={"auto_created": True}))
    assert t.status == TaskStatus.failed
    assert "autonomy" in (t.meta.get("error") or "")


def case_human_gate(tmp: Path) -> None:
    eng = _engine(tmp, auto_approve=False)
    t = eng.run(
        Task(
            task_id="smoke_human",
            objective="needs human",
            success_criteria=["artifact contains DEMO_OK"],
        )
    )
    assert t.status == TaskStatus.waiting_human
    assert t.current_step == 8  # last completed before approval (step 9)
    t2 = eng.resume("smoke_human", approve=True)
    assert t2.status == TaskStatus.completed


def main() -> int:
    cases = [
        ("full_complete", case_full),
        ("kill_resume", case_kill_resume),
        ("autonomy_block", case_autonomy),
        ("human_gate", case_human_gate),
    ]
    results = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in cases:
            try:
                fn(root / name)
                results.append({"case": name, "ok": True})
                print(f"PASS  {name}")
            except Exception as e:
                results.append({"case": name, "ok": False, "error": str(e)})
                print(f"FAIL  {name}: {e}")
    ok = all(r["ok"] for r in results)
    print(json.dumps({"passed": sum(r["ok"] for r in results), "total": len(results)}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
