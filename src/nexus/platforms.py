"""Multi-platform agent mesh: Grok CLI, Cursor, Claude, local LLMs — one tool surface.

Local models (Ollama / OpenAI-compatible) and cloud agents (Grok CLI today; Cursor,
Claude Desktop, Codex, Gemini next) all attach to the **same** NEXUS Workspace MCP
+ event bus. Agents hand off via workspace chat; tools are project-jailed.

  nexus platforms status
  nexus platforms connect          # auto-wire detected clients
  nexus platforms connect --grok --cursor --start

Autonomy: config writes are opt-in via ``connect`` (never silent rewrite without call).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# --- detection -----------------------------------------------------------------


@dataclass
class PlatformInfo:
    id: str
    name: str
    installed: bool
    path: Optional[str] = None
    config_path: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    agent_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def _home() -> Path:
    return Path.home()


def detect_platforms(*, project_root: Optional[Path] = None) -> list[PlatformInfo]:
    root = Path(project_root or os.getcwd()).resolve()
    out: list[PlatformInfo] = []

    # Grok CLI
    grok = _which("grok")
    grok_cfg = _home() / ".grok" / "config.toml"
    out.append(
        PlatformInfo(
            id="grok",
            name="Grok CLI (Build TUI)",
            installed=bool(grok) or grok_cfg.is_file(),
            path=grok,
            config_path=str(grok_cfg) if grok_cfg.is_file() or grok else str(grok_cfg),
            notes=[
                "Primary target: local LLMs + cloud Grok share tools via MCP",
                "config: ~/.grok/config.toml  [mcp_servers.*]  [model.*]",
            ],
            agent_id="grok_cli",
        )
    )

    # Cursor
    cursor_bin = _which("cursor") or _which("cursor-agent")
    cursor_mcp = _home() / ".cursor" / "mcp.json"
    cursor_proj = root / ".cursor" / "mcp.json"
    out.append(
        PlatformInfo(
            id="cursor",
            name="Cursor",
            installed=bool(cursor_bin) or cursor_mcp.is_file() or (_home() / ".cursor").is_dir(),
            path=cursor_bin,
            config_path=str(cursor_proj if cursor_proj.parent.is_dir() else cursor_mcp),
            notes=["MCP: ~/.cursor/mcp.json or project .cursor/mcp.json"],
            agent_id="cursor",
        )
    )

    # Claude Desktop / Code
    claude = _which("claude")
    claude_cfg = (
        _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    )
    if not claude_cfg.is_file():
        # Linux path variants
        for p in (
            _home() / ".config" / "Claude" / "claude_desktop_config.json",
            _home() / ".claude.json",
        ):
            if p.is_file():
                claude_cfg = p
                break
    out.append(
        PlatformInfo(
            id="claude",
            name="Claude (CLI / Desktop)",
            installed=bool(claude) or claude_cfg.is_file(),
            path=claude,
            config_path=str(claude_cfg),
            notes=["stdio MCP via claude_desktop_config.json or Claude Code"],
            agent_id="claude",
        )
    )

    # Codex / GPT CLI
    codex = _which("codex")
    out.append(
        PlatformInfo(
            id="codex",
            name="Codex / GPT CLI",
            installed=bool(codex),
            path=codex,
            notes=["Bus bridge via nexus start --with-cli; MCP when product supports it"],
            agent_id="gpt",
        )
    )

    # Gemini
    gemini = _which("gemini")
    out.append(
        PlatformInfo(
            id="gemini",
            name="Gemini CLI",
            installed=bool(gemini),
            path=gemini,
            notes=["Bus bridge via nexus start"],
            agent_id="gemini",
        )
    )

    # Ollama local LLM
    ollama = _which("ollama")
    out.append(
        PlatformInfo(
            id="ollama",
            name="Ollama (local LLM)",
            installed=bool(ollama),
            path=ollama,
            notes=[
                "Bus agent `local` via ollama-http bridge",
                "Also register OpenAI-compatible endpoint in Grok [model.*] for TUI use",
            ],
            agent_id="local",
        )
    )

    # NEXUS itself
    out.append(
        PlatformInfo(
            id="nexus",
            name="NEXUS Core bus + Workspace MCP",
            installed=True,
            path=str(root),
            notes=["nexus start · nexus mcp · shared tools for all clients"],
            agent_id="nexus",
        )
    )
    return out


def python_for_mcp() -> str:
    """Prefer active venv / current interpreter for MCP child processes."""
    import sys

    if os.environ.get("NEXUS_PYTHON"):
        return os.environ["NEXUS_PYTHON"]
    # When nexus was started from a venv, sys.executable finds the package
    exe = Path(sys.executable).resolve()
    if exec.is_file() and "python" in exec.name:
        return str(exe)
    return shutil.which("python3") or "python3"


def _src_on_path() -> str:
    # this file is src/nexus/platforms.py → parents[1] = src
    return str(Path(__file__).resolve().parents[1])


def mcp_server_command_fixed(project_root: Path) -> dict[str, Any]:
    """Stdio MCP launch spec — same tools for Grok, Cursor, Claude, local models."""
    py = python_for_mcp()
    src = _src_on_path()
    env = {
        "NEXUS_PROJECT_ROOT": str(Path(project_root).resolve()),
        "PYTHONPATH": src,
    }
    if os.environ.get("PYTHONPATH"):
        env["PYTHONPATH"] = src + os.pathsep + os.environ["PYTHONPATH"]
    return {
        "command": py,
        "args": ["-m", "nexus.mcp_server"],
        "env": env,
    }


# --- Grok config.toml helpers --------------------------------------------------


def _grok_has_mcp_server(text: str, name: str = "nexus-workspace") -> bool:
    return bool(re.search(rf"\[mcp_servers\.{re.escape(name)}\]", text))


def write_grok_mcp_snippet(project_root: Path, *, name: str = "nexus-workspace") -> str:
    spec = mcp_server_command_fixed(project_root)
    # TOML-ish block
    env_lines = ", ".join(f'{k} = "{v}"' for k, v in spec["env"].items())
    args = ", ".join(f'"{a}"' for a in spec["args"])
    return (
        f"\n# --- NEXUS auto-connect (nexus platforms connect) ---\n"
        f"[mcp_servers.{name}]\n"
        f'command = "{spec["command"]}"\n'
        f"args = [{args}]\n"
        f"env = {{ {env_lines} }}\n"
        f"enabled = true\n"
        f"startup_timeout_sec = 45\n"
    )


def connect_grok(
    project_root: Path,
    *,
    config_path: Optional[Path] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Register Workspace MCP in ~/.grok/config.toml (and try `grok mcp add`)."""
    cfg = Path(config_path or (_home() / ".grok" / "config.toml"))
    cfg.parent.mkdir(parents=True, exist_ok=True)
    existing = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    name = "nexus-workspace"
    if _grok_has_mcp_server(existing, name) and not force:
        return {
            "platform": "grok",
            "ok": True,
            "action": "already_configured",
            "config": str(cfg),
        }

    # Prefer official CLI when present
    if _which("grok"):
        spec = mcp_server_command_fixed(project_root)
        cmd = [
            "grok",
            "mcp",
            "add",
            name,
            "-e",
            f"NEXUS_PROJECT_ROOT={project_root.resolve()}",
            "-e",
            f"PYTHONPATH={spec['env']['PYTHONPATH']}",
            "--",
            spec["command"],
            *spec["args"],
        ]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if p.returncode == 0:
                return {
                    "platform": "grok",
                    "ok": True,
                    "action": "grok_mcp_add",
                    "config": str(cfg),
                    "stdout": (p.stdout or "")[:500],
                }
            # fall through to file write
            cli_err = (p.stderr or p.stdout or "")[:400]
        except Exception as e:
            cli_err = str(e)
    else:
        cli_err = "grok binary not on PATH"

    # File merge
    if _grok_has_mcp_server(existing, name) and force:
        # strip old block roughly
        existing = re.sub(
            rf"\n?# --- NEXUS auto-connect.*?\[mcp_servers\.{re.escape(name)}\][^\[]*",
            "\n",
            existing,
            flags=re.S,
        )
        existing = re.sub(
            rf"\[mcp_servers\.{re.escape(name)}\][^\[]*",
            "",
            existing,
            flags=re.S,
        )
    snippet = write_grok_mcp_snippet(project_root, name=name)
    cfg.write_text(existing.rstrip() + "\n" + snippet, encoding="utf-8")
    return {
        "platform": "grok",
        "ok": True,
        "action": "wrote_config_toml",
        "config": str(cfg),
        "cli_note": cli_err,
    }


