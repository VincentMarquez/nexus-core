"""Self-improvement loop: NEXUS stays alive under *user goals* + token budget.

  nexus alive init --goal "improve multi-agent durability and demos"
  nexus alive once
  nexus alive watch --interval 3600
  nexus alive status

Cycle (opt-in apply/self-approve):
  1. Check usage budget (throttle)
  2. Mine / research according to goals
  3. improve-ours plan from high scores
  4. If self_approve + tests green + apply → port patterns into our repo
  5. Heartbeat + workspace note
  6. Record token estimates

Autonomy defaults remain **off** for apply/push; ``self_approve`` + ``push_github``
are explicit config flags. Typical full loop::

  mine → score → improve plan → (apply) → tests → commit → push to GitHub
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import heartbeat as hb
from . import publish as pub
from . import repo_mine as rm
from . import usage as usage_mod


@dataclass
class AliveConfig:
    """What the user wants the living system to chase."""

    goal: str = "improve this repository using research and high-quality open source"
    queries: list[str] = field(
        default_factory=lambda: ["multi agent durable", "multi agent orchestration"]
    )
    arxiv_queries: list[str] = field(default_factory=list)
    min_score: float = 12.0
    fetch_count: int = 6
    # how many arXiv papers to pull per cycle (user-facing research depth)
    arxiv_count: int = 10
    # how many mined repos to keep/use after scoring
    use_limit: int = 10
    # apply code changes only when explicitly enabled
    apply: bool = False
    # if true, apply when make/smoke-like checks pass after plan (still needs apply=True)
    self_approve: bool = False
    # commit + push allowlisted files to GitHub after a successful cycle
    push_github: bool = False
    commit_prefix: str = "chore(alive):"
    git_remote: str = "origin"
    git_branch: str = ""  # empty = current branch
    use_ollama: bool = True  # local LLM for light fallback / bus
    # grader: auto|grok|ollama|heuristic — hard scoring defaults to Grok
    grader: str = "auto"
    # worker: auto|grok|bus — hard improve defaults to Grok, bus/local for light
    worker: str = "auto"
    prove: bool = True
    our_repo: str = ""
    interval_s: int = 3600
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AliveConfig":
        return cls(
            goal=str(d.get("goal") or "improve this repository using research and high-quality open source"),
            queries=list(d.get("queries") or ["multi agent durable"]),
            arxiv_queries=list(d.get("arxiv_queries") or []),
            min_score=float(d.get("min_score") or 12.0),
            fetch_count=int(d.get("fetch_count") or 6),
            arxiv_count=int(d.get("arxiv_count") or 10),
            use_limit=int(d.get("use_limit") or 10),
            apply=bool(d.get("apply", False)),
            self_approve=bool(d.get("self_approve", False)),
            push_github=bool(d.get("push_github", False)),
            commit_prefix=str(d.get("commit_prefix") or "chore(alive):"),
            git_remote=str(d.get("git_remote") or "origin"),
            git_branch=str(d.get("git_branch") or ""),
            use_ollama=bool(d.get("use_ollama", True)),
            grader=str(d.get("grader") or "auto"),
            worker=str(d.get("worker") or "auto"),
            prove=bool(d.get("prove", True)),
            our_repo=str(d.get("our_repo") or ""),
            interval_s=int(d.get("interval_s") or 3600),
            enabled=bool(d.get("enabled", True)),
        )


def _root(workdir: Optional[Path] = None) -> Path:
    return Path(workdir or os.environ.get("NEXUS_PROJECT_ROOT") or os.getcwd()).resolve()


def config_path(workdir: Optional[Path] = None) -> Path:
    d = _root(workdir) / ".nexus_state"
    d.mkdir(parents=True, exist_ok=True)
    return d / "alive.json"


def state_path(workdir: Optional[Path] = None) -> Path:
    return _root(workdir) / ".nexus_state" / "alive_state.json"


def load_config(workdir: Optional[Path] = None) -> AliveConfig:
    p = config_path(workdir)
    if p.is_file():
        try:
            return AliveConfig.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return AliveConfig()


def save_config(cfg: AliveConfig, workdir: Optional[Path] = None) -> Path:
    p = config_path(workdir)
    p.write_text(json.dumps(cfg.to_dict(), indent=2) + "\n", encoding="utf-8")
    return p


def _run_checks(workdir: Path) -> dict[str, Any]:
    from .github_community import run_project_checks

    checks = run_project_checks(workdir, timeout_each=180)
    required = [c for c in checks if c.name != "install"]
    ok = all(c.ok for c in required) if required else all(c.ok for c in checks)
    return {
        "ok": ok,
        "checks": [{"name": c.name, "ok": c.ok, "returncode": c.returncode} for c in checks],
    }


def cycle_once(
    workdir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """One self-improvement heartbeat under budget."""
    root = _root(workdir)
    cfg = load_config(root)
    report: dict[str, Any] = {
        "ts": time.time(),
        "goal": cfg.goal,
        "enabled": cfg.enabled,
        "steps": [],
    }
    if not cfg.enabled:
        report["skipped"] = "alive disabled in alive.json"
        return report

    # 1) budget gate (small reserve for this cycle)
    try:
        gate = usage_mod.check_budget(2_000, root, raise_on_exceed=True)
        report["budget"] = {
            "ok": gate.get("ok"),
            "warnings": gate.get("warnings"),
            "totals": gate.get("totals"),
        }
    except usage_mod.BudgetExceeded as e:
        report["blocked"] = str(e)
        report["budget"] = usage_mod.status(root)
        _save_state(report, root)
        return report

    if dry_run:
        report["dry_run"] = True
        report["steps"].append({"step": "dry_run", "ok": True})
        _save_state(report, root)
        return report

    # 2) mine for each query (rotate first query only per cycle to save tokens)
    q = (cfg.queries or ["multi agent"])[0]
    try:
        mine = rm.run_pipeline(
            root,
            query=q,
            fetch_count=cfg.fetch_count,
            eval_limit=cfg.fetch_count,
            min_score=cfg.min_score,
            use_limit=max(1, int(cfg.use_limit or cfg.fetch_count or 10)),
            use_ollama=cfg.use_ollama,
            prove=cfg.prove,
            improve=True,
            apply_improve=False,
            our_repo=cfg.our_repo or None,
            grader=cfg.grader or "auto",
            worker=cfg.worker or "auto",
        )
        report["steps"].append({
            "step": "mine",
            "query": q,
            "fetch": (mine.get("fetch") or {}).get("inserted"),
            "evaluated": (mine.get("evaluate") or {}).get("evaluated"),
            "used": (mine.get("use") or {}).get("used"),
            "improve_plan": ((mine.get("improve_ours") or {}).get("plan")),
        })
        # estimate tokens: digest-ish per eval
        usage_mod.record(
            1500 * int((mine.get("evaluate") or {}).get("evaluated") or 1),
            source="mine",
            label=f"mine:{q[:40]}",
            workdir=root,
            enforce=True,
        )
    except usage_mod.BudgetExceeded as e:
        report["steps"].append({"step": "mine", "blocked": str(e)})
        _save_state(report, root)
        return report
    except Exception as e:
        report["steps"].append({"step": "mine", "error": str(e)})

    # 3) optional arXiv (cheap if heuristic)
    if cfg.arxiv_queries:
        try:
            from . import github_autonomy as ga

            aq = cfg.arxiv_queries[0]
            ar = ga.improve_from_arxiv(
                aq,
                repo=cfg.our_repo or None,
                workdir=root,
                max_results=max(1, int(cfg.arxiv_count or 10)),
                apply=False,
                post_issue=False,
                also_scout=False,
            )
            report["steps"].append({
                "step": "arxiv",
                "query": aq,
                "papers": ar.get("papers"),
                "notes": ar.get("notes"),
            })
            usage_mod.record(
                800,
                source="arxiv",
                label=aq[:40],
                workdir=root,
                enforce=False,
            )
        except Exception as e:
            report["steps"].append({"step": "arxiv", "error": str(e)})

    # 4) self-approve path: tests green → optional apply
    checks = _run_checks(root)
    report["steps"].append({"step": "self_check", **checks})
    usage_mod.record(200, source="tests", label="alive_self_check", workdir=root, enforce=False)

    applied = None
    if cfg.apply and cfg.self_approve and checks.get("ok"):
        try:
            applied = rm.step_improve_ours(
                root,
                min_score=cfg.min_score,
                limit=3,
                apply=True,
                our_repo=cfg.our_repo or None,
                worker=cfg.worker or "auto",
            )
            report["steps"].append({
                "step": "self_approve_apply",
                "ok": True,
                "apply": applied.get("apply"),
                "plan": applied.get("plan"),
            })
            usage_mod.record(
                5000,
                source="improve_apply",
                label="self_approve",
                workdir=root,
                enforce=True,
            )
        except usage_mod.BudgetExceeded as e:
            report["steps"].append({"step": "self_approve_apply", "blocked": str(e)})
        except Exception as e:
            report["steps"].append({"step": "self_approve_apply", "error": str(e)})
    elif cfg.apply and not cfg.self_approve:
        report["steps"].append({
            "step": "self_approve_apply",
            "skipped": "self_approve=false — set alive.json self_approve true to auto-apply when tests pass",
        })
    elif cfg.self_approve and not checks.get("ok"):
        report["steps"].append({
            "step": "self_approve_apply",
            "skipped": "tests not green — refusing self-approve",
        })

    # 4b) always write commit-friendly docs (so GitHub updates even without code apply)
    try:
        log_path = pub.write_improvements_log(root, report)
        report["steps"].append({"step": "improvements_log", "path": str(log_path)})
        # snapshot latest plan into docs/ for the repo
        plan_src = root / ".nexus_state" / "repo_mine" / "IMPROVE_OURS.md"
        if plan_src.is_file():
            dest = root / "docs" / "LATEST_IMPROVE_PLAN.md"
            dest.write_text(
                "# Latest improve-ours plan (from alive cycle)\n\n"
                "Generated by `nexus alive`. Safe to commit.\n\n"
                + plan_src.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            report["steps"].append({"step": "plan_snapshot", "path": str(dest)})
        # arxiv notes snapshot if present
        arxiv_notes = root / ".nexus_state" / "arxiv_improve"
        if arxiv_notes.is_dir():
            latest = sorted(arxiv_notes.glob("improve-*.md"), key=lambda p: p.stat().st_mtime)
            if latest:
                adest = root / "docs" / "LATEST_ARXIV_IMPROVE.md"
                adest.write_text(
                    "# Latest arXiv improve notes (from alive cycle)\n\n"
                    + latest[-1].read_text(encoding="utf-8")[:12000],
                    encoding="utf-8",
                )
                report["steps"].append({"step": "arxiv_snapshot", "path": str(adest)})
    except Exception as e:
        report["steps"].append({"step": "improvements_log", "error": str(e)})

    # 4c) re-check after apply before publish
    if applied and cfg.push_github:
        checks2 = _run_checks(root)
        report["steps"].append({"step": "self_check_after_apply", **checks2})
        checks = checks2

    # 4d) publish to GitHub (commit + optional push) — needs push_github
    if cfg.push_github:
        if not checks.get("ok"):
            report["steps"].append({
                "step": "publish_github",
                "skipped": "tests not green — refusing commit/push",
            })
        else:
            try:
                msg = f"{cfg.commit_prefix} {cfg.goal[:72]}"
                pub_res = pub.commit_and_maybe_push(
                    root,
                    msg,
                    push=True,
                    remote=cfg.git_remote or "origin",
                    branch=cfg.git_branch or None,
                )
                report["steps"].append({"step": "publish_github", **pub_res})
                # rewrite log with publish line
                try:
                    pub.write_improvements_log(root, report)
                except Exception:
                    pass
            except Exception as e:
                report["steps"].append({"step": "publish_github", "error": str(e)})
    else:
        report["steps"].append({
            "step": "publish_github",
            "skipped": "push_github=false — enable with: nexus alive init --push-github",
        })

    # 5) heartbeat
    try:
        beat = hb.beat_once(root)
        report["steps"].append({
            "step": "heartbeat",
            "ping_ok": (beat.get("ping") or {}).get("ok"),
            "online": (beat.get("network") or {}).get("online"),
        })
    except Exception as e:
        report["steps"].append({"step": "heartbeat", "error": str(e)})

    # 6) workspace log
    try:
        log = root / ".nexus" / "workspace" / "chat.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "agent": "nexus_alive",
            "label": "alive_cycle",
            "message": f"goal={cfg.goal!r} steps={len(report['steps'])} "
            f"budget_day={(report.get('budget') or {}).get('totals', {}).get('day_tokens')}",
        }
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass

    report["usage"] = usage_mod.status(root)
    report["ok"] = True
    _save_state(report, root)
    return report


def _save_state(report: dict[str, Any], workdir: Path) -> None:
    p = state_path(workdir)
    p.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


def watch(
    workdir: Optional[Path] = None,
    *,
    interval_s: Optional[float] = None,
    max_cycles: int = 0,
) -> int:
    root = _root(workdir)
    cfg = load_config(root)
    interval = float(interval_s or cfg.interval_s or 3600)
    print("=== NEXUS alive (self-improvement under budget) ===")
    print(f"  goal:     {cfg.goal}")
    print(f"  interval: {interval}s")
    print(f"  apply:    {cfg.apply}  self_approve: {cfg.self_approve}")
    print(f"  usage:    {usage_mod.status(root).get('day_pct')}% daily")
    print("  Ctrl-C to stop")
    n = 0
    try:
        while True:
            n += 1
            print(f"\n--- alive cycle {n} @ {time.strftime('%H:%M:%S')} ---")
            rep = cycle_once(root)
            if rep.get("blocked"):
                print(f"  BUDGET BLOCK: {rep['blocked']}")
            else:
                for s in rep.get("steps") or []:
                    print(f"  {s.get('step')}: {json.dumps({k: s.get(k) for k in s if k != 'step'}, default=str)[:160]}")
            if max_cycles and n >= max_cycles:
                return 0
            time.sleep(max(60.0, interval))
    except KeyboardInterrupt:
        print("\n  stopped.")
        return 0
