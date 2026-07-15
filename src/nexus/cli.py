#!/usr/bin/env python3
"""NEXUS Core CLI — zero-config local stack.

  nexus              # same as: nexus start  (fully automatic)
  nexus start        # hardware, bus, dashboard, local LLM, agents if present
  nexus stop | status | doctor | demo | mcp
"""

from __future__ import annotations

import argparse
import json
import os
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
    # Local Ollama bridge uses MCP tool loop by default (same tools as Grok CLI)
    os.environ.setdefault("NEXUS_OLLAMA_TOOLS", "1")
    os.environ.setdefault("NEXUS_PROJECT_ROOT", str(Path.cwd().resolve()))
    backends = enable_agent_bridges(
        rt, hw, use_cli=use_cli, ollama_ok=ollama_ok, model=model
    )

    # Soft platform mesh tip (non-fatal)
    if not getattr(args, "no_platforms", False):
        try:
            from . import platforms as plat

            d = plat.doctor(Path.cwd())
            if not d.get("ok"):
                print("→ platforms: mesh incomplete (Grok/Cursor MCP)")
                for iss in (d.get("issues") or [])[:4]:
                    print(f"   · {iss}")
                print("   fix: nexus platforms connect --force")
            else:
                print("→ platforms: Grok/Cursor MCP mesh looks OK")
        except Exception:
            pass

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


