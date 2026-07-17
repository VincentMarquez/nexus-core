"""Unified agent interaction protocol (arXiv 2602.22953 × wshobson/agents).

Paper: *General Agent Evaluation*
https://arxiv.org/abs/2602.22953v2

GitHub pattern (shape only — not a vendored tree):
  wshobson/agents — single-source Markdown marketplace of plugins with
  agents/*.md, skills/*/SKILL.md, commands/*.md (+ multi-harness adapters).

Novel hybrid (portfolio cross_pattern):

  OpenAI tool_calls / Anthropic tool_use / MCP / CLI argv
                │
                ▼
         ┌──────────────────┐   ProtocolMessage envelope
         │ Agent Protocol   │ ──► surface-agnostic invoke/result
         └──────────────────┘   (offline normalize / validate / convert)
                │
                ├── marketplace targets (agent|skill|command)
                ├── multi_llm_agent PlanStep / ToolPlan
                └── ProtocolTranscript (eval-oriented interaction log)

General-purpose agents span heterogeneous protocols (function-calling,
CLI, plugin marketplaces). This module is a thin **unifying protocol
layer**: one message envelope + target surface model, plus converters
so Planner/Caller and marketplace components speak the same dialect.

Offline-first: pure normalize/validate/convert; no live LLM, no side
effects. Marketplace discovery reuses in-tree ``marketplace`` /
``marketplace_planner`` (shape only).
"""

from __future__ import annotations

import json
import shlex
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

SCHEMA = "nexus.agent_protocol/v1"
PAPER = "arxiv:2602.22953v2"
SOURCE_PATTERN = "wshobson/agents"

# Interaction surfaces (what is being addressed)
SURFACE_TOOL = "tool"
SURFACE_CLI = "cli"
SURFACE_MCP = "mcp"
SURFACE_AGENT = "agent"
SURFACE_SKILL = "skill"
SURFACE_COMMAND = "command"

SURFACES: frozenset[str] = frozenset(
    {
        SURFACE_TOOL,
        SURFACE_CLI,
        SURFACE_MCP,
        SURFACE_AGENT,
        SURFACE_SKILL,
        SURFACE_COMMAND,
    }
)

MARKETPLACE_SURFACES: frozenset[str] = frozenset(
    {SURFACE_AGENT, SURFACE_SKILL, SURFACE_COMMAND}
)

# Message kinds (protocol verbs)
KIND_INVOKE = "invoke"
KIND_RESULT = "result"
KIND_ERROR = "error"
KIND_OBSERVE = "observe"

KINDS: frozenset[str] = frozenset(
    {KIND_INVOKE, KIND_RESULT, KIND_ERROR, KIND_OBSERVE}
)

# Source formats (wire dialects we can normalize from)
FMT_GENERIC = "generic"
FMT_OPENAI = "openai"
FMT_ANTHROPIC = "anthropic"
FMT_CLI = "cli"
FMT_MCP = "mcp"
FMT_MARKETPLACE = "marketplace"
FMT_PLAN_STEP = "plan_step"

SOURCE_FORMATS: frozenset[str] = frozenset(
    {
        FMT_GENERIC,
        FMT_OPENAI,
        FMT_ANTHROPIC,
        FMT_CLI,
        FMT_MCP,
        FMT_MARKETPLACE,
        FMT_PLAN_STEP,
    }
)

ROLES: frozenset[str] = frozenset({"agent", "user", "system", "tool", "evaluator"})


class ProtocolError(ValueError):
    """Protocol message invalid or unknown wire dialect."""


# ── data ────────────────────────────────────────────────────────────────────


def _new_id(prefix: str = "msg") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class ProtocolTarget:
    """Who/what a protocol message addresses (surface-agnostic).

    Marketplace components use ``surface`` in {agent, skill, command} and
    optional ``plugin_id`` (wshobson plugin id). Tools/CLI/MCP use the
    matching surface with a bare name.
    """

    surface: str
    name: str
    plugin_id: str = ""
    privilege: str = "read"
    path: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        self.surface = str(self.surface or "").strip().lower() or SURFACE_TOOL
        self.name = str(self.name or "").strip()
        self.plugin_id = str(self.plugin_id or "").strip()
        self.privilege = str(self.privilege or "read").strip().lower() or "read"
        self.path = str(self.path or "").strip()
        self.description = str(self.description or "")
        if self.surface not in SURFACES:
            raise ProtocolError(
                f"unknown surface {self.surface!r}; expected one of {sorted(SURFACES)}"
            )
        if not self.name:
            raise ProtocolError("target.name must be non-empty")

    @property
    def tool_id(self) -> str:
        """Stable id shared with marketplace_planner / multi_llm_agent steps.

        Marketplace: ``agent:name@plugin`` (plugin optional).
        CLI: ``cli:name``. MCP: ``mcp:name``. Tool: bare ``name``.
        """
        if self.surface in MARKETPLACE_SURFACES:
            if self.plugin_id:
                return f"{self.surface}:{self.name}@{self.plugin_id}"
            return f"{self.surface}:{self.name}"
        if self.surface == SURFACE_CLI:
            return f"cli:{self.name}"
        if self.surface == SURFACE_MCP:
            return f"mcp:{self.name}"
        return self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "name": self.name,
            "plugin_id": self.plugin_id,
            "privilege": self.privilege,
            "path": self.path,
            "description": self.description,
            "tool_id": self.tool_id,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "ProtocolTarget":
        if not isinstance(d, dict):
            raise ProtocolError(f"target must be a dict, got {type(d).__name__}")
        # Accept tool_id shorthand
        tool_id = str(d.get("tool_id") or d.get("id") or "").strip()
        surface = str(d.get("surface") or d.get("kind") or "").strip().lower()
        name = str(d.get("name") or d.get("tool") or d.get("function") or "").strip()
        plugin_id = str(d.get("plugin_id") or d.get("plugin") or "").strip()
        if tool_id and (not name or not surface):
            parsed = parse_tool_id(tool_id)
            surface = surface or parsed["surface"]
            name = name or parsed["name"]
            plugin_id = plugin_id or parsed["plugin_id"]
        return cls(
            surface=surface or SURFACE_TOOL,
            name=name,
            plugin_id=plugin_id,
            privilege=str(d.get("privilege") or "read"),
            path=str(d.get("path") or ""),
            description=str(d.get("description") or d.get("desc") or ""),
        )


