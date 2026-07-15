"""Offline preference-pair store for apply rubric learning (arXiv 2602.04518).

Stores better/worse candidate pairs from mine→grade rankings so later cycles
can bias selection without a live IRL trainer. Append-only JSONL under
``.nexus_state/preference_pairs.jsonl``.

Patterns (shape only, not vendored):
- arXiv 2602.04518 — preference-based / inverse RL value systems
- ahmedEid1/lumen — decision audit trail
- builderz-labs/mission-control — operator-visible spend/quality history

Does not call the network; no model training loop here — just durable pairs
+ a tiny ranking brief for context packs / board hints.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence

SCHEMA = "nexus.preference_pairs/v1"
DEFAULT_REL = Path(".nexus_state") / "preference_pairs.jsonl"


class PreferenceError(ValueError):
    """Invalid preference pair payload."""


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def pairs_path(workdir: Optional[Path | str] = None) -> Path:
    return _root(workdir) / DEFAULT_REL


def record_pair(
    workdir: Optional[Path | str] = None,
    *,
    better: str,
    worse: str,
    criterion: str = "score",
    better_score: Optional[float] = None,
    worse_score: Optional[float] = None,
    source: str = "manual",
    note: str = "",
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append one better>worse preference pair. Fail-closed on empty/same ids."""
    b = str(better or "").strip()
    w = str(worse or "").strip()
    if not b or not w:
        raise PreferenceError("better and worse repo ids required")
    if b == w:
        raise PreferenceError("better and worse must differ")

    row: dict[str, Any] = {
        "schema": SCHEMA,
        "id": f"pref-{uuid.uuid4().hex[:12]}",
        "ts": time.time(),
        "better": b,
        "worse": w,
        "criterion": str(criterion or "score"),
        "source": str(source or "manual"),
        "note": str(note or "")[:500],
    }
    if better_score is not None:
        try:
            row["better_score"] = float(better_score)
        except (TypeError, ValueError):
            pass
    if worse_score is not None:
        try:
            row["worse_score"] = float(worse_score)
        except (TypeError, ValueError):
            pass
    if meta:
        row["meta"] = dict(meta)

    path = pairs_path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return row


def list_pairs(
    workdir: Optional[Path | str] = None,
    *,
    limit: int = 50,
    better: Optional[str] = None,
    worse: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return recent pairs (newest last in file → return newest-first)."""
    path = pairs_path(workdir)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        if better and str(d.get("better") or "") != better:
            continue
        if worse and str(d.get("worse") or "") != worse:
            continue
        rows.append(d)
    rows = rows[-max(1, int(limit)) :]
    rows.reverse()
    return rows


def win_counts(workdir: Optional[Path | str] = None) -> dict[str, dict[str, int]]:
    """Aggregate better/worse counts per repo id."""
    tallies: dict[str, dict[str, int]] = {}
    for row in list_pairs(workdir, limit=10_000):
        b = str(row.get("better") or "")
        w = str(row.get("worse") or "")
        if b:
            tallies.setdefault(b, {"wins": 0, "losses": 0})
            tallies[b]["wins"] += 1
        if w:
            tallies.setdefault(w, {"wins": 0, "losses": 0})
            tallies[w]["losses"] += 1
    return tallies


def preference_boost(repo: str, workdir: Optional[Path | str] = None) -> float:
    """Small numeric bias from historical wins-losses (capped).

    boost = 0.25 * (wins - losses), clamped to [-1.5, +1.5].
    """
    t = win_counts(workdir).get(str(repo or "").strip()) or {}
    wins = int(t.get("wins") or 0)
    losses = int(t.get("losses") or 0)
    raw = 0.25 * (wins - losses)
    return max(-1.5, min(1.5, raw))


def record_from_ranked(
    candidates: Sequence[dict[str, Any]],
    workdir: Optional[Path | str] = None,
    *,
    source: str = "select_rank",
    min_margin: float = 0.5,
) -> Optional[dict[str, Any]]:
    """If ≥2 ranked candidates, record top>second when score margin ≥ min_margin."""
    cands = [c for c in candidates if isinstance(c, dict) and c.get("repo")]
    if len(cands) < 2:
        return None
    a, b = cands[0], cands[1]
    try:
        sa = float(a.get("score") if a.get("score") is not None else a.get("rank") or 0)
    except (TypeError, ValueError):
        sa = 0.0
    try:
        sb = float(b.get("score") if b.get("score") is not None else b.get("rank") or 0)
    except (TypeError, ValueError):
        sb = 0.0
    if sa - sb < float(min_margin):
        return None
    return record_pair(
        workdir,
        better=str(a["repo"]),
        worse=str(b["repo"]),
        criterion="score",
        better_score=sa,
        worse_score=sb,
        source=source,
        note=f"auto from ranked margin {sa - sb:.2f}",
        meta={
            "a_rank": a.get("rank"),
            "b_rank": b.get("rank"),
            "a_evidence": a.get("evidence_hits"),
            "b_evidence": b.get("evidence_hits"),
        },
    )


def preference_brief(
    workdir: Optional[Path | str] = None,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    """Compact brief for context packs / improve board hints."""
    pairs = list_pairs(workdir, limit=limit)
    tallies = win_counts(workdir)
    top = sorted(
        tallies.items(),
        key=lambda kv: (kv[1]["wins"] - kv[1]["losses"], kv[1]["wins"]),
        reverse=True,
    )[:5]
    return {
        "schema": SCHEMA,
        "n_pairs": len(list_pairs(workdir, limit=10_000)),
        "recent": [
            {
                "better": p.get("better"),
                "worse": p.get("worse"),
                "criterion": p.get("criterion"),
                "source": p.get("source"),
            }
            for p in pairs[:limit]
        ],
        "leaderboard": [
            {"repo": repo, "wins": t["wins"], "losses": t["losses"]}
            for repo, t in top
        ],
        "path": str(pairs_path(workdir)),
    }


def format_brief(brief: dict[str, Any]) -> str:
    lines = [
        "=== NEXUS preference pairs (2602.04518 offline) ===",
        f"pairs: {brief.get('n_pairs')}  path: {brief.get('path')}",
    ]
    lb = brief.get("leaderboard") or []
    if lb:
        lines.append("leaderboard:")
        for row in lb:
            lines.append(
                f"  {row.get('repo')}: +{row.get('wins')} / -{row.get('losses')}"
            )
    recent = brief.get("recent") or []
    if recent:
        lines.append("recent:")
        for p in recent[:5]:
            lines.append(f"  {p.get('better')} > {p.get('worse')} ({p.get('source')})")
    if not lb and not recent:
        lines.append("(empty — record with: nexus improve prefer record …)")
    return "\n".join(lines)


__all__ = [
    "SCHEMA",
    "PreferenceError",
    "pairs_path",
    "record_pair",
    "list_pairs",
    "win_counts",
    "preference_boost",
    "record_from_ranked",
    "preference_brief",
    "format_brief",
]
