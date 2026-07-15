"""Offline self-improve smoke: mine → grade → claim_verify + decision ledger.

First apply slice (docs/LATEST_IMPROVE_PLAN.md §5):

  mine digest → Grok-shaped grade → claim-verify → immutable ledger append
  ordered stage smoke (no live apply, no network)

CLI::

  nexus improve smoke [--fixture PATH] [--json]
  python -m nexus.improve_smoke --fixture tests/fixtures/mine_eval_sample.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .claim_verify import ClaimVerifyError, verify_claim
from .decision_ledger import DecisionLedger
from .load_mine_eval import load_one
from .stages import SMOKE_STAGES, StageOrderError, StageRunner

SCHEMA = "nexus.improve_smoke/v1"


def run_smoke(
    workdir: Path | str,
    *,
    fixture: Optional[Path | str] = None,
    repo: Optional[str] = None,
    run_id: Optional[str] = None,
    require_path_exists: bool = False,
    ledger: Optional[DecisionLedger] = None,
) -> dict[str, Any]:
    """Execute mine → grade → claim_verify with ordered stages + ledger.

    Returns a report dict with ok=True/False, stages, ledger tail, grade.
    """
    workdir = Path(workdir).resolve()
    rid = run_id or f"smoke-{uuid.uuid4().hex[:10]}"
    runner = StageRunner.smoke()
    timeline: list[dict[str, Any]] = []
    own_ledger = ledger is None
    store = ledger or DecisionLedger.open(workdir)

    def _log(event: str, detail: str = "") -> None:
        timeline.append(
            {
                "ts": time.time(),
                "event": event,
                "detail": detail,
                "next": runner.next(),
            }
        )

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "ok": False,
        "run_id": rid,
        "workdir": str(workdir),
        "stages": list(SMOKE_STAGES),
        "completed": [],
        "grade": None,
        "claim": None,
        "ledger_tail": [],
        "timeline": timeline,
        "error": None,
    }

    try:
        # --- mine: load digest / fixture (offline) ---
        runner.assert_can_run("mine")
        grade = load_one(workdir, repo=repo, fixture=fixture)
        store.append(
            run_id=rid,
            agent="mine",
            claim=f"loaded grade for {grade.get('repo')}",
            evidence_refs=[str(grade.get("path") or "")],
            grade={
                "repo": grade.get("repo"),
                "score": grade.get("score"),
                "path": grade.get("path"),
            },
            action="mine_load",
        )
        runner.mark_complete("mine")
        _log("mine", f"repo={grade.get('repo')} score={grade.get('score')}")

        # --- grade: accept Grok-shaped record (already normalized) ---
        runner.assert_can_run("grade")
        store.append(
            run_id=rid,
            agent="grade",
            claim=(
                f"grade artifact score={grade.get('score')} "
                f"idea={grade.get('idea')} skill={grade.get('skill')}"
            ),
            evidence_refs=[str(grade.get("path") or "")],
            grade={
                "repo": grade.get("repo"),
                "score": grade.get("score"),
                "idea": grade.get("idea"),
                "skill": grade.get("skill"),
                "method": grade.get("method"),
                "path": grade.get("path"),
            },
            action="grade_accept",
        )
        runner.mark_complete("grade")
        _log("grade", f"method={grade.get('method')}")
        report["grade"] = {
            "repo": grade.get("repo"),
            "score": grade.get("score"),
            "idea": grade.get("idea"),
            "skill": grade.get("skill"),
            "method": grade.get("method"),
            "path": grade.get("path"),
            "pattern": grade.get("pattern"),
        }

        # --- claim_verify: refuse ungrounded apply candidates ---
        runner.assert_can_run("claim_verify")
        claim = verify_claim(
            grade,
            workdir=workdir,
            require_path_exists=require_path_exists,
        )
        store.append(
            run_id=rid,
            agent="claim_verify",
            claim=f"verified claim for {grade.get('repo')}",
            evidence_refs=[str(grade.get("path") or "")],
            grade={
                "repo": grade.get("repo"),
                "score": claim["score"],
                "idea": claim["idea"],
                "skill": claim["skill"],
                "path": claim["path"],
            },
            action="claim_pass",
        )
        runner.mark_complete("claim_verify")
        _log("claim_verify", "ok")
        report["claim"] = claim
        report["completed"] = list(runner.completed)
        report["ok"] = runner.is_done()
        report["ledger_tail"] = store.tail(limit=10, run_id=rid)
        report["stage_status"] = runner.status()
        return report

    except (StageOrderError, ClaimVerifyError, FileNotFoundError, ValueError) as e:
        report["error"] = f"{type(e).__name__}: {e}"
        report["completed"] = list(runner.completed)
        report["stage_status"] = runner.status()
        try:
            report["ledger_tail"] = store.tail(limit=10, run_id=rid)
        except Exception:
            report["ledger_tail"] = []
        _log("error", report["error"])
        return report
    finally:
        if own_ledger:
            store.close()


def format_report(report: dict[str, Any]) -> str:
    """Human-readable smoke board."""
    g = report.get("grade") or {}
    lines = [
        "=== NEXUS improve smoke (mine → grade → claim_verify) ===",
        f"run_id:    {report.get('run_id')}",
        f"ok:        {report.get('ok')}",
        f"stages:    {' → '.join(report.get('stages') or SMOKE_STAGES)}",
        f"completed: {', '.join(report.get('completed') or []) or '(none)'}",
        f"repo:      {g.get('repo')}  score={g.get('score')} "
        f"(idea={g.get('idea')} skill={g.get('skill')})",
        f"path:      {g.get('path')}",
        f"method:    {g.get('method')}",
    ]
    if report.get("error"):
        lines.append(f"error:     {report['error']}")
    tail = report.get("ledger_tail") or []
    lines.append(f"ledger:    {len(tail)} recent decision(s)")
    for row in reversed(tail):  # chronological for display
        lines.append(
            f"  [{row.get('agent')}] {row.get('action')}: {row.get('claim')}"
        )
    lines.append(f"pass:      {'YES' if report.get('ok') else 'NO'}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="nexus-improve-smoke",
        description="Offline self-improve smoke: mine → grade → claim_verify",
    )
    ap.add_argument(
        "--path",
        default=".",
        help="project workdir (default: cwd)",
    )
    ap.add_argument(
        "--fixture",
        default=None,
        help="grade JSON fixture (default: tests/fixtures/mine_eval_sample.json)",
    )
    ap.add_argument("--repo", default=None, help="select repo id from digests")
    ap.add_argument("--run-id", default=None)
    ap.add_argument(
        "--require-path-exists",
        action="store_true",
        help="fail if grade.path is not on disk",
    )
    ap.add_argument("--json", action="store_true", help="print JSON report")
    args = ap.parse_args(list(argv) if argv is not None else None)

    workdir = Path(args.path).resolve()
    fixture = args.fixture
    if fixture is None:
        candidate = workdir / "tests" / "fixtures" / "mine_eval_sample.json"
        if candidate.is_file():
            fixture = str(candidate)

    report = run_smoke(
        workdir,
        fixture=fixture,
        repo=args.repo,
        run_id=args.run_id,
        require_path_exists=bool(args.require_path_exists),
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_report(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
