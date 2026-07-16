"""OpenAPI-ish MCP tool catalog export (P2.2).

First-apply slice (docs/LATEST_IMPROVE_PLAN.md P2.2):

  MCP TOOLS[] (single source of truth)
    → privilege-tagged catalog (nexus.tool_catalog/v1)
    → OpenAPI 3.1 document (paths = POST /tools/{name})
    → validate / export / least-privilege filter
    → CLI + MCP + HTTP /openapi.json parity

Patterns (shape only, not vendored trees):
- builderz-labs/mission-control — openapi.json surface + ops CLI/MCP parity
- arXiv 2606.20023 — privilege ladder on tools (least-privilege signal)
- IBM/AssetOpsBench — eval/smoke harness shape (catalog validate as smoke)
- Network-AI — dual packaging / catalog export hygiene
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .persist import atomic_write_json, atomic_write_text

SCHEMA_VERSION = "nexus.tool_catalog/v1"
OPENAPI_VERSION = "3.1.0"
DEFAULT_OUT_DIR = ".nexus_state/tool_catalog"

# Privilege ladder (shared shape with skillpacks / arXiv 2606.20023).
PRIVILEGE_LEVELS: tuple[str, ...] = ("read", "write", "ops", "admin")
PRIVILEGE_RANK = {p: i for i, p in enumerate(PRIVILEGE_LEVELS)}

# Explicit privilege map for known MCP tools. Unknown tools default to "ops"
# (fail closed — operators must label new tools).
TOOL_PRIVILEGE: dict[str, str] = {
    # workspace FS / chat
    "list_project_files": "read",
    "read_project_file": "read",
    "write_to_project": "write",
    "send_to_workspace": "write",
    "read_workspace_chat": "read",
    # status / inspect
    "nexus_status": "read",
    "bus_status": "read",
    "list_platforms": "read",
    "github_community_status": "read",
    "vault_status": "read",
    "list_graded_candidates": "read",
    "get_grade": "read",
    "index_workspace": "ops",
    "search_evidence": "read",
    "apply_select": "read",
    "mine_eval_slice": "read",
    "improve_board": "read",
    "work_ledger": "ops",
    "ledger_append": "write",
    "ledger_list": "read",
    "grade_get": "read",
    "get_run_checkpoint": "read",
    "get_run_status": "read",
    "run_task": "ops",
    "get_task_status": "read",
    "context_pack": "read",
    "context_get": "read",
    "tool_catalog": "read",
    "mcp_eval": "read",
    # side-effecting ops
    "run_project_checks": "ops",
    "github_scout": "ops",
    "github_loop": "ops",
    "platforms_connect": "ops",
    "apply_phase": "ops",
    "context_set": "write",
    "handoff": "write",
    "demo_loop": "ops",
    "ops_control": "ops",
    "gap_board": "ops",
    "skillpacks": "ops",
}


class CatalogError(ValueError):
    """Structural error in the tool catalog."""


@dataclass
class Finding:
    severity: str  # error | warning | info
    tool: str
    path: str
    message: str
    remediation: str = ""

    def render(self) -> str:
        tail = f"  fix: {self.remediation}" if self.remediation else ""
        return f"[{self.severity}] {self.tool}: {self.path}: {self.message}{tail}"


@dataclass
class ValidateReport:
    schema: str = SCHEMA_VERSION
    ok: bool = True
    findings: list[Finding] = field(default_factory=list)

    def add(
        self,
        severity: str,
        tool: str,
        path: str,
        message: str,
        remediation: str = "",
    ) -> None:
        self.findings.append(
            Finding(
                severity=severity,
                tool=tool,
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
            "ok": self.ok,
            "errors": sum(1 for f in self.findings if f.severity == "error"),
            "warnings": sum(1 for f in self.findings if f.severity == "warning"),
            "findings": [asdict(f) for f in self.findings],
        }


@dataclass
class ToolEntry:
    name: str
    description: str
    privilege: str
    required: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "privilege": self.privilege,
            "required": list(self.required),
            "properties": list(self.properties),
            "tags": list(self.tags),
            "inputSchema": self.input_schema,
        }


def _norm_privilege(raw: Any, *, default: str = "ops") -> str:
    if raw is None or raw == "":
        return default
    s = str(raw).strip().lower()
    if s not in PRIVILEGE_RANK:
        raise CatalogError(
            f"privilege must be one of {list(PRIVILEGE_LEVELS)}, got {raw!r}"
        )
    return s


def privilege_for(name: str, override: Optional[str] = None) -> str:
    """Resolve privilege for a tool name (explicit map, else fail-closed ops)."""
    if override is not None:
        return _norm_privilege(override)
    if name in TOOL_PRIVILEGE:
        return TOOL_PRIVILEGE[name]
    return "ops"


def allowed_by_max(privilege: str, max_privilege: Optional[str]) -> bool:
    if max_privilege is None:
        return True
    max_p = _norm_privilege(max_privilege, default="admin")
    return PRIVILEGE_RANK[privilege] <= PRIVILEGE_RANK[max_p]


def load_mcp_tools() -> list[dict[str, Any]]:
    """Import live MCP TOOLS list (single source of truth)."""
    from . import mcp_server

    tools = getattr(mcp_server, "TOOLS", None)
    if not isinstance(tools, list):
        raise CatalogError("mcp_server.TOOLS missing or not a list")
    return list(tools)


def _entry_from_tool(tool: dict[str, Any]) -> ToolEntry:
    name = str(tool.get("name") or "").strip()
    if not name:
        raise CatalogError("tool missing name")
    desc = str(tool.get("description") or "").strip()
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    if not isinstance(schema, dict):
        raise CatalogError(f"tool {name}: inputSchema must be object")
    props = schema.get("properties") or {}
    if props is None:
        props = {}
    if not isinstance(props, dict):
        raise CatalogError(f"tool {name}: properties must be object")
    required = schema.get("required") or []
    if not isinstance(required, list):
        raise CatalogError(f"tool {name}: required must be list")
    priv = privilege_for(name, tool.get("x-nexus-privilege") or tool.get("privilege"))
    tags = [priv]
    if "github" in name:
        tags.append("github")
    if name.startswith("get_") or name.startswith("list_") or name.endswith("_status"):
        tags.append("inspect")
    return ToolEntry(
        name=name,
        description=desc,
        privilege=priv,
        required=[str(r) for r in required],
        properties=sorted(str(k) for k in props.keys()),
        input_schema=dict(schema),
        tags=tags,
    )


def build_entries(
    tools: Optional[Iterable[dict[str, Any]]] = None,
    *,
    max_privilege: Optional[str] = None,
) -> list[ToolEntry]:
    raw = list(tools) if tools is not None else load_mcp_tools()
    entries: list[ToolEntry] = []
    for t in raw:
        if not isinstance(t, dict):
            raise CatalogError("each tool must be a dict")
        e = _entry_from_tool(t)
        if allowed_by_max(e.privilege, max_privilege):
            entries.append(e)
    entries.sort(key=lambda x: (PRIVILEGE_RANK.get(x.privilege, 99), x.name))
    return entries


def build_catalog(
    tools: Optional[Iterable[dict[str, Any]]] = None,
    *,
    max_privilege: Optional[str] = None,
    server_name: Optional[str] = None,
    server_version: Optional[str] = None,
) -> dict[str, Any]:
    """Build nexus.tool_catalog/v1 document from MCP tools."""
    from . import mcp_server

    entries = build_entries(tools, max_privilege=max_privilege)
    by_priv: dict[str, int] = {p: 0 for p in PRIVILEGE_LEVELS}
    for e in entries:
        by_priv[e.privilege] = by_priv.get(e.privilege, 0) + 1
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "server": server_name or getattr(mcp_server, "SERVER_NAME", "nexus-workspace"),
        "version": server_version
        or getattr(mcp_server, "SERVER_VERSION", "0.0.0"),
        "protocol": getattr(mcp_server, "PROTOCOL_VERSION", "2024-11-05"),
        "tool_count": len(entries),
        "by_privilege": by_priv,
        "tools": [e.to_dict() for e in entries],
    }


def _json_schema_to_openapi_body(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize MCP inputSchema into an OpenAPI request body schema."""
    out = dict(schema) if schema else {"type": "object", "properties": {}}
    if "type" not in out:
        out["type"] = "object"
    if out.get("type") == "object" and "properties" not in out:
        out["properties"] = {}
    return out


