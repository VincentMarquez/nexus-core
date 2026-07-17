"""Self-improvement loop: NEXUS stays alive under *user goals* + token budget.

  nexus alive init --goal "improve multi-agent durability and demos"
  nexus alive once              # REAL (unless --dry-run)
  nexus alive once --dry-run
  nexus alive watch --interval 3600
  nexus alive status

**REAL** cycle (``run self-improve real``) always::

  1. Budget gate
  2. **GitHub ≥5K★ research INPUT** (required — labs→individuals)
  3. arXiv input + paper rank (when configured)
  4. dual brief
  5. **canonical_engine + Judge** (goal→…→deliver) — same as lab/MCP
  6. self_check → implement apply (if apply+self_approve+gates)
  7. meta_review + optional publish

DRY only runs the budget/dry_run probe. Research+engine are REAL path.

Autonomy: ``self_approve`` + ``push_github`` remain explicit config flags.
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
    # zenith-style principled stop (gap board + no-progress thrash guard)
    stop_max_no_progress: int = 3
    stop_max_cycles: int = 0  # 0 = unlimited (watch max_cycles still applies)
    stop_when_gaps_closed: bool = True
    stop_on_tests_red: bool = False
    # P1.5: auto-seed gap board from LATEST_IMPROVE_PLAN / IMPROVE_OURS each cycle
    seed_gaps: bool = True
    # P3.2: after green self_check, run improve_apply promote gate (zenith/cycgraph)
    promote_on_done: bool = False
    # when True, cycle step fails closed if IndependentVerify denies
    promote_require: bool = False
    # require decision_package + board signal continue before self_approve apply
    require_decision: bool = True
    # require work_ledger dual-control accept before self_approve apply
    # (default: same as require_decision)
    require_work_ledger: bool = True
    # require improve_spine grade record (+ dual-write grade_ledger) before apply
    # (default: same as require_decision)
    require_spine: bool = True
    # implementer/verifier role ids for anti-collusion (grader uses cfg.grader label)
    implementer: str = "worker:apply"
    verifier: str = "judge:verify"
    # wire board signal → PrincipledStop gap board (replan/stop → gaps; continue closes)
    sync_board_gaps: bool = True
    # hard board stop (collusion/budget) aborts stop board so watch() exits
    abort_on_board_stop: bool = True
    # offline preference pairs from ranked candidates (arXiv 2602.04518)
    record_preferences: bool = True
    # ── Research inputs + canonical engine pipeline (same as lab / MCP) ──
    # High-star GitHub mine (labs → individuals). Default 5000. Feeds goal/plan context.
    github_min_stars: int = 5000
    github_review: bool = True
    # Also run legacy mid-tier mine (stars≤500) for niche patterns
    mid_tier_mine: bool = False
    # Read+rank arXiv abstracts into PAPER_IMPROVE (not just a reading list)
    paper_improve: bool = True
    # After research: run DurableEngine + Judge (goal→…→meta_review→approval→deliver)
    # This is the ONE implement/meta path — not a parallel lab invention.
    use_canonical_engine: bool = True
    # After implement (or after plan if no apply): write meta-review snapshot
    meta_review: bool = True
    # When tests are red: worker fix → re-check until green (or max attempts)
    fix_max_attempts: int = 5
    # Implement quota: ≥1 arXiv + ≥1 GitHub idea, max 10; scan cross-paper/code patterns
    implement_min_arxiv: int = 1
    implement_min_github: int = 1
    implement_max_ideas: int = 10
    cross_pattern_scan: bool = True
    # Canonical step names (must match unified_pipeline / StepPolicy.default)
    pipeline: list[str] = field(
        default_factory=lambda: [
            "goal",
            "plan",
            "challenge",
            "implement",
            "test",
            "review",
            "log",
            "meta_review",
            "approval",
            "deliver",
        ]
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AliveConfig":
        require_decision = bool(d.get("require_decision", True))
        # default work-ledger / spine gates follow decision gate when key omitted
        if "require_work_ledger" in d:
            require_work_ledger = bool(d.get("require_work_ledger"))
        else:
            require_work_ledger = require_decision
        if "require_spine" in d:
            require_spine = bool(d.get("require_spine"))
        else:
            require_spine = require_decision
        pipe = d.get("pipeline")
        if not isinstance(pipe, list) or not pipe:
            pipe = [
                "goal",
                "plan",
                "challenge",
                "implement",
                "test",
                "review",
                "log",
                "meta_review",
                "approval",
                "deliver",
            ]
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
            stop_max_no_progress=int(d.get("stop_max_no_progress") or 3),
            stop_max_cycles=int(d.get("stop_max_cycles") or 0),
            stop_when_gaps_closed=bool(d.get("stop_when_gaps_closed", True)),
            stop_on_tests_red=bool(d.get("stop_on_tests_red", False)),
            seed_gaps=bool(d.get("seed_gaps", True)),
            promote_on_done=bool(d.get("promote_on_done", False)),
            promote_require=bool(d.get("promote_require", False)),
            require_decision=require_decision,
            require_work_ledger=require_work_ledger,
            require_spine=require_spine,
            implementer=str(d.get("implementer") or "worker:apply"),
            verifier=str(d.get("verifier") or "judge:verify"),
            sync_board_gaps=bool(d.get("sync_board_gaps", True)),
            abort_on_board_stop=bool(d.get("abort_on_board_stop", True)),
            record_preferences=bool(d.get("record_preferences", True)),
            github_min_stars=int(d.get("github_min_stars") or 5000),
            github_review=bool(d.get("github_review", True)),
            mid_tier_mine=bool(d.get("mid_tier_mine", False)),
            paper_improve=bool(d.get("paper_improve", True)),
            use_canonical_engine=bool(d.get("use_canonical_engine", True)),
            meta_review=bool(d.get("meta_review", True)),
            fix_max_attempts=max(1, int(d.get("fix_max_attempts") or 5)),
            implement_min_arxiv=max(1, int(d.get("implement_min_arxiv") or 1)),
            implement_min_github=max(1, int(d.get("implement_min_github") or 1)),
            implement_max_ideas=max(2, min(10, int(d.get("implement_max_ideas") or 10))),
            cross_pattern_scan=bool(d.get("cross_pattern_scan", True)),
            pipeline=[str(x) for x in pipe],
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
    rows = [
        {"name": c.name, "ok": c.ok, "returncode": c.returncode} for c in checks
    ]
    # In-process marketplace structural gate (wshobson-shaped validate/collisions).
    # Soft-skip when plugins/ is absent (non-nexus workdirs / empty checkouts).
    try:
        from . import marketplace as mp

        if (Path(workdir) / mp.DEFAULT_PLUGINS_DIR).is_dir():
            sc = mp.self_check(workdir)
            rows.append(
                {
                    "name": "marketplace",
                    "ok": bool(sc.get("ok")),
                    "returncode": 0 if sc.get("ok") else 1,
                    "errors": sc.get("errors"),
                }
            )
    except Exception as e:
        rows.append(
            {
                "name": "marketplace",
                "ok": False,
                "returncode": 1,
                "error": str(e)[:300],
            }
        )
    # Advisory MAFBench brief (arXiv 2602.03128 + AssetOpsBench hybrid):
    # consensus_overhead_x + multi-domain MCP hub + pack pass_rate.
    # Soft: failure is reported but does not fail overall self_check (bench
    # noise must not block apply). Full gate remains `nexus eval maf`.
    try:
        from . import maf_bench as maf

        brief = maf.maf_brief(workdir, iters=2, include_pack=True)
        rows.append(
            {
                "name": "maf_brief",
                "ok": True,  # advisory — always soft-ok
                "returncode": 0 if brief.get("ok") else 1,
                "advisory": True,
                "brief_ok": bool(brief.get("ok")),
                "consensus_overhead_x": brief.get("consensus_overhead_x"),
                "domain_mcp_overhead_x": brief.get("domain_mcp_overhead_x"),
                "domain_mcp_n_servers": brief.get("domain_mcp_n_servers"),
                "domain_mcp_pass_rate": brief.get("domain_mcp_pass_rate"),
                "pack_pass_rate": brief.get("pack_pass_rate"),
                "wall_ms": brief.get("wall_ms"),
            }
        )
    except Exception as e:
        rows.append(
            {
                "name": "maf_brief",
                "ok": True,  # advisory soft-skip on import/runtime errors
                "returncode": 1,
                "advisory": True,
                "brief_ok": False,
                "error": str(e)[:300],
            }
        )
    required = [c for c in rows if c.get("name") != "install"]
    ok = all(c.get("ok") for c in required) if required else all(
        c.get("ok") for c in rows
    )
    return {
        "ok": ok,
        "checks": rows,
    }


def _worker_fix_tests(
    root: Path,
    cfg: AliveConfig,
    checks: dict[str, Any],
    *,
    attempt: int,
    max_attempts: int,
) -> dict[str, Any]:
    """One fix attempt aimed at making pytest/smoke green."""
    fail_bits = [
        f"{c.get('name')}:rc={c.get('returncode')}"
        for c in (checks.get("checks") or [])
        if not c.get("ok")
    ]
    goal = (
        f"FIX LOOP attempt {attempt}/{max_attempts}: make install/pytest/smoke GREEN. "
        f"Failing checks: {fail_bits or 'unknown'}. "
        f"Read failures, apply minimal fixes, re-run pytest. "
        f"Do not push. Product goal context: {(cfg.goal or '')[:240]}"
    )
    worker = (cfg.worker or "auto").strip().lower()
    # Prefer Grok hard improve for real code fixes
    if worker in ("auto", "grok"):
        try:
            from . import grok_worker as gw

            if gw.grok_available():
                res = gw.grok_hard_improve(root, goal)
                return {
                    "worker": "grok",
                    "ok": bool(res.get("ok", True)) if isinstance(res, dict) else True,
                    "result": res if isinstance(res, dict) else {"raw": str(res)[:800]},
                }
        except Exception as e:
            return {"worker": "grok", "ok": False, "error": str(e)[:500]}
    # Fallback: improve_ours apply (pattern port)
    try:
        applied = rm.step_improve_ours(
            root,
            min_score=cfg.min_score,
            limit=3,
            apply=True,
            our_repo=cfg.our_repo or None,
            worker=cfg.worker or "auto",
        )
        st = _improve_ours_apply_status(applied)
        return {
            "worker": "improve_ours",
            "ok": bool(st.get("ok")),
            "result": applied if isinstance(applied, dict) else {},
            "reason": st.get("reason"),
        }
    except Exception as e:
        return {"worker": "improve_ours", "ok": False, "error": str(e)[:500]}


def _self_check_fix_loop(
    root: Path,
    cfg: AliveConfig,
    report: dict[str, Any],
    *,
    phase: str = "pre_implement",
) -> tuple[dict[str, Any], Any]:
    """Run self_check; if red, worker-fix and re-check until green or max attempts.

    Returns (final_checks, last_applied).
    """
    max_a = max(1, int(getattr(cfg, "fix_max_attempts", 5) or 5))
    applied: Any = None
    checks: dict[str, Any] = {"ok": False, "checks": []}

    for attempt in range(1, max_a + 1):
        checks = _run_checks(root)
        report["steps"].append({
            "step": "self_check",
            "phase": phase,
            "attempt": attempt,
            "max_attempts": max_a,
            **checks,
        })
        usage_mod.record(
            200,
            source="tests",
            label=f"self_check_{phase}_{attempt}",
            workdir=root,
            enforce=False,
        )
        if checks.get("ok"):
            report["steps"].append({
                "step": "fix_loop",
                "phase": phase,
                "ok": True,
                "green": True,
                "attempts": attempt,
                "note": "tests green — proceed",
            })
            return checks, applied

        # tests red → fix (needs apply+self_approve so worker can edit)
        if not (cfg.apply and cfg.self_approve):
            report["steps"].append({
                "step": "fix_loop",
                "phase": phase,
                "ok": False,
                "green": False,
                "attempt": attempt,
                "skipped": "tests red but apply+self_approve not both true — cannot auto-fix",
            })
            return checks, applied

        try:
            fix = _worker_fix_tests(
                root, cfg, checks, attempt=attempt, max_attempts=max_a
            )
            applied = fix.get("result") if isinstance(fix, dict) else fix
            report["steps"].append({
                "step": "fix_loop",
                "phase": phase,
                "attempt": attempt,
                "max_attempts": max_a,
                "worker": (fix or {}).get("worker"),
                "ok": bool((fix or {}).get("ok")),
                "error": (fix or {}).get("error"),
                "reason": (fix or {}).get("reason"),
                "note": "tests red → worker fix → re-check",
            })
            if fix.get("ok"):
                usage_mod.record(
                    5000,
                    source="fix_loop",
                    label=f"{phase}_{attempt}",
                    workdir=root,
                    enforce=True,
                )
        except usage_mod.BudgetExceeded as e:
            report["steps"].append({
                "step": "fix_loop",
                "phase": phase,
                "attempt": attempt,
                "blocked": str(e),
            })
            return checks, applied
        except Exception as e:
            report["steps"].append({
                "step": "fix_loop",
                "phase": phase,
                "attempt": attempt,
                "error": str(e)[:500],
            })

    # exhausted
    checks = _run_checks(root)
    report["steps"].append({
        "step": "self_check_final",
        "phase": phase,
        **checks,
    })
    report["steps"].append({
        "step": "fix_loop",
        "phase": phase,
        "ok": bool(checks.get("ok")),
        "green": bool(checks.get("ok")),
        "exhausted": not bool(checks.get("ok")),
        "attempts": max_a,
        "note": (
            "tests green after fix loop"
            if checks.get("ok")
            else f"tests still red after {max_a} fix attempts — refusing push"
        ),
    })
    return checks, applied


def _self_approve_apply_landed(report: dict[str, Any]) -> bool:
    """True when this cycle's implement / self_approve_apply step reported ok."""
    for s in report.get("steps") or []:
        if not isinstance(s, dict) or not s.get("ok"):
            continue
        if s.get("step") in ("self_approve_apply", "implement"):
            return True
        if s.get("alias") == "self_approve_apply" and s.get("ok"):
            return True
    return False


