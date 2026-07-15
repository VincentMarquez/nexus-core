#!/usr/bin/env python3
"""Full self-improve cycle: 10 repos + 10 arXiv + Grok 4.5 reason + apply + push.

  PYTHONPATH=src NEXUS_GROK_MODEL=grok-4.5 python3 scripts/full_self_improve_cycle.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
os.environ.setdefault("NEXUS_GROK_MODEL", "grok-4.5")
os.environ.setdefault("NEXUS_PROJECT_ROOT", str(ROOT))

from nexus import alive as al  # noqa: E402
from nexus import github_autonomy as ga  # noqa: E402
from nexus import grok_worker as gw  # noqa: E402
from nexus import publish as pub  # noqa: E402
from nexus import repo_mine as rm  # noqa: E402
from nexus import usage as usage_mod  # noqa: E402


N_REPOS = 10
N_PAPERS = 10
QUERY = "multi agent durable orchestration MCP"
ARXIV_Q = "multi-agent systems durable orchestration LLM"


def _log(msg: str) -> None:
    print(msg, flush=True)


def configure() -> al.AliveConfig:
    cfg = al.load_config(ROOT)
    cfg.goal = (
        "self-improve nexus-core from 10 arXiv papers + 10 mined repos "
        "using Grok 4.5 for grading, reasoning, and hard apply"
    )
    cfg.queries = [QUERY]
    cfg.arxiv_queries = [ARXIV_Q]
    cfg.fetch_count = N_REPOS
    cfg.arxiv_count = N_PAPERS
    cfg.use_limit = N_REPOS
    cfg.min_score = 10.0
    cfg.grader = "grok"
    cfg.worker = "grok"
    cfg.use_ollama = True  # light fallback only
    cfg.prove = True
    cfg.apply = True
    cfg.self_approve = True
    cfg.push_github = True
    cfg.our_repo = "VincentMarquez/nexus-core"
    al.save_config(cfg, ROOT)
    _log(f"config → {al.config_path(ROOT)}")
    return cfg


def reset_for_grok_regrade(limit: int = N_REPOS) -> int:
    """Clear scores so evaluate re-runs with Grok 4.5 (hard grade)."""
    conn = rm.connect(ROOT)
    rows = rm.list_entries(conn, min_score=0.0, limit=100)
    # prefer unscored first, else top by score for re-grade
    rows.sort(key=lambda r: (0 if r.get("idea") is None else 1, -float(r.get("score") or 0)))
    n = 0
    for r in rows[:limit]:
        conn.execute(
            "UPDATE entries SET idea=NULL, skill=NULL, summary=NULL WHERE repo=?",
            (r["repo"],),
        )
        n += 1
    conn.commit()
    conn.close()
    _log(f"re-grade queue: {n} repos cleared for Grok scoring")
    return n


def step_mine(cfg: al.AliveConfig) -> dict:
    _log("=== 1/5 MINE: fetch → Grok grade → use (10 repos) ===")
    # ensure we have enough candidates
    f1 = rm.step_fetch(
        ROOT,
        query=QUERY,
        count=N_REPOS,
        language="Python",
        max_stars=2000,
    )
    _log(f"  fetch primary: +{f1.get('inserted')} {f1.get('repos')}")
    f2 = rm.step_fetch(
        ROOT,
        query="multi agent LLM orchestration durable resume",
        count=N_REPOS,
        language="Python",
        max_stars=5000,
    )
    _log(f"  fetch secondary: +{f2.get('inserted')} {f2.get('repos')}")
    reset_for_grok_regrade(N_REPOS)
    e = rm.step_evaluate(
        ROOT,
        limit=N_REPOS,
        use_ollama=True,
        grader="grok",
    )
    _log(f"  evaluate: {e.get('evaluated')} graded (grader={e.get('grader')})")
    for r in (e.get("results") or []):
        if "idea" in r:
            _log(
                f"    · {r['repo']}: idea={r['idea']} skill={r['skill']} "
                f"sum={r.get('score')} [{r.get('method')}]"
            )
    # prove install/test on 10 clones is multi-hour; connect+notes is enough for Grok port
    u = rm.step_use(
        ROOT,
        min_score=cfg.min_score,
        limit=N_REPOS,
        prove=False,
        structure_only=True,
    )
    _log(f"  use: {u.get('used')} kept → {u.get('notes')}")
    imp = rm.step_improve_ours(
        ROOT,
        min_score=cfg.min_score,
        limit=N_REPOS,
        apply=False,
        our_repo=cfg.our_repo,
        worker="grok",
    )
    _log(f"  improve plan: {imp.get('plan')}")
    return {"fetch": [f1, f2], "evaluate": e, "use": u, "improve_ours": imp}


def step_arxiv(cfg: al.AliveConfig) -> dict:
    _log("=== 2/5 arXiv: 10 papers ===")
    ar = ga.improve_from_arxiv(
        ARXIV_Q,
        repo=cfg.our_repo,
        workdir=ROOT,
        max_results=N_PAPERS,
        apply=False,
        post_issue=False,
        also_scout=False,
    )
    paper_list = ar.get("paper_list") or []
    n = ar.get("papers") if not isinstance(ar.get("papers"), list) else len(ar.get("papers") or [])
    _log(f"  papers: {n} (list={len(paper_list)})")
    for i, p in enumerate(paper_list[:N_PAPERS], 1):
        _log(f"    {i}. {p.get('arxiv_id')}: {(p.get('title') or '')[:72]}")
    _log(f"  notes: {ar.get('notes')}")
    return ar


def _evidence_blob(mine: dict, arxiv: dict) -> str:
    parts: list[str] = ["# Mined repos (Grok-graded)\n"]
    for r in (mine.get("evaluate") or {}).get("results") or []:
        if "idea" not in r:
            continue
        parts.append(
            f"- **{r.get('repo')}** score={r.get('score')} "
            f"idea={r.get('idea')} skill={r.get('skill')} method={r.get('method')}\n"
            f"  {r.get('description') or ''}\n"
            f"  path={r.get('path') or ''}\n"
        )
    plan = (mine.get("improve_ours") or {}).get("plan")
    if plan and Path(plan).is_file():
        parts.append("\n# IMPROVE_OURS plan\n")
        parts.append(Path(plan).read_text(encoding="utf-8")[:12000])
    notes = arxiv.get("notes")
    if notes and Path(str(notes)).is_file():
        parts.append("\n# arXiv improve notes\n")
        parts.append(Path(str(notes)).read_text(encoding="utf-8")[:20000])
    # also try research brief
    for p in sorted((ROOT / ".nexus_workspaces").glob("rx-*/BRIEF.md"), reverse=True)[:1]:
        parts.append(f"\n# Research brief ({p})\n")
        parts.append(p.read_text(encoding="utf-8")[:8000])
    papers = arxiv.get("paper_list") or []
    if papers:
        parts.append("\n# Paper list\n")
        for p in papers[:N_PAPERS]:
            parts.append(
                f"- {p.get('arxiv_id')}: {p.get('title')}\n"
                f"  {p.get('abs_url') or ''}\n"
                f"  {(p.get('summary') or '')[:400]}\n"
            )
    return "\n".join(parts)


def step_reason(mine: dict, arxiv: dict, goal: str) -> dict:
    _log("=== 3/5 Grok 4.5 reasoning over papers + repos ===")
    if not gw.grok_available():
        return {"ok": False, "error": "grok CLI missing"}
    evidence = _evidence_blob(mine, arxiv)
    res = gw.grok_reason(evidence, goal=goal, model="grok-4.5", label="cycle_reason")
    text = (res.get("text") or "").strip()
    # unwrap json envelope if present
    try:
        outer = json.loads(text)
        if isinstance(outer, dict) and isinstance(outer.get("text"), str):
            text = outer["text"]
    except Exception:
        pass
    out = ROOT / "docs" / "SELF_IMPROVE_CYCLE.md"
    header = (
        "# Self-improve cycle — Grok 4.5\n\n"
        f"_Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}_\n\n"
        f"Model: `grok-4.5` · repos={N_REPOS} · arXiv={N_PAPERS}\n\n"
        "---\n\n"
    )
    out.write_text(header + (text or "(empty reasoning)"), encoding="utf-8")
    # snapshot for plan consumers
    (ROOT / "docs" / "LATEST_IMPROVE_PLAN.md").write_text(
        "# Latest improve plan (from full self-improve cycle)\n\n" + (text or "")[:20000],
        encoding="utf-8",
    )
    _log(f"  wrote {out} ({len(text)} chars) ok={res.get('ok')}")
    return {"ok": bool(res.get("ok") and text), "path": str(out), "chars": len(text), "raw": res}


def step_apply(cfg: al.AliveConfig, reason: dict) -> dict:
    _log("=== 4/5 Grok 4.5 hard improve (update the repo) ===")
    plan_path = reason.get("path") or str(ROOT / "docs" / "SELF_IMPROVE_CYCLE.md")
    goal = (
        f"{cfg.goal}\n\n"
        f"Follow the reasoning plan in {plan_path}. "
        "Implement the First apply slice and any P0 items that fit safely. "
        "Keep pytest green. Prefer patterns from .nexus_workspaces/scout_repos/."
    )
    # Prefer full agentic hard improve
    hard = gw.grok_hard_improve(ROOT, goal, model="grok-4.5", max_turns=18)
    _log(f"  hard_improve ok={hard.get('ok')} rc={hard.get('returncode')}")
    summary = (hard.get("text") or hard.get("error") or "")[:2000]
    if summary:
        _log(f"  summary: {summary[:500]}…")
    return hard


def step_checks_and_push(cfg: al.AliveConfig, report: dict) -> dict:
    _log("=== 5/5 checks + publish to GitHub ===")
    checks = al._run_checks(ROOT)
    report["checks"] = checks
    _log(f"  tests ok={checks.get('ok')} {checks.get('checks')}")
    try:
        log_path = pub.write_improvements_log(ROOT, report)
        _log(f"  improvements log: {log_path}")
    except Exception as e:
        _log(f"  improvements log error: {e}")
    pub_res = None
    if cfg.push_github and checks.get("ok"):
        msg = f"{cfg.commit_prefix} full cycle: 10 arxiv + 10 repos + Grok 4.5 apply"
        pub_res = pub.commit_and_maybe_push(
            ROOT,
            msg,
            push=True,
            remote=cfg.git_remote or "origin",
            branch=cfg.git_branch or None,
        )
        _log(f"  publish: {json.dumps(pub_res, default=str)[:500]}")
    elif not checks.get("ok"):
        _log("  refusing push — tests not green")
        # still commit docs-only if possible? no — keep safety
    else:
        _log("  push_github disabled")
    return {"checks": checks, "publish": pub_res}


def main() -> int:
    _log("NEXUS full self-improve cycle")
    _log(f"  root={ROOT}")
    _log(f"  grok model={gw.default_model()} available={gw.grok_available()}")
    try:
        usage_mod.check_budget(5_000, ROOT, raise_on_exceed=True)
    except usage_mod.BudgetExceeded as e:
        _log(f"BLOCKED budget: {e}")
        return 1

    cfg = configure()
    report: dict = {
        "ts": time.time(),
        "goal": cfg.goal,
        "model": "grok-4.5",
        "n_repos": N_REPOS,
        "n_papers": N_PAPERS,
        "steps": [],
    }

    t0 = time.time()
    try:
        mine = step_mine(cfg)
        report["steps"].append({"step": "mine", **{
            "evaluated": (mine.get("evaluate") or {}).get("evaluated"),
            "used": (mine.get("use") or {}).get("used"),
            "results": [
                {
                    "repo": r.get("repo"),
                    "score": r.get("score"),
                    "method": r.get("method"),
                    "description": (r.get("description") or "")[:200],
                }
                for r in ((mine.get("evaluate") or {}).get("results") or [])
                if "idea" in r
            ],
        }})
    except Exception as e:
        _log(f"mine FAILED: {e}")
        report["steps"].append({"step": "mine", "error": str(e)})
        mine = {}

    try:
        arxiv = step_arxiv(cfg)
        report["steps"].append({
            "step": "arxiv",
            "notes": arxiv.get("notes"),
            "papers": arxiv.get("papers"),
            "paper_list": arxiv.get("paper_list") or [],
        })
    except Exception as e:
        _log(f"arxiv FAILED: {e}")
        report["steps"].append({"step": "arxiv", "error": str(e)})
        arxiv = {}

    try:
        reason = step_reason(mine, arxiv, cfg.goal)
        report["steps"].append({"step": "grok_reason", **{k: reason.get(k) for k in ("ok", "path", "chars")}})
    except Exception as e:
        _log(f"reason FAILED: {e}")
        report["steps"].append({"step": "grok_reason", "error": str(e)})
        reason = {}

    try:
        apply_res = step_apply(cfg, reason)
        report["steps"].append({
            "step": "grok_hard_improve",
            "ok": apply_res.get("ok"),
            "returncode": apply_res.get("returncode"),
            "error": apply_res.get("error"),
            "summary": (apply_res.get("text") or "")[:1500],
        })
    except Exception as e:
        _log(f"apply FAILED: {e}")
        report["steps"].append({"step": "grok_hard_improve", "error": str(e)})

    try:
        fin = step_checks_and_push(cfg, report)
        report["steps"].append({"step": "publish", **(fin or {})})
    except Exception as e:
        _log(f"publish FAILED: {e}")
        report["steps"].append({"step": "publish", "error": str(e)})

    report["elapsed_s"] = round(time.time() - t0, 1)
    out = ROOT / ".nexus_state" / "full_cycle_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    _log(f"=== DONE in {report['elapsed_s']}s → {out} ===")
    print(json.dumps(report, indent=2, default=str)[:8000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
