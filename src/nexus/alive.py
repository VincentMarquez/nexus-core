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


def _self_approve_apply_landed(report: dict[str, Any]) -> bool:
    """True when this cycle's self_approve_apply step reported ok."""
    for s in report.get("steps") or []:
        if isinstance(s, dict) and s.get("step") == "self_approve_apply" and s.get("ok"):
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
        # Offline preference pairs from ranked mine results (2602.04518)
        # — auto each cycle when record_preferences, not only on self_approve.
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
                                    "repo": item.get("repo")
                                    or item.get("full_name"),
                                    "score": item.get("score")
                                    or item.get("total"),
                                    "rank": item.get("rank"),
                                }
                            )
                if len(ranked) >= 2:
                    pref = pp.record_from_ranked(
                        ranked,
                        root,
                        source="alive_cycle_mine",
                    )
                    if pref:
                        report["steps"].append(
                            {
                                "step": "record_preferences",
                                "ok": True,
                                "better": pref.get("better"),
                                "worse": pref.get("worse"),
                                "source": "alive_cycle_mine",
                            }
                        )
            except Exception as e:
                report["steps"].append(
                    {"step": "record_preferences", "error": str(e)}
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
            # Decision package + board signal before hard apply (2511.15755 / zenith)
            gate = _self_approve_decision_gate(root, cfg, report=report)
            report["steps"].append({"step": "self_approve_decision", **gate})
            if not gate.get("allow"):
                report["steps"].append({
                    "step": "self_approve_apply",
                    "skipped": gate.get("skip_reason") or "decision_or_signal_blocked",
                    "signal": gate.get("signal"),
                    "decision": gate.get("decision"),
                })
            else:
                applied = rm.step_improve_ours(
                    root,
                    min_score=cfg.min_score,
                    limit=3,
                    apply=True,
                    our_repo=cfg.our_repo or None,
                    worker=cfg.worker or "auto",
                )
                apply_status = _improve_ours_apply_status(applied)
                step_rec: dict[str, Any] = {
                    "step": "self_approve_apply",
                    "ok": bool(apply_status.get("ok")),
                    "apply": applied.get("apply") if isinstance(applied, dict) else None,
                    "plan": applied.get("plan") if isinstance(applied, dict) else None,
                    "decision": gate.get("decision"),
                    "signal": gate.get("signal"),
                }
                if not step_rec["ok"]:
                    step_rec["reason"] = apply_status.get("reason") or "worker apply failed"
                report["steps"].append(step_rec)
                if step_rec["ok"]:
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
    _save_state(report, root)
    return report


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
