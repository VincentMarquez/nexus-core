"""Idea scope contracts (S04) — Bubbles/DNA discipline for portfolio implement.

Advisory by default: build a machine-readable contract, inject a short DNA block
into the **idea goal** (not the full worker preamble), and persist CONTRACT.json.

This is not a filesystem sandbox. Soft mode never drops files from the review
slice; it only classifies paths. Fail-open means legacy path on helper errors.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA = "nexus.scope_contract/v1"
DNA_TAG_OPEN = "<NEXUS_SCOPE_CONTRACT>"
DNA_TAG_CLOSE = "</NEXUS_SCOPE_CONTRACT>"
MAX_DNA_CHARS = 2500
MAX_FIELD_CHARS = 400

# Trusted local defaults only (never from untrusted idea text for policy)
DEFAULT_ALLOWED = ("src/nexus/", "tests/", "docs/")
DEFAULT_FORBIDDEN = (
    ".venv/",
    ".env",
    ".nexus_state/",
    ".nexus_workspaces/",
    ".git/",
    "__pycache__/",
)
DEFAULT_NON_GOALS = (
    "vendor whole upstream trees",
    "force-push",
    "commit secrets or .env",
    "edit files under forbidden_prefixes",
)

REQUIRED_KEYS = (
    "schema",
    "idea_id",
    "source",
    "mission",
    "allowed_prefixes",
    "forbidden_prefixes",
    "non_goals",
    "success_check",
    "max_files",
    "owner",
    "created_ts",
)


def _bound(text: Any, n: int = MAX_FIELD_CHARS) -> str:
    s = str(text or "").replace("\x00", " ")
    # neutralize delimiter breakouts in free text
    s = s.replace(DNA_TAG_OPEN, "").replace(DNA_TAG_CLOSE, "")
    s = s.replace("</", "< /").replace("\r", " ")
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", s)
    return s.strip()[:n]


def _clean_prefix(p: str) -> Optional[str]:
    """Return a safe relative prefix or None if rejected."""
    raw = str(p or "").strip().replace("\\", "/")
    if not raw or raw in (".", "/", "./"):
        return None
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return None
    if ".." in Path(raw).parts:
        return None
    # normalize
    if not raw.endswith("/") and "." not in Path(raw).name:
        # allow exact filenames like Makefile / pyproject.toml without trailing slash
        pass
    return raw


def default_allowed_prefixes(source: str) -> list[str]:
    """Least-privilege defaults; github does not auto-widen to plugins."""
    del source  # same base for all sources in v1 (deterministic)
    out: list[str] = []
    for p in DEFAULT_ALLOWED:
        c = _clean_prefix(p)
        if c:
            out.append(c)
    return out


def default_contract(idea: dict[str, Any] | None) -> dict[str, Any]:
    """Build a deterministic v1 contract from an idea dict (fail-open defaults)."""
    idea = idea or {}
    iid = _bound(idea.get("id") or "unknown", 200) or "unknown"
    source = _bound(idea.get("source") or "unknown", 40) or "unknown"
    title = _bound(idea.get("title") or iid, 200)
    concrete = _bound(idea.get("concrete") or idea.get("summary") or title, 400)
    mission = _bound(f"{title}: {concrete}", 400) if concrete else title

    allowed = default_allowed_prefixes(source)
    forbidden = [p for p in (_clean_prefix(x) for x in DEFAULT_FORBIDDEN) if p]

    # success_check is metadata-only in S04 — never shell, never placeholder module
    success_check: dict[str, Any] = {
        "type": "none",
        "note": "metadata only in S04; not executed",
    }
    # Prefer a real test path if idea id looks like a module name — still advisory
    stem = re.sub(r"[^\w]+", "_", iid.split("/")[-1].split(":")[-1])[:40]
    if stem and stem not in ("unknown",):
        cand = f"tests/test_{stem}.py"
        success_check = {
            "type": "pytest_paths",
            "paths": [cand],
            "note": "advisory path guess; may not exist yet",
        }

    return {
        "schema": SCHEMA,
        "idea_id": iid,
        "source": source,
        "mission": mission or iid,
        "allowed_prefixes": allowed,
        "forbidden_prefixes": forbidden,
        "non_goals": list(DEFAULT_NON_GOALS),
        "success_check": success_check,
        "max_files": 12,  # advisory only
        "max_new_files": 4,  # advisory only
        "owner": "alive_real",
        "created_ts": time.time(),
        "advisory": True,
    }


def validate_contract(c: dict[str, Any] | None) -> list[str]:
    """Return soft warnings; never raises."""
    warnings: list[str] = []
    if not isinstance(c, dict):
        return ["contract is not a dict"]
    for k in REQUIRED_KEYS:
        if k not in c:
            warnings.append(f"missing key: {k}")
    if c.get("schema") != SCHEMA:
        warnings.append(f"unexpected schema: {c.get('schema')}")
    for p in c.get("allowed_prefixes") or []:
        if _clean_prefix(str(p)) is None:
            warnings.append(f"bad allowed prefix: {p!r}")
    for p in c.get("forbidden_prefixes") or []:
        if _clean_prefix(str(p)) is None:
            warnings.append(f"bad forbidden prefix: {p!r}")
    sc = c.get("success_check")
    if sc is not None and not isinstance(sc, dict):
        warnings.append("success_check must be object")
    elif isinstance(sc, dict):
        t = str(sc.get("type") or "")
        if t not in ("none", "pytest_paths", "py_compile", "manual"):
            warnings.append(f"unsupported success_check.type: {t}")
        if t == "pytest_paths" and not isinstance(sc.get("paths"), list):
            warnings.append("success_check.paths must be list")
    return warnings


def _norm_rel(rel: str) -> str:
    """Normalize repo-relative path without stripping leading dots from names."""
    rel_n = str(rel or "").replace("\\", "/")
    while rel_n.startswith("./"):
        rel_n = rel_n[2:]
    return rel_n


def path_is_forbidden(rel: str, contract: dict[str, Any]) -> bool:
    rel_n = _norm_rel(rel)
    if not rel_n or ".." in Path(rel_n).parts or rel_n.startswith("/"):
        return True
    for pref in contract.get("forbidden_prefixes") or []:
        p = _clean_prefix(str(pref))
        if not p:
            continue
        if p.endswith("/"):
            if rel_n.startswith(p) or rel_n == p.rstrip("/"):
                return True
        elif rel_n == p or rel_n.startswith(p + "/"):
            return True
    return False


def path_is_allowed(rel: str, contract: dict[str, Any]) -> bool:
    """Forbidden wins. Absolute/traversal → not allowed."""
    rel_n = _norm_rel(rel)
    if not rel_n or ".." in Path(rel_n).parts or rel_n.startswith("/"):
        return False
    if path_is_forbidden(rel_n, contract):
        return False
    allowed = contract.get("allowed_prefixes") or []
    if not allowed:
        return False
    for pref in allowed:
        p = _clean_prefix(str(pref))
        if not p:
            continue
        if p.endswith("/"):
            if rel_n.startswith(p) or rel_n == p.rstrip("/"):
                return True
        elif rel_n == p or rel_n.startswith(p + "/"):
            return True
    return False


def classify_paths(
    paths: list[str],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Classify paths without dropping any (soft mode)."""
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    forbidden: list[str] = []
    for raw in paths:
        rel = _norm_rel(str(raw or ""))
        if path_is_forbidden(rel, contract):
            forbidden.append(rel)
            out_of_scope.append(rel)
        elif path_is_allowed(rel, contract):
            in_scope.append(rel)
        else:
            out_of_scope.append(rel)
    return {
        "in_scope": in_scope,
        "out_of_scope": out_of_scope,
        "forbidden_hit": forbidden,
        "all": list(paths),
    }


