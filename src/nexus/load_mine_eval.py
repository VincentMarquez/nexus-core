"""Load Grok-shaped mine grades from fixtures / digests (offline).

P0.3 helper from docs/LATEST_IMPROVE_PLAN.md — turn existing mine digests
(``IMPROVE_OURS.md``, grade JSON fixtures, optional ``.nexus_workspaces/grades``)
into normalized grade records for claim_verify + ledger smoke.

No network I/O.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .grade_artifact import (
    DEFAULT_METHOD,
    GradeValidationError,
    build_grade,
    entry_to_grade,
    list_graded_candidates,
    load_grade,
    validate_grade,
)

DEFAULT_FIXTURE_REL = "tests/fixtures/mine_eval_sample.json"


def load_grade_dict(data: Any, *, source: str = "") -> dict[str, Any]:
    """Normalize a raw grade-like dict (fixture row or grade artifact)."""
    if not isinstance(data, dict):
        raise GradeValidationError("grade payload must be a dict")
    # Accept either full grade artifact or slim mine_eval row
    if all(k in data for k in ("repo", "score", "idea", "skill")):
        path = str(data.get("path") or data.get("local_path") or "").strip()
        if not path and data.get("repo"):
            repo = str(data["repo"])
            path = f".nexus_workspaces/mine_eval/{repo.replace('/', '__')}"
        g = build_grade(
            repo=str(data.get("repo") or ""),
            score=float(data["score"]),
            idea=float(data["idea"]),
            skill=float(data["skill"]),
            method=str(data.get("method") or DEFAULT_METHOD),
            path=path,
            pattern=data.get("pattern") or "",
            summary=data.get("summary") or data.get("excerpt") or "",
            source=source or data.get("source") or "",
            claims=data.get("claims"),
        )
        # optional extras
        for opt in ("arxiv_id", "notes", "local_path", "html_url"):
            if opt in data and data[opt] is not None:
                g[opt] = data[opt]
        # Prefer claims when present (First apply Thucy anchors)
        require_claims = bool(g.get("claims"))
        return validate_grade(g, require_path=True, require_claims=require_claims)
    return validate_grade(data, require_path=True)


def load_fixture_file(path: Path | str) -> list[dict[str, Any]]:
    """Load one or more grades from a JSON file.

    Accepts:
    - a single grade object
    - ``{"grades": [...]}`` or ``{"candidates": [...]}``
    - a bare list of grade objects
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"mine_eval fixture not found: {path}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    source = str(p)
    items: list[Any]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        if "grades" in raw and isinstance(raw["grades"], list):
            items = raw["grades"]
        elif "candidates" in raw and isinstance(raw["candidates"], list):
            items = raw["candidates"]
        else:
            items = [raw]
    else:
        raise GradeValidationError("fixture must be object or list")

    out: list[dict[str, Any]] = []
    for item in items:
        out.append(load_grade_dict(item, source=source))
    return out


def load_from_workdir(
    workdir: Path | str,
    *,
    min_score: float = 10.0,
    limit: int = 20,
    fixture: Optional[Path | str] = None,
) -> list[dict[str, Any]]:
    """Load grades preferring explicit fixture, then digests / grade cache."""
    workdir = Path(workdir).resolve()
    if fixture is not None:
        return load_fixture_file(fixture)[:limit]

    # Built-in sample under tests/ when present (offline CI)
    sample = workdir / DEFAULT_FIXTURE_REL
    if sample.is_file():
        try:
            return load_fixture_file(sample)[:limit]
        except (GradeValidationError, OSError, json.JSONDecodeError):
            pass

    return list_graded_candidates(workdir, min_score=min_score, limit=limit)


def load_one(
    workdir: Path | str,
    *,
    repo: Optional[str] = None,
    fixture: Optional[Path | str] = None,
    min_score: float = 0.0,
) -> dict[str, Any]:
    """Load a single grade: fixture first grade, named repo, or top candidate."""
    workdir = Path(workdir).resolve()
    if fixture is not None:
        grades = load_fixture_file(fixture)
        if repo:
            for g in grades:
                if g.get("repo") == repo:
                    return g
            raise FileNotFoundError(f"repo {repo!r} not in fixture {fixture}")
        if not grades:
            raise FileNotFoundError(f"empty fixture: {fixture}")
        return grades[0]

    if repo:
        from .grade_artifact import get_grade

        g = get_grade(workdir, repo, min_score=min_score)
        if g is not None:
            return g
        # Synthesize from IMPROVE_OURS entry shape via entry_to_grade fallback
        grades = list_graded_candidates(workdir, min_score=min_score, limit=100)
        for cand in grades:
            if cand.get("repo") == repo:
                return cand
        raise FileNotFoundError(f"no grade for repo={repo!r}")

    grades = load_from_workdir(workdir, min_score=max(min_score, 10.0), limit=1)
    if grades:
        return grades[0]
    # Last-resort: well-known high-score fixture shape (wshobson/agents)
    return entry_to_grade(
        {
            "repo": "wshobson/agents",
            "score": 16.0,
            "idea": 8.0,
            "skill": 8.0,
            "pattern": "Markdown SoT agents/skills/commands + generators",
        },
        workdir=workdir,
        source="builtin-fallback",
    )
