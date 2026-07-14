#!/usr/bin/env python3
"""NEXUS Core CLI — one-command local stack.

  nexus start          # detect hardware, bus, dashboard, local LLM
  nexus status
  nexus stop
  nexus doctor
  nexus demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .hardware import detect
from .runtime import RuntimeManager, shutil_which


def _print_hw(hw) -> None:
    print("=== Hardware / runtimes ===")
    print(f"  CPU:     {hw.cpu_count} cores  arch={hw.arch}  os={hw.system}")
    print(f"  RAM:     {hw.mem_available_gb:.1f} GB free / {hw.mem_total_gb:.1f} GB total")
    if hw.gpus:
        for g in hw.gpus:
            print(
                f"  GPU:     {g.get('name')}  "
                f"({g.get('backend')}, free~{g.get('vram_free_mb', 0):.0f} MB)"
            )
    else:
        print("  GPU:     (none detected)")
    print("  Tools:   " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in hw.tools.items()))
    if hw.ollama_models:
        print("  Ollama:  " + ", ".join(hw.ollama_models[:12]))
    else:
        print("  Ollama:  (no models listed yet)")
    if hw.recommended_model:
        print(f"  Pick:    {hw.recommended_model}")
    for n in hw.notes:
        print(f"  note:    {n}")
    print()


def cmd_doctor(_: argparse.Namespace) -> int:
    hw = detect()
    _print_hw(hw)
    rt = RuntimeManager()
    print("=== Runtime ===")
    print(json.dumps(rt.status(), indent=2))
    ok = hw.tools.get("node") and (hw.tools.get("ollama") or True)
    return 0 if hw.tools.get("node") else 1


def cmd_status(_: argparse.Namespace) -> int:
    rt = RuntimeManager()
    print(json.dumps(rt.status(), indent=2))
    return 0


def cmd_stop(_: argparse.Namespace) -> int:
    rt = RuntimeManager()
    stopped = rt.stop_all()
    print("stopped:", ", ".join(stopped) if stopped else "(nothing)")
    return 0


def _confirm(prompt: str, *, default: bool = False, yes: bool = False) -> bool:
    if yes:
        return default if default else True
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        ans = input(prompt + suffix).strip().lower()
    except EOFError:
        return default
    if not ans:
        return default
    return ans in {"y", "yes"}


def cmd_start(args: argparse.Namespace) -> int:
    rt = RuntimeManager()
    hw = detect()
    _print_hw(hw)

    if not hw.tools.get("node"):
        print("ERROR: Node.js is required for the dashboard/bus.")
        print("  Install Node 18+ then re-run: nexus start")
        return 1

    agents = ["local", "claude", "gpt", "gemini"]
    model = args.model or hw.recommended_model or "gemma2:2b"

    # --- Ollama ---
    ollama_ok = False
    if hw.tools.get("ollama"):
        print("→ ensuring Ollama is up…")
        ollama_ok = rt.ensure_ollama_serve()
        if ollama_ok:
            print("  ollama API: ok")
            # refresh models
            hw = detect()
            model = args.model or hw.recommended_model or model
            if model not in hw.ollama_models and not any(
                m.startswith(model.split(":")[0]) for m in hw.ollama_models
            ):
                if args.yes or _confirm(
                    f"Pull local model '{model}' now? (may take a while)",
                    default=True,
                    yes=args.yes,
                ):
                    print(f"→ ollama pull {model} (log: .nexus_state/logs/ollama-pull.log)")
                    if not rt.pull_model(model):
                        print("  pull failed — check .nexus_state/logs/ollama-pull.log")
                        # try an already-installed model
                        if hw.ollama_models:
                            model = hw.recommended_model or hw.ollama_models[0]
                            print(f"  falling back to installed: {model}")
                else:
                    if hw.ollama_models:
                        model = hw.recommended_model or [
                            m for m in hw.ollama_models if "embed" not in m.lower()
                        ][0]
                        print(f"  using installed model: {model}")
                    else:
                        print("  no model — local agent will use mock fallback")
                        ollama_ok = False
            else:
                # use best matching installed name
                if model not in hw.ollama_models:
                    for m in hw.ollama_models:
                        if m.startswith(model.split(":")[0]) and "embed" not in m.lower():
                            model = m
                            break
        else:
            print("  could not start ollama serve")
    else:
        print("→ Ollama not installed — starting mock local agent instead")
        print("  install: https://ollama.com  then re-run nexus start")

    # --- Bus (auto port if 3099 busy) ---
    print("→ starting event bus + dashboard…")
    rt.start_bus(agents)
    if not rt.wait_bus(20):
        print("ERROR: bus did not become healthy — see .nexus_state/logs/bus.log")
        return 1
    print(f"  bus:       http://127.0.0.1:{rt.bus_port}/health")
    print(f"  dashboard: http://127.0.0.1:{rt.bus_port}/dashboard")

    # --- Bridges ---
    if ollama_ok and model:
        print(f"→ local LLM bridge: agent=local model={model}")
        rt.start_ollama_bridge("local", model)
    else:
        print("→ mock bridge: local")
        rt.start_mock_bridge("local")

    # Always provide a mock claude so demos work offline
    print("→ mock bridge: claude (safe default)")
    rt.start_mock_bridge("claude")

    # Optional real CLIs — only if approved
    cli_enabled = []
    if args.with_cli or (
        not args.yes
        and (hw.tools.get("claude") or hw.tools.get("codex") or hw.tools.get("gemini"))
        and _confirm(
            "Enable real CLI bridges for installed tools? (claude/codex/gemini)",
            default=False,
            yes=False,
        )
    ):
        if hw.tools.get("claude"):
            # stop mock claude first
            rt.stop("bridge-claude")
            print("→ CLI bridge: claude")
            rt.start_cli_bridge("claude", ["claude", "--print"])
            cli_enabled.append("claude")
        if args.with_cli and hw.tools.get("codex"):
            print("→ CLI bridge: gpt (codex)")
            rt.start_cli_bridge("gpt", ["codex", "exec", "--skip-git-repo-check"])
            cli_enabled.append("gpt")
        if args.with_cli and hw.tools.get("gemini"):
            print("→ CLI bridge: gemini")
            rt.start_cli_bridge("gemini", ["gemini"])
            cli_enabled.append("gemini")
    elif args.with_cli:
        # non-interactive force
        if hw.tools.get("claude"):
            rt.stop("bridge-claude")
            rt.start_cli_bridge("claude", ["claude", "--print"])
            cli_enabled.append("claude")

    # Dashboard
    if not args.no_open:
        print("→ opening dashboard in browser…")
        rt.open_dashboard()

    # wait for local bridge online
    import time
    import urllib.request

    for _ in range(25):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{rt.bus_port}/api/status", timeout=2
            ) as r:
                st = json.loads(r.read().decode())
            local = next((a for a in st.get("agents") or [] if a.get("agent") == "local"), None)
            if local and local.get("status") in {"online", "busy"}:
                break
        except Exception:
            pass
        time.sleep(0.2)

    url = f"http://127.0.0.1:{rt.bus_port}/dashboard"
    print()
    print("=== NEXUS is up ===")
    print(f"  Dashboard:  {url}")
    print(f"  Bus API:    http://127.0.0.1:{rt.bus_port}/api/status")
    print(f"  Local LLM:  {'ollama:' + model if ollama_ok else 'mock'}")
    print(f"  CLI agents: {', '.join(cli_enabled) if cli_enabled else 'off (use: nexus start --with-cli)'}")
    print()
    print("Next:")
    print(f"  python examples/call_bus.py --base http://127.0.0.1:{rt.bus_port} --agent local --prompt 'Hello'")
    print(f"  NEXUS_BUS_PORT={rt.bus_port} python examples/run_with_bus.py --base http://127.0.0.1:{rt.bus_port}")
    print("  nexus demo")
    print("  nexus stop")
    print()
    print("Logs: .nexus_state/logs/")
    snap = {
        "hardware": hw.to_dict(),
        "runtime": rt.status(),
        "model": model,
        "cli": cli_enabled,
        "dashboard": url,
    }
    (rt.state_dir / "last_start.json").write_text(json_dump(snap), encoding="utf-8")
    return 0


def json_dump(obj) -> str:
    return json.dumps(obj, indent=2)


def cmd_demo(_: argparse.Namespace) -> int:
    import subprocess

    root = Path(__file__).resolve().parents[2]
    return subprocess.call(["bash", str(root / "scripts" / "demo.sh")], cwd=str(root))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="nexus",
        description="NEXUS Core — durable multi-agent stack on your machine",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start", help="auto-detect hardware, start bus+dashboard+local LLM")
    p.add_argument("--model", default=None, help="Ollama model name (default: auto)")
    p.add_argument("--yes", "-y", action="store_true", help="non-interactive defaults")
    p.add_argument("--with-cli", action="store_true", help="enable real CLI bridges when installed")
    p.add_argument("--no-open", action="store_true", help="do not open browser")
    p.set_defaults(func=cmd_start)

    sub.add_parser("stop", help="stop bus and bridges").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="show process status").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="detect hardware and tools").set_defaults(func=cmd_doctor)
    sub.add_parser("demo", help="crash→resume demo").set_defaults(func=cmd_demo)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
