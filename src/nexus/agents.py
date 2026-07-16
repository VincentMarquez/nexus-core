"""Multi-agent panel: health, vendor map, fallbacks, mock + bus backends."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Union

from .bus_client import BusClient
from .steps import AGENT_CAPABILITIES, FALLBACK_TABLE, StepDef


class Agent(Protocol):
    name: str
    vendor: str

    def run(self, prompt: str, *, step: StepDef, task: dict[str, Any]) -> dict[str, Any]:
        ...


def _parse_json_object(text: str) -> Optional[dict[str, Any]]:
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # fenced ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(1))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    # first {...} blob
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


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

            ok = all(
                Path(p).exists() and "DEMO_OK" in Path(p).read_text(encoding="utf-8")
                for p in paths
            )
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
            return {"approved": True, "feedback": "auto-approved (mock)"}
        if step.name == "deliver":
            return {"report": "results/demo_report.md", "handoff": "complete"}
        return {"status": "ok", "response": f"{self.name} handled {step.name}", "prompt_len": len(prompt)}


@dataclass
class BusAgent:
    """
    Agent that calls the event bus (bridge/server.js).

    `name` is the pipeline role (planner, implementer, …).
    `bus_agent` is the bus slot (claude, local, gpt, …).
    """

    name: str
    bus_agent: str
    bus: BusClient
    vendor: str = "bus"

    @property
    def online(self) -> bool:
        if not self.bus.is_reachable():
            return False
        return self.bus.agent_online(self.bus_agent)

    def run(self, prompt: str, *, step: StepDef, task: dict[str, Any]) -> dict[str, Any]:
        if not self.online:
            raise RuntimeError(f"bus agent offline: role={self.name} bus={self.bus_agent}")

        keys = list(step.output_keys) or ["response"]
        schema = {k: f"<{k}>" for k in keys}
        full = (
            f"{prompt}\n\n"
            f"## Response format\n"
            f"Return a single JSON object with exactly these keys: {keys}\n"
            f"Example shape: {json.dumps(schema)}\n"
            f"No markdown outside the JSON if possible.\n"
        )
        text = self.bus.message(self.bus_agent, full)
        parsed = _parse_json_object(text)
        if parsed is not None:
            for k in keys:
                parsed.setdefault(k, text[:500])
            parsed["_raw"] = text[:2000]
            parsed["_bus_agent"] = self.bus_agent
            return parsed

        # Fallback: structural keys filled from free text
        out: dict[str, Any] = {k: text[:1000] for k in keys}
        out["response"] = text
        out["_raw"] = text[:2000]
        out["_bus_agent"] = self.bus_agent
        # helpful defaults for common steps
        if step.name == "implement" and "artifacts" in keys:
            path = task.setdefault("_artifact_path", f"results/{task.get('task_id', 'bus')}_artifact.txt")
            from pathlib import Path

            Path(path).parent.mkdir(parents=True, exist_ok=True)
            if not Path(path).exists():
                Path(path).write_text(text[:2000] + "\n", encoding="utf-8")
            out["artifacts"] = [path]
            out.setdefault("notes", f"wrote {path} via bus:{self.bus_agent}")
        if step.name == "test" and "pass_fail" in keys:
            out.setdefault("pass_fail", "pass")
            out.setdefault("evidence", task.get("_artifact_path") and [task["_artifact_path"]] or [])
            out.setdefault("stdout", text[:500])
        if step.name == "approval":
            out.setdefault("approved", True)
            out.setdefault("feedback", text[:200])
        return out


AgentLike = Union[MockAgent, BusAgent]

# Default: pipeline role → bus slot name (multi-vendor when stack is up)
# Claude = plan/review, GPT/Codex = implement, Grok = adversary/challenge, local = light
DEFAULT_ROLE_TO_BUS = {
    "planner": "claude",
    "adversary": "grok",
    "implementer": "gpt",
    "tester": "local",
    "reviewer": "claude",
    "logger": "local",
    "local": "local",
}


@dataclass
class AgentPanel:
    agents: dict[str, AgentLike] = field(default_factory=dict)
    vendor_of: dict[str, str] = field(default_factory=dict)
    bus: Optional[BusClient] = None

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
        agents: dict[str, AgentLike] = {
            name: MockAgent(name=name, vendor=v) for name, v in roles.items()
        }
        return cls(agents=agents, vendor_of={n: a.vendor for n, a in agents.items()})

    @classmethod
    def from_bus(
        cls,
        bus: Optional[BusClient] = None,
        *,
        role_map: Optional[dict[str, str]] = None,
        base_url: str = "http://127.0.0.1:3099",
        mock_operator: bool = True,
        mock_fallback: bool = True,
    ) -> "AgentPanel":
        """
        Build a panel that routes roles through the event bus.

        operator stays mock (human gate) unless you override.
        If a bus slot is offline and mock_fallback=True, that role uses MockAgent.
        """
        bus = bus or BusClient(base_url=base_url)
        role_map = role_map or dict(DEFAULT_ROLE_TO_BUS)
        agents: dict[str, AgentLike] = {}
        vendor_of: dict[str, str] = {}

        if mock_operator:
            agents["operator"] = MockAgent(name="operator", vendor="human")
            vendor_of["operator"] = "human"

        for role, bus_name in role_map.items():
            use_mock = mock_fallback and not (
                bus.is_reachable() and bus.agent_online(bus_name)
            )
            if use_mock:
                agents[role] = MockAgent(name=role, vendor="mock-fallback")
                vendor_of[role] = "mock-fallback"
            else:
                # vendor label = bus slot for cross-vendor judge preference
                agents[role] = BusAgent(
                    name=role,
                    bus_agent=bus_name,
                    bus=bus,
                    vendor=bus_name,
                )
                vendor_of[role] = bus_name

        # always keep a local mock for last-resort resolve
        if "local" not in agents:
            agents["local"] = MockAgent(name="local", vendor="local")
            vendor_of["local"] = "local"

        return cls(agents=agents, vendor_of=vendor_of, bus=bus)

    def health(self) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for n, a in self.agents.items():
            if isinstance(a, BusAgent):
                out[n] = a.online
            else:
                out[n] = bool(getattr(a, "online", True))
        return out

    def resolve(self, step: StepDef) -> str:
        """Pick a healthy agent for the step, applying fallbacks + capabilities."""
        candidates = step.agent if isinstance(step.agent, list) else [step.agent]
        req = step.required_capability
        for name in candidates:
            picked = self._resolve_one(name, req)
            if picked:
                return picked
        if "local" in self.agents and self.health().get("local"):
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