def format_dna_block(contract: dict[str, Any]) -> str:
    """Short prompt block — first in **idea goal**, not full worker prompt."""
    warnings = validate_contract(contract)
    allowed = ", ".join(contract.get("allowed_prefixes") or []) or "(none)"
    forbidden = ", ".join(contract.get("forbidden_prefixes") or []) or "(none)"
    non_goals = "; ".join(contract.get("non_goals") or [])[:500]
    mission = _bound(contract.get("mission"), 300)
    iid = _bound(contract.get("idea_id"), 120)
    lines = [
        DNA_TAG_OPEN,
        f"schema: {SCHEMA}",
        f"idea_id: {iid}",
        f"mission: {mission}",
        f"allowed_prefixes: {allowed}",
        f"forbidden_prefixes: {forbidden}",
        f"non_goals: {non_goals}",
        f"max_files (advisory): {contract.get('max_files')}",
        "rules:",
        "- Prefer edits under allowed_prefixes only.",
        "- Never touch forbidden_prefixes or secrets.",
        "- This block is advisory scope DNA for this idea (not a sandbox).",
        "- Contract is first in the idea goal; worker may add its own preamble after.",
    ]
    if warnings:
        lines.append(f"contract_warnings: {'; '.join(warnings)[:300]}")
    lines.append(DNA_TAG_CLOSE)
    blob = "\n".join(lines) + "\n"
    if len(blob) > MAX_DNA_CHARS:
        blob = blob[: MAX_DNA_CHARS - 20] + f"\n{DNA_TAG_CLOSE}\n"
    return blob


def contract_digest(contract: dict[str, Any]) -> str:
    raw = json.dumps(contract, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def write_contract(pack_dir: Path | str, contract: dict[str, Any]) -> Path:
    """Write CONTRACT.json under pack_dir (fixed name only)."""
    base = Path(pack_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / "CONTRACT.json"
    payload = dict(contract)
    payload["digest"] = contract_digest(contract)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def prepend_dna_to_goal(goal: str, contract: dict[str, Any]) -> str:
    dna = format_dna_block(contract)
    g = goal or ""
    if DNA_TAG_OPEN in g:
        return g  # already injected
    return dna + "\n" + g
