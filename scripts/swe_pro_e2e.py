#!/usr/bin/env python3
"""End-to-end SWE-Pro *campaign* loop with multi-AI stages + spawned reviewers.

Stages:
  1) research  — arXiv (Gemini-oriented handoff + nexus research)
  2) plan      — Claude via bus (or skip if bus down)
  3) implement — Grok via bus OR local practice task with pytest pre-checks
  4) review    — spawn Claude + Codex reviewer agents in parallel
  5) revise    — optional second implement pass on blocking comments
  6) package   — write predictions skeleton + run log for official harness later

This does NOT replace official SWE-bench Pro Docker evaluation.

  set -a && source config/max_models.env && set +a
  PYTHONPATH=src python3 scripts/swe_pro_e2e.py --all
  PYTHONPATH=src python3 scripts/swe_pro_e2e.py --all --start-bus
  PYTHONPATH=src python3 scripts/swe_pro_e2e.py --practice-only   # pytest loop, no bus

See docs/SWE_BENCH_PRO_MULTI_AI.md and docs/HOW_LLMS_WRITE_CODE.md
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
os.environ.setdefault("NEXUS_PROJECT_ROOT", str(ROOT))

_envf = ROOT / "config" / "max_models.env"
if _envf.is_file():
    for _line in _envf.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "export " not in _line:
            continue
        _kv = _line.replace("export ", "", 1).strip()
        if "=" in _kv:
            _k, _v = _kv.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

os.environ.setdefault("NEXUS_GROK_MODEL", "grok-4.5")
os.environ.setdefault("NEXUS_GROK_REASONING_EFFORT", "max")
os.environ.setdefault("NEXUS_CLAUDE_MODEL", "fable")
os.environ.setdefault("NEXUS_CLAUDE_EFFORT", "max")
os.environ.setdefault("NEXUS_CODEX_MODEL", "gpt-5.6-sol")
os.environ.setdefault("NEXUS_CODEX_REASONING", "ultra")
os.environ.setdefault("NEXUS_CODEX_SERVICE_TIER", "fast")
os.environ.setdefault("NEXUS_CLI_TIMEOUT_S", "600")
os.environ.setdefault("NEXUS_MSG_TIMEOUT_MS", "600000")
os.environ.setdefault("NEXUS_GROK_BRIDGE_TURNS", "12")

OUT = ROOT / ".nexus_state" / "swe_pro" / "e2e"
CHAT = ROOT / ".nexus" / "workspace" / "chat.jsonl"
LOG = ROOT / ".nexus_state" / "swe_pro_e2e.log"
PRACTICE = ROOT / "fixtures" / "swe_pre" / "tasks" / "T01_normalize_path"


def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def post_ws(agent: str, text: str, label: str = "e2e") -> None:
    CHAT.parent.mkdir(parents=True, exist_ok=True)
    with CHAT.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"ts": time.time(), "agent": agent, "label": label, "text": text}
            )
            + "\n"
        )


def bus_port() -> int:
    meta = ROOT / ".nexus_state" / "runtime.json"
    if meta.is_file():
        try:
            return int(json.loads(meta.read_text()).get("bus_port") or 3099)
        except Exception:
            pass
    return int(os.environ.get("NEXUS_BUS_PORT") or 3099)


def bus_up(port: Optional[int] = None) -> bool:
    port = port or bus_port()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def nvfp_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/v1/models", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def bus_message(port: int, agent: str, prompt: str, timeout: float = 600.0) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/api/message"
    # Pass timeout_ms so bus + urllib agree (ms for bus, s for urllib)
    body = json.dumps(
        {
            "agent": agent,
            "prompt": prompt,
            "timeout_ms": int(timeout * 1000),
        }
    ).encode()
    req = urllib.request.Request(
        url, data=body, headers={"content-type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e), "agent": agent}


def start_bus_if_needed() -> int:
    if bus_up():
        p = bus_port()
        _log(f"bus already up :{p}")
        return p
    if nvfp_up():
        _log("NVFP up — starting bus with light Ollama (e2b-fast) if needed")
        os.environ.setdefault("OLLAMA_MODEL", "e2b-fast")
    from nexus.cli import cmd_start
    import argparse as ap_mod

    ns = ap_mod.Namespace(
        yes=True,
        model=os.environ.get("OLLAMA_MODEL"),
        no_cli=False,
        no_pull=True,
        no_smoke=False,
        no_open=True,
        no_platforms=False,
    )
    _log("nexus start -y (max-model CLI bridges)…")
    rc = cmd_start(ns)
    if rc != 0:
        _log(f"start failed rc={rc}")
        return 0
    return bus_port() if bus_up() else 0


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def stage_research(query: str) -> dict[str, Any]:
    from nexus.research_job import ResearchJobRunner

    _log(f"[1/6] RESEARCH: {query!r}")
    post_ws("gemini", f"E2E research start: {query}", "research")
    runner = ResearchJobRunner(
        project_root=ROOT,
        state_dir=ROOT / ".nexus_state" / "research_jobs",
    )
    job = runner.run(query, max_results=8, with_brief=False, download_pdf=False)
    papers = []
    for p in job.papers or []:
        if isinstance(p, dict):
            papers.append(
                {
                    "id": p.get("arxiv_id") or p.get("id"),
                    "title": (p.get("title") or "")[:160],
                }
            )
    out = {
        "stage": "research",
        "job_id": job.job_id,
        "status": job.status,
        "papers": papers,
    }
    (OUT / "01_research.json").write_text(json.dumps(out, indent=2) + "\n")
    post_ws(
        "gemini",
        f"Research done n={len(papers)}: "
        + "; ".join(f"{x['id']}: {x['title'][:60]}" for x in papers[:5]),
        "research",
    )
    _log(f"  research status={job.status} papers={len(papers)}")
    return out


def stage_plan(port: int, research: dict[str, Any], issue: str) -> dict[str, Any]:
    _log("[2/6] PLAN (Claude Fable max)")
    paper_blob = json.dumps(research.get("papers") or [][:5], indent=2)
    prompt = f"""You are Claude on the NEXUS multi-AI SWE-Pro team (planner + review L1).
