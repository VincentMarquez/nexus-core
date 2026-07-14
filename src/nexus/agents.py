"""Multi-agent panel: health, vendor map, fallbacks, mock implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from .steps import AGENT_CAPABILITIES, FALLBACK_TABLE, StepDef


class Agent(Protocol):
    name: str
    vendor: str

    def run(self, prompt: str, *, step: StepDef, task: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class MockAgent:
    """Deterministic offline agent for demos and tests."""

    name: str
    vendor: str = "mock"
    online: bool = True

    def run(self, prompt: str, *, step: StepDef, task: dict[str, Any]) -> dict[str, Any]:
        if not self.online:
            raise RuntimeError(f"agent offline: {self.name}")
        obj = task.get("objective", "")
        criteria = task.get("success_criteria", [])
        # Produce plausible structured outputs per step name
        if step.name == "goal":
            return {
                "objective": obj or "demo objective",
                "constraints": ["no network", "deterministic"],
                "success_criteria": criteria or ["artifact contains DEMO_OK"],
            }
        if step.name == "plan":
            return {
                "approach": f"Implement a small artifact that satisfies: {criteria}",
                "risks": ["overfitting demo"],
                "estimated_steps": 3,
            }
        if step.name == "challenge":
            return {
                "concerns": ["criteria must be checkable on disk"],
                "alternatives": ["write a one-line file"],
                "recommendation": "proceed with minimal artifact",
            }
        if step.name == "implement":
            path = task.setdefault("_artifact_path", "results/demo_artifact.txt")
            from pathlib import Path

            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text("DEMO_OK\n", encoding="utf-8")
            return {"artifacts": [path], "notes": f"wrote {path} via {self.name}"}
        if step.name == "test":
            paths = (task.get("last_output") or {}).get("artifacts") or [
                task.get("_artifact_path", "results/demo_artifact.txt")
            ]
            from pathlib import Path

            ok = all(Path(p).exists() and "DEMO_OK" in Path(p).read_text(encoding="utf-8") for p in paths)
            return {
                "pass_fail": "pass" if ok else "fail",
                "evidence": paths,
                "stdout": "ok" if ok else "missing DEMO_OK",
            }
        if step.name == "review":
            return {"findings": [], "severity": "low", "verdict": "approve"}
        if step.name == "log":
            return {"state_snapshot": {"step": step.number, "agent": self.name}}
        if step.name == "meta_review":
            return {"agent_verdicts": {self.name: "approve"}, "unanimous": True}
        if step.name == "approval":
            # Auto-approve in mock mode; real systems interrupt for humans.
            return {"approved": True, "feedback": "auto-approved (mock)"}
        if step.name == "deliver":
            return {
                "report": "results/demo_report.md",
                "handoff": "complete",
            }
        return {"status": "ok", "response": f"{self.name} handled {step.name}", "prompt_len": len(prompt)}


@dataclass
class AgentPanel:
    agents: dict[str, MockAgent] = field(default_factory=dict)
    vendor_of: dict[str, str] = field(default_factory=dict)

    @classmethod
    def demo(cls) -> "AgentPanel":
        roles = {
            "operator": "human",
            "planner": "openai",
            "adversary": "xai",
            "implementer": "openai",
            "tester": "openai",
            "reviewer": "anthropic",
            "logger": "local",
            "local": "local",
        }
        agents = {name: MockAgent(name=name, vendor=v) for name, v in roles.items()}
        return cls(agents=agents, vendor_of={n: a.vendor for n, a in agents.items()})

    def health(self) -> dict[str, bool]:
        return {n: a.online for n, a in self.agents.items()}

    def resolve(self, step: StepDef) -> str:
        """Pick a healthy agent for the step, applying fallbacks + capabilities."""
        candidates = step.agent if isinstance(step.agent, list) else [step.agent]
        req = step.required_capability
        for name in candidates:
            picked = self._resolve_one(name, req)
            if picked:
                return picked
        # last resort
        if "local" in self.agents and self.agents["local"].online:
            return "local"
        raise RuntimeError(f"no healthy agent for step {step.number} {step.name}")

    def _resolve_one(self, name: str, req: Optional[str]) -> Optional[str]:
        if name == "operator":
            return "operator"
        h = self.health()
        if h.get(name, False):
            if req and req not in AGENT_CAPABILITIES.get(name, set()):
                pass
            else:
                return name
        fb = FALLBACK_TABLE.get(name)
        if fb and h.get(fb, False):
            if req and req not in AGENT_CAPABILITIES.get(fb, set()):
                return None
            return fb
        return None

    def run(self, agent_name: str, prompt: str, *, step: StepDef, task: dict[str, Any]) -> dict[str, Any]:
        agent = self.agents[agent_name]
        return agent.run(prompt, step=step, task=task)
