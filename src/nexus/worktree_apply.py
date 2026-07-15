"""Worktree-isolated apply worker (P0.5 — cas + forge + wshobson patterns).

First apply slice next PR after mine→grade→claim_verify smoke:

  claim-verified grade
    → create isolated worktree (never dirty main)
    → apply one Markdown skill SoT pattern (wshobson/agents shape)
    → validate skillpack structure
    → ledger plan_apply + apply decisions
    → cleanup optional

Isolation modes:
- ``sandbox`` (default, always available): directory under
  ``.nexus_workspaces/apply_worktrees/<job_id>/`` with path jail
- ``git``: ``git worktree add`` when *source* is a git repo (optional)

Patterns (shape only, not vendored trees):
- codingagentsystem/cas, automagik-dev/forge — one worktree per apply job
- wshobson/agents — Markdown skill source-of-truth + structural validate
- lumen — content-hash ledger / idempotent apply keys
- tiger_cowork / improve_apply — path safety jail

CLI::

  nexus improve apply [--fixture PATH] [--pattern markdown-skill-sot-validator]
  python -m nexus.worktree_apply --fixture tests/fixtures/mine_eval_sample.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .claim_verify import ClaimVerifyError, verify_claim
from .decision_ledger import DecisionLedger
from .improve_apply import PathSafetyError, safe_path
from .load_mine_eval import load_one
from .persist import atomic_write_json, atomic_write_text
from .stages import APPLY_STAGES, StageOrderError, StageRunner

SCHEMA = "nexus.worktree_apply/v1"
DEFAULT_PATTERN = "markdown-skill-sot-validator"
WORKTREE_ROOT = ".nexus_workspaces/apply_worktrees"

# ---------------------------------------------------------------------------
# Ported pattern catalog (content only — not whole upstream trees)
# ---------------------------------------------------------------------------

_SOT_MANIFEST = {
    "id": "markdown-sot-demo",
    "version": "0.1.0",
    "name": "Markdown skill SoT validator (demo)",
    "tags": ["self-improve", "sot", "wshobson-pattern", "read"],
    "privilege": "read",
    "harnesses": ["grok", "local", "claude"],
    "entrypoints": {"skill": "SKILL.md"},
    "source_pattern": "wshobson/agents:markdown-skill-sot",
}

_SOT_SKILL_MD = """# Skill: Markdown skill SoT validator

Ported *pattern* from wshobson/agents (single Markdown source of truth +
structural validate). This pack is materialised inside an isolated apply
worktree so main stays clean until review promotes the change.

## When to use

- Self-improve apply jobs that must prove skillpack structure offline
- Smoke tests for worktree isolation (cas / forge pattern)
- Least-privilege skill catalog demos

## Commands

```bash
nexus skillpacks validate --packs-dir skillpacks
nexus improve apply --pattern markdown-skill-sot-validator
```

## Rules

1. SKILL.md is the source of truth; generators are derived.
2. Never vendor whole upstream trees — port patterns only.
3. Apply only inside isolated worktrees; never dirty main mid-run.
4. Keep tests green; claim-verify before apply.

## Success

