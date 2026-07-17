"""Capability factory (S12/S13) — propose skills & tools under quarantine.

Creation ≠ activation:
  candidates live under ``.nexus_state/capability_factory/candidates/``
  live skills only after ``activate_skill`` → ``skillpacks/<id>/``
  live tools only after ``activate_tool`` records + optional handler path

Default: all generate/activate paths are explicit API calls (no auto REAL wire yet).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .improve_apply import PathSafetyError, safe_path

SCHEMA = "nexus.capability_factory/v1"
FACTORY_DIR = ".nexus_state/capability_factory"
SKILL_SCHEMA = "nexus.skill_candidate/v1"
TOOL_SCHEMA = "nexus.tool_candidate/v1"
MAX_ID_LEN = 64


class FactoryError(RuntimeError):
    """Capability factory error."""


def _root(workdir: Path | str | None = None) -> Path:
    if workdir:
        return Path(workdir).resolve()
    import os

    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def factory_root(workdir: Path | str | None = None) -> Path:
    d = _root(workdir) / FACTORY_DIR
    (d / "candidates" / "skills").mkdir(parents=True, exist_ok=True)
    (d / "candidates" / "tools").mkdir(parents=True, exist_ok=True)
    return d


def sanitize_capability_id(raw: str) -> str:
    raw_s = str(raw or "").strip()
    if not raw_s or "/" in raw_s or "\\" in raw_s or ".." in raw_s:
        raise FactoryError(f"invalid capability id: {raw!r}")
    s = re.sub(r"[^\w.\-]+", "-", raw_s.lower()).strip("-._")
    s = re.sub(r"-{2,}", "-", s)
    if not s or s in (".", "..") or ".." in s:
        raise FactoryError(f"invalid capability id: {raw!r}")
    if len(s) > MAX_ID_LEN:
        s = s[:MAX_ID_LEN].rstrip("-._")
    if not re.fullmatch(r"[\w.\-]+", s):
        raise FactoryError(f"invalid capability id: {raw!r}")
    return s


def _ledger_path(root: Path) -> Path:
    return factory_root(root) / "ledger.jsonl"


def append_ledger(
    workdir: Path | str | None,
    *,
    action: str,
    kind: str,
    cap_id: str,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    path = _ledger_path(_root(workdir))
    row = {
        "schema": SCHEMA,
        "ts": time.time(),
        "action": action,
        "kind": kind,
        "id": cap_id,
        "detail": detail or {},
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _short_hash(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode("utf-8", errors="replace")).hexdigest()
    return h[:8]


def _skill_template(cap_id: str, *, title: str, purpose: str, evidence: str) -> str:
    return f"""# Skill: {title}

## When to use

{purpose}

## Steps

1. Read the scope / file list for this unit of work (prefer strict delta).
2. Apply the procedure below without expanding into unrelated paths.
3. Record residuals and link evidence.

## Procedure

(Fill during implement / Grok fill. Keep small and testable.)

1. …
2. …
3. …

## Tools (optional)

List callables this skill may use (S13), e.g. `nexus_scope_check`, `nexus_lesson_query`.

## Rules

1. Prefer small, tested changes.
2. Do not force-push; do not commit secrets.
3. Creation of candidates is not activation of live packs/tools.
4. Stay within allowed prefixes for the current scope contract when present.

## Success

- Checklist completed
- Tests / smoke for this skill green when defined
- Evidence linked in EVIDENCE.md

## Evidence seed

{evidence}
"""


def _tool_template(name: str, *, purpose: str, privilege: str, evidence: str) -> str:
    return f"""# Tool: {name}

## Purpose

{purpose}

## Privilege

`{privilege}` (default read; write/ops require owner activation)

## Arguments

| Name | Type | Required | Description |
|------|------|----------|-------------|
| query | string | no | Free-text query / path list |

## Returns

JSON object with `ok`, `result` / `error`.

## Safety

- Path jail when touching files
- No network unless privilege and policy allow
- Fail closed on invalid args

## Evidence seed

