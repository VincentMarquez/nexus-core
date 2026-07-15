"""Skill pack catalog: list / validate / generate multi-harness artifacts.

First-apply slice (docs/LATEST_IMPROVE_PLAN.md P2.1):

  single Markdown source (SKILL.md) + manifest.json
    → validate structure
    → emit idiomatic stubs for grok / cursor / claude / codex / local
    → drift-check generated vs source

Patterns (shape only, not vendored trees):
- wshobson/agents — one source → many harness adapters + validate/smoke
- 2389-research/claude-plugins — install-template tests
- arXiv 2606.20023 — privilege labels on tools/packs (least-privilege signal)
- mission-control — CLI/MCP parity for ops surfaces
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .persist import atomic_write_json, atomic_write_text

SCHEMA_VERSION = "nexus.skillpacks/v1"
DEFAULT_PACKS_DIR = "skillpacks"

# Harness ids we emit. Keep small and portable.
SUPPORTED_HARNESSES: tuple[str, ...] = (
    "grok",
    "cursor",
    "claude",
    "codex",
    "local",
)

# Privilege ladder (arXiv 2606.20023): lower is safer default.
PRIVILEGE_LEVELS: tuple[str, ...] = ("read", "write", "ops", "admin")
PRIVILEGE_RANK = {p: i for i, p in enumerate(PRIVILEGE_LEVELS)}

MANIFEST_REQUIRED = ("id", "version", "name")
SKILL_REQUIRED_SECTIONS = ("When to use", "Commands", "Rules", "Success")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class SkillpackError(ValueError):
    """Structural or generation error for a skill pack."""


@dataclass
class Finding:
    severity: str  # error | warning | info
    pack_id: str
    path: str
    message: str
    remediation: str = ""

    def render(self) -> str:
        tail = f"  fix: {self.remediation}" if self.remediation else ""
        return f"[{self.severity}] {self.pack_id}: {self.path}: {self.message}{tail}"


@dataclass
class ValidateReport:
    schema: str = SCHEMA_VERSION
    pack_id: str = ""
    ok: bool = True
    findings: list[Finding] = field(default_factory=list)

    def add(
        self,
        severity: str,
        pack_id: str,
        path: str,
        message: str,
        remediation: str = "",
    ) -> None:
        self.findings.append(
            Finding(
                severity=severity,
                pack_id=pack_id,
                path=path,
                message=message,
                remediation=remediation,
            )
        )
        if severity == "error":
            self.ok = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "pack_id": self.pack_id,
            "ok": self.ok,
            "errors": sum(1 for f in self.findings if f.severity == "error"),
            "warnings": sum(1 for f in self.findings if f.severity == "warning"),
            "findings": [asdict(f) for f in self.findings],
        }


@dataclass
class PackInfo:
    id: str
    version: str
    name: str
    path: str
    tags: list[str] = field(default_factory=list)
    harnesses: list[str] = field(default_factory=list)
    privilege: str = "read"
    entrypoints: dict[str, str] = field(default_factory=dict)
    skill_chars: int = 0
    valid: Optional[bool] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def packs_root(workdir: Path | str, packs_dir: str = DEFAULT_PACKS_DIR) -> Path:
    return Path(workdir).resolve() / packs_dir


def list_pack_dirs(workdir: Path | str, packs_dir: str = DEFAULT_PACKS_DIR) -> list[Path]:
    root = packs_root(workdir, packs_dir)
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and (p / "manifest.json").is_file():
            out.append(p)
    return out


def load_manifest(pack_dir: Path) -> dict[str, Any]:
    path = pack_dir / "manifest.json"
    if not path.is_file():
        raise SkillpackError(f"missing manifest.json in {pack_dir}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SkillpackError(f"invalid JSON in {path}: {e}") from e
    if not isinstance(data, dict):
        raise SkillpackError(f"manifest must be object: {path}")
    return data


def load_skill_md(pack_dir: Path) -> str:
    path = pack_dir / "SKILL.md"
    if not path.is_file():
        raise SkillpackError(f"missing SKILL.md in {pack_dir}")
    return path.read_text(encoding="utf-8")


def _norm_privilege(raw: Any) -> str:
    if raw is None or raw == "":
        return "read"
    s = str(raw).strip().lower()
    if s not in PRIVILEGE_RANK:
        raise SkillpackError(
            f"privilege must be one of {list(PRIVILEGE_LEVELS)}, got {raw!r}"
        )
    return s


def pack_info(pack_dir: Path, *, validate: bool = False) -> PackInfo:
    man = load_manifest(pack_dir)
    skill_chars = 0
    skill_path = pack_dir / "SKILL.md"
    if skill_path.is_file():
        skill_chars = len(skill_path.read_text(encoding="utf-8"))
    harnesses = man.get("harnesses") or list(SUPPORTED_HARNESSES)
    if not isinstance(harnesses, list):
        harnesses = list(SUPPORTED_HARNESSES)
    tags = man.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    entrypoints = man.get("entrypoints") or {}
    if not isinstance(entrypoints, dict):
        entrypoints = {}
    try:
        priv = _norm_privilege(man.get("privilege"))
    except SkillpackError:
        priv = "read"
    info = PackInfo(
        id=str(man.get("id") or pack_dir.name),
        version=str(man.get("version") or ""),
        name=str(man.get("name") or ""),
        path=str(pack_dir),
        tags=[str(t) for t in tags],
        harnesses=[str(h) for h in harnesses],
        privilege=priv,
        entrypoints={str(k): str(v) for k, v in entrypoints.items()},
        skill_chars=skill_chars,
    )
    if validate:
        rep = validate_pack(pack_dir)
        info.valid = rep.ok
    return info


def list_packs(
    workdir: Path | str,
    *,
    packs_dir: str = DEFAULT_PACKS_DIR,
    validate: bool = False,
    max_privilege: Optional[str] = None,
) -> list[PackInfo]:
    """List skill packs under workdir/skillpacks.

    If *max_privilege* is set, filter out packs above that level
    (least-privilege selection; arXiv 2606.20023).
    """
    cap = None
    if max_privilege is not None:
        cap = PRIVILEGE_RANK[_norm_privilege(max_privilege)]
    rows: list[PackInfo] = []
    for d in list_pack_dirs(workdir, packs_dir):
        try:
            info = pack_info(d, validate=validate)
        except SkillpackError:
            # Still surface broken packs as minimal info
            info = PackInfo(
                id=d.name,
                version="",
                name=d.name,
                path=str(d),
                valid=False if validate else None,
            )
        if cap is not None and PRIVILEGE_RANK.get(info.privilege, 0) > cap:
            continue
        rows.append(info)
    return rows


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def _heading_titles(md: str) -> set[str]:
    titles: set[str] = set()
    for line in md.splitlines():
        m = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if m:
            titles.add(m.group(1).strip())
    return titles


def validate_pack(pack_dir: Path | str) -> ValidateReport:
    """Structural validation of one pack (source of truth, not generated)."""
    pack_dir = Path(pack_dir)
    rep = ValidateReport(pack_id=pack_dir.name)

    man_path = pack_dir / "manifest.json"
    skill_path = pack_dir / "SKILL.md"
    if not man_path.is_file():
        rep.add(
            "error",
            pack_dir.name,
            "manifest.json",
            "missing manifest.json",
            "Add manifest.json with id/version/name.",
        )
        return rep
    if not skill_path.is_file():
        rep.add(
            "error",
            pack_dir.name,
            "SKILL.md",
            "missing SKILL.md (source of truth)",
            "Add SKILL.md with When to use / Commands / Rules / Success.",
        )

    try:
        man = load_manifest(pack_dir)
    except SkillpackError as e:
        rep.add("error", pack_dir.name, "manifest.json", str(e), "Fix JSON syntax.")
        return rep

    pack_id = str(man.get("id") or "")
    rep.pack_id = pack_id or pack_dir.name

    for key in MANIFEST_REQUIRED:
        val = man.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            rep.add(
                "error",
                rep.pack_id,
                "manifest.json",
                f"missing required field `{key}`",
                f"Set `{key}` in manifest.json.",
            )

    if pack_id and not _SLUG_RE.match(pack_id):
        rep.add(
            "error",
            rep.pack_id,
            "manifest.json",
            f"id must be slug-like (a-z0-9._-), got {pack_id!r}",
            "Use lowercase slug e.g. durable-operator.",
        )
    if pack_id and pack_id != pack_dir.name:
        rep.add(
            "warning",
            rep.pack_id,
            "manifest.json",
            f"id {pack_id!r} != directory name {pack_dir.name!r}",
            "Rename folder or set id to match directory.",
        )

    # Privilege
    try:
        priv = _norm_privilege(man.get("privilege"))
    except SkillpackError as e:
        rep.add(
            "error",
            rep.pack_id,
            "manifest.json",
            str(e),
            f"Set privilege to one of {list(PRIVILEGE_LEVELS)}.",
        )
        priv = "read"
    else:
        if "privilege" not in man:
            rep.add(
                "info",
                rep.pack_id,
                "manifest.json",
                "privilege omitted; defaulting to read",
                "Set privilege explicitly for least-privilege tooling.",
            )

    # Harnesses
    harnesses = man.get("harnesses")
    if harnesses is None:
        rep.add(
            "info",
            rep.pack_id,
            "manifest.json",
            "harnesses omitted; all supported harnesses assumed",
            f"Set harnesses to a subset of {list(SUPPORTED_HARNESSES)}.",
        )
        harnesses = list(SUPPORTED_HARNESSES)
    elif not isinstance(harnesses, list) or not harnesses:
        rep.add(
            "error",
            rep.pack_id,
            "manifest.json",
            "harnesses must be a non-empty list",
            f"Example: {list(SUPPORTED_HARNESSES)}",
        )
        harnesses = []
    else:
        for h in harnesses:
            if str(h) not in SUPPORTED_HARNESSES:
                rep.add(
                    "warning",
                    rep.pack_id,
                    "manifest.json",
                    f"unknown harness {h!r}",
                    f"Supported: {list(SUPPORTED_HARNESSES)}",
                )

    # Entrypoints must exist when relative
    entrypoints = man.get("entrypoints") or {}
    if entrypoints and not isinstance(entrypoints, dict):
        rep.add(
            "error",
            rep.pack_id,
            "manifest.json",
            "entrypoints must be an object",
            'Example: {"skill": "SKILL.md", "demo": "examples/demo.py"}',
        )
        entrypoints = {}
    root = pack_dir.parent.parent  # workdir ≈ skillpacks parent
    # Prefer pack-relative first, then repo-root relative
    for key, rel in entrypoints.items():
        rel_s = str(rel)
        if key == "skill":
            cand = pack_dir / Path(rel_s).name if Path(rel_s).name == "SKILL.md" else pack_dir / rel_s
            if not cand.is_file() and not (pack_dir / "SKILL.md").is_file():
                rep.add(
                    "error",
                    rep.pack_id,
                    f"entrypoints.{key}",
                    f"skill entrypoint missing: {rel_s}",
                    "Point skill to SKILL.md inside the pack.",
                )
            continue
        # repo-root relative paths for demos/cookbooks
        cand_root = root / rel_s
        cand_pack = pack_dir / rel_s
        if not cand_root.is_file() and not cand_pack.is_file():
            # warning only — demo paths may be optional in isolated tests
            rep.add(
                "warning",
                rep.pack_id,
                f"entrypoints.{key}",
                f"entrypoint path not found: {rel_s}",
                "Fix path or remove entrypoint key.",
            )

    # SKILL.md sections
    if skill_path.is_file():
        md = skill_path.read_text(encoding="utf-8")
        if len(md.strip()) < 40:
            rep.add(
                "error",
                rep.pack_id,
                "SKILL.md",
                "SKILL.md too short to be useful",
                "Document When to use, Commands, Rules, Success.",
            )
        titles = _heading_titles(md)
        # Allow partial match (case-insensitive)
        lower_titles = {t.lower() for t in titles}
        for sec in SKILL_REQUIRED_SECTIONS:
            if sec.lower() not in lower_titles:
                # also accept "## Skill: …" only as info if missing
                rep.add(
                    "warning",
                    rep.pack_id,
                    "SKILL.md",
                    f"recommended section missing: {sec}",
                    f"Add a `## {sec}` heading.",
                )
        if "```" not in md:
            rep.add(
                "info",
                rep.pack_id,
                "SKILL.md",
                "no fenced code block (commands often benefit from one)",
                "Wrap CLI examples in ```bash fences.",
            )

    # Privilege tag consistency
    tags = man.get("tags") or []
    if isinstance(tags, list) and priv != "read" and priv not in [str(t) for t in tags]:
        rep.add(
            "info",
            rep.pack_id,
            "manifest.json",
            f"privilege={priv} not reflected in tags",
            f"Add tag {priv!r} for discoverability.",
        )

    return rep


def validate_all(
    workdir: Path | str,
    *,
    packs_dir: str = DEFAULT_PACKS_DIR,
) -> dict[str, Any]:
    reports = [validate_pack(d) for d in list_pack_dirs(workdir, packs_dir)]
    ok = all(r.ok for r in reports) if reports else True
    return {
        "schema": SCHEMA_VERSION,
        "ok": ok,
        "count": len(reports),
        "packs": [r.to_dict() for r in reports],
        "errors": sum(r.to_dict()["errors"] for r in reports),
        "warnings": sum(r.to_dict()["warnings"] for r in reports),
    }


# ---------------------------------------------------------------------------
# Generate multi-harness artifacts
# ---------------------------------------------------------------------------


def _harness_paths(pack_id: str, harness: str) -> dict[str, str]:
    """Relative paths under generated/ for each harness artifact."""
    if harness == "claude":
        return {
            "skill": f"claude/skills/{pack_id}/SKILL.md",
            "meta": f"claude/skills/{pack_id}/manifest.json",
        }
    if harness == "cursor":
        return {
            "rule": f"cursor/rules/{pack_id}.mdc",
            "meta": f"cursor/skills/{pack_id}.json",
        }
    if harness == "codex":
        return {
            "agents": f"codex/skills/{pack_id}.md",
            "meta": f"codex/skills/{pack_id}.json",
        }
    if harness == "grok":
        return {
            "skill": f"grok/skills/{pack_id}/SKILL.md",
            "meta": f"grok/skills/{pack_id}/manifest.json",
        }
    if harness == "local":
        return {
            "skill": f"local/{pack_id}/SKILL.md",
            "meta": f"local/{pack_id}/manifest.json",
        }
    raise SkillpackError(f"unknown harness: {harness}")


def _wrap_cursor_mdc(pack: PackInfo, skill_md: str) -> str:
    front = (
        "---\n"
        f"description: {pack.name}\n"
        f"globs:\n"
        f"alwaysApply: false\n"
        f"nexus_pack: {pack.id}\n"
        f"privilege: {pack.privilege}\n"
        "---\n\n"
    )
    return front + skill_md.strip() + "\n"


def _wrap_codex(pack: PackInfo, skill_md: str) -> str:
    return (
        f"# Skill: {pack.name} (`{pack.id}`)\n\n"
        f"> privilege: `{pack.privilege}` · version: `{pack.version}`\n\n"
        f"{skill_md.strip()}\n"
    )


def _meta_blob(pack: PackInfo, harness: str, *, source_sha: str = "") -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "pack_id": pack.id,
        "version": pack.version,
        "name": pack.name,
        "harness": harness,
        "privilege": pack.privilege,
        "tags": list(pack.tags),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "skillpacks/" + pack.id,
        "source_skill_chars": pack.skill_chars,
    }


def generate_root(
    workdir: Path | str,
    *,
    packs_dir: str = DEFAULT_PACKS_DIR,
) -> Path:
    """Default output root: .nexus_state/generated_skillpacks (gitignored)."""
    return Path(workdir).resolve() / ".nexus_state" / "generated_skillpacks"


def generate_pack(
    pack_dir: Path | str,
    *,
    out_root: Path | str,
    harnesses: Optional[Iterable[str]] = None,
    clean: bool = False,
) -> dict[str, Any]:
    """Emit multi-harness artifacts from one pack. Returns emit report."""
    pack_dir = Path(pack_dir)
    out_root = Path(out_root).resolve()
    info = pack_info(pack_dir)
    # Fail closed on invalid source
    rep = validate_pack(pack_dir)
    if not rep.ok:
        raise SkillpackError(
            f"refuse to generate invalid pack {info.id}: "
            + "; ".join(f.message for f in rep.findings if f.severity == "error")
        )

    skill_md = load_skill_md(pack_dir)
    man = load_manifest(pack_dir)
    want = list(harnesses) if harnesses is not None else list(
        man.get("harnesses") or SUPPORTED_HARNESSES
    )
    for h in want:
        if h not in SUPPORTED_HARNESSES:
            raise SkillpackError(f"unsupported harness: {h}")

    written: list[str] = []
    for h in want:
        paths = _harness_paths(info.id, h)
        if clean:
            for rel in paths.values():
                p = out_root / rel
                if p.is_file():
                    p.unlink()
        for kind, rel in paths.items():
            target = out_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if kind in {"skill", "agents", "rule"}:
                if h == "cursor" and kind == "rule":
                    body = _wrap_cursor_mdc(info, skill_md)
                elif h == "codex" and kind == "agents":
                    body = _wrap_codex(info, skill_md)
                else:
                    # claude / grok / local — keep SKILL.md body + short header
                    body = (
                        f"<!-- generated by nexus.skillpacks from skillpacks/{info.id} "
                        f"harness={h} privilege={info.privilege} -->\n\n"
                        + skill_md.strip()
                        + "\n"
                    )
                atomic_write_text(target, body)
            else:
                atomic_write_json(target, _meta_blob(info, h))
            written.append(str(target.relative_to(out_root)))

    return {
        "schema": SCHEMA_VERSION,
        "pack_id": info.id,
        "version": info.version,
        "privilege": info.privilege,
        "harnesses": want,
        "out_root": str(out_root),
        "written": written,
        "count": len(written),
    }


def generate_all(
    workdir: Path | str,
    *,
    packs_dir: str = DEFAULT_PACKS_DIR,
    out_root: Optional[Path | str] = None,
    harnesses: Optional[Iterable[str]] = None,
    clean: bool = False,
    max_privilege: Optional[str] = None,
) -> dict[str, Any]:
    workdir = Path(workdir).resolve()
    out = Path(out_root) if out_root else generate_root(workdir)
    packs = list_packs(workdir, packs_dir=packs_dir, max_privilege=max_privilege)
    results = []
    errors = []
    for p in packs:
        try:
            results.append(
                generate_pack(
                    Path(p.path),
                    out_root=out,
                    harnesses=harnesses,
                    clean=clean,
                )
            )
        except SkillpackError as e:
            errors.append({"pack_id": p.id, "error": str(e)})
    return {
        "schema": SCHEMA_VERSION,
        "ok": not errors,
        "out_root": str(out),
        "generated": results,
        "errors": errors,
        "count": len(results),
    }


# ---------------------------------------------------------------------------
# Drift detection (source vs generated)
# ---------------------------------------------------------------------------


def drift_check(
    workdir: Path | str,
    *,
    packs_dir: str = DEFAULT_PACKS_DIR,
    out_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Compare source packs to generated artifacts; report missing/stale."""
    workdir = Path(workdir).resolve()
    out = Path(out_root) if out_root else generate_root(workdir)
    findings: list[dict[str, Any]] = []
    packs = list_packs(workdir, packs_dir=packs_dir)
    for p in packs:
        man = load_manifest(Path(p.path))
        harnesses = list(man.get("harnesses") or SUPPORTED_HARNESSES)
        skill = load_skill_md(Path(p.path))
        for h in harnesses:
            if h not in SUPPORTED_HARNESSES:
                continue
            paths = _harness_paths(p.id, h)
            for kind, rel in paths.items():
                target = out / rel
                if not target.is_file():
                    findings.append(
                        {
                            "severity": "error",
                            "pack_id": p.id,
                            "harness": h,
                            "path": rel,
                            "message": "generated artifact missing",
                            "remediation": "Run: nexus skillpacks generate",
                        }
                    )
                    continue
                if kind in {"skill", "agents", "rule"}:
                    body = target.read_text(encoding="utf-8")
                    # Source body must appear (allow wrappers)
                    core = skill.strip()
                    if core and core not in body and not _loosely_contains(body, core):
                        findings.append(
                            {
                                "severity": "warning",
                                "pack_id": p.id,
                                "harness": h,
                                "path": rel,
                                "message": "generated content drifts from SKILL.md",
                                "remediation": "Re-run: nexus skillpacks generate --clean",
                            }
                        )
                else:
                    try:
                        meta = json.loads(target.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        findings.append(
                            {
                                "severity": "error",
                                "pack_id": p.id,
                                "harness": h,
                                "path": rel,
                                "message": "meta JSON unreadable",
                                "remediation": "Regenerate pack artifacts.",
                            }
                        )
                        continue
                    if str(meta.get("version") or "") != p.version:
                        findings.append(
                            {
                                "severity": "warning",
                                "pack_id": p.id,
                                "harness": h,
                                "path": rel,
                                "message": (
                                    f"version drift meta={meta.get('version')!r} "
                                    f"source={p.version!r}"
                                ),
                                "remediation": "Re-run: nexus skillpacks generate",
                            }
                        )
                    if str(meta.get("privilege") or "") != p.privilege:
                        findings.append(
                            {
                                "severity": "warning",
                                "pack_id": p.id,
                                "harness": h,
                                "path": rel,
                                "message": "privilege drift vs source manifest",
                                "remediation": "Re-run generate after privilege change.",
                            }
                        )

    errors = sum(1 for f in findings if f["severity"] == "error")
    warnings = sum(1 for f in findings if f["severity"] == "warning")
    return {
        "schema": SCHEMA_VERSION,
        "ok": errors == 0,
        "out_root": str(out),
        "pack_count": len(packs),
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
    }


def _loosely_contains(body: str, core: str) -> bool:
    """True if most non-empty lines of core appear in body (wrapper tolerance)."""
    lines = [ln.strip() for ln in core.splitlines() if ln.strip()]
    if not lines:
        return True
    hits = sum(1 for ln in lines if ln in body)
    return hits >= max(1, int(0.7 * len(lines)))


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


def format_list(rows: list[PackInfo]) -> str:
    if not rows:
        return "(no skill packs found)"
    lines = [
        f"{'ID':<24} {'VER':<8} {'PRIV':<6} {'HARNESSES':<28} NAME",
        "-" * 80,
    ]
    for r in rows:
        h = ",".join(r.harnesses[:4])
        if len(r.harnesses) > 4:
            h += "…"
        lines.append(
            f"{r.id:<24} {r.version:<8} {r.privilege:<6} {h:<28} {r.name}"
        )
    return "\n".join(lines)


def format_validate(report: dict[str, Any]) -> str:
    lines = [
        f"skillpacks validate  ok={report.get('ok')}  "
        f"packs={report.get('count')}  "
        f"errors={report.get('errors')}  warnings={report.get('warnings')}"
    ]
    for p in report.get("packs") or []:
        mark = "OK" if p.get("ok") else "FAIL"
        lines.append(f"  [{mark}] {p.get('pack_id')}")
        for f in p.get("findings") or []:
            if f.get("severity") == "info":
                continue
            rem = f"  fix: {f['remediation']}" if f.get("remediation") else ""
            lines.append(
                f"    [{f.get('severity')}] {f.get('path')}: {f.get('message')}{rem}"
            )
    return "\n".join(lines)


def format_generate(report: dict[str, Any]) -> str:
    lines = [
        f"skillpacks generate  ok={report.get('ok')}  "
        f"count={report.get('count')}  out={report.get('out_root')}"
    ]
    for g in report.get("generated") or []:
        lines.append(
            f"  {g.get('pack_id')}: {g.get('count')} files "
            f"harnesses={','.join(g.get('harnesses') or [])}"
        )
    for e in report.get("errors") or []:
        lines.append(f"  ERROR {e.get('pack_id')}: {e.get('error')}")
    return "\n".join(lines)


def format_drift(report: dict[str, Any]) -> str:
    lines = [
        f"skillpacks drift  ok={report.get('ok')}  "
        f"errors={report.get('errors')}  warnings={report.get('warnings')}  "
        f"packs={report.get('pack_count')}"
    ]
    for f in report.get("findings") or []:
        rem = f"  fix: {f['remediation']}" if f.get("remediation") else ""
        lines.append(
            f"  [{f.get('severity')}] {f.get('pack_id')}/{f.get('harness')}: "
            f"{f.get('message')}{rem}"
        )
    if not report.get("findings"):
        lines.append("  (no drift)")
    return "\n".join(lines)
