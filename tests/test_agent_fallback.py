"""Agent panel must not kill the job when a bus vendor times out."""

from __future__ import annotations

from nexus.agents import AgentPanel, BusAgent, MockAgent
from nexus.steps import StepDef


class _BoomAgent:
    name = "planner"
    vendor = "boom"

    def run(self, prompt, *, step, task):
        raise RuntimeError("HTTP Error 504: Gateway Timeout")


def test_panel_falls_back_to_mock_on_vendor_timeout():
    panel = AgentPanel(
        agents={
            "planner": _BoomAgent(),  # type: ignore[dict-item]
            "local": MockAgent(name="local", vendor="local"),
        },
        vendor_of={"planner": "boom", "local": "local"},
    )
    step = StepDef(2, "plan", "plan", "planner", output_keys=("approach", "risks", "estimated_steps"))
    out = panel.run("planner", "plan something", step=step, task={"task_id": "t1"})
    assert "approach" in out or "response" in out or out.get("_fallback_from") == "planner"
    assert out.get("_fallback_from") == "planner"
    assert "504" in (out.get("_fallback_error") or "")
