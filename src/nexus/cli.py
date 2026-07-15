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


def cmd_procure(args: argparse.Namespace) -> int:
    """Procurement intelligence engine + expert panel."""
    from . import procurement as proc

    if args.procure_cmd == "demo":
        out = Path(args.out) if args.out else Path(".nexus_state") / "procurement_demo"
        path = proc.run_demo(out)
        print(f"=== procurement demo ===")
        print(f"  report: {path}")
        print(f"  open:   less {path}")
        # print rank line
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines()[:12]:
            print(" ", line)
        return 0

    if args.procure_cmd == "persona":
        root = Path(__file__).resolve().parents[2]
        persona = root / "docs" / "agents" / "PROCUREMENT.md"
        print(persona.read_text(encoding="utf-8") if persona.exists() else "(missing persona)")
        return 0

    print("usage: nexus procure demo | persona")
    return 2


def cmd_arxiv(args: argparse.Namespace) -> int:
    from . import arxiv_client

    if args.arxiv_cmd == "search":
        try:
            papers = arxiv_client.search(args.query, max_results=args.max)
        except Exception as e:
            print(f"arXiv search failed: {e}")
            return 1
        if not papers:
            print("(no results)")
            return 0
        for p in papers:
            print(f"{p.arxiv_id}\t{p.published}\t{p.title}")
            print(f"  {p.abs_url}")
        return 0

    if args.arxiv_cmd == "get":
        try:
            p = arxiv_client.get_paper(args.arxiv_id)
        except Exception as e:
            print(f"arXiv get failed: {e}")
            return 1
        if not p:
            print("not found")
            return 1
        print(p.title)
        print("authors:", ", ".join(p.authors))
        print("abs:", p.abs_url)
        print("pdf:", p.pdf_url)
        print()
        print(p.summary[:2000])
        out = Path(args.out) if args.out else Path(".nexus_workspaces") / "research" / "manual"
        out.mkdir(parents=True, exist_ok=True)
        arxiv_client.save_abstract_md(p, out)
        arxiv_client.save_paper_json(p, out)
        if args.pdf:
            try:
                path = arxiv_client.download_pdf(p, out / "pdfs")
                print(f"pdf saved: {path}")
            except Exception as e:
                print(f"pdf download failed: {e}")
                return 1
        return 0

    print("usage: nexus arxiv search <query> | get <id> [--pdf]")
    return 2


def cmd_research(args: argparse.Namespace) -> int:
    from .github_job import ensure_panel_for_job
    from .research_job import ResearchJobRunner

    panel = None
    if not args.heuristic_only:
        try:
            panel = ensure_panel_for_job()
        except Exception:
            panel = None
    runner = ResearchJobRunner(panel=panel)
    job = runner.run(
        args.query,
        max_results=args.max,
        download_pdf=args.pdf,
        with_brief=not args.no_brief,
    )
    return 0 if job.status == "completed" else 1


