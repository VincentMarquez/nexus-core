#!/usr/bin/env python3
"""Full-time multi-vendor NEXUS: Claude + ChatGPT(Codex) + Grok + local Ollama.

Not Grok-only. Starts the bus with real CLI bridges and runs durable multi-agent
tasks in a loop (or once).

  # once
  PYTHONPATH=src python3 scripts/multi_vendor_live.py

  # keep going until stop file
  PYTHONPATH=src python3 scripts/multi_vendor_live.py --watch --interval 300

  touch .nexus_state/STOP_MULTI_VENDOR

Roles (default):
  planner/reviewer → Claude
  implementer      → GPT (Codex)
  adversary        → Grok 4.5
  tester/logger    → local Ollama
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
os.environ.setdefault("NEXUS_PROJECT_ROOT", str(ROOT))
os.environ.setdefault("NEXUS_GROK_MODEL", "grok-4.5")
os.environ.setdefault("NEXUS_OLLAMA_TOOLS", "1")
# CLI bridges need long timeouts for real Claude/Codex/Grok turns
os.environ.setdefault("NEXUS_CLI_TIMEOUT_S", "300")
os.environ.setdefault("NEXUS_GROK_BRIDGE_TURNS", "8")

from nexus import DurableEngine, Settings, Task  # noqa: E402
from nexus.agents import AgentPanel, DEFAULT_ROLE_TO_BUS  # noqa: E402
from nexus.bus_client import BusClient  # noqa: E402
from nexus.cli import cmd_start  # noqa: E402
import argparse as ap_mod  # noqa: E402

STOP = ROOT / ".nexus_state" / "STOP_MULTI_VENDOR"
PID = ROOT / ".nexus_state" / "multi_vendor.pid"
LOG = ROOT / ".nexus_state" / "multi_vendor_live.log"


def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _bus_port() -> int:
    meta = ROOT / ".nexus_state" / "runtime.json"
    if meta.is_file():
        try:
            return int(json.loads(meta.read_text()).get("bus_port") or 3099)
        except Exception:
            pass
    return int(os.environ.get("NEXUS_BUS_PORT") or 3099)


def ensure_stack() -> int:
    port = _bus_port()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            if r.status == 200:
                _log(f"bus already up on :{port}")
                return port
    except Exception:
        pass
    _log("starting NEXUS stack with real CLIs (claude, codex, grok, ollama)…")
    ns = ap_mod.Namespace(
        yes=True,
        model=None,
        no_cli=False,
        no_pull=True,
        no_smoke=False,
        no_open=True,
        no_platforms=False,
    )
    rc = cmd_start(ns)
    if rc != 0:
        _log(f"nexus start failed rc={rc}")
        return 0
    return _bus_port()


def bus_status(port: int) -> dict:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def smoke_agents(port: int, agents: list[str]) -> dict[str, str]:
    """Ping each vendor on the bus; return agent→snippet."""
    out: dict[str, str] = {}
    for agent in agents:
        body = json.dumps({
            "agent": agent,
            "prompt": (
                f"You are bus agent '{agent}'. Reply with exactly one line: "
                f"{agent.upper()}_ONLINE ready for multi-vendor NEXUS."
            ),
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/message",
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode())
            text = (
                data.get("response")
                or data.get("text")
                or data.get("content")
                or json.dumps(data)[:200]
            )
            out[agent] = str(text).strip()[:200]
            _log(f"  smoke {agent}: {out[agent][:120]}")
        except Exception as e:
            out[agent] = f"ERROR: {e}"
            _log(f"  smoke {agent}: ERROR {e}")
    return out


def workspace_handoff_demo() -> None:
    """Write multi-agent handoff messages via workspace chat files if available."""
    chat = ROOT / ".nexus" / "workspace" / "chat.jsonl"
    chat.parent.mkdir(parents=True, exist_ok=True)
    for agent, msg in (
        ("claude", "Claude: planning multi-vendor durable task"),
        ("gpt", "Codex/GPT: ready to implement artifacts"),
        ("grok", "Grok: ready to challenge plan and hard-grade"),
        ("local", "Ollama local: ready for test/log light turns"),
    ):
        entry = {
            "ts": time.time(),
            "agent": agent,
            "text": msg,
        }
        with chat.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    _log(f"workspace handoff log → {chat}")


def run_multi_vendor_task(port: int, cycle: int) -> dict:
    role_map = dict(DEFAULT_ROLE_TO_BUS)
    # force multi-vendor map
    role_map.update({
        "planner": "claude",
        "adversary": "grok",
        "implementer": "gpt",
        "tester": "local",
        "reviewer": "claude",
        "logger": "local",
    })
    base = f"http://127.0.0.1:{port}"
    bus = BusClient(base_url=base)
    if not bus.is_reachable():
        return {"ok": False, "error": f"bus not reachable {base}"}

    panel = AgentPanel.from_bus(
        bus,
        role_map=role_map,
        base_url=base,
        mock_fallback=True,  # fall back if a slot flakes mid-run
    )
    health = panel.health()
    _log(f"panel health: {health}")

    tid = f"multi-vendor-{int(time.time())}-c{cycle}"
    settings = Settings(autonomy=False, state_dir=ROOT / ".nexus_state")
    engine = DurableEngine(
        settings=settings,
        panel=panel,
        auto_approve=True,
        journal=True,
    )
    task = Task(
        task_id=tid,
        objective=(
            "Multi-vendor durable pipeline: Claude plans, Grok challenges, "
            "Codex/GPT implements a DEMO_OK artifact, local Ollama tests. "
            "Prove crash-safe multi-agent collaboration."
        ),
        success_criteria=["artifact contains DEMO_OK"],
        namespace="proj/multi_vendor",
        constraints=["multi-vendor", "claude+gpt+grok+local"],
    )
    _log(f"=== durable run {tid} ===")
    t0 = time.time()
    task = engine.run(task)
    elapsed = round(time.time() - t0, 1)

    steps = []
    for n, out in sorted(task.outputs.items()):
        steps.append({
            "step": n,
            "bus": out.get("_bus_agent"),
            "verdict": (out.get("_verdict") or {}).get("decision"),
            "keys": [k for k in out if not str(k).startswith("_")][:8],
        })
        _log(
            f"  step {n}: bus={out.get('_bus_agent')} "
            f"verdict={(out.get('_verdict') or {}).get('decision')}"
        )

    rep = {
        "ok": task.status.value == "completed",
        "task_id": tid,
        "status": task.status.value,
        "current_step": task.current_step,
        "elapsed_s": elapsed,
        "error": task.meta.get("error"),
        "steps": steps,
        "role_map": role_map,
        "panel_health": health,
    }
    outp = ROOT / ".nexus_state" / "multi_vendor_last.json"
    outp.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    _log(f"result status={task.status.value} elapsed={elapsed}s → {outp}")
    return rep


def watch(interval: float) -> int:
    STOP.parent.mkdir(parents=True, exist_ok=True)
    if STOP.is_file():
        STOP.unlink()
    PID.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    _log("=== MULTI-VENDOR LIVE WATCH (Claude + GPT/Codex + Grok + local) ===")
    _log(f"stop: touch {STOP}")
    port = ensure_stack()
    if not port:
        return 1
    st = bus_status(port)
    _log(f"bus agents: {json.dumps(st.get('agents') or st, default=str)[:500]}")
    smoke_agents(port, ["claude", "gpt", "grok", "local"])
    workspace_handoff_demo()
    n = 0
    try:
        while True:
            if STOP.is_file():
                _log("stop file — exiting")
                break
            n += 1
            _log(f"\n######## multi-vendor cycle {n} ########")
            try:
                run_multi_vendor_task(port, n)
            except Exception as e:
                _log(f"cycle error: {e}")
            if STOP.is_file():
                break
            _log(f"sleeping {interval}s…")
            end = time.time() + max(30.0, interval)
            while time.time() < end:
                if STOP.is_file():
                    _log("stop during sleep")
                    return 0
                time.sleep(min(5.0, end - time.time()))
    except KeyboardInterrupt:
        _log("Ctrl-C")
    finally:
        if PID.is_file():
            PID.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Multi-vendor NEXUS live (Claude+GPT+Grok)")
    p.add_argument("--watch", action="store_true", help="loop until STOP_MULTI_VENDOR")
    p.add_argument("--interval", type=float, default=300.0, help="seconds between cycles")
    p.add_argument("--once", action="store_true", help="single multi-vendor durable run")
    args = p.parse_args(argv)
    if args.watch:
        return watch(args.interval)
    port = ensure_stack()
    if not port:
        return 1
    smoke_agents(port, ["claude", "gpt", "grok", "local"])
    workspace_handoff_demo()
    rep = run_multi_vendor_task(port, 1)
    print(json.dumps(rep, indent=2, default=str)[:4000])
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