{evidence}
"""


def propose_skill(
    workdir: Path | str | None,
    *,
    skill_id: str,
    title: str = "",
    purpose: str = "",
    tags: Optional[list[str]] = None,
    evidence: str = "",
    required_tools: Optional[list[str]] = None,
    source: str = "manual",
) -> dict[str, Any]:
    """Create a quarantined skill candidate (never writes skillpacks/)."""
    root = _root(workdir)
    factory_root(root)
    sid = sanitize_capability_id(skill_id)
    hid = _short_hash(sid, purpose or title, str(time.time()))
    cand = factory_root(root) / "candidates" / "skills" / f"{sid}-{hid}"
    if cand.exists():
        raise FactoryError(f"candidate exists: {cand}")
    # path jail
    try:
        safe_path(factory_root(root) / "candidates" / "skills", f"{sid}-{hid}")
    except PathSafetyError as e:
        raise FactoryError(str(e)) from e

    cand.mkdir(parents=True, exist_ok=False)
    title_s = (title or sid).strip()[:120]
    purpose_s = (purpose or f"Reusable procedure for {sid}").strip()[:800]
    evidence_s = (evidence or "(none)").strip()[:2000]
    tags = list(tags or ["nexus", "factory", "candidate"])

    manifest = {
        "id": sid,
        "version": "0.0.1-candidate",
        "name": title_s,
        "tags": tags,
        "privilege": "read",
        "entrypoints": {"skill": "SKILL.md"},
        "harnesses": ["grok", "claude", "local"],
        "required_tools": list(required_tools or []),
        "factory": {
            "schema": SKILL_SCHEMA,
            "status": "proposed",
            "source": source,
            "candidate_dir": str(cand.relative_to(root)),
        },
    }
    (cand / "SKILL.md").write_text(
        _skill_template(sid, title=title_s, purpose=purpose_s, evidence=evidence_s),
        encoding="utf-8",
    )
    (cand / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (cand / "EVIDENCE.md").write_text(
        f"# Evidence — {sid}\n\n{evidence_s}\n", encoding="utf-8"
    )
    status = {
        "schema": SKILL_SCHEMA,
        "id": sid,
        "status": "proposed",
        "ts": time.time(),
        "path": str(cand.relative_to(root)),
        "source": source,
    }
    (cand / "STATUS.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )
    (cand / "tests").mkdir(exist_ok=True)
    (cand / "tests" / "test_pack_layout.py").write_text(
        f'''"""Pack layout smoke for candidate {sid}."""
from pathlib import Path

def test_skill_md_and_manifest_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "SKILL.md").is_file()
    assert (root / "manifest.json").is_file()
''',
        encoding="utf-8",
    )
    append_ledger(
        root, action="propose", kind="skill", cap_id=sid, detail={"path": status["path"]}
    )
    # skill → tool spawn (missing required_tools become tool candidates)
    spawned = _spawn_required_tools(
        root,
        list(required_tools or []),
        evidence=f"skill propose {sid}",
    )
    return {
        "ok": True,
        "id": sid,
        "path": str(cand),
        "status": "proposed",
        "kind": "skill",
        "spawned_tools": spawned,
    }


def propose_tool(
    workdir: Path | str | None,
    *,
    tool_name: str,
    purpose: str = "",
    privilege: str = "read",
    evidence: str = "",
    source: str = "manual",
) -> dict[str, Any]:
    """Create a quarantined tool candidate (never registers MCP)."""
    root = _root(workdir)
    factory_root(root)
    # tools use snake_case names for callables
    name = re.sub(r"[^\w]+", "_", str(tool_name).strip().lower()).strip("_")
    if not name or not re.fullmatch(r"[a-z][\w]{1,62}", name):
        raise FactoryError(f"invalid tool name: {tool_name!r}")
    priv = str(privilege or "read").strip().lower()
    if priv not in ("read", "write", "ops", "admin"):
        raise FactoryError(f"invalid privilege: {privilege!r}")
    if priv != "read":
        # still allow proposing write tools; activation will refuse without flag
        pass

    hid = _short_hash(name, purpose, str(time.time()))
    cand = factory_root(root) / "candidates" / "tools" / f"{name}-{hid}"
    try:
        safe_path(factory_root(root) / "candidates" / "tools", f"{name}-{hid}")
    except PathSafetyError as e:
        raise FactoryError(str(e)) from e
    cand.mkdir(parents=True, exist_ok=False)

    purpose_s = (purpose or f"Callable tool {name}").strip()[:800]
    evidence_s = (evidence or "(none)").strip()[:2000]
    (cand / "TOOL.md").write_text(
        _tool_template(name, purpose=purpose_s, privilege=priv, evidence=evidence_s),
        encoding="utf-8",
    )
    (cand / "EVIDENCE.md").write_text(
        f"# Evidence — {name}\n\n{evidence_s}\n", encoding="utf-8"
    )
    handler = f'''"""Candidate handler for {name} (quarantine — not live MCP)."""
from __future__ import annotations
from typing import Any

PRIVILEGE = {priv!r}
TOOL_NAME = {name!r}


def handle(**kwargs: Any) -> dict[str, Any]:
    """Implement real logic before activate. Default is a safe stub."""
    return {{
        "ok": True,
        "tool": TOOL_NAME,
        "privilege": PRIVILEGE,
        "args": kwargs,
        "note": "stub — fill before activation",
        "candidate": True,
    }}
'''
    (cand / "handler.py").write_text(handler, encoding="utf-8")
    (cand / "test_handler.py").write_text(
        f'''"""Tests for candidate tool {name}."""
from handler import handle, TOOL_NAME, PRIVILEGE

def test_handle_stub():
    r = handle(query="ping")
    assert r["ok"] is True
    assert r["tool"] == TOOL_NAME
    assert PRIVILEGE in ("read", "write", "ops", "admin")
''',
        encoding="utf-8",
    )
    status = {
        "schema": TOOL_SCHEMA,
        "id": name,
        "status": "proposed",
        "privilege": priv,
        "ts": time.time(),
        "path": str(cand.relative_to(root)),
        "source": source,
    }
    (cand / "STATUS.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )
    meta = {
        "name": name,
        "privilege": priv,
        "purpose": purpose_s,
        "factory": status,
    }
    (cand / "manifest.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    append_ledger(
        root, action="propose", kind="tool", cap_id=name, detail={"path": status["path"], "privilege": priv}
    )
    return {"ok": True, "id": name, "path": str(cand), "status": "proposed", "kind": "tool", "privilege": priv}


def validate_skill_candidate(cand_dir: Path | str) -> dict[str, Any]:
    """Structural validate of a skill candidate directory."""
    d = Path(cand_dir)
    errors: list[str] = []
    if not d.is_dir():
        return {"ok": False, "errors": ["not a directory"]}
    if not (d / "SKILL.md").is_file():
        errors.append("missing SKILL.md")
    if not (d / "manifest.json").is_file():
        errors.append("missing manifest.json")
    else:
        try:
            man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            if not man.get("id"):
                errors.append("manifest.id missing")
        except json.JSONDecodeError as e:
            errors.append(f"manifest json: {e}")
    if not (d / "STATUS.json").is_file():
        errors.append("missing STATUS.json")
    return {"ok": not errors, "errors": errors, "path": str(d)}


def validate_tool_candidate(cand_dir: Path | str) -> dict[str, Any]:
    d = Path(cand_dir)
    errors: list[str] = []
    if not d.is_dir():
        return {"ok": False, "errors": ["not a directory"]}
    for name in ("TOOL.md", "handler.py", "STATUS.json"):
        if not (d / name).is_file():
            errors.append(f"missing {name}")
    # refuse handlers that escape with obvious bad patterns (light)
    hp = d / "handler.py"
    if hp.is_file():
        text = hp.read_text(encoding="utf-8", errors="replace")
        if "subprocess" in text and "PRIVILEGE = \"read\"" in text:
            errors.append("read tool should not use subprocess without review")
    return {"ok": not errors, "errors": errors, "path": str(d)}


def list_candidates(
    workdir: Path | str | None = None,
    *,
    kind: str = "all",
) -> list[dict[str, Any]]:
    root = _root(workdir)
    fr = factory_root(root)
    out: list[dict[str, Any]] = []
    kinds = ("skills", "tools") if kind == "all" else (kind if kind.endswith("s") else kind + "s",)
    for k in kinds:
        base = fr / "candidates" / k
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if not p.is_dir():
                continue
            st = {}
            sp = p / "STATUS.json"
            if sp.is_file():
                try:
                    st = json.loads(sp.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    st = {}
            out.append(
                {
                    "kind": "skill" if k == "skills" else "tool",
                    "dir": str(p.relative_to(root)),
                    "id": st.get("id") or p.name,
                    "status": st.get("status") or "unknown",
                    "privilege": st.get("privilege"),
                }
            )
    return out


def _spawn_required_tools(
    workdir: Path | str | None,
    required_tools: list[str],
    *,
    evidence: str = "",
) -> list[dict[str, Any]]:
    """For each missing tool name, propose a tool candidate (skill→tool spawn)."""
    root = _root(workdir)
    spawned: list[dict[str, Any]] = []
    existing = {c.get("id") for c in list_candidates(root, kind="tools")}
    # also skip builtins
    try:
        from .factory_tools import BUILTIN_TOOLS

        existing |= set(BUILTIN_TOOLS)
    except Exception:
        pass
    reg_path = factory_root(root) / "activated_tools.json"
    if reg_path.is_file():
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
            existing |= set((reg.get("tools") or {}).keys())
        except json.JSONDecodeError:
            pass
    for name in required_tools or []:
        n = re.sub(r"[^\w]+", "_", str(name).strip().lower()).strip("_")
        if not n or n in existing:
            continue
        try:
            r = propose_tool(
                root,
                tool_name=n,
                purpose=f"Tool required by skill (auto-spawn): {n}",
                privilege="read",
                evidence=evidence or "spawned from skill.required_tools",
                source="skill_spawn",
            )
            spawned.append(r)
            existing.add(n)
        except FactoryError as e:
            spawned.append({"id": n, "error": str(e)})
    return spawned


def fill_skill_candidate(
    workdir: Path | str | None,
    cand_dir: Path | str,
    *,
    use_grok: bool = True,
    grok_fn: Any = None,
) -> dict[str, Any]:
    """Fill SKILL.md with a concrete procedure (Grok when available, else heuristic).

    Always stays inside the candidate dir. Updates STATUS to ``filled``.
    """
    root = _root(workdir)
    d = Path(cand_dir)
    if not d.is_absolute():
        d = (root / d).resolve()
    try:
        d.relative_to((root / FACTORY_DIR / "candidates" / "skills").resolve())
    except ValueError as e:
        raise FactoryError("fill refused: not under factory skills/") from e

    man: dict[str, Any] = {}
    if (d / "manifest.json").is_file():
        try:
            man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            man = {}
    sid = str(man.get("id") or d.name.split("-")[0])
    title = str(man.get("name") or sid)
    evidence = ""
    if (d / "EVIDENCE.md").is_file():
        evidence = (d / "EVIDENCE.md").read_text(encoding="utf-8", errors="replace")[:1500]
    purpose = ""
    skill_path = d / "SKILL.md"
    if skill_path.is_file():
        # extract purpose from When to use section if present
        raw = skill_path.read_text(encoding="utf-8", errors="replace")
        if "## When to use" in raw:
            purpose = raw.split("## When to use", 1)[1].split("##", 1)[0].strip()[:500]

    filled_by = "heuristic"
    body = None
    if use_grok:
        try:
            from . import grok_worker as gw

            if gw.grok_available() or grok_fn is not None:
                prompt = (
                    f"Rewrite the skill file at {skill_path} for NEXUS self-improve.\n"
                    f"Skill id: {sid}\nTitle: {title}\nPurpose: {purpose}\n"
                    f"Evidence:\n{evidence}\n\n"
                    "Write a COMPLETE SKILL.md (markdown) with sections: When to use, "
                    "Steps (numbered, concrete), Procedure (detailed), Tools (optional "
                    "nexus_* names), Rules, Success. No secrets. Max ~120 lines. "
                    "Output ONLY the markdown file contents."
                )
                fn = grok_fn or gw.grok_prompt
                if grok_fn is not None:
                    res = grok_fn(root, prompt)
                else:
                    res = gw.grok_prompt(
                        prompt,
                        max_turns=2,
                        tools=False,
                        timeout_s=180,
                        label="skill_fill",
                        soft_ok=True,
                    )
                text = ""
                if isinstance(res, dict):
                    text = str(res.get("text") or "")
                else:
                    text = str(res or "")
                text = text.strip()
                if text.startswith("```"):
                    text = text.strip("`")
                    if text.lower().startswith("markdown"):
                        text = text[8:].lstrip()
                    elif text.lower().startswith("md"):
                        text = text[2:].lstrip()
                if len(text) > 200 and (
                    "# " in text[:80] or text.startswith("#")
                ):
                    body = text[:12000]
                    filled_by = "grok"
        except Exception as e:
            filled_by = f"heuristic_after_error:{type(e).__name__}"

    if not body:
        # Deterministic high-quality fill without LLM
        body = f"""# Skill: {title}