@dataclass
class ProtocolMessage:
    """One agent interaction in the unifying protocol envelope.

    Abstracts specific tool-calling / CLI dialects into a single shape for
    planning, execution handoff, and evaluation transcripts.
    """

    kind: str
    target: ProtocolTarget
    id: str = field(default_factory=lambda: _new_id("msg"))
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str = ""
    role: str = "agent"
    source_format: str = FMT_GENERIC
    schema: str = SCHEMA
    paper: str = PAPER
    created_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.kind = str(self.kind or "").strip().lower()
        if self.kind not in KINDS:
            raise ProtocolError(
                f"unknown kind {self.kind!r}; expected one of {sorted(KINDS)}"
            )
        if not isinstance(self.target, ProtocolTarget):
            raise ProtocolError("target must be a ProtocolTarget")
        if not isinstance(self.args, dict):
            raise ProtocolError(f"args must be a dict, got {type(self.args).__name__}")
        self.role = str(self.role or "agent").strip().lower() or "agent"
        if self.role not in ROLES:
            self.role = "agent"
        self.source_format = (
            str(self.source_format or FMT_GENERIC).strip().lower() or FMT_GENERIC
        )
        if self.source_format not in SOURCE_FORMATS:
            self.source_format = FMT_GENERIC
        self.error = str(self.error or "")
        if not isinstance(self.meta, dict):
            self.meta = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "paper": self.paper,
            "id": self.id,
            "kind": self.kind,
            "role": self.role,
            "source_format": self.source_format,
            "target": self.target.to_dict(),
            "args": dict(self.args or {}),
            "result": self.result,
            "error": self.error,
            "created_at": float(self.created_at),
            "meta": dict(self.meta or {}),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, d: Any) -> "ProtocolMessage":
        if not isinstance(d, dict):
            raise ProtocolError(f"message must be a dict, got {type(d).__name__}")
        target_raw = d.get("target")
        if target_raw is None and (
            d.get("tool") or d.get("name") or d.get("function") or d.get("tool_id")
        ):
            target_raw = {
                "surface": d.get("surface") or d.get("kind_surface") or SURFACE_TOOL,
                "name": d.get("tool") or d.get("name") or d.get("function") or "",
                "plugin_id": d.get("plugin_id") or "",
                "tool_id": d.get("tool_id") or "",
                "privilege": d.get("privilege") or "read",
                "path": d.get("path") or "",
                "description": d.get("description") or "",
            }
        if target_raw is None:
            raise ProtocolError("message missing target")
        target = (
            target_raw
            if isinstance(target_raw, ProtocolTarget)
            else ProtocolTarget.from_dict(target_raw)
        )
        args = d.get("args")
        if args is None:
            args = d.get("arguments") or d.get("parameters") or d.get("input") or {}
        if not isinstance(args, dict):
            # CLI sometimes packs argv as a list
            if isinstance(args, list):
                args = {"argv": [str(a) for a in args]}
            else:
                raise ProtocolError(f"args must be object, got {type(args).__name__}")
        kind = str(d.get("kind") or d.get("type") or KIND_INVOKE).strip().lower()
        # Heuristic: result/error payload without explicit kind
        if kind not in KINDS:
            if d.get("error"):
                kind = KIND_ERROR
            elif "result" in d and d.get("result") is not None:
                kind = KIND_RESULT
            else:
                kind = KIND_INVOKE
        return cls(
            id=str(d.get("id") or _new_id("msg")),
            kind=kind,
            target=target,
            args=dict(args),
            result=d.get("result"),
            error=str(d.get("error") or ""),
            role=str(d.get("role") or "agent"),
            source_format=str(d.get("source_format") or d.get("format") or FMT_GENERIC),
            schema=str(d.get("schema") or SCHEMA),
            paper=str(d.get("paper") or PAPER),
            created_at=float(d.get("created_at") or time.time()),
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
        )


# ── tool id helpers ─────────────────────────────────────────────────────────


def parse_tool_id(tool_id: str) -> dict[str, str]:
    """Parse ``surface:name[@plugin]`` or bare tool name → surface/name/plugin."""
    raw = str(tool_id or "").strip()
    if not raw:
        return {"surface": SURFACE_TOOL, "name": "", "plugin_id": "", "tool_id": ""}
    # cli:foo / mcp:bar / agent:name@plugin
    if ":" in raw:
        surface, _, rest = raw.partition(":")
        surface = surface.strip().lower()
        if surface in SURFACES:
            name, _, plugin_id = rest.partition("@")
            return {
                "surface": surface,
                "name": name.strip(),
                "plugin_id": plugin_id.strip(),
                "tool_id": raw,
            }
        # unknown prefix — treat whole string as tool name
    name, _, plugin_id = raw.partition("@")
    return {
        "surface": SURFACE_TOOL,
        "name": name.strip(),
        "plugin_id": plugin_id.strip(),
        "tool_id": raw,
    }


