"""10-step adversarial pipeline policy + multi-agent task DAG helpers.

P1.2: goal → ordered agent steps with ``depends_on`` (open-multi-agent DAG shape;
AOAD-MAT explicit action order). Pattern only — no vendored trees.
"""

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


def completed_set(
    outputs: Optional[dict[int, Any]] = None,
    *,
    current_step: int = 0,
) -> set[int]:
    """Resolve completed step numbers from task outputs / legacy current_step.

    Prefer explicit ``outputs`` keys (DAG source of truth). When outputs are
    empty but ``current_step`` advanced (legacy checkpoints), treat
    ``1..current_step`` as done.
    """
    done: set[int] = set()
    if outputs:
        for k in outputs:
            try:
                done.add(int(k))
            except (TypeError, ValueError):
                continue
    if not done and int(current_step or 0) > 0:
        done = set(range(1, int(current_step) + 1))
    return done


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

    def has_dag(self) -> bool:
        """True when any step declares an explicit ``depends_on`` edge."""
        return any(s.depends_on for s in self.steps)

    def numbers(self) -> set[int]:
        return {s.number for s in self.steps}

    def validate(self) -> None:
        """Fail-closed: unknown dependency targets or cycles raise ValueError."""
        nums = self.numbers()
        for s in self.steps:
            for d in s.depends_on:
                if d not in nums:
                    raise ValueError(
                        f"step {s.number} ({s.name}) depends_on unknown step {d}"
                    )
        self.topo_numbers()  # raises on cycle

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
        any_deps = self.has_dag()
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

    def next_ready(
        self,
        completed: set[int],
        *,
        current_step: int = 0,
    ) -> Optional[StepDef]:
        """Deterministic next step: lowest-number ready (AOAD-MAT stable order)."""
        r = self.ready(completed, current_step=current_step)
        return r[0] if r else None

    def blocked(self, completed: set[int]) -> list[StepDef]:
        """Incomplete steps still waiting on unmet dependencies."""
        if not self.has_dag():
            return []
        out: list[StepDef] = []
        for s in self.steps:
            if s.number in completed:
                continue
            deps = set(s.depends_on)
            if deps and not deps.issubset(completed):
                out.append(s)
        out.sort(key=lambda s: s.number)
        return out

    def pending(self, completed: set[int]) -> list[StepDef]:
        """All incomplete steps (ready + blocked)."""
        out = [s for s in self.steps if s.number not in completed]
        out.sort(key=lambda s: s.number)
        return out

    def prior_keys(self, step: StepDef) -> tuple[int, ...]:
        """Which prior step outputs to inject as context (deps-only when DAG).

        open-multi-agent ``memoryScope: dependencies`` pattern: prefer explicit
        ``depends_on``; otherwise legacy ``1..number-1``.
        """
        if step.depends_on:
            return tuple(sorted(step.depends_on))
        return tuple(range(1, step.number))

    def dependency_edges(self) -> list[tuple[int, int]]:
        """(from, to) edges: dependency → dependent (Kahn / mermaid direction)."""
        edges: list[tuple[int, int]] = []
        if not self.has_dag():
            nums = sorted(self.numbers())
            for a, b in zip(nums, nums[1:]):
                edges.append((a, b))
            return edges
        for s in self.steps:
            for d in s.depends_on:
                edges.append((int(d), int(s.number)))
        edges.sort()
        return edges

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

    def mermaid(
        self,
        *,
        completed: Optional[set[int]] = None,
        ready_nums: Optional[set[int]] = None,
    ) -> str:
        """Policy dependency DAG as mermaid flowchart (operator paste)."""
        completed = completed or set()
        ready_nums = ready_nums or set()
        lines = ["flowchart TD"]
        if not self.steps:
            lines.append("  empty[no steps]")
            return "\n".join(lines)
        for s in sorted(self.steps, key=lambda x: x.number):
            safe_name = s.name.replace('"', "'")
            label = f"s{s.number}:{safe_name}"
            if s.number in completed:
                shape = f'  s{s.number}["{label} ✓"]'
            elif s.number in ready_nums:
                shape = f'  s{s.number}["{label} ▶"]'
            else:
                shape = f'  s{s.number}["{label}"]'
            lines.append(shape)
        for frm, to in self.dependency_edges():
            lines.append(f"  s{frm} --> s{to}")
        return "\n".join(lines)

    def dag_snapshot(
        self,
        *,
        completed: Optional[set[int]] = None,
        current_step: int = 0,
        action_order: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Inspectable multi-agent task DAG (open-multi-agent plan shape)."""
        done = set(completed or set())
        ready_list = self.ready(done, current_step=current_step)
        ready_nums = {s.number for s in ready_list}
        blocked_list = self.blocked(done)
        nodes: list[dict[str, Any]] = []
        for s in sorted(self.steps, key=lambda x: x.number):
            if s.number in done:
                status = "completed"
            elif s.number in ready_nums:
                status = "ready"
            elif s.number in {b.number for b in blocked_list}:
                status = "blocked"
            else:
                status = "pending"
            agent = s.agent if isinstance(s.agent, str) else list(s.agent)
            nodes.append(
                {
                    "id": s.number,
                    "name": s.name,
                    "agent": agent,
                    "depends_on": list(s.depends_on),
                    "status": status,
                    "human": bool(s.human),
                    "checkpoint": bool(s.checkpoint),
                }
            )
        edges = [
            {"from": a, "to": b, "kind": "depends_on"}
            for a, b in self.dependency_edges()
        ]
        order = list(action_order or [])
        return {
            "schema": "nexus.dag/v1",
            "has_dag": self.has_dag(),
            "topo": self.topo_numbers(),
            "completed": sorted(done),
            "ready": [s.number for s in ready_list],
            "blocked": [
                {
                    "id": s.number,
                    "name": s.name,
                    "waiting_on": sorted(set(s.depends_on) - done),
                }
                for s in blocked_list
            ],
            "nodes": nodes,
            "edges": edges,
            "action_order": order,
            "mermaid": self.mermaid(completed=done, ready_nums=ready_nums),
            "n_steps": len(self.steps),
            "n_completed": len(done),
            "n_ready": len(ready_list),
            "n_blocked": len(blocked_list),
        }

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