## When to use

{purpose or f'Use when working on `{sid}` related self-improve work.'}

## Steps

1. Confirm unit of work (strict file delta / scope contract if present).
2. Read EVIDENCE.md and any linked lessons.
3. Execute the procedure below without expanding scope.
4. Run pack tests / py_compile on touched files.
5. Record residuals if incomplete.

## Procedure

1. **Orient** — List in-scope files; refuse forbidden prefixes (`.venv/`, `.env`, `.nexus_state/` secrets).
2. **Diagnose** — Map symptoms to one root cause; prefer existing modules over new ones.
3. **Act** — Make the smallest change that satisfies Success.
4. **Verify** — Run focused tests; do not claim ok if compile/tests fail.
5. **Leave trail** — Update docs only if behavior changed; link cycle evidence.

## Tools (optional)

- `nexus_scope_check` — classify paths
- `nexus_lesson_query` — prior failures
- `nexus_code_review` — static review checklist
- `nexus_skill_search` — find related packs

## Rules

1. Prefer small, tested changes.
2. Do not force-push; do not commit secrets.
3. Creation of candidates is not activation.
4. Honor portfolio cooldown and scope DNA when present.

## Success

- Procedure steps completed or residual noted
- Layout tests pass for this pack
- No forbidden-path edits

## Evidence seed