def target_from_tool_id(
    tool_id: str,
    *,
    privilege: str = "read",
    path: str = "",
    description: str = "",
) -> ProtocolTarget:
    p = parse_tool_id(tool_id)
    if not p["name"]:
        raise ProtocolError("tool_id must include a name")
    return ProtocolTarget(
        surface=p["surface"],
        name=p["name"],
        plugin_id=p["plugin_id"],
        privilege=privilege,
        path=path,
        description=description,
    )


# ── normalizers (wire dialects → ProtocolMessage) ───────────────────────────


def from_openai_tool_call(raw: Any, *, msg_id: str = "") -> ProtocolMessage:
    """Normalize OpenAI-style tool_call / function_call dicts.

    Accepts shapes::

        {"id": "...", "type": "function", "function": {"name": "x", "arguments": "{...}"}}
        {"function": {"name": "x", "arguments": {...}}}
        {"name": "x", "arguments": {...}}
    """
    if not isinstance(raw, dict):
        raise ProtocolError(f"openai tool_call must be dict, got {type(raw).__name__}")
    fn = raw.get("function") if isinstance(raw.get("function"), dict) else None
    name = ""
    args_raw: Any = {}
    if fn is not None:
        name = str(fn.get("name") or "").strip()
        args_raw = fn.get("arguments") if "arguments" in fn else fn.get("parameters")
    else:
        name = str(raw.get("name") or raw.get("tool") or "").strip()
        args_raw = raw.get("arguments") if "arguments" in raw else raw.get("parameters")
    if not name:
        raise ProtocolError("openai tool_call missing function name")
    args = _coerce_args(args_raw)
    return ProtocolMessage(
        id=str(msg_id or raw.get("id") or _new_id("oai")),
        kind=KIND_INVOKE,
        target=ProtocolTarget(surface=SURFACE_TOOL, name=name),
        args=args,
        role="agent",
        source_format=FMT_OPENAI,
        meta={"openai_type": str(raw.get("type") or "function")},
    )


def from_anthropic_tool_use(raw: Any, *, msg_id: str = "") -> ProtocolMessage:
    """Normalize Anthropic tool_use content blocks.

    Accepts::

        {"type": "tool_use", "id": "...", "name": "x", "input": {...}}
    """
    if not isinstance(raw, dict):
        raise ProtocolError(
            f"anthropic tool_use must be dict, got {type(raw).__name__}"
        )
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ProtocolError("anthropic tool_use missing name")
    args = _coerce_args(raw.get("input") if "input" in raw else raw.get("arguments"))
    return ProtocolMessage(
        id=str(msg_id or raw.get("id") or _new_id("ant")),
        kind=KIND_INVOKE,
        target=ProtocolTarget(surface=SURFACE_TOOL, name=name),
        args=args,
        role="agent",
        source_format=FMT_ANTHROPIC,
        meta={"anthropic_type": str(raw.get("type") or "tool_use")},
    )


def from_mcp_call(raw: Any, *, msg_id: str = "") -> ProtocolMessage:
    """Normalize MCP tools/call params: ``{"name": "...", "arguments": {...}}``."""
    if not isinstance(raw, dict):
        raise ProtocolError(f"mcp call must be dict, got {type(raw).__name__}")
    name = str(raw.get("name") or raw.get("tool") or "").strip()
    if not name:
        raise ProtocolError("mcp call missing name")
    args = _coerce_args(
        raw.get("arguments") if "arguments" in raw else raw.get("params")
    )
    return ProtocolMessage(
        id=str(msg_id or raw.get("id") or _new_id("mcp")),
        kind=KIND_INVOKE,
        target=ProtocolTarget(surface=SURFACE_MCP, name=name),
        args=args,
        role="agent",
        source_format=FMT_MCP,
    )


def from_cli(
    raw: Any,
    *,
    msg_id: str = "",
    cwd: str = "",
) -> ProtocolMessage:
    """Normalize CLI argv (list) or shell string into a protocol invoke.

    Target name is the program (argv[0]); full argv retained in args.
    """
    argv: list[str]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ProtocolError("cli string is empty")
        try:
            argv = shlex.split(text)
        except ValueError as e:
            raise ProtocolError(f"could not parse cli string: {e}") from e
    elif isinstance(raw, (list, tuple)):
        argv = [str(a) for a in raw]
    elif isinstance(raw, dict):
        if "argv" in raw:
            argv = [str(a) for a in (raw.get("argv") or [])]
        elif "command" in raw:
            return from_cli(raw.get("command"), msg_id=msg_id, cwd=str(raw.get("cwd") or cwd))
        else:
            raise ProtocolError("cli dict needs argv or command")
    else:
        raise ProtocolError(f"cli input must be str/list/dict, got {type(raw).__name__}")
    if not argv:
        raise ProtocolError("cli argv is empty")
    prog = Path(argv[0]).name or argv[0]
    meta: dict[str, Any] = {}
    if cwd:
        meta["cwd"] = cwd
    return ProtocolMessage(
        id=str(msg_id or _new_id("cli")),
        kind=KIND_INVOKE,
        target=ProtocolTarget(
            surface=SURFACE_CLI,
            name=prog,
            description=f"CLI program {prog}",
        ),
        args={"argv": argv, "program": prog},
        role="agent",
        source_format=FMT_CLI,
        meta=meta,
    )


