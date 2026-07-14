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

    @classmethod
    def default(cls) -> "StepPolicy":
        """Canonical NEXUS-style 10-step policy (generic agent roles)."""
        steps = [
            StepDef(
                1, "goal", "Operator defines objective and success criteria",
                "operator", output_keys=("objective", "constraints", "success_criteria"),
            ),
            StepDef(
                2, "plan", "Planner architects the approach",
                "planner", required_capability="can_plan",
                output_keys=("approach", "risks", "estimated_steps"),
            ),
            StepDef(
                3, "challenge", "Adversary challenges the plan",
                "adversary", checkpoint=True, required_capability="can_review",
                output_keys=("concerns", "alternatives", "recommendation"),
            ),
            StepDef(
                4, "implement", "Implementer produces artifacts",
                "implementer", required_capability="can_execute",
                output_keys=("artifacts", "notes"),
            ),
            StepDef(
                5, "test", "Tester runs checks and reports evidence",
                "tester", checkpoint=True, required_capability="can_execute",
                output_keys=("pass_fail", "evidence", "stdout"),
            ),
            StepDef(
                6, "review", "Reviewer verdict on the work",
                "reviewer", required_capability="can_review",
                output_keys=("findings", "severity", "verdict"),
            ),
            StepDef(
                7, "log", "Logger snapshots system state",
                "logger", required_capability="can_log",
                output_keys=("state_snapshot",),
            ),
            StepDef(
                8, "meta_review", "Multi-agent meta review",
                ["reviewer", "adversary", "planner"], required_capability="can_review",
                output_keys=("agent_verdicts", "unanimous"),
            ),
            StepDef(
                9, "approval", "Human final approval",
                "operator", checkpoint=True, human=True,
                output_keys=("approved", "feedback"),
            ),
            StepDef(
                10, "deliver", "Finalize deliverable / report",
                "implementer", required_capability="can_execute",
                output_keys=("report", "handoff"),
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