{evidence or '(none)'}
"""
        if filled_by.startswith("heuristic") is False:
            filled_by = "heuristic"

    skill_path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    st: dict[str, Any] = {}
    if (d / "STATUS.json").is_file():
        try:
            st = json.loads((d / "STATUS.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            st = {}
    st["status"] = "filled"
    st["filled"] = {"ts": time.time(), "by": filled_by, "chars": len(body)}
    (d / "STATUS.json").write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
    append_ledger(
        root,
        action="fill",
        kind="skill",
        cap_id=sid,
        detail={"by": filled_by, "path": str(d.relative_to(root))},
    )
    # spawn missing tools declared on manifest
    spawned = _spawn_required_tools(
        root,
        list(man.get("required_tools") or []),
        evidence=f"skill fill {sid}",
    )
    return {
        "ok": True,
        "id": sid,
        "path": str(d),
        "filled_by": filled_by,
        "spawned_tools": spawned,
        "status": "filled",
    }


def soft_accept_skill(
    cand_dir: Path | str,
    workdir: Path | str | None = None,
) -> dict[str, Any]:
    """Soft accept: layout validate + optional pack tests. Does not activate."""
    d = Path(cand_dir)
    if not d.is_absolute():
        d = (_root(workdir) / d).resolve()
    v = validate_skill_candidate(d)
    reasons = []
    accept = bool(v.get("ok"))
    if accept:
        reasons.append("layout_ok")
    else:
        reasons.append("layout_failed")
    # require non-template procedure (filled)
    skill = d / "SKILL.md"
    if skill.is_file() and accept:
        text = skill.read_text(encoding="utf-8", errors="replace")
        if "1. …" in text or "(Fill during implement" in text:
            # still allow accept if enough content
            if len(text) < 400:
                accept = False
                reasons.append("skill_still_template")
            else:
                reasons.append("skill_content_ok")
        else:
            reasons.append("skill_content_ok")
    # run pack layout test if present
    testf = d / "tests" / "test_pack_layout.py"
    if testf.is_file() and accept:
        import subprocess

        try:
            r = subprocess.run(
                ["python3", "-m", "pytest", "-q", str(testf)],
                cwd=str(d),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode != 0:
                accept = False
                reasons.append("pack_tests_failed")
            else:
                reasons.append("pack_tests_ok")
        except Exception as e:
            reasons.append(f"pack_tests_error:{e}")
    status_path = d / "STATUS.json"
    st = {}
    if status_path.is_file():
        try:
            st = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            st = {}
    st["status"] = "accepted" if accept else "rejected"
    st["accept"] = {
        "schema": "nexus.accept_predicate/v1",
        "accept": accept,
        "soft": True,
        "reasons": reasons,
        "ts": time.time(),
    }
    status_path.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "accept": accept, "reasons": reasons, "status": st["status"]}


def activate_skill(
    workdir: Path | str | None,
    cand_dir: Path | str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Copy accepted skill candidate into skillpacks/<id>/ (creation ≠ propose)."""
    root = _root(workdir)
    d = Path(cand_dir)
    if not d.is_absolute():
        d = (root / d).resolve()
    # must live under factory candidates
    try:
        d.relative_to((root / FACTORY_DIR / "candidates" / "skills").resolve())
    except ValueError as e:
        raise FactoryError("activate refused: candidate not under factory skills/") from e

    v = validate_skill_candidate(d)
    if not v.get("ok"):
        raise FactoryError(f"activate refused: invalid candidate: {v.get('errors')}")

    st = json.loads((d / "STATUS.json").read_text(encoding="utf-8"))
    if st.get("status") not in ("accepted", "verified") and not force:
        raise FactoryError(
            f"activate refused: status={st.get('status')!r} (need accepted or force=True)"
        )

    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    sid = sanitize_capability_id(str(man.get("id") or st.get("id") or d.name))
    dest = root / "skillpacks" / sid
    try:
        safe_path(root / "skillpacks", sid)
    except PathSafetyError as e:
        raise FactoryError(str(e)) from e
    if dest.exists() and not force:
        raise FactoryError(f"skillpacks/{sid} already exists (pass force=True)")

    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(d / "SKILL.md", dest / "SKILL.md")
    # rewrite manifest for live
    live_man = dict(man)
    live_man["version"] = str(man.get("version") or "0.0.1").replace("-candidate", "")
    if live_man["version"].endswith("0.0.1") or "candidate" in str(man.get("version")):
        live_man["version"] = "0.1.0"
    live_man.pop("factory", None)
    live_man["factory_activated"] = {
        "ts": time.time(),
        "from": str(d.relative_to(root)),
    }
    (dest / "manifest.json").write_text(
        json.dumps(live_man, indent=2) + "\n", encoding="utf-8"
    )
    st["status"] = "activated"
    st["activated_path"] = str(dest.relative_to(root))
    (d / "STATUS.json").write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
    append_ledger(
        root,
        action="activate",
        kind="skill",
        cap_id=sid,
        detail={"dest": str(dest.relative_to(root))},
    )
    return {"ok": True, "id": sid, "path": str(dest), "status": "activated"}


