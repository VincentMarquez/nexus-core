#!/usr/bin/env python3
"""NEXUS Core CLI — zero-config local stack.

  nexus              # same as: nexus start  (fully automatic)
  nexus start        # hardware, bus, dashboard, local LLM, agents if present
  nexus stop | status | doctor | demo | mcp
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

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
        return True
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        ans = input(prompt + suffix).strip().lower()
    except EOFError:
        return default
    if not ans:
        return default
    return ans in {"y", "yes"}


def _model_installed(model: str, models: list[str]) -> bool:
    if model in models:
        return True
    prefix = model.split(":")[0]
    return any(m.startswith(prefix) and "embed" not in m.lower() for m in models)


def _resolve_model_name(model: str, models: list[str]) -> str:
    if model in models:
        return model
    prefix = model.split(":")[0]
    for m in models:
        if m.startswith(prefix) and "embed" not in m.lower():
            return m
    return model


def enable_agent_bridges(
    rt: RuntimeManager,
    hw,
    *,
    use_cli: bool,
    ollama_ok: bool,
    model: str,
) -> dict[str, str]:
    """Start bridges for local + known agent slots.

    Returns mapping agent_name → backend description.
    Real CLIs are used when installed and use_cli=True; otherwise mock
    so the stack always has agents ready for demos / orchestration.
    """
    backends: dict[str, str] = {}

    # --- local LLM ---
    if ollama_ok and model:
        print(f"→ local LLM bridge: agent=local model={model}")
        rt.start_ollama_bridge("local", model)
        backends["local"] = f"ollama:{model}"
    else:
        print("→ mock bridge: local (no Ollama model yet)")
        rt.start_mock_bridge("local")
        backends["local"] = "mock"

    # Agent slots the bus expects
    # claude / gpt / gemini — real CLI when available and allowed
    cli_specs = [
        ("claude", "claude", ["claude", "--print"]),
        ("gpt", "codex", ["codex", "exec", "--skip-git-repo-check"]),
        ("gemini", "gemini", ["gemini"]),
    ]

    for agent, tool_key, cmd in cli_specs:
        if use_cli and hw.tools.get(tool_key):
            print(f"→ CLI bridge: {agent}  ({' '.join(cmd)})")
            # replace any previous mock
            rt.stop(f"bridge-{agent}")
            rt.start_cli_bridge(agent, cmd)
            backends[agent] = f"cli:{tool_key}"
        else:
            print(f"→ mock bridge: {agent}" + (" (CLI not installed)" if use_cli else " (--no-cli)"))
            rt.start_mock_bridge(agent)
            backends[agent] = "mock"

    return backends


def _bus_post_message(port: int, agent: str, prompt: str, timeout: float = 90.0) -> Optional[dict[str, Any]]:
    """Best-effort smoke call so the user sees an agent answer on first boot."""
    url = f"http://127.0.0.1:{port}/api/message"
    body = json.dumps({"agent": agent, "prompt": prompt}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _smoke_agent(port: int, backends: dict[str, str]) -> None:
    """Ping the best available agent so the dashboard shows activity."""
    # Prefer real backends over mock
    order = []
    for name, backend in backends.items():
        if backend.startswith("ollama:") or backend.startswith("cli:"):
            order.append(name)
    for name, backend in backends.items():
        if name not in order:
            order.append(name)
    if not order:
        return
    agent = order[0]
    print(f"→ first-contact smoke: agent={agent} ({backends[agent]})")
    result = _bus_post_message(
        port,
        agent,
        "Reply with exactly: NEXUS_READY. One short line only.",
        timeout=120.0,
    )
    if not result:
        print("  smoke: no response (bus message API may differ — stack is still up)")
        return
    if result.get("error") and not result.get("ok", True):
        print(f"  smoke: {result.get('error')}")
        return
    text = (
        result.get("response")
        or result.get("text")
        or result.get("content")
        or result.get("output")
        or json.dumps(result)[:200]
    )
    print(f"  smoke reply: {str(text).strip()[:240]}")


def cmd_start(args: argparse.Namespace) -> int:
    rt = RuntimeManager()
    hw = detect()
    _print_hw(hw)

    if not hw.tools.get("node"):
        print("ERROR: Node.js is required for the dashboard/bus.")
        print("  Install Node 18+ then re-run: ./run   or   nexus start")
        return 1

    agents = ["local", "claude", "gpt", "gemini"]
    model = args.model or hw.recommended_model or "gemma2:2b"
    yes = bool(args.yes) or not sys.stdin.isatty()
    # Auto mode: enable every installed CLI unless user opts out
    use_cli = not bool(getattr(args, "no_cli", False))
    do_smoke = not bool(getattr(args, "no_smoke", False))

    # --- Ollama ---
    ollama_ok = False
    if hw.tools.get("ollama"):
        print("→ ensuring Ollama is up…")
        ollama_ok = rt.ensure_ollama_serve()
        if ollama_ok:
            print("  ollama API: ok")
            hw = detect()
            model = args.model or hw.recommended_model or model
            if not _model_installed(model, hw.ollama_models):
                # Auto-pull by default (zero-config). Skip only with --no-pull.
                should_pull = not getattr(args, "no_pull", False)
                if not yes and should_pull:
                    should_pull = _confirm(
                        f"Pull local model '{model}' now? (may take a while)",
                        default=True,
                        yes=False,
                    )
                if should_pull and not getattr(args, "no_pull", False):
                    print(f"→ ollama pull {model} (log: .nexus_state/logs/ollama-pull.log)")
                    if not rt.pull_model(model):
                        print("  pull failed — check .nexus_state/logs/ollama-pull.log")
                        if hw.ollama_models:
                            model = hw.recommended_model or hw.ollama_models[0]
                            print(f"  falling back to installed: {model}")
                            ollama_ok = True
                        else:
                            print("  no model — local agent will use mock fallback")
                            ollama_ok = False
                    else:
                        hw = detect()
                        model = _resolve_model_name(model, hw.ollama_models)
                else:
                    if hw.ollama_models:
                        model = hw.recommended_model or next(
                            (m for m in hw.ollama_models if "embed" not in m.lower()),
                            hw.ollama_models[0],
                        )
                        print(f"  using installed model: {model}")
                    else:
                        print("  no model — local agent will use mock fallback")
                        ollama_ok = False
            else:
                model = _resolve_model_name(model, hw.ollama_models)
        else:
            print("  could not start ollama serve")
    else:
        print("→ Ollama not installed — starting mock local agent instead")
        print("  install: https://ollama.com  then re-run ./run for a real local LLM")

    # --- Bus ---
    print("→ starting event bus + dashboard…")
    rt.start_bus(agents)
    if not rt.wait_bus(20):
        print("ERROR: bus did not become healthy — see .nexus_state/logs/bus.log")
        return 1
    print(f"  bus:       http://127.0.0.1:{rt.bus_port}/health")
    print(f"  dashboard: http://127.0.0.1:{rt.bus_port}/dashboard")

    # --- Agents (auto) ---
    print("→ wiring agents (real tools when installed, mock otherwise)…")
    backends = enable_agent_bridges(
        rt, hw, use_cli=use_cli, ollama_ok=ollama_ok, model=model
    )

    # Dashboard
    if not args.no_open:
        print("→ opening dashboard in browser…")
        rt.open_dashboard()

    # wait for local bridge online
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

    if do_smoke:
        _smoke_agent(rt.bus_port, backends)

    real = [f"{k}={v}" for k, v in backends.items() if v != "mock"]
    mock = [k for k, v in backends.items() if v == "mock"]

    url = f"http://127.0.0.1:{rt.bus_port}/dashboard"
    print()
    print("=== NEXUS is up (automatic) ===")
    print(f"  Dashboard:  {url}")
    print(f"  Bus API:    http://127.0.0.1:{rt.bus_port}/api/status")
    print(f"  Agents ON:  {', '.join(real) if real else '(none — using mocks)'}")
    if mock:
        print(f"  Agents mock:{', '.join(mock)}  (install CLI / Ollama to upgrade)")
    print()
    print("You don't need to do anything else for the stack to run.")
    print("Orchestration will use real agents when present, mocks when not.")
    print()
    print("Useful:")
    print(f"  NEXUS_BUS_PORT={rt.bus_port} python examples/run_with_bus.py --base http://127.0.0.1:{rt.bus_port}")
    print("  nexus demo          # crash → resume proof")
    print("  nexus stop")
    print()
    print("Logs: .nexus_state/logs/")
    snap = {
        "hardware": hw.to_dict(),
        "runtime": rt.status(),
        "model": model,
        "backends": backends,
        "dashboard": url,
        "auto": True,
    }
    (rt.state_dir / "last_start.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
    return 0


def cmd_demo(_: argparse.Namespace) -> int:
    import subprocess

    root = Path(__file__).resolve().parents[2]
    return subprocess.call(["bash", str(root / "scripts" / "demo.sh")], cwd=str(root))


def cmd_mcp(args: argparse.Namespace) -> int:
    from . import mcp_server

    argv = []
    if args.http:
        argv.append("--http")
        argv.extend(["--host", args.host, "--port", str(args.port)])
    if args.project_root:
        argv.extend(["--project-root", args.project_root])
    return mcp_server.main(argv)


def _looks_like_github(s: str) -> bool:
    if not s or s.startswith("-"):
        return False
    if s.startswith(("https://github.com/", "http://github.com/", "git@github.com:")):
        return True
    if "github.com/" in s:
        return True
    # owner/repo slug (no spaces, single slash)
    if s.count("/") == 1 and " " not in s and not s.startswith("."):
        a, b = s.split("/", 1)
        if a and b and all(c.isalnum() or c in "._-" for c in a + b):
            return True
    return False


def cmd_do(args: argparse.Namespace) -> int:
    """Paste a GitHub URL → clone, install, run checks, fix with agents."""
    from .github_job import GithubJobRunner, ensure_panel_for_job
    from .runtime import RuntimeManager

    # Bring stack up so real agents can help (unless user opts out)
    if not getattr(args, "no_start", False):
        rt = RuntimeManager()
        if not rt.bus_healthy():
            print("→ stack not running — starting automatically (agents will help)…")
            start_args = argparse.Namespace(
                model=None,
                yes=True,
                with_cli=True,
                no_cli=bool(getattr(args, "no_cli", False)),
                no_pull=bool(getattr(args, "no_pull", False)),
                no_smoke=True,
                no_open=bool(getattr(args, "no_open", True)),
            )
            # default no browser during do unless --open
            if getattr(args, "open", False):
                start_args.no_open = False
            else:
                start_args.no_open = True
            rc = cmd_start(start_args)
            if rc != 0:
                print("  warning: stack start failed — continuing with heuristics/mocks")

    panel = None if getattr(args, "heuristic_only", False) else ensure_panel_for_job()
    runner = GithubJobRunner(panel=panel)
    job = runner.run(
        args.repo,
        goal=args.goal or "",
        resume_id=args.resume,
        max_fix_rounds=int(args.fix_rounds),
    )
    return 0 if job.status == "completed" else 1


def main(argv: Optional[list[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    known = {
        "start",
        "stop",
        "status",
        "doctor",
        "demo",
        "mcp",
        "do",
        "github",
        "-h",
        "--help",
    }

    # nexus https://github.com/owner/repo  →  nexus do …
    if raw and _looks_like_github(raw[0]):
        raw = ["do", *raw]
    elif not raw or raw[0] not in known:
        if raw and raw[0] in known:
            pass
        else:
            # bare flags → start; anything else unknown still start
            raw = ["start", "--yes", *raw]

    ap = argparse.ArgumentParser(
        prog="nexus",
        description=(
            "NEXUS Core — auto multi-agent stack. "
            "Paste a GitHub URL to clone, run, and fix a project."
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "start",
        help="auto-detect hardware, start bus+dashboard+local LLM+agents",
    )
    p.add_argument("--model", default=None, help="Ollama model name (default: auto)")
    p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="non-interactive (default when stdin is not a TTY, or via ./run)",
    )
    p.add_argument(
        "--with-cli",
        action="store_true",
        help="(default) enable real CLI bridges when installed",
    )
    p.add_argument(
        "--no-cli",
        action="store_true",
        help="do not enable real CLI agents (mock only for claude/gpt/gemini)",
    )
    p.add_argument(
        "--no-pull",
        action="store_true",
        help="do not auto-pull an Ollama model",
    )
    p.add_argument(
        "--no-smoke",
        action="store_true",
        help="skip first-contact agent smoke message",
    )
    p.add_argument("--no-open", action="store_true", help="do not open browser")
    p.set_defaults(func=cmd_start)

    sub.add_parser("stop", help="stop bus and bridges").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="show process status").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="detect hardware and tools").set_defaults(func=cmd_doctor)
    sub.add_parser("demo", help="crash→resume demo").set_defaults(func=cmd_demo)

    pm = sub.add_parser("mcp", help="run Workspace MCP server (stdio or --http)")
    pm.add_argument("--http", action="store_true", help="HTTP tools API instead of stdio")
    pm.add_argument("--host", default="127.0.0.1")
    pm.add_argument("--port", type=int, default=8765)
    pm.add_argument("--project-root", default=None)
    pm.set_defaults(func=cmd_mcp)

    def _add_do_parser(name: str, help_text: str):
        d = sub.add_parser(name, help=help_text)
        d.add_argument(
            "repo",
            help="GitHub URL or owner/repo (e.g. https://github.com/psf/requests)",
        )
        d.add_argument(
            "--goal",
            "-g",
            default="",
            help="what you want (default: install, run checks, fix until green)",
        )
        d.add_argument("--resume", default=None, help="resume job id")
        d.add_argument(
            "--fix-rounds",
            type=int,
            default=3,
            help="max agent/heuristic fix iterations (default 3)",
        )
        d.add_argument(
            "--no-start",
            action="store_true",
            help="do not auto-start the NEXUS stack",
        )
        d.add_argument("--no-cli", action="store_true", help="start stack without CLI agents")
        d.add_argument("--no-pull", action="store_true", help="do not pull Ollama models on start")
        d.add_argument(
            "--open",
            action="store_true",
            help="open dashboard browser when auto-starting",
        )
        d.add_argument(
            "--heuristic-only",
            action="store_true",
            help="skip LLM agents; clone/install/check with rules only",
        )
        d.set_defaults(func=cmd_do)
        return d

    _add_do_parser(
        "do",
        "GitHub URL → clone, install, run checks, fix with agents",
    )
    _add_do_parser(
        "github",
        "alias for: nexus do <github-url>",
    )

    args = ap.parse_args(raw)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