def from_marketplace(
    kind: str,
    name: str,
    *,
    plugin_id: str = "",
    args: Optional[dict[str, Any]] = None,
    privilege: str = "read",
    path: str = "",
    description: str = "",
    msg_id: str = "",
) -> ProtocolMessage:
    """Build an invoke against a wshobson-shaped marketplace component."""
    surface = str(kind or "").strip().lower()
    if surface not in MARKETPLACE_SURFACES:
        raise ProtocolError(
            f"marketplace kind must be one of {sorted(MARKETPLACE_SURFACES)}, got {surface!r}"
        )
    return ProtocolMessage(
        id=str(msg_id or _new_id("mkt")),
        kind=KIND_INVOKE,
        target=ProtocolTarget(
            surface=surface,
            name=str(name or "").strip(),
            plugin_id=str(plugin_id or "").strip(),
            privilege=privilege,
            path=path,
            description=description
            or f"marketplace {surface} {name}"
            + (f"@{plugin_id}" if plugin_id else ""),
        ),
        args=dict(args or {}),
        role="agent",
        source_format=FMT_MARKETPLACE,
        meta={"source_pattern": SOURCE_PATTERN},
    )


def from_plan_step(step: Any, *, msg_id: str = "") -> ProtocolMessage:
    """Normalize multi_llm_agent.PlanStep (or dict) into a protocol invoke."""
    if hasattr(step, "to_dict") and callable(step.to_dict):
        d = step.to_dict()
    elif isinstance(step, dict):
        d = step
    else:
        raise ProtocolError(f"plan step must be PlanStep or dict, got {type(step).__name__}")
    tool = str(d.get("tool") or d.get("name") or "").strip()
    if not tool:
        raise ProtocolError("plan step missing tool")
    target = target_from_tool_id(tool)
    args = d.get("args") if isinstance(d.get("args"), dict) else {}
    kind = KIND_INVOKE
    err = str(d.get("error") or "")
    result = d.get("result")
    status = str(d.get("status") or "").lower()
    if err or status == "failed":
        kind = KIND_ERROR
    elif result is not None and status in ("done", "skipped"):
        kind = KIND_RESULT
    meta: dict[str, Any] = {"plan_step_id": d.get("id"), "plan_status": status}
    if d.get("rationale"):
        meta["rationale"] = d.get("rationale")
    return ProtocolMessage(
        id=str(msg_id or _new_id("plan")),
        kind=kind,
        target=target,
        args=dict(args or {}),
        result=result,
        error=err,
        role="agent",
        source_format=FMT_PLAN_STEP,
        meta=meta,
    )


def normalize(raw: Any, *, hint: str = "") -> ProtocolMessage:
    """Auto-detect wire dialect and normalize to :class:`ProtocolMessage`.

    *hint* may be one of :data:`SOURCE_FORMATS` to force a dialect.
    """
    if isinstance(raw, ProtocolMessage):
        return raw
    hint_l = str(hint or "").strip().lower()
    if hint_l and hint_l in SOURCE_FORMATS:
        if hint_l == FMT_OPENAI:
            return from_openai_tool_call(raw)
        if hint_l == FMT_ANTHROPIC:
            return from_anthropic_tool_use(raw)
        if hint_l == FMT_MCP:
            return from_mcp_call(raw)
        if hint_l == FMT_CLI:
            return from_cli(raw)
        if hint_l == FMT_PLAN_STEP:
            return from_plan_step(raw)
        if hint_l == FMT_MARKETPLACE:
            if not isinstance(raw, dict):
                raise ProtocolError("marketplace normalize expects dict")
            return from_marketplace(
                str(raw.get("kind") or raw.get("surface") or ""),
                str(raw.get("name") or ""),
                plugin_id=str(raw.get("plugin_id") or ""),
                args=raw.get("args") if isinstance(raw.get("args"), dict) else {},
                privilege=str(raw.get("privilege") or "read"),
                path=str(raw.get("path") or ""),
                description=str(raw.get("description") or ""),
            )
        if hint_l == FMT_GENERIC:
            return ProtocolMessage.from_dict(raw)

    # Auto-detect
    if isinstance(raw, (str, list, tuple)):
        return from_cli(raw)
    if not isinstance(raw, dict):
        raise ProtocolError(f"cannot normalize {type(raw).__name__}")

    # Already a protocol envelope
    if raw.get("schema") == SCHEMA or (
        isinstance(raw.get("target"), dict) and raw.get("kind") in KINDS
    ):
        return ProtocolMessage.from_dict(raw)

    typ = str(raw.get("type") or "").strip().lower()
    if typ == "tool_use" or ("input" in raw and "name" in raw and "function" not in raw):
        return from_anthropic_tool_use(raw)
    if typ == "function" or isinstance(raw.get("function"), dict):
        return from_openai_tool_call(raw)
    if "argv" in raw or ("command" in raw and "name" not in raw):
        return from_cli(raw)
    if raw.get("marketplace") is True or (
        str(raw.get("kind") or "").lower() in MARKETPLACE_SURFACES
        and raw.get("plugin_id") is not None
    ):
        return from_marketplace(
            str(raw.get("kind") or raw.get("surface") or ""),
            str(raw.get("name") or raw.get("component") or ""),
            plugin_id=str(raw.get("plugin_id") or ""),
            args=raw.get("args") if isinstance(raw.get("args"), dict) else {},
            privilege=str(raw.get("privilege") or "read"),
            path=str(raw.get("path") or ""),
            description=str(raw.get("description") or ""),
        )
    if raw.get("tool") and ("args" in raw or "rationale" in raw or "status" in raw):
        return from_plan_step(raw)
    # MCP-ish or generic tool
    if "name" in raw and ("arguments" in raw or "params" in raw):
        # Prefer MCP surface when arguments key present
        if "arguments" in raw:
            return from_mcp_call(raw)
        return from_openai_tool_call(raw)
    if "name" in raw or "tool" in raw or "tool_id" in raw:
        return ProtocolMessage.from_dict(
            {
                "kind": KIND_INVOKE,
                "target": {
                    "surface": raw.get("surface") or SURFACE_TOOL,
                    "name": raw.get("name") or raw.get("tool") or "",
                    "plugin_id": raw.get("plugin_id") or "",
                    "tool_id": raw.get("tool_id") or "",
                },
                "args": raw.get("args") or raw.get("arguments") or {},
                "source_format": FMT_GENERIC,
            }
        )
    raise ProtocolError("unrecognized agent interaction payload")