def cmd_demo(args: argparse.Namespace) -> int:
    import subprocess

    root = Path(__file__).resolve().parents[2]
    # First-apply slice: grade → durable phase FSM → decision audit
    slice_name = getattr(args, "slice", None) or getattr(args, "demo_slice", None)
    if slice_name in {"grade-loop", "grade_loop"}:
        from . import grade_artifact as ga

        workdir = Path(getattr(args, "workdir", None) or root).resolve()
        run_id = getattr(args, "run_id", None)
        repo = getattr(args, "repo", None)
        if run_id:
            gl = workdir / ".nexus_workspaces" / "grade_loop" / str(run_id) / "checkpoint.json"
            if gl.is_file():
                run = ga.resume_ordered_loop(workdir, str(run_id))
            else:
                run = ga.start_ordered_loop(
                    workdir, repo=repo, run_id=str(run_id), dry_run=True
                )
        else:
            run = ga.start_ordered_loop(workdir, repo=repo, dry_run=True)
        # Prove crash/resume: grade_read → save → reload → apply_plan
        run.run_grade_read()
        mid = ga.resume_ordered_loop(workdir, run.run_id)
        assert mid.next_agent == "apply_plan"
        status = mid.run_to_done()
        print(ga.format_board(status))
        return 0 if status.get("status") == "success" else 1

    if slice_name == "self-improve-slice" or getattr(args, "self_improve_slice", False):
        from . import improve_apply as ia

        workdir = Path(getattr(args, "workdir", None) or root).resolve()
        fixture = getattr(args, "fixture", None)
        if fixture:
            fixture = str(Path(fixture))
        status = ia.run_demo(
            workdir,
            fixture=fixture,
            run_id=getattr(args, "run_id", None),
            show_audit=bool(getattr(args, "show_audit", True)),
            dry_run=not bool(getattr(args, "no_dry_run", False)),
        )
        print(status.get("demo_text") or ia.format_demo(status))
        return 0 if status.get("phase") == "done" else 1

    if getattr(args, "all", False) or getattr(args, "showcase", False):
        script = root / "scripts" / "demo_showcase.sh"
        cmd = ["bash", str(script)]
        if getattr(args, "quick", False):
            cmd.append("--quick")
        return subprocess.call(cmd, cwd=str(root))
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
                "  nexus github inbox|reply|loop|watch|init|search|scout|improve|status\n"
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
        print("loop:   nexus github loop <n>     # run tests + post results")
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

    if sub == "loop":
        # response → run tests → post results (same as Actions response_loop)
        workdir = Path(getattr(args, "workdir", None) or Path.cwd())
        try:
            if getattr(args, "number", None) is not None:
                item = None
                try:
                    item = gc.fetch_thread(repo, int(args.number))
                except Exception:
                    item = None
                res = gc.run_and_post_loop(
                    repo,
                    int(args.number),
                    workdir=workdir,
                    kind=(item.kind if item else "issue"),
                    triggered_by=os.environ.get("USER", "local"),
                    dry_run=bool(getattr(args, "dry_run", False)),
                    force=bool(getattr(args, "force", False)),
                )
                print(json.dumps(res, indent=2))
                if res.get("skipped"):
                    return 0
                return 0 if res.get("ok_checks", True) or res.get("dry_run") else 1
            print("usage: nexus github loop <number> [--dry-run] [--force] [--workdir PATH]")
            return 2
        except gc.GhError as e:
            print(f"error: {e}")
            return 1

    if sub == "init":
        from . import github_autonomy as ga

        path = Path(getattr(args, "path", None) or Path.cwd())
        try:
            res = ga.bootstrap_personal_repo(
                path,
                force=bool(getattr(args, "force", False)),
            )
        except Exception as e:
            print(f"error: {e}")
            return 1
        print(json.dumps(res, indent=2))
        print("\nNext:")
        for line in res.get("next") or []:
            print(" ", line)
        return 0

    if sub == "watch":
        from . import github_autonomy as ga

        workdir = Path(getattr(args, "workdir", None) or Path.cwd())
        kwargs = dict(
            workdir=workdir,
            autonomous=bool(getattr(args, "autonomous", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            arxiv_query=getattr(args, "arxiv", None) or None,
            arxiv_every_s=float(getattr(args, "arxiv_every", 86400) or 86400),
            scout_query=getattr(args, "scout", None) or None,
            scout_every_s=float(getattr(args, "scout_every", 43200) or 43200),
            apply_improve=bool(getattr(args, "apply", False)),
        )
        if getattr(args, "once", False):
            res = ga.watch_once(repo, **kwargs)
            print(json.dumps(res, indent=2))
            return 0
        return ga.watch_forever(
            repo,
            interval_s=float(getattr(args, "interval", 120) or 120),
            max_cycles=int(getattr(args, "max_cycles", 0) or 0),
            **kwargs,
        )

    if sub == "improve":
        from . import github_autonomy as ga

        q = getattr(args, "arxiv", None) or getattr(args, "query", None)
        scout_q = getattr(args, "scout", None)
        if not q and not scout_q:
            print(
                "usage: nexus github improve --arxiv \"topic\" [--scout \"topic\"] "
                "[--repo YOU/REPO] [--apply]"
            )
            return 2
        workdir = Path(getattr(args, "workdir", None) or Path.cwd())
        try:
            if q:
                res = ga.improve_from_arxiv(
                    q,
                    repo=repo,
                    workdir=workdir,
                    max_results=int(getattr(args, "max", 6) or 6),
                    apply=bool(getattr(args, "apply", False)),
                    dry_run=bool(getattr(args, "dry_run", False)),
                    download_pdf=bool(getattr(args, "pdf", False)),
                    post_issue=not bool(getattr(args, "no_issue", False)),
                    also_scout=bool(scout_q) or bool(getattr(args, "with_scout", False)),
                    scout_query=scout_q,
                )
            else:
                res = ga.scout_other_repos(
                    scout_q,
                    repo=repo,
                    workdir=workdir,
                    limit=int(getattr(args, "max", 8) or 8),
                    deep=not bool(getattr(args, "shallow", False)),
                    connect=not bool(getattr(args, "no_connect", False)),
                    prove=not bool(getattr(args, "no_prove", False)),
                    post_issue=not bool(getattr(args, "no_issue", False)),
                    dry_run=bool(getattr(args, "dry_run", False)),
                    apply=bool(getattr(args, "apply", False)),
                )
        except Exception as e:
            print(f"error: {e}")
            return 1
        print(json.dumps(res, indent=2))
        if "research_status" in res:
            return 0 if res.get("research_status") != "failed" else 1
        return 0

    if sub == "search":
        from . import github_autonomy as ga

        q = getattr(args, "query", None) or getattr(args, "q", None)
        if not q:
            print('usage: nexus github search "multi agent durable" [--limit 10]')
            return 2
        try:
            hits = ga.search_github_repos(
                q,
                limit=int(getattr(args, "limit", 10) or 10),
                language=getattr(args, "language", None) or None,
            )
        except Exception as e:
            print(f"error: {e}")
            return 1
        if not hits:
            print("(no repos found)")
            return 0
        print(f"{'STARS':>6}  {'LANG':<10}  REPO")
        print("-" * 72)
        for h in hits:
            print(f"{h.stars:>6}  {(h.language or '-')[:10]:<10}  {h.full_name}")
            if h.description:
                print(f"        {h.description[:90]}")
            print(f"        {h.url}")
        return 0

    if sub == "scout":
        from . import github_autonomy as ga

        q = getattr(args, "query", None)
        if not q:
            print(
                'usage: nexus github scout "topic" [--connect] [--prove] '
                "[--repo YOU/REPO] [--apply]"
            )
            return 2
        workdir = Path(getattr(args, "workdir", None) or Path.cwd())
        connect = not bool(getattr(args, "no_connect", False))
        if getattr(args, "connect", False):
            connect = True
        prove = connect and not bool(getattr(args, "no_prove", False))
        try:
            res = ga.scout_other_repos(
                q,
                repo=repo,
                workdir=workdir,
                limit=int(getattr(args, "limit", 8) or 8),
                language=getattr(args, "language", None) or None,
                deep=not bool(getattr(args, "shallow", False)),
                connect=connect,
                prove=prove,
                pull=not bool(getattr(args, "no_pull", False)),
                run_checks=not bool(getattr(args, "structure_only", False)),
                post_issue=bool(getattr(args, "issue", False)),
                dry_run=bool(getattr(args, "dry_run", False)),
                apply=bool(getattr(args, "apply", False)),
            )
        except Exception as e:
            print(f"error: {e}")
            return 1
        print(json.dumps(res, indent=2))
        return 0

    if sub == "connect":
        from . import github_autonomy as ga

        slug = getattr(args, "slug", None)
        if not slug:
            print("usage: nexus github connect owner/repo [--prove] [--workdir PATH]")
            return 2
        workdir = Path(getattr(args, "workdir", None) or Path.cwd())
        try:
            res = ga.connect_and_prove(
                slug,
                workdir=workdir,
                pull=not bool(getattr(args, "no_pull", False)),
                prove=not bool(getattr(args, "no_prove", False)),
                run_checks=not bool(getattr(args, "structure_only", False)),
            )
        except Exception as e:
            print(f"error: {e}")
            return 1
        print(json.dumps(res, indent=2))
        ok = (res.get("connect") or {}).get("ok")
        return 0 if ok else 1


    if sub == "mine":
        from . import repo_mine as rm

        msub = getattr(args, "mine_cmd", None) or "run"
        workdir = Path(getattr(args, "workdir", None) or Path.cwd())
        try:
            if msub == "fetch":
                res = rm.step_fetch(
                    workdir,
                    query=getattr(args, "query", None) or "multi agent",
                    count=int(getattr(args, "count", 8) or 8),
                    language=getattr(args, "language", None),
                    max_stars=getattr(args, "max_stars", 500),
                )
            elif msub == "evaluate":
                grader = getattr(args, "grader", None) or "auto"
                if getattr(args, "heuristic_only", False):
                    grader = "heuristic"
                res = rm.step_evaluate(
                    workdir,
                    limit=getattr(args, "limit", 10),
                    use_ollama=not bool(getattr(args, "heuristic_only", False)),
                    ollama_model=getattr(args, "model", None),
                    grader=grader,
                )
            elif msub == "use":
                res = rm.step_use(
                    workdir,
                    min_score=float(getattr(args, "min_score", 12) or 12),
                    limit=int(getattr(args, "limit", 5) or 5),
                    prove=not bool(getattr(args, "no_prove", False)),
                    structure_only=bool(getattr(args, "structure_only", False)),
                )
            elif msub == "list":
                conn = rm.connect(workdir)
                rows = rm.list_entries(
                    conn,
                    min_score=float(getattr(args, "min_score", 0) or 0),
                    only_used=bool(getattr(args, "used", False)),
                    limit=int(getattr(args, "limit", 30) or 30),
                )
                conn.close()
                res = {"step": "list", "count": len(rows), "entries": rows}
            elif msub in ("improve-ours", "improve_ours"):
                res = rm.step_improve_ours(
                    workdir,
                    min_score=float(getattr(args, "min_score", 12) or 12),
                    limit=int(getattr(args, "limit", 3) or 3),
                    apply=bool(getattr(args, "apply", False)),
                    our_repo=getattr(args, "repo_flag", None) or getattr(args, "repo", None),
                    dry_run=bool(getattr(args, "dry_run", False)),
                    worker=getattr(args, "worker", None) or "auto",
                )
            elif msub == "run":
                grader = getattr(args, "grader", None) or "auto"
                if getattr(args, "heuristic_only", False):
                    grader = "heuristic"
                res = rm.run_pipeline(
                    workdir,
                    query=getattr(args, "query", None) or "multi agent durable",
                    fetch_count=int(getattr(args, "count", 6) or 6),
                    language=getattr(args, "language", None) or "Python",
                    max_stars=getattr(args, "max_stars", 500),
                    eval_limit=int(getattr(args, "limit", 6) or 6),
                    min_score=float(getattr(args, "min_score", 12) or 12),
                    use_limit=int(getattr(args, "use_limit", 4) or 4),
                    use_ollama=not bool(getattr(args, "heuristic_only", False)),
                    prove=not bool(getattr(args, "no_prove", False)),
                    improve=bool(getattr(args, "improve", False)),
                    apply_improve=bool(getattr(args, "apply", False)),
                    our_repo=getattr(args, "repo_flag", None),
                    grader=grader,
                    worker=getattr(args, "worker", None) or "auto",
                )
            else:
                print("usage: nexus github mine fetch|evaluate|use|list|run|improve-ours")
                return 2
        except Exception as e:
            print(f"error: {e}")
            return 1
        print(json.dumps(res, indent=2, default=str))
        return 0

    print(f"unknown github subcommand: {sub}")
    return 2


def cmd_platforms(args: argparse.Namespace) -> int:
    """Detect and auto-connect Grok CLI / Cursor / Claude / local LLM tool mesh."""
    from . import platforms as plat

    sub = getattr(args, "platforms_cmd", None) or "status"
    root = Path(getattr(args, "path", None) or Path.cwd()).resolve()

    if sub == "status":
        plats = plat.detect_platforms(project_root=root)
        print("=== NEXUS multi-platform mesh ===")
        print(f"project: {root}")
        print(plat.format_status_table(plats))
        print()
        flow = plat.agent_flow_map()
        print("Shared tools:", ", ".join(flow["shared_tools"]))
        print("Handoff:", flow["handoff"])
        print("Rule:", flow["rule"])
        print()
        print("connect:  nexus platforms connect")
        print("start:    nexus start -y   # local LLM + CLI agents on bus")
        return 0

    if sub == "connect":
        res = plat.connect_all(
            root,
            grok=not bool(getattr(args, "no_grok", False)),
            cursor=not bool(getattr(args, "no_cursor", False)),
            claude=not bool(getattr(args, "no_claude", False)),
            local_model=not bool(getattr(args, "no_local_model", False)),
            force=bool(getattr(args, "force", False)),
            ollama_model=getattr(args, "model", None),
        )
        print(json.dumps(res, indent=2))
        if getattr(args, "start", False):
            print("→ starting NEXUS stack so local LLM joins the bus…")
            start_args = argparse.Namespace(
                model=getattr(args, "model", None),
                yes=True,
                with_cli=True,
                no_cli=False,
                no_pull=False,
                no_smoke=True,
                no_open=True,
            )
            return cmd_start(start_args)
        print("\nNext:")
        for line in res.get("next") or []:
            print(" ", line)
        return 0 if all(r.get("ok", True) for r in res.get("results") or []) else 1

    if sub == "flow":
        print(json.dumps(plat.agent_flow_map(), indent=2))
        return 0

    if sub == "doctor":
        res = plat.doctor(root, fix=bool(getattr(args, "fix", False)))
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    print("usage: nexus platforms status|connect|flow|doctor")
    return 2


def cmd_heartbeat(args: argparse.Namespace) -> int:
    """Cloud dead-man switch: ping Healthchecks / custom URL; cron-friendly."""
    from . import heartbeat as hb

    root = Path(getattr(args, "path", None) or Path.cwd()).resolve()
    sub = getattr(args, "heartbeat_cmd", None) or "once"

    if sub == "init":
        url = getattr(args, "url", None) or ""
        if not url:
            print("usage: nexus heartbeat init --url https://hc-ping.com/UUID")
            return 2
        p = hb.init_config(
            url,
            root,
            interval_s=int(getattr(args, "interval", 300) or 300),
            host_id=getattr(args, "host_id", "") or "",
            status_url=getattr(args, "status_url", "") or "",
            notify_webhook=getattr(args, "webhook", "") or "",
        )
        print(f"wrote {p}")
        print(hb.install_instructions(root))
        return 0

    if sub == "once":
        res = hb.beat_once(root, dry_run=bool(getattr(args, "dry_run", False)))
        print(json.dumps(res, indent=2))
        ping_ok = (res.get("ping") or {}).get("ok")
        # offline with no URL is not a hard fail for local probe-only
        if (res.get("ping") or {}).get("skipped"):
            return 0 if (res.get("network") or {}).get("online") else 1
        return 0 if ping_ok else 1

    if sub == "watch":
        return hb.watch(
            root,
            interval_s=float(getattr(args, "interval", 0) or 0) or None,
            max_beats=int(getattr(args, "max_beats", 0) or 0),
        )

    if sub == "status":
        cfg = hb.load_config(root)
        st = hb.read_local_state(root)
        print(json.dumps({
            "config": {
                "ping_url_set": bool(cfg.ping_url),
                "host_id": cfg.host_id,
                "interval_s": cfg.interval_s,
                "status_url_set": bool(cfg.status_url),
                "webhook_set": bool(cfg.notify_webhook),
            },
            "last": st,
            "network": hb.probe_network(),
        }, indent=2))
        return 0

    if sub == "install-cron":
        print(hb.install_instructions(root))
        print()
        print("# crontab line:")
        print(hb.cron_line(
            project_root=root,
            interval_min=int(getattr(args, "every", 5) or 5),
        ))
        return 0

    print("usage: nexus heartbeat init|once|watch|status|install-cron")
    return 2


def cmd_recovery(args: argparse.Namespace) -> int:
    """Opt-in network/WiFi recovery; reboot only with double gate."""
    from . import recovery as rec

    sub = getattr(args, "recovery_cmd", None) or "status"

    if sub == "status":
        print(json.dumps(rec.status(), indent=2))
        return 0

    if sub == "network":
        r = rec.network_diagnose()
        print(json.dumps(r.to_dict(), indent=2))
        return 0 if r.ok else 1

    if sub == "wifi":
        r = rec.wifi_recover(
            allow_reconnect=bool(getattr(args, "allow_reconnect", False)),
            connection=getattr(args, "connection", None) or None,
        )
        print(json.dumps(r.to_dict(), indent=2))
        return 0 if r.ok else 1

    if sub == "reboot":
        r = rec.reboot_machine(allow_reboot=bool(getattr(args, "allow_reboot", False)))
        print(json.dumps(r.to_dict(), indent=2))
        return 0 if r.ok else 1

    if sub == "auto":
        r = rec.auto_recover(
            allow_reconnect=bool(getattr(args, "allow_reconnect", False)),
            allow_reboot=bool(getattr(args, "allow_reboot", False)),
        )
        print(json.dumps(r.to_dict(), indent=2))
        return 0 if r.ok else 1

    print("usage: nexus recovery status|network|wifi|reboot|auto")
    return 2


def cmd_schedule(args: argparse.Namespace) -> int:
    """Print cron lines so heartbeat/mine/MCP can run unattended; ChatGPT/Claude attach via MCP."""
    from . import schedule_install as si

    root = Path(getattr(args, "path", None) or Path.cwd()).resolve()
    text = si.install_bundle(
        root,
        mine_query=getattr(args, "query", None) or "multi agent durable",
        heartbeat=not bool(getattr(args, "no_heartbeat", False)),
        mine=not bool(getattr(args, "no_mine", False)),
        mcp_http=bool(getattr(args, "mcp_http", False)),
    )
    print(text)
    print("# Docs: docs/SCHEDULE_AGENTS.md")
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    """Token budget / throttle controls."""
    from . import usage as um

    root = Path(getattr(args, "path", None) or Path.cwd()).resolve()
    sub = getattr(args, "usage_cmd", None) or "status"
    if sub == "status":
        print(json.dumps(um.status(root), indent=2))
        return 0
    if sub == "set":
        b = um.load_budget(root)
        if getattr(args, "off", False):
            b.enabled = False
        if getattr(args, "on", False):
            b.enabled = True
        if getattr(args, "daily", None) is not None:
            b.daily_tokens = int(args.daily)
        if getattr(args, "monthly", None) is not None:
            b.monthly_tokens = int(args.monthly)
        if getattr(args, "per_call", None) is not None:
            b.per_call_max = int(args.per_call)
        if getattr(args, "soft", False):
            b.hard_limit = False
        if getattr(args, "hard", False):
            b.hard_limit = True
        p = um.save_budget(b, root)
        print(json.dumps({"saved": str(p), "budget": b.to_dict()}, indent=2))
        return 0
    if sub == "record":
        r = um.record(
            int(getattr(args, "tokens", 0) or 0),
            source=getattr(args, "source", None) or "manual",
            label=getattr(args, "label", None) or "",
            workdir=root,
            enforce=not bool(getattr(args, "force", False)),
        )
        print(json.dumps(r, indent=2))
        return 0
    if sub == "reset-day":
        print(json.dumps(um.reset_day(root), indent=2))
        return 0
    print("usage: nexus usage status|set|record|reset-day")
    return 2


def _task_settings(args: argparse.Namespace):
    """Resolve Settings for task inspect commands (state-dir override or env)."""
    from .config import Settings

    state = getattr(args, "state_dir", None) or os.environ.get("NEXUS_STATE_DIR")
    if state:
        return Settings(state_dir=Path(state))
    return Settings()


def cmd_task(args: argparse.Namespace) -> int:
    """Operator surface: list/show/events/resume + replay/explain/cost/prov/verify/graph/dag/evidence."""
    from .engine import DurableEngine, TaskStatus
    from .persist import atomic_write_json

    settings = _task_settings(args)
    engine = DurableEngine(settings=settings, auto_approve=True, journal=True)
    sub = getattr(args, "task_cmd", None)

    if sub == "list":
        rows = engine.list_tasks()
        if not rows:
            print(f"(no tasks in {settings.state_dir / 'tasks'})")
            return 0
        print(
            f"{'TASK_ID':<24} {'STATUS':<14} {'STEP':>4} {'EVENTS':>6} "
            f"{'TOK':>6} {'LAST':<14} {'AGENT':<12}  OBJECTIVE"
        )
        for r in rows:
            print(
                f"{r['task_id']:<24} {r['status']:<14} {r['current_step']:>4} "
                f"{r.get('events', 0):>6} {int(r.get('tokens') or 0):>6} "
                f"{str(r.get('last_event') or '')[:14]:<14} "
                f"{str(r.get('last_agent') or '')[:12]:<12}  {r.get('objective', '')}"
            )
        return 0

    if sub == "show":
        try:
            task = engine.load(args.task_id)
        except FileNotFoundError:
            print(f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        print(json.dumps(task.to_dict(), indent=2, default=str))
        return 0

    if sub == "events":
        rows = engine.events(args.task_id, limit=int(getattr(args, "limit", 50) or 50))
        path = engine._events_path(args.task_id)
        if not rows:
            if not path.is_file():
                print(f"no journal for task {args.task_id!r} ({path})", file=sys.stderr)
                return 1
            print(f"(empty journal: {path})")
            return 0
        if getattr(args, "json", False):
            print(json.dumps(rows, indent=2, default=str))
            return 0
        print(f"# events for {args.task_id}  ({len(rows)} shown)  path={path}")
        for r in rows:
            ts = r.get("ts")
            try:
                ts_s = time.strftime("%H:%M:%S", time.localtime(float(ts))) if ts else "??:??:??"
            except (TypeError, ValueError, OSError):
                ts_s = "??:??:??"
            step = r.get("step")
            step_s = f"s{step}" if step is not None else "  "
            agent = (r.get("agent") or "")[:16]
            ev = r.get("event", "?")
            detail = (r.get("detail") or "")[:60]
            extra = ""
            if r.get("from_agent") or r.get("to_agent"):
                extra = f"  {r.get('from_agent', '')}->{r.get('to_agent', '')}"
            elif r.get("verdict"):
                extra = f"  verdict={r['verdict']}"
            elif r.get("why"):
                extra = f"  why={str(r['why'])[:40]}"
            if r.get("tokens") is not None:
                extra += f"  tok={r['tokens']}"
            if r.get("score") is not None:
                extra += f"  score={r['score']}"
            print(f"{ts_s}  {step_s:>3}  {ev:<14}  {agent:<16}  {detail}{extra}")
        return 0

    if sub == "replay":
        # open-multi-agent plan-replay: normalized timeline, no re-execution
        path = engine._events_path(args.task_id)
        rows = engine.replay(
            args.task_id,
            limit=int(getattr(args, "limit", 0) or 0) or None,
        )
        if not rows:
            if not path.is_file():
                print(f"no journal for task {args.task_id!r} ({path})", file=sys.stderr)
                return 1
            print(f"(empty journal: {path})")
            return 0
        if getattr(args, "json", False):
            print(json.dumps(rows, indent=2, default=str))
            return 0
        print(f"# replay {args.task_id}  ({len(rows)} events)  path={path}")
        for r in rows:
            ts = r.get("ts")
            try:
                ts_s = time.strftime("%H:%M:%S", time.localtime(float(ts))) if ts else "??:??:??"
            except (TypeError, ValueError, OSError):
                ts_s = "??:??:??"
            step = r.get("step")
            step_s = f"s{step}" if step is not None else "  "
            agent = (r.get("agent") or "")[:14]
            ev = r.get("event", "?")
            detail = (r.get("detail") or "")[:50]
            bits = []
            if r.get("from_agent") or r.get("to_agent"):
                bits.append(f"{r.get('from_agent', '')}->{r.get('to_agent', '')}")
            if r.get("decision"):
                bits.append(f"dec={r['decision']}")
            if r.get("score") is not None:
                bits.append(f"score={r['score']}")
            if r.get("tokens") is not None:
                bits.append(f"tok={r['tokens']}")
            if r.get("why"):
                bits.append(f"why={str(r['why'])[:36]}")
            if r.get("verdict"):
                bits.append(f"verdict={r['verdict']}")
            tail = ("  " + " ".join(bits)) if bits else ""
            print(f"{r.get('i', 0):>3} {ts_s}  {step_s:>3}  {ev:<14}  {agent:<14}  {detail}{tail}")
        return 0

    if sub == "explain":
        # CEMA-style causal decision summary (read-only)
        rep = engine.explain(args.task_id)
        if not rep.get("found"):
            print(rep.get("error") or f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(rep, indent=2, default=str))
            return 0
        print(f"# explain {rep['task_id']}")
        print(f"status:       {rep.get('status')}  step={rep.get('current_step')}  events={rep.get('n_events')}")
        print(f"objective:    {rep.get('objective', '')}")
        if rep.get("last_agent"):
            print(f"last_agent:   {rep['last_agent']}")
        if rep.get("waiting_step") is not None and rep.get("status") == "waiting_human":
            print(f"waiting_step: {rep['waiting_step']}")
        if rep.get("error"):
            print(f"error:        {rep['error']}")
        print(f"story:        {rep.get('story', '')}")
        cost = rep.get("cost") or {}
        if cost:
            thr = cost.get("thresholds") or {}
            thr_s = (
                f"pass>={thr.get('pass')} revise>={thr.get('revise')}"
                if thr
                else ""
            )
            print(
                f"cost:         tokens={cost.get('total_tokens', 0)}  "
                f"avg_score={cost.get('avg_score')}  {thr_s}"
            )
        if rep.get("handoffs"):
            print("handoffs:")
            for h in rep["handoffs"]:
                print(
                    f"  step {h.get('step')}: "
                    f"{h.get('from_agent')} -> {h.get('to_agent')}"
                )
        if rep.get("human_decisions"):
            print("human_decisions:")
            for h in rep["human_decisions"]:
                print(
                    f"  step {h.get('step')}: {h.get('decision')}  "
                    f"approve={h.get('approve')}  feedback={h.get('feedback')!r}"
                )
        if rep.get("vetoes"):
            print("vetoes:")
            for v in rep["vetoes"]:
                print(f"  step {v.get('step')}: {v.get('verdict')}  agent={v.get('agent')}")
        if rep.get("failures"):
            print("failures:")
            for f in rep["failures"]:
                print(f"  step {f.get('step')}: {f.get('detail')}")
        if rep.get("steps"):
            print("steps:")
            for s in rep["steps"]:
                why = (s.get("why") or "")[:70]
                score_s = f" score={s['score']}" if s.get("score") is not None else ""
                tok_s = f" tok={s['tokens']}" if s.get("tokens") is not None else ""
                print(
                    f"  s{s.get('step')}: {s.get('name') or '?'}  "
                    f"agent={s.get('agent') or '-'}  "
                    f"decision={s.get('decision') or '-'}{score_s}{tok_s}  "
                    f"why={why or '-'}"
                )
        return 0

    if sub == "cost":
        # mission-control task cost rollup (journal + optional usage ledger)
        rep = engine.cost(args.task_id)
        if not rep.get("found"):
            print(rep.get("error") or f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(rep, indent=2, default=str))
            return 0
        thr = rep.get("thresholds") or {}
        print(f"# cost {rep['task_id']}")
        print(f"status:       {rep.get('status')}")
        print(f"total_tokens: {rep.get('total_tokens', 0)}")
        print(f"steps:        {rep.get('request_count', 0)}  avg/step={rep.get('avg_tokens_per_step', 0)}")
        print(f"avg_score:    {rep.get('avg_score')}")
        cap = rep.get("max_tokens")
        if cap is not None:
            rem = rep.get("remaining_tokens")
            # token-only exhaustion label (wall has its own line)
            tok_exh = (
                rep.get("budget_exhausted")
                and not rep.get("wall_exhausted")
            ) or (
                cap is not None
                and rep.get("remaining_tokens") == 0
                and int(rep.get("total_tokens") or 0) > int(cap or 0)
            )
            exh = "EXHAUSTED" if tok_exh or (
                rep.get("budget_exhausted") and rep.get("max_wall_s") is None
            ) else "ok"
            if rep.get("budget_exhausted") and not rep.get("wall_exhausted"):
                exh = "EXHAUSTED"
            print(f"budget:       max={cap}  remaining={rem}  {exh}")
        else:
            print("budget:       unlimited")
        wall = rep.get("max_wall_s")
        elapsed = rep.get("elapsed_s")
        if wall is not None:
            rem_w = rep.get("remaining_wall_s")
            exh_w = "EXHAUSTED" if rep.get("wall_exhausted") else "ok"
            el_s = f"{elapsed}" if elapsed is not None else "?"
            print(f"wall:         max={wall}s  elapsed={el_s}s  remaining={rem_w}s  {exh_w}")
        elif elapsed is not None:
            print(f"wall:         elapsed={elapsed}s  (unlimited)")
        if thr:
            print(f"thresholds:   pass>={thr.get('pass')}  revise>={thr.get('revise')}")
        if rep.get("by_agent"):
            print("by_agent:")
            for agent, tok in sorted(rep["by_agent"].items(), key=lambda x: -x[1]):
                print(f"  {agent}: {tok}")
        if rep.get("by_step"):
            print("by_step:")
            for sn, tok in sorted(rep["by_step"].items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
                print(f"  s{sn}: {tok}")
        if rep.get("steps"):
            print("steps:")
            for s in rep["steps"]:
                print(
                    f"  s{s.get('step')}: {s.get('name') or '?'}  "
                    f"agent={s.get('agent') or '-'}  "
                    f"tok={s.get('tokens') or 0}  "
                    f"score={s.get('score')}  "
                    f"dec={s.get('decision') or '-'}"
                )
        return 0

    if sub == "graph":
        # MAS call-graph / space-time profile (read-only)
        rep = engine.graph(args.task_id)
        if not rep.get("found"):
            print(rep.get("error") or f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(rep, indent=2, default=str))
            return 0
        print(f"# graph {rep['task_id']}  schema={rep.get('schema')}")
        print(
            f"status:       {rep.get('status')}  step={rep.get('current_step')}  "
            f"agents={rep.get('n_agents', 0)}  handoffs={rep.get('n_handoffs', 0)}"
        )
        print(f"objective:    {rep.get('objective', '')}")
        cost = rep.get("cost") or {}
        if cost:
            budget_s = ""
            if cost.get("max_tokens") is not None:
                budget_s = (
                    f"  budget={cost.get('max_tokens')} "
                    f"rem={cost.get('remaining_tokens')}"
                )
                if cost.get("budget_exhausted"):
                    budget_s += " EXHAUSTED"
            print(f"cost:         tokens={cost.get('total_tokens', 0)}{budget_s}")
        nodes = rep.get("nodes") or []
        if nodes:
            print("nodes:")
            for n in nodes:
                print(
                    f"  {n.get('id')}: vendor={n.get('vendor')}  "
                    f"starts={n.get('n_starts', 0)}  "
                    f"completes={n.get('n_completes', 0)}  "
                    f"tokens={n.get('tokens', 0)}  "
                    f"steps={n.get('steps')}"
                )
        edges = rep.get("edges") or []
        if edges:
            print("edges:")
            for e in edges:
                cnt = e.get("count") or 1
                mult = f" x{cnt}" if cnt > 1 else ""
                print(f"  {e.get('from')} -> {e.get('to')}{mult}  ({e.get('kind')})")
        seq = rep.get("sequence") or []
        if seq:
            print(f"sequence:     ({len(seq)} events)")
            for s in seq[:40]:
                step = s.get("step")
                step_s = f"s{step}" if step is not None else "  "
                ev = s.get("event") or "?"
                if ev == "handoff":
                    detail = f"{s.get('from_agent')}->{s.get('to_agent')}"
                elif s.get("agent"):
                    detail = f"agent={s.get('agent')}"
                    if s.get("name"):
                        detail += f" {s.get('name')}"
                    if s.get("decision"):
                        detail += f" dec={s.get('decision')}"
                    if s.get("tokens") is not None:
                        detail += f" tok={s.get('tokens')}"
                else:
                    detail = (s.get("detail") or "")[:60]
                print(f"  {step_s:>3}  {ev:<14}  {detail}")
            if len(seq) > 40:
                print(f"  … +{len(seq) - 40} more (use --json)")
        if getattr(args, "mermaid", False) and rep.get("mermaid"):
            print("mermaid:")
            print(rep["mermaid"])
        return 0

    if sub == "dag":
        # P1.2 multi-agent task dependency DAG (policy + action_order)
        rep = engine.dag(args.task_id)
        if not rep.get("found"):
            print(rep.get("error") or f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(rep, indent=2, default=str))
            return 0
        print(f"# dag {rep['task_id']}  schema={rep.get('schema')}")
        print(
            f"status:       {rep.get('status')}  step={rep.get('current_step')}  "
            f"completed={rep.get('n_completed', 0)}/{rep.get('n_steps', 0)}  "
            f"ready={rep.get('n_ready', 0)}  blocked={rep.get('n_blocked', 0)}"
        )
        print(f"objective:    {rep.get('objective', '')}")
        print(f"topo:         {rep.get('topo')}")
        order = rep.get("action_order") or []
        if order:
            print(f"action_order: {' → '.join(str(x) for x in order)}")
        nodes = rep.get("nodes") or []
        if nodes:
            print("nodes:")
            for n in nodes:
                deps = n.get("depends_on") or []
                dep_s = f" depends_on={deps}" if deps else ""
                print(
                    f"  s{n.get('id')}:{n.get('name')}  "
                    f"status={n.get('status')}  agent={n.get('agent')}{dep_s}"
                )
        blocked = rep.get("blocked") or []
        if blocked:
            print("blocked:")
            for b in blocked:
                print(f"  s{b.get('id')}:{b.get('name')}  waiting_on={b.get('waiting_on')}")
        if getattr(args, "mermaid", False) and rep.get("mermaid"):
            print("mermaid:")
            print(rep["mermaid"])
        return 0

    if sub == "context":
        # P1.4 bounded multi-source context pack (arXiv 2508.08322)
        rep = engine.context_pack(
            args.task_id,
            include_research=bool(getattr(args, "research", False)),
            include_repo_digests=bool(getattr(args, "repos", False)),
            journal_limit=int(getattr(args, "journal_limit", 8) or 8),
        )
        if not rep.get("found"):
            print(rep.get("error") or f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        out_path = getattr(args, "out", None)
        if out_path:
            from .persist import atomic_write_json

            atomic_write_json(Path(out_path), rep)
        if getattr(args, "json", False):
            print(json.dumps(rep, indent=2, default=str))
            return 0
        if getattr(args, "prompt", False):
            print(rep.get("prompt") or "")
            return 0
        print(f"# context {rep['task_id']}  schema={rep.get('schema')}")
        print(
            f"status:       {rep.get('status')}  step={rep.get('current_step')}  "
            f"chars={rep.get('total_chars')}/{rep.get('total_budget')}  "
            f"~tokens={rep.get('est_tokens')}"
        )
        print(f"objective:    {rep.get('objective', '')}")
        sections = rep.get("sections") or []
        if sections:
            print("sections:")
            for s in sections:
                flag = "*" if s.get("truncated") else " "
                print(
                    f"  {flag}{s.get('name')}: chars={s.get('chars')}  "
                    f"src={s.get('source') or '-'}"
                )
        trunc = rep.get("truncated_sections") or []
        if trunc:
            print(f"truncated:   {', '.join(str(t) for t in trunc)}")
        if out_path:
            print(f"wrote:        {out_path}")
        return 0

    if sub == "consensus":
        # P1.3 multi-grader consensus (gossipcat findings + trust weights)
        rep = engine.consensus(args.task_id)
        if not rep.get("found"):
            print(rep.get("error") or f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(rep, indent=2, default=str))
            return 0
        print(f"# consensus {rep['task_id']}  schema={rep.get('schema')}")
        print(
            f"status:       {rep.get('status')}  step={rep.get('current_step')}  "
            f"enabled={rep.get('enabled')}  rounds={rep.get('n_rounds', 0)}"
        )
        print(f"objective:    {rep.get('objective', '')}")
        totals = rep.get("totals") or {}
        print(
            f"totals:       agreement={totals.get('agreement', 0)}  "
            f"disagreement={totals.get('disagreement', 0)}  "
            f"avg_agree={totals.get('avg_agreement_ratio')}"
        )
        weights = rep.get("trust_weights") or {}
        if weights:
            top = sorted(weights.items(), key=lambda x: -float(x[1]))[:6]
            print(
                "trust:        "
                + " ".join(f"{k}={v}" for k, v in top)
            )
        rounds = rep.get("rounds") or []
        if rounds:
            print("rounds:")
            for r in rounds:
                graders = ",".join(str(g) for g in (r.get("graders") or [])[:5])
                print(
                    f"  s{r.get('step')}: {r.get('detail') or '?'}  "
                    f"dec={r.get('decision')}  score={r.get('score')}  "
                    f"agree={r.get('agreement_ratio')}  n={r.get('n_graders')}  "
                    f"graders=[{graders}]"
                )
        steps = rep.get("step_findings") or []
        if steps and getattr(args, "findings", False):
            print("findings:")
            for s in steps:
                for f in s.get("findings") or []:
                    print(
                        f"  s{s.get('step')}  {f.get('grader')}: "
                        f"dec={f.get('decision')} score={f.get('score')} "
                        f"w={f.get('weight')} signal={f.get('signal')}"
                    )
        return 0

    if sub == "prov":
        # PROV-AGENT style unified provenance export (read-only)
        rep = engine.provenance(args.task_id)
        if not rep.get("found"):
            print(rep.get("error") or f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(rep, indent=2, default=str))
            return 0
        print(f"# provenance {rep['task_id']}  schema={rep.get('schema')}")
        print(f"status:       {rep.get('status')}  step={rep.get('current_step')}  events={rep.get('n_events')}")
        print(f"objective:    {rep.get('objective', '')}")
        print(f"story:        {rep.get('story', '')}")
        cost = rep.get("cost") or {}
        if cost:
            print(
                f"cost:         tokens={cost.get('total_tokens', 0)}  "
                f"avg_score={cost.get('avg_score')}"
            )
        agents = rep.get("agents") or []
        if agents:
            print(f"agents:       {len(agents)}")
            for a in agents:
                print(
                    f"  {a.get('id')}: vendor={a.get('vendor')}  "
                    f"steps={a.get('steps')}  tokens={a.get('tokens', 0)}"
                )
        acts = rep.get("activities") or []
        if acts:
            print(f"activities:   {len(acts)}")
            for a in acts:
                print(
                    f"  {a.get('id')}: {a.get('name') or '?'}  "
                    f"agent={a.get('agent') or '-'}  "
                    f"dec={a.get('decision') or '-'}  "
                    f"score={a.get('score')}  tok={a.get('tokens')}"
                )
        ents = rep.get("entities") or []
        if ents:
            print(f"entities:     {len(ents)}")
            for e in ents:
                extra = e.get("path") or e.get("objective") or e.get("status") or ""
                if isinstance(extra, str) and len(extra) > 60:
                    extra = extra[:60] + "…"
                print(f"  {e.get('id')}: type={e.get('type')}  {extra}")
        rels = rep.get("relations") or []
        if rels:
            print(f"relations:    {len(rels)}")
            for r in rels[:24]:
                bits = [f"type={r.get('type')}"]
                for k in (
                    "activity", "agent", "entity", "informed_by",
                    "derived_from", "kind", "step",
                ):
                    if r.get(k) not in (None, ""):
                        bits.append(f"{k}={r[k]}")
                print("  " + " ".join(bits))
            if len(rels) > 24:
                print(f"  … +{len(rels) - 24} more (use --json)")
        if rep.get("handoffs"):
            print(f"handoffs:     {len(rep['handoffs'])}")
        if rep.get("trust"):
            print(f"trust_rows:   {len(rep['trust'])}")
        return 0

    if sub == "verify":
        # checkpoint ↔ journal integrity (fault-tolerant durability)
        rep = engine.verify(args.task_id)
        if not rep.get("found"):
            print(rep.get("error") or f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(rep, indent=2, default=str))
            return 0 if rep.get("ok") else 1
        status = "OK" if rep.get("ok") else "FAIL"
        print(f"# verify {rep['task_id']}  {status}")
        print(
            f"status:       {rep.get('status')}  step={rep.get('current_step')}  "
            f"events={rep.get('n_events')}"
        )
        print(
            f"tokens:       journal={rep.get('journal_tokens', 0)}  "
            f"meta={rep.get('meta_tokens', 0)}  "
            f"max_step_complete={rep.get('max_step_complete', 0)}"
        )
        print(f"errors:       {rep.get('n_errors', 0)}  warns={rep.get('n_warns', 0)}")
        checks = rep.get("checks") or {}
        if checks:
            print("checks:")
            for k, v in checks.items():
                mark = "pass" if v else "FAIL"
                print(f"  {k}: {mark}")
        issues = rep.get("issues") or []
        if issues:
            print("issues:")
            for i in issues:
                print(
                    f"  [{i.get('severity', '?')}] {i.get('code', '?')}: "
                    f"{i.get('msg', '')}"
                )
        else:
            print("issues:       (none)")
        return 0 if rep.get("ok") else 1

    if sub == "resume":
        # P7 HITL / crash-resume (rojak Temporal resume + mission-control operator)
        approve_flag = bool(getattr(args, "approve", False))
        reject_flag = bool(getattr(args, "reject", False))
        if approve_flag and reject_flag:
            print("use only one of --approve or --reject", file=sys.stderr)
            return 2
        approve: Optional[bool]
        if approve_flag:
            approve = True
        elif reject_flag:
            approve = False
        else:
            approve = None
        feedback = getattr(args, "feedback", None)
        try:
            task = engine.load(args.task_id)
        except FileNotFoundError:
            print(f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        if task.status == TaskStatus.waiting_human and approve is None:
            waiting = task.meta.get("waiting_step")
            print(
                f"task {args.task_id!r} is waiting_human"
                + (f" at step {waiting}" if waiting is not None else "")
                + " — pass --approve or --reject",
                file=sys.stderr,
            )
            return 2
        if task.status in (TaskStatus.completed, TaskStatus.failed) and approve is None:
            # still allow re-run? No — report terminal unless explicit force later
            print(
                f"task {args.task_id!r} is already {task.status.value} "
                f"(step={task.current_step}); nothing to resume",
                file=sys.stderr,
            )
            return 1
        # HITL: keep auto_approve off so a pending gate is only resolved via flags
        if approve is not None:
            engine.auto_approve = False
        try:
            task = engine.resume(
                args.task_id,
                approve=approve,
                feedback=feedback,
            )
        except FileNotFoundError:
            print(f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(task.to_dict(), indent=2, default=str))
        else:
            print(f"# resume {task.task_id}")
            print(f"status:       {task.status.value}")
            print(f"step:         {task.current_step}")
            if task.meta.get("waiting_step") and task.status == TaskStatus.waiting_human:
                print(f"waiting_step: {task.meta.get('waiting_step')}")
            if task.meta.get("error"):
                print(f"error:        {task.meta.get('error')}")
            if task.meta.get("human_decision"):
                hd = task.meta["human_decision"]
                print(
                    f"human:        approved={hd.get('approved')}  "
                    f"feedback={hd.get('feedback')!r}  step={hd.get('step')}"
                )
            print(f"objective:    {task.objective[:120]}")
        # exit 0 when completed/running/waiting; 1 when failed after resume
        if task.status == TaskStatus.failed:
            return 1
        return 0

    if sub == "evidence":
        # routa / mission-control portable evidence pack (P6)
        compact = bool(getattr(args, "compact", False))
        rep = engine.evidence(args.task_id, compact=compact)
        if not rep.get("found"):
            print(rep.get("error") or f"task not found: {args.task_id}", file=sys.stderr)
            return 1
        out_path = getattr(args, "out", None)
        if out_path:
            path = Path(out_path)
            atomic_write_json(path, rep)
            print(f"wrote evidence pack → {path}  schema={rep.get('schema')}")
            if not getattr(args, "json", False):
                # still print a short human summary after write
                pass
            else:
                return 0
        if getattr(args, "json", False):
            print(json.dumps(rep, indent=2, default=str))
            return 0
        task = rep.get("task") or {}
        gates = rep.get("gates") or {}
        ready = "READY" if rep.get("ready") else "NOT_READY"
        print(f"# evidence {rep['task_id']}  schema={rep.get('schema')}  {ready}")
        print(
            f"status:       {task.get('status')}  step={task.get('current_step')}  "
            f"tokens={task.get('tokens_total', 0)}"
        )
        print(f"objective:    {task.get('objective', '')}")
        print(f"story:        {rep.get('story', '')}")
        cost = rep.get("cost") or {}
        if cost:
            budget_s = ""
            if cost.get("max_tokens") is not None:
                budget_s = f"  max={cost.get('max_tokens')} rem={cost.get('remaining_tokens')}"
            print(
                f"cost:         tokens={cost.get('total_tokens', 0)}  "
                f"avg_score={cost.get('avg_score')}{budget_s}"
            )
        norms = rep.get("norms") or {}
        if norms:
            print(
                f"norms:        rules={norms.get('n_rules', 0)}  "
                f"require={norms.get('require') or []}  "
                f"deny={norms.get('deny') or []}  "
                f"max_tokens={norms.get('max_tokens')}"
            )
            for r in (norms.get("rules") or [])[:12]:
                kind = r.get("kind") or "?"
                if kind == "budget":
                    print(f"  [{kind}] max_tokens={r.get('value')}  ({r.get('source')})")
                else:
                    print(f"  [{kind}] {r.get('value') or r.get('source')}")
            if len(norms.get("rules") or []) > 12:
                print(f"  … +{len(norms['rules']) - 12} more (use --json)")
        if gates:
            print("gates:")
            for k, v in gates.items():
                mark = "pass" if v else "FAIL"
                print(f"  {k}: {mark}")
        if rep.get("gate_failures"):
            print(f"gate_failures: {rep['gate_failures']}")
        ver = rep.get("verify") or {}
        print(
            f"verify:       {'OK' if ver.get('ok') else 'FAIL'}  "
            f"errors={ver.get('n_errors', 0)}  warns={ver.get('n_warns', 0)}"
        )
        print(
            f"timeline:     {rep.get('n_timeline', 0)} events  "
            f"vetoes={rep.get('n_vetoes', 0)}  failures={rep.get('n_failures', 0)}"
        )
        graph = rep.get("graph") or {}
        if graph:
            print(
                f"graph:        agents={graph.get('n_agents', len(graph.get('nodes') or []))}  "
                f"handoffs={graph.get('n_handoffs', 0)}"
            )
        prov = rep.get("provenance") or {}
        if prov and not compact:
            print(
                f"provenance:   agents={len(prov.get('agents') or [])}  "
                f"activities={len(prov.get('activities') or [])}  "
                f"relations={len(prov.get('relations') or [])}"
            )
        elif prov and compact:
            print(
                f"provenance:   agents={prov.get('n_agents', 0)}  "
                f"activities={prov.get('n_activities', 0)}  "
                f"relations={prov.get('n_relations', 0)}  (compact)"
            )
        if out_path:
            print(f"written:      {out_path}")
        # inspect-only: always exit 0 when pack found (use --json + gates for automation)
        return 0

    print(f"unknown task subcommand: {sub}", file=sys.stderr)
    return 2


def cmd_ops(args: argparse.Namespace) -> int:
    """Mission-control-style ops plane: list/show jobs + spend (P1.1)."""
    from .ops_store import OpsStore, OpsError

    root = Path(getattr(args, "path", None) or Path.cwd()).resolve()
    sub = getattr(args, "ops_cmd", None) or "list"
    try:
        with OpsStore.open(root) as store:
            if sub == "list":
                rows = store.list_jobs(
                    kind=getattr(args, "kind", None) or None,
                    status=getattr(args, "status", None) or None,
                    limit=int(getattr(args, "limit", 50) or 50),
                )
                if getattr(args, "json", False):
                    print(json.dumps(rows, indent=2, default=str))
                    return 0
                if not rows:
                    print(f"(no ops jobs in {store.workdir / '.nexus_state' / 'ops'})")
                    return 0
                print(
                    f"{'JOB_ID':<28} {'KIND':<10} {'STATUS':<10} "
                    f"{'TOK':>8}  TITLE"
                )
                for r in rows:
                    print(
                        f"{str(r['id'])[:28]:<28} {str(r['kind'])[:10]:<10} "
                        f"{str(r['status'])[:10]:<10} {int(r.get('tokens') or 0):>8}  "
                        f"{str(r.get('title') or '')[:48]}"
                    )
                return 0
            if sub == "show":
                jid = str(getattr(args, "job_id", "") or "")
                job = store.get(jid)
                if not job:
                    print(f"job not found: {jid}", file=sys.stderr)
                    return 1
                rep = store.spend_report(jid)
                out = {"job": job, "spend": rep}
                print(json.dumps(out, indent=2, default=str))
                return 0
            if sub == "spend":
                jid = getattr(args, "job_id", None) or None
                rep = store.spend_report(jid)
                print(json.dumps(rep, indent=2, default=str))
                return 0
            if sub == "record":
                jid = str(getattr(args, "job_id", "") or "")
                tokens = int(getattr(args, "tokens", 0) or 0)
                kind = str(getattr(args, "kind", None) or "task")
                title = str(getattr(args, "title", None) or jid)
                status = str(getattr(args, "status", None) or "running")
                store.upsert_job(
                    jid,
                    kind=kind,
                    title=title,
                    status=status,
                    goal=str(getattr(args, "goal", None) or ""),
                )
                row = store.record_spend(
                    jid,
                    tokens,
                    source=str(getattr(args, "source", None) or "manual"),
                    label=str(getattr(args, "label", None) or ""),
                    dual_write_usage=bool(getattr(args, "usage", False)),
                    ensure=False,
                    kind=kind,
                )
                print(json.dumps(row, indent=2, default=str))
                return 0
            if sub == "status":
                print(json.dumps(store.summary(), indent=2, default=str))
                return 0
            if sub == "ingest":
                res = store.ingest_usage_ledger()
                print(json.dumps(res, indent=2, default=str))
                return 0
            if sub == "set-status":
                jid = str(getattr(args, "job_id", "") or "")
                st = str(getattr(args, "status", "") or "")
                job = store.set_status(jid, st)
                print(json.dumps(job, indent=2, default=str))
                return 0
    except OpsError as e:
        print(f"ops error: {e}", file=sys.stderr)
        return 1
    print("usage: nexus ops list|show|spend|record|status|ingest|set-status", file=sys.stderr)
    return 2


def cmd_alive(args: argparse.Namespace) -> int:
    """Self-improvement under user goals + token budget."""
    from . import alive as al
    from . import usage as um

    root = Path(getattr(args, "path", None) or Path.cwd()).resolve()
    sub = getattr(args, "alive_cmd", None) or "status"
    if sub == "init":
        cfg = al.load_config(root)
        if getattr(args, "goal", None):
            cfg.goal = args.goal
        if getattr(args, "query", None):
            cfg.queries = [args.query]
        if getattr(args, "apply", False):
            cfg.apply = True
        if getattr(args, "self_approve", False):
            cfg.self_approve = True
        if getattr(args, "push_github", False):
            cfg.push_github = True
        if getattr(args, "no_push_github", False):
            cfg.push_github = False
        if getattr(args, "repo", None):
            cfg.our_repo = args.repo
        if getattr(args, "interval", None):
            cfg.interval_s = int(args.interval)
        if getattr(args, "grader", None):
            cfg.grader = str(args.grader)
        if getattr(args, "worker", None):
            cfg.worker = str(args.worker)
        p = al.save_config(cfg, root)
        print(json.dumps({"saved": str(p), "config": cfg.to_dict()}, indent=2))
        print("Run: nexus alive once | nexus alive watch")
        print("Full loop to GitHub: --apply --self-approve --push-github")
        print("Hard grade/work: Grok (grader/worker=auto|grok); light: local Ollama")
        return 0
    if sub == "status":
        cfg = al.load_config(root)
        st = {}
        sp = al.state_path(root)
        if sp.is_file():
            try:
                st = json.loads(sp.read_text(encoding="utf-8"))
            except Exception:
                st = {}
        print(json.dumps({"config": cfg.to_dict(), "last": st, "usage": um.status(root)}, indent=2, default=str))
        return 0
    if sub == "once":
        rep = al.cycle_once(root, dry_run=bool(getattr(args, "dry_run", False)))
        print(json.dumps(rep, indent=2, default=str))
        return 0 if not rep.get("blocked") else 1
    if sub == "watch":
        return al.watch(
            root,
            interval_s=float(getattr(args, "interval", 0) or 0) or None,
            max_cycles=int(getattr(args, "max_cycles", 0) or 0),
        )
    if sub == "gaps":
        # P1.5: supervised gap board — list / seed / close
        if getattr(args, "close", None):
            try:
                out = al.close_gap(
                    str(args.close),
                    root,
                    evidence=str(getattr(args, "evidence", None) or "operator close"),
                )
            except KeyError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            print(json.dumps(out, indent=2, default=str))
            return 0
        if getattr(args, "seed", False):
            out = al.seed_gaps(
                root,
                reopen_closed=bool(getattr(args, "reopen", False)),
            )
            print(json.dumps(out, indent=2, default=str))
            return 0
        board = al.gap_board(root)
        if getattr(args, "json", False):
            print(json.dumps(board, indent=2, default=str))
            return 0
        counts = board.get("counts") or {}
        print(
            f"gap board  open={counts.get('open', 0)}  "
            f"closed={counts.get('closed', 0)}  "
            f"cycle={board.get('cycle', 0)}  "
            f"streak={board.get('no_progress_streak', 0)}"
        )
        print(f"  path: {board.get('path')}")
        for g in board.get("open") or []:
            print(f"  [open]   {g.get('id')}: {(g.get('description') or '')[:80]}")
        for g in board.get("closed") or []:
            print(f"  [closed] {g.get('id')}: {(g.get('evidence') or '')[:60]}")
        if not (board.get("open") or board.get("closed")):
            print("  (empty — run: nexus alive gaps --seed)")
        return 0
    print("usage: nexus alive init|status|once|watch|gaps")
    return 2


def cmd_vault(args: argparse.Namespace) -> int:
    """Secrets vault — presence checks + redaction (never print values)."""
    from . import vault as vmod

    root = Path(getattr(args, "path", None) or Path.cwd()).resolve()
    sub = getattr(args, "vault_cmd", None) or "status"
    vault = vmod.Vault(workdir=root)
    if sub == "status":
        st = vault.status()
        print(json.dumps(st, indent=2, default=str))
        return 0
    if sub == "check":
        name = str(getattr(args, "key", None) or "").strip()
        if not name:
            print("usage: nexus vault check KEY", file=sys.stderr)
            return 2
        present = vault.present(name)
        out = {
            "key": name,
            "present": present,
            "source": vault.source_of(name),
        }
        print(json.dumps(out, indent=2))
        return 0 if present else 1
    if sub == "redact":
        text = str(getattr(args, "text", None) or "")
        if getattr(args, "stdin", False) or text == "-":
            text = sys.stdin.read()
        print(vault.redact(text), end="" if text.endswith("\n") else "\n")
        return 0
    print("usage: nexus vault status|check|redact", file=sys.stderr)
    return 2


def cmd_skillpacks(args: argparse.Namespace) -> int:
    """P2.1 multi-harness skillpack list / validate / generate / drift."""
    from . import skillpacks as sp

    root = Path(getattr(args, "path", None) or Path.cwd()).resolve()
    sub = getattr(args, "skillpacks_cmd", None) or "list"
    as_json = bool(getattr(args, "json", False))
    packs_dir = str(getattr(args, "packs_dir", None) or sp.DEFAULT_PACKS_DIR)
    max_priv = getattr(args, "max_privilege", None)

    if sub == "list":
        rows = sp.list_packs(
            root, packs_dir=packs_dir, validate=bool(getattr(args, "validate", False)),
            max_privilege=max_priv,
        )
        if as_json:
            print(json.dumps(
                {"schema": sp.SCHEMA_VERSION, "packs": [r.to_dict() for r in rows]},
                indent=2,
            ))
        else:
            print(sp.format_list(rows))
        return 0

    if sub == "validate":
        pack = getattr(args, "pack", None)
        if pack:
            pack_path = root / packs_dir / str(pack)
            if not pack_path.is_dir():
                pack_path = Path(pack)
            rep = sp.validate_pack(pack_path)
            data = {"schema": sp.SCHEMA_VERSION, "ok": rep.ok, "count": 1, "packs": [rep.to_dict()],
                    "errors": sum(1 for f in rep.findings if f.severity == "error"),
                    "warnings": sum(1 for f in rep.findings if f.severity == "warning")}
        else:
            data = sp.validate_all(root, packs_dir=packs_dir)
        if as_json:
            print(json.dumps(data, indent=2))
        else:
            print(sp.format_validate(data))
        return 0 if data.get("ok") else 1

    if sub == "generate":
        out_root = getattr(args, "out", None)
        harnesses = getattr(args, "harness", None)
        if harnesses:
            harnesses = list(harnesses)
        pack = getattr(args, "pack", None)
        clean = bool(getattr(args, "clean", False))
        if pack:
            pack_path = root / packs_dir / str(pack)
            if not pack_path.is_dir():
                pack_path = Path(pack)
            try:
                one = sp.generate_pack(
                    pack_path,
                    out_root=out_root or sp.generate_root(root),
                    harnesses=harnesses,
                    clean=clean,
                )
                data = {
                    "schema": sp.SCHEMA_VERSION,
                    "ok": True,
                    "out_root": one["out_root"],
                    "generated": [one],
                    "errors": [],
                    "count": 1,
                }
            except sp.SkillpackError as e:
                print(f"SkillpackError: {e}", file=sys.stderr)
                return 1
        else:
            data = sp.generate_all(
                root,
                packs_dir=packs_dir,
                out_root=out_root,
                harnesses=harnesses,
                clean=clean,
                max_privilege=max_priv,
            )
        if as_json:
            print(json.dumps(data, indent=2))
        else:
            print(sp.format_generate(data))
        return 0 if data.get("ok") else 1

    if sub == "drift":
        data = sp.drift_check(
            root,
            packs_dir=packs_dir,
            out_root=getattr(args, "out", None),
        )
        if as_json:
            print(json.dumps(data, indent=2))
        else:
            print(sp.format_drift(data))
        return 0 if data.get("ok") else 1

    print("usage: nexus skillpacks list|validate|generate|drift", file=sys.stderr)
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
        "platforms",
        "heartbeat",
        "recovery",
        "schedule",
        "usage",
        "ops",
        "alive",
        "vault",
        "skillpacks",
        "procure",
        "arxiv",
        "research",
        "task",
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
        and raw[1]
        not in {
            "inbox",
            "reply",
            "draft",
            "auto",
            "loop",
            "watch",
            "init",
            "search",
            "scout",
            "connect",
            "mine",
            "improve",
            "status",
            "do",
        }
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
    p.add_argument(
        "--no-platforms",
        action="store_true",
        help="skip multi-platform mesh doctor tip on start",
    )
    p.set_defaults(func=cmd_start)

    sub.add_parser("stop", help="stop bus and bridges").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="show process status").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="detect hardware and tools").set_defaults(func=cmd_doctor)
    p_demo = sub.add_parser(
        "demo",
        help="crash→resume demo, self-improve-slice, or --all showcase",
    )
    p_demo.add_argument(
        "slice",
        nargs="?",
        default=None,
        choices=["self-improve-slice", "grade-loop"],
        help="optional: self-improve-slice | grade-loop (grade_read→apply_plan + MCP board)",
    )
    p_demo.add_argument(
        "--repo",
        default=None,
        help="with grade-loop: pick offline grade by owner/name",
    )
    p_demo.add_argument(
        "--all",
        "--showcase",
        dest="all",
        action="store_true",
        help="full showcase: resume + judge + smoke + platforms + resilience",
    )
    p_demo.add_argument(
        "--quick",
        action="store_true",
        help="with --all, skip slower optional sections",
    )
    p_demo.add_argument(
        "--fixture",
        default=None,
        help="grade fixture path or mine_eval dir (self-improve-slice)",
    )
    p_demo.add_argument(
        "--show-audit",
        action="store_true",
        default=True,
        help="print decision audit JSON (self-improve-slice; default on)",
    )
    p_demo.add_argument(
        "--run-id",
        default=None,
        help="resume an existing improve-apply run id",
    )
    p_demo.add_argument(
        "--workdir",
        default=None,
        help="project root for improve-apply state (default: repo root)",
    )
    p_demo.set_defaults(func=cmd_demo)

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

    gh_loop = gh_sub.add_parser(
        "loop",
        help="pick up thread → run tests → post results (response loop)",
    )
    gh_loop.add_argument("number", type=int, help="issue or PR number")
    gh_loop.add_argument("--repo", dest="repo_flag", default=None)
    gh_loop.add_argument(
        "--workdir",
        default=None,
        help="repo root to test (default: cwd)",
    )
    gh_loop.add_argument("--dry-run", action="store_true")
    gh_loop.add_argument(
        "--force",
        action="store_true",
        help="post even if this commit sha was already reported",
    )
    gh_loop.set_defaults(func=cmd_github)

    gh_init = gh_sub.add_parser(
        "init",
        help="bootstrap community-bot workflow into a personal repo path",
    )
    gh_init.add_argument(
        "--path",
        default=".",
        help="local path to your repo (default: cwd)",
    )
    gh_init.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing community-bot.yml",
    )
    gh_init.set_defaults(func=cmd_github)

    gh_watch = gh_sub.add_parser(
        "watch",
        help="continuous loop: poll issues/PRs, run tests, post (opt-in --autonomous)",
    )
    gh_watch.add_argument("--repo", dest="repo_flag", default=None)
    gh_watch.add_argument("--workdir", default=None)
    gh_watch.add_argument(
        "--interval",
        type=float,
        default=120,
        help="seconds between cycles (default 120)",
    )
    gh_watch.add_argument(
        "--autonomous",
        action="store_true",
        help="actually post replies/loop results (default is observe-only)",
    )
    gh_watch.add_argument(
        "--once",
        action="store_true",
        help="single cycle then exit",
    )
    gh_watch.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        help="stop after N cycles (0 = forever)",
    )
    gh_watch.add_argument(
        "--arxiv",
        default=None,
        help="optional arXiv topic to re-pull periodically while watching",
    )
    gh_watch.add_argument(
        "--arxiv-every",
        type=float,
        default=86400,
        help="seconds between arXiv improve runs (default 1 day)",
    )
    gh_watch.add_argument(
        "--scout",
        default=None,
        help="search other GitHub repos on this topic for continuous improvement",
    )
    gh_watch.add_argument(
        "--scout-every",
        type=float,
        default=43200,
        help="seconds between repo scout runs (default 12h)",
    )
    gh_watch.add_argument(
        "--apply",
        action="store_true",
        help="with --arxiv/--scout, also run nexus do repair (powerful)",
    )
    gh_watch.add_argument("--dry-run", action="store_true")
    gh_watch.set_defaults(func=cmd_github)

    gh_search = gh_sub.add_parser(
        "search",
        help="search other public repos (ideas for continuous improvement)",
    )
    gh_search.add_argument("query", help='e.g. "multi agent orchestration durable"')
    gh_search.add_argument("--limit", type=int, default=10)
    gh_search.add_argument("--language", default=None, help="e.g. Python")
    gh_search.set_defaults(func=cmd_github)

    gh_scout = gh_sub.add_parser(
        "scout",
        help="search → clone/pull related repos → prove with checks → notes",
    )
    gh_scout.add_argument("query", help="topic / keywords to find other repos")
    gh_scout.add_argument("--repo", dest="repo_flag", default=None)
    gh_scout.add_argument("--workdir", default=None)
    gh_scout.add_argument("--limit", type=int, default=8)
    gh_scout.add_argument("--language", default=None)
    gh_scout.add_argument(
        "--shallow",
        action="store_true",
        help="skip README deep fetch",
    )
    gh_scout.add_argument(
        "--connect",
        action="store_true",
        default=True,
        help="clone/pull hits into .nexus_workspaces/scout_repos/ (default on)",
    )
    gh_scout.add_argument(
        "--no-connect",
        action="store_true",
        help="search + notes only (no clone)",
    )
    gh_scout.add_argument(
        "--no-prove",
        action="store_true",
        help="clone/pull but skip install/test evidence",
    )
    gh_scout.add_argument(
        "--structure-only",
        action="store_true",
        help="prove layout/languages only (no install/pytest)",
    )
    gh_scout.add_argument(
        "--no-pull",
        action="store_true",
        help="if already cloned, do not git pull",
    )
    gh_scout.add_argument(
        "--issue",
        action="store_true",
        help="open a tracking issue on your repo",
    )
    gh_scout.add_argument(
        "--apply",
        action="store_true",
        help="run nexus do informed by scouted repos (opt-in)",
    )
    gh_scout.add_argument("--dry-run", action="store_true")
    gh_scout.set_defaults(func=cmd_github)

    gh_conn = gh_sub.add_parser(
        "connect",
        help="clone/pull one external repo and prove it (local workspace)",
    )
    gh_conn.add_argument("slug", help="owner/repo")
    gh_conn.add_argument("--workdir", default=None)
    gh_conn.add_argument("--no-pull", action="store_true")
    gh_conn.add_argument("--no-prove", action="store_true")
    gh_conn.add_argument("--structure-only", action="store_true")
    gh_conn.set_defaults(func=cmd_github)

    gh_imp = gh_sub.add_parser(
        "improve",
        help="arXiv + optional repo scout → notes (+ optional fix job)",
    )
    gh_imp.add_argument(
        "--arxiv",
        "--query",
        dest="arxiv",
        default=None,
        help='topic / arXiv query, e.g. "durable multi-agent systems"',
    )
    gh_imp.add_argument(
        "--scout",
        default=None,
        help="also search related GitHub repos (or use alone without --arxiv)",
    )
    gh_imp.add_argument(
        "--with-scout",
        action="store_true",
        help="when using --arxiv, also scout GitHub with the same query",
    )
    gh_imp.add_argument("--repo", dest="repo_flag", default=None)
    gh_imp.add_argument("--workdir", default=None)
    gh_imp.add_argument("--max", type=int, default=6)
    gh_imp.add_argument("--pdf", action="store_true", help="download PDFs")
    gh_imp.add_argument(
        "--apply",
        action="store_true",
        help="after research/scout, run nexus do to try applying insights (opt-in)",
    )
    gh_imp.add_argument(
        "--no-issue",
        action="store_true",
        help="do not open a tracking GitHub issue",
    )
    gh_imp.add_argument("--shallow", action="store_true")
    gh_imp.add_argument("--dry-run", action="store_true")
    gh_imp.set_defaults(func=cmd_github)


    gh_mine = gh_sub.add_parser(
        "mine",
        help="discover+grade+USE other repos (clone/prove) — never follow/star",
    )
    gh_mine_sub = gh_mine.add_subparsers(dest="mine_cmd")
    mf = gh_mine_sub.add_parser("fetch", help="search GitHub → SQLite (no social actions)")
    mf.add_argument("--query", "-q", default="multi agent orchestration")
    mf.add_argument("--count", "-n", type=int, default=8)
    mf.add_argument("--language", default="Python")
    mf.add_argument("--max-stars", type=int, default=500)
    mf.add_argument("--workdir", default=None)
    mf.set_defaults(func=cmd_github)
    me = gh_mine_sub.add_parser(
        "evaluate",
        help="clone + grade (Grok hard → local Ollama light → heuristic)",
    )
    me.add_argument("--limit", "-l", type=int, default=10)
    me.add_argument("--workdir", default=None)
    me.add_argument("--heuristic-only", action="store_true")
    me.add_argument(
        "--grader",
        choices=["auto", "grok", "ollama", "heuristic"],
        default="auto",
        help="auto=Grok then Ollama then heuristic (default)",
    )
    me.add_argument("--model", default=None, help="Ollama model (light fallback)")
    me.set_defaults(func=cmd_github)
    mu = gh_mine_sub.add_parser("use", help="keep high scores: connect+prove+notes for YOUR code")
    mu.add_argument("--min-score", type=float, default=12.0)
    mu.add_argument("--limit", type=int, default=5)
    mu.add_argument("--workdir", default=None)
    mu.add_argument("--no-prove", action="store_true")
    mu.add_argument("--structure-only", action="store_true")
    mu.set_defaults(func=cmd_github)
    ml = gh_mine_sub.add_parser("list", help="list graded / used repos")
    ml.add_argument("--min-score", type=float, default=0.0)
    ml.add_argument("--used", action="store_true")
    ml.add_argument("--limit", type=int, default=30)
    ml.add_argument("--workdir", default=None)
    ml.set_defaults(func=cmd_github)
    mi = gh_mine_sub.add_parser(
        "improve-ours",
        help="from scored clones → plan (and optional --apply) to improve THIS project",
    )
    mi.add_argument("--min-score", type=float, default=12.0)
    mi.add_argument("--limit", type=int, default=3)
    mi.add_argument("--workdir", default=None)
    mi.add_argument("--repo", dest="repo_flag", default=None, help="owner/name for --apply job")
    mi.add_argument("--apply", action="store_true", help="hard apply (Grok by default; opt-in)")
    mi.add_argument(
        "--worker",
        choices=["auto", "grok", "bus"],
        default="auto",
        help="auto/grok=Grok hard work; bus=local panel job",
    )
    mi.add_argument("--dry-run", action="store_true")
    mi.set_defaults(func=cmd_github)
    mr = gh_mine_sub.add_parser("run", help="fetch → evaluate → use (full pipeline)")
    mr.add_argument("--query", "-q", default="multi agent durable resume")
    mr.add_argument("--count", "-n", type=int, default=6)
    mr.add_argument("--limit", "-l", type=int, default=6)
    mr.add_argument("--use-limit", type=int, default=4)
    mr.add_argument("--min-score", type=float, default=12.0)
    mr.add_argument("--language", default="Python")
    mr.add_argument("--max-stars", type=int, default=500)
    mr.add_argument("--workdir", default=None)
    mr.add_argument("--heuristic-only", action="store_true")
    mr.add_argument(
        "--grader",
        choices=["auto", "grok", "ollama", "heuristic"],
        default="auto",
        help="auto=Grok grades hard, local LLM light fallback",
    )
    mr.add_argument(
        "--worker",
        choices=["auto", "grok", "bus"],
        default="auto",
        help="hard improve worker when --apply",
    )
    mr.add_argument("--no-prove", action="store_true")
    mr.add_argument("--improve", action="store_true", help="also write IMPROVE_OURS.md")
    mr.add_argument("--apply", action="store_true", help="with --improve, run hard apply")
    mr.add_argument("--repo", dest="repo_flag", default=None)
    mr.set_defaults(func=cmd_github)
    gh_mine.set_defaults(func=cmd_github, mine_cmd="run")

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

    # --- multi-platform mesh (Grok CLI, Cursor, local LLM tools) ---
    pl = sub.add_parser(
        "platforms",
        help="detect/connect Grok CLI, Cursor, Claude; local LLM gets full tools",
    )
    pl_sub = pl.add_subparsers(dest="platforms_cmd")
    pl_st = pl_sub.add_parser("status", help="show installed platforms + agent ids")
    pl_st.add_argument("--path", default=".", help="project root")
    pl_st.set_defaults(func=cmd_platforms)
    pl_co = pl_sub.add_parser(
        "connect",
        help="auto-wire MCP + local model so all agents share NEXUS tools",
    )
    pl_co.add_argument("--path", default=".", help="project root")
    pl_co.add_argument("--force", action="store_true", help="overwrite existing MCP entries")
    pl_co.add_argument("--no-grok", action="store_true")
    pl_co.add_argument("--no-cursor", action="store_true")
    pl_co.add_argument("--no-claude", action="store_true")
    pl_co.add_argument(
        "--no-local-model",
        action="store_true",
        help="do not register Ollama endpoint in Grok config",
    )
    pl_co.add_argument(
        "--model",
        default=None,
        help="Ollama model name for Grok [model.nexus-local]",
    )
    pl_co.add_argument(
        "--start",
        action="store_true",
        help="also nexus start -y so local agent is on the bus",
    )
    pl_co.set_defaults(func=cmd_platforms)
    pl_flow = pl_sub.add_parser("flow", help="print agent ingress/handoff map as JSON")
    pl_flow.set_defaults(func=cmd_platforms)
    pl_doc = pl_sub.add_parser(
        "doctor",
        help="diagnose MCP/local LLM wiring; --fix re-runs connect --force",
    )
    pl_doc.add_argument("--path", default=".")
    pl_doc.add_argument("--fix", action="store_true")
    pl_doc.set_defaults(func=cmd_platforms)
    pl.set_defaults(func=cmd_platforms, platforms_cmd="status")

    # --- heartbeat / dead-man + recovery ---
    hb = sub.add_parser(
        "heartbeat",
        help="ping cloud dead-man URL (Healthchecks) so you're poked when the host dies",
    )
    hb_sub = hb.add_subparsers(dest="heartbeat_cmd")
    hb_init = hb_sub.add_parser("init", help="save ping URL to .nexus_state/heartbeat.json")
    hb_init.add_argument("--url", required=True, help="Healthchecks ping URL or webhook")
    hb_init.add_argument("--status-url", default="", help="optional status URL for Actions")
    hb_init.add_argument("--webhook", default="", help="Discord/Slack webhook for local alerts")
    hb_init.add_argument("--host-id", default="")
    hb_init.add_argument("--interval", type=int, default=300)
    hb_init.add_argument("--path", default=".")
    hb_init.set_defaults(func=cmd_heartbeat)
    hb_once = hb_sub.add_parser("once", help="single beat (cron-friendly)")
    hb_once.add_argument("--path", default=".")
    hb_once.add_argument("--dry-run", action="store_true")
    hb_once.set_defaults(func=cmd_heartbeat)
    hb_w = hb_sub.add_parser("watch", help="loop beats until Ctrl-C")
    hb_w.add_argument("--path", default=".")
    hb_w.add_argument("--interval", type=float, default=0, help="seconds (default from config)")
    hb_w.add_argument("--max-beats", type=int, default=0)
    hb_w.set_defaults(func=cmd_heartbeat)
    hb_st = hb_sub.add_parser("status", help="last beat + network probe")
    hb_st.add_argument("--path", default=".")
    hb_st.set_defaults(func=cmd_heartbeat)
    hb_cron = hb_sub.add_parser("install-cron", help="print crontab + setup instructions")
    hb_cron.add_argument("--path", default=".")
    hb_cron.add_argument("--every", type=int, default=5, help="minutes between pings")
    hb_cron.set_defaults(func=cmd_heartbeat)
    hb.set_defaults(func=cmd_heartbeat, heartbeat_cmd="once")

    rc = sub.add_parser(
        "recovery",
        help="diagnose network; opt-in WiFi reconnect; reboot only with double gate",
    )
    rc_sub = rc.add_subparsers(dest="recovery_cmd")
    rc_sub.add_parser("status", help="tools + network + last heartbeat").set_defaults(
        func=cmd_recovery
    )
    rc_sub.add_parser("network", help="diagnose connectivity only").set_defaults(
        func=cmd_recovery
    )
    rc_wifi = rc_sub.add_parser("wifi", help="WiFi diagnose / optional nmcli reconnect")
    rc_wifi.add_argument(
        "--allow-reconnect",
        action="store_true",
        help="actually try nmcli reconnect (default is diagnose-only)",
    )
    rc_wifi.add_argument("--connection", default=None, help="nmcli connection name")
    rc_wifi.set_defaults(func=cmd_recovery)
    rc_rb = rc_sub.add_parser("reboot", help="reboot host (DANGEROUS — double gate)")
    rc_rb.add_argument("--allow-reboot", action="store_true")
    rc_rb.set_defaults(func=cmd_recovery)
    rc_auto = rc_sub.add_parser("auto", help="diagnose → optional wifi → optional reboot")
    rc_auto.add_argument("--allow-reconnect", action="store_true")
    rc_auto.add_argument("--allow-reboot", action="store_true")
    rc_auto.set_defaults(func=cmd_recovery)
    rc.set_defaults(func=cmd_recovery, recovery_cmd="status")

    sch = sub.add_parser(
        "schedule",
        help="print cron lines: heartbeat + mine + optional MCP for ChatGPT/Claude",
    )
    sch.add_argument("--path", default=".")
    sch.add_argument("--query", "-q", default="multi agent durable")
    sch.add_argument("--no-heartbeat", action="store_true")
    sch.add_argument("--no-mine", action="store_true")
    sch.add_argument(
        "--mcp-http",
        action="store_true",
        help="include @reboot nexus mcp --http (tunnel for ChatGPT connectors)",
    )
    sch.set_defaults(func=cmd_schedule)

    ops = sub.add_parser(
        "ops",
        help="mission-control ops plane: jobs + spend (list/show/record)",
    )
    ops_sub = ops.add_subparsers(dest="ops_cmd")
    ops_list = ops_sub.add_parser("list", help="list jobs")
    ops_list.add_argument("--path", default=".")
    ops_list.add_argument("--kind", default=None, help="filter: mine|alive|improve|task|…")
    ops_list.add_argument("--status", default=None, help="filter: running|completed|…")
    ops_list.add_argument("--limit", type=int, default=50)
    ops_list.add_argument("--json", action="store_true")
    ops_list.set_defaults(func=cmd_ops)
    ops_show = ops_sub.add_parser("show", help="show one job + spend rollup")
    ops_show.add_argument("job_id")
    ops_show.add_argument("--path", default=".")
    ops_show.set_defaults(func=cmd_ops)
    ops_sp = ops_sub.add_parser("spend", help="spend report (optional job_id)")
    ops_sp.add_argument("job_id", nargs="?", default=None)
    ops_sp.add_argument("--path", default=".")
    ops_sp.set_defaults(func=cmd_ops)
    ops_rec = ops_sub.add_parser("record", help="upsert job + record token spend")
    ops_rec.add_argument("job_id")
    ops_rec.add_argument("--tokens", type=int, required=True)
    ops_rec.add_argument("--path", default=".")
    ops_rec.add_argument("--kind", default="task")
    ops_rec.add_argument("--title", default=None)
    ops_rec.add_argument("--status", default="running")
    ops_rec.add_argument("--goal", default="")
    ops_rec.add_argument("--source", default="manual")
    ops_rec.add_argument("--label", default="")
    ops_rec.add_argument(
        "--usage",
        action="store_true",
        help="also append global usage ledger",
    )
    ops_rec.set_defaults(func=cmd_ops)
    ops_st = ops_sub.add_parser("status", help="ops dashboard summary")
    ops_st.add_argument("--path", default=".")
    ops_st.set_defaults(func=cmd_ops)
    ops_in = ops_sub.add_parser(
        "ingest",
        help="backfill spend from usage ledger rows with meta.task_id",
    )
    ops_in.add_argument("--path", default=".")
    ops_in.set_defaults(func=cmd_ops)
    ops_ss = ops_sub.add_parser("set-status", help="set job status")
    ops_ss.add_argument("job_id")
    ops_ss.add_argument("status", help="inbox|running|blocked|completed|failed|cancelled")
    ops_ss.add_argument("--path", default=".")
    ops_ss.set_defaults(func=cmd_ops)
    ops.set_defaults(func=cmd_ops, ops_cmd="list")

    us = sub.add_parser("usage", help="token budget / throttle (daily/monthly caps)")
    us_sub = us.add_subparsers(dest="usage_cmd")
    us_st = us_sub.add_parser("status", help="show budget + counters")
    us_st.add_argument("--path", default=".")
    us_st.set_defaults(func=cmd_usage)
    us_set = us_sub.add_parser("set", help="configure budget")
    us_set.add_argument("--path", default=".")
    us_set.add_argument("--daily", type=int, default=None)
    us_set.add_argument("--monthly", type=int, default=None)
    us_set.add_argument("--per-call", type=int, default=None)
    us_set.add_argument("--off", action="store_true")
    us_set.add_argument("--on", action="store_true")
    us_set.add_argument("--soft", action="store_true", help="warn only, do not block")
    us_set.add_argument("--hard", action="store_true", help="block when over budget")
    us_set.set_defaults(func=cmd_usage)
    us_rec = us_sub.add_parser("record", help="manually record tokens")
    us_rec.add_argument("--tokens", type=int, required=True)
    us_rec.add_argument("--source", default="manual")
    us_rec.add_argument("--label", default="")
    us_rec.add_argument("--path", default=".")
    us_rec.add_argument("--force", action="store_true")
    us_rec.set_defaults(func=cmd_usage)
    us_rs = us_sub.add_parser("reset-day", help="archive ledger and start fresh")
    us_rs.add_argument("--path", default=".")
    us_rs.set_defaults(func=cmd_usage)
    us.set_defaults(func=cmd_usage, usage_cmd="status")

    alv = sub.add_parser(
        "alive",
        help="self-improvement loop under user goals + token budget",
    )
    al_sub = alv.add_subparsers(dest="alive_cmd")
    al_i = al_sub.add_parser("init", help="set goal / self-approve / apply policy")
    al_i.add_argument("--path", default=".")
    al_i.add_argument("--goal", default=None)
    al_i.add_argument("--query", "-q", default=None)
    al_i.add_argument("--repo", default=None)
    al_i.add_argument("--apply", action="store_true", help="allow code apply step")
    al_i.add_argument(
        "--self-approve",
        action="store_true",
        help="auto-apply when tests pass (needs --apply)",
    )
    al_i.add_argument(
        "--push-github",
        action="store_true",
        help="after green tests, commit + push allowlisted files to origin",
    )
    al_i.add_argument("--no-push-github", action="store_true")
    al_i.add_argument("--interval", type=int, default=None)
    al_i.add_argument(
        "--grader",
        choices=["auto", "grok", "ollama", "heuristic"],
        default=None,
        help="hard grading: auto/grok preferred; ollama=local light only",
    )
    al_i.add_argument(
        "--worker",
        choices=["auto", "grok", "bus"],
        default=None,
        help="hard improve worker (default auto→Grok)",
    )
    al_i.set_defaults(func=cmd_alive)
    al_s = al_sub.add_parser("status")
    al_s.add_argument("--path", default=".")
    al_s.set_defaults(func=cmd_alive)
    al_o = al_sub.add_parser("once", help="one self-improve cycle")
    al_o.add_argument("--path", default=".")
    al_o.add_argument("--dry-run", action="store_true")
    al_o.set_defaults(func=cmd_alive)
    al_w = al_sub.add_parser("watch", help="loop cycles until Ctrl-C")
    al_w.add_argument("--path", default=".")
    al_w.add_argument("--interval", type=float, default=0)
    al_w.add_argument("--max-cycles", type=int, default=0)
    al_w.set_defaults(func=cmd_alive)
    al_g = al_sub.add_parser(
        "gaps",
        help="P1.5 principled-stop gap board (list / --seed / --close)",
    )
    al_g.add_argument("--path", default=".")
    al_g.add_argument("--seed", action="store_true", help="seed from LATEST_IMPROVE_PLAN / IMPROVE_OURS")
    al_g.add_argument(
        "--reopen",
        action="store_true",
        help="with --seed, re-open gaps that were previously closed",
    )
    al_g.add_argument("--close", default=None, metavar="ID", help="close a gap id")
    al_g.add_argument("--evidence", default="", help="evidence when --close")
    al_g.add_argument("--json", action="store_true")
    al_g.set_defaults(func=cmd_alive)
    alv.set_defaults(func=cmd_alive, alive_cmd="status")

    vlt = sub.add_parser(
        "vault",
        help="secrets vault: presence checks + redaction (never prints values)",
    )
    vlt_sub = vlt.add_subparsers(dest="vault_cmd")
    vlt_st = vlt_sub.add_parser("status", help="which known keys are configured (booleans only)")
    vlt_st.add_argument("--path", default=".")
    vlt_st.set_defaults(func=cmd_vault)
    vlt_ck = vlt_sub.add_parser("check", help="exit 0 if key present")
    vlt_ck.add_argument("key")
    vlt_ck.add_argument("--path", default=".")
    vlt_ck.set_defaults(func=cmd_vault)
    vlt_rd = vlt_sub.add_parser("redact", help="mask known secret values in text")
    vlt_rd.add_argument("text", nargs="?", default="", help="text to redact (or - for stdin)")
    vlt_rd.add_argument("--stdin", action="store_true")
    vlt_rd.add_argument("--path", default=".")
    vlt_rd.set_defaults(func=cmd_vault)
    vlt.set_defaults(func=cmd_vault, vault_cmd="status")

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

    # --- durable task inspect (event journal / operator surface) ---
    tk = sub.add_parser("task", help="list / inspect durable tasks and event journals")
    tk_sub = tk.add_subparsers(dest="task_cmd", required=True)
    tk_list = tk_sub.add_parser("list", help="list checkpointed tasks")
    tk_list.add_argument(
        "--state-dir",
        default=None,
        help="state directory (default: .nexus_state or NEXUS_STATE_DIR)",
    )
    tk_list.set_defaults(func=cmd_task)
    tk_ev = tk_sub.add_parser("events", help="pretty-print append-only task event journal")
    tk_ev.add_argument("task_id", help="task id (e.g. t1)")
    tk_ev.add_argument("--limit", type=int, default=50, help="show last N events (default 50)")
    tk_ev.add_argument("--json", action="store_true", help="emit raw JSON array")
    tk_ev.add_argument(
        "--state-dir",
        default=None,
        help="state directory (default: .nexus_state or NEXUS_STATE_DIR)",
    )
    tk_ev.set_defaults(func=cmd_task)
    tk_show = tk_sub.add_parser("show", help="show task checkpoint JSON summary")
    tk_show.add_argument("task_id")
    tk_show.add_argument("--state-dir", default=None)
    tk_show.set_defaults(func=cmd_task)
    tk_replay = tk_sub.add_parser(
        "replay",
        help="normalized decision timeline from journal (no re-run; plan-replay)",
    )
    tk_replay.add_argument("task_id")
    tk_replay.add_argument(
        "--limit", type=int, default=0, help="last N events (0 = all)"
    )
    tk_replay.add_argument("--json", action="store_true", help="emit JSON array")
    tk_replay.add_argument("--state-dir", default=None)
    tk_replay.set_defaults(func=cmd_task)
    tk_explain = tk_sub.add_parser(
        "explain",
        help="causal decision chain (steps, handoffs, vetoes, judge why)",
    )
    tk_explain.add_argument("task_id")
    tk_explain.add_argument("--json", action="store_true", help="emit JSON object")
    tk_explain.add_argument("--state-dir", default=None)
    tk_explain.set_defaults(func=cmd_task)
    tk_cost = tk_sub.add_parser(
        "cost",
        help="task token/score rollup (mission-control cost tracker; journal-based)",
    )
    tk_cost.add_argument("task_id")
    tk_cost.add_argument("--json", action="store_true", help="emit JSON object")
    tk_cost.add_argument("--state-dir", default=None)
    tk_cost.set_defaults(func=cmd_task)
    tk_prov = tk_sub.add_parser(
        "prov",
        help="PROV-style provenance export (agents/activities/entities/relations)",
    )
    tk_prov.add_argument("task_id")
    tk_prov.add_argument("--json", action="store_true", help="emit full JSON document")
    tk_prov.add_argument("--state-dir", default=None)
    tk_prov.set_defaults(func=cmd_task)
    tk_verify = tk_sub.add_parser(
        "verify",
        help="checkpoint ↔ journal integrity checks (durability gate)",
    )
    tk_verify.add_argument("task_id")
    tk_verify.add_argument("--json", action="store_true", help="emit JSON report")
    tk_verify.add_argument("--state-dir", default=None)
    tk_verify.set_defaults(func=cmd_task)
    tk_graph = tk_sub.add_parser(
        "graph",
        help="agent call-graph + space-time sequence (MAS profiling; read-only)",
    )
    tk_graph.add_argument("task_id")
    tk_graph.add_argument("--json", action="store_true", help="emit full JSON document")
    tk_graph.add_argument(
        "--mermaid",
        action="store_true",
        help="also print mermaid flowchart block",
    )
    tk_graph.add_argument("--state-dir", default=None)
    tk_graph.set_defaults(func=cmd_task)
    tk_dag = tk_sub.add_parser(
        "dag",
        help="multi-agent task dependency DAG + action_order (P1.2; read-only)",
    )
    tk_dag.add_argument("task_id")
    tk_dag.add_argument("--json", action="store_true", help="emit full JSON document")
    tk_dag.add_argument(
        "--mermaid",
        action="store_true",
        help="also print mermaid flowchart of step dependencies",
    )
    tk_dag.add_argument("--state-dir", default=None)
    tk_dag.set_defaults(func=cmd_task)
    tk_cons = tk_sub.add_parser(
        "consensus",
        help="multi-grader consensus pack (findings + trust weights; P1.3)",
    )
    tk_cons.add_argument("task_id")
    tk_cons.add_argument("--json", action="store_true", help="emit full JSON document")
    tk_cons.add_argument(
        "--findings",
        action="store_true",
        help="also print per-grader findings from step verdicts",
    )
    tk_cons.add_argument("--state-dir", default=None)
    tk_cons.set_defaults(func=cmd_task)
    tk_ctx = tk_sub.add_parser(
        "context",
        help="bounded multi-source context pack (goal/journal/memory; P1.4)",
    )
    tk_ctx.add_argument("task_id")
    tk_ctx.add_argument("--json", action="store_true", help="emit full JSON document")
    tk_ctx.add_argument(
        "--prompt",
        action="store_true",
        help="emit markdown prompt block only (for agent injection)",
    )
    tk_ctx.add_argument(
        "--research",
        action="store_true",
        help="include latest arXiv improve notes from .nexus_state/arxiv_improve",
    )
    tk_ctx.add_argument(
        "--repos",
        action="store_true",
        help="include mined repo digests from IMPROVE_OURS / USE_LATEST",
    )
    tk_ctx.add_argument(
        "--journal-limit",
        type=int,
        default=8,
        help="last-N journal events in pack (default 8)",
    )
    tk_ctx.add_argument(
        "--out",
        default=None,
        help="write JSON pack to path (atomic write-then-rename)",
    )
    tk_ctx.add_argument("--state-dir", default=None)
    tk_ctx.set_defaults(func=cmd_task)
    tk_evd = tk_sub.add_parser(
        "evidence",
        help="portable evidence pack (norms + gates + timeline + cost + prov + graph)",
    )
    tk_evd.add_argument("task_id")
    tk_evd.add_argument("--json", action="store_true", help="emit full JSON evidence pack")
    tk_evd.add_argument(
        "--compact",
        action="store_true",
        help="omit full provenance relations / graph sequence (summaries only)",
    )
    tk_evd.add_argument(
        "--out",
        default=None,
        help="write JSON pack to path (atomic write-then-rename)",
    )
    tk_evd.add_argument("--state-dir", default=None)
    tk_evd.set_defaults(func=cmd_task)
    tk_resume = tk_sub.add_parser(
        "resume",
        help="continue a checkpointed task; HITL --approve/--reject when waiting_human",
    )
    tk_resume.add_argument("task_id")
    tk_resume.add_argument(
        "--approve",
        action="store_true",
        help="approve a waiting_human gate and continue",
    )
    tk_resume.add_argument(
        "--reject",
        action="store_true",
        help="reject a waiting_human gate (fail-closed)",
    )
    tk_resume.add_argument(
        "--feedback",
        default=None,
        help="optional human feedback stored on the approval step",
    )
    tk_resume.add_argument("--json", action="store_true", help="emit task checkpoint JSON")
    tk_resume.add_argument("--state-dir", default=None)
    tk_resume.set_defaults(func=cmd_task)

    sk = sub.add_parser(
        "skillpacks",
        help="multi-harness skill packs: list / validate / generate / drift (P2.1)",
    )
    sk_sub = sk.add_subparsers(dest="skillpacks_cmd")
    sk_list = sk_sub.add_parser("list", help="list skill packs under skillpacks/")
    sk_list.add_argument("--path", default=None, help="project root (default: cwd)")
    sk_list.add_argument("--packs-dir", default="skillpacks")
    sk_list.add_argument("--json", action="store_true")
    sk_list.add_argument("--validate", action="store_true", help="include valid flag")
    sk_list.add_argument(
        "--max-privilege",
        default=None,
        choices=["read", "write", "ops", "admin"],
        help="filter packs above this privilege (least-privilege)",
    )
    sk_list.set_defaults(func=cmd_skillpacks)
    sk_val = sk_sub.add_parser("validate", help="structural validate (source of truth)")
    sk_val.add_argument("pack", nargs="?", default=None, help="optional pack id")
    sk_val.add_argument("--path", default=None)
    sk_val.add_argument("--packs-dir", default="skillpacks")
    sk_val.add_argument("--json", action="store_true")
    sk_val.set_defaults(func=cmd_skillpacks)
    sk_gen = sk_sub.add_parser(
        "generate",
        help="emit multi-harness stubs from SKILL.md + manifest",
    )
    sk_gen.add_argument("pack", nargs="?", default=None, help="optional pack id")
    sk_gen.add_argument("--path", default=None)
    sk_gen.add_argument("--packs-dir", default="skillpacks")
    sk_gen.add_argument(
        "--out",
        default=None,
        help="output root (default: .nexus_state/generated_skillpacks)",
    )
    sk_gen.add_argument(
        "--harness",
        action="append",
        default=None,
        choices=["grok", "cursor", "claude", "codex", "local"],
        help="limit harnesses (repeatable)",
    )
    sk_gen.add_argument("--clean", action="store_true", help="remove prior artifacts first")
    sk_gen.add_argument(
        "--max-privilege",
        default=None,
        choices=["read", "write", "ops", "admin"],
    )
    sk_gen.add_argument("--json", action="store_true")
    sk_gen.set_defaults(func=cmd_skillpacks)
    sk_dr = sk_sub.add_parser(
        "drift",
        help="detect missing/stale generated harness artifacts",
    )
    sk_dr.add_argument("--path", default=None)
    sk_dr.add_argument("--packs-dir", default="skillpacks")
    sk_dr.add_argument("--out", default=None, help="generated root to check")
    sk_dr.add_argument("--json", action="store_true")
    sk_dr.set_defaults(func=cmd_skillpacks)

    args = ap.parse_args(raw)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