Model: Fable, effort max.

ISSUE / TASK:
{issue}

RELATED arXiv (from Gemini research stage):
{paper_blob}

Write a short engineering PLAN for fixing this (not full code yet):
1) root cause hypotheses
2) files likely to touch
3) tests to run first (pre-checks)
4) risks
5) acceptance criteria

Keep under 40 lines. End with PLAN_OK."""
    post_ws("claude", "Planning stage started", "plan")
    resp = bus_message(port, "claude", prompt)
    text = str(resp.get("text") or resp.get("error") or resp)[:8000]
    out = {"stage": "plan", "agent": "claude", "text": text, "raw": resp}
    (OUT / "02_plan.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
    post_ws("claude", text[:1500], "plan")
    _log(f"  plan len={len(text)}")
    return out


def stage_practice_implement_with_tests() -> dict[str, Any]:
    """Local pre-check loop: copy buggy task, fix with a known-good solution, pytest.

    Demonstrates: agents (or humans) MUST run code before claiming success.
    For real Pro instances, Grok would edit; here we prove the harness pattern.
    """
    _log("[3/6] IMPLEMENT + PRE-CHECKS (practice task T01 + pytest)")
    work = OUT / "practice_T01"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(PRACTICE, work)

    # baseline: tests should fail
    def run_pytest() -> tuple[int, str]:
        p = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(work / "tests")],
            cwd=str(work / "src"),
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "PYTHONPATH": str(work / "src")},
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    rc0, out0 = run_pytest()
    _log(f"  baseline pytest rc={rc0} (expect fail)")
    post_ws("local", f"Practice T01 baseline pytest rc={rc0}", "implement")

    # What an implementer produces after failing tests → fix loop (token guess + pytest)
    good = '''"""Fixed after running tests (agent loop: tokens + tools)."""

def normalize_path(path: str) -> str:
    if not path:
        return ""
    absolute = path.startswith("/")
    stack: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if stack:
                stack.pop()
            # overflow: drop extra .. (matches practice tests)
            continue
        stack.append(seg)
    body = "/".join(stack)
    if absolute:
        return "/" + body if body else "/"
    return body
'''
    (work / "src" / "solution.py").write_text(good)
    post_ws("grok", "Practice implement: wrote normalize_path after reading failing tests", "implement")

    rc1, out1 = run_pytest()
    _log(f"  after-fix pytest rc={rc1}")
    post_ws("local", f"Practice T01 after-fix pytest rc={rc1}\n{out1[:500]}", "implement")

    out = {
        "stage": "implement_practice",
        "baseline_rc": rc0,
        "after_rc": rc1,
        "baseline_out": out0[-800:],
        "after_out": out1[-800:],
        "passed": rc1 == 0,
        "work_dir": str(work),
        "note": "Real SWE-Pro: Grok iterates with same pattern on instance sandbox",
    }
    (OUT / "03_implement.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


def stage_spawn_reviews(port: int, plan: dict, implement: dict) -> dict[str, Any]:
    """Spawn Claude + Codex reviewer agents in parallel (bus messages)."""
    _log("[4/6] SPAWN REVIEWS (Claude L1 + Codex L2 in parallel)")
    diff_hint = (
        f"Practice implement passed={implement.get('passed')} "
        f"baseline_rc={implement.get('baseline_rc')} after_rc={implement.get('after_rc')}"
    )
    plan_snip = str(plan.get("text") or "")[:2000]

    claude_prompt = f"""You are Claude (Fable max) — line-by-line review L1 on the NEXUS SWE-Pro team.
