#!/usr/bin/env python3
"""Run the durable engine using the event bus (Ollama / CLI bridges).

Prereqs:
  - cd bridge && npm start
  - ./bridges/ollama-http.sh local <model>   and/or mock-bridge / cli-bridge

No API keys in this script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexus import DurableEngine, Settings, Task
from nexus.agents import AgentPanel, DEFAULT_ROLE_TO_BUS
from nexus.bus_client import BusClient


def parse_map(s: str) -> dict[str, str]:
    out = dict(DEFAULT_ROLE_TO_BUS)
    if not s:
        return out
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        role, _, agent = part.partition("=")
        out[role.strip()] = agent.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="NEXUS engine over event bus")
    ap.add_argument("--base", default="http://127.0.0.1:3099")
    ap.add_argument("--task-id", default="bus-demo-1")
    ap.add_argument("--map", default="", help="role=bus_agent,... overrides")
    ap.add_argument("--no-mock-fallback", action="store_true")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    bus = BusClient(base_url=args.base)
    if not bus.is_reachable():
        print(f"Bus not reachable at {args.base}")
        print("  cd bridge && npm start")
        print("  ./bridges/ollama-http.sh local gemma2")
        return 1

    print("bus health:", bus.health())
    print("bus status:", bus.status())

    panel = AgentPanel.from_bus(
        bus,
        role_map=parse_map(args.map),
        mock_fallback=not args.no_mock_fallback,
    )
    print("panel health:", panel.health())

    settings = Settings(autonomy=False, state_dir=Path(".nexus_state"))
    engine = DurableEngine(settings=settings, panel=panel, auto_approve=True)

    if args.resume:
        task = engine.resume(args.task_id)
    else:
        task = Task(
            task_id=args.task_id,
            objective="Use the multi-agent bus to produce a tiny DEMO_OK artifact",
            success_criteria=["artifact contains DEMO_OK"],
            namespace="proj/demo",
        )
        # reset if completed
        p = settings.state_dir / "tasks" / f"{args.task_id}.json"
        if p.exists():
            old = engine.load(args.task_id)
            if old.status.value == "completed":
                p.unlink()
        task = engine.run(task)

    print("=== result ===")
    print(f"status: {task.status.value}  step: {task.current_step}/10")
    if task.meta.get("error"):
        print("error:", task.meta["error"])
    for n, out in sorted(task.outputs.items()):
        bus_a = out.get("_bus_agent")
        v = (out.get("_verdict") or {}).get("decision")
        print(f"  step {n}: bus={bus_a} verdict={v} keys={[k for k in out if not k.startswith('_')][:6]}")
    return 0 if task.status.value == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
