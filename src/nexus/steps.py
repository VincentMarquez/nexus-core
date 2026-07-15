"""10-step adversarial pipeline policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class StepDef:
    number: int
    name: str
    description: str
    agent: str | list[str]
    checkpoint: bool = False
    human: bool = False
    required_capability: Optional[str] = None
    output_keys: tuple[str, ...] = ()
    timeout_s: Optional[int] = None
    # DAG edges: step numbers that must complete before this step runs.
    # Empty = only sequential current_step ordering (legacy linear pipeline).
    depends_on: tuple[int, ...] = ()


@dataclass
class StepPolicy:
    steps: list[StepDef] = field(default_factory=list)

    def __iter__(self):
        return iter(self.steps)

    def get(self, number: int) -> StepDef:
        for s in self.steps:
            if s.number == number:
                return s
        raise KeyError(number)

    def ready(
        self,
        completed: set[int],
        *,
        current_step: int = 0,
    ) -> list[StepDef]:
        """Steps whose dependencies are satisfied and not yet completed.

        If no step declares ``depends_on``, falls back to linear order:
        the next number after ``current_step``.
        """
        any_deps = any(s.depends_on for s in self.steps)
        if not any_deps:
            for s in self.steps:
                if s.number > current_step:
                    return [s]
            return []
        ready: list[StepDef] = []
        for s in self.steps:
            if s.number in completed:
                continue
            deps = set(s.depends_on)
            if deps.issubset(completed):
                ready.append(s)
        ready.sort(key=lambda s: s.number)
        return ready

    def topo_numbers(self) -> list[int]:
        """Topological order of step numbers (Kahn). Raises on cycles."""
        steps = {s.number: s for s in self.steps}
        indeg = {n: 0 for n in steps}
        succ: dict[int, list[int]] = {n: [] for n in steps}
        for s in self.steps:
            for d in s.depends_on:
                if d not in steps:
                    continue
                indeg[s.number] += 1
                succ[d].append(s.number)
        # linear edges when no explicit deps: n-1 → n for stability
        if not any(s.depends_on for s in self.steps):
            nums = sorted(steps)
            for a, b in zip(nums, nums[1:]):
                indeg[b] += 1
                succ[a].append(b)
        q = sorted(n for n, deg in indeg.items() if deg == 0)
        out: list[int] = []
        while q:
            n = q.pop(0)
            out.append(n)
            for m in succ[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    q.append(m)
                    q.sort()
        if len(out) != len(steps):
            raise ValueError("step dependency cycle detected")
        return out

    @classmethod
    def default(cls) -> "StepPolicy":
        """Canonical NEXUS-style 10-step policy (generic agent roles).

        Explicit ``depends_on`` documents the DAG; linear numbers still work
        when runners only advance ``current_step``.
        """
        steps = [
            StepDef(
                1, "goal", "Operator defines objective and success criteria",
                "operator", output_keys=("objective", "constraints", "success_criteria"),
            ),
            StepDef(
                2, "plan", "Planner architects the approach",
                "planner", required_capability="can_plan",
                output_keys=("approach", "risks", "estimated_steps"),
                depends_on=(1,),
            ),
            StepDef(
                3, "challenge", "Adversary challenges the plan",
                "adversary", checkpoint=True, required_capability="can_review",
                output_keys=("concerns", "alternatives", "recommendation"),
                depends_on=(2,),
            ),
            StepDef(
                4, "implement", "Implementer produces artifacts",
                "implementer", required_capability="can_execute",
                output_keys=("artifacts", "notes"),
                depends_on=(3,),
            ),
            StepDef(
                5, "test", "Tester runs checks and reports evidence",
                "tester", checkpoint=True, required_capability="can_execute",
                output_keys=("pass_fail", "evidence", "stdout"),
                depends_on=(4,),
            ),
            StepDef(
                6, "review", "Reviewer verdict on the work",
                "reviewer", required_capability="can_review",
                output_keys=("findings", "severity", "verdict"),
                depends_on=(5,),
            ),
            StepDef(
                7, "log", "Logger snapshots system state",
                "logger", required_capability="can_log",
                output_keys=("state_snapshot",),
                depends_on=(6,),
            ),
            StepDef(
                8, "meta_review", "Multi-agent meta review",
                ["reviewer", "adversary", "planner"], required_capability="can_review",
                output_keys=("agent_verdicts", "unanimous"),
                depends_on=(6, 7),
            ),
            StepDef(
                9, "approval", "Human final approval",
                "operator", checkpoint=True, human=True,
                output_keys=("approved", "feedback"),
                depends_on=(8,),
            ),
            StepDef(
                10, "deliver", "Finalize deliverable / report",
                "implementer", required_capability="can_execute",
                output_keys=("report", "handoff"),
                depends_on=(9,),
            ),
        ]
        return cls(steps=steps)


# Capability model
AGENT_CAPABILITIES: dict[str, set[str]] = {
    "operator": {"can_goal", "can_approve"},
    "planner": {"can_plan", "can_review"},
    "adversary": {"can_review", "can_plan"},
    "implementer": {"can_execute", "can_plan"},
    "tester": {"can_execute", "can_review"},
    "reviewer": {"can_review"},
    "logger": {"can_log"},
    "local": {"can_plan", "can_review", "can_execute", "can_log"},
}

FALLBACK_TABLE: dict[str, Optional[str]] = {
    "planner": "local",
    "adversary": "reviewer",
    "implementer": "local",
    "tester": "local",
    "reviewer": "local",
    "logger": "local",
    "local": None,
    "operator": None,
}


def structural_ok(step: StepDef, output: dict[str, Any]) -> tuple[bool, str]:
    """Cheap pre-gate: required keys exist. Not a success-criteria judge."""
    if not isinstance(output, dict):
        return False, "output is not a dict"
    missing = [k for k in step.output_keys if k not in output]
    if missing:
        return False, f"missing keys: {missing}"
    return True, "ok"
