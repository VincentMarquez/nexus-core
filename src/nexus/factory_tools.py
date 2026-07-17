"""Built-in read tools for the capability factory (S13 Wave C).

These wrap existing modules and are safe to call without MCP registration.
Activated factory tools may also be loaded from handler.py under candidates/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from .capability_factory import (
    FACTORY_DIR,
    factory_root,
    list_candidates,
    validate_skill_candidate,
    validate_tool_candidate,
)
from .improve_apply import PathSafetyError, safe_path


def _root(workdir: Path | str | None = None) -> Path:
    if workdir:
        return Path(workdir).resolve()
    import os

    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def nexus_lesson_query(
    workdir: Path | str | None = None,
    *,
    query: str = "",
    code: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    from . import cross_run_lessons as crl

    rows = crl.load_lessons(workdir, limit=max(limit * 3, 20))
    q = (query or "").lower().strip()
    c = (code or "").strip()
    out = []
    for r in rows:
        if c and str(r.get("code") or "") != c:
            continue
        blob = f"{r.get('code')} {r.get('text')}".lower()
        if q and q not in blob:
            continue
        out.append(
            {
                "code": r.get("code"),
                "text": r.get("text"),
                "severity": r.get("severity"),
                "ts": r.get("ts"),
            }
        )
        if len(out) >= limit:
            break
    return {"ok": True, "tool": "nexus_lesson_query", "count": len(out), "lessons": out}


def nexus_scope_check(
    workdir: Path | str | None = None,
    *,
    paths: Optional[list[str]] = None,
    paths_csv: str = "",
    idea: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from . import scope_contract as sc

    path_list = list(paths or [])
    if paths_csv:
        path_list.extend([p.strip() for p in paths_csv.split(",") if p.strip()])
    contract = sc.default_contract(idea or {"id": "scope-check", "source": "tool"})
    cls = sc.classify_paths(path_list, contract)
    return {
        "ok": True,
        "tool": "nexus_scope_check",
        "contract_id": contract.get("idea_id"),
        "allowed_prefixes": contract.get("allowed_prefixes"),
        "classification": cls,
    }


def nexus_skill_search(
    workdir: Path | str | None = None,
    *,
    query: str = "",
    include_candidates: bool = True,
    limit: int = 20,
) -> dict[str, Any]:
    root = _root(workdir)
    q = (query or "").lower().strip()
    hits: list[dict[str, Any]] = []

    # live skillpacks
    sp = root / "skillpacks"
    if sp.is_dir():
        for d in sorted(sp.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            man_p = d / "manifest.json"
            skill_p = d / "SKILL.md"
            man: dict[str, Any] = {}
            if man_p.is_file():
                try:
                    man = json.loads(man_p.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    man = {}
            text = ""
            if skill_p.is_file():
                text = skill_p.read_text(encoding="utf-8", errors="replace")[:2000]
            blob = f"{d.name} {man} {text}".lower()
            if q and q not in blob:
                continue
            hits.append(
                {
                    "id": man.get("id") or d.name,
                    "source": "skillpacks",
                    "path": str(d.relative_to(root)),
                    "tags": man.get("tags"),
                    "status": "activated",
                }
            )
            if len(hits) >= limit:
                break

    if include_candidates and len(hits) < limit:
        for c in list_candidates(root, kind="skills"):
            blob = f"{c.get('id')} {c.get('dir')}".lower()
            if q and q not in blob:
                continue
            hits.append(
                {
                    "id": c.get("id"),
                    "source": "candidate",
                    "path": c.get("dir"),
                    "status": c.get("status"),
                }
            )
            if len(hits) >= limit:
                break

    return {"ok": True, "tool": "nexus_skill_search", "count": len(hits), "skills": hits}


def nexus_pack_validate(
    workdir: Path | str | None = None,
    *,
    path: str = "",
) -> dict[str, Any]:
    root = _root(workdir)
    if not path:
        return {"ok": False, "error": "path required"}
    try:
        p = safe_path(root, path)
    except PathSafetyError as e:
        return {"ok": False, "error": str(e)}
    if (p / "SKILL.md").is_file():
        return {"ok": True, "kind": "skill", **validate_skill_candidate(p)}
    if (p / "handler.py").is_file() or (p / "TOOL.md").is_file():
        return {"ok": True, "kind": "tool", **validate_tool_candidate(p)}
    return {"ok": False, "error": "unrecognized pack (need SKILL.md or TOOL.md/handler.py)"}


def nexus_code_review(
    workdir: Path | str | None = None,
    *,
    paths: Optional[list[str]] = None,
    paths_csv: str = "",
) -> dict[str, Any]:
    """Structured review checklist (no LLM) — companion to code-review skill."""
    root = _root(workdir)
    path_list = list(paths or [])
    if paths_csv:
        path_list.extend([p.strip() for p in paths_csv.split(",") if p.strip()])
    findings: list[dict[str, Any]] = []
    for rel in path_list[:40]:
        try:
            p = safe_path(root, rel)
        except PathSafetyError:
            findings.append(
                {
                    "path": rel,
                    "severity": "high",
                    "issue": "path_escape_or_invalid",
                }
            )
            continue
        if not p.is_file():
            findings.append({"path": rel, "severity": "med", "issue": "missing_file"})
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            findings.append({"path": rel, "severity": "med", "issue": f"read_error:{e}"})
            continue
        # lightweight static smells
        if "TODO" in text or "FIXME" in text:
            findings.append({"path": rel, "severity": "low", "issue": "todo_or_fixme"})
        if re_search_secretish(text):
            findings.append({"path": rel, "severity": "high", "issue": "possible_secret"})
        if p.suffix == ".py" and "except:" in text and "except Exception" not in text:
            findings.append({"path": rel, "severity": "low", "issue": "bare_except"})
        if len(text) > 200_000:
            findings.append({"path": rel, "severity": "med", "issue": "very_large_file"})
    return {
        "ok": True,
        "tool": "nexus_code_review",
        "paths": len(path_list),
        "findings": findings,
        "note": "static checklist only — pair with code-review-portfolio-slice skill for LLM review",
    }


def re_search_secretish(text: str) -> bool:
    import re

    pats = [
        r"api[_-]?key\s*=\s*['\"][^'\"]{8,}",
        r"secret\s*=\s*['\"][^'\"]{8,}",
        r"BEGIN (RSA |OPENSSH )?PRIVATE KEY",
        r"xai-[A-Za-z0-9]{20,}",
    ]
    for p in pats:
        if re.search(p, text, re.I):
            return True
    return False


BUILTIN_TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "nexus_lesson_query": nexus_lesson_query,
    "nexus_scope_check": nexus_scope_check,
    "nexus_skill_search": nexus_skill_search,
    "nexus_pack_validate": nexus_pack_validate,
    "nexus_code_review": nexus_code_review,
}


def invoke_tool(
    name: str,
    workdir: Path | str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke a builtin read tool or an activated factory tool handler."""
    n = str(name or "").strip()
    if n in BUILTIN_TOOLS:
        try:
            return BUILTIN_TOOLS[n](workdir, **kwargs)
        except TypeError:
            # some kwargs unused
            fn = BUILTIN_TOOLS[n]
            return fn(workdir)  # type: ignore[call-arg]
        except Exception as e:
            return {"ok": False, "tool": n, "error": str(e)[:400]}

    # activated registry
    root = _root(workdir)
    reg_path = factory_root(root) / "activated_tools.json"
    if reg_path.is_file():
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            reg = {}
        meta = (reg.get("tools") or {}).get(n)
        if meta:
            if str(meta.get("privilege") or "read") != "read":
                return {
                    "ok": False,
                    "tool": n,
                    "error": "only read tools invokable via factory_tools in v1",
                }
            handler = root / str(meta.get("handler") or "")
            try:
                handler.relative_to((root / FACTORY_DIR / "candidates" / "tools").resolve())
            except ValueError:
                return {"ok": False, "tool": n, "error": "handler outside factory jail"}
            if not handler.is_file():
                return {"ok": False, "tool": n, "error": "handler missing"}
            # load handler module by path
            import importlib.util

            spec = importlib.util.spec_from_file_location(f"factory_tool_{n}", handler)
            if not spec or not spec.loader:
                return {"ok": False, "tool": n, "error": "cannot load handler"}
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            handle = getattr(mod, "handle", None)
            if not callable(handle):
                return {"ok": False, "tool": n, "error": "handler.handle missing"}
            try:
                return dict(handle(**kwargs))
            except Exception as e:
                return {"ok": False, "tool": n, "error": str(e)[:400]}

    return {"ok": False, "error": f"unknown tool: {n}", "known_builtins": list(BUILTIN_TOOLS)}
