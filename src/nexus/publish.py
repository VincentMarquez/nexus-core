"""Publish local self-improve results to GitHub (commit + optional push).

Safe defaults:
  - never force-push
  - never add .nexus_state / .nexus_workspaces / .venv secrets
  - only allowlisted paths
  - push only when explicitly enabled
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from .path_privacy import public_path, scrub_obj

# Paths we are willing to auto-commit from an alive cycle
DEFAULT_ALLOW = (
    "src/",
    "docs/",
    "scripts/",
    "cookbook/",
    "skillpacks/",
    "connectors/",
    "bridge/",
    "tests/",
    "evals/",
    "examples/",
    "README.md",
    "CHANGELOG.md",
    "Makefile",
    "mkdocs.yml",
    "pyproject.toml",
    ".github/",
    ".grok/config.example.toml",
)


def _run(cmd: list[str], *, cwd: Path) -> dict[str, Any]:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=120)
    return {
        "cmd": cmd,
        "ok": p.returncode == 0,
        "returncode": p.returncode,
        "stdout": (p.stdout or "").strip(),
        "stderr": (p.stderr or "").strip()[-800:],
    }


def is_git_repo(root: Path) -> bool:
    return (root / ".git").is_dir() or _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root).get("stdout") == "true"


def status_porcelain(root: Path) -> list[str]:
    """Porcelain lines; empty list on failure (legacy). Prefer ``status_porcelain_checked``."""
    lines, ok = status_porcelain_checked(root)
    if not ok:
        return []
    return lines


def status_porcelain_checked(root: Path) -> tuple[list[str], bool]:
    """Return (lines, ok). *ok* False when git status failed (S11 fail-closed)."""
    r = _run(["git", "status", "--porcelain"], cwd=root)
    if not r["ok"]:
        return [], False
    return [ln for ln in (r["stdout"] or "").splitlines() if ln.strip()], True


def parse_porcelain_paths(lines: list[str] | str) -> set[str]:
    """Extract paths from porcelain lines (handles renames / quoted paths)."""
    if isinstance(lines, str):
        seq = [ln for ln in lines.splitlines() if ln.strip()]
    else:
        seq = list(lines)
    out: set[str] = set()
    for ln in seq:
        if len(ln) < 4:
            continue
        path = ln[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if path:
            out.add(path)
    return out


def _allowed(path: str, allow: tuple[str, ...]) -> bool:
    path = path.lstrip("./")
    # reject junk
    deny_prefix = (
        ".nexus_state/",
        ".nexus_workspaces/",
        ".venv/",
        ".nexus/",
        "site/",
        "dist/",
        "results/",
        "__pycache__/",
        ".env",
    )
    for d in deny_prefix:
        if path.startswith(d) or f"/{d}" in path:
            return False
    if path.endswith(".sqlite") or path.endswith(".db"):
        return False
    for a in allow:
        if a.endswith("/"):
            if path.startswith(a) or path == a.rstrip("/"):
                return True
        elif path == a or path.startswith(a + "/"):
            return True
    return False


def unstage_all(root: Path) -> dict[str, Any]:
    """Clear the index (unstage) without touching the working tree (S11)."""
    # ``git reset`` (mixed) unstages; keep worktree
    return _run(["git", "reset", "HEAD", "--"], cwd=root)


def stage_allowed(
    root: Path,
    allow: tuple[str, ...] = DEFAULT_ALLOW,
    *,
    baseline_status: Optional[str | list[str]] = None,
) -> list[str]:
    """git add allowlisted changed files; return list of staged paths.

    When *baseline_status* is provided (porcelain text or lines captured at
    cycle start), only paths that became dirty **after** that baseline are
    staged. Pre-existing dirty WIP is left unstaged so a cycle cannot ship
    unrelated prior edits.
    """
    lines, st_ok = status_porcelain_checked(root)
    if not st_ok:
        return []  # caller should refuse cycle-scoped commit separately
    baseline_paths: Optional[set[str]] = None
    if baseline_status is not None:
        baseline_paths = parse_porcelain_paths(baseline_status)

    staged: list[str] = []
    for ln in lines:
        # XY PATH or XY ORIG -> PATH
        path = ln[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if baseline_paths is not None and path in baseline_paths:
            # Already dirty at cycle start — not this cycle's unit of work
            continue
        if _allowed(path, allow):
            r = _run(["git", "add", "--", path], cwd=root)
            if r["ok"]:
                staged.append(path)
    return staged


def commit_and_maybe_push(
    root: Path,
    message: str,
    *,
    push: bool = False,
    remote: str = "origin",
    branch: Optional[str] = None,
    allow: tuple[str, ...] = DEFAULT_ALLOW,
    baseline_status: Optional[str | list[str]] = None,
    require_cycle_scope: bool = False,
) -> dict[str, Any]:
    """Stage allowlisted changes, commit, optionally push (no force).

    Pass *baseline_status* (porcelain at cycle start) to scope the commit to
    paths introduced during this cycle only.

    *require_cycle_scope* (S11): when True, refuse if baseline is missing or
    ``git status`` fails — never silently widen to all dirty files.
    When cycle-scoped, the index is reset first so pre-staged unrelated files
    cannot ride into the commit.
    """
    root = Path(root).resolve()
    out: dict[str, Any] = {
        "root": str(root),
        "push": push,
        "cycle_scoped": baseline_status is not None,
        "require_cycle_scope": bool(require_cycle_scope),
    }
    if not is_git_repo(root):
        out["ok"] = False
        out["error"] = "not a git repository"
        return out

    # S11: fail-closed when cycle scope was required but baseline unavailable
    if require_cycle_scope and baseline_status is None:
        out["ok"] = False
        out["error"] = "cycle scope required but baseline missing (git status failed?)"
        out["skipped"] = "publish fail-closed: no reliable baseline"
        return out

    # S11: when cycle-scoped, clear index so only our stage_allowed paths commit
    if baseline_status is not None:
        ur = unstage_all(root)
        out["unstage_all"] = {"ok": ur.get("ok"), "returncode": ur.get("returncode")}

    # Verify status works before staging
    _lines, st_ok = status_porcelain_checked(root)
    if not st_ok and (require_cycle_scope or baseline_status is not None):
        out["ok"] = False
        out["error"] = "git status failed — refusing cycle-scoped publish"
        out["skipped"] = "publish fail-closed: git status failed"
        return out

    staged = stage_allowed(root, allow, baseline_status=baseline_status)
    out["staged"] = staged
    if not staged:
        # When cycle-scoped, do not fall through to pre-staged unrelated files.
        if baseline_status is not None or require_cycle_scope:
            out["ok"] = True
            out["skipped"] = "nothing to commit (no cycle-scoped allowlisted changes)"
            return out
        # Legacy: still try commit if something already staged
        r = _run(["git", "diff", "--cached", "--name-only"], cwd=root)
        staged = [x for x in (r.get("stdout") or "").splitlines() if x.strip()]
        out["staged"] = staged
    if not staged:
        out["ok"] = True
        out["skipped"] = "nothing to commit (no allowlisted changes)"
        return out

    # S11: drop any cached path we did not intentionally stage
    if baseline_status is not None:
        r = _run(["git", "diff", "--cached", "--name-only"], cwd=root)
        cached = [x for x in (r.get("stdout") or "").splitlines() if x.strip()]
        staged_set = set(staged)
        extra = [p for p in cached if p not in staged_set]
        for p in extra:
            _run(["git", "restore", "--staged", "--", p], cwd=root)
        if extra:
            out["unstaged_extra"] = extra
            # re-read staged
            r2 = _run(["git", "diff", "--cached", "--name-only"], cwd=root)
            staged = [x for x in (r2.get("stdout") or "").splitlines() if x.strip()]
            out["staged"] = staged
            if not staged:
                out["ok"] = True
                out["skipped"] = "nothing to commit after dropping pre-staged extras"
                return out

    msg = (message or "chore(alive): self-improve cycle").strip()
    r = _run(["git", "commit", "-m", msg], cwd=root)
    out["commit"] = r
    if not r["ok"]:
        # maybe empty commit
        if "nothing to commit" in (r.get("stdout") or "") + (r.get("stderr") or ""):
            out["ok"] = True
            out["skipped"] = "nothing to commit"
            return out
        out["ok"] = False
        out["error"] = r.get("stderr") or r.get("stdout")
        return out

    sha = _run(["git", "rev-parse", "HEAD"], cwd=root)
    out["sha"] = (sha.get("stdout") or "")[:12]
    out["ok"] = True

    if push:
        br = branch
        if not br:
            b = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
            br = (b.get("stdout") or "main").strip()
        # never force
        pr = _run(["git", "push", remote, br], cwd=root)
        out["push_result"] = pr
        out["branch"] = br
        out["pushed"] = bool(pr.get("ok"))
        if not pr.get("ok"):
            out["ok"] = False
            out["error"] = pr.get("stderr") or "push failed"
    return out


def write_evidence_snapshot(root: Path, *, limit: int = 5) -> list[Path]:
    """Export evidence packs for recent tasks into docs/evidence/ (allowlisted)."""
    root = Path(root)
    out_dir = root / "docs" / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        from .config import Settings
        from .engine import DurableEngine

        settings = Settings(state_dir=root / ".nexus_state")
        eng = DurableEngine(settings=settings, auto_approve=True, journal=True)
        rows = eng.list_tasks()[: max(1, limit)]
        for r in rows:
            tid = r.get("task_id")
            if not tid:
                continue
            try:
                pack = eng.evidence(str(tid))
            except Exception:
                continue
            path = out_dir / f"{tid}.json"
            import json

            safe_pack = scrub_obj(pack, root)
            path.write_text(json.dumps(safe_pack, indent=2, default=str) + "\n", encoding="utf-8")
            written.append(path)
        # index
        idx = out_dir / "README.md"
        lines = [
            "# Task evidence snapshots\n\n",
            "Written by alive/publish when self-improve runs. Safe to commit.\n\n",
        ]
        for p in written:
            lines.append(f"- [`{p.name}`]({p.name})\n")
        idx.write_text("".join(lines), encoding="utf-8")
        written.append(idx)
    except Exception:
        pass
    return written


def write_improvements_log(root: Path, cycle: dict[str, Any]) -> Path:
    """Append a durable markdown log under docs/ (safe to commit)."""
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    log = docs / "ALIVE_IMPROVEMENTS.md"
    import time

    ts = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    lines = [
        f"\n## Cycle {ts}\n",
        f"- goal: `{cycle.get('goal', '')}`\n",
    ]
    for s in cycle.get("steps") or []:
        step = s.get("step")
        if step == "mine":
            plan = public_path(s.get("improve_plan") or "", root)
            lines.append(
                f"- mine: fetch={s.get('fetch')} eval={s.get('evaluated')} "
                f"used={s.get('used')} plan=`{plan}`\n"
            )
        elif step == "arxiv":
            notes = public_path(s.get("notes") or "", root)
            lines.append(f"- arxiv: papers={s.get('papers')} notes=`{notes}`\n")
        elif step == "self_check":
            lines.append(f"- self_check: ok={s.get('ok')}\n")
        elif step == "self_approve_apply":
            lines.append(f"- apply: {s.get('apply') or s.get('skipped') or s.get('error')}\n")
        elif step == "publish_github":
            lines.append(
                f"- publish: pushed={s.get('pushed')} sha={s.get('sha')} "
                f"staged={s.get('staged')}\n"
            )
        elif step == "grok_hard_improve":
            lines.append(
                f"- hard_improve: ok={s.get('ok')} rc={s.get('returncode')}\n"
            )
    # always try evidence export (routa / mission-control board shape)
    try:
        ev_paths = write_evidence_snapshot(root, limit=5)
        if ev_paths:
            lines.append(
                f"- evidence: {len(ev_paths)} file(s) under `docs/evidence/`\n"
            )
    except Exception as e:
        lines.append(f"- evidence: error `{e}`\n")
    if not log.exists():
        header = (
            "# Alive improvement log\n\n"
            "Auto-appended by `nexus alive` when self-improve runs. "
            "Safe to commit; no secrets.\n"
        )
        log.write_text(header, encoding="utf-8")
    with open(log, "a", encoding="utf-8") as f:
        f.writelines(lines)
    return log