def build_openapi(
    tools: Optional[Iterable[dict[str, Any]]] = None,
    *,
    max_privilege: Optional[str] = None,
    server_name: Optional[str] = None,
    server_version: Optional[str] = None,
) -> dict[str, Any]:
    """Build OpenAPI 3.1 document from MCP tools (mission-control-shaped export)."""
    from . import mcp_server

    name = server_name or getattr(mcp_server, "SERVER_NAME", "nexus-workspace")
    version = server_version or getattr(mcp_server, "SERVER_VERSION", "0.0.0")
    entries = build_entries(tools, max_privilege=max_privilege)

    tags = [
        {"name": p, "description": f"Tools with privilege ≤ {p}" if p != "admin" else "Admin tools"}
        for p in PRIVILEGE_LEVELS
        if any(e.privilege == p for e in entries)
    ]

    paths: dict[str, Any] = {}
    for e in entries:
        path_key = f"/tools/{e.name}"
        paths[path_key] = {
            "post": {
                "operationId": e.name,
                "summary": e.description[:120] if e.description else e.name,
                "description": e.description,
                "tags": [e.privilege],
                "x-nexus-privilege": e.privilege,
                "x-nexus-tags": e.tags,
                "requestBody": {
                    "required": bool(e.required),
                    "content": {
                        "application/json": {
                            "schema": _json_schema_to_openapi_body(e.input_schema),
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "MCP tool result (content + isError)",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "content": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "type": {"type": "string"},
                                                    "text": {"type": "string"},
                                                },
                                            },
                                        },
                                        "isError": {"type": "boolean"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }

    # Also document list + call envelope for HTTP demo API
    paths["/tools"] = {
        "get": {
            "operationId": "list_tools",
            "summary": "List MCP tools (raw MCP descriptors)",
            "tags": ["read"],
            "x-nexus-privilege": "read",
            "responses": {
                "200": {
                    "description": "Tool list",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "tools": {"type": "array", "items": {"type": "object"}},
                                },
                            }
                        }
                    },
                }
            },
        }
    }
    paths["/tools/call"] = {
        "post": {
            "operationId": "call_tool",
            "summary": "Call an MCP tool by name (HTTP demo API)",
            "tags": ["ops"],
            "x-nexus-privilege": "ops",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": {"type": "string"},
                                "arguments": {"type": "object"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": {"description": "Tool result"},
            },
        }
    }
    paths["/openapi.json"] = {
        "get": {
            "operationId": "get_openapi",
            "summary": "This OpenAPI document",
            "tags": ["read"],
            "x-nexus-privilege": "read",
            "responses": {"200": {"description": "OpenAPI 3.1 JSON"}},
        }
    }

    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": f"{name} MCP Tools",
            "version": version,
            "description": (
                "NEXUS Workspace MCP tool catalog (auto-generated from TOOLS[]). "
                "Patterns: mission-control openapi export; privilege ladder from "
                "arXiv 2606.20023. Not a full REST product API."
            ),
        },
        "servers": [
            {"url": "http://127.0.0.1:8765", "description": "Local HTTP tools API"},
        ],
        "tags": tags,
        "paths": paths,
        "x-nexus-catalog": {
            "schema": SCHEMA_VERSION,
            "tool_count": len(entries),
            "privilege_levels": list(PRIVILEGE_LEVELS),
        },
    }