- `manifest.json` has id/version/name
- SKILL.md has When to use / Commands / Rules / Success
- `nexus skillpacks validate` reports ok
- Main worktree file set unchanged after apply job
"""


PATTERN_CATALOG: dict[str, dict[str, Any]] = {
    DEFAULT_PATTERN: {
        "id": DEFAULT_PATTERN,
        "repo": "wshobson/agents",
        "description": (
            "Markdown skill source-of-truth pack + structural validator "
            "(wshobson/agents shape; pattern only)"
        ),
        "files": {
            "skillpacks/markdown-sot-demo/manifest.json": json.dumps(
                _SOT_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/markdown-sot-demo/SKILL.md": _SOT_SKILL_MD,
            "skillpacks/markdown-sot-demo/APPLY_META.json": None,  # filled at apply
        },
        "verify": "skillpack_validate",
        "pack_id": "markdown-sot-demo",
    },
}


class WorktreeApplyError(RuntimeError):
    """Isolation or apply failed."""


def list_patterns() -> list[dict[str, Any]]:
    """Return catalog entries (id, repo, description)."""
    out: list[dict[str, Any]] = []
    for pid, meta in PATTERN_CATALOG.items():
        out.append(
            {
                "id": pid,
                "repo": meta.get("repo"),
                "description": meta.get("description"),
                "pack_id": meta.get("pack_id"),
                "verify": meta.get("verify"),
            }
        )
    return out


def get_pattern(pattern_id: str) -> dict[str, Any]:
    key = str(pattern_id or "").strip()
    if key not in PATTERN_CATALOG:
        known = sorted(PATTERN_CATALOG)
        raise WorktreeApplyError(
            f"unknown pattern {pattern_id!r}; known={known}"
        )
    return PATTERN_CATALOG[key]


def worktrees_dir(workdir: Path | str) -> Path:
    d = Path(workdir).resolve() / WORKTREE_ROOT
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_git_repo(path: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return r.returncode == 0 and "true" in (r.stdout or "").lower()
    except (OSError, subprocess.SubprocessError):
        return False


def _git_head(path: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def create_worktree(
    workdir: Path | str,
    *,
    job_id: Optional[str] = None,
    mode: str = "auto",
    branch: Optional[str] = None,
) -> dict[str, Any]:
    """Create an isolated apply worktree; never mutates tracked files on main.

    *mode*:
      - ``sandbox``: always use ``.nexus_workspaces/apply_worktrees/<id>``
      - ``git``: require ``git worktree add`` (fails if not a git repo)
      - ``auto``: try git worktree, fall back to sandbox
    """
    source = Path(workdir).resolve()
    jid = job_id or f"apply-{uuid.uuid4().hex[:10]}"
    mode_n = (mode or "auto").strip().lower()
    if mode_n not in ("auto", "sandbox", "git"):
        raise WorktreeApplyError(f"invalid mode {mode!r}")

    target = worktrees_dir(source) / jid
    if target.exists():
        raise WorktreeApplyError(f"worktree path already exists: {target}")

    used = "sandbox"
    git_sha = ""
    branch_name = branch or f"nexus/apply/{jid}"

    want_git = mode_n in ("auto", "git")
    if want_git and _is_git_repo(source):
        # Prefer detached worktree from HEAD so main stays clean.
        # Destination must be outside the main checkout's nested path issues;
        # we keep it under .nexus_workspaces which is typically gitignored.
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "worktree",
                    "add",
                    "--detach",
                    str(target),
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if r.returncode == 0 and target.is_dir():
                used = "git"
                git_sha = _git_head(target)
            elif mode_n == "git":
                err = (r.stderr or r.stdout or "").strip()
                raise WorktreeApplyError(f"git worktree add failed: {err}")
        except WorktreeApplyError:
            raise
        except (OSError, subprocess.SubprocessError) as e:
            if mode_n == "git":
                raise WorktreeApplyError(f"git worktree add failed: {e}") from e

    if used == "sandbox":
        target.mkdir(parents=True, exist_ok=False)
        # Seed a marker so operators can see isolation root; no main files copied
        # (avoids huge trees). Pattern files are written only under this root.
        marker = {
            "schema": SCHEMA,
            "mode": "sandbox",
            "job_id": jid,
            "source": str(source),
            "created_at": time.time(),
            "note": "sandbox isolation — pattern files only (no full tree clone)",
        }
        atomic_write_json(target / ".nexus_apply_worktree.json", marker)

    meta = {
        "schema": SCHEMA,
        "job_id": jid,
        "mode": used,
        "path": str(target),
        "source": str(source),
        "branch": branch_name if used == "git" else None,
        "git_sha": git_sha or None,
        "created_at": time.time(),
    }
    atomic_write_json(target / ".nexus_apply_meta.json", meta)
    return meta


def cleanup_worktree(
    workdir: Path | str,
    job_id: str,
    *,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Remove an apply worktree (git worktree remove or rmtree)."""
    source = Path(workdir).resolve()
    jid = str(job_id)
    target = worktrees_dir(source) / jid
    info = meta or {}
    mode = str(info.get("mode") or "")
    if not mode and target.is_dir():
        # Infer from marker
        mpath = target / ".nexus_apply_meta.json"
        if mpath.is_file():
            try:
                info = json.loads(mpath.read_text(encoding="utf-8"))
                mode = str(info.get("mode") or "")
            except (json.JSONDecodeError, OSError):
                pass

    removed = False
    method = "none"
    if mode == "git" and _is_git_repo(source):
        try:
            r = subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "worktree",
                    "remove",
                    "--force",
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if r.returncode == 0:
                removed = True
                method = "git_worktree_remove"
        except (OSError, subprocess.SubprocessError):
            pass

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        removed = not target.exists()
        method = method if method != "none" else "rmtree"

    return {
        "job_id": jid,
        "path": str(target),
        "removed": removed,
        "method": method,
    }


