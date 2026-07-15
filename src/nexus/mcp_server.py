"""Minimal Workspace MCP server (stdio JSON-RPC + optional HTTP).

Project-jail tools for AI clients (Claude Desktop, etc.).
No API keys. Scope is NEXUS_PROJECT_ROOT only.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


SERVER_NAME = "nexus-workspace"
SERVER_VERSION = "0.7.4"
PROTOCOL_VERSION = "2024-11-05"


def _root() -> Path:
    raw = os.environ.get("NEXUS_PROJECT_ROOT") or os.getcwd()
    return Path(raw).resolve()


def _workspace_dir() -> Path:
    d = _root() / ".nexus" / "workspace"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_path(rel: str) -> Path:
    """Resolve path under project root; reject escapes."""
    root = _root()
    # strip leading slashes so /etc/passwd becomes relative junk inside root
    clean = rel.lstrip("/\\")
    target = (root / clean).resolve()
    if root != target and root not in target.parents:
        raise PermissionError(f"path escapes project root: {rel}")
    return target


TOOLS = [
    {
        "name": "list_project_files",
        "description": "List files under the project root (optional subdirectory).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory (default '.')",
                    "default": ".",
                },
                "max_entries": {"type": "integer", "default": 200},
            },
        },
    },
    {
        "name": "read_project_file",
        "description": "Read a text file under the project root.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"},
                "max_bytes": {"type": "integer", "default": 100000},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_to_project",
        "description": "Write or overwrite a text file under the project root.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "send_to_workspace",
        "description": "Append a message to the shared workspace log (multi-agent handoff).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "agent": {
                    "type": "string",
                    "description": "Stable id e.g. claude_web, chatgpt_web, grok_web",
                    "default": "mcp_client",
                },
                "label": {"type": "string", "default": "note"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "read_workspace_chat",
        "description": "Read recent workspace messages (newest last).",
        "inputSchema": {
            "type": "object",
            "properties": {"count": {"type": "integer", "default": 20}},
        },
    },
    {
        "name": "nexus_status",
        "description": "Report NEXUS project root and basic runtime status if available.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_project_checks",
        "description": (
            "Run allowlisted project checks (install + pytest + smoke when present). "
            "Same evidence loop the community bot uses. Local and cloud agents share this tool."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout_each": {
                    "type": "number",
                    "default": 180,
                    "description": "Seconds per check command",
                }
            },
        },
    },
    {
        "name": "bus_status",
        "description": "If the NEXUS event bus is up, return agent online/busy status (local LLM + CLIs).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "github_community_status",
        "description": "Show GitHub community one-stop status (gh auth + target repo) for this machine.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "owner/repo override (optional)",
                }
            },
        },
    },
    {
        "name": "list_platforms",
        "description": "List detected agent platforms (Grok CLI, Cursor, Claude, Ollama, …) and connect hints.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "github_scout",
        "description": "Search related public GitHub repos, optionally clone/prove them for continuous improvement notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
                "connect": {"type": "boolean", "default": True},
                "prove": {"type": "boolean", "default": True},
                "structure_only": {"type": "boolean", "default": True}
            },
            "required": ["query"]
        }
    },
    {
        "name": "github_loop",
        "description": "Run community test loop for an issue/PR number and post or dry-run results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "number": {"type": "integer"},
                "repo": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
                "force": {"type": "boolean", "default": False}
            },
            "required": ["number"]
        }
    },
    {
        "name": "platforms_connect",
        "description": "Auto-wire Grok CLI / Cursor / Claude MCP so local and cloud agents share tools.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "force": {"type": "boolean", "default": False}
            }
        }
    },
    {
        "name": "apply_phase",
        "description": (
            "Start/resume the improve-apply phase machine (briefed→context_packed→"
            "applying→audited→done). Returns current phase + last decision audit. "
            "Idempotent; dry-run by default."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Existing run id to resume (optional)",
                },
                "fixture": {
                    "type": "string",
                    "description": "Grade fixture path or mine_eval dir (optional)",
                },
                "advance": {
                    "type": "string",
                    "description": "one | all | status (default: all)",
                    "default": "all",
                },
                "dry_run": {"type": "boolean", "default": True},
            },
        },
    },
]


def _tool_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def call_tool(name: str, arguments: Optional[dict[str, Any]]) -> dict[str, Any]:
    args = arguments or {}
    try:
        if name == "list_project_files":
            rel = args.get("path") or "."
            max_entries = int(args.get("max_entries") or 200)
            base = _safe_path(rel)
            if not base.exists():
                return _tool_result(f"not found: {rel}", is_error=True)
            if not base.is_dir():
                return _tool_result(f"not a directory: {rel}", is_error=True)
            entries = []
            for i, p in enumerate(sorted(base.rglob("*"))):
                if i >= max_entries:
                    entries.append("… truncated …")
                    break
                try:
                    rel_s = str(p.relative_to(_root()))
                except ValueError:
                    continue
                kind = "dir" if p.is_dir() else "file"
                entries.append(f"{kind}\t{rel_s}")
            return _tool_result("\n".join(entries) if entries else "(empty)")

        if name == "read_project_file":
            path = _safe_path(str(args.get("path") or ""))
            max_bytes = int(args.get("max_bytes") or 100000)
            if not path.is_file():
                return _tool_result(f"not a file: {args.get('path')}", is_error=True)
            data = path.read_bytes()[:max_bytes]
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("utf-8", errors="replace")
            return _tool_result(text)

        if name == "write_to_project":
            path = _safe_path(str(args.get("path") or ""))
            content = str(args.get("content") or "")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return _tool_result(f"wrote {path.relative_to(_root())} ({len(content)} chars)")

        if name == "send_to_workspace":
            msg = str(args.get("message") or "")
            agent = str(args.get("agent") or "mcp_client")
            label = str(args.get("label") or "note")
            log = _workspace_dir() / "chat.jsonl"
            row = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "agent": agent,
                "label": label,
                "message": msg[:8000],
            }
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            return _tool_result(f"recorded as {agent}: {label}")

        if name == "read_workspace_chat":
            count = int(args.get("count") or 20)
            log = _workspace_dir() / "chat.jsonl"
            if not log.exists():
                return _tool_result("(no workspace messages yet)")
            lines = log.read_text(encoding="utf-8").splitlines()
            tail = lines[-count:]
            return _tool_result("\n".join(tail) if tail else "(empty)")

        if name == "nexus_status":
            root = _root()
            runtime = root / ".nexus_state" / "runtime.json"
            extra = ""
            if runtime.exists():
                extra = "\n" + runtime.read_text(encoding="utf-8")[:2000]
            return _tool_result(
                f"project_root={root}\nserver={SERVER_NAME} {SERVER_VERSION}" + extra
            )

        if name == "run_project_checks":
            from .github_community import format_loop_report, git_head_sha, run_project_checks
            from .github_community import LoopReport

            timeout = float(args.get("timeout_each") or 180)
            root = _root()
            checks = run_project_checks(root, timeout_each=timeout)
            report = LoopReport(
                sha=git_head_sha(root),
                workdir=str(root),
                checks=checks,
                triggered_by="mcp",
                kind="local",
                number=0,
            )
            # compact JSON for tool result
            summary = {
                "ok": report.ok,
                "sha": report.sha,
                "checks": [
                    {
                        "name": c.name,
                        "ok": c.ok,
                        "returncode": c.returncode,
                        "duration_s": round(c.duration_s, 2),
                    }
                    for c in checks
                ],
            }
            return _tool_result(json.dumps(summary, indent=2))

        if name == "bus_status":
            import urllib.error
            import urllib.request

            port = os.environ.get("NEXUS_BUS_PORT") or "3099"
            url = f"http://127.0.0.1:{port}/api/status"
            try:
                with urllib.request.urlopen(url, timeout=3) as r:
                    body = r.read().decode()[:8000]
                return _tool_result(body)
            except Exception as e:
                return _tool_result(
                    f"bus unreachable at {url}: {e}\n"
                    "Start with: nexus start -y",
                    is_error=True,
                )

        if name == "github_community_status":
            from . import github_community as gc

            repo = args.get("repo")
            try:
                r = gc.resolve_repo(repo)
                gh = "yes" if gc.gh_available() else "no"
                return _tool_result(f"gh={gh}\nrepo={r}\nproject_root={_root()}")
            except Exception as e:
                return _tool_result(str(e), is_error=True)

        if name == "list_platforms":
            from .platforms import detect_platforms, format_status_table

            plats = detect_platforms(project_root=_root())
            return _tool_result(format_status_table(plats))


        if name == "github_scout":
            from . import github_autonomy as ga
            q = str(args.get("query") or "")
            if not q:
                return _tool_result("query required", is_error=True)
            res = ga.scout_other_repos(
                q,
                workdir=_root(),
                limit=int(args.get("limit") or 5),
                connect=bool(args.get("connect", True)),
                prove=bool(args.get("prove", True)),
                run_checks=not bool(args.get("structure_only", True)),
                dry_run=False,
                post_issue=False,
                apply=False,
            )
            # compact
            slim = {k: res.get(k) for k in (
                "query","hits","connected","check_steps_green","repos","notes","clone_root"
            )}
            return _tool_result(json.dumps(slim, indent=2))

        if name == "github_loop":
            from . import github_community as gc
            number = int(args.get("number") or 0)
            if not number:
                return _tool_result("number required", is_error=True)
            res = gc.run_and_post_loop(
                args.get("repo"),
                number,
                workdir=_root(),
                dry_run=bool(args.get("dry_run", True)),
                force=bool(args.get("force", False)),
                triggered_by="mcp",
            )
            return _tool_result(json.dumps(res, indent=2, default=str)[:12000])

        if name == "platforms_connect":
            from . import platforms as plat
            res = plat.connect_all(_root(), force=bool(args.get("force", False)))
            return _tool_result(json.dumps({"results": res.get("results"), "next": res.get("next")}, indent=2))

        if name == "apply_phase":
            from . import improve_apply as ia

            root = _root()
            run_id = args.get("run_id") or None
            fixture = args.get("fixture") or None
            advance = str(args.get("advance") or "all").lower()
            dry_run = bool(args.get("dry_run", True))
            run = ia.resume_or_start(
                root,
                run_id=run_id,
                fixture=fixture,
                dry_run=dry_run,
            )
            if advance in {"status", "show"}:
                status = run.status()
            elif advance in {"one", "step", "next"}:
                status = run.advance_one()
            else:
                status = run.run_to_done()
            slim = {
                "run_id": status.get("run_id"),
                "phase": status.get("phase"),
                "grade": status.get("grade"),
                "audit_path": status.get("audit_path"),
                "context_pack_path": status.get("context_pack_path"),
                "state_path": status.get("state_path"),
                "timeline": status.get("timeline"),
                "audit": status.get("audit"),
            }
            return _tool_result(json.dumps(slim, indent=2, default=str))

        return _tool_result(f"unknown tool: {name}", is_error=True)

    except Exception as e:
        return _tool_result(f"{type(e).__name__}: {e}", is_error=True)


def handle_rpc(msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Handle one JSON-RPC message; return response or None for notifications."""
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "notifications/initialized" or method == "initialized":
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name") or ""
        arguments = params.get("arguments") or {}
        result = call_tool(name, arguments)
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    # ignore unknown notifications
    if mid is None:
        return None

    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _read_message_stdio() -> Optional[dict[str, Any]]:
    """Read one MCP message (Content-Length framed or newline JSON)."""
    # Try Content-Length framing first
    header = b""
    while True:
        ch = sys.stdin.buffer.read(1)
        if not ch:
            return None
        header += ch
        if header.endswith(b"\r\n\r\n"):
            break
        # fallback: if no headers and looks like JSON
        if header.startswith(b"{") and b"\n" in header:
            line = header.decode("utf-8", errors="replace").strip()
            return json.loads(line)

    headers = header.decode("utf-8", errors="replace")
    length = 0
    for line in headers.split("\r\n"):
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message_stdio(msg: dict[str, Any]) -> None:
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def run_stdio() -> int:
    """Run MCP over stdin/stdout (Claude Desktop style)."""
    while True:
        try:
            msg = _read_message_stdio()
        except Exception:
            traceback.print_exc(file=sys.stderr)
            break
        if msg is None:
            break
        try:
            resp = handle_rpc(msg)
            if resp is not None:
                _write_message_stdio(resp)
        except Exception as e:
            mid = msg.get("id")
            if mid is not None:
                _write_message_stdio(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "error": {"code": -32000, "message": str(e)},
                    }
                )
    return 0