def _coerce_args(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            return {"_raw": s}
        if isinstance(obj, dict):
            return obj
        return {"value": obj}
    return {"value": raw}


# ── converters (ProtocolMessage → other dialects) ───────────────────────────


def to_openai_tool_call(msg: ProtocolMessage) -> dict[str, Any]:
    """Emit OpenAI-style tool_call dict from a protocol message."""
    return {
        "id": msg.id,
        "type": "function",
        "function": {
            "name": msg.target.tool_id
            if msg.target.surface in MARKETPLACE_SURFACES
            else msg.target.name,
            "arguments": json.dumps(msg.args or {}, default=str),
        },
    }


def to_anthropic_tool_use(msg: ProtocolMessage) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": msg.id,
        "name": msg.target.tool_id
        if msg.target.surface in MARKETPLACE_SURFACES
        else msg.target.name,
        "input": dict(msg.args or {}),
    }


def to_mcp_call(msg: ProtocolMessage) -> dict[str, Any]:
    name = msg.target.name if msg.target.surface == SURFACE_MCP else msg.target.tool_id
    return {"name": name, "arguments": dict(msg.args or {})}


def to_cli_argv(msg: ProtocolMessage) -> list[str]:
    """Recover argv list; fall back to ``[name, ...flattened args]``."""
    if msg.target.surface == SURFACE_CLI and isinstance(msg.args.get("argv"), list):
        return [str(a) for a in msg.args["argv"]]
    argv = [msg.target.name]
    for k, v in (msg.args or {}).items():
        if k in ("argv", "program"):
            continue
        if isinstance(v, bool):
            if v:
                argv.append(f"--{k}")
        elif v is None:
            continue
        else:
            argv.extend([f"--{k}", str(v)])
    return argv


def to_plan_step(msg: ProtocolMessage, *, step_id: int = 1) -> Any:
    """Convert to :class:`multi_llm_agent.PlanStep` (import lazily)."""
    from . import multi_llm_agent as mla

    status = mla.STEP_PENDING
    if msg.kind == KIND_ERROR:
        status = mla.STEP_FAILED
    elif msg.kind == KIND_RESULT:
        status = mla.STEP_DONE
    rationale = ""
    if isinstance(msg.meta, dict):
        rationale = str(msg.meta.get("rationale") or "")
    return mla.PlanStep(
        id=int(step_id),
        tool=msg.target.tool_id,
        args=dict(msg.args or {}),
        rationale=rationale,
        status=status,
        result=msg.result,
        error=msg.error,
    )


def to_result_message(
    invoke: ProtocolMessage,
    result: Any = None,
    *,
    error: str = "",
    msg_id: str = "",
) -> ProtocolMessage:
    """Pair an invoke with a result/error message (same target)."""
    kind = KIND_ERROR if error else KIND_RESULT
    return ProtocolMessage(
        id=str(msg_id or _new_id("res")),
        kind=kind,
        target=ProtocolTarget(
            surface=invoke.target.surface,
            name=invoke.target.name,
            plugin_id=invoke.target.plugin_id,
            privilege=invoke.target.privilege,
            path=invoke.target.path,
            description=invoke.target.description,
        ),
        args=dict(invoke.args or {}),
        result=None if error else result,
        error=str(error or ""),
        role="tool",
        source_format=invoke.source_format,
        meta={"in_reply_to": invoke.id},
    )


# ── marketplace catalog → protocol targets ──────────────────────────────────


def marketplace_targets(
    workdir: Path | str = ".",
    *,
    plugins_dir: str = "plugins",
    kinds: Optional[Iterable[str]] = None,
    max_privilege: Optional[str] = None,
    disambiguate: bool = True,
) -> list[ProtocolTarget]:
    """Load wshobson-shaped marketplace components as protocol targets.

    Reuses :func:`marketplace_planner.marketplace_as_tools` (no tree vendor).
    """
    from . import marketplace as mp
    from . import marketplace_planner as mplan

    tools = mplan.marketplace_as_tools(
        workdir,
        plugins_dir=plugins_dir or mp.DEFAULT_PLUGINS_DIR,
        kinds=kinds,
        max_privilege=max_privilege,
        disambiguate=disambiguate,
    )
    return targets_from_catalog(tools)