def snapshot_main_fingerprint(workdir: Path | str, rel_paths: list[str]) -> dict[str, str]:
    """Hash selected relative paths under main workdir (for dirty-main checks)."""
    root = Path(workdir).resolve()
    out: dict[str, str] = {}
    for rel in rel_paths:
        p = root / rel
        if not p.is_file():
            out[rel] = "missing"
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        out[rel] = h
    return out


def apply_pattern_files(
    worktree_path: Path | str,
    pattern_id: str = DEFAULT_PATTERN,
    *,
    grade: Optional[dict[str, Any]] = None,
    job_id: str = "",
) -> dict[str, Any]:
    """Write pattern files into *worktree_path* with path jail (never outside)."""
    wt = Path(worktree_path).resolve()
    if not wt.is_dir():
        raise WorktreeApplyError(f"worktree path missing: {wt}")
    pattern = get_pattern(pattern_id)
    written: list[str] = []
    files = dict(pattern.get("files") or {})

    # Fill APPLY_META dynamically
    apply_meta = {
        "schema": SCHEMA,
        "pattern": pattern_id,
        "repo": pattern.get("repo"),
        "job_id": job_id,
        "applied_at": time.time(),
        "grade": {
            "repo": (grade or {}).get("repo"),
            "score": (grade or {}).get("score"),
            "idea": (grade or {}).get("idea"),
            "skill": (grade or {}).get("skill"),
            "path": (grade or {}).get("path"),
            "method": (grade or {}).get("method"),
        },
    }
    files["skillpacks/markdown-sot-demo/APPLY_META.json"] = (
        json.dumps(apply_meta, indent=2, default=str) + "\n"
    )

    for rel, content in files.items():
        if content is None:
            continue
        try:
            dest = safe_path(wt, rel)
        except PathSafetyError as e:
            raise WorktreeApplyError(str(e)) from e
        if isinstance(content, (dict, list)):
            atomic_write_json(dest, content)
        else:
            atomic_write_text(dest, str(content))
        written.append(rel)

    return {
        "pattern": pattern_id,
        "pack_id": pattern.get("pack_id"),
        "files_written": written,
        "worktree": str(wt),
    }


def verify_in_worktree(
    worktree_path: Path | str,
    pattern_id: str = DEFAULT_PATTERN,
) -> dict[str, Any]:
    """Run pattern verification inside the worktree (offline, no network)."""
    from . import skillpacks as sp

    wt = Path(worktree_path).resolve()
    pattern = get_pattern(pattern_id)
    verify = str(pattern.get("verify") or "skillpack_validate")
    pack_id = str(pattern.get("pack_id") or "")

    if verify == "skillpack_validate":
        pack_dir = wt / "skillpacks" / pack_id
        if not pack_dir.is_dir():
            return {
                "ok": False,
                "verify": verify,
                "error": f"pack dir missing: {pack_dir}",
            }
        rep = sp.validate_pack(pack_dir)
        # Require structural ok; also require APPLY_META present
        meta_ok = (pack_dir / "APPLY_META.json").is_file()
        return {
            "ok": bool(rep.ok and meta_ok),
            "verify": verify,
            "pack_id": pack_id,
            "validate": rep.to_dict(),
            "apply_meta_present": meta_ok,
        }

    return {"ok": False, "verify": verify, "error": f"unknown verify mode {verify}"}