def run_http(host: str = "127.0.0.1", port: int = 8765) -> int:
    """Minimal HTTP JSON tools API for demos (not full MCP-over-SSE)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, code: int, obj: Any) -> None:
            raw = json.dumps(obj, indent=2).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("access-control-allow-origin", "*")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-methods", "GET,POST,OPTIONS")
            self.send_header("access-control-allow-headers", "content-type")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path in ("/", "/health"):
                return self._send(
                    200,
                    {
                        "ok": True,
                        "server": SERVER_NAME,
                        "version": SERVER_VERSION,
                        "project_root": str(_root()),
                        "tools": [t["name"] for t in TOOLS],
                    },
                )
            if self.path == "/tools":
                return self._send(200, {"tools": TOOLS})
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            n = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/tools/call":
                name = body.get("name") or ""
                result = call_tool(name, body.get("arguments") or {})
                return self._send(200, result)
            if self.path == "/rpc":
                resp = handle_rpc(body)
                return self._send(200, resp or {"ok": True})
            self._send(404, {"error": "not found"})

    httpd = HTTPServer((host, port), H)
    print(
        f"[nexus-mcp] HTTP tools API http://{host}:{port}  root={_root()}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[nexus-mcp] POST /tools/call  GET /tools  GET /health",
        file=sys.stderr,
        flush=True,
    )
    httpd.serve_forever()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="NEXUS Workspace MCP server")
    ap.add_argument(
        "--http",
        action="store_true",
        help="run simple HTTP tools API instead of stdio MCP",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument(
        "--project-root",
        default=None,
        help="override NEXUS_PROJECT_ROOT",
    )
    args = ap.parse_args(argv)
    if args.project_root:
        os.environ["NEXUS_PROJECT_ROOT"] = str(Path(args.project_root).resolve())
    if args.http:
        return run_http(args.host, args.port)
    return run_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
