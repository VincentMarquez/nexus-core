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
    {
        "name": "context_get",
        "description": (
            "Read SQLite MCP persistent context for a self-improve run "
            "(key or full map). From cas/lumen durable context pattern."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Context run id"},
                "key": {
                    "type": "string",
                    "description": "Optional key; omit for full map",
                },
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "context_set",
        "description": (
            "Write a key into SQLite MCP persistent context for a self-improve run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "key": {"type": "string"},
                "value": {
                    "description": "String or JSON-serializable value",
                },
                "agent": {"type": "string", "default": ""},
            },
            "required": ["run_id", "key", "value"],
        },
    },
    {
        "name": "handoff",
        "description": (
            "Record agent handoff in durable MCP context (from→to + summary). "
            "Swarm/cas-shaped; persists across restarts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "from_agent": {"type": "string"},
                "to_agent": {"type": "string"},
                "summary": {"type": "string", "default": ""},
            },
            "required": ["run_id", "from_agent", "to_agent"],
        },
    },
    {
        "name": "demo_loop",
        "description": (
            "Run/resume durable self-improve demo-loop: ordered stages + "
            "verify-before-done + grade row. Restart-safe via run_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Resume id (optional)"},
                "goal": {"type": "string"},
                "stop_after": {
                    "type": "string",
                    "description": "Stop after stage (e.g. apply) for restart demos",
                },
            },
        },
    },
    {
        "name": "ops_control",
        "description": (
            "Mission-control ops plane: list/show jobs and spend rollups "
            "(mine/alive/improve/task). action=list|show|spend|status|record."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "list | show | spend | status | record",
                    "default": "list",
                },
                "job_id": {"type": "string", "description": "Required for show/record"},
                "kind": {"type": "string", "description": "Filter kind for list"},
                "status": {"type": "string", "description": "Filter status for list"},
                "tokens": {
                    "type": "integer",
                    "description": "Tokens to record (action=record)",
                },
                "source": {"type": "string", "default": "mcp"},
                "label": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "context_pack",
        "description": (
            "Build a bounded multi-source context pack (goal/grade/research/"
            "repo digests/journal) — P1.4 context engineering. "
            "Pass task_id for a durable task, or grade+notes for ad-hoc."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Durable task id (optional)",
                },
                "research": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include latest arXiv improve notes",
                },
                "repos": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include mined repo digests",
                },
                "prompt": {
                    "type": "boolean",
                    "default": False,
                    "description": "Return markdown prompt only",
                },
                "objective": {
                    "type": "string",
                    "description": "Ad-hoc objective when no task_id",
                },
            },
        },
    },
    {
        "name": "gap_board",
        "description": (
            "P1.5 principled-stop gap board: list open/closed gaps, seed from "
            "LATEST_IMPROVE_PLAN / IMPROVE_OURS, or close a gap with evidence. "
            "action=list|seed|close."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "list | seed | close",
                    "default": "list",
                },
                "gap_id": {
                    "type": "string",
                    "description": "Required for action=close",
                },
                "evidence": {
                    "type": "string",
                    "description": "Evidence when closing a gap",
                    "default": "",
                },
                "reopen": {
                    "type": "boolean",
                    "description": "With seed: reopen previously closed plan gaps",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "vault_status",
        "description": (
            "P1.5 secrets vault presence report (booleans only — never returns "
            "secret values). Optional key to check a single name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "If set, report only this key's presence/source",
                },
            },
        },
    },
    {
        "name": "list_graded_candidates",
        "description": (
            "List offline Grok grade artifacts (repo/score/idea/skill/method/path) "
            "from IMPROVE_OURS / mine digests. First-apply slice P0.2/P0.3."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_score": {"type": "number", "default": 10.0},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "get_grade",
        "description": (
            "Get one Grok grade artifact by repo id (offline, no network)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "owner/name e.g. ahmedEid1/lumen",
                },
            },
            "required": ["repo"],
        },
    },
    {
        "name": "get_run_checkpoint",
        "description": (
            "Read durable checkpoint for a grade_loop or improve_apply run "
            "(next_agent + action_order — AOAD-MAT ordered resume)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "get_run_status",
        "description": (
            "Query grade_loop / improve_apply run status including success guard "
            "(score threshold + audit + resume_ok)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "skillpacks",
        "description": (
            "P2.1 multi-harness skill packs: list / validate / generate / drift "
            "from skillpacks/*/SKILL.md + manifest.json (wshobson-style adapters)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "list | validate | generate | drift",
                    "default": "list",
                },
                "pack": {
                    "type": "string",
                    "description": "Optional pack id for validate/generate",
                },
                "harness": {
                    "type": "string",
                    "description": "Optional single harness for generate",
                },
                "max_privilege": {
                    "type": "string",
                    "description": "read|write|ops|admin filter (least-privilege)",
                },
                "clean": {
                    "type": "boolean",
                    "default": False,
                    "description": "With generate: remove prior artifacts first",
                },
            },
        },
    },
    {
        "name": "tool_catalog",
        "description": (
            "P2.2 OpenAPI-ish MCP tool catalog: list / validate / export / openapi "
            "from TOOLS[] with privilege ladder (mission-control-shaped export)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "list | validate | export | openapi | catalog",
                    "default": "list",
                },
                "max_privilege": {
                    "type": "string",
                    "description": "read|write|ops|admin filter (least-privilege)",
                },
                "out_dir": {
                    "type": "string",
                    "description": "Relative export dir (default .nexus_state/tool_catalog)",
                },
            },
        },
    },
    {
        "name": "mcp_eval",
        "description": (
            "P2.3/P2.4 domain MCP eval smoke (AssetOpsBench-shaped): list/run "
            "built-in + JSON scenario packs; offline code-based scorers; optional "
            "export under .nexus_state/mcp_eval/."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "list | run | smoke | packs (default: smoke)",
                    "default": "smoke",
                },
                "domain": {
                    "type": "string",
                    "description": "Filter domain (workspace|status|catalog|…); comma-separated ok",
                },
                "max_privilege": {
                    "type": "string",
                    "description": "read|write|ops|admin — skip higher-priv scenarios",
                },
                "pack": {
                    "type": "string",
                    "description": "JSON scenario pack path(s), comma-separated (P2.4)",
                },
                "no_builtin": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, skip built-in suite (packs only)",
                },
                "discover_packs": {
                    "type": "boolean",
                    "default": False,
                    "description": "Also load *.json under .nexus_state/mcp_eval/packs",
                },
                "install_samples": {
                    "type": "boolean",
                    "default": False,
                    "description": "Copy fixtures/mcp_eval/packs into .nexus_state/mcp_eval/packs",
                },
                "export": {
                    "type": "boolean",
                    "default": True,
                    "description": "Write report under .nexus_state/mcp_eval",
                },
                "out_dir": {
                    "type": "string",
                    "description": "Relative export dir (default .nexus_state/mcp_eval)",
                },
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

        if name == "context_get":
            from .context_store import ContextStore, ContextStoreError

            rid = str(args.get("run_id") or "").strip()
            if not rid:
                return _tool_result("run_id required", is_error=True)
            try:
                with ContextStore.open(_root()) as store:
                    if store.get_run(rid) is None:
                        return _tool_result(f"unknown run: {rid}", is_error=True)
                    val = store.context_get(rid, args.get("key"))
                    return _tool_result(json.dumps(val, indent=2, default=str))
            except ContextStoreError as e:
                return _tool_result(str(e), is_error=True)

        if name == "context_set":
            from .context_store import ContextStore, ContextStoreError

            rid = str(args.get("run_id") or "").strip()
            key = str(args.get("key") or "").strip()
            if not rid or not key:
                return _tool_result("run_id and key required", is_error=True)
            if "value" not in args:
                return _tool_result("value required", is_error=True)
            try:
                with ContextStore.open(_root()) as store:
                    if store.get_run(rid) is None:
                        store.create_run(run_id=rid, goal="mcp context_set")
                    row = store.context_set(
                        rid,
                        key,
                        args.get("value"),
                        agent=str(args.get("agent") or "mcp"),
                    )
                    return _tool_result(json.dumps(row, indent=2, default=str))
            except ContextStoreError as e:
                return _tool_result(str(e), is_error=True)

        if name == "handoff":
            from .context_store import ContextStore, ContextStoreError

            rid = str(args.get("run_id") or "").strip()
            fr = str(args.get("from_agent") or "").strip()
            to = str(args.get("to_agent") or "").strip()
            if not rid or not fr or not to:
                return _tool_result(
                    "run_id, from_agent, to_agent required", is_error=True
                )
            try:
                with ContextStore.open(_root()) as store:
                    if store.get_run(rid) is None:
                        store.create_run(run_id=rid, goal="mcp handoff")
                    body = store.handoff(
                        rid,
                        from_agent=fr,
                        to_agent=to,
                        summary=str(args.get("summary") or ""),
                    )
                    return _tool_result(json.dumps(body, indent=2, default=str))
            except ContextStoreError as e:
                return _tool_result(str(e), is_error=True)

        if name == "demo_loop":
            from . import context_store as cs

            report = cs.run_demo_loop(
                _root(),
                run_id=args.get("run_id") or None,
                goal=str(
                    args.get("goal")
                    or "prove durable MCP context + verify-before-done"
                ),
                stop_after=args.get("stop_after") or None,
            )
            return _tool_result(json.dumps(report, indent=2, default=str))

        if name == "context_pack":
            from .config import Settings
            from .context_pack import build_context_pack
            from .engine import DurableEngine

            root = _root()
            task_id = args.get("task_id") or None
            want_prompt = bool(args.get("prompt", False))
            include_research = bool(args.get("research", True))
            include_repos = bool(args.get("repos", True))
            if task_id:
                settings = Settings(state_dir=root / ".nexus_state", autonomy=False)
                engine = DurableEngine(settings=settings, auto_approve=True)
                rep = engine.context_pack(
                    str(task_id),
                    include_research=include_research,
                    include_repo_digests=include_repos,
                )
                if not rep.get("found"):
                    return _tool_result(
                        rep.get("error") or f"task not found: {task_id}",
                        is_error=True,
                    )
                if want_prompt:
                    return _tool_result(str(rep.get("prompt") or ""))
                slim = {
                    k: rep.get(k)
                    for k in (
                        "schema",
                        "task_id",
                        "status",
                        "total_chars",
                        "total_budget",
                        "est_tokens",
                        "n_sections",
                        "truncated_sections",
                        "summary",
                        "prompt",
                    )
                }
                slim["sections"] = [
                    {
                        "name": s.get("name"),
                        "chars": s.get("chars"),
                        "source": s.get("source"),
                        "truncated": s.get("truncated"),
                    }
                    for s in (rep.get("sections") or [])
                ]
                return _tool_result(json.dumps(slim, indent=2, default=str))
            # Ad-hoc pack from workdir sources
            pack = build_context_pack(
                workdir=root,
                objective=str(args.get("objective") or "context pack"),
                include_research=include_research,
                include_repo_digests=include_repos,
                meta={"source": "mcp"},
            )
            if want_prompt:
                return _tool_result(pack.prompt_block())
            return _tool_result(json.dumps(pack.to_dict(), indent=2, default=str)[:12000])

        if name == "gap_board":
            from . import alive as al

            root = _root()
            action = str(args.get("action") or "list").lower()
            try:
                if action in {"seed", "refresh"}:
                    out = al.seed_gaps(
                        root,
                        reopen_closed=bool(args.get("reopen", False)),
                    )
                    # drop full gaps list if huge — keep registered/closed
                    slim = {
                        k: out.get(k)
                        for k in (
                            "schema",
                            "n_plan",
                            "registered",
                            "closed",
                            "skipped",
                            "board",
                            "path",
                        )
                    }
                    slim["snapshot_counts"] = (out.get("snapshot") or {}).get("counts")
                    return _tool_result(json.dumps(slim, indent=2, default=str))
                if action == "close":
                    gid = str(args.get("gap_id") or "").strip()
                    if not gid:
                        return _tool_result("gap_id required for close", is_error=True)
                    out = al.close_gap(
                        gid,
                        root,
                        evidence=str(args.get("evidence") or "mcp close"),
                    )
                    return _tool_result(json.dumps(out, indent=2, default=str))
                # list
                out = al.gap_board(root)
                return _tool_result(json.dumps(out, indent=2, default=str))
            except KeyError as e:
                return _tool_result(str(e), is_error=True)
            except Exception as e:
                return _tool_result(f"gap_board error: {e}", is_error=True)

        if name == "vault_status":
            from . import vault as vmod

            root = _root()
            vault = vmod.Vault(workdir=root)
            key = str(args.get("key") or "").strip()
            if key:
                return _tool_result(
                    json.dumps(
                        {
                            "schema": vmod.SCHEMA,
                            "key": key,
                            "present": vault.present(key),
                            "source": vault.source_of(key),
                        },
                        indent=2,
                    )
                )
            # presence only — never values
            return _tool_result(json.dumps(vault.status(), indent=2, default=str))

        if name == "list_graded_candidates":
            from . import grade_artifact as ga

            root = _root()
            rows = ga.list_graded_candidates(
                root,
                min_score=float(args.get("min_score") or ga.DEFAULT_SCORE_THRESHOLD),
                limit=int(args.get("limit") or 20),
            )
            slim = [
                {
                    "repo": r.get("repo"),
                    "score": r.get("score"),
                    "idea": r.get("idea"),
                    "skill": r.get("skill"),
                    "method": r.get("method"),
                    "path": r.get("path"),
                }
                for r in rows
            ]
            return _tool_result(
                json.dumps(
                    {"schema": ga.SCHEMA_VERSION, "count": len(slim), "candidates": slim},
                    indent=2,
                    default=str,
                )
            )

        if name == "get_grade":
            from . import grade_artifact as ga

            root = _root()
            repo = str(args.get("repo") or "").strip()
            if not repo:
                return _tool_result("repo required", is_error=True)
            g = ga.get_grade(root, repo)
            if not g:
                return _tool_result(f"grade not found: {repo}", is_error=True)
            return _tool_result(json.dumps(g, indent=2, default=str))

        if name == "get_run_checkpoint":
            from . import grade_artifact as ga

            root = _root()
            run_id = str(args.get("run_id") or "").strip()
            if not run_id:
                return _tool_result("run_id required", is_error=True)
            try:
                cp = ga.get_run_checkpoint(root, run_id)
            except FileNotFoundError as e:
                return _tool_result(str(e), is_error=True)
            return _tool_result(json.dumps(cp, indent=2, default=str))

        if name == "get_run_status":
            from . import grade_artifact as ga

            root = _root()
            run_id = str(args.get("run_id") or "").strip()
            if not run_id:
                return _tool_result("run_id required", is_error=True)
            try:
                st = ga.get_run_status(root, run_id)
            except FileNotFoundError as e:
                return _tool_result(str(e), is_error=True)
            return _tool_result(json.dumps(st, indent=2, default=str)[:12000])

        if name == "skillpacks":
            from . import skillpacks as sp

            root = _root()
            action = str(args.get("action") or "list").lower().strip()
            pack = str(args.get("pack") or "").strip() or None
            max_priv = args.get("max_privilege") or None
            try:
                if action == "list":
                    rows = sp.list_packs(root, max_privilege=max_priv)
                    return _tool_result(
                        json.dumps(
                            {
                                "schema": sp.SCHEMA_VERSION,
                                "count": len(rows),
                                "packs": [r.to_dict() for r in rows],
                            },
                            indent=2,
                            default=str,
                        )
                    )
                if action == "validate":
                    if pack:
                        pdir = root / sp.DEFAULT_PACKS_DIR / pack
                        rep = sp.validate_pack(pdir)
                        data = {
                            "schema": sp.SCHEMA_VERSION,
                            "ok": rep.ok,
                            "count": 1,
                            "packs": [rep.to_dict()],
                            "errors": sum(
                                1 for f in rep.findings if f.severity == "error"
                            ),
                            "warnings": sum(
                                1 for f in rep.findings if f.severity == "warning"
                            ),
                        }
                    else:
                        data = sp.validate_all(root)
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action == "generate":
                    harnesses = None
                    if args.get("harness"):
                        harnesses = [str(args.get("harness"))]
                    clean = bool(args.get("clean"))
                    if pack:
                        one = sp.generate_pack(
                            root / sp.DEFAULT_PACKS_DIR / pack,
                            out_root=sp.generate_root(root),
                            harnesses=harnesses,
                            clean=clean,
                        )
                        data = {
                            "schema": sp.SCHEMA_VERSION,
                            "ok": True,
                            "out_root": one["out_root"],
                            "generated": [one],
                            "errors": [],
                            "count": 1,
                        }
                    else:
                        data = sp.generate_all(
                            root,
                            harnesses=harnesses,
                            clean=clean,
                            max_privilege=max_priv,
                        )
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action == "drift":
                    data = sp.drift_check(root)
                    return _tool_result(json.dumps(data, indent=2, default=str))
            except sp.SkillpackError as e:
                return _tool_result(f"SkillpackError: {e}", is_error=True)
            except Exception as e:
                return _tool_result(f"skillpacks error: {e}", is_error=True)
            return _tool_result(
                f"unknown skillpacks action: {action} "
                "(list|validate|generate|drift)",
                is_error=True,
            )

        if name == "tool_catalog":
            from . import tool_catalog as tc

            action = str(args.get("action") or "list").lower()
            max_priv = args.get("max_privilege") or None
            try:
                if action == "list":
                    entries = tc.build_entries(max_privilege=max_priv)
                    return _tool_result(
                        json.dumps(
                            {
                                "schema": tc.SCHEMA_VERSION,
                                "count": len(entries),
                                "tools": [e.to_dict() for e in entries],
                            },
                            indent=2,
                            default=str,
                        )
                    )
                if action in ("catalog", "export"):
                    out_dir = str(
                        args.get("out_dir") or tc.DEFAULT_OUT_DIR
                    ).lstrip("/\\")
                    # Keep export under project root (path jail)
                    if ".." in Path(out_dir).parts:
                        return _tool_result(
                            "out_dir escapes project root", is_error=True
                        )
                    if action == "catalog":
                        data = tc.build_catalog(max_privilege=max_priv)
                        # compact JSON — full catalog must stay parseable
                        return _tool_result(json.dumps(data, default=str))
                    result = tc.export_catalog(
                        _root(), out_dir=out_dir, max_privilege=max_priv
                    )
                    return _tool_result(json.dumps(result, indent=2, default=str))
                if action == "openapi":
                    data = tc.build_openapi(max_privilege=max_priv)
                    # compact + no mid-document truncation (clients parse this)
                    return _tool_result(json.dumps(data, default=str))
                if action == "validate":
                    rep = tc.validate_tools()
                    return _tool_result(
                        json.dumps(rep.to_dict(), indent=2, default=str)
                    )
            except tc.CatalogError as e:
                return _tool_result(f"CatalogError: {e}", is_error=True)
            except Exception as e:
                return _tool_result(f"tool_catalog error: {e}", is_error=True)
            return _tool_result(
                f"unknown tool_catalog action: {action} "
                "(list|validate|export|openapi|catalog)",
                is_error=True,
            )

        if name == "mcp_eval":
            from . import mcp_eval as me

            action = str(args.get("action") or "smoke").lower()
            max_priv = args.get("max_privilege") or None
            domain_raw = str(args.get("domain") or "").strip()
            domains = (
                [d.strip() for d in domain_raw.split(",") if d.strip()]
                if domain_raw
                else None
            )
            pack_raw = str(args.get("pack") or "").strip()
            pack_paths: list[str] = []
            root = _root()
            for part in pack_raw.split(",") if pack_raw else []:
                part = part.strip()
                if not part:
                    continue
                pp = Path(part)
                pack_paths.append(str(pp if pp.is_absolute() else (root / pp)))
            include_builtin = not bool(args.get("no_builtin", False))
            discover = bool(args.get("discover_packs", False))
            install_samples = bool(args.get("install_samples", False))
            try:
                if action == "packs":
                    install_result = None
                    if install_samples:
                        install_result = me.ensure_sample_packs(root)
                    found = me.discover_packs(root)
                    bundled = me.list_bundled_packs(root)
                    payload: dict[str, Any] = {
                        "schema": me.SCENARIO_PACK_SCHEMA,
                        "count": len(found),
                        "packs": [str(p) for p in found],
                        "bundled": [str(p) for p in bundled],
                        "bundled_count": len(bundled),
                    }
                    if install_result is not None:
                        payload["install"] = install_result
                    return _tool_result(
                        json.dumps(payload, indent=2, default=str)
                    )
                if action == "list":
                    if install_samples:
                        me.ensure_sample_packs(root)
                        discover = True
                    rows = me.list_scenarios(
                        workdir=root,
                        packs=pack_paths or None,
                        include_builtin=include_builtin,
                        discover_packs_flag=discover,
                        domains=domains,
                        max_privilege=max_priv,
                    )
                    return _tool_result(
                        json.dumps(
                            {
                                "schema": me.SCHEMA_VERSION,
                                "count": len(rows),
                                "packs": pack_paths,
                                "scenarios": rows,
                            },
                            indent=2,
                            default=str,
                        )
                    )
                if action in ("run", "smoke", "evaluate"):
                    if install_samples:
                        me.ensure_sample_packs(root)
                        discover = True
                    do_export = bool(args.get("export", True))
                    out_dir = str(
                        args.get("out_dir") or me.DEFAULT_OUT_DIR
                    ).lstrip("/\\")
                    if ".." in Path(out_dir).parts:
                        return _tool_result(
                            "out_dir escapes project root", is_error=True
                        )
                    report = me.run_and_export(
                        root,
                        domains=domains,
                        max_privilege=max_priv,
                        out_dir=out_dir,
                        export=do_export,
                        packs=pack_paths or None,
                        include_builtin=include_builtin,
                        discover_packs_flag=discover,
                    )
                    # Keep MCP payload bounded (drop full trajectories)
                    slim = {
                        k: v
                        for k, v in report.items()
                        if k not in {"trajectories"}
                    }
                    # trim long previews
                    for r in slim.get("results") or []:
                        if isinstance(r, dict) and "answer_preview" in r:
                            r["answer_preview"] = str(r["answer_preview"])[:120]
                    return _tool_result(
                        json.dumps(slim, indent=2, default=str)
                    )
            except Exception as e:
                return _tool_result(f"mcp_eval error: {e}", is_error=True)
            return _tool_result(
                f"unknown mcp_eval action: {action} (list|run|smoke|packs)",
                is_error=True,
            )

        if name == "ops_control":
            from .ops_store import OpsStore, OpsError

            root = _root()
            action = str(args.get("action") or "list").lower()
            try:
                with OpsStore.open(root) as store:
                    if action == "list":
                        rows = store.list_jobs(
                            kind=args.get("kind") or None,
                            status=args.get("status") or None,
                            limit=int(args.get("limit") or 50),
                        )
                        return _tool_result(json.dumps(rows, indent=2, default=str))
                    if action == "show":
                        jid = str(args.get("job_id") or "")
                        job = store.get(jid)
                        if not job:
                            return _tool_result(f"job not found: {jid}", is_error=True)
                        return _tool_result(
                            json.dumps(
                                {"job": job, "spend": store.spend_report(jid)},
                                indent=2,
                                default=str,
                            )
                        )
                    if action == "spend":
                        jid = args.get("job_id") or None
                        return _tool_result(
                            json.dumps(
                                store.spend_report(jid),
                                indent=2,
                                default=str,
                            )
                        )
                    if action == "status":
                        return _tool_result(
                            json.dumps(store.summary(), indent=2, default=str)
                        )
                    if action == "record":
                        jid = str(args.get("job_id") or "")
                        tokens = int(args.get("tokens") or 0)
                        if not jid:
                            return _tool_result("job_id required", is_error=True)
                        row = store.record_spend(
                            jid,
                            tokens,
                            source=str(args.get("source") or "mcp"),
                            label=str(args.get("label") or ""),
                            dual_write_usage=False,
                            ensure=True,
                            kind=str(args.get("kind") or "task"),
                        )
                        return _tool_result(json.dumps(row, indent=2, default=str))
            except OpsError as e:
                return _tool_result(f"OpsError: {e}", is_error=True)
            return _tool_result(
                f"unknown ops action: {action} (list|show|spend|status|record)",
                is_error=True,
            )

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
            if self.path in ("/openapi.json", "/openapi"):
                from . import tool_catalog as tc

                return self._send(200, tc.build_openapi())
            if self.path in ("/catalog.json", "/catalog"):
                from . import tool_catalog as tc

                return self._send(200, tc.build_catalog())
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
        f"[nexus-mcp] POST /tools/call  GET /tools  GET /openapi.json  GET /health",
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