def validate_tools(
    tools: Optional[Iterable[dict[str, Any]]] = None,
) -> ValidateReport:
    """Structural + privilege validate of the live (or provided) tool list."""
    rep = ValidateReport()
    try:
        raw = list(tools) if tools is not None else load_mcp_tools()
    except CatalogError as e:
        rep.add("error", "*", "TOOLS", str(e), "define mcp_server.TOOLS as list")
        return rep

    if not raw:
        rep.add("error", "*", "TOOLS", "empty tool list", "register at least one tool")
        return rep

    seen: set[str] = set()
    for i, t in enumerate(raw):
        loc = f"TOOLS[{i}]"
        if not isinstance(t, dict):
            rep.add("error", f"#{i}", loc, "tool is not an object")
            continue
        name = str(t.get("name") or "").strip()
        if not name:
            rep.add("error", f"#{i}", f"{loc}.name", "missing name")
            continue
        if name in seen:
            rep.add("error", name, f"{loc}.name", "duplicate tool name")
        seen.add(name)

        if not str(t.get("description") or "").strip():
            rep.add(
                "warning",
                name,
                f"{loc}.description",
                "empty description",
                "document the tool for clients",
            )

        schema = t.get("inputSchema")
        if schema is None:
            rep.add(
                "error",
                name,
                f"{loc}.inputSchema",
                "missing inputSchema",
                "add JSON Schema object",
            )
            continue
        if not isinstance(schema, dict):
            rep.add("error", name, f"{loc}.inputSchema", "inputSchema must be object")
            continue
        stype = schema.get("type")
        if stype not in (None, "object"):
            rep.add(
                "warning",
                name,
                f"{loc}.inputSchema.type",
                f"expected type=object, got {stype!r}",
            )
        props = schema.get("properties")
        if props is not None and not isinstance(props, dict):
            rep.add("error", name, f"{loc}.inputSchema.properties", "must be object")
            props = {}
        props = props or {}
        required = schema.get("required") or []
        if required and not isinstance(required, list):
            rep.add("error", name, f"{loc}.inputSchema.required", "must be list")
            required = []
        for r in required:
            if str(r) not in props:
                rep.add(
                    "error",
                    name,
                    f"{loc}.inputSchema.required",
                    f"required field {r!r} not in properties",
                    "add property or drop from required",
                )

        if name not in TOOL_PRIVILEGE and not (
            t.get("x-nexus-privilege") or t.get("privilege")
        ):
            rep.add(
                "warning",
                name,
                "privilege",
                "no explicit privilege map entry (defaults to ops)",
                f"add TOOL_PRIVILEGE[{name!r}] = 'read'|'write'|'ops'|'admin'",
            )

    # OpenAPI round-trip smoke: every tool becomes a path
    try:
        openapi = build_openapi(raw)
        for name in seen:
            if f"/tools/{name}" not in openapi.get("paths", {}):
                rep.add(
                    "error",
                    name,
                    "openapi.paths",
                    "missing OpenAPI path after export",
                )
    except CatalogError as e:
        rep.add("error", "*", "openapi", str(e))

    return rep