def cmd_github(args: argparse.Namespace) -> int:
    """One-stop shop: community inbox / reply / auto, or repo repair job."""
    from . import github_community as gc

    sub = getattr(args, "github_cmd", None)

    # Back-compat: nexus github owner/repo → repair job
    if sub in (None, "do") or (isinstance(sub, str) and _looks_like_github(sub)):
        # When user typed: nexus github owner/repo  (subparser may capture as github_cmd)
        if sub and _looks_like_github(sub):
            args.repo = sub
        if not getattr(args, "repo", None):
            print(
                "usage:\n"
                "  nexus github inbox|reply|draft|auto|status   # community one-stop\n"
                "  nexus github do <owner/repo>                 # repair job\n"
                "  nexus do <owner/repo>                        # same job"
            )
            return 2
        return cmd_do(args)

    repo = getattr(args, "repo_flag", None) or getattr(args, "repo", None)

    if sub == "status":
        print("gh:", "yes" if gc.gh_available() else "no")
        try:
            r = gc.resolve_repo(repo)
            print("repo:", r)
        except gc.GhError as e:
            print("repo: (unresolved)", e)
            return 1
        return 0

    if sub == "inbox":
        try:
            items = gc.list_inbox(
                repo,
                limit=int(getattr(args, "limit", 30)),
                include_bot_replied=bool(getattr(args, "all", False)),
            )
        except gc.GhError as e:
            print(f"error: {e}")
            return 1
        print(f"=== GitHub inbox ({gc.resolve_repo(repo)}) ===")
        print(gc.format_inbox_table(items))
        print()
        print("reply:  nexus github reply <n> --body '…'")
        print("draft:  nexus github draft <n>")
        print("auto:   nexus github auto --dry-run")
        return 0

    if sub == "draft":
        try:
            item = gc.fetch_thread(repo, int(args.number))
        except gc.GhError as e:
            print(f"error: {e}")
            return 1
        panel = None
        if getattr(args, "llm", False):
            try:
                from .github_job import ensure_panel_for_job

                panel = ensure_panel_for_job()
            except Exception:
                panel = None
        text = gc.draft_reply(
            item,
            repo=repo,
            panel=panel,
            prefer_llm=bool(getattr(args, "llm", False)),
        )
        print(text)
        return 0

    if sub == "reply":
        body = getattr(args, "body", None)
        if not body and getattr(args, "stdin", False):
            body = sys.stdin.read()
        if not body:
            # auto-draft then post
            try:
                item = gc.fetch_thread(repo, int(args.number))
            except gc.GhError as e:
                print(f"error: {e}")
                return 1
            panel = None
            if getattr(args, "llm", False):
                try:
                    from .github_job import ensure_panel_for_job

                    panel = ensure_panel_for_job()
                except Exception:
                    panel = None
            body = gc.draft_reply(
                item,
                repo=repo,
                panel=panel,
                prefer_llm=bool(getattr(args, "llm", False)),
            )
        try:
            res = gc.post_comment(
                repo,
                int(args.number),
                body,
                dry_run=bool(getattr(args, "dry_run", False)),
            )
        except gc.GhError as e:
            print(f"error: {e}")
            return 1
        print(json.dumps(res, indent=2))
        return 0

    if sub == "auto":
        panel = None
        if getattr(args, "llm", False):
            try:
                from .github_job import ensure_panel_for_job

                panel = ensure_panel_for_job()
            except Exception:
                panel = None
        try:
            results = gc.auto_reply_open(
                repo,
                limit=int(getattr(args, "limit", 20)),
                dry_run=bool(getattr(args, "dry_run", False)),
                prefer_llm=bool(getattr(args, "llm", False)),
                panel=panel,
            )
        except gc.GhError as e:
            print(f"error: {e}")
            return 1
        if not results:
            print("(nothing to reply to)")
            return 0
        for r in results:
            print(
                f"#{r.get('number')} {r.get('kind')} — "
                f"{'DRY' if r.get('dry_run') else 'posted'} — {r.get('title', '')}"
            )
        return 0

    print(f"unknown github subcommand: {sub}")
    return 2


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
        "procure",
        "arxiv",
        "research",
        "-h",
        "--help",
    }

    # nexus https://github.com/owner/repo  →  nexus do …
    if raw and _looks_like_github(raw[0]):
        raw = ["do", *raw]
    # nexus github owner/repo  →  nexus github do owner/repo
    elif (
        len(raw) >= 2
        and raw[0] == "github"
        and _looks_like_github(raw[1])
        and raw[1] not in {"inbox", "reply", "draft", "auto", "status", "do"}
    ):
        raw = ["github", "do", *raw[1:]]
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

    # --- GitHub community one-stop shop ---
    gh = sub.add_parser(
        "github",
        help="community inbox / auto-reply, or repair job (see: github do)",
    )
    gh_sub = gh.add_subparsers(dest="github_cmd")

    gh_inbox = gh_sub.add_parser(
        "inbox",
        help="list open issues/PRs needing a first reply",
    )
    gh_inbox.add_argument(
        "--repo",
        dest="repo_flag",
        default=None,
        help="owner/repo (default: current gh repo or VincentMarquez/nexus-core)",
    )
    gh_inbox.add_argument("--limit", type=int, default=30)
    gh_inbox.add_argument(
        "--all",
        action="store_true",
        help="include threads that already have a bot reply",
    )
    gh_inbox.set_defaults(func=cmd_github)

    gh_draft = gh_sub.add_parser("draft", help="print a draft reply (no post)")
    gh_draft.add_argument("number", type=int, help="issue or PR number")
    gh_draft.add_argument("--repo", dest="repo_flag", default=None)
    gh_draft.add_argument(
        "--llm",
        action="store_true",
        help="prefer NEXUS bus LLM draft when available",
    )
    gh_draft.set_defaults(func=cmd_github)

    gh_reply = gh_sub.add_parser(
        "reply",
        help="post a comment (drafted automatically if --body omitted)",
    )
    gh_reply.add_argument("number", type=int, help="issue or PR number")
    gh_reply.add_argument("--repo", dest="repo_flag", default=None)
    gh_reply.add_argument("--body", default=None, help="comment markdown")
    gh_reply.add_argument(
        "--stdin",
        action="store_true",
        help="read body from stdin",
    )
    gh_reply.add_argument("--dry-run", action="store_true")
    gh_reply.add_argument(
        "--llm",
        action="store_true",
        help="prefer NEXUS bus LLM draft when body omitted",
    )
    gh_reply.set_defaults(func=cmd_github)

    gh_auto = gh_sub.add_parser(
        "auto",
        help="post first replies on open threads without a bot marker",
    )
    gh_auto.add_argument("--repo", dest="repo_flag", default=None)
    gh_auto.add_argument("--limit", type=int, default=20)
    gh_auto.add_argument("--dry-run", action="store_true")
    gh_auto.add_argument("--llm", action="store_true")
    gh_auto.set_defaults(func=cmd_github)

    gh_st = gh_sub.add_parser("status", help="show gh auth + target repo")
    gh_st.add_argument("--repo", dest="repo_flag", default=None)
    gh_st.set_defaults(func=cmd_github)

    # repair job still available under github do
    gh_do = gh_sub.add_parser(
        "do",
        help="same as: nexus do <github-url>",
    )
    gh_do.add_argument(
        "repo",
        help="GitHub URL or owner/repo",
    )
    gh_do.add_argument("--goal", "-g", default="")
    gh_do.add_argument("--resume", default=None)
    gh_do.add_argument("--fix-rounds", type=int, default=3)
    gh_do.add_argument("--no-start", action="store_true")
    gh_do.add_argument("--no-cli", action="store_true")
    gh_do.add_argument("--no-pull", action="store_true")
    gh_do.add_argument("--open", action="store_true")
    gh_do.add_argument("--heuristic-only", action="store_true")
    gh_do.set_defaults(func=cmd_github)

    # bare `nexus github` → help-ish via cmd_github
    gh.set_defaults(func=cmd_github, github_cmd=None)

    # --- procurement domain ---
    pr = sub.add_parser("procure", help="procurement intelligence engine + expert panel")
    pr_sub = pr.add_subparsers(dest="procure_cmd", required=True)
    pr_demo = pr_sub.add_parser("demo", help="run synthetic 3-supplier demo report")
    pr_demo.add_argument(
        "--out",
        default=None,
        help="output directory (default .nexus_state/procurement_demo)",
    )
    pr_demo.set_defaults(func=cmd_procure)
    pr_sub.add_parser("persona", help="print procurement agent system prompt").set_defaults(
        func=cmd_procure
    )

    # --- arxiv ---
    ax = sub.add_parser("arxiv", help="search / fetch arXiv papers (public API)")
    ax_sub = ax.add_subparsers(dest="arxiv_cmd", required=True)
    ax_s = ax_sub.add_parser("search", help="search arXiv")
    ax_s.add_argument("query", help='query (e.g. "multi agent orchestration" or all:transformer)')
    ax_s.add_argument("--max", type=int, default=8)
    ax_s.set_defaults(func=cmd_arxiv)
    ax_g = ax_sub.add_parser("get", help="fetch one paper by id")
    ax_g.add_argument("arxiv_id", help="e.g. 1706.03762 or arXiv:1706.03762")
    ax_g.add_argument("--pdf", action="store_true", help="also download PDF")
    ax_g.add_argument("--out", default=None, help="output directory")
    ax_g.set_defaults(func=cmd_arxiv)

    # --- research job ---
    rs = sub.add_parser(
        "research",
        help="arXiv research job: search → abstracts → brief → report",
    )
    rs.add_argument("query", help="topic or arXiv query string")
    rs.add_argument("--max", type=int, default=8)
    rs.add_argument("--pdf", action="store_true", help="download PDFs")
    rs.add_argument("--no-brief", action="store_true")
    rs.add_argument(
        "--heuristic-only",
        action="store_true",
        help="skip LLM brief (structured summary only)",
    )
    rs.set_defaults(func=cmd_research)

    args = ap.parse_args(raw)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
