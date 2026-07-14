#!/usr/bin/env python3
"""Side-by-side: presence check vs rubric judge.

Presence: "did the agent return a dict?" → often PASS even when work is wrong.
Judge:    "do artifacts satisfy success_criteria?" → grounded in files.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexus.agents import AgentPanel
from nexus.judge import RubricJudge
from nexus.steps import StepPolicy


def presence_ok(output: dict) -> bool:
    return isinstance(output, dict) and len(output) > 0


def main() -> int:
    print("\n=== Presence validator vs Rubric judge ===\n")
    panel = AgentPanel.demo()
    judge = RubricJudge(panel)
    step = StepPolicy.default().get(5)  # test step
    criteria = ["artifact contains DEMO_OK"]
    task = {"success_criteria": criteria, "objective": "ship a tiny proof file"}

    # Case A: agent "replied" but artifact is wrong
    bad_path = Path("results/presence_trap.txt")
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("I pinky-promise it works\n", encoding="utf-8")
    out_bad = {
        "pass_fail": "pass",  # agent claims success
        "evidence": [str(bad_path)],
        "stdout": "all green (trust me)",
    }

    # Case B: real evidence
    good_path = Path("results/presence_ok.txt")
    good_path.write_text("DEMO_OK\n", encoding="utf-8")
    out_good = {
        "pass_fail": "pass",
        "evidence": [str(good_path)],
        "stdout": "ok",
    }

    for label, out in [("WRONG artifact (agent claimed pass)", out_bad), ("CORRECT artifact", out_good)]:
        p = "PASS" if presence_ok(out) else "FAIL"
        v = judge.evaluate(step=step, task=task, output=out, implementer="implementer")
        print(f"{label}")
        print(f"  presence check:  {p}")
        print(f"  rubric judge:    {v.decision.upper()}  score={v.score:.2f}")
        print(f"  rationale:       {v.rationale}")
        print()

    print("Takeaway: presence is necessary plumbing; the judge is the quality gate.")
    print("NEXUS Core hard-fails implement/test when the judge fails.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