def targets_from_catalog(tools: Sequence[dict[str, Any]]) -> list[ProtocolTarget]:
    """Convert Planner-style catalog rows into :class:`ProtocolTarget` list."""
    out: list[ProtocolTarget] = []
    seen: set[str] = set()
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or t.get("tool") or "").strip()
        if not name:
            continue
        kind = str(t.get("kind") or "").strip().lower()
        if kind in MARKETPLACE_SURFACES:
            surface = kind
            # Prefer component name + plugin when present
            comp = str(t.get("component") or "").strip()
            plugin_id = str(t.get("plugin_id") or "").strip()
            if comp:
                target = ProtocolTarget(
                    surface=surface,
                    name=comp,
                    plugin_id=plugin_id,
                    privilege=str(t.get("privilege") or "read"),
                    path=str(t.get("path") or ""),
                    description=str(t.get("description") or ""),
                )
            else:
                target = target_from_tool_id(
                    name,
                    privilege=str(t.get("privilege") or "read"),
                    path=str(t.get("path") or ""),
                    description=str(t.get("description") or ""),
                )
        elif name.startswith("cli:"):
            target = target_from_tool_id(name, description=str(t.get("description") or ""))
        elif name.startswith("mcp:") or t.get("mcp") is True:
            parsed = parse_tool_id(name if ":" in name else f"mcp:{name}")
            target = ProtocolTarget(
                surface=SURFACE_MCP,
                name=parsed["name"] or name,
                description=str(t.get("description") or ""),
                privilege=str(t.get("privilege") or "read"),
            )
        else:
            target = ProtocolTarget(
                surface=SURFACE_TOOL,
                name=name,
                privilege=str(t.get("privilege") or "read"),
                description=str(t.get("description") or ""),
            )
        tid = target.tool_id
        if tid in seen:
            continue
        seen.add(tid)
        out.append(target)
    return out


def catalog_summary(targets: Sequence[ProtocolTarget]) -> dict[str, Any]:
    by_surface: dict[str, int] = {}
    plugins: set[str] = set()
    for t in targets:
        by_surface[t.surface] = by_surface.get(t.surface, 0) + 1
        if t.plugin_id:
            plugins.add(t.plugin_id)
    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "n_targets": len(targets),
        "n_plugins": len(plugins),
        "by_surface": dict(sorted(by_surface.items())),
        "plugins": sorted(plugins),
    }


# ── validation ──────────────────────────────────────────────────────────────


def validate_message(
    msg: ProtocolMessage,
    *,
    allowed_tool_ids: Optional[Sequence[str]] = None,
    require_invoke_args_dict: bool = True,
) -> dict[str, Any]:
    """Validate one protocol message; return ``{ok, findings}``."""
    findings: list[dict[str, str]] = []
    ok = True

    def err(path: str, message: str) -> None:
        nonlocal ok
        ok = False
        findings.append({"severity": "error", "path": path, "message": message})

    def warn(path: str, message: str) -> None:
        findings.append({"severity": "warning", "path": path, "message": message})

    if msg.kind not in KINDS:
        err("kind", f"invalid kind {msg.kind!r}")
    if msg.target.surface not in SURFACES:
        err("target.surface", f"invalid surface {msg.target.surface!r}")
    if not msg.target.name:
        err("target.name", "empty name")
    if require_invoke_args_dict and not isinstance(msg.args, dict):
        err("args", "args must be a dict")
    if msg.kind == KIND_ERROR and not msg.error:
        warn("error", "error kind without error string")
    if msg.kind == KIND_RESULT and msg.error:
        warn("error", "result kind should not carry error string")
    allowed = {str(t).strip() for t in (allowed_tool_ids or []) if str(t).strip()}
    if allowed and msg.target.tool_id not in allowed and msg.target.name not in allowed:
        err(
            "target",
            f"target {msg.target.tool_id!r} not in allowed set",
        )
    return {
        "schema": SCHEMA,
        "ok": ok,
        "findings": findings,
        "tool_id": msg.target.tool_id,
        "kind": msg.kind,
        "surface": msg.target.surface,
    }


# ── transcript (evaluation log) ─────────────────────────────────────────────