def activate_tool_record(
    workdir: Path | str | None,
    cand_dir: Path | str,
    *,
    force: bool = False,
    allow_write: bool = False,
) -> dict[str, Any]:
    """Record tool activation (does not patch MCP). Write privilege needs allow_write."""
    root = _root(workdir)
    d = Path(cand_dir)
    if not d.is_absolute():
        d = (root / d).resolve()
    try:
        d.relative_to((root / FACTORY_DIR / "candidates" / "tools").resolve())
    except ValueError as e:
        raise FactoryError("activate refused: candidate not under factory tools/") from e

    v = validate_tool_candidate(d)
    if not v.get("ok"):
        raise FactoryError(f"activate refused: {v.get('errors')}")

    st = json.loads((d / "STATUS.json").read_text(encoding="utf-8"))
    priv = str(st.get("privilege") or "read")
    if priv != "read" and not allow_write:
        raise FactoryError(
            f"activate refused: privilege={priv!r} requires allow_write=True"
        )
    name = str(st.get("id") or "")
    if not name:
        raise FactoryError("activate refused: missing tool id")

    # registry file for activated factory tools (read path for agents)
    reg_path = factory_root(root) / "activated_tools.json"
    reg: dict[str, Any] = {"schema": SCHEMA, "tools": {}}
    if reg_path.is_file():
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            reg = {"schema": SCHEMA, "tools": {}}
    reg.setdefault("tools", {})[name] = {
        "privilege": priv,
        "candidate": str(d.relative_to(root)),
        "handler": str((d / "handler.py").relative_to(root)),
        "activated_ts": time.time(),
        "builtin": False,
    }
    reg_path.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")
    st["status"] = "activated"
    (d / "STATUS.json").write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
    append_ledger(
        root, action="activate", kind="tool", cap_id=name, detail={"privilege": priv}
    )
    return {"ok": True, "id": name, "privilege": priv, "registry": str(reg_path)}



def harvest_skill_proposals_from_lessons(
    workdir: Path | str | None = None,
    *,
    limit: int = 3,
    dry_run: bool = False,
    fill: bool = True,
    auto_accept: bool = True,
    auto_activate: bool = False,
    use_grok_fill: bool = True,
) -> dict[str, Any]:
    """Propose (+ optional fill/accept/activate) skills from S07 lesson codes."""
    root = _root(workdir)
    try:
        from . import cross_run_lessons as crl

        lessons = crl.load_lessons(root, limit=40)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "proposed": []}

    CODE_MAP = {
        "panel_timeout_or_offline": (
            "panel-timeout-resilience",
            "Recover when multi-LLM panel seats timeout",
        ),
        "synthesis_reverted": (
            "synthesis-safe-edit",
            "Apply panel synthesis only when tests stay green",
        ),
        "accept_rejected": (
            "accept-before-claim-ok",
            "Do not treat worker finished as success without accept checks",
        ),
        "implement_failed": (
            "implement-failure-triage",
            "Triage failed portfolio implement and leave residuals",
        ),
        "engine_failed_open": (
            "engine-fail-aware-brief",
            "Continue carefully when canonical engine fails open",
        ),
        "x_research_failed": (
            "x-research-fallback",
            "Proceed when live X research fails with explicit gap marker",
        ),
        "cooldown_reuse": (
            "portfolio-cooldown-hygiene",
            "Avoid re-selecting cooled high-star seeds when alternatives exist",
        ),
    }
    counts: dict[str, int] = {}
    samples: dict[str, str] = {}
    for les in lessons:
        code = str(les.get("code") or "")
        if code in CODE_MAP:
            counts[code] = counts.get(code, 0) + 1
            samples[code] = str(les.get("text") or "")[:200]

    proposed: list[dict[str, Any]] = []
    for code, n in sorted(counts.items(), key=lambda x: -x[1]):
        if len(proposed) >= limit:
            break
        if n < 1:
            continue
        sid, purpose = CODE_MAP[code]
        if (root / "skillpacks" / sid).is_dir():
            continue
        existing = [
            c
            for c in list_candidates(workdir, kind="skills")
            if c.get("id") == sid or str(c.get("dir") or "").find(sid) >= 0
        ]
        if existing:
            if fill and not dry_run:
                try:
                    ed = existing[0].get("dir") or ""
                    fill_skill_candidate(root, ed, use_grok=use_grok_fill)
                    if auto_accept:
                        soft_accept_skill(
                            root / ed if not Path(ed).is_absolute() else ed
                        )
                except Exception:
                    pass
            continue
        if dry_run:
            proposed.append(
                {"id": sid, "purpose": purpose, "from_lesson": code, "dry_run": True}
            )
            continue
        try:
            r = propose_skill(
                workdir,
                skill_id=sid,
                title=sid.replace("-", " ").title(),
                purpose=purpose,
                evidence=f"lesson:{code} n≈{n} sample={samples.get(code)}",
                source="harvest_lessons",
                tags=["nexus", "factory", "from-lesson", code],
                required_tools=["nexus_lesson_query", "nexus_scope_check"],
            )
            if fill:
                r["fill"] = fill_skill_candidate(
                    root, r["path"], use_grok=use_grok_fill
                )
            if auto_accept:
                ar = soft_accept_skill(r["path"])
                r["accept"] = ar
                if auto_activate and ar.get("accept"):
                    try:
                        r["activate"] = activate_skill(root, r["path"])
                    except FactoryError as e:
                        r["activate"] = {"ok": False, "error": str(e)}
            proposed.append(r)
        except FactoryError as e:
            proposed.append({"id": sid, "error": str(e)})
    return {"ok": True, "proposed": proposed, "lesson_codes": counts}


