#!/usr/bin/env python3
"""SWE-bench Pro multi-AI campaign: Claude + Codex + Grok + Gemini + local.

Does NOT replace the official Pro Docker harness. This:
  1) Posts a campaign brief to the workspace (all agents see roles)
  2) Starts the multi-vendor bus (CLI bridges)
  3) Runs a durable multi-agent task with group-review objective
  4) Optionally kicks arXiv research (Gemini-oriented handoff)

  PYTHONPATH=src python3 scripts/swe_pro_multi_ai.py --once
  PYTHONPATH=src python3 scripts/swe_pro_multi_ai.py --once --research "SWE-bench Pro agent"

Memory: if NVFP4 vLLM is up (~80-90GiB), prefer CLI-only agents; avoid heavy Ollama.
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
os.environ.setdefault("NEXUS_CLI_TIMEOUT_S", "360")
os.environ.setdefault("NEXUS_MSG_TIMEOUT_MS", "360000")

from nexus import DurableEngine, Settings, Task  # noqa: E402
from nexus.agents import AgentPanel, DEFAULT_ROLE_TO_BUS  # noqa: E402
from nexus.bus_client import BusClient  # noqa: E402
from nexus.cli import cmd_start  # noqa: E402
import argparse as ap_mod  # noqa: E402

LOG = ROOT / ".nexus_state" / "swe_pro_multi_ai.log"
CHAT = ROOT / ".nexus" / "workspace" / "chat.jsonl"
BRIEF = ROOT / ".nexus_state" / "swe_pro" / "campaign_brief.json"


def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def nvfp_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/v1/models", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def bus_port() -> int:
    meta = ROOT / ".nexus_state" / "runtime.json"
    if meta.is_file():
        try:
            return int(json.loads(meta.read_text()).get("bus_port") or 3099)
        except Exception:
            pass
    return int(os.environ.get("NEXUS_BUS_PORT") or 3099)


def ensure_stack(*, light_local: bool) -> int:
    port = bus_port()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            if r.status == 200:
                _log(f"bus already up on :{port}")
                return port
    except Exception:
        pass
    _log("starting NEXUS stack (CLI agents: claude, codex/gpt, grok, gemini)…")
    if light_local:
        # Prefer small model if Ollama must start — avoid fighting NVFP
        os.environ.setdefault("OLLAMA_MODEL", "e2b-fast")
    ns = ap_mod.Namespace(
        yes=True,
        model=os.environ.get("OLLAMA_MODEL"),
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
    return bus_port()


def post_workspace(agent: str, text: str, label: str = "swe-pro") -> None:
    CHAT.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.time(),
        "agent": agent,
        "label": label,
        "text": text,
    }
    with CHAT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def campaign_brief() -> dict:
    brief = {
        "campaign": "swe-bench-pro-multi-ai",
        "benchmark": "SWE-bench Pro (official harness only for score)",
        "aspiration": "maximize resolve rate; 100% is not currently realistic on Pro",
        "roles": {
            "claude": "plan + line-by-line review L1",
            "grok": "implement patches",
            "gpt": "Codex/ChatGPT adversary + review L2",
            "gemini": "web + arXiv research",
            "local": "local files, logs, prior failures under .nexus_state",
        },
        "protocol": [
            "Grok implements",
            "Claude reviews line-by-line",
            "Codex/ChatGPT adversarial review",
            "Gemini posts external evidence",
            "Local greps repo/logs",
            "Revise until reviews clear",
            "Score only with official Pro Docker eval",
        ],
        "docs": "docs/SWE_BENCH_PRO_MULTI_AI.md",
        "skill": "skillpacks/swe-pro-group-review/",
        "ts": time.time(),
    }
    BRIEF.parent.mkdir(parents=True, exist_ok=True)
    BRIEF.write_text(json.dumps(brief, indent=2) + "\n", encoding="utf-8")
    return brief


def announce_roles(brief: dict) -> None:
    post_workspace(
        "nexus",
        "SWE-bench Pro multi-AI campaign started. Official Pro harness = only score. "
        "Skill: swe-pro-group-review. Roles: Claude plan/review, Grok implement, "
        "Codex/ChatGPT adversary/review, Gemini arXiv/web, local files.",
        "campaign",
    )
    for agent, job in brief["roles"].items():
        post_workspace(agent, f"Role assignment: {job}", "role")
    _log(f"workspace brief → {CHAT}")


def run_group_task(port: int) -> dict:
    """Durable multi-vendor task with multi-review objective."""
    role_map = dict(DEFAULT_ROLE_TO_BUS)
    role_map.update(
        {
            "planner": "claude",
            "adversary": "grok",
            "implementer": "gpt",
            "tester": "local",
            "reviewer": "claude",
            "logger": "gemini",  # research/logger slot → Gemini when bridge is up
            "local": "local",
        }
    )
    base = f"http://127.0.0.1:{port}"
    bus = BusClient(base_url=base)
    if not bus.is_reachable():
        return {"ok": False, "error": f"bus not reachable {base}"}

    panel = AgentPanel.from_bus(
        bus,
        role_map=role_map,
        base_url=base,
        mock_fallback=True,
    )
    health = panel.health()
    _log(f"panel health: {health}")

    tid = f"swe-pro-mv-{int(time.time())}"
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
            "SWE-bench Pro multi-AI dry-run collaboration: "
            "Claude plans a rigorous fix strategy; Grok challenges it; "
            "Codex implements a DEMO_OK artifact proving multi-file discipline; "
            "local verifies tests; Gemini records external research notes. "
            "Practice group review like a human PR team. "
            "Real Pro scoring requires official Docker harness + predictions.jsonl."
        ),
        success_criteria=[
            "artifact contains DEMO_OK",
            "multi-vendor handoffs recorded",
        ],
        namespace="proj/swe_pro_multi_ai",
        constraints=[
            "swe-bench-pro-campaign",
            "claude+gpt+grok+gemini+local",
            "group-review",
        ],
    )
    _log(f"=== durable SWE-Pro campaign task {tid} ===")
    t0 = time.time()
    task = engine.run(task)
    elapsed = round(time.time() - t0, 1)
    steps = []
    for n, out in sorted(task.outputs.items()):
        steps.append(
            {
                "step": n,
                "bus": out.get("_bus_agent"),
                "verdict": (out.get("_verdict") or {}).get("decision"),
            }
        )
        _log(
            f"  step {n}: bus={out.get('_bus_agent')} "
            f"verdict={(out.get('_verdict') or {}).get('decision')}"
        )
    rep = {
        "ok": task.status.value == "completed",
        "task_id": tid,
        "status": task.status.value,
        "elapsed_s": elapsed,
        "error": task.meta.get("error"),
        "steps": steps,
        "role_map": role_map,
        "panel_health": health,
        "note": "This is multi-AI collaboration practice; score Pro only with official harness",
    }
    outp = ROOT / ".nexus_state" / "swe_pro" / "last_multi_ai.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    post_workspace(
        "nexus",
        f"Campaign task {tid} status={task.status.value} elapsed={elapsed}s. "
        "Next: generate predictions.jsonl and run official SWE-bench Pro Docker eval.",
        "result",
    )
    _log(f"result → {outp}")
    return rep


def run_research(query: str) -> dict:
    """arXiv/research path (Gemini should lead externally; Nexus research is shared)."""
    from nexus.research_job import ResearchJobRunner

    _log(f"research: {query!r}")
    post_workspace("gemini", f"Fetching research for: {query}", "research")
    runner = ResearchJobRunner(
        project_root=ROOT,
        state_dir=ROOT / ".nexus_state" / "research_jobs",
    )
    # no LLM brief by default (saves NVFP/cloud); structured arXiv pull
    job = runner.run(query, max_results=8, with_brief=False, download_pdf=False)
    summary = {
        "job_id": job.job_id,
        "status": job.status,
        "n_papers": len(job.papers or []),
        "papers": [
            {"id": p.get("arxiv_id") or p.get("id"), "title": (p.get("title") or "")[:120]}
            for p in (job.papers or [])[:8]
            if isinstance(p, dict)
        ],
    }
    post_workspace(
        "gemini",
        f"Research done status={job.status} papers={summary['n_papers']}: "
        + "; ".join(
            f"{x.get('id')}: {x.get('title')}" for x in summary["papers"][:5]
        ),
        "research",
    )
    path = ROOT / ".nexus_state" / "swe_pro" / "last_research.json"
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SWE-bench Pro multi-AI campaign")
    p.add_argument("--once", action="store_true", help="one campaign cycle (default)")
    p.add_argument(
        "--research",
        default="",
        help="optional arXiv query for Gemini-oriented research handoff",
    )
    p.add_argument(
        "--skip-stack",
        action="store_true",
        help="do not start bus (workspace brief + research only)",
    )
    p.add_argument(
        "--force-ollama",
        action="store_true",
        help="start Ollama local even if NVFP is up (not recommended)",
    )
    args = p.parse_args(argv)

    _log("=== SWE-BENCH PRO MULTI-AI CAMPAIGN ===")
    if nvfp_up():
        _log("NVFP4 detected on :8000 — prefer CLI agents; avoid heavy Ollama")
        light = not args.force_ollama
    else:
        light = True

    brief = campaign_brief()
    announce_roles(brief)

    research_rep = None
    if args.research.strip():
        try:
            research_rep = run_research(args.research.strip())
        except Exception as e:
            _log(f"research error: {e}")
            research_rep = {"ok": False, "error": str(e)}

    if args.skip_stack:
        print(
            json.dumps(
                {"brief": brief, "research": research_rep, "stack": "skipped"},
                indent=2,
                default=str,
            )[:4000]
        )
        return 0

    port = ensure_stack(light_local=light)
    if not port:
        _log("bus failed — brief still written; start manually: nexus start -y")
        return 1

    rep = run_group_task(port)
    print(json.dumps({"brief": brief, "research": research_rep, "task": rep}, indent=2, default=str)[:5000])
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