def ensure_grok_local_model_hint(
    *,
    model_id: str = "nexus-local",
    base_url: str = "http://127.0.0.1:11434/v1",
    model_name: str = "gemma2",
    force: bool = False,
) -> dict[str, Any]:
    """Optionally register an OpenAI-compatible local endpoint for Grok CLI.

    Ollama OpenAI compatibility: http://127.0.0.1:11434/v1
    """
    cfg = _home() / ".grok" / "config.toml"
    if not cfg.parent.is_dir():
        return {"ok": False, "reason": "no ~/.grok directory"}
    text = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    if f"[model.{model_id}]" in text and not force:
        return {"ok": True, "action": "already_present", "model_id": model_id}
    block = (
        f"\n# --- NEXUS local LLM for Grok CLI ---\n"
        f"[model.{model_id}]\n"
        f'model = "{model_name}"\n'
        f'base_url = "{base_url}"\n'
        f'name = "NEXUS local ({model_name})"\n'
        f'description = "Local LLM via Ollama — full tools via mcp_servers.nexus-workspace"\n'
        f'api_key = "EMPTY"\n'
        f'api_backend = "chat_completions"\n'
        f"context_window = 32768\n"
        f"max_completion_tokens = 4096\n"
        f"temperature = 0.3\n"
    )
    cfg.write_text((text.rstrip() + "\n" + block) if text else block.lstrip(), encoding="utf-8")
    return {"ok": True, "action": "wrote_model", "model_id": model_id, "base_url": base_url}


