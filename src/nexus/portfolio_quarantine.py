"""S06 — Opt-in quarantine apply for portfolio ideas.

When enabled, Grok hard-improve runs in a **git worktree** under
``.nexus_workspaces/apply_worktrees/<job_id>/``. After the worker finishes,
allowlisted changed files are promoted onto main (copy), then the worktree is
cleaned up.

Default off. Falls back to main-tree apply if worktree creation fails.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Optional

from .improve_apply import PathSafetyError, safe_path
from .publish import DEFAULT_ALLOW, _allowed
from .worktree_apply import (
    WorktreeApplyError,
    cleanup_worktree,
    create_worktree,
    worktrees_dir,
)


def _git_status_paths(cwd: Path) -> list[str]:
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    out: list[str] = []
    for ln in (r.stdout or "").splitlines():
        if len(ln) < 4:
            continue
        path = ln[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if path:
            out.append(path)
    return out


def promote_paths_to_main(
    main: Path,
    worktree: Path,
    paths: list[str],
    *,
    allow: tuple[str, ...] = DEFAULT_ALLOW,
) -> dict[str, Any]:
    """Copy allowlisted *paths* from worktree onto main (atomic-ish replace)."""
    main = Path(main).resolve()
    worktree = Path(worktree).resolve()
    # jail: worktree under apply_worktrees
    try:
        worktree.relative_to(worktrees_dir(main))
    except ValueError:
        return {
            "ok": False,
            "error": f"worktree not under apply_worktrees: {worktree}",
            "copied": [],
        }

    copied: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    for rel in paths:
        rel_n = str(rel).replace("\\", "/").lstrip("./")
        if not _allowed(rel_n, allow):
            skipped.append(rel_n)
            continue
        try:
            src = safe_path(worktree, rel_n)
            dest = safe_path(main, rel_n)
        except PathSafetyError as e:
            errors.append(f"{rel_n}:{e}")
            continue
        if not src.exists():
            # deleted in worktree — delete on main if was a file
            if dest.is_file():
                try:
                    dest.unlink()
                    copied.append(rel_n + " (deleted)")
                except OSError as e:
                    errors.append(f"{rel_n}:unlink:{e}")
            continue
        if src.is_dir():
            skipped.append(rel_n + " (dir)")
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + f".qtmp-{uuid.uuid4().hex[:8]}")
            shutil.copy2(src, tmp)
            tmp.replace(dest)
            copied.append(rel_n)
        except OSError as e:
            errors.append(f"{rel_n}:{e}")
            try:
                if "tmp" in locals() and tmp.exists():  # type: ignore[name-defined]
                    tmp.unlink(missing_ok=True)  # type: ignore[arg-type]
            except OSError:
                pass
    return {
        "ok": not errors,
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
    }


def quarantine_apply(
    main: Path,
    goal: str,
    *,
    job_id: Optional[str] = None,
    cleanup: bool = True,
    allow: tuple[str, ...] = DEFAULT_ALLOW,
    grok_fn: Any = None,
) -> dict[str, Any]:
    """Run hard-improve inside a git worktree; promote allowlisted deltas to main.

    Returns worker-like dict with extra quarantine metadata. On worktree failure,
    falls back to in-main apply (``fallback_main=True``).
    """
    from . import grok_worker as gw

    main = Path(main).resolve()
    jid = job_id or f"pf-{uuid.uuid4().hex[:10]}"
    out: dict[str, Any] = {
        "schema": "nexus.portfolio_quarantine/v1",
        "job_id": jid,
        "fallback_main": False,
        "promoted": [],
    }

    meta: dict[str, Any] | None = None
    wt_path: Path | None = None
    try:
        meta = create_worktree(main, job_id=jid, mode="git")
        wt_path = Path(meta["path"])
        if meta.get("mode") != "git":
            raise WorktreeApplyError(
                f"expected git worktree, got mode={meta.get('mode')}"
            )
    except Exception as e:
        # Fall back to main-tree apply
        out["fallback_main"] = True
        out["worktree_error"] = str(e)[:400]
        fn = grok_fn or gw.grok_hard_improve
        res = fn(main, goal)
        out["ok"] = bool(res.get("ok", True)) if isinstance(res, dict) else bool(res)
        out["result"] = res if isinstance(res, dict) else {"raw": res}
        out["worker"] = "grok_main_fallback"
        return out

    try:
        fn = grok_fn or gw.grok_hard_improve
        res = fn(wt_path, goal)
        out["result"] = res if isinstance(res, dict) else {"raw": res}
        out["ok"] = bool(res.get("ok", True)) if isinstance(res, dict) else bool(res)
        out["worker"] = "grok_quarantine"
        changed = _git_status_paths(wt_path)
        out["changed_in_worktree"] = changed
        prom = promote_paths_to_main(main, wt_path, changed, allow=allow)
        out["promote"] = prom
        out["promoted"] = prom.get("copied") or []
        if prom.get("errors"):
            out["promote_errors"] = prom["errors"]
            # still ok if worker ok and some files promoted
        return out
    finally:
        if cleanup and meta is not None:
            try:
                cleanup_worktree(main, jid, meta=meta)
                out["cleaned"] = True
            except Exception as e:
                out["cleanup_error"] = str(e)[:200]
