"""Plan-reuse cache for dry-run / apply plans (multi-stage workflow shape).

Inspired by multi-stage agent workflows (arXiv 2604.03350) and context
engineering reuse (2508.08322): identical (repo, pattern, score band, method)
fingerprints return a prior plan summary without re-materialising a worktree.

Storage (atomic JSON)::

  ``.nexus_workspaces/plan_reuse/cache.json``

No network; no secrets. Pattern only — not a vendored upstream tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from .persist import atomic_write_json

SCHEMA = "nexus.plan_reuse/v1"
CACHE_REL = Path(".nexus_workspaces") / "plan_reuse" / "cache.json"
DEFAULT_MAX_ENTRIES = 200


class PlanReuseError(RuntimeError):
    """Plan-reuse cache failure."""


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def cache_path(workdir: Optional[Path | str] = None) -> Path:
    return _root(workdir) / CACHE_REL


def score_band(score: Any, *, width: float = 1.0) -> str:
    """Bucket scores so near-identical grades share a plan key."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "na"
    w = float(width) if width > 0 else 1.0
    bucket = int(s // w) * w
    return f"{bucket:.1f}"


def plan_key(
    *,
    repo: str,
    pattern: str,
    score: Any = None,
    method: str = "",
    extra: str = "",
) -> str:
    """Stable fingerprint for plan reuse (sha256 hex, 32 chars)."""
    payload = "|".join(
        [
            str(repo or "").strip().lower(),
            str(pattern or "").strip(),
            score_band(score),
            str(method or "").strip().lower(),
            str(extra or "").strip(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _empty_store() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "updated_at": time.time(),
        "entries": {},
    }


def load_cache(workdir: Optional[Path | str] = None) -> dict[str, Any]:
    path = cache_path(workdir)
    if not path.is_file():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    entries = data.get("entries")
    if not isinstance(entries, dict):
        data = _empty_store()
    data.setdefault("schema", SCHEMA)
    data.setdefault("entries", {})
    return data


def save_cache(
    store: dict[str, Any],
    workdir: Optional[Path | str] = None,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> Path:
    path = cache_path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = store.get("entries") if isinstance(store.get("entries"), dict) else {}
    if len(entries) > int(max_entries):
        # Drop oldest by ts
        ranked = sorted(
            entries.items(),
            key=lambda kv: float((kv[1] or {}).get("ts") or 0),
        )
        drop = len(entries) - int(max_entries)
        for k, _ in ranked[:drop]:
            entries.pop(k, None)
    out = {
        "schema": SCHEMA,
        "updated_at": time.time(),
        "entries": entries,
    }
    atomic_write_json(path, out)
    return path


def lookup(
    workdir: Optional[Path | str] = None,
    *,
    key: Optional[str] = None,
    repo: str = "",
    pattern: str = "",
    score: Any = None,
    method: str = "",
) -> Optional[dict[str, Any]]:
    """Return cached plan summary or None."""
    k = key or plan_key(repo=repo, pattern=pattern, score=score, method=method)
    store = load_cache(workdir)
    ent = (store.get("entries") or {}).get(k)
    if not isinstance(ent, dict):
        return None
    out = dict(ent)
    out["cache_hit"] = True
    out["key"] = k
    return out


def store_plan(
    workdir: Optional[Path | str] = None,
    *,
    key: Optional[str] = None,
    repo: str = "",
    pattern: str = "",
    score: Any = None,
    method: str = "",
    summary: Optional[dict[str, Any]] = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict[str, Any]:
    """Persist a plan summary; returns the stored entry."""
    k = key or plan_key(repo=repo, pattern=pattern, score=score, method=method)
    store = load_cache(workdir)
    entry = {
        "key": k,
        "ts": time.time(),
        "repo": str(repo or ""),
        "pattern": str(pattern or ""),
        "score": score,
        "score_band": score_band(score),
        "method": str(method or ""),
        "summary": dict(summary or {}),
        "schema": SCHEMA,
    }
    store.setdefault("entries", {})[k] = entry
    save_cache(store, workdir, max_entries=max_entries)
    return {**entry, "cache_hit": False, "stored": True}


def get_or_compute(
    workdir: Optional[Path | str],
    *,
    repo: str,
    pattern: str,
    score: Any = None,
    method: str = "",
    compute: Optional[Any] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Lookup cache; on miss call *compute()* (no-arg callable) and store.

    Returns ``{ok, cache_hit, key, entry, result?}``.
    """
    k = plan_key(repo=repo, pattern=pattern, score=score, method=method)
    if not force:
        hit = lookup(workdir, key=k)
        if hit is not None:
            return {
                "ok": True,
                "cache_hit": True,
                "key": k,
                "entry": hit,
                "result": hit.get("summary"),
            }
    if compute is None:
        return {
            "ok": False,
            "cache_hit": False,
            "key": k,
            "entry": None,
            "result": None,
            "error": "cache_miss_no_compute",
        }
    result = compute()
    summary: dict[str, Any]
    if isinstance(result, dict):
        summary = {
            "ok": result.get("ok"),
            "pattern": result.get("pattern") or pattern,
            "run_id": result.get("run_id"),
            "files": (result.get("apply") or {}).get("files_written")
            or result.get("files")
            or [],
            "verify_ok": (result.get("verify") or {}).get("ok"),
            "error": result.get("error"),
            "dry_run": result.get("dry_run", True),
        }
    else:
        summary = {"ok": bool(result), "raw_type": type(result).__name__}
    # Only cache successful plans so failures are not sticky.
    entry: Optional[dict[str, Any]] = None
    if summary.get("ok") or summary.get("verify_ok"):
        entry = store_plan(
            workdir,
            key=k,
            repo=repo,
            pattern=pattern,
            score=score,
            method=method,
            summary=summary,
        )
    return {
        "ok": True,
        "cache_hit": False,
        "key": k,
        "entry": entry,
        "result": result if isinstance(result, dict) else summary,
        "stored": entry is not None,
    }


def clear_cache(workdir: Optional[Path | str] = None) -> dict[str, Any]:
    """Wipe plan-reuse cache file."""
    path = cache_path(workdir)
    existed = path.is_file()
    if existed:
        path.unlink()
    return {"ok": True, "cleared": existed, "path": str(path)}


def stats(workdir: Optional[Path | str] = None) -> dict[str, Any]:
    store = load_cache(workdir)
    entries = store.get("entries") or {}
    return {
        "schema": SCHEMA,
        "path": str(cache_path(workdir)),
        "count": len(entries),
        "updated_at": store.get("updated_at"),
        "repos": sorted(
            {
                str(e.get("repo") or "")
                for e in entries.values()
                if isinstance(e, dict) and e.get("repo")
            }
        ),
    }


__all__ = [
    "SCHEMA",
    "PlanReuseError",
    "cache_path",
    "score_band",
    "plan_key",
    "load_cache",
    "save_cache",
    "lookup",
    "store_plan",
    "get_or_compute",
    "clear_cache",
    "stats",
]