def catalog_root(workdir: Path | str, out_dir: str = DEFAULT_OUT_DIR) -> Path:
    return Path(workdir).resolve() / out_dir


def export_catalog(
    workdir: Path | str,
    *,
    out_dir: str = DEFAULT_OUT_DIR,
    max_privilege: Optional[str] = None,
    tools: Optional[Iterable[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Write catalog.json + openapi.json (+ summary.md) under out_dir."""
    root = catalog_root(workdir, out_dir)
    root.mkdir(parents=True, exist_ok=True)

    catalog = build_catalog(tools, max_privilege=max_privilege)
    openapi = build_openapi(tools, max_privilege=max_privilege)
    rep = validate_tools(tools if tools is not None else None)

    catalog_path = root / "catalog.json"
    openapi_path = root / "openapi.json"
    summary_path = root / "summary.md"
    validate_path = root / "validate.json"

    atomic_write_json(catalog_path, catalog)
    atomic_write_json(openapi_path, openapi)
    atomic_write_json(validate_path, rep.to_dict())
    atomic_write_text(summary_path, format_summary(catalog))

    return {
        "schema": SCHEMA_VERSION,
        "ok": rep.ok,
        "out_dir": str(root),
        "files": {
            "catalog": str(catalog_path),
            "openapi": str(openapi_path),
            "summary": str(summary_path),
            "validate": str(validate_path),
        },
        "tool_count": catalog["tool_count"],
        "by_privilege": catalog["by_privilege"],
        "validate": rep.to_dict(),
    }


def format_list(entries: list[ToolEntry]) -> str:
    if not entries:
        return "(no tools)"
    lines = [
        f"{'PRIV':<6} {'NAME':<28} {'REQ':<20} DESCRIPTION",
        f"{'----':<6} {'----':<28} {'---':<20} -----------",
    ]
    for e in entries:
        req = ",".join(e.required) if e.required else "-"
        desc = (e.description or "").replace("\n", " ")
        if len(desc) > 60:
            desc = desc[:57] + "..."
        lines.append(f"{e.privilege:<6} {e.name:<28} {req:<20} {desc}")
    lines.append(f"\n{len(entries)} tools")
    return "\n".join(lines)


def format_summary(catalog: dict[str, Any]) -> str:
    lines = [
        f"# NEXUS tool catalog ({catalog.get('schema')})",
        "",
        f"- server: `{catalog.get('server')}` v{catalog.get('version')}",
        f"- generated: {catalog.get('generated_at')}",
        f"- tools: **{catalog.get('tool_count', 0)}**",
        f"- by privilege: `{json.dumps(catalog.get('by_privilege') or {})}`",
        "",
        "| privilege | name | required |",
        "|-----------|------|----------|",
    ]
    for t in catalog.get("tools") or []:
        req = ", ".join(t.get("required") or []) or "—"
        lines.append(
            f"| {t.get('privilege')} | `{t.get('name')}` | {req} |"
        )
    lines.append("")
    lines.append("Generated by `nexus tools export` (P2.2 OpenAPI tool catalog).")
    lines.append("")
    return "\n".join(lines)


def format_validate(rep: ValidateReport | dict[str, Any]) -> str:
    data = rep.to_dict() if isinstance(rep, ValidateReport) else rep
    status = "OK" if data.get("ok") else "FAIL"
    lines = [
        f"tool catalog validate: {status}",
        f"  errors={data.get('errors', 0)} warnings={data.get('warnings', 0)}",
    ]
    for f in data.get("findings") or []:
        if isinstance(f, dict):
            lines.append(
                f"  [{f.get('severity')}] {f.get('tool')}: {f.get('path')}: {f.get('message')}"
            )
        else:
            lines.append(f"  {f}")
    return "\n".join(lines)


def format_export(result: dict[str, Any]) -> str:
    status = "OK" if result.get("ok") else "FAIL (validate)"
    lines = [
        f"tool catalog export: {status}",
        f"  out: {result.get('out_dir')}",
        f"  tools: {result.get('tool_count')}",
        f"  privilege: {json.dumps(result.get('by_privilege') or {})}",
    ]
    files = result.get("files") or {}
    for k, v in files.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)