def run_apply(
    workdir: Path | str,
    *,
    fixture: Optional[Path | str] = None,
    repo: Optional[str] = None,
    pattern_id: str = DEFAULT_PATTERN,
    run_id: Optional[str] = None,
    mode: str = "auto",
    cleanup: bool = True,
    require_path_exists: bool = False,
    ledger: Optional[DecisionLedger] = None,
    skip_smoke_prefix: bool = False,
    grade: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Full ordered apply: mine→grade→claim_verify→plan_apply→apply (isolated).

    When *skip_smoke_prefix* is True and *grade* is provided, starts at
    plan_apply (assumes prior stages already completed externally).
    """
    workdir = Path(workdir).resolve()
    rid = run_id or f"apply-{uuid.uuid4().hex[:10]}"
    pid = pattern_id or DEFAULT_PATTERN
    runner = StageRunner.apply_slice()
    timeline: list[dict[str, Any]] = []
    own_ledger = ledger is None
    store = ledger or DecisionLedger.open(workdir)
    wt_meta: Optional[dict[str, Any]] = None
    main_before: dict[str, str] = {}
    # Paths that must remain untouched on main (isolation proof)
    watch_paths = [
        "skillpacks/markdown-sot-demo/manifest.json",
        "skillpacks/markdown-sot-demo/SKILL.md",
        "src/nexus/worktree_apply.py",
    ]

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
        "pattern": pid,
        "stages": list(APPLY_STAGES),
        "completed": [],
        "grade": None,
        "claim": None,
        "worktree": None,
        "apply": None,
        "verify": None,
        "main_untouched": None,
        "cleanup": None,
        "ledger_tail": [],
        "timeline": timeline,
        "error": None,
    }

    try:
        # --- mine / grade / claim_verify (or accept preloaded grade) ---
        if skip_smoke_prefix and grade is not None:
            for s in ("mine", "grade", "claim_verify"):
                if s not in runner.completed:
                    runner.completed.append(s)
            g = grade
            claim = verify_claim(
                g,
                workdir=workdir,
                require_path_exists=require_path_exists,
            )
            report["grade"] = {
                "repo": g.get("repo"),
                "score": g.get("score"),
                "idea": g.get("idea"),
                "skill": g.get("skill"),
                "method": g.get("method"),
                "path": g.get("path"),
                "pattern": g.get("pattern"),
            }
            report["claim"] = claim
            _log("preload", f"repo={g.get('repo')}")
        else:
            runner.assert_can_run("mine")
            g = load_one(workdir, repo=repo, fixture=fixture)
            store.append(
                run_id=rid,
                agent="mine",
                claim=f"loaded grade for {g.get('repo')}",
                evidence_refs=[str(g.get("path") or "")],
                grade={
                    "repo": g.get("repo"),
                    "score": g.get("score"),
                    "path": g.get("path"),
                },
                action="mine_load",
            )
            runner.mark_complete("mine")
            _log("mine", f"repo={g.get('repo')} score={g.get('score')}")

            runner.assert_can_run("grade")
            store.append(
                run_id=rid,
                agent="grade",
                claim=(
                    f"grade artifact score={g.get('score')} "
                    f"idea={g.get('idea')} skill={g.get('skill')}"
                ),
                evidence_refs=[str(g.get("path") or "")],
                grade={
                    "repo": g.get("repo"),
                    "score": g.get("score"),
                    "idea": g.get("idea"),
                    "skill": g.get("skill"),
                    "method": g.get("method"),
                    "path": g.get("path"),
                },
                action="grade_accept",
            )
            runner.mark_complete("grade")
            _log("grade", f"method={g.get('method')}")
            report["grade"] = {
                "repo": g.get("repo"),
                "score": g.get("score"),
                "idea": g.get("idea"),
                "skill": g.get("skill"),
                "method": g.get("method"),
                "path": g.get("path"),
                "pattern": g.get("pattern"),
            }

            runner.assert_can_run("claim_verify")
            claim = verify_claim(
                g,
                workdir=workdir,
                require_path_exists=require_path_exists,
            )
            store.append(
                run_id=rid,
                agent="claim_verify",
                claim=f"verified claim for {g.get('repo')}",
                evidence_refs=[str(g.get("path") or "")],
                grade={
                    "repo": g.get("repo"),
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

        # Snapshot main before apply (isolation invariant)
        main_before = snapshot_main_fingerprint(workdir, watch_paths)

        # --- plan_apply: create worktree + choose pattern ---
        runner.assert_can_run("plan_apply")
        get_pattern(pid)  # validate catalog entry
        wt_meta = create_worktree(workdir, job_id=rid, mode=mode)
        report["worktree"] = wt_meta
        store.append(
            run_id=rid,
            agent="plan_apply",
            claim=f"planned isolated apply pattern={pid} mode={wt_meta.get('mode')}",
            evidence_refs=[
                str(g.get("path") or ""),
                str(wt_meta.get("path") or ""),
            ],
            grade={
                "repo": g.get("repo"),
                "score": g.get("score"),
                "path": g.get("path"),
                "pattern": pid,
            },
            action="plan_worktree",
        )
        runner.mark_complete("plan_apply")
        _log("plan_apply", f"mode={wt_meta.get('mode')} path={wt_meta.get('path')}")

        # --- apply: materialise pattern + verify inside worktree ---
        runner.assert_can_run("apply")
        applied = apply_pattern_files(
            wt_meta["path"],
            pid,
            grade=g,
            job_id=rid,
        )
        report["apply"] = applied
        verify = verify_in_worktree(wt_meta["path"], pid)
        report["verify"] = verify
        if not verify.get("ok"):
            raise WorktreeApplyError(
                f"verify failed in worktree: {verify.get('error') or verify}"
            )

        # Isolation: main watch paths unchanged
        main_after = snapshot_main_fingerprint(workdir, watch_paths)
        untouched = main_before == main_after
        report["main_untouched"] = {
            "ok": untouched,
            "before": main_before,
            "after": main_after,
        }
        if not untouched:
            raise WorktreeApplyError(
                "isolation violated: main workdir files changed during apply"
            )

        # Pattern files must exist under worktree; main fingerprint already proves
        # isolation when those paths were missing or unchanged on main.
        wt_pack = Path(wt_meta["path"]) / "skillpacks" / "markdown-sot-demo" / "SKILL.md"
        if not wt_pack.is_file():
            raise WorktreeApplyError("pattern SKILL.md missing from worktree")

        store.append(
            run_id=rid,
            agent="apply",
            claim=(
                f"applied {pid} in worktree files={len(applied.get('files_written') or [])} "
                f"verify=ok main_untouched={untouched}"
            ),
            evidence_refs=list(applied.get("files_written") or [])
            + [str(wt_meta.get("path") or "")],
            grade={
                "repo": g.get("repo"),
                "score": g.get("score"),
                "path": g.get("path"),
                "pattern": pid,
            },
            action="apply_worktree",
        )
        runner.mark_complete("apply")
        _log("apply", f"files={applied.get('files_written')}")

        report["completed"] = list(runner.completed)
        report["ok"] = runner.is_done() and bool(verify.get("ok")) and untouched
        report["stage_status"] = runner.status()
        report["ledger_tail"] = store.tail(limit=12, run_id=rid)
        return report

    except (
        StageOrderError,
        ClaimVerifyError,
        WorktreeApplyError,
        FileNotFoundError,
        ValueError,
        PathSafetyError,
    ) as e:
        report["error"] = f"{type(e).__name__}: {e}"
        report["completed"] = list(runner.completed)
        report["stage_status"] = runner.status()
        try:
            report["ledger_tail"] = store.tail(limit=12, run_id=rid)
        except Exception:
            report["ledger_tail"] = []
        _log("error", report["error"])
        return report
    finally:
        if cleanup and wt_meta and wt_meta.get("path"):
            try:
                report["cleanup"] = cleanup_worktree(
                    workdir, wt_meta.get("job_id") or rid, meta=wt_meta
                )
            except Exception as ce:  # noqa: BLE001 — best-effort cleanup
                report["cleanup"] = {"removed": False, "error": str(ce)}
        if own_ledger:
            store.close()


def format_report(report: dict[str, Any]) -> str:
    """Human-readable apply board."""
    g = report.get("grade") or {}
    wt = report.get("worktree") or {}
    lines = [
        "=== NEXUS improve apply (worktree-isolated) ===",
        f"run_id:    {report.get('run_id')}",
        f"ok:        {report.get('ok')}",
        f"stages:    {' → '.join(report.get('stages') or APPLY_STAGES)}",
        f"completed: {', '.join(report.get('completed') or []) or '(none)'}",
        f"pattern:   {report.get('pattern')}",
        f"repo:      {g.get('repo')}  score={g.get('score')} "
        f"(idea={g.get('idea')} skill={g.get('skill')})",
        f"worktree:  mode={wt.get('mode')} path={wt.get('path')}",
    ]
    app = report.get("apply") or {}
    if app:
        lines.append(f"files:     {', '.join(app.get('files_written') or [])}")
    ver = report.get("verify") or {}
    if ver:
        lines.append(f"verify:    ok={ver.get('ok')} mode={ver.get('verify')}")
    mu = report.get("main_untouched") or {}
    if mu:
        lines.append(f"main clean:{mu.get('ok')}")
    if report.get("cleanup"):
        c = report["cleanup"]
        lines.append(f"cleanup:   removed={c.get('removed')} via={c.get('method')}")
    if report.get("error"):
        lines.append(f"error:     {report['error']}")
    tail = report.get("ledger_tail") or []
    lines.append(f"ledger:    {len(tail)} recent decision(s)")
    for row in reversed(tail):
        lines.append(
            f"  [{row.get('agent')}] {row.get('action')}: {row.get('claim')}"
        )
    lines.append(f"pass:      {'YES' if report.get('ok') else 'NO'}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="nexus-worktree-apply",
        description="Worktree-isolated apply of one Markdown skill SoT pattern",
    )
    ap.add_argument("--path", default=".", help="project workdir")
    ap.add_argument("--fixture", default=None, help="grade JSON fixture")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--run-id", default=None)
    ap.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=f"pattern id (default: {DEFAULT_PATTERN})",
    )
    ap.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "sandbox", "git"],
        help="isolation mode (default: auto)",
    )
    ap.add_argument(
        "--keep",
        action="store_true",
        help="do not cleanup worktree after apply",
    )
    ap.add_argument("--require-path-exists", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--list-patterns",
        action="store_true",
        help="list available patterns and exit",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.list_patterns:
        rows = list_patterns()
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                print(f"{r['id']}: {r.get('repo')} — {r.get('description')}")
        return 0

    workdir = Path(args.path).resolve()
    fixture = args.fixture
    if fixture is None:
        candidate = workdir / "tests" / "fixtures" / "mine_eval_sample.json"
        if candidate.is_file():
            fixture = str(candidate)

    report = run_apply(
        workdir,
        fixture=fixture,
        repo=args.repo,
        pattern_id=args.pattern,
        run_id=args.run_id,
        mode=args.mode,
        cleanup=not args.keep,
        require_path_exists=bool(args.require_path_exists),
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_report(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
