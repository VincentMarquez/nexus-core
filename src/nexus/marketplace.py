"""Plugin marketplace catalog: discover / validate / collisions / export / generate.

First-apply + follow-on slice (docs/LATEST_IMPROVE_PLAN.md — wshobson/agents):

  plugins/<id>/
    plugin.json | .nexus-plugin/plugin.json | .claude-plugin/plugin.json
    agents/*.md
    commands/*.md
    skills/<skill-id>/SKILL.md
      → list + structural validate (remediation hints)
      → cross-plugin name collision report
      → multi-harness marketplace registry export (JSON stubs)
      → per-plugin harness stubs (component index, no body rewrite)
      → multi-harness adapters (generate): rewrite frontmatter, command→skill,
        skill body cap split (Codex 8 KiB), model alias map
      → validate_generated structural gate on adapter trees
      → round_trip: generate → source/expected count integrity → validate
      → optional thin index of skillpacks/ as single-skill plugins
      → self_check gate (validate + collisions + skillpack + garden)
      → harness capability matrix + portability score (graceful degrade)

Patterns (shape only, not vendored trees):
- wshobson/agents — single-source Markdown plugin marketplace + multi-harness
  adapters (tools/adapters/*) + validate/collision gates + capabilities matrix
  + round-trip integrity (tools/tests/test_round_trip.py shape)
- skillpacks.py — privilege ladder + Finding/remediation style (in-repo)
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .persist import atomic_write_json, atomic_write_text

SCHEMA_VERSION = "nexus.marketplace/v1"
DEFAULT_PLUGINS_DIR = "plugins"
DEFAULT_SKILLPACKS_DIR = "skillpacks"

# Harness ids for marketplace registry export (broader than skillpacks stubs).
SUPPORTED_HARNESSES: tuple[str, ...] = (
    "claude",
    "cursor",
    "codex",
    "opencode",
    "gemini",
    "copilot",
    "grok",
    "local",
)

PRIVILEGE_LEVELS: tuple[str, ...] = ("read", "write", "ops", "admin")
PRIVILEGE_RANK = {p: i for i, p in enumerate(PRIVILEGE_LEVELS)}

PLUGIN_REQUIRED = ("name", "version")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_FRONTMATTER_RE = re.compile(r"\A---\n(?P<fm>.*?)\n---", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*(?P<name>.+?)\s*$", re.MULTILINE)

# Progressive-disclosure / harness caps (wshobson capabilities shape).
_NO_BODY_CAP = 0
CODEX_SKILL_BODY_MAX_BYTES = 8 * 1024  # Codex hard skill body limit
CONTEXT_FILE_MAX_LINES = 150


class MarketplaceError(ValueError):
    """Structural or export error for the plugin marketplace."""


@dataclass(frozen=True)
class HarnessCapability:
    """One row of the multi-harness capability matrix.

    Shape from wshobson/agents ``tools/adapters/capabilities.py`` (pattern only).
    Consumed by portability scoring, garden drift, and docs — not a full adapter.
    """

    harness_id: str
    display_name: str
    skills_native: bool = True
    agents_native: bool = True
    commands_native: bool = True
    plugin_marketplace: bool = True
    skill_body_max_bytes: int = _NO_BODY_CAP  # 0 = no hard cap
    context_file_name: str | None = "AGENTS.md"
    context_file_max_lines: int = CONTEXT_FILE_MAX_LINES
    # When commands_native is False, adapters map commands → skills.
    commands_map_to_skills: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Single source of truth for supported harness capabilities (NEXUS ids).
CAPABILITIES: dict[str, HarnessCapability] = {
    "claude": HarnessCapability(
        harness_id="claude",
        display_name="Claude Code",
        skills_native=True,
        agents_native=True,
        commands_native=True,
        plugin_marketplace=True,
        skill_body_max_bytes=_NO_BODY_CAP,
        context_file_name="CLAUDE.md",
        notes="Native marketplace + agents/skills/commands; source-friendly layout.",
    ),
    "cursor": HarnessCapability(
        harness_id="cursor",
        display_name="Cursor",
        skills_native=True,
        agents_native=True,
        commands_native=True,
        plugin_marketplace=True,
        skill_body_max_bytes=_NO_BODY_CAP,
        context_file_name="AGENTS.md",
        notes="Marketplace + rules; often reuses Claude-layout skills/agents.",
    ),
    "codex": HarnessCapability(
        harness_id="codex",
        display_name="OpenAI Codex CLI",
        skills_native=True,
        agents_native=True,
        commands_native=False,
        plugin_marketplace=False,
        skill_body_max_bytes=CODEX_SKILL_BODY_MAX_BYTES,
        context_file_name="AGENTS.md",
        commands_map_to_skills=True,
        notes="8 KiB skill body hard cap; commands map to skills.",
    ),
    "opencode": HarnessCapability(
        harness_id="opencode",
        display_name="OpenCode",
        skills_native=True,
        agents_native=True,
        commands_native=True,
        plugin_marketplace=False,
        skill_body_max_bytes=_NO_BODY_CAP,
        context_file_name="AGENTS.md",
        notes="Emits .opencode agents/commands/skills; no marketplace.json.",
    ),
    "gemini": HarnessCapability(
        harness_id="gemini",
        display_name="Gemini CLI",
        skills_native=True,
        agents_native=True,
        commands_native=True,
        plugin_marketplace=False,
        skill_body_max_bytes=_NO_BODY_CAP,
        context_file_name="GEMINI.md",
        notes="Native skills + subagents; TOML commands at extension root.",
    ),
    "copilot": HarnessCapability(
        harness_id="copilot",
        display_name="GitHub Copilot",
        skills_native=True,
        agents_native=True,
        commands_native=False,
        plugin_marketplace=False,
        skill_body_max_bytes=_NO_BODY_CAP,
        context_file_name="AGENTS.md",
        commands_map_to_skills=True,
        notes="Commands emitted as invocable skills; agent profiles under .copilot/.",
    ),
    "grok": HarnessCapability(
        harness_id="grok",
        display_name="Grok / xAI CLI",
        skills_native=True,
        agents_native=True,
        commands_native=True,
        plugin_marketplace=False,
        skill_body_max_bytes=_NO_BODY_CAP,
        context_file_name="AGENTS.md",
        notes="NEXUS-native harness; skillpacks generate full bodies.",
    ),
    "local": HarnessCapability(
        harness_id="local",
        display_name="Local / offline",
        skills_native=True,
        agents_native=True,
        commands_native=True,
        plugin_marketplace=False,
        skill_body_max_bytes=_NO_BODY_CAP,
        context_file_name="AGENTS.md",
        notes="Offline index + stubs; no remote marketplace install.",
    ),
}


def capability(harness: str) -> HarnessCapability:
    """Return capability row for a harness id (raises on unknown)."""
    key = str(harness or "").strip().lower()
    if key not in CAPABILITIES:
        raise MarketplaceError(
            f"unknown harness capability: {harness!r}; "
            f"known={list(CAPABILITIES)}"
        )
    return CAPABILITIES[key]


def list_capabilities(
    harnesses: Optional[Iterable[str]] = None,
) -> list[HarnessCapability]:
    """List capability rows (default: all SUPPORTED_HARNESSES order)."""
    want = list(harnesses) if harnesses is not None else list(SUPPORTED_HARNESSES)
    out: list[HarnessCapability] = []
    for h in want:
        if h not in CAPABILITIES:
            raise MarketplaceError(f"unknown harness capability: {h}")
        out.append(CAPABILITIES[h])
    return out


def capabilities_matrix(
    harnesses: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """JSON-serializable capability matrix for CLI/MCP/docs."""
    rows = list_capabilities(harnesses)
    return {
        "schema": SCHEMA_VERSION,
        "kind": "harness_capabilities",
        "count": len(rows),
        "codex_skill_body_max_bytes": CODEX_SKILL_BODY_MAX_BYTES,
        "harnesses": [r.to_dict() for r in rows],
    }


@dataclass
class Finding:
    severity: str  # error | warning | info
    plugin_id: str
    path: str
    message: str
    remediation: str = ""

    def render(self) -> str:
        tail = f"  fix: {self.remediation}" if self.remediation else ""
        return f"[{self.severity}] {self.plugin_id}: {self.path}: {self.message}{tail}"


@dataclass
class ValidateReport:
    schema: str = SCHEMA_VERSION
    plugin_id: str = ""
    ok: bool = True
    findings: list[Finding] = field(default_factory=list)

    def add(
        self,
        severity: str,
        plugin_id: str,
        path: str,
        message: str,
        remediation: str = "",
    ) -> None:
        self.findings.append(
            Finding(
                severity=severity,
                plugin_id=plugin_id,
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
            "plugin_id": self.plugin_id,
            "ok": self.ok,
            "errors": sum(1 for f in self.findings if f.severity == "error"),
            "warnings": sum(1 for f in self.findings if f.severity == "warning"),
            "findings": [asdict(f) for f in self.findings],
        }


@dataclass
class ComponentRef:
    kind: str  # agent | skill | command
    name: str
    path: str
    plugin_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PluginInfo:
    id: str
    name: str
    version: str
    path: str
    description: str = ""
    category: str = ""
    privilege: str = "read"
    tags: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    valid: Optional[bool] = None
    origin: str = "plugin"  # plugin | skillpack
    source: str = ""  # relative e.g. plugins/foo or skillpacks/bar

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def component_count(self) -> int:
        return len(self.agents) + len(self.skills) + len(self.commands)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def plugins_root(workdir: Path | str, plugins_dir: str = DEFAULT_PLUGINS_DIR) -> Path:
    return Path(workdir).resolve() / plugins_dir


def skillpacks_root(
    workdir: Path | str, packs_dir: str = DEFAULT_SKILLPACKS_DIR
) -> Path:
    return Path(workdir).resolve() / packs_dir


def list_plugin_dirs(
    workdir: Path | str, plugins_dir: str = DEFAULT_PLUGINS_DIR
) -> list[Path]:
    root = plugins_root(workdir, plugins_dir)
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        if _plugin_manifest_path(p) is not None:
            out.append(p)
    return out


def _plugin_manifest_path(plugin_dir: Path) -> Optional[Path]:
    """Resolve plugin.json from common locations (nexus / claude-plugin layout)."""
    candidates = (
        plugin_dir / "plugin.json",
        plugin_dir / ".nexus-plugin" / "plugin.json",
        plugin_dir / ".claude-plugin" / "plugin.json",
    )
    for c in candidates:
        if c.is_file():
            return c
    return None


def load_plugin_manifest(plugin_dir: Path) -> dict[str, Any]:
    path = _plugin_manifest_path(plugin_dir)
    if path is None:
        raise MarketplaceError(f"missing plugin.json in {plugin_dir}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise MarketplaceError(f"invalid JSON in {path}: {e}") from e
    if not isinstance(data, dict):
        raise MarketplaceError(f"plugin.json must be object: {path}")
    return data


def _norm_privilege(raw: Any) -> str:
    if raw is None or raw == "":
        return "read"
    s = str(raw).strip().lower()
    if s not in PRIVILEGE_RANK:
        raise MarketplaceError(
            f"privilege must be one of {list(PRIVILEGE_LEVELS)}, got {raw!r}"
        )
    return s


def _stem_name(path: Path) -> str:
    return path.stem


def _frontmatter_name(path: Path) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except OSError:
        return None
    m = _FRONTMATTER_RE.search(text)
    if not m:
        return None
    nm = _NAME_RE.search(m.group("fm"))
    if not nm:
        return None
    raw = nm.group("name").split("#", 1)[0].strip().strip("\"'")
    return raw or None


def discover_components(plugin_dir: Path, plugin_id: str) -> list[ComponentRef]:
    """Discover agents, skills, and commands under a plugin directory."""
    comps: list[ComponentRef] = []

    agents_dir = plugin_dir / "agents"
    if agents_dir.is_dir():
        for p in sorted(agents_dir.glob("*.md")):
            name = _frontmatter_name(p) or _stem_name(p)
            comps.append(
                ComponentRef(
                    kind="agent",
                    name=name,
                    path=str(p.relative_to(plugin_dir)),
                    plugin_id=plugin_id,
                )
            )

    commands_dir = plugin_dir / "commands"
    if commands_dir.is_dir():
        for p in sorted(commands_dir.glob("*.md")):
            name = _frontmatter_name(p) or _stem_name(p)
            comps.append(
                ComponentRef(
                    kind="command",
                    name=name,
                    path=str(p.relative_to(plugin_dir)),
                    plugin_id=plugin_id,
                )
            )

    skills_dir = plugin_dir / "skills"
    if skills_dir.is_dir():
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            skill_md = d / "SKILL.md"
            if skill_md.is_file():
                name = _frontmatter_name(skill_md) or d.name
                comps.append(
                    ComponentRef(
                        kind="skill",
                        name=name,
                        path=str(skill_md.relative_to(plugin_dir)),
                        plugin_id=plugin_id,
                    )
                )
            else:
                # bare skill dir without SKILL.md still recorded for validation
                comps.append(
                    ComponentRef(
                        kind="skill",
                        name=d.name,
                        path=str(d.relative_to(plugin_dir)),
                        plugin_id=plugin_id,
                    )
                )

    # Flat single-skill layout (compat with skillpack-shaped plugins)
    if (plugin_dir / "SKILL.md").is_file() and not any(
        c.kind == "skill" for c in comps
    ):
        name = _frontmatter_name(plugin_dir / "SKILL.md") or plugin_id
        comps.append(
            ComponentRef(
                kind="skill",
                name=name,
                path="SKILL.md",
                plugin_id=plugin_id,
            )
        )

    return comps


def plugin_info(plugin_dir: Path, *, validate: bool = False) -> PluginInfo:
    man = load_plugin_manifest(plugin_dir)
    plugin_id = str(man.get("name") or man.get("id") or plugin_dir.name)
    try:
        priv = _norm_privilege(man.get("privilege"))
    except MarketplaceError:
        priv = "read"
    tags = man.get("tags") or man.get("keywords") or []
    if not isinstance(tags, list):
        tags = []
    comps = discover_components(plugin_dir, plugin_id)
    rel_source = f"{DEFAULT_PLUGINS_DIR}/{plugin_dir.name}"
    info = PluginInfo(
        id=plugin_id,
        name=str(man.get("name") or plugin_id),
        version=str(man.get("version") or ""),
        path=str(plugin_dir),
        description=str(man.get("description") or ""),
        category=str(man.get("category") or ""),
        privilege=priv,
        tags=[str(t) for t in tags],
        agents=[c.name for c in comps if c.kind == "agent"],
        skills=[c.name for c in comps if c.kind == "skill"],
        commands=[c.name for c in comps if c.kind == "command"],
        origin="plugin",
        source=rel_source,
    )
    if validate:
        rep = validate_plugin(plugin_dir)
        info.valid = rep.ok
    return info


def list_skillpack_dirs(
    workdir: Path | str, packs_dir: str = DEFAULT_SKILLPACKS_DIR
) -> list[Path]:
    """Dirs under skillpacks/ that look like packs (manifest.json or SKILL.md)."""
    root = skillpacks_root(workdir, packs_dir)
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name.startswith(".") or p.name == "README.md":
            continue
        if (p / "manifest.json").is_file() or (p / "SKILL.md").is_file():
            out.append(p)
    return out


def thin_plugin_from_skillpack(pack_dir: Path | str) -> PluginInfo:
    """Index a skillpack as a thin single-skill marketplace plugin (no vendor).

    Shape only: maps skillpacks/<id> → PluginInfo with origin=skillpack so the
    marketplace catalog can reuse production skill packs across harnesses
    without copying bodies (skillpacks.generate still owns emit).
    """
    pack_dir = Path(pack_dir)
    man: dict[str, Any] = {}
    man_path = pack_dir / "manifest.json"
    if man_path.is_file():
        try:
            raw = json.loads(man_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                man = raw
        except json.JSONDecodeError as e:
            raise MarketplaceError(
                f"invalid skillpack manifest {man_path}: {e}"
            ) from e

    pack_id = str(man.get("id") or man.get("name") or pack_dir.name)
    try:
        priv = _norm_privilege(man.get("privilege"))
    except MarketplaceError:
        priv = "read"
    tags = man.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    skill_md = pack_dir / "SKILL.md"
    skill_name = pack_id
    if skill_md.is_file():
        skill_name = _frontmatter_name(skill_md) or pack_id
    valid: Optional[bool] = None
    if skill_md.is_file() and man_path.is_file():
        valid = True
    elif not skill_md.is_file():
        valid = False

    return PluginInfo(
        id=pack_id,
        name=str(man.get("name") or pack_id),
        version=str(man.get("version") or ""),
        path=str(pack_dir),
        description=str(man.get("description") or man.get("name") or ""),
        category=str(man.get("category") or "skillpack"),
        privilege=priv,
        tags=[str(t) for t in tags],
        agents=[],
        skills=[skill_name],
        commands=[],
        valid=valid,
        origin="skillpack",
        source=f"{DEFAULT_SKILLPACKS_DIR}/{pack_dir.name}",
    )


def list_thin_skillpack_plugins(
    workdir: Path | str,
    *,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
    max_privilege: Optional[str] = None,
    skip_ids: Optional[Iterable[str]] = None,
) -> list[PluginInfo]:
    """List skillpacks as thin marketplace plugins (skip ids already present)."""
    skip = {s.lower() for s in (skip_ids or [])}
    cap = None
    if max_privilege is not None:
        cap = PRIVILEGE_RANK[_norm_privilege(max_privilege)]
    rows: list[PluginInfo] = []
    for d in list_skillpack_dirs(workdir, packs_dir):
        try:
            info = thin_plugin_from_skillpack(d)
        except MarketplaceError:
            info = PluginInfo(
                id=d.name,
                name=d.name,
                version="",
                path=str(d),
                origin="skillpack",
                source=f"{packs_dir}/{d.name}",
                valid=False,
            )
        if info.id.lower() in skip:
            continue
        if cap is not None and PRIVILEGE_RANK.get(info.privilege, 0) > cap:
            continue
        rows.append(info)
    return rows


def list_plugins(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    validate: bool = False,
    max_privilege: Optional[str] = None,
    include_skillpacks: bool = False,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
) -> list[PluginInfo]:
    """List installable plugins under workdir/plugins.

    When ``include_skillpacks`` is True, also index skillpacks/ as thin
    single-skill plugins (skipped if a real plugin already has the same id).
    """
    cap = None
    if max_privilege is not None:
        cap = PRIVILEGE_RANK[_norm_privilege(max_privilege)]
    rows: list[PluginInfo] = []
    for d in list_plugin_dirs(workdir, plugins_dir):
        try:
            info = plugin_info(d, validate=validate)
        except MarketplaceError:
            info = PluginInfo(
                id=d.name,
                name=d.name,
                version="",
                path=str(d),
                valid=False if validate else None,
                origin="plugin",
                source=f"{plugins_dir}/{d.name}",
            )
        if cap is not None and PRIVILEGE_RANK.get(info.privilege, 0) > cap:
            continue
        rows.append(info)
    if include_skillpacks:
        skip = {r.id for r in rows}
        rows.extend(
            list_thin_skillpack_plugins(
                workdir,
                packs_dir=packs_dir,
                max_privilege=max_privilege,
                skip_ids=skip,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def validate_plugin(plugin_dir: Path | str) -> ValidateReport:
    """Structural validation of one plugin (source of truth)."""
    plugin_dir = Path(plugin_dir)
    rep = ValidateReport(plugin_id=plugin_dir.name)

    man_path = _plugin_manifest_path(plugin_dir)
    if man_path is None:
        rep.add(
            "error",
            plugin_dir.name,
            "plugin.json",
            "missing plugin.json",
            "Add plugin.json (or .nexus-plugin/plugin.json) with name + version.",
        )
        return rep

    try:
        man = load_plugin_manifest(plugin_dir)
    except MarketplaceError as e:
        rep.add(
            "error",
            plugin_dir.name,
            "plugin.json",
            str(e),
            "Fix JSON syntax.",
        )
        return rep

    plugin_id = str(man.get("name") or man.get("id") or plugin_dir.name)
    rep.plugin_id = plugin_id

    for key in PLUGIN_REQUIRED:
        val = man.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            # accept `id` as alias for `name`
            if key == "name" and man.get("id"):
                continue
            rep.add(
                "error",
                plugin_id,
                "plugin.json",
                f"missing required field `{key}`",
                f"Set `{key}` in plugin.json.",
            )

    if plugin_id and not _SLUG_RE.match(plugin_id):
        rep.add(
            "error",
            plugin_id,
            "plugin.json",
            f"name must be slug-like (a-z0-9._-), got {plugin_id!r}",
            "Use lowercase slug e.g. nexus-durable.",
        )
    if plugin_id and plugin_id != plugin_dir.name:
        rep.add(
            "warning",
            plugin_id,
            "plugin.json",
            f"name {plugin_id!r} != directory name {plugin_dir.name!r}",
            "Rename folder or set name to match directory.",
        )

    try:
        _norm_privilege(man.get("privilege"))
    except MarketplaceError as e:
        rep.add(
            "error",
            plugin_id,
            "plugin.json",
            str(e),
            f"Set privilege to one of {list(PRIVILEGE_LEVELS)}.",
        )
    else:
        if "privilege" not in man:
            rep.add(
                "info",
                plugin_id,
                "plugin.json",
                "privilege omitted; defaulting to read",
                "Set privilege explicitly for least-privilege tooling.",
            )

    if not man.get("description"):
        rep.add(
            "warning",
            plugin_id,
            "plugin.json",
            "description missing",
            "Add a short description for marketplace listings.",
        )

    comps = discover_components(plugin_dir, plugin_id)
    if not comps:
        rep.add(
            "error",
            plugin_id,
            plugin_dir.name,
            "plugin has no agents/, commands/, or skills/",
            "Add at least one agent .md, command .md, or skills/*/SKILL.md.",
        )

    # Per-component checks
    for c in comps:
        full = plugin_dir / c.path
        if c.kind == "skill" and full.is_dir():
            rep.add(
                "error",
                plugin_id,
                c.path,
                "skill directory missing SKILL.md",
                f"Add {c.path}/SKILL.md.",
            )
            continue
        if not full.is_file():
            rep.add(
                "error",
                plugin_id,
                c.path,
                f"{c.kind} file missing",
                f"Create {c.path}.",
            )
            continue
        try:
            body = full.read_text(encoding="utf-8")
        except OSError as e:
            rep.add(
                "error",
                plugin_id,
                c.path,
                f"unreadable: {e}",
                "Fix file permissions.",
            )
            continue
        if len(body.strip()) < 20:
            rep.add(
                "warning",
                plugin_id,
                c.path,
                f"{c.kind} body too short",
                "Document purpose and usage.",
            )
        if c.kind == "agent" and not _frontmatter_name(full):
            rep.add(
                "info",
                plugin_id,
                c.path,
                "agent has no frontmatter name; using filename stem",
                "Add YAML frontmatter with `name:` for harness portability.",
            )

    # Intra-plugin name collisions
    for kind in ("agent", "skill", "command"):
        seen: dict[str, list[str]] = defaultdict(list)
        for c in comps:
            if c.kind == kind:
                seen[c.name.lower()].append(c.path)
        for name, paths in seen.items():
            if len(paths) > 1:
                rep.add(
                    "error",
                    plugin_id,
                    paths[0],
                    f"duplicate {kind} name {name!r} within plugin",
                    "Rename so each component name is unique inside the plugin.",
                )

    return rep


def validate_all(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
) -> dict[str, Any]:
    reports = [validate_plugin(d) for d in list_plugin_dirs(workdir, plugins_dir)]
    ok = all(r.ok for r in reports) if reports else True
    return {
        "schema": SCHEMA_VERSION,
        "ok": ok,
        "count": len(reports),
        "plugins": [r.to_dict() for r in reports],
        "errors": sum(r.to_dict()["errors"] for r in reports),
        "warnings": sum(r.to_dict()["warnings"] for r in reports),
    }


# ---------------------------------------------------------------------------
# Cross-plugin name collisions
# ---------------------------------------------------------------------------


def collect_components(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
) -> list[ComponentRef]:
    out: list[ComponentRef] = []
    for d in list_plugin_dirs(workdir, plugins_dir):
        try:
            man = load_plugin_manifest(d)
            pid = str(man.get("name") or man.get("id") or d.name)
        except MarketplaceError:
            pid = d.name
        out.extend(discover_components(d, pid))
    return out


def collisions(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    kinds: Optional[Iterable[str]] = None,
    fail_on_duplicates: bool = True,
) -> dict[str, Any]:
    """Report cross-plugin duplicate agent/skill/command names.

    Pattern from wshobson/agents tools/check_agent_name_collisions.py
    (shape only — no upstream code).
    """
    want = set(kinds) if kinds is not None else {"agent", "skill", "command"}
    comps = [c for c in collect_components(workdir, plugins_dir=plugins_dir) if c.kind in want]
    by_key: dict[tuple[str, str], list[ComponentRef]] = defaultdict(list)
    for c in comps:
        by_key[(c.kind, c.name.lower())].append(c)

    dups: list[dict[str, Any]] = []
    for (kind, name), refs in sorted(by_key.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        # collision only across different plugins (or same plugin multi-path)
        plugins = {r.plugin_id for r in refs}
        if len(refs) > 1 and (len(plugins) > 1 or len(refs) > 1):
            # same name in one plugin already flagged by validate_plugin;
            # still surface multi-plugin collisions as the primary signal
            if len(plugins) < 2 and len(refs) < 2:
                continue
            if len(plugins) < 2:
                # intra-plugin: include only if >1 path
                pass
            dups.append(
                {
                    "kind": kind,
                    "name": refs[0].name,
                    "count": len(refs),
                    "plugins": sorted(plugins),
                    "paths": [
                        {"plugin_id": r.plugin_id, "path": r.path} for r in refs
                    ],
                    "cross_plugin": len(plugins) > 1,
                }
            )

    # Prefer reporting cross-plugin; keep intra as lower severity
    cross = [d for d in dups if d["cross_plugin"]]
    intra = [d for d in dups if not d["cross_plugin"]]
    error_count = len(cross) if fail_on_duplicates else 0
    warning_count = len(intra) + (0 if fail_on_duplicates else len(cross))
    return {
        "schema": SCHEMA_VERSION,
        "ok": error_count == 0,
        "component_count": len(comps),
        "duplicate_names": len(dups),
        "cross_plugin": len(cross),
        "intra_plugin": len(intra),
        "errors": error_count,
        "warnings": warning_count,
        "collisions": dups,
    }


# ---------------------------------------------------------------------------
# Catalog + multi-harness export
# ---------------------------------------------------------------------------


def build_catalog(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    name: str = "nexus-plugins",
    description: str = "NEXUS plugin marketplace (single Markdown source)",
    version: str = "1.0.0",
    include_skillpacks: bool = True,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
) -> dict[str, Any]:
    """Build a marketplace catalog (claude-plugin-shaped registry JSON).

    By default includes skillpacks/ as thin single-skill plugins so one catalog
    covers multi-component plugins and reusable skill packs (wshobson shape).
    """
    plugins = list_plugins(
        workdir,
        plugins_dir=plugins_dir,
        validate=False,
        include_skillpacks=include_skillpacks,
        packs_dir=packs_dir,
    )
    entries = []
    for p in plugins:
        source = p.source or f"{plugins_dir}/{Path(p.path).name}"
        if not source.startswith("./"):
            source = f"./{source}"
        entries.append(
            {
                "name": p.id,
                "source": source,
                "description": p.description or p.name,
                "version": p.version,
                "category": p.category or "general",
                "privilege": p.privilege,
                "tags": list(p.tags),
                "origin": p.origin,
                "agents": list(p.agents),
                "skills": list(p.skills),
                "commands": list(p.commands),
                "counts": {
                    "agents": len(p.agents),
                    "skills": len(p.skills),
                    "commands": len(p.commands),
                },
            }
        )
    n_plugin = sum(1 for e in entries if e.get("origin") == "plugin")
    n_skillpack = sum(1 for e in entries if e.get("origin") == "skillpack")
    totals = {
        "plugins": len(entries),
        "from_plugins_dir": n_plugin,
        "from_skillpacks": n_skillpack,
        "agents": sum(e["counts"]["agents"] for e in entries),
        "skills": sum(e["counts"]["skills"] for e in entries),
        "commands": sum(e["counts"]["commands"] for e in entries),
    }
    return {
        "schema": SCHEMA_VERSION,
        "name": name,
        "metadata": {
            "description": description,
            "version": version,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "harnesses": list(SUPPORTED_HARNESSES),
            "include_skillpacks": include_skillpacks,
            "codex_skill_body_max_bytes": CODEX_SKILL_BODY_MAX_BYTES,
            "capability_notes": {
                h: CAPABILITIES[h].notes
                for h in SUPPORTED_HARNESSES
                if h in CAPABILITIES
            },
        },
        "totals": totals,
        "plugins": entries,
    }


def export_root(workdir: Path | str) -> Path:
    return Path(workdir).resolve() / ".nexus_state" / "generated_marketplace"


def _harness_registry_path(harness: str) -> str:
    """Relative path under export root for a harness marketplace registry."""
    if harness == "claude":
        return "claude/.claude-plugin/marketplace.json"
    if harness == "cursor":
        return "cursor/.cursor-plugin/marketplace.json"
    if harness == "codex":
        return "codex/.agents/plugins/marketplace.json"
    if harness == "opencode":
        return "opencode/marketplace.json"
    if harness == "gemini":
        return "gemini/marketplace.json"
    if harness == "copilot":
        return "copilot/marketplace.json"
    if harness == "grok":
        return "grok/marketplace.json"
    if harness == "local":
        return "local/marketplace.json"
    raise MarketplaceError(f"unknown harness: {harness}")


def _adapt_catalog_for_harness(catalog: dict[str, Any], harness: str) -> dict[str, Any]:
    """Thin harness-native registry (points at source plugins/, no body rewrite)."""
    base = {
        "schema": SCHEMA_VERSION,
        "harness": harness,
        "name": catalog.get("name"),
        "metadata": {
            **(catalog.get("metadata") or {}),
            "harness": harness,
        },
        "totals": catalog.get("totals"),
        "plugins": catalog.get("plugins") or [],
    }
    if harness == "claude":
        # Claude Code marketplace.json shape (subset)
        return {
            "name": catalog.get("name"),
            "metadata": catalog.get("metadata") or {},
            "plugins": [
                {
                    "name": p["name"],
                    "source": p["source"],
                    "description": p.get("description") or "",
                    "version": p.get("version") or "0.0.0",
                    "category": p.get("category") or "general",
                }
                for p in base["plugins"]
            ],
        }
    if harness == "cursor":
        return {
            "name": catalog.get("name"),
            "plugins": [
                {
                    "name": p["name"],
                    "source": p["source"],
                    "description": p.get("description") or "",
                }
                for p in base["plugins"]
            ],
        }
    if harness == "codex":
        return {
            "name": catalog.get("name"),
            "plugins": [
                {
                    "name": p["name"],
                    "path": p["source"],
                    "description": p.get("description") or "",
                    "version": p.get("version") or "0.0.0",
                }
                for p in base["plugins"]
            ],
        }
    # opencode / gemini / copilot / grok / local — full nexus catalog + harness tag
    return base


def _plugin_stub_blob(
    plugin: PluginInfo | dict[str, Any], harness: str
) -> dict[str, Any]:
    """Per-plugin harness stub: component index pointing at source (no body rewrite)."""
    if isinstance(plugin, PluginInfo):
        p = plugin.to_dict()
    else:
        p = dict(plugin)
    return {
        "schema": SCHEMA_VERSION,
        "harness": harness,
        "name": p.get("id") or p.get("name"),
        "version": p.get("version") or "0.0.0",
        "description": p.get("description") or "",
        "privilege": p.get("privilege") or "read",
        "origin": p.get("origin") or "plugin",
        "source": p.get("source") or "",
        "category": p.get("category") or "general",
        "tags": list(p.get("tags") or []),
        "agents": list(p.get("agents") or []),
        "skills": list(p.get("skills") or []),
        "commands": list(p.get("commands") or []),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": (
            "Harness stub index only — source Markdown remains under source path. "
            "Full skill body emit lives in nexus.skillpacks."
        ),
    }


def export_plugin_stubs(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    out_root: Optional[Path | str] = None,
    harnesses: Optional[Iterable[str]] = None,
    include_skillpacks: bool = True,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
    clean: bool = False,
) -> dict[str, Any]:
    """Emit per-plugin per-harness stub indexes under out/stubs/<harness>/<id>/."""
    workdir = Path(workdir).resolve()
    out = Path(out_root) if out_root else export_root(workdir)
    out = out.resolve()
    want = list(harnesses) if harnesses is not None else list(SUPPORTED_HARNESSES)
    for h in want:
        if h not in SUPPORTED_HARNESSES:
            raise MarketplaceError(f"unsupported harness: {h}")

    plugins = list_plugins(
        workdir,
        plugins_dir=plugins_dir,
        include_skillpacks=include_skillpacks,
        packs_dir=packs_dir,
    )
    written: list[str] = []
    stubs_root = out / "stubs"

    if clean and stubs_root.is_dir():
        for h in SUPPORTED_HARNESSES:
            hdir = stubs_root / h
            if not hdir.is_dir():
                continue
            for child in hdir.iterdir():
                if child.is_dir():
                    for f in child.glob("*"):
                        if f.is_file():
                            f.unlink()
                    try:
                        child.rmdir()
                    except OSError:
                        pass

    for p in plugins:
        for h in want:
            rel_dir = f"stubs/{h}/{p.id}"
            target_dir = out / rel_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            stub = _plugin_stub_blob(p, h)
            json_path = target_dir / "plugin.stub.json"
            atomic_write_json(json_path, stub)
            written.append(f"{rel_dir}/plugin.stub.json")
            md = (
                f"# {p.name} (`{p.id}`)\n\n"
                f"- harness: `{h}`\n"
                f"- origin: `{p.origin}`\n"
                f"- source: `{p.source or p.path}`\n"
                f"- privilege: `{p.privilege}`\n"
                f"- agents: {', '.join(p.agents) or '—'}\n"
                f"- skills: {', '.join(p.skills) or '—'}\n"
                f"- commands: {', '.join(p.commands) or '—'}\n"
            )
            md_path = target_dir / "README.md"
            atomic_write_text(md_path, md)
            written.append(f"{rel_dir}/README.md")

    return {
        "schema": SCHEMA_VERSION,
        "ok": True,
        "out_root": str(out),
        "harnesses": want,
        "plugin_count": len(plugins),
        "written": written,
        "count": len(written),
    }


def export_registries(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    out_root: Optional[Path | str] = None,
    harnesses: Optional[Iterable[str]] = None,
    clean: bool = False,
    include_skillpacks: bool = True,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
    with_stubs: bool = True,
) -> dict[str, Any]:
    """Emit multi-harness marketplace registry JSON from plugins/ source.

    Also writes per-plugin harness stubs when ``with_stubs`` is True (default).
    """
    workdir = Path(workdir).resolve()
    out = Path(out_root) if out_root else export_root(workdir)
    out = out.resolve()
    want = list(harnesses) if harnesses is not None else list(SUPPORTED_HARNESSES)
    for h in want:
        if h not in SUPPORTED_HARNESSES:
            raise MarketplaceError(f"unsupported harness: {h}")

    # Fail closed if any plugin is invalid
    val = validate_all(workdir, plugins_dir=plugins_dir)
    if not val.get("ok"):
        raise MarketplaceError(
            f"refuse to export: {val.get('errors')} validation error(s); "
            "run: nexus marketplace validate"
        )

    catalog = build_catalog(
        workdir,
        plugins_dir=plugins_dir,
        include_skillpacks=include_skillpacks,
        packs_dir=packs_dir,
    )
    written: list[str] = []

    if clean and out.is_dir():
        # only remove known harness registry files (safe)
        for h in SUPPORTED_HARNESSES:
            p = out / _harness_registry_path(h)
            if p.is_file():
                p.unlink()

    # Unified catalog always written
    unified = out / "marketplace.json"
    unified.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(unified, catalog)
    written.append(str(unified.relative_to(out)))

    # Human-readable index
    totals = catalog.get("totals") or {}
    md_lines = [
        f"# {catalog.get('name')}",
        "",
        f"_schema {SCHEMA_VERSION} · generated "
        f"{(catalog.get('metadata') or {}).get('generated_at')}_",
        "",
        f"| plugins | agents | skills | commands | skillpacks |",
        f"|--------:|-------:|-------:|---------:|-----------:|",
        (
            f"| {totals.get('plugins', 0)} "
            f"| {totals.get('agents', 0)} "
            f"| {totals.get('skills', 0)} "
            f"| {totals.get('commands', 0)} "
            f"| {totals.get('from_skillpacks', 0)} |"
        ),
        "",
        "## Plugins",
        "",
    ]
    for p in catalog.get("plugins") or []:
        origin = p.get("origin") or "plugin"
        md_lines.append(
            f"- **{p['name']}** v{p.get('version') or '?'} "
            f"[{origin}] — "
            f"{p.get('description') or ''} "
            f"(agents={p['counts']['agents']}, skills={p['counts']['skills']}, "
            f"commands={p['counts']['commands']})"
        )
    md_path = out / "MARKETPLACE.md"
    atomic_write_text(md_path, "\n".join(md_lines) + "\n")
    written.append("MARKETPLACE.md")

    for h in want:
        rel = _harness_registry_path(h)
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, _adapt_catalog_for_harness(catalog, h))
        written.append(rel)

    stub_report: dict[str, Any] = {}
    if with_stubs:
        stub_report = export_plugin_stubs(
            workdir,
            plugins_dir=plugins_dir,
            out_root=out,
            harnesses=want,
            include_skillpacks=include_skillpacks,
            packs_dir=packs_dir,
            clean=clean,
        )
        written.extend(stub_report.get("written") or [])

    return {
        "schema": SCHEMA_VERSION,
        "ok": True,
        "out_root": str(out),
        "harnesses": want,
        "totals": catalog.get("totals"),
        "written": written,
        "count": len(written),
        "stubs": {
            "ok": stub_report.get("ok", False) if with_stubs else None,
            "plugin_count": stub_report.get("plugin_count", 0) if with_stubs else 0,
            "count": stub_report.get("count", 0) if with_stubs else 0,
        },
    }


# ---------------------------------------------------------------------------
# Multi-harness adapters (wshobson tools/adapters shape — generate + validate)
# ---------------------------------------------------------------------------

# Fields Claude Code honors that other harnesses silently ignore.
_CLAUDE_ONLY_AGENT_FIELDS = frozenset(
    {
        "color",
        "hooks",
        "user-invocable",
        "disable-model-invocation",
        "allowed-tools",
    }
)
_CLAUDE_ONLY_SKILL_FIELDS = frozenset(
    {
        "hooks",
        "user-invocable",
        "disable-model-invocation",
        "context",
        "agent",
    }
)

# Bare model aliases → harness-native ids (pattern only; not a full provider matrix).
_MODEL_MAP: dict[str, dict[str, str]] = {
    "codex": {
        "opus": "gpt-5.5",
        "sonnet": "gpt-5.5",
        "haiku": "gpt-5-mini",
        "fable": "gpt-5.5",
        "inherit": "gpt-5.5",
    },
    "cursor": {
        "opus": "inherit",
        "sonnet": "inherit",
        "haiku": "inherit",
        "fable": "inherit",
    },
    "gemini": {
        "opus": "gemini-2.5-pro",
        "sonnet": "gemini-2.5-flash",
        "haiku": "gemini-2.5-flash",
        "fable": "gemini-2.5-pro",
    },
    "opencode": {
        "opus": "anthropic/claude-opus",
        "sonnet": "anthropic/claude-sonnet",
        "haiku": "anthropic/claude-haiku",
        "fable": "anthropic/claude-opus",
    },
    "copilot": {
        "opus": "claude-opus",
        "sonnet": "claude-sonnet",
        "haiku": "claude-haiku",
        "fable": "claude-opus",
    },
}


def generate_adapters_root(workdir: Path | str) -> Path:
    """Default output root for harness adapter trees (gitignored under .nexus_state)."""
    return Path(workdir).resolve() / ".nexus_state" / "generated_adapters"


def parse_frontmatter_fields(content: str) -> tuple[dict[str, str], str]:
    """Tolerant scalar frontmatter parse → (fields, body). No external YAML dep."""
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        # skip indented list/map continuations
        if line.startswith(" ") or line.startswith("\t"):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        if not key or not re.match(r"^[\w-]+$", key):
            continue
        fields[key] = val.strip().strip("\"'")
    return fields, body


def serialize_frontmatter(fields: dict[str, Any], body: str) -> str:
    """Emit ``---\\nkey: val\\n---\\n\\nbody`` (stable key order)."""
    if not fields:
        return body if body.endswith("\n") else body + "\n"
    lines = ["---"]
    for k in sorted(fields.keys()):
        v = fields[k]
        if v is None:
            continue
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (list, dict)):
            lines.append(f"{k}: {json.dumps(v)}")
        else:
            s = str(v)
            if any(c in s for c in (":", "#", '"', "'")) or s == "":
                lines.append(f'{k}: "{s.replace(chr(34), chr(92) + chr(34))}"')
            else:
                lines.append(f"{k}: {s}")
    lines.append("---")
    lines.append("")
    body_s = body.lstrip("\n")
    if body_s and not body_s.endswith("\n"):
        body_s += "\n"
    return "\n".join(lines) + "\n" + body_s


def map_model_for_harness(model: str, harness: str) -> str:
    """Map bare Claude model aliases to harness-native ids when known."""
    raw = str(model or "").strip()
    if not raw:
        return raw
    table = _MODEL_MAP.get(str(harness).strip().lower()) or {}
    key = raw.lower().split("/")[-1]  # strip provider prefix for lookup
    # also strip claude- prefix
    if key.startswith("claude-"):
        key = key[len("claude-") :]
    return table.get(key, table.get(raw.lower(), raw))


def adapt_markdown(
    content: str,
    *,
    harness: str,
    kind: str,
    name_hint: str = "",
) -> tuple[str, list[str]]:
    """Rewrite component Markdown frontmatter for a target harness.

    Returns (adapted_text, transform_notes). Body content is preserved;
    only frontmatter fields are filtered/mapped (wshobson graceful degrade).
    """
    notes: list[str] = []
    fields, body = parse_frontmatter_fields(content)
    h = str(harness).strip().lower()
    k = str(kind).strip().lower()
    drop: set[str] = set()
    if h != "claude":
        if k == "agent":
            drop |= set(_CLAUDE_ONLY_AGENT_FIELDS)
        elif k in ("skill", "command"):
            drop |= set(_CLAUDE_ONLY_SKILL_FIELDS)
    for d in drop:
        if d in fields:
            del fields[d]
            notes.append(f"drop:{d}")
    if "model" in fields:
        mapped = map_model_for_harness(fields["model"], h)
        if mapped != fields["model"]:
            notes.append(f"model:{fields['model']}→{mapped}")
            fields["model"] = mapped
    if name_hint and "name" not in fields:
        fields["name"] = name_hint
        notes.append("name:injected")
    # OpenCode-style permission hint when tools allowlist present and harness
    # prefers permission blocks (we only emit a note field, no full rewrite).
    if h == "opencode" and ("tools" in fields or "allowed-tools" in fields):
        tools_raw = fields.pop("tools", None) or fields.pop("allowed-tools", None)
        if tools_raw is not None:
            fields["permission"] = f"allow:{tools_raw}"
            notes.append("tools→permission")
    elif h in ("codex", "cursor") and "tools" in fields:
        # coarser harnesses drop per-agent tool allowlists
        del fields["tools"]
        notes.append("drop:tools")
    if h in ("codex", "cursor") and "allowed-tools" in fields:
        del fields["allowed-tools"]
        notes.append("drop:allowed-tools")
    adapted = serialize_frontmatter(fields, body)
    header = (
        f"<!-- generated by nexus.marketplace adapters harness={h} kind={k} "
        f"schema={SCHEMA_VERSION} -->\n"
    )
    if not adapted.lstrip().startswith("<!-- generated by nexus.marketplace"):
        adapted = header + adapted
    return adapted, notes


def split_skill_for_cap(
    content: str, max_bytes: int
) -> tuple[str, Optional[str], bool]:
    """Split oversize skill body for harnesses with a hard skill cap (Codex).

    Returns (skill_md, references_details_or_None, did_split).
    Keeps frontmatter + head of body in SKILL.md; overflow → references/details.md.
    """
    if max_bytes <= 0:
        return content, None, False
    raw = content.encode("utf-8")
    if len(raw) <= max_bytes:
        return content, None, False
    fields, body = parse_frontmatter_fields(content)
    # Budget for body after frontmatter + pointer
    pointer = (
        "\n\n> **Note:** Body truncated for harness skill cap; "
        "see [references/details.md](references/details.md) for full text.\n"
    )
    # binary-search a UTF-8 safe head that fits
    lo, hi = 0, len(body)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = serialize_frontmatter(fields, body[:mid] + pointer)
        if len(candidate.encode("utf-8")) <= max_bytes:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if best <= 0:
        # frontmatter alone may exceed — emit minimal body
        skill = serialize_frontmatter(
            fields,
            pointer.strip() + "\n",
        )
        # if still over, force-truncate bytes
        b = skill.encode("utf-8")
        if len(b) > max_bytes:
            skill = b[:max_bytes].decode("utf-8", errors="ignore")
        return skill, body, True
    skill = serialize_frontmatter(fields, body[:best] + pointer)
    return skill, body[best:].lstrip("\n"), True


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _component_source_files(plugin: PluginInfo) -> dict[str, list[tuple[str, Path]]]:
    """Map kind → [(component_name, path)] for a plugin (or skillpack thin)."""
    root = Path(plugin.path)
    out: dict[str, list[tuple[str, Path]]] = {
        "agent": [],
        "skill": [],
        "command": [],
    }
    if plugin.origin == "skillpack":
        skill_md = root / "SKILL.md"
        if skill_md.is_file():
            name = plugin.skills[0] if plugin.skills else plugin.id
            out["skill"].append((name, skill_md))
        return out
    agents = root / "agents"
    if agents.is_dir():
        for p in sorted(agents.glob("*.md")):
            out["agent"].append((_frontmatter_name(p) or p.stem, p))
    commands = root / "commands"
    if commands.is_dir():
        for p in sorted(commands.glob("*.md")):
            out["command"].append((_frontmatter_name(p) or p.stem, p))
    for name, path in _skill_paths_for_plugin(plugin):
        out["skill"].append((name, path))
    return out


def generate_plugin_for_harness(
    plugin: PluginInfo,
    harness: str,
    out_root: Path | str,
) -> dict[str, Any]:
    """Emit one plugin's harness-native tree under ``out_root/<harness>/plugins/<id>/``.

    Graceful degradation (wshobson adapters shape):
    - drop Claude-only frontmatter on non-claude harnesses
    - map bare model aliases
    - when ``commands_map_to_skills``, emit commands as skills
    - when skill_body_max_bytes > 0, split overflow into references/details.md
    """
    h = str(harness).strip().lower()
    if h not in SUPPORTED_HARNESSES:
        raise MarketplaceError(f"unsupported harness: {harness}")
    cap = capability(h)
    out_root = Path(out_root).resolve()
    plugin_out = out_root / h / "plugins" / plugin.id
    plugin_out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    transforms: list[dict[str, Any]] = []
    sources = _component_source_files(plugin)

    # Manifest (always)
    meta = {
        "schema": SCHEMA_VERSION,
        "harness": h,
        "name": plugin.id,
        "version": plugin.version,
        "description": plugin.description,
        "privilege": plugin.privilege,
        "origin": plugin.origin,
        "source": plugin.source or plugin.path,
        "category": plugin.category,
        "tags": list(plugin.tags),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "capabilities": {
            "skills_native": cap.skills_native,
            "agents_native": cap.agents_native,
            "commands_native": cap.commands_native,
            "commands_map_to_skills": cap.commands_map_to_skills,
            "skill_body_max_bytes": cap.skill_body_max_bytes,
        },
    }
    meta_path = plugin_out / "plugin.meta.json"
    atomic_write_json(meta_path, meta)
    written.append(str(meta_path.relative_to(out_root)))

    # Agents
    if sources["agent"] and cap.agents_native:
        agents_dir = plugin_out / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        for name, src in sources["agent"]:
            text = _read_text(src)
            adapted, notes = adapt_markdown(
                text, harness=h, kind="agent", name_hint=name
            )
            dest = agents_dir / f"{_slug_component(name)}.md"
            atomic_write_text(dest, adapted)
            written.append(str(dest.relative_to(out_root)))
            if notes:
                transforms.append(
                    {"kind": "agent", "name": name, "notes": notes, "path": str(dest)}
                )

    # Skills
    if sources["skill"] and cap.skills_native:
        for name, src in sources["skill"]:
            text = _read_text(src)
            adapted, notes = adapt_markdown(
                text, harness=h, kind="skill", name_hint=name
            )
            skill_dir = plugin_out / "skills" / _slug_component(name)
            skill_dir.mkdir(parents=True, exist_ok=True)
            if cap.skill_body_max_bytes > 0:
                skill_body, overflow, did_split = split_skill_for_cap(
                    adapted, cap.skill_body_max_bytes
                )
                if did_split:
                    notes = list(notes) + [
                        f"split:skill_body_cap={cap.skill_body_max_bytes}"
                    ]
                    if overflow:
                        ref_dir = skill_dir / "references"
                        ref_dir.mkdir(parents=True, exist_ok=True)
                        ref_path = ref_dir / "details.md"
                        atomic_write_text(ref_path, overflow)
                        written.append(str(ref_path.relative_to(out_root)))
                adapted = skill_body
            dest = skill_dir / "SKILL.md"
            atomic_write_text(dest, adapted)
            written.append(str(dest.relative_to(out_root)))
            if notes:
                transforms.append(
                    {"kind": "skill", "name": name, "notes": notes, "path": str(dest)}
                )

    # Commands — native or map to skills
    if sources["command"]:
        if cap.commands_native and not cap.commands_map_to_skills:
            cmd_dir = plugin_out / "commands"
            cmd_dir.mkdir(parents=True, exist_ok=True)
            for name, src in sources["command"]:
                text = _read_text(src)
                adapted, notes = adapt_markdown(
                    text, harness=h, kind="command", name_hint=name
                )
                dest = cmd_dir / f"{_slug_component(name)}.md"
                atomic_write_text(dest, adapted)
                written.append(str(dest.relative_to(out_root)))
                if notes:
                    transforms.append(
                        {
                            "kind": "command",
                            "name": name,
                            "notes": notes,
                            "path": str(dest),
                        }
                    )
        elif cap.commands_map_to_skills or not cap.commands_native:
            # Emit as invocable skills (Codex / Copilot shape)
            for name, src in sources["command"]:
                text = _read_text(src)
                adapted, notes = adapt_markdown(
                    text, harness=h, kind="skill", name_hint=name
                )
                notes = list(notes) + ["command→skill"]
                skill_name = f"cmd-{_slug_component(name)}"
                skill_dir = plugin_out / "skills" / skill_name
                skill_dir.mkdir(parents=True, exist_ok=True)
                if cap.skill_body_max_bytes > 0:
                    skill_body, overflow, did_split = split_skill_for_cap(
                        adapted, cap.skill_body_max_bytes
                    )
                    if did_split:
                        notes.append(f"split:skill_body_cap={cap.skill_body_max_bytes}")
                        if overflow:
                            ref_dir = skill_dir / "references"
                            ref_dir.mkdir(parents=True, exist_ok=True)
                            ref_path = ref_dir / "details.md"
                            atomic_write_text(ref_path, overflow)
                            written.append(str(ref_path.relative_to(out_root)))
                    adapted = skill_body
                dest = skill_dir / "SKILL.md"
                atomic_write_text(dest, adapted)
                written.append(str(dest.relative_to(out_root)))
                transforms.append(
                    {
                        "kind": "command",
                        "name": name,
                        "notes": notes,
                        "path": str(dest),
                        "emitted_as": "skill",
                    }
                )

    # Manifest index of components written
    index = {
        "schema": SCHEMA_VERSION,
        "harness": h,
        "plugin_id": plugin.id,
        "written": written,
        "transforms": transforms,
        "counts": {
            "agents": len(list((plugin_out / "agents").glob("*.md")))
            if (plugin_out / "agents").is_dir()
            else 0,
            "skills": sum(
                1
                for d in (plugin_out / "skills").iterdir()
                if d.is_dir() and (d / "SKILL.md").is_file()
            )
            if (plugin_out / "skills").is_dir()
            else 0,
            "commands": len(list((plugin_out / "commands").glob("*.md")))
            if (plugin_out / "commands").is_dir()
            else 0,
        },
    }
    idx_path = plugin_out / "adapter.index.json"
    atomic_write_json(idx_path, index)
    written.append(str(idx_path.relative_to(out_root)))

    return {
        "schema": SCHEMA_VERSION,
        "ok": True,
        "harness": h,
        "plugin_id": plugin.id,
        "out_dir": str(plugin_out),
        "written": written,
        "count": len(written),
        "transforms": transforms,
        "counts": index["counts"],
    }


def _slug_component(name: str) -> str:
    """Filesystem-safe component slug (keep simple alnum/._-)."""
    s = str(name or "component").strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "-", s)
    s = s.strip("-._") or "component"
    return s[:64]


def generate_adapters(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    out_root: Optional[Path | str] = None,
    harnesses: Optional[Iterable[str]] = None,
    include_skillpacks: bool = True,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
    clean: bool = False,
    plugin: Optional[str] = None,
    max_privilege: Optional[str] = None,
) -> dict[str, Any]:
    """Generate multi-harness adapter trees from ``plugins/`` Markdown source.

    Fail-closed: refuses when source validate has errors (same spirit as export).
    Pattern: wshobson ``tools/generate.py`` + per-harness adapters (shape only).
    """
    workdir = Path(workdir).resolve()
    out = Path(out_root) if out_root else generate_adapters_root(workdir)
    out = out.resolve()
    want = list(harnesses) if harnesses is not None else list(SUPPORTED_HARNESSES)
    for h in want:
        if h not in SUPPORTED_HARNESSES:
            raise MarketplaceError(f"unsupported harness: {h}")

    val = validate_all(workdir, plugins_dir=plugins_dir)
    if not val.get("ok"):
        raise MarketplaceError(
            f"refuse to generate adapters: {val.get('errors')} validation error(s); "
            "run: nexus marketplace validate"
        )

    plugins = list_plugins(
        workdir,
        plugins_dir=plugins_dir,
        include_skillpacks=include_skillpacks,
        packs_dir=packs_dir,
        max_privilege=max_privilege,
    )
    if plugin:
        plugins = [p for p in plugins if p.id == plugin]
        if not plugins:
            raise MarketplaceError(f"plugin not found: {plugin}")

    if clean and out.is_dir():
        for h in want:
            hdir = out / h / "plugins"
            if not hdir.is_dir():
                continue
            for child in list(hdir.iterdir()):
                if not child.is_dir():
                    continue
                for f in child.rglob("*"):
                    if f.is_file():
                        try:
                            f.unlink()
                        except OSError:
                            pass

    results: list[dict[str, Any]] = []
    written: list[str] = []
    for p in plugins:
        for h in want:
            rep = generate_plugin_for_harness(p, h, out)
            results.append(rep)
            written.extend(rep.get("written") or [])

    # Top-level harness summary
    summary = {
        "schema": SCHEMA_VERSION,
        "kind": "generate_adapters",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "harnesses": want,
        "plugin_ids": [p.id for p in plugins],
        "plugin_count": len(plugins),
        "result_count": len(results),
    }
    summary_path = out / "adapters.summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(summary_path, summary)
    written.append(str(summary_path.relative_to(out)))

    return {
        "schema": SCHEMA_VERSION,
        "kind": "generate_adapters",
        "ok": True,
        "out_root": str(out),
        "harnesses": want,
        "plugin_count": len(plugins),
        "result_count": len(results),
        "results": results,
        "written": written,
        "count": len(written),
    }


def validate_generated(
    out_root: Path | str,
    *,
    harnesses: Optional[Iterable[str]] = None,
    fail_on_oversize: bool = True,
) -> dict[str, Any]:
    """Structural gate on adapter output trees (wshobson validate_generated shape).

    Checks per harness/plugin:
    - plugin.meta.json present
    - adapter.index.json present
    - skill bodies respect harness skill_body_max_bytes
    - when commands_map_to_skills, no leftover commands/ tree
    """
    out = Path(out_root).resolve()
    if not out.is_dir():
        return {
            "schema": SCHEMA_VERSION,
            "kind": "validate_generated",
            "ok": False,
            "out_root": str(out),
            "errors": 1,
            "warnings": 0,
            "findings": [
                {
                    "severity": "error",
                    "message": f"generated adapters root missing: {out}",
                    "remediation": "Run: nexus marketplace generate",
                }
            ],
        }

    want = list(harnesses) if harnesses is not None else list(SUPPORTED_HARNESSES)
    findings: list[dict[str, Any]] = []
    plugin_count = 0
    file_count = 0

    for h in want:
        if h not in SUPPORTED_HARNESSES:
            findings.append(
                {
                    "severity": "error",
                    "harness": h,
                    "message": f"unknown harness: {h}",
                }
            )
            continue
        cap = capability(h)
        plugins_dir = out / h / "plugins"
        if not plugins_dir.is_dir():
            findings.append(
                {
                    "severity": "warning",
                    "harness": h,
                    "message": f"no plugins tree for harness {h}",
                    "remediation": f"Run: nexus marketplace generate --harness {h}",
                }
            )
            continue
        for pdir in sorted(plugins_dir.iterdir()):
            if not pdir.is_dir() or pdir.name.startswith("."):
                continue
            plugin_count += 1
            meta = pdir / "plugin.meta.json"
            idx = pdir / "adapter.index.json"
            if not meta.is_file():
                findings.append(
                    {
                        "severity": "error",
                        "harness": h,
                        "plugin_id": pdir.name,
                        "path": str(meta.relative_to(out)),
                        "message": "missing plugin.meta.json",
                        "remediation": "Re-run marketplace generate",
                    }
                )
            else:
                file_count += 1
            if not idx.is_file():
                findings.append(
                    {
                        "severity": "error",
                        "harness": h,
                        "plugin_id": pdir.name,
                        "path": str(idx.relative_to(out)),
                        "message": "missing adapter.index.json",
                        "remediation": "Re-run marketplace generate",
                    }
                )
            else:
                file_count += 1

            # commands should not exist when mapped to skills
            cmd_dir = pdir / "commands"
            if cap.commands_map_to_skills and cmd_dir.is_dir():
                leftover = list(cmd_dir.glob("*.md"))
                if leftover:
                    findings.append(
                        {
                            "severity": "error",
                            "harness": h,
                            "plugin_id": pdir.name,
                            "path": str(cmd_dir.relative_to(out)),
                            "message": (
                                f"commands/ present but {h} maps commands→skills "
                                f"({len(leftover)} files)"
                            ),
                            "remediation": (
                                "Emit commands as skills/cmd-*/SKILL.md only."
                            ),
                        }
                    )

            # skill body caps
            skills_dir = pdir / "skills"
            if skills_dir.is_dir() and cap.skill_body_max_bytes > 0:
                for sdir in sorted(skills_dir.iterdir()):
                    if not sdir.is_dir():
                        continue
                    skill_md = sdir / "SKILL.md"
                    if not skill_md.is_file():
                        findings.append(
                            {
                                "severity": "error",
                                "harness": h,
                                "plugin_id": pdir.name,
                                "path": str(sdir.relative_to(out)),
                                "message": "skill dir missing SKILL.md",
                            }
                        )
                        continue
                    file_count += 1
                    size = _utf8_size(skill_md)
                    if size > cap.skill_body_max_bytes:
                        sev = "error" if fail_on_oversize else "warning"
                        findings.append(
                            {
                                "severity": sev,
                                "harness": h,
                                "plugin_id": pdir.name,
                                "path": str(skill_md.relative_to(out)),
                                "bytes": size,
                                "max_bytes": cap.skill_body_max_bytes,
                                "message": (
                                    f"generated skill body {size} bytes exceeds "
                                    f"{cap.skill_body_max_bytes}"
                                ),
                                "remediation": (
                                    "split_skill_for_cap should have truncated; "
                                    "re-run generate or reduce frontmatter."
                                ),
                            }
                        )

    errors = sum(1 for f in findings if f.get("severity") == "error")
    warnings = sum(1 for f in findings if f.get("severity") == "warning")
    return {
        "schema": SCHEMA_VERSION,
        "kind": "validate_generated",
        "ok": errors == 0,
        "out_root": str(out),
        "harnesses": want,
        "plugin_count": plugin_count,
        "file_count": file_count,
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
    }


def format_generate(report: dict[str, Any]) -> str:
    lines = [
        f"marketplace generate  ok={report.get('ok')}  "
        f"plugins={report.get('plugin_count')}  "
        f"results={report.get('result_count')}  "
        f"files={report.get('count')}  out={report.get('out_root')}"
    ]
    for r in report.get("results") or []:
        c = r.get("counts") or {}
        n_tx = len(r.get("transforms") or [])
        lines.append(
            f"  [{r.get('harness')}] {r.get('plugin_id')}: "
            f"a={c.get('agents', 0)} s={c.get('skills', 0)} "
            f"c={c.get('commands', 0)} transforms={n_tx}"
        )
    return "\n".join(lines)


def format_validate_generated(report: dict[str, Any]) -> str:
    lines = [
        f"marketplace validate-generated  ok={report.get('ok')}  "
        f"plugins={report.get('plugin_count')}  "
        f"errors={report.get('errors')}  warnings={report.get('warnings')}  "
        f"out={report.get('out_root')}"
    ]
    for f in report.get("findings") or []:
        if f.get("severity") == "info":
            continue
        rem = f"  fix: {f['remediation']}" if f.get("remediation") else ""
        loc = f.get("path") or f.get("plugin_id") or f.get("harness") or ""
        lines.append(
            f"  [{f.get('severity')}] {loc}: {f.get('message')}{rem}"
        )
    if not report.get("findings"):
        lines.append("  (no findings)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Round-trip integrity (wshobson tools/tests/test_round_trip.py shape)
# ---------------------------------------------------------------------------

# Default harnesses for CI/Makefile smoke (fast, covers native + map-to-skills).
ROUND_TRIP_SMOKE_HARNESSES: tuple[str, ...] = ("claude", "codex", "copilot")


def source_component_counts(plugin: PluginInfo) -> dict[str, int]:
    """Count source Markdown components for a plugin (or thin skillpack).

    Prefer filesystem discovery (matches what generate emits). Fall back to
    ``PluginInfo`` list lengths when the path is missing (unit tests / catalog
    rows without a local tree).
    """
    sources = _component_source_files(plugin)
    agents = len(sources["agent"])
    skills = len(sources["skill"])
    commands = len(sources["command"])
    if agents == 0 and skills == 0 and commands == 0:
        if plugin.agents or plugin.skills or plugin.commands:
            return {
                "agents": len(plugin.agents),
                "skills": len(plugin.skills),
                "commands": len(plugin.commands),
            }
    return {"agents": agents, "skills": skills, "commands": commands}


def expected_counts_for_harness(
    plugin: PluginInfo,
    harness: str,
) -> dict[str, int]:
    """Expected post-adapter component counts for one harness (capability-aware).

    Codex/Copilot map commands → skills, so ``commands`` becomes 0 and those
    skills are added to the skills total. Non-native kinds count as 0.
    """
    src = source_component_counts(plugin)
    cap = capability(harness)
    agents = src["agents"] if cap.agents_native else 0
    skills = src["skills"] if cap.skills_native else 0
    commands = 0
    if src["commands"]:
        if cap.commands_native and not cap.commands_map_to_skills:
            commands = src["commands"]
        elif cap.commands_map_to_skills or not cap.commands_native:
            # Emitted as skills/cmd-*/SKILL.md
            if cap.skills_native:
                skills += src["commands"]
            # else dropped
    return {"agents": agents, "skills": skills, "commands": commands}


def count_generated_plugin(plugin_out: Path | str) -> dict[str, int]:
    """Count agents/skills/commands under a generated plugin tree."""
    root = Path(plugin_out)
    agents = (
        len(list((root / "agents").glob("*.md")))
        if (root / "agents").is_dir()
        else 0
    )
    skills = 0
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        skills = sum(
            1
            for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        )
    commands = (
        len(list((root / "commands").glob("*.md")))
        if (root / "commands").is_dir()
        else 0
    )
    return {"agents": agents, "skills": skills, "commands": commands}


def check_round_trip_counts(
    workdir: Path | str,
    out_root: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
    include_skillpacks: bool = True,
    harnesses: Optional[Iterable[str]] = None,
    plugin: Optional[str] = None,
    max_privilege: Optional[str] = None,
) -> dict[str, Any]:
    """Compare source→expected→generated component counts (no generate).

    Pattern: wshobson round-trip count integrity — catches silent skips/dupes
    when adapters drop or double-emit components.
    """
    workdir = Path(workdir).resolve()
    out = Path(out_root).resolve()
    want = list(harnesses) if harnesses is not None else list(SUPPORTED_HARNESSES)
    for h in want:
        if h not in SUPPORTED_HARNESSES:
            raise MarketplaceError(f"unsupported harness: {h}")

    plugins = list_plugins(
        workdir,
        plugins_dir=plugins_dir,
        include_skillpacks=include_skillpacks,
        packs_dir=packs_dir,
        max_privilege=max_privilege,
    )
    if plugin:
        plugins = [p for p in plugins if p.id == plugin]
        if not plugins:
            raise MarketplaceError(f"plugin not found: {plugin}")

    findings: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    mismatches = 0

    for p in plugins:
        src = source_component_counts(p)
        for h in want:
            expected = expected_counts_for_harness(p, h)
            pdir = out / h / "plugins" / p.id
            if not pdir.is_dir():
                findings.append(
                    {
                        "severity": "error",
                        "harness": h,
                        "plugin_id": p.id,
                        "message": f"missing generated plugin tree: {pdir}",
                        "remediation": (
                            f"Run: nexus marketplace generate --harness {h} "
                            f"--plugin {p.id}"
                        ),
                    }
                )
                mismatches += 1
                comparisons.append(
                    {
                        "harness": h,
                        "plugin_id": p.id,
                        "source": src,
                        "expected": expected,
                        "generated": None,
                        "ok": False,
                    }
                )
                continue
            got = count_generated_plugin(pdir)
            ok = got == expected
            row = {
                "harness": h,
                "plugin_id": p.id,
                "source": src,
                "expected": expected,
                "generated": got,
                "ok": ok,
            }
            comparisons.append(row)
            if not ok:
                mismatches += 1
                findings.append(
                    {
                        "severity": "error",
                        "harness": h,
                        "plugin_id": p.id,
                        "path": str(pdir.relative_to(out))
                        if out in pdir.parents or pdir == out
                        else str(pdir),
                        "message": (
                            f"count mismatch expected={expected} generated={got} "
                            f"(source={src})"
                        ),
                        "remediation": (
                            "Re-run generate; check adapters for silent skips "
                            "or duplicate emits (wshobson round-trip gate)."
                        ),
                    }
                )

    return {
        "schema": SCHEMA_VERSION,
        "kind": "round_trip_counts",
        "ok": mismatches == 0,
        "out_root": str(out),
        "harnesses": want,
        "plugin_count": len(plugins),
        "comparison_count": len(comparisons),
        "mismatches": mismatches,
        "errors": mismatches,
        "warnings": 0,
        "comparisons": comparisons,
        "findings": findings,
    }


def round_trip(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    out_root: Optional[Path | str] = None,
    harnesses: Optional[Iterable[str]] = None,
    include_skillpacks: bool = False,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
    clean: bool = True,
    plugin: Optional[str] = None,
    max_privilege: Optional[str] = None,
    fail_on_oversize: bool = True,
) -> dict[str, Any]:
    """Generate adapters, check source/expected count integrity, validate trees.

    Single CI-friendly gate combining:
      generate → check_round_trip_counts → validate_generated

    Defaults to ``include_skillpacks=False`` and ``clean=True`` so smoke runs
    stay fast and deterministic. Pattern only from wshobson ``test_round_trip``.
    """
    workdir = Path(workdir).resolve()
    want = (
        list(harnesses)
        if harnesses is not None
        else list(ROUND_TRIP_SMOKE_HARNESSES)
    )
    out = Path(out_root) if out_root else generate_adapters_root(workdir)
    out = out.resolve()

    gen = generate_adapters(
        workdir,
        plugins_dir=plugins_dir,
        out_root=out,
        harnesses=want,
        include_skillpacks=include_skillpacks,
        packs_dir=packs_dir,
        clean=clean,
        plugin=plugin,
        max_privilege=max_privilege,
    )
    counts = check_round_trip_counts(
        workdir,
        out,
        plugins_dir=plugins_dir,
        packs_dir=packs_dir,
        include_skillpacks=include_skillpacks,
        harnesses=want,
        plugin=plugin,
        max_privilege=max_privilege,
    )
    gate = validate_generated(
        out,
        harnesses=want,
        fail_on_oversize=fail_on_oversize,
    )

    ok = bool(gen.get("ok")) and bool(counts.get("ok")) and bool(gate.get("ok"))
    findings: list[dict[str, Any]] = []
    findings.extend(counts.get("findings") or [])
    findings.extend(gate.get("findings") or [])
    errors = int(counts.get("errors") or 0) + int(gate.get("errors") or 0)
    warnings = int(counts.get("warnings") or 0) + int(gate.get("warnings") or 0)

    return {
        "schema": SCHEMA_VERSION,
        "kind": "round_trip",
        "ok": ok,
        "out_root": str(out),
        "harnesses": want,
        "plugin_count": gen.get("plugin_count"),
        "generate": {
            "ok": gen.get("ok"),
            "plugin_count": gen.get("plugin_count"),
            "result_count": gen.get("result_count"),
            "count": gen.get("count"),
        },
        "counts": {
            "ok": counts.get("ok"),
            "mismatches": counts.get("mismatches"),
            "comparison_count": counts.get("comparison_count"),
            "errors": counts.get("errors"),
        },
        "validate_generated": {
            "ok": gate.get("ok"),
            "plugin_count": gate.get("plugin_count"),
            "errors": gate.get("errors"),
            "warnings": gate.get("warnings"),
        },
        "comparisons": counts.get("comparisons") or [],
        "findings": findings,
        "errors": errors,
        "warnings": warnings,
    }


def smoke_round_trip(workdir: Path | str = ".") -> dict[str, Any]:
    """Makefile/CI helper: round-trip seed plugins with default smoke harnesses."""
    workdir = Path(workdir).resolve()
    return round_trip(
        workdir,
        harnesses=list(ROUND_TRIP_SMOKE_HARNESSES),
        include_skillpacks=False,
        clean=True,
        fail_on_oversize=True,
    )


def format_round_trip(report: dict[str, Any]) -> str:
    gen = report.get("generate") or {}
    counts = report.get("counts") or {}
    gate = report.get("validate_generated") or {}
    lines = [
        f"marketplace round-trip  ok={report.get('ok')}  "
        f"plugins={report.get('plugin_count')}  "
        f"harnesses={','.join(report.get('harnesses') or [])}  "
        f"out={report.get('out_root')}"
    ]
    lines.append(
        f"  generate: ok={gen.get('ok')} files={gen.get('count')} "
        f"results={gen.get('result_count')}"
    )
    lines.append(
        f"  counts: ok={counts.get('ok')} mismatches={counts.get('mismatches')} "
        f"comparisons={counts.get('comparison_count')}"
    )
    lines.append(
        f"  validate-generated: ok={gate.get('ok')} "
        f"errors={gate.get('errors')} warnings={gate.get('warnings')}"
    )
    for f in report.get("findings") or []:
        if f.get("severity") == "info":
            continue
        rem = f"  fix: {f['remediation']}" if f.get("remediation") else ""
        loc = f.get("path") or f.get("plugin_id") or f.get("harness") or ""
        lines.append(f"  [{f.get('severity')}] {loc}: {f.get('message')}{rem}")
    bad = [c for c in (report.get("comparisons") or []) if not c.get("ok")]
    for c in bad[:12]:
        lines.append(
            f"  mismatch {c.get('harness')}/{c.get('plugin_id')}: "
            f"expected={c.get('expected')} generated={c.get('generated')}"
        )
    if report.get("ok") and not report.get("findings"):
        lines.append("  (round-trip clean)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Capability-aware portability + garden (wshobson shape)
# ---------------------------------------------------------------------------


def _utf8_size(path: Path) -> int:
    try:
        return len(path.read_bytes())
    except OSError:
        return 0


def _skill_paths_for_plugin(plugin: PluginInfo) -> list[tuple[str, Path]]:
    """Return (skill_name, path) for skills under a plugin or skillpack."""
    root = Path(plugin.path)
    out: list[tuple[str, Path]] = []
    if plugin.origin == "skillpack":
        skill_md = root / "SKILL.md"
        if skill_md.is_file():
            name = (plugin.skills[0] if plugin.skills else plugin.id)
            out.append((name, skill_md))
        return out
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            skill_md = d / "SKILL.md"
            if skill_md.is_file():
                name = _frontmatter_name(skill_md) or d.name
                out.append((name, skill_md))
    flat = root / "SKILL.md"
    if flat.is_file() and not out:
        out.append((_frontmatter_name(flat) or plugin.id, flat))
    return out


def _has_progressive_disclosure(text: str) -> bool:
    """Heuristic: skill documents when-to-use / success style sections."""
    lower = text.lower()
    markers = (
        "when to use",
        "when-to-use",
        "## success",
        "success criteria",
        "## rules",
        "## commands",
        "progressive",
    )
    return any(m in lower for m in markers)


def garden(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
    include_skillpacks: bool = True,
    skill_body_max_bytes: int = CODEX_SKILL_BODY_MAX_BYTES,
    fail_on_oversize: bool = False,
) -> dict[str, Any]:
    """Drift / progressive-disclosure garden over plugins (+ optional skillpacks).

    Pattern from wshobson ``doc_gardener`` / skill body caps (shape only):
    oversize skills, thin bodies, missing progressive-disclosure markers.
    Findings carry remediation strings. Oversize is warning unless
    ``fail_on_oversize`` (Codex hard cap spirit).
    """
    workdir = Path(workdir).resolve()
    plugins = list_plugins(
        workdir,
        plugins_dir=plugins_dir,
        include_skillpacks=include_skillpacks,
        packs_dir=packs_dir,
    )
    findings: list[dict[str, Any]] = []
    oversize = 0
    thin = 0
    no_disclosure = 0

    for p in plugins:
        if not (p.description or "").strip() and p.origin == "plugin":
            findings.append(
                {
                    "severity": "warning",
                    "kind": "missing_description",
                    "plugin_id": p.id,
                    "path": p.source or p.path,
                    "message": "plugin description empty",
                    "remediation": "Add description in plugin.json for marketplace listings.",
                }
            )
        for skill_name, skill_path in _skill_paths_for_plugin(p):
            rel = (
                f"{p.source}/{skill_path.name}"
                if p.origin == "skillpack"
                else f"{p.source}/{skill_path.relative_to(Path(p.path))}"
                if p.source
                else str(skill_path)
            )
            size = _utf8_size(skill_path)
            try:
                text = skill_path.read_text(encoding="utf-8")
            except OSError as e:
                findings.append(
                    {
                        "severity": "error",
                        "kind": "unreadable",
                        "plugin_id": p.id,
                        "path": rel,
                        "message": f"unreadable skill: {e}",
                        "remediation": "Fix file permissions.",
                    }
                )
                continue
            if skill_body_max_bytes > 0 and size > skill_body_max_bytes:
                oversize += 1
                sev = "error" if fail_on_oversize else "warning"
                findings.append(
                    {
                        "severity": sev,
                        "kind": "skill_oversize",
                        "plugin_id": p.id,
                        "path": rel,
                        "skill": skill_name,
                        "bytes": size,
                        "max_bytes": skill_body_max_bytes,
                        "message": (
                            f"skill body {size} bytes exceeds "
                            f"{skill_body_max_bytes} (Codex cap)"
                        ),
                        "remediation": (
                            "Move detail to references/ or split skills; "
                            "keep SKILL.md under 8 KiB for Codex portability."
                        ),
                    }
                )
            body = text
            # strip frontmatter for body length
            m = _FRONTMATTER_RE.search(text.replace("\r\n", "\n").replace("\r", "\n"))
            if m:
                body = text[m.end() :]
            if len(body.strip()) < 40:
                thin += 1
                findings.append(
                    {
                        "severity": "warning",
                        "kind": "skill_thin",
                        "plugin_id": p.id,
                        "path": rel,
                        "skill": skill_name,
                        "message": "skill body very short",
                        "remediation": "Document when to use, commands, rules, success.",
                    }
                )
            elif not _has_progressive_disclosure(text):
                no_disclosure += 1
                findings.append(
                    {
                        "severity": "info",
                        "kind": "progressive_disclosure",
                        "plugin_id": p.id,
                        "path": rel,
                        "skill": skill_name,
                        "message": "skill missing progressive-disclosure section markers",
                        "remediation": (
                            "Add 'When to use' / 'Rules' / 'Success' headings "
                            "(load detail on demand)."
                        ),
                    }
                )

    errors = sum(1 for f in findings if f.get("severity") == "error")
    warnings = sum(1 for f in findings if f.get("severity") == "warning")
    infos = sum(1 for f in findings if f.get("severity") == "info")
    return {
        "schema": SCHEMA_VERSION,
        "kind": "garden",
        "ok": errors == 0,
        "plugin_count": len(plugins),
        "skill_body_max_bytes": skill_body_max_bytes,
        "oversize_skills": oversize,
        "thin_skills": thin,
        "missing_disclosure": no_disclosure,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "findings": findings,
    }


def portability(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
    include_skillpacks: bool = True,
    harnesses: Optional[Iterable[str]] = None,
    fail_on_oversize: bool = False,
) -> dict[str, Any]:
    """Score plugins for multi-harness reuse (graceful degradation).

    For each plugin × harness:
    - native component support (agents/skills/commands)
    - command→skill remap when harness lacks commands_native
    - skill body size vs harness skill_body_max_bytes

    Returns a 0..1 score per plugin (mean of per-harness scores) and findings
    with remediations. Pattern: wshobson harness_portability dimension.
    """
    workdir = Path(workdir).resolve()
    want = list(harnesses) if harnesses is not None else list(SUPPORTED_HARNESSES)
    caps = list_capabilities(want)
    plugins = list_plugins(
        workdir,
        plugins_dir=plugins_dir,
        include_skillpacks=include_skillpacks,
        packs_dir=packs_dir,
    )
    plugin_rows: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []

    for p in plugins:
        skill_sizes = [
            (name, path, _utf8_size(path))
            for name, path in _skill_paths_for_plugin(p)
        ]
        per_harness: list[dict[str, Any]] = []
        scores: list[float] = []
        for cap in caps:
            score = 1.0
            notes: list[str] = []
            degradations: list[str] = []

            if p.agents and not cap.agents_native:
                score -= 0.35
                notes.append("agents not native")
                all_findings.append(
                    {
                        "severity": "warning",
                        "kind": "agents_not_native",
                        "plugin_id": p.id,
                        "harness": cap.harness_id,
                        "message": f"agents not native on {cap.harness_id}",
                        "remediation": "Emit agents as prose/skills or skip agent load.",
                    }
                )
            if p.skills and not cap.skills_native:
                score -= 0.4
                notes.append("skills not native")
                all_findings.append(
                    {
                        "severity": "warning",
                        "kind": "skills_not_native",
                        "plugin_id": p.id,
                        "harness": cap.harness_id,
                        "message": f"skills not native on {cap.harness_id}",
                        "remediation": "Provide harness-native skill transform.",
                    }
                )
            if p.commands and not cap.commands_native:
                if cap.commands_map_to_skills:
                    score -= 0.1
                    degradations.append("commands→skills")
                    notes.append("commands map to skills")
                else:
                    score -= 0.25
                    notes.append("commands not native")
                    all_findings.append(
                        {
                            "severity": "warning",
                            "kind": "commands_not_native",
                            "plugin_id": p.id,
                            "harness": cap.harness_id,
                            "message": f"commands not native on {cap.harness_id}",
                            "remediation": "Map commands to skills or drop commands for this harness.",
                        }
                    )

            for skill_name, skill_path, size in skill_sizes:
                cap_max = cap.skill_body_max_bytes
                if cap_max > 0 and size > cap_max:
                    score -= 0.3
                    notes.append(f"skill {skill_name} oversize")
                    sev = "error" if fail_on_oversize else "warning"
                    all_findings.append(
                        {
                            "severity": sev,
                            "kind": "skill_oversize",
                            "plugin_id": p.id,
                            "harness": cap.harness_id,
                            "skill": skill_name,
                            "path": str(skill_path),
                            "bytes": size,
                            "max_bytes": cap_max,
                            "message": (
                                f"skill {skill_name!r} is {size} bytes; "
                                f"{cap.harness_id} cap is {cap_max}"
                            ),
                            "remediation": (
                                "Trim SKILL.md or move detail to references/ "
                                f"for {cap.display_name} portability."
                            ),
                        }
                    )

            score = max(0.0, min(1.0, score))
            scores.append(score)
            per_harness.append(
                {
                    "harness": cap.harness_id,
                    "score": round(score, 3),
                    "degradations": degradations,
                    "notes": notes,
                    "plugin_marketplace": cap.plugin_marketplace,
                }
            )

        mean = round(sum(scores) / len(scores), 3) if scores else 1.0
        plugin_rows.append(
            {
                "id": p.id,
                "origin": p.origin,
                "score": mean,
                "counts": {
                    "agents": len(p.agents),
                    "skills": len(p.skills),
                    "commands": len(p.commands),
                },
                "skill_bytes": [
                    {"skill": n, "bytes": sz} for n, _p, sz in skill_sizes
                ],
                "harnesses": per_harness,
            }
        )

    errors = sum(1 for f in all_findings if f.get("severity") == "error")
    warnings = sum(1 for f in all_findings if f.get("severity") == "warning")
    mean_all = (
        round(sum(r["score"] for r in plugin_rows) / len(plugin_rows), 3)
        if plugin_rows
        else 1.0
    )
    return {
        "schema": SCHEMA_VERSION,
        "kind": "portability",
        "ok": errors == 0,
        "mean_score": mean_all,
        "plugin_count": len(plugin_rows),
        "harnesses": [c.harness_id for c in caps],
        "plugins": plugin_rows,
        "errors": errors,
        "warnings": warnings,
        "findings": all_findings,
    }


# ---------------------------------------------------------------------------
# Self-check (validate + collisions + skillpack + garden)
# ---------------------------------------------------------------------------


def self_check(
    workdir: Path | str,
    *,
    plugins_dir: str = DEFAULT_PLUGINS_DIR,
    packs_dir: str = DEFAULT_SKILLPACKS_DIR,
    include_skillpacks: bool = True,
    fail_on_collisions: bool = True,
    include_garden: bool = True,
    include_portability: bool = True,
    fail_on_oversize: bool = False,
) -> dict[str, Any]:
    """Fast structural gate for alive/self-check and CI.

    Combines plugin validate, cross-plugin collisions, optional thin
    skillpack index health, garden drift, and portability summary.
    Does not run pytest. Garden oversize is warning unless fail_on_oversize.
    """
    workdir = Path(workdir).resolve()
    val = validate_all(workdir, plugins_dir=plugins_dir)
    col = collisions(
        workdir,
        plugins_dir=plugins_dir,
        fail_on_duplicates=fail_on_collisions,
    )

    skillpack_findings: list[dict[str, Any]] = []
    skillpack_count = 0
    if include_skillpacks:
        for d in list_skillpack_dirs(workdir, packs_dir):
            skillpack_count += 1
            try:
                info = thin_plugin_from_skillpack(d)
            except MarketplaceError as e:
                skillpack_findings.append(
                    {
                        "severity": "error",
                        "pack_id": d.name,
                        "path": f"{packs_dir}/{d.name}/manifest.json",
                        "message": str(e),
                        "remediation": "Fix skillpack manifest JSON.",
                    }
                )
                continue
            if not (d / "SKILL.md").is_file():
                skillpack_findings.append(
                    {
                        "severity": "error",
                        "pack_id": info.id,
                        "path": f"{packs_dir}/{d.name}/SKILL.md",
                        "message": "skillpack missing SKILL.md",
                        "remediation": "Add SKILL.md with When to use / Commands / Rules / Success.",
                    }
                )
            if not (d / "manifest.json").is_file():
                skillpack_findings.append(
                    {
                        "severity": "error",
                        "pack_id": info.id,
                        "path": f"{packs_dir}/{d.name}/manifest.json",
                        "message": "skillpack missing manifest.json",
                        "remediation": "Add manifest.json with id, version, name.",
                    }
                )
            elif not info.version:
                skillpack_findings.append(
                    {
                        "severity": "warning",
                        "pack_id": info.id,
                        "path": f"{packs_dir}/{d.name}/manifest.json",
                        "message": "skillpack version empty",
                        "remediation": "Set version in manifest.json.",
                    }
                )

    sp_errors = sum(1 for f in skillpack_findings if f.get("severity") == "error")
    sp_warnings = sum(1 for f in skillpack_findings if f.get("severity") == "warning")

    garden_rep: dict[str, Any] = {}
    port_rep: dict[str, Any] = {}
    if include_garden:
        garden_rep = garden(
            workdir,
            plugins_dir=plugins_dir,
            packs_dir=packs_dir,
            include_skillpacks=include_skillpacks,
            fail_on_oversize=fail_on_oversize,
        )
    if include_portability:
        port_rep = portability(
            workdir,
            plugins_dir=plugins_dir,
            packs_dir=packs_dir,
            include_skillpacks=include_skillpacks,
            fail_on_oversize=fail_on_oversize,
        )

    garden_errors = int(garden_rep.get("errors") or 0) if garden_rep else 0
    port_errors = int(port_rep.get("errors") or 0) if port_rep else 0
    ok = (
        bool(val.get("ok"))
        and bool(col.get("ok"))
        and sp_errors == 0
        and garden_errors == 0
        and port_errors == 0
    )

    garden_warnings = int(garden_rep.get("warnings") or 0) if garden_rep else 0
    port_warnings = int(port_rep.get("warnings") or 0) if port_rep else 0

    return {
        "schema": SCHEMA_VERSION,
        "ok": ok,
        "validate": {
            "ok": val.get("ok"),
            "count": val.get("count"),
            "errors": val.get("errors"),
            "warnings": val.get("warnings"),
        },
        "collisions": {
            "ok": col.get("ok"),
            "cross_plugin": col.get("cross_plugin"),
            "duplicate_names": col.get("duplicate_names"),
            "errors": col.get("errors"),
        },
        "skillpacks": {
            "ok": sp_errors == 0,
            "count": skillpack_count,
            "errors": sp_errors,
            "warnings": sp_warnings,
            "findings": skillpack_findings,
        },
        "garden": {
            "ok": garden_rep.get("ok", True) if garden_rep else None,
            "oversize_skills": garden_rep.get("oversize_skills", 0) if garden_rep else 0,
            "errors": garden_errors,
            "warnings": garden_warnings,
            "infos": int(garden_rep.get("infos") or 0) if garden_rep else 0,
        }
        if include_garden
        else None,
        "portability": {
            "ok": port_rep.get("ok", True) if port_rep else None,
            "mean_score": port_rep.get("mean_score") if port_rep else None,
            "plugin_count": port_rep.get("plugin_count", 0) if port_rep else 0,
            "errors": port_errors,
            "warnings": port_warnings,
        }
        if include_portability
        else None,
        "errors": int(val.get("errors") or 0)
        + int(col.get("errors") or 0)
        + sp_errors
        + garden_errors
        + port_errors,
        "warnings": int(val.get("warnings") or 0)
        + int(col.get("warnings") or 0)
        + sp_warnings
        + garden_warnings
        + port_warnings,
    }


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


def format_list(rows: list[PluginInfo]) -> str:
    if not rows:
        return "(no plugins found)"
    lines = [
        f"{'ID':<22} {'VER':<8} {'PRIV':<6} {'ORIG':<9} "
        f"{'A':>3} {'S':>3} {'C':>3}  NAME",
        "-" * 84,
    ]
    for r in rows:
        lines.append(
            f"{r.id:<22} {r.version:<8} {r.privilege:<6} {r.origin:<9} "
            f"{len(r.agents):>3} {len(r.skills):>3} {len(r.commands):>3}  {r.name}"
        )
    return "\n".join(lines)


def format_self_check(report: dict[str, Any]) -> str:
    val = report.get("validate") or {}
    col = report.get("collisions") or {}
    sp = report.get("skillpacks") or {}
    garden_rep = report.get("garden") or {}
    port_rep = report.get("portability") or {}
    lines = [
        f"marketplace self-check  ok={report.get('ok')}  "
        f"errors={report.get('errors')}  warnings={report.get('warnings')}",
        (
            f"  validate: ok={val.get('ok')} plugins={val.get('count')} "
            f"errors={val.get('errors')} warnings={val.get('warnings')}"
        ),
        (
            f"  collisions: ok={col.get('ok')} cross={col.get('cross_plugin')} "
            f"dups={col.get('duplicate_names')}"
        ),
        (
            f"  skillpacks: ok={sp.get('ok')} count={sp.get('count')} "
            f"errors={sp.get('errors')} warnings={sp.get('warnings')}"
        ),
    ]
    if garden_rep:
        lines.append(
            f"  garden: ok={garden_rep.get('ok')} "
            f"oversize={garden_rep.get('oversize_skills')} "
            f"errors={garden_rep.get('errors')} "
            f"warnings={garden_rep.get('warnings')}"
        )
    if port_rep:
        lines.append(
            f"  portability: ok={port_rep.get('ok')} "
            f"mean_score={port_rep.get('mean_score')} "
            f"plugins={port_rep.get('plugin_count')} "
            f"warnings={port_rep.get('warnings')}"
        )
    for f in sp.get("findings") or []:
        if f.get("severity") == "info":
            continue
        rem = f"  fix: {f['remediation']}" if f.get("remediation") else ""
        lines.append(
            f"    [{f.get('severity')}] {f.get('pack_id')}: "
            f"{f.get('path')}: {f.get('message')}{rem}"
        )
    return "\n".join(lines)


def format_capabilities(matrix: dict[str, Any]) -> str:
    lines = [
        f"marketplace capabilities  count={matrix.get('count')}  "
        f"codex_skill_cap={matrix.get('codex_skill_body_max_bytes')}B"
    ]
    for h in matrix.get("harnesses") or []:
        cmds = "yes" if h.get("commands_native") else (
            "→skills" if h.get("commands_map_to_skills") else "no"
        )
        cap = h.get("skill_body_max_bytes") or 0
        cap_s = f"{cap}B" if cap else "none"
        lines.append(
            f"  {h.get('harness_id'):<10} skills={h.get('skills_native')} "
            f"agents={h.get('agents_native')} cmds={cmds} "
            f"mkt={h.get('plugin_marketplace')} skill_cap={cap_s}"
        )
    return "\n".join(lines)


def format_garden(report: dict[str, Any]) -> str:
    lines = [
        f"marketplace garden  ok={report.get('ok')}  "
        f"plugins={report.get('plugin_count')}  "
        f"oversize={report.get('oversize_skills')}  "
        f"errors={report.get('errors')}  warnings={report.get('warnings')}"
    ]
    for f in report.get("findings") or []:
        if f.get("severity") == "info":
            continue
        rem = f"  fix: {f['remediation']}" if f.get("remediation") else ""
        lines.append(
            f"  [{f.get('severity')}] {f.get('plugin_id')}: "
            f"{f.get('path')}: {f.get('message')}{rem}"
        )
    if not any(
        f.get("severity") != "info" for f in (report.get("findings") or [])
    ):
        lines.append("  (no garden issues)")
    return "\n".join(lines)


def format_portability(report: dict[str, Any]) -> str:
    lines = [
        f"marketplace portability  ok={report.get('ok')}  "
        f"mean_score={report.get('mean_score')}  "
        f"plugins={report.get('plugin_count')}  "
        f"warnings={report.get('warnings')}"
    ]
    for p in report.get("plugins") or []:
        lines.append(
            f"  {p.get('id')}: score={p.get('score')} "
            f"a={p['counts']['agents']} s={p['counts']['skills']} "
            f"c={p['counts']['commands']}"
        )
        for h in p.get("harnesses") or []:
            deg = ",".join(h.get("degradations") or []) or "—"
            if h.get("score", 1) < 1.0 or (h.get("degradations") or []):
                lines.append(
                    f"    {h.get('harness')}: score={h.get('score')} "
                    f"degrade={deg}"
                )
    for f in report.get("findings") or []:
        if f.get("severity") == "info":
            continue
        rem = f"  fix: {f['remediation']}" if f.get("remediation") else ""
        lines.append(
            f"  [{f.get('severity')}] {f.get('plugin_id')}"
            f"/{f.get('harness')}: {f.get('message')}{rem}"
        )
    return "\n".join(lines)


def format_validate(report: dict[str, Any]) -> str:
    lines = [
        f"marketplace validate  ok={report.get('ok')}  "
        f"plugins={report.get('count')}  "
        f"errors={report.get('errors')}  warnings={report.get('warnings')}"
    ]
    for p in report.get("plugins") or []:
        mark = "OK" if p.get("ok") else "FAIL"
        lines.append(f"  [{mark}] {p.get('plugin_id')}")
        for f in p.get("findings") or []:
            if f.get("severity") == "info":
                continue
            rem = f"  fix: {f['remediation']}" if f.get("remediation") else ""
            lines.append(
                f"    [{f.get('severity')}] {f.get('path')}: {f.get('message')}{rem}"
            )
    return "\n".join(lines)


def format_collisions(report: dict[str, Any]) -> str:
    lines = [
        f"marketplace collisions  ok={report.get('ok')}  "
        f"dups={report.get('duplicate_names')}  "
        f"cross={report.get('cross_plugin')}  "
        f"components={report.get('component_count')}"
    ]
    for d in report.get("collisions") or []:
        scope = "cross-plugin" if d.get("cross_plugin") else "intra-plugin"
        lines.append(
            f"  [{scope}] {d.get('kind')}:{d.get('name')} "
            f"plugins={','.join(d.get('plugins') or [])} count={d.get('count')}"
        )
    if not report.get("collisions"):
        lines.append("  (no collisions)")
    return "\n".join(lines)


def format_export(report: dict[str, Any]) -> str:
    lines = [
        f"marketplace export  ok={report.get('ok')}  "
        f"files={report.get('count')}  out={report.get('out_root')}"
    ]
    totals = report.get("totals") or {}
    if totals:
        lines.append(
            f"  totals: plugins={totals.get('plugins')} "
            f"agents={totals.get('agents')} "
            f"skills={totals.get('skills')} "
            f"commands={totals.get('commands')}"
        )
    for w in report.get("written") or []:
        lines.append(f"  wrote {w}")
    return "\n".join(lines)


def format_catalog(catalog: dict[str, Any]) -> str:
    totals = catalog.get("totals") or {}
    lines = [
        f"marketplace catalog  {catalog.get('name')}  "
        f"plugins={totals.get('plugins', 0)}  "
        f"agents={totals.get('agents', 0)}  "
        f"skills={totals.get('skills', 0)}  "
        f"commands={totals.get('commands', 0)}"
    ]
    for p in catalog.get("plugins") or []:
        c = p.get("counts") or {}
        lines.append(
            f"  {p.get('name')}: a={c.get('agents', 0)} "
            f"s={c.get('skills', 0)} c={c.get('commands', 0)}  "
            f"{(p.get('description') or '')[:60]}"
        )
    return "\n".join(lines)