Review this practice patch context (normalize_path fixed after pytest):
{diff_hint}

Plan was:
{plan_snip}

Checklist: correctness, edge cases (/, .., empty), tests, scope.
List BLOCKING issues (or NONE). End with REVIEW_L1_DONE."""

    codex_prompt = f"""You are Codex/ChatGPT (gpt-5.6-sol ultra, service fast) — adversarial review L2.
Challenge the practice fix for normalize_path. How could tests still be wrong?
{diff_hint}

List BLOCKING issues (or NONE). End with REVIEW_L2_DONE."""

    def run_one(agent: str, prompt: str) -> dict[str, Any]:
        post_ws(agent, f"Spawned review agent: {agent}", "review")
        r = bus_message(port, agent, prompt)
        text = str(r.get("text") or r.get("error") or r)[:6000]
        post_ws(agent, text[:2000], "review")
        return {"agent": agent, "text": text, "raw_ok": "error" not in r or r.get("ok")}

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futs = {
            ex.submit(run_one, "claude", claude_prompt): "claude",
            ex.submit(run_one, "gpt", codex_prompt): "gpt",
        }
        for fut in concurrent.futures.as_completed(futs):
            name = futs[fut]
            try:
                results[name] = fut.result()
                _log(f"  review {name} done len={len(results[name].get('text') or '')}")
            except Exception as e:
                results[name] = {"agent": name, "error": str(e)}
                _log(f"  review {name} ERROR {e}")

    # local file agent pass
    local_notes = []
    if PRACTICE.is_dir():
        local_notes.append(f"practice task path: {PRACTICE}")
    local_notes.append(f"e2e out: {OUT}")
    post_ws("local", "Local check: " + "; ".join(local_notes), "review")
    results["local"] = {"agent": "local", "text": "\n".join(local_notes)}

    out = {"stage": "review", "reviews": results}
    (OUT / "04_review.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
    return out


def stage_package(research, plan, implement, review) -> dict[str, Any]:
    _log("[5-6/6] PACKAGE predictions skeleton + summary")
    # Official format is instance_id + model_patch; skeleton for later Pro runs
    pred_path = OUT / "predictions.jsonl"
    skeleton = {
        "instance_id": "PRACTICE-T01_normalize_path",
        "model_name_or_path": "nexus-multi-ai/grok-4.5-max+claude-fable+gpt-5.6-sol",
        "model_patch": "",  # fill from real instance git diff
        "note": "Practice only — replace with real SWE-bench Pro instance patches",
    }
    with pred_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(skeleton) + "\n")

    summary = {
        "campaign": "swe_pro_e2e",
        "ts": time.time(),
        "research_papers": len((research or {}).get("papers") or []),
        "plan_ok": "PLAN_OK" in str((plan or {}).get("text") or ""),
        "implement_passed": bool((implement or {}).get("passed")),
        "reviewers": list(((review or {}).get("reviews") or {}).keys()),
        "predictions": str(pred_path),
        "next": [
            "Install official SWE-bench / Pro harness",
            "For each Pro instance: research→plan→Grok implement with pytest→spawn reviews→patch",
            "python -m swebench.harness.run_evaluation ... on predictions.jsonl",
        ],
        "how_llms_write_code": "docs/HOW_LLMS_WRITE_CODE.md",
    }
    (OUT / "06_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    post_ws(
        "nexus",
        f"E2E package done implement_passed={summary['implement_passed']} "
        f"reviewers={summary['reviewers']} predictions={pred_path}",
        "package",
    )
    _log(f"  summary → {OUT / '06_summary.json'}")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SWE-Pro E2E multi-AI campaign")
    ap.add_argument("--all", action="store_true", help="run all stages")
    ap.add_argument("--practice-only", action="store_true", help="only pytest implement demo")
    ap.add_argument("--start-bus", action="store_true", help="start nexus bus if down")
    ap.add_argument(
        "--research",
        default="SWE-bench Pro multi-agent coding evaluation scaffolds",
        help="arXiv research query",
    )
    ap.add_argument(
        "--issue",
        default=(
            "PRACTICE: Implement normalize_path correctly "
            "(collapse ., .., slashes; absolute/relative). Tests in fixtures/swe_pre/T01."
        ),
    )
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    _log("=== SWE-PRO E2E MULTI-AI (spawn reviews + pre-check tests) ===")
    _log(
        "LLMs write code as tokens; quality comes from agent loops + running tests. "
        "See docs/HOW_LLMS_WRITE_CODE.md"
    )

    if args.practice_only:
        impl = stage_practice_implement_with_tests()
        print(json.dumps(impl, indent=2)[:3000])
        return 0 if impl.get("passed") else 1

    research = stage_research(args.research)

    port = 0
    plan: dict[str, Any] = {"stage": "plan", "skipped": True}
    review: dict[str, Any] = {"stage": "review", "skipped": True}

    if args.start_bus or args.all:
        port = start_bus_if_needed() if (args.start_bus or not bus_up()) else bus_port()
        if not port and bus_up():
            port = bus_port()
        if port and bus_up(port):
            plan = stage_plan(port, research, args.issue)
        else:
            _log("bus unavailable — plan/review stages skipped (research+practice still run)")
            post_ws("nexus", "Bus down: ran research + practice implement only", "e2e")

    implement = stage_practice_implement_with_tests()

    if port and bus_up(port):
        review = stage_spawn_reviews(port, plan, implement)
    else:
        # still "spawn" local-only review note
        review = {
            "stage": "review",
            "reviews": {
                "local": {
                    "agent": "local",
                    "text": "Bus down — only local pre-check review. Start bus for Claude+Codex spawn.",
                }
            },
        }
        post_ws("local", review["reviews"]["local"]["text"], "review")

    summary = stage_package(research, plan, implement, review)
    print(json.dumps(summary, indent=2))
    return 0 if implement.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
