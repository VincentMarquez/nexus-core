"""S05 — Soft accept predicate (evidence-gated *accept*, not worker ok).

Records whether an implement unit is *accepted* under light evidence:
worker ok, no forbidden path hits (if files known), optional compile check.

Soft mode never changes ``entry['ok']`` and never blocks publish by itself.
Hard block is a separate flag wired only when explicitly enabled later.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA = "nexus.accept_predicate/v1"


def _root(workdir: Path | str | None = None) -> Path:
    if workdir:
        return Path(workdir).resolve()
    import os

    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def evaluate_accept(
    root: Path | str | None,
    entry: dict[str, Any],
    *,
    idea: Optional[dict[str, Any]] = None,
    scope_contract: Optional[dict[str, Any]] = None,
    slice_files: Optional[list[str]] = None,
    panel: Optional[dict[str, Any]] = None,
    soft: bool = True,
) -> dict[str, Any]:
    """Return accept decision + reasons (never raises).

    Soft: advisory only. Does not mutate *entry* (caller may attach result).
    """
    del idea  # reserved for future mission checks
    root_p = _root(root)
    reasons: list[str] = []
    warnings: list[str] = []
    accept = True
    evidence: dict[str, Any] = {}

    # 1) Worker must claim ok
    if not entry.get("ok"):
        accept = False
        reasons.append("worker_not_ok")
    else:
        reasons.append("worker_ok")

    # 2) Panel status (informational; synthesis_reverted still keeps implement)
    if isinstance(panel, dict):
        st = str(panel.get("status") or "")
        evidence["panel_status"] = st
        if st == "panel_round1_failed":
            warnings.append("panel_offline_or_failed")
            reasons.append("panel_no_successful_critiques")
        elif st == "synthesis_reverted":
            warnings.append("synthesis_reverted_implement_kept")
            reasons.append("synthesis_reverted")
        elif st in ("synthesis_ok", "synthesis_ok_after_retry", "dry_critiques_only"):
            reasons.append(f"panel_{st}")
        elif panel.get("error"):
            warnings.append("panel_error")

    # 3) Scope classification (if contract + files)
    files = list(slice_files or [])
    if not files and isinstance(panel, dict):
        files = list(panel.get("files") or [])
    if scope_contract and files:
        try:
            from . import scope_contract as sc

            cls = sc.classify_paths(files, scope_contract)
            evidence["scope"] = {
                "in_scope": len(cls.get("in_scope") or []),
                "out_of_scope": len(cls.get("out_of_scope") or []),
                "forbidden_hit": list(cls.get("forbidden_hit") or [])[:40],
            }
            if cls.get("forbidden_hit"):
                accept = False
                reasons.append("forbidden_path_hit")
            elif cls.get("out_of_scope"):
                warnings.append("paths_outside_allowed_prefixes")
                reasons.append("scope_out_of_prefix_advisory")
            else:
                reasons.append("scope_clean")
            # incomplete coverage: S01 can't see pre-dirty content edits
            evidence["coverage_complete"] = False
            evidence["coverage_note"] = (
                "path-set delta only; pre-dirty content edits not fully observed"
            )
        except Exception as e:
            warnings.append(f"scope_classify_error:{str(e)[:120]}")
    elif scope_contract and not files:
        warnings.append("no_slice_files_for_scope")
        evidence["coverage_complete"] = False
    else:
        evidence["coverage_complete"] = None

    # 4) Light compile check on in-repo python slice files (soft evidence)
    py_files = [
        f
        for f in files
        if str(f).endswith(".py") and (root_p / f).is_file()
    ][:20]
    if py_files:
        bad: list[str] = []
        for f in py_files:
            try:
                r = subprocess.run(
                    ["python3", "-m", "py_compile", f],
                    cwd=str(root_p),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if r.returncode != 0:
                    bad.append(f"{f}:{(r.stderr or r.stdout or '')[:120]}")
            except Exception as e:
                bad.append(f"{f}:{e}")
        evidence["py_compile"] = {"checked": len(py_files), "bad": len(bad)}
        if bad:
            accept = False
            reasons.append("py_compile_failed")
            evidence["py_compile"]["samples"] = bad[:5]
        else:
            reasons.append("py_compile_ok")

    # 5) success_check from contract — metadata evaluation only when files exist
    sc_meta = (scope_contract or {}).get("success_check") if scope_contract else None
    if isinstance(sc_meta, dict):
        stype = str(sc_meta.get("type") or "none")
        if stype == "none":
            evidence["success_check"] = {"status": "not_evaluated", "type": "none"}
        elif stype == "pytest_paths":
            paths = [p for p in (sc_meta.get("paths") or []) if isinstance(p, str)]
            existing = [p for p in paths if (root_p / p).is_file()]
            if not existing:
                evidence["success_check"] = {
                    "status": "not_evaluated",
                    "type": stype,
                    "note": "paths missing",
                }
                warnings.append("success_check_paths_missing")
            else:
                try:
                    r = subprocess.run(
                        ["python3", "-m", "pytest", "-q", "--tb=line", *existing[:10]],
                        cwd=str(root_p),
                        capture_output=True,
                        text=True,
                        timeout=120,
                        env={
                            **dict(__import__("os").environ),
                            "PYTHONPATH": str(root_p / "src")
                            + __import__("os").pathsep
                            + __import__("os").environ.get("PYTHONPATH", ""),
                        },
                    )
                    evidence["success_check"] = {
                        "status": "evaluated",
                        "type": stype,
                        "ok": r.returncode == 0,
                        "paths": existing[:10],
                    }
                    if r.returncode != 0:
                        accept = False
                        reasons.append("success_check_pytest_failed")
                    else:
                        reasons.append("success_check_pytest_ok")
                except Exception as e:
                    evidence["success_check"] = {
                        "status": "not_evaluated",
                        "type": stype,
                        "error": str(e)[:200],
                    }
                    warnings.append("success_check_error")
        else:
            evidence["success_check"] = {
                "status": "not_evaluated",
                "type": stype,
            }

    out = {
        "schema": SCHEMA,
        "ts": time.time(),
        "accept": bool(accept),
        "soft": bool(soft),
        "reasons": reasons,
        "warnings": warnings,
        "evidence": evidence,
        "mode": "soft" if soft else "hard",
    }
    return out


def summarize_accepts(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate accept fields from implement results."""
    total = len(results)
    accepted = sum(
        1
        for r in results
        if isinstance(r.get("accept_predicate"), dict)
        and r["accept_predicate"].get("accept")
    )
    evaluated = sum(1 for r in results if isinstance(r.get("accept_predicate"), dict))
    return {
        "evaluated": evaluated,
        "accepted": accepted,
        "rejected": max(0, evaluated - accepted),
        "total_results": total,
        "accept_rate": (accepted / evaluated) if evaluated else None,
    }