def retire_skill(
    workdir: Path | str | None,
    skill_id: str,
    *,
    reason: str = "retired",
) -> dict[str, Any]:
    """Move activated skillpacks/<id> to factory retired/ (Wave E)."""
    root = _root(workdir)
    sid = sanitize_capability_id(skill_id)
    src = root / "skillpacks" / sid
    if not src.is_dir():
        raise FactoryError(f"skill not activated: {sid}")
    dest_root = factory_root(root) / "retired" / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / f"{sid}-{_short_hash(sid, str(time.time()))}"
    shutil.move(str(src), str(dest))
    meta = {
        "id": sid,
        "retired_ts": time.time(),
        "reason": reason[:300],
        "path": str(dest.relative_to(root)),
    }
    (dest / "RETIRED.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    append_ledger(root, action="retire", kind="skill", cap_id=sid, detail=meta)
    return {"ok": True, **meta}


def auto_activate_ready_skills(
    workdir: Path | str | None = None,
    *,
    limit: int = 3,
    fill_first: bool = True,
    use_grok_fill: bool = False,
) -> dict[str, Any]:
    """Activate up to *limit* accepted skill candidates (Wave E soft)."""
    root = _root(workdir)
    activated: list[dict[str, Any]] = []
    for c in list_candidates(root, kind="skills"):
        if len(activated) >= limit:
            break
        st = c.get("status")
        path = c.get("dir") or ""
        full = root / path if not Path(path).is_absolute() else Path(path)
        if st in ("proposed", "filled") and fill_first:
            try:
                if st == "proposed":
                    fill_skill_candidate(root, full, use_grok=use_grok_fill)
                soft_accept_skill(full)
            except Exception as e:
                activated.append({"id": c.get("id"), "error": str(e)[:200]})
                continue
            try:
                st = json.loads((full / "STATUS.json").read_text(encoding="utf-8")).get(
                    "status"
                )
            except Exception:
                st = None
        if st != "accepted":
            continue
        sid = str(c.get("id") or "")
        if sid and (root / "skillpacks" / sid).is_dir():
            continue
        try:
            activated.append(activate_skill(root, full))
        except FactoryError as e:
            activated.append({"id": sid, "error": str(e)})
    return {"ok": True, "activated": activated}


def collect_capability_ideas(
    workdir: Path | str | None = None,
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Portfolio-style ideas for capability:skill / capability:tool (Wave D)."""
    root = _root(workdir)
    ideas: list[dict[str, Any]] = []
    for c in list_candidates(root, kind="skills"):
        if c.get("status") == "activated":
            continue
        sid = str(c.get("id") or "skill")
        ideas.append(
            {
                "source": "capability_skill",
                "id": f"capability:skill:{sid}",
                "title": f"Fill/activate skill {sid}",
                "score": 9.5,
                "summary": f"Factory skill candidate status={c.get('status')}",
                "concrete": (
                    f"Run factory fill+accept for skill `{sid}` under "
                    f"`{c.get('dir')}`; activate into skillpacks if accepted."
                ),
                "candidate_dir": c.get("dir"),
                "capability_id": sid,
                "capability_kind": "skill",
                "url": "",
            }
        )
    for c in list_candidates(root, kind="tools"):
        if c.get("status") == "activated":
            continue
        tid = str(c.get("id") or "tool")
        ideas.append(
            {
                "source": "capability_tool",
                "id": f"capability:tool:{tid}",
                "title": f"Implement/activate tool {tid}",
                "score": 9.0,
                "summary": f"Factory tool candidate privilege={c.get('privilege')}",
                "concrete": (
                    f"Implement handler for tool `{tid}` in `{c.get('dir')}` "
                    f"and activate (read-only default)."
                ),
                "candidate_dir": c.get("dir"),
                "capability_id": tid,
                "capability_kind": "tool",
                "url": "",
            }
        )
    if len(ideas) < limit:
        for sid, purpose in (
            (
                "novel-diff-review",
                "Review only the git delta for an idea with a structured checklist",
            ),
            (
                "novel-test-first-slice",
                "Write or extend a focused test before product edit",
            ),
        ):
            if (root / "skillpacks" / sid).is_dir():
                continue
            if any(i.get("capability_id") == sid for i in ideas):
                continue
            ideas.append(
                {
                    "source": "capability_skill",
                    "id": f"capability:skill:{sid}",
                    "title": f"Create skill {sid}",
                    "score": 8.5,
                    "summary": purpose,
                    "concrete": f"Propose+fill+accept new skill `{sid}`: {purpose}",
                    "capability_id": sid,
                    "capability_kind": "skill",
                    "novel": True,
                    "url": "",
                }
            )
    ideas.sort(key=lambda x: -float(x.get("score") or 0))
    return ideas[: max(1, limit)]


def implement_capability_idea(
    workdir: Path | str | None,
    idea: dict[str, Any],
    *,
    use_grok_fill: bool = True,
    auto_activate_skill: bool = True,
    auto_activate_tool: bool = True,
) -> dict[str, Any]:
    """Implement a capability:* portfolio idea (fill/accept/activate)."""
    root = _root(workdir)
    kind = str(idea.get("capability_kind") or "")
    out: dict[str, Any] = {
        "ok": False,
        "source": idea.get("source"),
        "id": idea.get("id"),
        "kind": kind,
    }
    if kind == "skill":
        cand = idea.get("candidate_dir")
        sid = str(idea.get("capability_id") or "")
        if not cand:
            try:
                pr = propose_skill(
                    root,
                    skill_id=sid,
                    title=str(idea.get("title") or sid),
                    purpose=str(idea.get("concrete") or idea.get("summary") or ""),
                    evidence="portfolio capability idea",
                    source="portfolio",
                    required_tools=["nexus_scope_check", "nexus_code_review"],
                )
                cand = pr["path"]
                out["propose"] = pr
            except FactoryError as e:
                out["error"] = str(e)
                return out
        try:
            cand_path = Path(str(cand))
            if not cand_path.is_absolute():
                cand_path = (root / cand_path).resolve()
            out["fill"] = fill_skill_candidate(
                root, cand_path, use_grok=use_grok_fill
            )
            out["accept"] = soft_accept_skill(cand_path, workdir=root)
            if auto_activate_skill and out["accept"].get("accept"):
                out["activate"] = activate_skill(root, cand_path)
            out["ok"] = bool(out.get("accept", {}).get("accept"))
        except Exception as e:
            out["error"] = str(e)[:400]
        return out

    if kind == "tool":
        cand = idea.get("candidate_dir")
        tid = str(idea.get("capability_id") or "")
        if not cand:
            try:
                pr = propose_tool(
                    root,
                    tool_name=tid,
                    purpose=str(idea.get("concrete") or ""),
                    privilege="read",
                    evidence="portfolio capability idea",
                    source="portfolio",
                )
                cand = pr["path"]
                out["propose"] = pr
            except FactoryError as e:
                out["error"] = str(e)
                return out
        d = Path(cand) if Path(str(cand)).is_absolute() else (root / str(cand)).resolve()
        if (d / "STATUS.json").is_file():
            st = json.loads((d / "STATUS.json").read_text(encoding="utf-8"))
            st["status"] = "filled"
            (d / "STATUS.json").write_text(
                json.dumps(st, indent=2) + "\n", encoding="utf-8"
            )
        v = validate_tool_candidate(d)
        out["validate"] = v
        if auto_activate_tool and v.get("ok"):
            try:
                out["activate"] = activate_tool_record(root, d, allow_write=False)
                out["ok"] = True
            except FactoryError as e:
                out["error"] = str(e)
                out["ok"] = False
        else:
            out["ok"] = bool(v.get("ok"))
        return out

    out["error"] = f"unknown capability kind: {kind}"
    return out



def propose_builtin_read_tools(workdir: Path | str | None = None) -> dict[str, Any]:
    """Propose standard read tools that wrap existing modules (S13 Wave C)."""
    specs = [
        (
            "nexus_lesson_query",
            "Query cross-run lessons (S07) by keyword/code",
            "read",
        ),
        (
            "nexus_scope_check",
            "Classify paths against a scope contract (S04)",
            "read",
        ),
        (
            "nexus_skill_search",
            "Search activated skillpacks and factory candidates",
            "read",
        ),
        (
            "nexus_pack_validate",
            "Validate skillpack or skill candidate layout",
            "read",
        ),
        (
            "nexus_code_review",
            "Structured review checklist over a list of paths (skill companion)",
            "read",
        ),
    ]
    out = []
    for name, purpose, priv in specs:
        # skip if candidate or activated already
        acts = factory_root(workdir) / "activated_tools.json"
        if acts.is_file():
            try:
                reg = json.loads(acts.read_text(encoding="utf-8"))
                if name in (reg.get("tools") or {}):
                    out.append({"id": name, "skipped": "already_activated"})
                    continue
            except json.JSONDecodeError:
                pass
        existing = [c for c in list_candidates(workdir, kind="tools") if c.get("id") == name]
        if existing:
            out.append({"id": name, "skipped": "candidate_exists", "dir": existing[0].get("dir")})
            continue
        try:
            r = propose_tool(
                workdir,
                tool_name=name,
                purpose=purpose,
                privilege=priv,
                evidence="builtin wrapper over existing nexus modules",
                source="builtin_read_wave",
            )
            out.append(r)
        except FactoryError as e:
            out.append({"id": name, "error": str(e)})
    return {"ok": True, "tools": out}


def propose_golden_review_skill(workdir: Path | str | None = None) -> dict[str, Any]:
    """First golden skill: code-review-portfolio-slice."""
    return propose_skill(
        workdir,
        skill_id="code-review-portfolio-slice",
        title="Code review portfolio slice",
        purpose=(
            "Structured multi-point code review of the files in a portfolio implement "
            "slice (strict delta). Use after Grok apply / before or during panel synthesis."
        ),
        tags=["nexus", "review", "portfolio", "factory", "golden"],
        evidence="operator request: skill factory should mint review skills",
        required_tools=["nexus_scope_check", "nexus_code_review"],
        source="golden",
    )


def bootstrap_wave_ab(workdir: Path | str | None = None) -> dict[str, Any]:
    """Wave A+B: golden skill + builtin read tool candidates + lesson harvest."""
    root = _root(workdir)
    factory_root(root)
    out: dict[str, Any] = {"ok": True, "skill": None, "tools": None, "harvest": None}
    live = root / "skillpacks" / "code-review-portfolio-slice"
    cands = [
        c
        for c in list_candidates(root, kind="skills")
        if "code-review-portfolio-slice" in str(c.get("id"))
        or "code-review-portfolio-slice" in str(c.get("dir"))
    ]
    if live.is_dir():
        out["skill"] = {"skipped": "already_activated"}
    elif cands:
        out["skill"] = {"skipped": "candidate_exists", "dir": cands[0].get("dir")}
    else:
        out["skill"] = propose_golden_review_skill(root)
    out["tools"] = propose_builtin_read_tools(root)
    out["harvest"] = harvest_skill_proposals_from_lessons(root, limit=2)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: python -m nexus.capability_factory <cmd> ..."""
    import argparse
    import sys

    argv = list(argv if argv is not None else sys.argv[1:])
    p = argparse.ArgumentParser(prog="nexus.capability_factory")
    p.add_argument("--path", default=".", help="repo root")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("bootstrap", help="Wave A/B: golden skill + read tools + harvest")
    sub.add_parser("list", help="list candidates")
    ps = sub.add_parser("propose-skill", help="propose a skill candidate")
    ps.add_argument("--id", required=True)
    ps.add_argument("--title", default="")
    ps.add_argument("--purpose", default="")
    pt = sub.add_parser("propose-tool", help="propose a tool candidate")
    pt.add_argument("--name", required=True)
    pt.add_argument("--purpose", default="")
    pt.add_argument("--privilege", default="read")
    pf = sub.add_parser("fill-skill", help="fill skill candidate (Grok or heuristic)")
    pf.add_argument("candidate")
    pf.add_argument("--no-grok", action="store_true", help="heuristic fill only")
    pa = sub.add_parser("accept-skill", help="soft-accept skill candidate dir")
    pa.add_argument("candidate")
    act = sub.add_parser("activate-skill", help="activate skill into skillpacks/")
    act.add_argument("candidate")
    act.add_argument("--force", action="store_true")
    att = sub.add_parser("activate-tool", help="record tool activation")
    att.add_argument("candidate")
    att.add_argument("--allow-write", action="store_true")
    aa = sub.add_parser(
        "auto-activate", help="Wave E: activate accepted skill candidates (soft)"
    )
    aa.add_argument("--limit", type=int, default=3)
    aa.add_argument("--use-grok-fill", action="store_true")
    rs = sub.add_parser("retire-skill", help="Wave E: move skillpacks/<id> to retired/")
    rs.add_argument("--id", required=True)
    rs.add_argument("--reason", default="retired")
    hv = sub.add_parser("harvest", help="harvest skill proposals from lessons")
    hv.add_argument("--limit", type=int, default=3)
    hv.add_argument("--no-fill", action="store_true")
    hv.add_argument("--no-accept", action="store_true")
    hv.add_argument("--auto-activate", action="store_true")
    hv.add_argument("--no-grok", action="store_true")
    inv = sub.add_parser("invoke", help="invoke builtin/activated read tool")
    inv.add_argument("tool")
    inv.add_argument("--query", default="")
    inv.add_argument("--paths", default="", help="comma-separated paths")
    inv.add_argument("--code", default="", help="lesson code filter")

    args = p.parse_args(argv)
    root = Path(args.path).resolve()

    try:
        if args.cmd == "bootstrap":
            print(json.dumps(bootstrap_wave_ab(root), indent=2, default=str))
        elif args.cmd == "list":
            print(json.dumps(list_candidates(root), indent=2, default=str))
        elif args.cmd == "propose-skill":
            print(
                json.dumps(
                    propose_skill(
                        root,
                        skill_id=args.id,
                        title=args.title,
                        purpose=args.purpose,
                    ),
                    indent=2,
                    default=str,
                )
            )
        elif args.cmd == "propose-tool":
            print(
                json.dumps(
                    propose_tool(
                        root,
                        tool_name=args.name,
                        purpose=args.purpose,
                        privilege=args.privilege,
                    ),
                    indent=2,
                    default=str,
                )
            )
        elif args.cmd == "fill-skill":
            cand = Path(args.candidate)
            if not cand.is_absolute():
                cand = root / cand
            print(
                json.dumps(
                    fill_skill_candidate(
                        root, cand, use_grok=not bool(args.no_grok)
                    ),
                    indent=2,
                    default=str,
                )
            )
        elif args.cmd == "accept-skill":
            cand = Path(args.candidate)
            if not cand.is_absolute():
                cand = root / cand
            print(json.dumps(soft_accept_skill(cand), indent=2, default=str))
        elif args.cmd == "activate-skill":
            print(
                json.dumps(
                    activate_skill(root, args.candidate, force=bool(args.force)),
                    indent=2,
                    default=str,
                )
            )
        elif args.cmd == "activate-tool":
            print(
                json.dumps(
                    activate_tool_record(
                        root, args.candidate, allow_write=bool(args.allow_write)
                    ),
                    indent=2,
                    default=str,
                )
            )
        elif args.cmd == "auto-activate":
            print(
                json.dumps(
                    auto_activate_ready_skills(
                        root,
                        limit=int(args.limit),
                        use_grok_fill=bool(args.use_grok_fill),
                    ),
                    indent=2,
                    default=str,
                )
            )
        elif args.cmd == "retire-skill":
            print(
                json.dumps(
                    retire_skill(root, args.id, reason=str(args.reason)),
                    indent=2,
                    default=str,
                )
            )
        elif args.cmd == "harvest":
            print(
                json.dumps(
                    harvest_skill_proposals_from_lessons(
                        root,
                        limit=int(args.limit),
                        fill=not bool(args.no_fill),
                        auto_accept=not bool(args.no_accept),
                        auto_activate=bool(args.auto_activate),
                        use_grok_fill=not bool(args.no_grok),
                    ),
                    indent=2,
                    default=str,
                )
            )
        elif args.cmd == "invoke":
            from . import factory_tools as ft

            kw: dict[str, Any] = {}
            if args.query:
                kw["query"] = args.query
            if args.paths:
                kw["paths_csv"] = args.paths
            if args.code:
                kw["code"] = args.code
            if args.tool == "nexus_pack_validate" and args.query:
                kw["path"] = args.query
            print(
                json.dumps(
                    ft.invoke_tool(args.tool, root, **kw), indent=2, default=str
                )
            )
        else:
            return 2
    except FactoryError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