@dataclass
class ProtocolTranscript:
    """Ordered interaction log for general agent evaluation (paper intent).

    Records normalized messages across heterogeneous surfaces so evaluators
    can score architecture without caring about OpenAI vs CLI vs marketplace.
    """

    task: str = ""
    messages: list[ProtocolMessage] = field(default_factory=list)
    schema: str = SCHEMA
    paper: str = PAPER
    source_pattern: str = SOURCE_PATTERN
    created_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def append(self, msg: ProtocolMessage | Any, *, hint: str = "") -> ProtocolMessage:
        m = msg if isinstance(msg, ProtocolMessage) else normalize(msg, hint=hint)
        self.messages.append(m)
        return m

    def surfaces_used(self) -> list[str]:
        seen: list[str] = []
        for m in self.messages:
            s = m.target.surface
            if s not in seen:
                seen.append(s)
        return seen

    def source_formats_used(self) -> list[str]:
        seen: list[str] = []
        for m in self.messages:
            f = m.source_format
            if f not in seen:
                seen.append(f)
        return seen

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        by_surface: dict[str, int] = {}
        n_err = 0
        for m in self.messages:
            by_kind[m.kind] = by_kind.get(m.kind, 0) + 1
            by_surface[m.target.surface] = by_surface.get(m.target.surface, 0) + 1
            if m.kind == KIND_ERROR or m.error:
                n_err += 1
        return {
            "schema": self.schema,
            "paper": self.paper,
            "source_pattern": self.source_pattern,
            "task": self.task,
            "n_messages": len(self.messages),
            "n_errors": n_err,
            "by_kind": dict(sorted(by_kind.items())),
            "by_surface": dict(sorted(by_surface.items())),
            "surfaces": self.surfaces_used(),
            "source_formats": self.source_formats_used(),
        }

    def validate(
        self,
        *,
        allowed_tool_ids: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        ok = True
        for i, m in enumerate(self.messages):
            rep = validate_message(m, allowed_tool_ids=allowed_tool_ids)
            if not rep["ok"]:
                ok = False
            for f in rep["findings"]:
                findings.append({**f, "index": i, "id": m.id})
        return {
            "schema": self.schema,
            "ok": ok,
            "n_messages": len(self.messages),
            "findings": findings,
            "summary": self.summary(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "paper": self.paper,
            "source_pattern": self.source_pattern,
            "task": self.task,
            "created_at": float(self.created_at),
            "meta": dict(self.meta or {}),
            "messages": [m.to_dict() for m in self.messages],
            "summary": self.summary(),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, d: Any) -> "ProtocolTranscript":
        if not isinstance(d, dict):
            raise ProtocolError(f"transcript must be dict, got {type(d).__name__}")
        msgs = []
        for raw in d.get("messages") or []:
            msgs.append(ProtocolMessage.from_dict(raw))
        return cls(
            task=str(d.get("task") or ""),
            messages=msgs,
            schema=str(d.get("schema") or SCHEMA),
            paper=str(d.get("paper") or PAPER),
            source_pattern=str(d.get("source_pattern") or SOURCE_PATTERN),
            created_at=float(d.get("created_at") or time.time()),
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
        )


# ── plan bridge ─────────────────────────────────────────────────────────────


def messages_to_plan(
    messages: Sequence[ProtocolMessage],
    *,
    task: str = "",
    auto_ready: bool = True,
    planner: str = "agent_protocol",
) -> Any:
    """Fold invoke messages into a :class:`multi_llm_agent.ToolPlan`."""
    from . import multi_llm_agent as mla

    steps = []
    tools: list[str] = []
    for i, m in enumerate(messages, start=1):
        if m.kind not in (KIND_INVOKE, KIND_RESULT, KIND_ERROR):
            continue
        step = to_plan_step(m, step_id=i)
        steps.append(step)
        if step.tool not in tools:
            tools.append(step.tool)
    status = mla.STATUS_READY if (auto_ready and steps) else mla.STATUS_DRAFT
    return mla.ToolPlan(
        task=task or "protocol transcript plan",
        steps=steps,
        status=status if steps else mla.STATUS_DRAFT,
        planner=planner,
        tools_available=tools,
        schema=mla.SCHEMA,
        paper=PAPER,
        notes="built from nexus.agent_protocol messages",
        meta={
            "protocol_schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "n_messages": len(messages),
        },
    )


def plan_to_messages(plan: Any) -> list[ProtocolMessage]:
    """Expand a ToolPlan into protocol messages (one per step)."""
    if hasattr(plan, "steps"):
        steps = plan.steps
        task = str(getattr(plan, "task", "") or "")
    elif isinstance(plan, dict):
        steps = plan.get("steps") or []
        task = str(plan.get("task") or "")
    else:
        raise ProtocolError(f"plan must be ToolPlan or dict, got {type(plan).__name__}")
    out: list[ProtocolMessage] = []
    for s in steps:
        m = from_plan_step(s)
        if task:
            m.meta = {**m.meta, "task": task}
        out.append(m)
    return out


def invoke(
    surface: str,
    name: str,
    *,
    args: Optional[dict[str, Any]] = None,
    plugin_id: str = "",
    msg_id: str = "",
) -> ProtocolMessage:
    """Convenience constructor for a protocol invoke on any surface."""
    surface_l = str(surface or SURFACE_TOOL).strip().lower()
    if surface_l in MARKETPLACE_SURFACES:
        return from_marketplace(
            surface_l, name, plugin_id=plugin_id, args=args, msg_id=msg_id
        )
    if surface_l == SURFACE_CLI:
        argv = [name]
        if args and isinstance(args.get("argv"), list):
            argv = [str(a) for a in args["argv"]]
        elif args:
            for k, v in args.items():
                if k == "argv":
                    continue
                argv.extend([f"--{k}", str(v)])
        return from_cli(argv, msg_id=msg_id)
    if surface_l == SURFACE_MCP:
        return from_mcp_call(
            {"name": name, "arguments": dict(args or {})}, msg_id=msg_id
        )
    return ProtocolMessage(
        id=str(msg_id or _new_id("msg")),
        kind=KIND_INVOKE,
        target=ProtocolTarget(
            surface=SURFACE_TOOL if surface_l not in SURFACES else surface_l,
            name=str(name).strip(),
            plugin_id=str(plugin_id or "").strip(),
        ),
        args=dict(args or {}),
        source_format=FMT_GENERIC,
    )


# ── formatting / CLI ────────────────────────────────────────────────────────


def format_message(msg: ProtocolMessage) -> str:
    lines = [
        f"id:       {msg.id}",
        f"kind:     {msg.kind}",
        f"surface:  {msg.target.surface}",
        f"target:   {msg.target.tool_id}",
        f"format:   {msg.source_format}",
        f"role:     {msg.role}",
        f"args:     {json.dumps(msg.args, default=str)}",
    ]
    if msg.result is not None:
        lines.append(f"result:   {msg.result!r}"[:200])
    if msg.error:
        lines.append(f"error:    {msg.error}")
    return "\n".join(lines)


def format_transcript(tr: ProtocolTranscript) -> str:
    s = tr.summary()
    lines = [
        f"schema:   {tr.schema}",
        f"paper:    {tr.paper}",
        f"source:   {tr.source_pattern}",
        f"task:     {tr.task or '(none)'}",
        f"messages: {s['n_messages']} errors={s['n_errors']}",
        f"surfaces: {s['surfaces']}",
        f"formats:  {s['source_formats']}",
        "",
    ]
    for i, m in enumerate(tr.messages):
        lines.append(
            f"  [{i}] {m.kind:7} {m.target.surface:8} {m.target.tool_id}  "
            f"fmt={m.source_format}"
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m nexus.agent_protocol normalize|validate|catalog|transcript``."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        prog="nexus.agent_protocol",
        description=(
            "Unified agent interaction protocol "
            "(arXiv 2602.22953 × wshobson/agents marketplace)"
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_norm = sub.add_parser("normalize", help="normalize JSON stdin/file to protocol")
    p_norm.add_argument("--file", default="", help="path to JSON payload")
    p_norm.add_argument("--hint", default="", help="force source format")
    p_norm.add_argument("--json", action="store_true")

    p_val = sub.add_parser("validate", help="validate protocol message JSON")
    p_val.add_argument("--file", default="")
    p_val.add_argument("--json", action="store_true")

    p_cat = sub.add_parser("catalog", help="marketplace components as protocol targets")
    p_cat.add_argument("--workdir", default=".")
    p_cat.add_argument("--plugins-dir", default="plugins", dest="plugins_dir")
    p_cat.add_argument("--json", action="store_true")

    p_tr = sub.add_parser(
        "transcript",
        help="build eval transcript from JSON list of heterogeneous payloads",
    )
    p_tr.add_argument("--file", default="", help="JSON list or {messages:[...]}")
    p_tr.add_argument("--task", default="")
    p_tr.add_argument("--json", action="store_true")

    p_plan = sub.add_parser(
        "to-plan",
        help="normalize messages → multi_llm ToolPlan JSON",
    )
    p_plan.add_argument("--file", default="")
    p_plan.add_argument("--task", default="protocol plan")
    p_plan.add_argument("--json", action="store_true")

    args = ap.parse_args(list(argv) if argv is not None else None)

    def _load_json(path: str) -> Any:
        if path:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        data = sys.stdin.read()
        if not data.strip():
            raise SystemExit("expected JSON on stdin or --file")
        return json.loads(data)

    if args.cmd == "normalize":
        raw = _load_json(args.file)
        msg = normalize(raw, hint=args.hint)
        if args.json:
            print(msg.to_json())
        else:
            print(format_message(msg))
        return 0

    if args.cmd == "validate":
        raw = _load_json(args.file)
        msg = normalize(raw) if not (
            isinstance(raw, dict) and raw.get("schema") == SCHEMA
        ) else ProtocolMessage.from_dict(raw)
        rep = validate_message(msg)
        if args.json:
            print(json.dumps(rep, indent=2))
        else:
            print(f"ok={rep['ok']} tool_id={rep['tool_id']} surface={rep['surface']}")
            for f in rep["findings"]:
                print(f"  [{f['severity']}] {f['path']}: {f['message']}")
        return 0 if rep["ok"] else 1

    if args.cmd == "catalog":
        targets = marketplace_targets(args.workdir, plugins_dir=args.plugins_dir)
        summary = catalog_summary(targets)
        if args.json:
            print(
                json.dumps(
                    {
                        "schema": SCHEMA,
                        "summary": summary,
                        "targets": [t.to_dict() for t in targets],
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"schema={SCHEMA} targets={summary['n_targets']} "
                f"by_surface={summary['by_surface']}"
            )
            for t in targets:
                print(f"  - {t.tool_id}: {(t.description or '')[:72]}")
        return 0 if targets else 1

    if args.cmd == "transcript":
        raw = _load_json(args.file)
        tr = ProtocolTranscript(task=args.task)
        if isinstance(raw, dict) and "messages" in raw:
            for m in raw["messages"]:
                tr.append(m)
            if not tr.task:
                tr.task = str(raw.get("task") or "")
        elif isinstance(raw, list):
            for m in raw:
                tr.append(m)
        else:
            tr.append(raw)
        if args.json:
            print(tr.to_json())
        else:
            print(format_transcript(tr))
        return 0

    if args.cmd == "to-plan":
        raw = _load_json(args.file)
        msgs: list[ProtocolMessage] = []
        if isinstance(raw, dict) and "messages" in raw:
            for m in raw["messages"]:
                msgs.append(normalize(m))
        elif isinstance(raw, list):
            for m in raw:
                msgs.append(normalize(m))
        else:
            msgs.append(normalize(raw))
        plan = messages_to_plan(msgs, task=args.task)
        if args.json:
            print(plan.to_json())
        else:
            print(f"task={plan.task} status={plan.status} steps={len(plan.steps)}")
            for s in plan.steps:
                print(f"  [{s.id}] {s.tool}")
        return 0 if plan.steps else 1

    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