def _improve_ours_apply_status(applied: Any) -> dict[str, Any]:
    """Derive landed ok/reason from ``repo_mine.step_improve_ours`` result.

    ``step_improve_ours`` keeps top-level ``ok: True`` whenever a plan was
    written; worker success lives under ``apply`` (grok: ``ok``, bus:
    ``status``). Hard-fail when the worker reports error/failure so
    ``_self_approve_apply_landed`` does not treat a dead apply as landed.
    """
    if not isinstance(applied, dict):
        return {"ok": False, "reason": "improve_ours returned non-dict"}

    # No scored repos / plan-level hard fail
    if applied.get("ok") is False:
        return {
            "ok": False,
            "reason": str(applied.get("error") or "improve_ours ok=False")[:500],
        }

    apply_blob = applied.get("apply")
    if apply_blob is None:
        return {"ok": False, "reason": "no apply result from improve_ours"}
    if not isinstance(apply_blob, dict):
        return {"ok": False, "reason": "apply result not a dict"}

    # Grok (and any path that sets explicit ok)
    if apply_blob.get("ok") is False:
        reason = (
            apply_blob.get("error")
            or apply_blob.get("summary")
            or f"worker apply failed via={apply_blob.get('via')}"
        )
        return {"ok": False, "reason": str(reason)[:500]}
    if apply_blob.get("ok") is True:
        return {"ok": True}

    # Bus job: status completed|failed (no ok field)
    status = apply_blob.get("status")
    if status is not None:
        st = str(status).strip().lower()
        if st in ("completed", "success", "ok", "done"):
            return {"ok": True}
        err = apply_blob.get("error") or f"bus job status={status}"
        return {"ok": False, "reason": str(err)[:500]}

    if apply_blob.get("error"):
        return {"ok": False, "reason": str(apply_blob["error"])[:500]}

    return {"ok": False, "reason": "apply result missing success signal"}


def _grader_role(cfg: "AliveConfig") -> str:
    """Map alive grader knob to anti-collusion role id (never equals implementer)."""
    g = str(cfg.grader or "auto").strip().lower()
    if g in ("", "auto", "heuristic"):
        return "grok:grade"
    if g.startswith("grok"):
        return "grok:grade"
    if g.startswith("ollama"):
        return "ollama:grade"
    return f"{g}:grade"