# --- Cursor --------------------------------------------------------------------


def connect_cursor(
    project_root: Path,
    *,
    project_local: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Write MCP server entry for Cursor (project .cursor/mcp.json preferred)."""
    if project_local:
        path = Path(project_root).resolve() / ".cursor" / "mcp.json"
    else:
        path = _home() / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    servers = data.get("mcpServers") or data.get("mcp") or {}
    if not isinstance(servers, dict):
        servers = {}
    if "nexus-workspace" in servers and not force:
        return {
            "platform": "cursor",
            "ok": True,
            "action": "already_configured",
            "config": str(path),
        }
    spec = mcp_server_command_fixed(project_root)
    servers["nexus-workspace"] = {
        "command": spec["command"],
        "args": spec["args"],
        "env": spec["env"],
    }
    data["mcpServers"] = servers
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {
        "platform": "cursor",
        "ok": True,
        "action": "wrote_mcp_json",
        "config": str(path),
    }


# --- Claude Desktop ------------------------------------------------------------


def connect_claude_desktop(
    project_root: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Merge nexus-workspace into Claude Desktop config if path known."""
    candidates = [
        _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        _home() / ".config" / "Claude" / "claude_desktop_config.json",
    ]
    # Always also write a portable example into the project
    example = Path(project_root).resolve() / "connectors" / "examples" / "claude-desktop.nexus.json"
    spec = mcp_server_command_fixed(project_root)
    payload = {
        "mcpServers": {
            "nexus-workspace": {
                "command": spec["command"],
                "args": spec["args"],
                "env": spec["env"],
            }
        }
    }
    example.parent.mkdir(parents=True, exist_ok=True)
    example.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    wrote = None
    for cfg in candidates:
        if not cfg.parent.is_dir() and not force:
            continue
        cfg.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        servers = data.get("mcpServers") or {}
        if "nexus-workspace" in servers and not force:
            wrote = str(cfg)
            break
        servers["nexus-workspace"] = payload["mcpServers"]["nexus-workspace"]
        data["mcpServers"] = servers
        cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        wrote = str(cfg)
        break

    return {
        "platform": "claude",
        "ok": True,
        "action": "wrote_example_and_optional_desktop",
        "example": str(example),
        "desktop_config": wrote,
    }


# --- orchestrate ---------------------------------------------------------------


def connect_all(
    project_root: Optional[Path] = None,
    *,
    grok: bool = True,
    cursor: bool = True,
    claude: bool = True,
    local_model: bool = True,
    force: bool = False,
    ollama_model: Optional[str] = None,
) -> dict[str, Any]:
    """Auto-connect detected platforms so agents + local LLM share NEXUS tools."""
    root = Path(project_root or os.getcwd()).resolve()
    results: list[dict[str, Any]] = []
    platforms = {p.id: p for p in detect_platforms(project_root=root)}

    if grok and platforms.get("grok", PlatformInfo("grok", "", False)).installed:
        results.append(connect_grok(root, force=force))
        if local_model and platforms.get("ollama", PlatformInfo("ollama", "", False)).installed:
            # discover a model name
            model = ollama_model or os.environ.get("OLLAMA_MODEL") or "gemma2"
            results.append(
                ensure_grok_local_model_hint(
                    model_name=model,
                    force=force,
                )
            )
    elif grok:
        results.append({"platform": "grok", "ok": False, "reason": "not_installed"})

    if cursor and platforms.get("cursor", PlatformInfo("cursor", "", False)).installed:
        results.append(connect_cursor(root, force=force))
    elif cursor:
        # still write project-local cursor config for when they install later
        results.append(connect_cursor(root, force=force))

    if claude:
        results.append(connect_claude_desktop(root, force=force))

    # Agent flow map for docs / status
    flow = agent_flow_map()
    return {
        "project_root": str(root),
        "results": results,
        "agent_flow": flow,
        "next": [
            "nexus start -y                 # bus + Ollama local agent + CLI bridges",
            "nexus mcp                      # stdio MCP (or: already configured in clients)",
            "grok                           # Grok CLI — tools include nexus-workspace; /model nexus-local",
            "Open Cursor → enable MCP nexus-workspace",
            "Agents post to shared workspace via send_to_workspace (agent id per platform)",
        ],
    }


def agent_flow_map() -> dict[str, Any]:
    """How agents move between platforms and into NEXUS."""
    return {
        "hub": "NEXUS event bus + Workspace MCP + durable engine",
        "ingress": [
            {
                "from": "Grok CLI (cloud or local model)",
                "via": "MCP stdio nexus-workspace + optional bus bridges",
                "agent_id": "grok_cli",
            },
            {
                "from": "Cursor",
                "via": "MCP stdio nexus-workspace",
                "agent_id": "cursor",
            },
            {
                "from": "Claude Desktop / CLI",
                "via": "MCP stdio + cli-bridge on bus",
                "agent_id": "claude",
            },
            {
                "from": "Codex / Gemini CLIs",
                "via": "cli-bridge on bus (nexus start)",
                "agent_id": "gpt / gemini",
            },
            {
                "from": "Ollama / local OpenAI-compatible",
                "via": "ollama-http bridge agent=local + Grok [model.nexus-local]",
                "agent_id": "local",
            },
        ],
        "shared_tools": [
            "list_project_files",
            "read_project_file",
            "write_to_project",
            "send_to_workspace",
            "read_workspace_chat",
            "nexus_status",
            "run_project_checks",
            "bus_status",
            "github_community_status",
        ],
        "handoff": "send_to_workspace / read_workspace_chat with distinct agent ids",
        "rule": "Local LLM uses the same MCP tools as cloud agents when launched from Grok CLI with nexus-workspace enabled",
    }


def format_status_table(platforms: list[PlatformInfo]) -> str:
    lines = [
        f"{'ID':<10} {'OK':<4} {'AGENT':<12} NAME",
        "-" * 64,
    ]
    for p in platforms:
        ok = "yes" if p.installed else "no"
        lines.append(f"{p.id:<10} {ok:<4} {(p.agent_id or '-')[:12]:<12} {p.name}")
        if p.path:
            lines.append(f"{'':10} path: {p.path}")
    return "\n".join(lines)
