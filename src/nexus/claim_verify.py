"""Claim verification against grade evidence (Thucy-style, arXiv 2512.03278).

P0.4 from docs/LATEST_IMPROVE_PLAN.md — refuse apply suggestions that lack
grounding fields (score, idea, skill, path) or cannot be linked to a mine
evidence location.

Does not call the network; offline validation only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

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


def verify_claim(
    grade: Any,
    *,
    workdir: Optional[Path | str] = None,
    require_path_exists: bool = False,
    min_score: Optional[float] = None,
) -> dict[str, Any]:
    """Validate a grade claim for apply eligibility.

    Required: score, idea, skill, path (non-empty strings / numerics).
    Optional: if *require_path_exists*, path must resolve under *workdir*
    (or absolute) and exist on disk.

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