def _self_approve_decision_gate(
    root: Path,
    cfg: "AliveConfig",
    *,
    report: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Board + decision package gate before self_approve hard apply.

    Returns ``allow`` True only when require_decision is off *or* the improve
    board signal is ``continue`` and the decision package is ok.
    """
    from . import apply_select as asel

    grader = _grader_role(cfg)
    implementer = str(cfg.implementer or asel.DEFAULT_ROLES["implementer"])
    verifier = str(cfg.verifier or asel.DEFAULT_ROLES["verifier"])

    stop_blob: Optional[dict[str, Any]] = None
    if isinstance(report, dict):
        for s in report.get("steps") or []:
            if isinstance(s, dict) and s.get("step") == "principled_stop":
                stop_blob = {
                    "stop": bool(s.get("stop")),
                    "reason": s.get("reason"),
                    "detail": s.get("detail"),
                }
                break
        # also accept top-level stop decision if present
        if stop_blob is None and isinstance(report.get("stop"), dict):
            stop_blob = report["stop"]

    board = asel.improve_board(
        root,
        min_score=float(cfg.min_score),
        limit=max(3, int(cfg.use_limit or 3)),
        grader=grader,
        implementer=implementer,
        verifier=verifier,
        goal=str(cfg.goal or "self-improve"),
        auto_index=True,
        stop_decision=stop_blob,
    )
    signal = str(board.get("signal") or "")
    decision = board.get("decision") or {}
    out: dict[str, Any] = {
        "require_decision": bool(cfg.require_decision),
        "signal": signal,
        "signal_reason": board.get("signal_reason"),
        "replan_hints": list(board.get("replan_hints") or []),
        "decision": {
            "ok": decision.get("ok"),
            "reason": decision.get("reason"),
            "confidence": decision.get("confidence"),
            "candidate": decision.get("candidate"),
        }
        if decision
        else None,
        "roles": board.get("roles"),
        "roles_ok": board.get("roles_ok"),
        "candidates": len(board.get("candidates") or []),
        "board_schema": board.get("schema"),
        "allow": True,
        "skip_reason": None,
    }
    if not cfg.require_decision:
        out["allow"] = True
        out["skip_reason"] = None
        return out

    if signal == asel.SIGNAL_STOP:
        out["allow"] = False
        out["skip_reason"] = f"board_stop:{board.get('signal_reason')}"
    elif signal == asel.SIGNAL_REPLAN:
        out["allow"] = False
        out["skip_reason"] = f"board_replan:{board.get('signal_reason')}"
    elif not decision or not decision.get("ok"):
        out["allow"] = False
        out["skip_reason"] = f"decision_denied:{(decision or {}).get('reason') or 'no_decision'}"
    else:
        out["allow"] = True

    # Prefer offline pairs from ranked candidates (2602.04518) — fail-open
    if bool(getattr(cfg, "record_preferences", True)):
        try:
            from . import preference_pairs as pp

            pref = pp.record_from_ranked(
                board.get("candidates") or [],
                root,
                source="alive_self_approve_gate",
            )
            if pref:
                out["preference_pair"] = {
                    "id": pref.get("id"),
                    "better": pref.get("better"),
                    "worse": pref.get("worse"),
                }
        except Exception as e:
            out["preference_error"] = str(e)

    # Wire board signal → PrincipledStop gap board (zenith replan/stop)
    if bool(getattr(cfg, "sync_board_gaps", True)) and signal:
        try:
            out["gap_sync"] = _sync_board_signal_gaps(
                root,
                cfg,
                signal=signal,
                signal_reason=str(board.get("signal_reason") or ""),
                signal_detail=str(board.get("signal_detail") or ""),
                hints=list(board.get("replan_hints") or []),
            )
        except Exception as e:
            out["gap_sync_error"] = str(e)

    # Work ledger dual-control accept before self_approve hard apply
    out["require_work_ledger"] = bool(getattr(cfg, "require_work_ledger", True))
    if out["allow"] and out["require_work_ledger"]:
        try:
            out["work_ledger"] = _self_approve_work_ledger_gate(
                root,
                cfg,
                decision=decision if isinstance(decision, dict) else {},
                board=board,
            )
            if not (out["work_ledger"] or {}).get("accepted"):
                out["allow"] = False
                err = (out["work_ledger"] or {}).get("error") or "not accepted"
                out["skip_reason"] = f"work_ledger_denied:{err}"
        except Exception as e:
            out["allow"] = False
            out["work_ledger_error"] = str(e)
            out["skip_reason"] = f"work_ledger_error:{e}"

    # Improve spine grade ensure + dual-write before self_approve hard apply
    out["require_spine"] = bool(getattr(cfg, "require_spine", True))
    if out["allow"] and out["require_spine"]:
        try:
            out["spine"] = _self_approve_spine_gate(
                root,
                cfg,
                decision=decision if isinstance(decision, dict) else {},
                board=board,
            )
            if not (out["spine"] or {}).get("accepted"):
                out["allow"] = False
                err = (out["spine"] or {}).get("error") or "not accepted"
                out["skip_reason"] = f"spine_denied:{err}"
        except Exception as e:
            out["allow"] = False
            out["spine_error"] = str(e)
            out["skip_reason"] = f"spine_error:{e}"

    return out


def _self_approve_work_ledger_gate(
    root: Path,
    cfg: "AliveConfig",
    *,
    decision: dict[str, Any],
    board: dict[str, Any],
) -> dict[str, Any]:
    """Record dual-control accept on work ledger for the board's top candidate."""
    from . import work_ledger as wl

    cand = (decision or {}).get("candidate") or {}
    if not cand:
        ranked = board.get("candidates") or []
        cand = ranked[0] if ranked else {}
    grade = {
        "repo": cand.get("repo") or cand.get("source_repo") or "",
        "score": cand.get("score"),
        "idea": cand.get("idea"),
        "skill": cand.get("skill"),
        "method": cand.get("method") or "alive:self_approve",
        "path": cand.get("path") or "",
        "pattern": cand.get("pattern") or cand.get("pattern_name") or "alive-self-approve",
    }
    if not grade["repo"]:
        return {
            "ok": False,
            "accepted": False,
            "error": "no candidate repo for work_ledger gate",
        }
    grader = _grader_role(cfg)
    applier = str(cfg.implementer or "worker:apply")
    try:
        score_f = float(grade.get("score") or 0)
    except (TypeError, ValueError):
        score_f = 0.0
    thr = float(cfg.min_score or 0)
    if score_f > 0:
        thr = min(max(thr, 0.0), score_f) if thr > 0 else score_f
    return wl.ensure_apply_gate(
        root,
        grade=grade,
        run_id=f"alive-{grade['repo'].replace('/', '_')[:40]}",
        pattern_name=str(grade.get("pattern") or "alive-self-approve"),
        target_module="src/nexus/alive.py",
        score_threshold=thr if thr > 0 else None,
        grader=grader,
        applier=applier,
        accept=True,
        tests_to_run=["tests/test_usage_alive.py", "tests/test_work_ledger.py"],
    )


def _self_approve_spine_gate(
    root: Path,
    cfg: "AliveConfig",
    *,
    decision: dict[str, Any],
    board: dict[str, Any],
) -> dict[str, Any]:
    """Ensure top candidate is on improve_spine (+ dual-write grade_ledger)."""
    from . import improve_spine as spine

    cand = (decision or {}).get("candidate") or {}
    if not cand:
        ranked = board.get("candidates") or []
        cand = ranked[0] if ranked else {}
    grade = {
        "repo": cand.get("repo") or cand.get("source_repo") or "",
        "score": cand.get("score"),
        "idea": cand.get("idea"),
        "skill": cand.get("skill"),
        "method": cand.get("method") or "alive:self_approve",
        "path": cand.get("path") or "",
        "summary": cand.get("pattern")
        or cand.get("pattern_name")
        or cand.get("summary")
        or "",
        "pattern": cand.get("pattern") or cand.get("pattern_name") or "alive-self-approve",
    }
    if not grade["repo"]:
        return {
            "ok": False,
            "accepted": False,
            "error": "no candidate repo for spine gate",
        }
    rid = f"alive-{grade['repo'].replace('/', '_')[:40]}"
    thr = float(cfg.min_score or 0) or None
    return spine.require_spine_grade(
        root,
        repo=str(grade["repo"]),
        run_id=rid,
        min_score=thr,
        auto_ensure=grade,
    )


def _sync_board_signal_gaps(
    root: Path,
    cfg: "AliveConfig",
    *,
    signal: str,
    signal_reason: str = "",
    signal_detail: str = "",
    hints: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Persist board signal onto the alive PrincipledStop gap board."""
    from . import apply_select as asel
    from .durability.stop import PrincipledStop, default_stop_path

    path = default_stop_path(root)
    stopper = PrincipledStop.load(path)
    sync = asel.sync_signal_to_stop(
        stopper,
        {
            "signal": signal,
            "reason": signal_reason,
            "detail": signal_detail,
            "hints": list(hints or []),
        },
        abort_on_hard_stop=bool(getattr(cfg, "abort_on_board_stop", True)),
        close_on_continue=True,
    )
    stopper.save(path)
    sync["path"] = str(path)
    return sync


def _should_promote_on_done(
    cfg: AliveConfig,
    *,
    checks: dict[str, Any],
    report: dict[str, Any],
) -> bool:
    """P3.3: promote after green cycle when configured or self_approve applied.

    - Explicit ``cfg.promote_on_done`` always runs the gate.
    - Auto-wire: when ``self_approve`` + ``apply`` landed a real apply this
      cycle (tests green path), run promote even if the knob is still false.
      This closes the "full-cycle demo" gap without forcing promote on dry
      planning cycles.
    """
    if cfg.promote_on_done:
        return True
    if cfg.self_approve and cfg.apply and checks.get("ok"):
        return _self_approve_apply_landed(report)
    return False


def _run_promote_on_done(
    workdir: Path,
    cfg: AliveConfig,
    *,
    checks: dict[str, Any],
    applied: Any = None,
) -> dict[str, Any]:
    """P3.2: independent verify-before-promote after a green alive cycle.

    Runs a dry-run ``ImproveApplyRun`` with ``meta.promote_on_done`` so the
    same IndependentVerify gate used by improve_apply is exercised from the
    alive loop. Fail-closed when ``cfg.promote_require`` and verify denies
    (or tests are red).
    """
    from . import improve_apply as ia
    from .judge import PASS_THRESHOLD

    tests_ok = bool(checks.get("ok"))
    score = 0.95 if tests_ok else 0.2
    decision = "pass" if tests_ok else "fail"
    # Prefer mine grade score when apply returned one
    if isinstance(applied, dict):
        apply_blob = applied.get("apply") if isinstance(applied.get("apply"), dict) else applied
        for key in ("score", "grade_score"):
            if apply_blob and apply_blob.get(key) is not None:
                try:
                    score = float(apply_blob[key])
                except (TypeError, ValueError):
                    pass
                break

    grade = {
        "repo": cfg.our_repo or "local/nexus-core",
        "score": 15.0 if tests_ok else 5.0,
        "idea": 7.0,
        "skill": 8.0,
        "method": f"alive:{cfg.worker or 'auto'}",
        "pattern": "alive-cycle-promote",
        "arxiv_id": "",
        "promote_on_done": True,
        "promote_require": bool(cfg.promote_require),
    }
    meta = {
        "promote_on_done": True,
        "promote_require": bool(cfg.promote_require),
        "promote_implementer": "alive_worker",
        "promote_verifier": "alive_verify",
        "promote_score": score,
        "promote_decision": decision,
        "source": "alive_cycle",
        "goal": cfg.goal,
        "tests_ok": tests_ok,
        "pass_threshold": PASS_THRESHOLD,
    }
    run = ia.start_run(workdir, grade=grade, dry_run=True, meta=meta)
    try:
        status = run.run_to_done()
    except ia.PhaseGuardError as e:
        return {
            "step": "promote_on_done",
            "ok": False,
            "blocked": str(e),
            "run_id": run.run_id,
            "phase": run.phase,
            "promote": (run.meta or {}).get("promote"),
            "require": bool(cfg.promote_require),
        }
    prom = (run.meta or {}).get("promote") or {}
    # IndependentVerify result preferred; fall back to tests_ok if gate skipped
    if prom and not prom.get("skipped"):
        ok = bool(prom.get("ok"))
    else:
        ok = tests_ok
    out: dict[str, Any] = {
        "step": "promote_on_done",
        "ok": ok,
        "run_id": status.get("run_id") or run.run_id,
        "phase": status.get("phase") or run.phase,
        "promote": prom,
        "require": bool(cfg.promote_require),
        "tests_ok": tests_ok,
    }
    if cfg.promote_require and not ok:
        out["blocked"] = f"promote denied: {(prom or {}).get('reason') or 'verify failed'}"
    return out


def _phase_github_review(
    root: Path,
    cfg: AliveConfig,
    query: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    """High-star GitHub review (≥github_min_stars) + improve plan. Optional mid-tier mine."""
    from . import github_autonomy as ga

    min_stars = max(0, int(getattr(cfg, "github_min_stars", 5000) or 5000))
    phase: dict[str, Any] = {
        "step": "github_review",
        "query": query,
        "min_stars": min_stars,
        "ok": True,
    }

    # Fast catalog of ≥min_stars repos (labs → individuals).
    # Fallbacks when the goal phrase is too narrow (found: 0).
    alt_queries = list(cfg.queries or [])
    try:
        hs = ga.search_high_star_repos(
            query,
            min_stars=min_stars,
            limit=max(5, int(cfg.use_limit or 15)),
            language="Python",
            fallback_queries=alt_queries[1:] if len(alt_queries) > 1 else None,
        )
        phase["high_star"] = {
            "count": hs.get("count"),
            "repos": (hs.get("repos") or [])[:20],
            "query_used": hs.get("query"),
            "fallback_used": hs.get("fallback_used"),
            "tried": hs.get("tried"),
        }
        # Persist for dual_review / multi-agent
        mine_dir = root / ".nexus_state" / "repo_mine"
        mine_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# GitHub high-star review (≥{min_stars}★)",
            "",
            f"query_requested: `{query}`",
            f"query_used: `{hs.get('query')}`",
            f"fallback_used: {hs.get('fallback_used')}",
            f"found: {hs.get('count')}",
            "",
        ]
        for i, r in enumerate(hs.get("repos") or [], 1):
            lines.append(
                f"{i}. **{r.get('full_name')}** ★{r.get('stars')} · {r.get('language') or '?'}"
            )
            lines.append(f"   {r.get('url') or ''}")
            if r.get("description"):
                lines.append(f"   {(r.get('description') or '')[:160]}")
        (mine_dir / "GITHUB_HIGHSTAR.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "LATEST_GITHUB_REVIEW.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        phase["notes"] = str(mine_dir / "GITHUB_HIGHSTAR.md")
        # Prefer the query that actually found high-star repos for the mine pipeline
        if hs.get("query") and int(hs.get("count") or 0) > 0:
            query = str(hs.get("query"))
            phase["query"] = query
    except Exception as e:
        phase["high_star_error"] = str(e)

    # Full mine pipeline targeting high-star repos (plan for implement)
    mine = rm.run_pipeline(
        root,
        query=query,
        fetch_count=cfg.fetch_count,
        eval_limit=cfg.fetch_count,
        min_score=cfg.min_score,
        min_stars=min_stars,
        max_stars=None,
        use_limit=max(1, int(cfg.use_limit or cfg.fetch_count or 10)),
        use_ollama=cfg.use_ollama,
        prove=cfg.prove,
        improve=True,
        apply_improve=False,
        our_repo=cfg.our_repo or None,
        grader=cfg.grader or "auto",
        worker=cfg.worker or "auto",
    )
    phase["mine"] = {
        "fetch": (mine.get("fetch") or {}).get("inserted"),
        "evaluated": (mine.get("evaluate") or {}).get("evaluated"),
        "used": (mine.get("use") or {}).get("used"),
        "improve_plan": ((mine.get("improve_ours") or {}).get("plan")),
    }
    report["steps"].append(phase)

    # Legacy mid-tier mine (optional niche repos)
    if bool(getattr(cfg, "mid_tier_mine", False)):
        try:
            mid = rm.run_pipeline(
                root,
                query=query,
                fetch_count=min(8, int(cfg.fetch_count or 6)),
                eval_limit=min(8, int(cfg.fetch_count or 6)),
                min_score=cfg.min_score,
                max_stars=500,
                min_stars=None,
                use_limit=5,
                use_ollama=cfg.use_ollama,
                prove=False,
                improve=False,
                apply_improve=False,
                grader="heuristic",
                worker=cfg.worker or "auto",
            )
            report["steps"].append({
                "step": "github_mid_tier_mine",
                "fetch": (mid.get("fetch") or {}).get("inserted"),
                "evaluated": (mid.get("evaluate") or {}).get("evaluated"),
                "used": (mid.get("use") or {}).get("used"),
            })
        except Exception as e:
            report["steps"].append({"step": "github_mid_tier_mine", "error": str(e)})

    usage_mod.record(
        1500 * int((mine.get("evaluate") or {}).get("evaluated") or 1),
        source="mine",
        label=f"github_review:{query[:40]}",
        workdir=root,
        enforce=True,
    )

    if bool(getattr(cfg, "record_preferences", True)):
        try:
            from . import preference_pairs as pp

            ranked: list[dict[str, Any]] = []
            for key in ("use", "evaluate", "improve_ours"):
                blob = mine.get(key) or {}
                for item in (
                    blob.get("results")
                    or blob.get("repos")
                    or blob.get("grades")
                    or blob.get("items")
                    or []
                ):
                    if isinstance(item, dict) and (
                        item.get("repo") or item.get("full_name")
                    ):
                        ranked.append(
                            {
                                "repo": item.get("repo") or item.get("full_name"),
                                "score": item.get("score") or item.get("total"),
                                "rank": item.get("rank"),
                            }
                        )
            # Prefer high-star catalog when mine ranking empty
            if len(ranked) < 2:
                for r in (phase.get("high_star") or {}).get("repos") or []:
                    ranked.append(
                        {
                            "repo": r.get("full_name"),
                            "score": r.get("stars"),
                        }
                    )
            if len(ranked) >= 2:
                pref = pp.record_from_ranked(
                    ranked, root, source="alive_cycle_github_review"
                )
                if pref:
                    report["steps"].append(
                        {
                            "step": "record_preferences",
                            "ok": True,
                            "better": pref.get("better"),
                            "worse": pref.get("worse"),
                            "source": "alive_cycle_github_review",
                        }
                    )
        except Exception as e:
            report["steps"].append({"step": "record_preferences", "error": str(e)})

    return mine


def _phase_arxiv_review(
    root: Path,
    cfg: AliveConfig,
    report: dict[str, Any],
) -> None:
    """arXiv search + optional paper_improve ranking."""
    from . import github_autonomy as ga

    queries = list(cfg.arxiv_queries or [])
    if not queries and cfg.goal:
        # Derive a paper query from the goal so the phase still runs
        queries = [str(cfg.goal)[:120]]

    if not queries:
        report["steps"].append({
            "step": "arxiv_review",
            "skipped": "no arxiv_queries and empty goal",
        })
        return

    # Rotate primary query each hour so REAL is not stuck on one saturated search
    rot = int(time.time() // 3600) % max(1, len(queries))
    aq = queries[rot]
    extras = [q for i, q in enumerate(queries) if i != rot]
    # Also sprinkle goal-derived / sibling alive queries for diversity
    for q in list(cfg.queries or [])[:3]:
        if q and q not in extras and q != aq:
            extras.append(q)
    ar = ga.improve_from_arxiv(
        aq,
        repo=cfg.our_repo or None,
        workdir=root,
        max_results=max(1, int(cfg.arxiv_count or 10)),
        apply=False,
        post_issue=False,
        also_scout=False,
        skip_seen=True,
        extra_queries=extras[:5],
        reuse_policy="lru",
    )
    report["steps"].append({
        "step": "arxiv_review",
        "query": aq,
        "extra_queries": extras[:5],
        "papers": ar.get("papers"),
        "notes": ar.get("notes"),
        "ledger": ar.get("ledger"),
        "alias": "arxiv",
        "note": "prefer NEW papers; multi-query; LRU reuse if ledger full",
    })
    usage_mod.record(
        800,
        source="arxiv",
        label=aq[:40],
        workdir=root,
        enforce=False,
    )

    # paper_improve: always when flag on (or legacy env)
    want_pi = bool(getattr(cfg, "paper_improve", True)) or (
        (os.environ.get("NEXUS_PAPER_IMPROVE") or "").strip().lower() in ("1", "true", "yes")
    )
    if want_pi:
        try:
            from . import paper_improve as _pi

            pi_res = _pi.step_paper_improve(
                root,
                limit=max(1, int(cfg.arxiv_count or 10)),
                use_llm=bool(cfg.use_ollama),
            )
            pi_res["phase"] = "arxiv_review"
            report["steps"].append(pi_res)
        except Exception as e:
            report["steps"].append({"step": "paper_improve", "error": str(e)})


def _phase_dual_review(
    root: Path,
    cfg: AliveConfig,
    report: dict[str, Any],
    *,
    mine: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Synthesize GitHub + arXiv reviews into one implement brief."""
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    gh_path = root / ".nexus_state" / "repo_mine" / "GITHUB_HIGHSTAR.md"
    plan_path = root / ".nexus_state" / "repo_mine" / "IMPROVE_OURS.md"
    paper_path = root / ".nexus_state" / "arxiv_improve" / "PAPER_IMPROVE.md"

    gh = gh_path.read_text(encoding="utf-8")[:6000] if gh_path.is_file() else "(no high-star github review yet)"
    plan = plan_path.read_text(encoding="utf-8")[:6000] if plan_path.is_file() else "(no improve-ours plan yet)"
    paper = paper_path.read_text(encoding="utf-8")[:6000] if paper_path.is_file() else "(no paper_improve yet)"

    body = "\n".join(
        [
            "# Dual review — GitHub (≥★) + arXiv → implement brief",
            "",
            f"Goal: {cfg.goal}",
            f"Pipeline: {' → '.join(cfg.pipeline or [])}",
            f"github_min_stars: {getattr(cfg, 'github_min_stars', 5000)}",
            "",
            "## 1. GitHub high-star review",
            "",
            gh,
            "",
            "## 2. Improve-ours plan (from mined/scored repos)",
            "",
            plan,
            "",
            "## 3. arXiv paper ranking",
            "",
            paper,
            "",
            "## 4. Implementer charter",
            "",
            "- Port **patterns** only (no whole-tree vendor).",
            "- Prefer tests + small modules; keep pytest green.",
            "- Prefer high-star + high paper-score items first.",
            "- After apply, meta-review must re-check tests and residual gaps.",
            "",
        ]
    )
    dest = docs / "LATEST_DUAL_REVIEW.md"
    dest.write_text(body, encoding="utf-8")
    state_dest = root / ".nexus_state" / "DUAL_REVIEW.md"
    state_dest.parent.mkdir(parents=True, exist_ok=True)
    state_dest.write_text(body, encoding="utf-8")
    return {
        "step": "dual_review",
        "ok": True,
        "path": str(dest),
        "state_path": str(state_dest),
        "mine_used": ((mine or {}).get("use") or {}).get("used")
        if isinstance(mine, dict)
        else None,
    }


def _phase_meta_review(
    root: Path,
    cfg: AliveConfig,
    report: dict[str, Any],
    *,
    checks: Optional[dict[str, Any]] = None,
    applied: Any = None,
) -> dict[str, Any]:
    """Meta-review after implement (or plan-only): residual gaps + verdict."""
    steps = report.get("steps") or []
    names = [s.get("step") for s in steps if isinstance(s, dict)]
    impl = next(
        (
            s
            for s in reversed(steps)
            if isinstance(s, dict) and s.get("step") in ("implement", "self_approve_apply")
        ),
        None,
    )
    gh = next(
        (s for s in steps if isinstance(s, dict) and s.get("step") == "github_review"),
        None,
    )
    ax = next(
        (s for s in steps if isinstance(s, dict) and s.get("step") in ("arxiv_review", "arxiv")),
        None,
    )
    tests_ok = bool((checks or {}).get("ok"))
    impl_ok = bool(impl and impl.get("ok"))
    impl_skipped = bool(impl and impl.get("skipped"))

    verdict = "plan_only"
    if impl_ok and tests_ok:
        verdict = "implemented_green"
    elif impl_ok and not tests_ok:
        verdict = "implemented_tests_red"
    elif impl_skipped:
        verdict = "implement_skipped"
    elif not tests_ok:
        verdict = "blocked_tests_red"

    lines = [
        "# Meta-review (alive cycle)",
        "",
        f"ts: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"goal: {cfg.goal}",
        f"verdict: **{verdict}**",
        f"tests_ok: {tests_ok}",
        f"phases_seen: {', '.join(str(n) for n in names)}",
        "",
        "## Review phases",
        "",
        f"- github_review: {'ok' if gh and not gh.get('error') else gh}",
        f"- arxiv_review: {'ok' if ax and not ax.get('error') else ax}",
        f"- implement: {impl}",
        "",
        "## Artifacts",
        "",
        "- `docs/LATEST_GITHUB_REVIEW.md`",
        "- `docs/LATEST_ARXIV_IMPROVE.md` / `.nexus_state/arxiv_improve/PAPER_IMPROVE.md`",
        "- `docs/LATEST_DUAL_REVIEW.md`",
        "- `docs/LATEST_IMPROVE_PLAN.md`",
        "",
        "## Residual / next",
        "",
    ]
    if verdict == "implemented_green":
        lines.append("- Landed apply; re-run official harness if SWE-Pro is the goal.")
    elif verdict == "blocked_tests_red":
        lines.append("- Fix pytest before next implement cycle.")
    elif verdict == "plan_only":
        lines.append("- Dual review ready; enable apply+self_approve or run implementer agent.")
    else:
        lines.append("- Inspect implement step + dual review; tighten gates or worker.")

    if applied and isinstance(applied, dict):
        lines += ["", "## Apply payload (truncated)", "", "```", json.dumps(applied, default=str)[:2500], "```"]

    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    dest = docs / "LATEST_META_REVIEW.md"
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / ".nexus_state" / "META_REVIEW.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return {
        "step": "meta_review",
        "ok": True,
        "verdict": verdict,
        "tests_ok": tests_ok,
        "path": str(dest),
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
        report["pipeline"] = list(cfg.pipeline or [])
        _save_state(report, root)
        return report

    # REAL cycle always: GitHub ≥5K★ research INPUT → engine+judge steps → apply/meta.
    # (DRY returns earlier. Do not make high-star + engine optional on REAL.)
    report["pipeline"] = list(cfg.pipeline or [])
    report["real_flow"] = [
        "github_ge_5k_input",
        "arxiv_input",
        "dual_brief",
        "canonical_engine_judge",
        "idea_portfolio",  # ≥1 arXiv + ≥1 GitHub, max 10 + cross-pattern novels
        "self_check_fix_loop",
        "implement_portfolio",
        "meta_review",
    ]
    q = (cfg.queries or ["multi agent"])[0]
    min_stars = max(5000, int(getattr(cfg, "github_min_stars", 5000) or 5000))
    # Force high-star floor on REAL even if config was lowered
    cfg.github_min_stars = min_stars
    mine: dict[str, Any] = {}

    # ── REQUIRED INPUT: GitHub ≥min_stars (labs→individuals) ──
    try:
        mine = _phase_github_review(root, cfg, q, report)
        report["steps"].append({
            "step": "github_ge_5k_input",
            "ok": True,
            "min_stars": min_stars,
            "query": q,
            "required_on_real": True,
            "note": "research INPUT for engine — not optional on REAL",
        })
    except usage_mod.BudgetExceeded as e:
        report["steps"].append({"step": "github_ge_5k_input", "blocked": str(e), "required_on_real": True})
        _save_state(report, root)
        return report
    except Exception as e:
        report["steps"].append({"step": "github_ge_5k_input", "error": str(e), "required_on_real": True})
        # Continue with whatever brief we have; engine still runs

    # ── INPUT: arxiv_review (search + paper_improve rank) ──
    if cfg.arxiv_queries or bool(getattr(cfg, "paper_improve", True)):
        try:
            _phase_arxiv_review(root, cfg, report)
        except Exception as e:
            report["steps"].append({"step": "arxiv_review", "error": str(e)})

    # ── dual brief (feeds engine research_brief) ──
    dual: dict[str, Any] = {}
    try:
        dual = _phase_dual_review(root, cfg, report, mine=mine)
        report["steps"].append(dual)
    except Exception as e:
        report["steps"].append({"step": "dual_review", "error": str(e)})

    # ── REQUIRED: DurableEngine + Judge (same as lab / MCP) ──
    try:
        from . import unified_pipeline as up

        brief_parts: list[str] = []
        # Prefer freshly written high-star review first
        for p in (
            root / "docs" / "LATEST_GITHUB_REVIEW.md",
            root / ".nexus_state" / "repo_mine" / "GITHUB_HIGHSTAR.md",
            root / "docs" / "LATEST_DUAL_REVIEW.md",
            root / ".nexus_state" / "arxiv_improve" / "PAPER_IMPROVE.md",
            root / "docs" / "LATEST_ARXIV_IMPROVE.md",
        ):
            if p.is_file():
                brief_parts.append(
                    f"### {p.name}\n"
                    + p.read_text(encoding="utf-8", errors="replace")[:5000]
                )
        # Inline high-star list from this cycle if phase stored it
        for st in report.get("steps") or []:
            if isinstance(st, dict) and st.get("step") == "github_review":
                hs = (st.get("high_star") or {}).get("repos") or []
                if hs:
                    lines = [f"### GitHub ≥{min_stars}★ (this cycle)"]
                    for r in hs[:15]:
                        lines.append(
                            f"- {r.get('full_name')} ★{r.get('stars')}: "
                            f"{(r.get('description') or '')[:100]}"
                        )
                    brief_parts.insert(0, "\n".join(lines))
                break

        eng_res = up.run_canonical(
            root,
            query=q,
            research_brief="\n\n".join(brief_parts),
            goal_hint=str(cfg.goal or "")[:400],
            auto_approve=True,
            source="alive_real",
        )
        report["steps"].append({
            "step": "canonical_engine",
            "ok": bool(eng_res.get("ok")),
            "task_id": eng_res.get("task_id"),
            "status": eng_res.get("status"),
            "pipeline": eng_res.get("pipeline"),
            "judge_steps": eng_res.get("steps"),
            "error": eng_res.get("error"),
            "required_on_real": True,
            "github_min_stars": min_stars,
            "note": (
                f"REAL: GitHub ≥{min_stars}★ research INPUT then "
                "DurableEngine+Judge (same as lab canonical_pipeline)"
            ),
        })
        usage_mod.record(
            2000,
            source="canonical_engine",
            label=str(eng_res.get("task_id") or "engine")[:40],
            workdir=root,
            enforce=False,
        )
    except Exception as e:
        report["steps"].append({
            "step": "canonical_engine",
            "error": str(e),
            "required_on_real": True,
        })

    # ── Build implement portfolio: ≥1 arXiv + ≥1 GitHub, max 10 + cross-pattern novels ──
    portfolio_blob: dict[str, Any] = {}
    try:
        from . import idea_portfolio as ip

        portfolio_blob = ip.build_portfolio(
            root,
            min_arxiv=int(getattr(cfg, "implement_min_arxiv", 1) or 1),
            min_github=int(getattr(cfg, "implement_min_github", 1) or 1),
            max_ideas=min(10, int(getattr(cfg, "implement_max_ideas", 10) or 10)),
            min_github_score=float(cfg.min_score or 0),
        )
        if not bool(getattr(cfg, "cross_pattern_scan", True)):
            portfolio_blob["novels"] = []
        report["steps"].append({
            "step": "idea_portfolio",
            "ok": bool(portfolio_blob.get("ok")),
            "path": portfolio_blob.get("path"),
            "meta": portfolio_blob.get("meta"),
            "error": portfolio_blob.get("error"),
            "novels": len(portfolio_blob.get("novels") or []),
            "ids": [p.get("id") for p in (portfolio_blob.get("portfolio") or [])],
            "note": "≥1 arXiv + ≥1 GitHub idea, max 10; cross-pattern novel scan",
        })
    except Exception as e:
        report["steps"].append({"step": "idea_portfolio", "error": str(e), "ok": False})

    # ── self_check → if red, FIX LOOP until green → then implement portfolio ──
    checks, fix_applied = _self_check_fix_loop(
        root, cfg, report, phase="pre_implement"
    )
    applied = fix_applied

    if not checks.get("ok"):
        report["steps"].append({
            "step": "implement",
            "skipped": "tests still red after fix_loop — refusing feature implement/push",
            "alias": "self_approve_apply",
            "fix_max_attempts": int(getattr(cfg, "fix_max_attempts", 5) or 5),
        })
    elif cfg.apply and cfg.self_approve:
        try:
            # Decision package + board signal before hard apply (2511.15755 / zenith)
            gate = _self_approve_decision_gate(root, cfg, report=report)
            report["steps"].append({"step": "self_approve_decision", **gate})
            if not gate.get("allow"):
                report["steps"].append({
                    "step": "implement",
                    "skipped": gate.get("skip_reason") or "decision_or_signal_blocked",
                    "signal": gate.get("signal"),
                    "decision": gate.get("decision"),
                    "alias": "self_approve_apply",
                })
            else:
                from . import idea_portfolio as ip

                portfolio = list(portfolio_blob.get("portfolio") or [])
                if not portfolio:
                    # fallback single improve_ours if portfolio empty
                    applied = rm.step_improve_ours(
                        root,
                        min_score=cfg.min_score,
                        limit=3,
                        apply=True,
                        our_repo=cfg.our_repo or None,
                        worker=cfg.worker or "auto",
                    )
                    apply_status = _improve_ours_apply_status(applied)
                    report["steps"].append({
                        "step": "implement",
                        "ok": bool(apply_status.get("ok")),
                        "mode": "improve_ours_fallback",
                        "reason": apply_status.get("reason"),
                        "alias": "self_approve_apply",
                        "phase": "implement",
                    })
                else:
                    impl = ip.implement_portfolio(
                        root,
                        portfolio,
                        worker=cfg.worker or "auto",
                        our_repo=cfg.our_repo or "",
                        apply=True,
                    )
                    applied = impl
                    report["steps"].append({
                        "step": "implement",
                        "ok": bool(impl.get("ok")),
                        "mode": "idea_portfolio",
                        "implemented": impl.get("implemented"),
                        "total": impl.get("total"),
                        "arxiv_done": impl.get("arxiv_done"),
                        "github_done": impl.get("github_done"),
                        "cross_done": impl.get("cross_done"),
                        "results": impl.get("results"),
                        "decision": gate.get("decision"),
                        "signal": gate.get("signal"),
                        "alias": "self_approve_apply",
                        "phase": "implement",
                        "note": "min 1 arxiv + 1 github, max 10 ideas",
                    })
                    if impl.get("ok"):
                        usage_mod.record(
                            5000 * max(1, int(impl.get("implemented") or 1)),
                            source="improve_apply",
                            label="implement_portfolio",
                            workdir=root,
                            enforce=True,
                        )
                    # Quota hard requirement for REAL
                    if int(impl.get("arxiv_done") or 0) < int(
                        getattr(cfg, "implement_min_arxiv", 1) or 1
                    ) or int(impl.get("github_done") or 0) < int(
                        getattr(cfg, "implement_min_github", 1) or 1
                    ):
                        report["steps"].append({
                            "step": "implement_quota",
                            "ok": False,
                            "arxiv_done": impl.get("arxiv_done"),
                            "github_done": impl.get("github_done"),
                            "required": {
                                "arxiv": getattr(cfg, "implement_min_arxiv", 1),
                                "github": getattr(cfg, "implement_min_github", 1),
                            },
                            "note": "REAL quota unmet — keep fix/implement before push",
                        })
                # After feature apply: re-check; if red, fix_loop until green again
                checks, post_fix = _self_check_fix_loop(
                    root, cfg, report, phase="post_implement"
                )
                if post_fix is not None:
                    applied = post_fix
        except usage_mod.BudgetExceeded as e:
            report["steps"].append({"step": "implement", "blocked": str(e)})
        except Exception as e:
            report["steps"].append({"step": "implement", "error": str(e)})
    elif cfg.apply and not cfg.self_approve:
        report["steps"].append({
            "step": "implement",
            "skipped": "self_approve=false — set alive.json self_approve true to auto-apply when tests pass",
            "alias": "self_approve_apply",
        })
    else:
        report["steps"].append({
            "step": "implement",
            "skipped": "apply/self_approve not both true — plan only (research+engine still ran)",
            "alias": "self_approve_apply",
        })

    # 4a) optional promote gate after green checks (P3.2 / P3.3)
    # Explicit promote_on_done, or auto when self_approve landed a real apply.
    if _should_promote_on_done(cfg, checks=checks, report=report):
        try:
            promote_step = _run_promote_on_done(
                root,
                cfg,
                checks=checks,
                applied=applied,
            )
            if not cfg.promote_on_done:
                promote_step = {
                    **promote_step,
                    "auto": True,
                    "auto_reason": "self_approve_apply",
                }
            report["steps"].append(promote_step)
            if promote_step.get("blocked"):
                report["blocked"] = promote_step.get("blocked")
                _save_state(report, root)
                return report
        except Exception as e:
            report["steps"].append({"step": "promote_on_done", "error": str(e)})

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

    # ── PHASE: meta_review (always when enabled — plan-only or post-implement) ──
    if bool(getattr(cfg, "meta_review", True)):
        try:
            # Fresh checks for meta verdict when implement ran
            meta_checks = checks
            if applied:
                meta_checks = _run_checks(root)
                report["steps"].append({"step": "self_check_meta", **meta_checks})
            mr = _phase_meta_review(
                root, cfg, report, checks=meta_checks, applied=applied
            )
            report["steps"].append(mr)
        except Exception as e:
            report["steps"].append({"step": "meta_review", "error": str(e)})

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

    # 7) principled stop (zenith gap / no-progress discipline)
    try:
        stop_dec = _record_principled_stop(root, cfg, report, checks=checks)
        report["stop"] = stop_dec
        if stop_dec.get("stop"):
            report["stopped"] = True
            report["stop_reason"] = stop_dec.get("reason")
            report["steps"].append({"step": "principled_stop", **stop_dec})
    except Exception as e:
        report["steps"].append({"step": "principled_stop", "error": str(e)})

    report["usage"] = usage_mod.status(root)
    report["ok"] = True
    # P1.1: mission-control ops plane — register this cycle as a job (fail-open)
    try:
        from .ops_store import note_alive_cycle

        ops_job = note_alive_cycle(
            root,
            {**report, "goal": cfg.goal, "cycle": int(time.time())},
            tokens=0,
        )
        if ops_job:
            report["ops_job"] = {
                "id": ops_job.get("id"),
                "status": ops_job.get("status"),
                "kind": ops_job.get("kind"),
            }
            report["steps"].append(
                {
                    "step": "ops_store",
                    "job_id": ops_job.get("id"),
                    "status": ops_job.get("status"),
                }
            )
    except Exception as e:
        report["steps"].append({"step": "ops_store", "error": str(e)})

    # REAL only: operator-facing "what was implemented" summary (skip dry)
    if not dry_run:
        try:
            summary = write_implement_summary(root, report, cfg=cfg)
            report["implement_summary_path"] = summary.get("path")
            report["implement_summary"] = summary.get("text")
            report["steps"].append({
                "step": "implement_summary",
                "ok": True,
                "path": summary.get("path"),
                "implemented_count": summary.get("implemented_count"),
            })
            # Always print so /tmp/nexus-alive-watch.log shows what landed
            print("\n" + summary.get("text", ""), flush=True)
        except Exception as e:
            report["steps"].append({"step": "implement_summary", "error": str(e)})

    _save_state(report, root)
    return report


def _pct(num: float, den: float) -> float:
    if not den:
        return 0.0
    return round(100.0 * float(num) / float(den), 1)


def write_implement_summary(
    root: Path,
    report: dict[str, Any],
    *,
    cfg: Optional[AliveConfig] = None,
) -> dict[str, Any]:
    """Executive review for REAL self-improve: hit rates, tokens, approvals, implement list."""
    root = Path(root).resolve()
    steps = [s for s in (report.get("steps") or []) if isinstance(s, dict)]
    impl = next((s for s in reversed(steps) if s.get("step") == "implement"), None)
    portfolio = next((s for s in steps if s.get("step") == "idea_portfolio"), None)
    fix_loops = [s for s in steps if s.get("step") == "fix_loop"]
    pub = next((s for s in steps if s.get("step") == "publish_github"), None)
    eng = next((s for s in steps if s.get("step") == "canonical_engine"), None)
    gate = next((s for s in steps if s.get("step") == "self_approve_decision"), None)
    gh_in = next(
        (s for s in steps if s.get("step") in ("github_review", "github_ge_5k_input")),
        None,
    )
    ax_in = next(
        (s for s in steps if s.get("step") in ("arxiv_review", "arxiv", "paper_improve")),
        None,
    )

    tests_checks = [s for s in steps if s.get("step") in (
        "self_check", "self_check_final", "self_check_meta", "self_check_after_apply"
    )]
    tests_final = tests_checks[-1] if tests_checks else None
    tests_green_n = sum(1 for s in tests_checks if s.get("ok"))
    tests_total_n = len(tests_checks)

    results: list[dict[str, Any]] = []
    if isinstance(impl, dict):
        results = [r for r in (impl.get("results") or []) if isinstance(r, dict)]
    implemented_ok = [r for r in results if r.get("ok")]
    implemented_fail = [r for r in results if not r.get("ok")]
    n_ideas = len(results)
    n_ok = len(implemented_ok)
    arxiv_ok = sum(1 for r in implemented_ok if r.get("source") == "arxiv")
    github_ok = sum(1 for r in implemented_ok if r.get("source") == "github")
    cross_ok = sum(1 for r in implemented_ok if r.get("source") == "cross_pattern")
    arxiv_n = sum(1 for r in results if r.get("source") == "arxiv")
    github_n = sum(1 for r in results if r.get("source") == "github")
    cross_n = sum(1 for r in results if r.get("source") == "cross_pattern")

    # Judge hit rates from engine steps
    judge_steps = list((eng or {}).get("judge_steps") or [])
    j_pass = sum(1 for j in judge_steps if str(j.get("judge_decision") or "").lower() == "pass")
    j_revise = sum(1 for j in judge_steps if str(j.get("judge_decision") or "").lower() == "revise")
    j_fail = sum(1 for j in judge_steps if str(j.get("judge_decision") or "").lower() == "fail")
    j_n = len(judge_steps)
    scores = [
        float(j.get("judge_score"))
        for j in judge_steps
        if j.get("judge_score") is not None
    ]
    avg_judge = round(sum(scores) / len(scores), 3) if scores else None

    # Fix loop hit rate
    fix_attempts = [f for f in fix_loops if f.get("attempt") is not None or f.get("worker")]
    fix_green = any(f.get("green") for f in fix_loops)

    # Approvals / gates
    gate_allow = None
    if isinstance(gate, dict):
        gate_allow = bool(gate.get("allow")) if "allow" in gate else None
    impl_skipped = bool(isinstance(impl, dict) and impl.get("skipped"))
    impl_ok = bool(isinstance(impl, dict) and impl.get("ok") and not impl_skipped)
    pushed = bool(isinstance(pub, dict) and (pub.get("pushed") or pub.get("ok")))
    pub_skipped = bool(isinstance(pub, dict) and pub.get("skipped"))

    # Tokens / usage
    usage_blob = report.get("usage") if isinstance(report.get("usage"), dict) else {}
    try:
        usage_blob = usage_blob or usage_mod.status(root)
    except Exception:
        pass
    totals = (usage_blob.get("totals") or {}) if isinstance(usage_blob, dict) else {}
    budget = (usage_blob.get("budget") or {}) if isinstance(usage_blob, dict) else {}
    day_tok = int(totals.get("day_tokens") or 0)
    month_tok = int(totals.get("month_tokens") or 0)
    day_calls = int(totals.get("day_calls") or 0)
    daily_cap = int(budget.get("daily_tokens") or 0) or 1
    monthly_cap = int(budget.get("monthly_tokens") or 0) or 1
    day_pct = float(usage_blob.get("day_pct") or _pct(day_tok, daily_cap))
    month_pct = float(usage_blob.get("month_pct") or _pct(month_tok, monthly_cap))
    by_source = dict(totals.get("by_source") or {})

    # Cycle token estimate from steps we recorded this run
    cycle_sources = ("mine", "arxiv", "canonical_engine", "improve_apply", "fix_loop", "tests", "paper_improve")
    # We don't have per-cycle ledger isolation easily; show budget snapshot + step count
    step_names = [s.get("step") for s in steps]
    n_steps = len(steps)

    metrics = {
        "implement_hit_rate_pct": _pct(n_ok, n_ideas) if n_ideas else None,
        "arxiv_hit_rate_pct": _pct(arxiv_ok, max(1, arxiv_n)) if arxiv_n else None,
        "github_hit_rate_pct": _pct(github_ok, max(1, github_n)) if github_n else None,
        "cross_hit_rate_pct": _pct(cross_ok, max(1, cross_n)) if cross_n else None,
        "judge_pass_rate_pct": _pct(j_pass, j_n) if j_n else None,
        "judge_revise_rate_pct": _pct(j_revise, j_n) if j_n else None,
        "judge_fail_rate_pct": _pct(j_fail, j_n) if j_n else None,
        "judge_avg_score": avg_judge,
        "tests_green_rate_pct": _pct(tests_green_n, tests_total_n) if tests_total_n else None,
        "tests_final_green": (tests_final or {}).get("ok"),
        "approval_allow": gate_allow,
        "implement_ok": impl_ok,
        "implement_skipped": impl_skipped,
        "pushed": pushed,
        "publish_skipped": pub_skipped,
        "fix_loop_attempts": len(fix_attempts),
        "fix_loop_green": fix_green,
        "day_tokens": day_tok,
        "month_tokens": month_tok,
        "day_calls": day_calls,
        "day_budget_pct": round(day_pct, 1),
        "month_budget_pct": round(month_pct, 1),
        "by_source": by_source,
        "steps_recorded": n_steps,
        "ideas_total": n_ideas,
        "ideas_ok": n_ok,
        "arxiv_ok": arxiv_ok,
        "github_ok": github_ok,
        "cross_ok": cross_ok,
    }

    # Overall health score (simple weighted)
    components = []
    if metrics["implement_hit_rate_pct"] is not None:
        components.append(metrics["implement_hit_rate_pct"])
    if metrics["judge_pass_rate_pct"] is not None:
        components.append(metrics["judge_pass_rate_pct"])
    if metrics["tests_green_rate_pct"] is not None:
        components.append(metrics["tests_green_rate_pct"])
    if gate_allow is True:
        components.append(100.0)
    elif gate_allow is False:
        components.append(0.0)
    if metrics["tests_final_green"] is True:
        components.append(100.0)
    elif metrics["tests_final_green"] is False:
        components.append(0.0)
    overall = round(sum(components) / len(components), 1) if components else None
    metrics["overall_health_pct"] = overall

    lines = [
        "▶ EXECUTIVE REVIEW — REAL SELF-IMPROVE",
        f"ts: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"goal: {(cfg.goal if cfg else report.get('goal') or '')[:220]}",
        f"overall_health: {overall if overall is not None else 'n/a'}%",
        "",
        "## Scoreboard (hit rates)",
        f"| Metric | Value |",
        f"|---|---|",
        f"| **Overall health** | **{overall if overall is not None else 'n/a'}%** |",
        f"| Implement success | {n_ok}/{n_ideas or 0} = "
        f"{metrics['implement_hit_rate_pct'] if metrics['implement_hit_rate_pct'] is not None else 'n/a'}% |",
        f"| arXiv ideas landed | {arxiv_ok}/{arxiv_n or 0} = "
        f"{metrics['arxiv_hit_rate_pct'] if metrics['arxiv_hit_rate_pct'] is not None else 'n/a'}% |",
        f"| GitHub ideas landed | {github_ok}/{github_n or 0} = "
        f"{metrics['github_hit_rate_pct'] if metrics['github_hit_rate_pct'] is not None else 'n/a'}% |",
        f"| Cross-pattern novels | {cross_ok}/{cross_n or 0} = "
        f"{metrics['cross_hit_rate_pct'] if metrics['cross_hit_rate_pct'] is not None else 'n/a'}% |",
        f"| Judge pass rate | {j_pass}/{j_n or 0} = "
        f"{metrics['judge_pass_rate_pct'] if metrics['judge_pass_rate_pct'] is not None else 'n/a'}% |",
        f"| Judge revise rate | {j_revise}/{j_n or 0} = "
        f"{metrics['judge_revise_rate_pct'] if metrics['judge_revise_rate_pct'] is not None else 'n/a'}% |",
        f"| Judge fail rate | {j_fail}/{j_n or 0} = "
        f"{metrics['judge_fail_rate_pct'] if metrics['judge_fail_rate_pct'] is not None else 'n/a'}% |",
        f"| Judge avg score | {avg_judge if avg_judge is not None else 'n/a'} |",
        f"| Tests green rate (this cycle) | {tests_green_n}/{tests_total_n or 0} = "
        f"{metrics['tests_green_rate_pct'] if metrics['tests_green_rate_pct'] is not None else 'n/a'}% |",
        f"| Final tests green | {metrics['tests_final_green']} |",
        f"| Fix-loop attempts | {len(fix_attempts)} · green={fix_green} |",
        "",
        "## Approvals & gates",
        f"| Gate | Result |",
        f"|---|---|",
        f"| Decision/board allow | {gate_allow if gate_allow is not None else 'n/a'} |",
        f"| Board signal | {(gate or {}).get('signal') if gate else 'n/a'} |",
        f"| Implement ok | {impl_ok} |",
        f"| Implement skipped | {impl_skipped} "
        f"{('— ' + str((impl or {}).get('skipped'))) if impl_skipped else ''} |",
        f"| Publish pushed | {pushed} |",
        f"| Publish skipped | {pub_skipped} "
        f"{('— ' + str((pub or {}).get('skipped'))) if pub_skipped else ''} |",
        "",
        "## Tokens & budget",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Day tokens | {day_tok:,} ({day_pct:.1f}% of daily cap {daily_cap:,}) |",
        f"| Month tokens | {month_tok:,} ({month_pct:.1f}% of monthly cap {monthly_cap:,}) |",
        f"| Day API/CLI calls (ledger) | {day_calls} |",
        f"| Steps recorded this cycle | {n_steps} |",
        f"| Throttle | {usage_blob.get('throttle') if isinstance(usage_blob, dict) else 'n/a'} |",
        "",
    ]
    if by_source:
        lines.append("### Tokens by source (ledger totals)")
        for src, tok in sorted(by_source.items(), key=lambda x: -int(x[1] or 0))[:12]:
            lines.append(f"- `{src}`: {int(tok):,} ({_pct(int(tok), max(1, month_tok))}%)")
        lines.append("")

    # Research inputs
    lines += [
        "## Research inputs",
        f"- GitHub ≥5K★ phase: {bool(gh_in)} "
        f"{('(ok=' + str((gh_in or {}).get('ok')) + ')') if gh_in else ''}",
        f"- arXiv phase: {bool(ax_in)}",
        f"- Portfolio: arxiv_pool="
        f"{(portfolio or {}).get('meta', {}).get('arxiv_pool') if isinstance(portfolio, dict) else '?'} "
        f"github_pool="
        f"{(portfolio or {}).get('meta', {}).get('github_pool') if isinstance(portfolio, dict) else '?'} "
        f"novels="
        f"{(portfolio or {}).get('novels') if isinstance(portfolio, dict) else '?'}",
        "",
    ]

    # What was implemented
    lines.append("## What was implemented")
    if isinstance(impl, dict) and impl.get("skipped"):
        lines.append(f"- SKIPPED: {impl.get('skipped')}")
    elif results:
        for r in results:
            st = "OK" if r.get("ok") else "FAIL"
            lines.append(
                f"- [{st}] [{r.get('source')}] `{r.get('id')}` "
                f"worker={r.get('worker') or '?'}"
            )
            if r.get("error"):
                lines.append(f"  error: {str(r.get('error'))[:180]}")
    elif isinstance(impl, dict):
        lines.append(
            f"- mode={impl.get('mode')} ok={impl.get('ok')} "
            f"{impl.get('reason') or ''}"
        )
    else:
        lines.append("- No implement step results.")
    lines.append("")

    if eng:
        lines.append("## Engine + judge (per step)")
        lines.append(f"- task `{eng.get('task_id')}` status={eng.get('status')}")
        for js in judge_steps[:14]:
            lines.append(
                f"  · {js.get('step')}:{js.get('name')} → "
                f"**{js.get('judge_decision')}** score={js.get('judge_score')}"
            )
        lines.append("")

    if fix_loops:
        lines.append("## Fix loop detail")
        for f in fix_loops[-8:]:
            lines.append(
                f"- {f.get('phase')} #{f.get('attempt')}: "
                f"green={f.get('green')} worker={f.get('worker')} "
                f"{f.get('note') or f.get('skipped') or f.get('error') or ''}"
            )
        lines.append("")

    lines += [
        "## Artifacts",
        "- `docs/LATEST_IMPLEMENT_SUMMARY.md` (this executive review)",
        "- `docs/LATEST_IDEA_PORTFOLIO.md`",
        "- `docs/LATEST_META_REVIEW.md`",
        "- `.nexus_state/alive_state.json`",
        "- `.nexus_state/LAST_IMPLEMENT_SUMMARY.json` (metrics machine-readable)",
        "",
        f"**Bottom line:** overall_health={overall}% · "
        f"implemented {n_ok}/{n_ideas or 0} ideas · "
        f"tests_final={metrics['tests_final_green']} · "
        f"pushed={pushed} · day_budget={day_pct:.1f}%",
        "",
    ]

    text = "\n".join(lines) + "\n"
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "LATEST_IMPLEMENT_SUMMARY.md"
    path.write_text(text, encoding="utf-8")
    (root / ".nexus_state" / "LAST_IMPLEMENT_SUMMARY.md").write_text(text, encoding="utf-8")
    (root / ".nexus_state" / "LAST_IMPLEMENT_SUMMARY.json").write_text(
        json.dumps(
            {
                "ts": time.time(),
                "metrics": metrics,
                "implemented_ok": implemented_ok,
                "implemented_fail": implemented_fail,
                "implement_step": impl,
                "portfolio": portfolio,
                "tests_ok": (tests_final or {}).get("ok"),
                "publish": pub,
                "gate": gate,
                "engine": {
                    "task_id": (eng or {}).get("task_id"),
                    "status": (eng or {}).get("status"),
                    "judge_steps": judge_steps,
                },
                "text": text,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return {
        "path": str(path),
        "text": text,
        "metrics": metrics,
        "implemented_count": n_ok,
        "failed_count": len(implemented_fail),
    }


def _save_state(report: dict[str, Any], workdir: Path) -> None:
    p = state_path(workdir)
    p.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


def _record_principled_stop(
    root: Path,
    cfg: AliveConfig,
    report: dict[str, Any],
    *,
    checks: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Load stop board, record this cycle's progress, persist, return decision."""
    from .durability.stop import (
        PrincipledStop,
        StopPolicy,
        cycle_progressed,
        default_stop_path,
    )

    path = default_stop_path(root)
    stopper = PrincipledStop.load(path)
    # refresh policy from alive config each cycle (operator knobs)
    max_cycles = int(cfg.stop_max_cycles or 0) or None
    stopper.policy = StopPolicy(
        max_no_progress=max(1, int(cfg.stop_max_no_progress or 3)),
        max_cycles=max_cycles,
        stop_when_gaps_closed=bool(cfg.stop_when_gaps_closed),
        require_registered_gaps=True,
        stop_on_tests_red=bool(cfg.stop_on_tests_red),
        stop_on_budget=True,
    )
    # P1.5: seed open backlog ids from LATEST_IMPROVE_PLAN / IMPROVE_OURS
    seed_info: Optional[dict[str, Any]] = None
    if bool(getattr(cfg, "seed_gaps", True)):
        try:
            from .durability.gap_seed import seed_gap_board

            seed_info = seed_gap_board(stopper, root, reopen_closed=False, close_done=True)
            report["gap_seed"] = {
                "n_plan": seed_info.get("n_plan"),
                "registered": seed_info.get("registered"),
                "closed": seed_info.get("closed"),
                "board": seed_info.get("board"),
            }
        except Exception as e:
            report.setdefault("steps", []).append({"step": "gap_seed", "error": str(e)})

    # Board signal → gap board (if decision gate already ran this cycle, reuse it;
    # otherwise compute a lightweight board signal so thrash still registers).
    board_sync: Optional[dict[str, Any]] = None
    if bool(getattr(cfg, "sync_board_gaps", True)):
        try:
            from . import apply_select as asel

            sig_name = ""
            sig_reason = ""
            sig_detail = ""
            hints: list[str] = []
            for s in report.get("steps") or []:
                if isinstance(s, dict) and s.get("step") == "self_approve_decision":
                    sig_name = str(s.get("signal") or "")
                    sig_reason = str(s.get("signal_reason") or s.get("skip_reason") or "")
                    gap_sync = s.get("gap_sync")
                    if isinstance(gap_sync, dict):
                        board_sync = gap_sync  # already persisted mid-cycle
                    break
            if not board_sync:
                if not sig_name:
                    # Lightweight board peek (no auto_index to stay cheap)
                    board = asel.improve_board(
                        root,
                        min_score=float(cfg.min_score),
                        limit=max(3, int(cfg.use_limit or 3)),
                        grader=_grader_role(cfg),
                        implementer=str(cfg.implementer or asel.DEFAULT_ROLES["implementer"]),
                        verifier=str(cfg.verifier or asel.DEFAULT_ROLES["verifier"]),
                        goal=str(cfg.goal or "self-improve"),
                        auto_index=False,
                    )
                    sig_name = str(board.get("signal") or "")
                    sig_reason = str(board.get("signal_reason") or "")
                    sig_detail = str(board.get("signal_detail") or "")
                    hints = list(board.get("replan_hints") or [])
                if sig_name:
                    board_sync = asel.sync_signal_to_stop(
                        stopper,
                        {
                            "signal": sig_name,
                            "reason": sig_reason,
                            "detail": sig_detail,
                            "hints": hints,
                        },
                        abort_on_hard_stop=bool(
                            getattr(cfg, "abort_on_board_stop", True)
                        ),
                        close_on_continue=True,
                    )
                    report.setdefault("steps", []).append(
                        {"step": "board_gap_sync", **board_sync}
                    )
        except Exception as e:
            report.setdefault("steps", []).append(
                {"step": "board_gap_sync", "error": str(e)}
            )

    # if apply path ran, stash for progress heuristic
    if any(
        isinstance(s, dict) and s.get("step") == "self_approve_apply" and s.get("ok")
        for s in (report.get("steps") or [])
    ):
        report.setdefault("applied", {"status": "completed"})
    progressed = cycle_progressed(report)
    tests_ok = True if not checks else bool(checks.get("ok"))
    budget_ok = not bool(report.get("blocked"))
    decision = stopper.record_cycle(
        progressed=progressed,
        tests_ok=tests_ok,
        budget_ok=budget_ok,
        note=f"goal={cfg.goal[:80]}",
    )
    stopper.save(path)
    out = decision.to_dict()
    if seed_info is not None:
        out["gap_seed"] = {
            "n_plan": seed_info.get("n_plan"),
            "registered": seed_info.get("registered"),
            "closed": seed_info.get("closed"),
            "board": seed_info.get("board"),
        }
    if board_sync is not None:
        out["board_gap_sync"] = board_sync
    return out


def seed_gaps(
    workdir: Optional[Path] = None,
    *,
    reopen_closed: bool = False,
    close_done: bool = True,
) -> dict[str, Any]:
    """Operator helper: seed / refresh the gap board from plan docs (no cycle)."""
    from .durability.gap_seed import board_snapshot, seed_gap_board
    from .durability.stop import PrincipledStop, StopPolicy, default_stop_path

    root = _root(workdir)
    cfg = load_config(root)
    path = default_stop_path(root)
    stopper = PrincipledStop.load(path)
    max_cycles = int(cfg.stop_max_cycles or 0) or None
    stopper.policy = StopPolicy(
        max_no_progress=max(1, int(cfg.stop_max_no_progress or 3)),
        max_cycles=max_cycles,
        stop_when_gaps_closed=bool(cfg.stop_when_gaps_closed),
        require_registered_gaps=True,
        stop_on_tests_red=bool(cfg.stop_on_tests_red),
        stop_on_budget=True,
    )
    info = seed_gap_board(
        stopper,
        root,
        reopen_closed=reopen_closed,
        close_done=close_done,
    )
    stopper.save(path)
    snap = board_snapshot(stopper)
    return {**info, "snapshot": snap, "path": str(path)}


def gap_board(workdir: Optional[Path] = None) -> dict[str, Any]:
    """Read-only view of the principled-stop gap board."""
    from .durability.gap_seed import board_snapshot
    from .durability.stop import PrincipledStop, default_stop_path

    root = _root(workdir)
    path = default_stop_path(root)
    stopper = PrincipledStop.load(path)
    snap = board_snapshot(stopper)
    snap["path"] = str(path)
    return snap


def close_gap(
    gap_id: str,
    workdir: Optional[Path] = None,
    *,
    evidence: str = "",
) -> dict[str, Any]:
    """Mark a gap closed on the alive stop board."""
    from .durability.gap_seed import board_snapshot
    from .durability.stop import PrincipledStop, default_stop_path

    root = _root(workdir)
    path = default_stop_path(root)
    stopper = PrincipledStop.load(path)
    item = stopper.close_gap(gap_id, evidence=evidence or "operator close")
    stopper.save(path)
    return {"closed": item.to_dict(), "board": board_snapshot(stopper), "path": str(path)}


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
    print(f"  stop:     max_no_progress={cfg.stop_max_no_progress} "
          f"max_cycles={cfg.stop_max_cycles or '∞'}")
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
            if rep.get("stopped"):
                print(f"  PRINCIPLED STOP: {rep.get('stop_reason')} "
                      f"— {(rep.get('stop') or {}).get('detail', '')}")
                return 0
            if max_cycles and n >= max_cycles:
                return 0
            time.sleep(max(60.0, interval))
    except KeyboardInterrupt:
        print("\n  stopped.")
        return 0
