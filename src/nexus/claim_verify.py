"""Claim verification against grade evidence (Thucy-style, arXiv 2512.03278).

P0.4 from docs/LATEST_IMPROVE_PLAN.md — refuse apply suggestions that lack
grounding fields (score, idea, skill, path) or cannot be linked to a mine
evidence location.

Follow-on (arXiv 2503.15223 + wshobson/agents marketplace shape):
  When a grade carries an **explicit** patch payload (``patch`` /
  ``candidate_patch`` / ``patch_files`` / gold reference — not generic
  ``files``/``diff``), run a structural PatchDiff preflight via
  ``patch_diff.diff_from_grade`` and attach the report under
  ``claim["patch_diff"]``. Soft by default; set ``require_patch_diff_ok``
  to fail-closed when a *present* report has ``ok=False`` (or a verdict
  listed in ``patch_diff_fail_verdicts``). Grades without a patch payload
  are unchanged — ``require_patch_diff_ok`` does not invent a patch.

Does not call the network; offline validation only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

# Required grade claim fields (First apply slice acceptance criteria).
REQUIRED_CLAIM_FIELDS: tuple[str, ...] = ("score", "idea", "skill", "path")

# Prefer these optional identity fields when present.
OPTIONAL_IDENTITY: tuple[str, ...] = ("repo", "arxiv_id", "method", "pattern")


class ClaimVerifyError(ValueError):
    """Claim failed verification against evidence requirements."""


def _as_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ClaimVerifyError(f"claim.{field} must be numeric") from e


def missing_fields(grade: Any) -> list[str]:
    """Return list of required fields missing or empty."""
    if not isinstance(grade, dict):
        return list(REQUIRED_CLAIM_FIELDS)
    missing: list[str] = []
    for key in REQUIRED_CLAIM_FIELDS:
        if key not in grade:
            missing.append(key)
            continue
        val = grade[key]
        if key == "path":
            if not str(val or "").strip():
                missing.append(key)
        elif key in ("score", "idea", "skill"):
            try:
                float(val)
            except (TypeError, ValueError):
                missing.append(key)
    return missing


def _attach_patch_diff(
    grade: dict[str, Any],
    out: dict[str, Any],
    *,
    run_patch_diff: bool,
    require_patch_diff_ok: bool,
    patch_diff_checks: Optional[Sequence[str]],
    patch_diff_min_overlap: float,
    patch_diff_fail_verdicts: Optional[Sequence[str]],
) -> None:
    """Optionally run PatchDiff and attach / gate (mutates *out*).

    Soft mode never raises for PatchDiff config/parse errors — attaches a
    skip/error report instead. Hard mode converts those to ClaimVerifyError.
    """
    if not run_patch_diff:
        return
    try:
        from . import patch_diff as pd
    except Exception as e:  # pragma: no cover — import failure is environment
        out["patch_diff"] = {
            "schema": "nexus.patch_diff/v1",
            "ok": False,
            "verdict": "skip",
            "error": f"import_failed:{e}",
            "flags": ["error"],
            "findings": [],
        }
        if require_patch_diff_ok:
            raise ClaimVerifyError(f"patch_diff unavailable: {e}") from e
        return

    try:
        report = pd.diff_from_grade(
            grade,
            checks=patch_diff_checks,
            min_overlap=patch_diff_min_overlap,
        )
    except pd.PatchDiffError as e:
        out["patch_diff"] = {
            "schema": pd.SCHEMA,
            "ok": False,
            "verdict": "skip",
            "error": str(e),
            "flags": ["error"],
            "findings": [],
        }
        if require_patch_diff_ok:
            raise ClaimVerifyError(f"patch_diff invalid config: {e}") from e
        return

    if report is None:
        # No explicit patch payload — require_patch_diff_ok does not invent one.
        return
    out["patch_diff"] = report

    verdict = str(report.get("verdict") or "fail")
    flags = report.get("flags") or []
    fail_verdicts = {
        str(v).strip()
        for v in (patch_diff_fail_verdicts or ())
        if str(v).strip()
    }
    bad = (not report.get("ok")) or (verdict in fail_verdicts)
    if require_patch_diff_ok and bad:
        raise ClaimVerifyError(
            f"patch_diff failed (verdict={verdict}, flags={flags})"
        )


def verify_claim(
    grade: Any,
    *,
    workdir: Optional[Path | str] = None,
    require_path_exists: bool = False,
    min_score: Optional[float] = None,
    run_patch_diff: bool = True,
    require_patch_diff_ok: bool = False,
    patch_diff_checks: Optional[Sequence[str]] = None,
    patch_diff_min_overlap: float = 0.0,
    patch_diff_fail_verdicts: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Validate a grade claim for apply eligibility.

    Required: score, idea, skill, path (non-empty strings / numerics).
    Optional: if *require_path_exists*, path must resolve under *workdir*
    (or absolute) and exist on disk.

    Structural PatchDiff preflight (arXiv 2503.15223 idea, offline):
    when the grade includes an explicit patch payload, run checks and soft-
    attach the report. Set *require_patch_diff_ok* to refuse when a present
    report has ``ok=False`` (empty / test-only / unparseable gold /
    min_overlap breach). Optionally list *patch_diff_fail_verdicts* (e.g.
    ``("divergent",)``) to also refuse on those verdicts even when nested
    ``ok`` is still True (warn-level content divergence).

    Note: *require_patch_diff_ok* only gates *present* patch reports; patchless
    grades still pass (use a separate presence check if you need a patch).

    Returns normalized claim dict on success; raises ClaimVerifyError otherwise.
    """
    if not isinstance(grade, dict):
        raise ClaimVerifyError("claim must be a dict")

    miss = missing_fields(grade)
    if miss:
        raise ClaimVerifyError(
            f"claim missing required fields: {miss} "
            f"(need {list(REQUIRED_CLAIM_FIELDS)})"
        )

    score = _as_float(grade["score"], "score")
    idea = _as_float(grade["idea"], "idea")
    skill = _as_float(grade["skill"], "skill")
    path = str(grade.get("path") or "").strip()
    if not path:
        raise ClaimVerifyError("claim.path must be non-empty")

    if min_score is not None and score < float(min_score):
        raise ClaimVerifyError(
            f"claim.score {score} below min_score {min_score}"
        )

    resolved: Optional[str] = None
    if require_path_exists:
        root = Path(workdir).resolve() if workdir is not None else None
        p = Path(path)
        if not p.is_absolute() and root is not None:
            p = (root / path).resolve()
        else:
            p = p.resolve()
        if not p.exists():
            raise ClaimVerifyError(f"claim.path does not exist: {path}")
        resolved = str(p)

    out: dict[str, Any] = {
        "schema": "nexus.claim_verify/v1",
        "ok": True,
        "score": score,
        "idea": idea,
        "skill": skill,
        "path": path,
    }
    if resolved:
        out["resolved_path"] = resolved
    for key in OPTIONAL_IDENTITY:
        if key in grade and grade[key] is not None:
            out[key] = grade[key]
    # passthrough useful extras
    for opt in ("summary", "source", "local_path", "notes", "method"):
        if opt in grade and grade[opt] is not None and opt not in out:
            out[opt] = grade[opt]

    _attach_patch_diff(
        grade,
        out,
        run_patch_diff=run_patch_diff,
        require_patch_diff_ok=require_patch_diff_ok,
        patch_diff_checks=patch_diff_checks,
        patch_diff_min_overlap=float(patch_diff_min_overlap or 0.0),
        patch_diff_fail_verdicts=patch_diff_fail_verdicts,
    )
    return out


def verify_or_report(
    grade: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Like verify_claim but returns {ok: False, reasons} instead of raising."""
    try:
        result = verify_claim(grade, **kwargs)
        return result
    except ClaimVerifyError as e:
        return {
            "schema": "nexus.claim_verify/v1",
            "ok": False,
            "reasons": [str(e)],
            "missing": missing_fields(grade) if isinstance(grade, dict) else list(
                REQUIRED_CLAIM_FIELDS
            ),
        }
