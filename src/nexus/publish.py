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

# Paths we are willing to auto-commit from an alive cycle
DEFAULT_ALLOW = (
    "src/",
    "docs/",
    "scripts/",
    "cookbook/",
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
    ".grok/",
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
    r = _run(["git", "status", "--porcelain"], cwd=root)
    if not r["ok"]:
        return []
    return [ln for ln in (r["stdout"] or "").splitlines() if ln.strip()]


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


def stage_allowed(root: Path, allow: tuple[str, ...] = DEFAULT_ALLOW) -> list[str]:
    """git add allowlisted changed files; return list of staged paths."""
    lines = status_porcelain(root)
    staged: list[str] = []
    for ln in lines:
        # XY PATH or XY ORIG -> PATH
        path = ln[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
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
) -> dict[str, Any]:
    """Stage allowlisted changes, commit, optionally push (no force)."""
    root = Path(root).resolve()
    out: dict[str, Any] = {"root": str(root), "push": push}
    if not is_git_repo(root):
        out["ok"] = False
        out["error"] = "not a git repository"
        return out

    staged = stage_allowed(root, allow)
    out["staged"] = staged
    if not staged:
        # still try commit if something already staged
        r = _run(["git", "diff", "--cached", "--name-only"], cwd=root)
        staged = [x for x in (r.get("stdout") or "").splitlines() if x.strip()]
        out["staged"] = staged
    if not staged:
        out["ok"] = True
        out["skipped"] = "nothing to commit (no allowlisted changes)"
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
            lines.append(
                f"- mine: fetch={s.get('fetch')} eval={s.get('evaluated')} "
                f"used={s.get('used')} plan=`{s.get('improve_plan')}`\n"
            )
        elif step == "arxiv":
            lines.append(f"- arxiv: papers={s.get('papers')} notes=`{s.get('notes')}`\n")
        elif step == "self_check":
            lines.append(f"- self_check: ok={s.get('ok')}\n")
        elif step == "self_approve_apply":
            lines.append(f"- apply: {s.get('apply') or s.get('skipped') or s.get('error')}\n")
        elif step == "publish_github":
            lines.append(
                f"- publish: pushed={s.get('pushed')} sha={s.get('sha')} "
                f"staged={s.get('staged')}\n"
            )
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
