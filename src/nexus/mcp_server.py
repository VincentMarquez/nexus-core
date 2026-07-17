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
SERVER_VERSION = "0.8.0"
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
        "name": "github_mine",
        "description": (
            "Research INPUT only: find high-star public GitHub repos (default ≥5000★). "
            "Does not replace the pipeline — feed results into canonical_pipeline. "
            "mode=search (fast) or full (fetch/grade). Read-only; no apply."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search topic, e.g. multi-agent orchestration",
                },
                "min_stars": {
                    "type": "integer",
                    "description": "Minimum stars (default 5000)",
                    "default": 5000,
                },
                "limit": {"type": "integer", "default": 15},
                "language": {
                    "type": "string",
                    "description": "GitHub language filter (default Python; empty = any)",
                    "default": "Python",
                },
                "mode": {
                    "type": "string",
                    "description": "search | full (default search)",
                    "default": "search",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "canonical_pipeline",
        "description": (
            "ONE unified flow for lab + alive + agents: optional GitHub≥5K★ research input, "
            "then DurableEngine steps goal→plan→challenge→implement→test→review→log→"
            "meta_review→approval→deliver with ConsensusJudge/RubricJudge on every step. "
            "Not a parallel multi-agent invention. Prefer this over free-form debate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Topic / goal for the pipeline",
                },
                "include_github_mine": {
                    "type": "boolean",
                    "description": "Prepend high-star GitHub mine as research brief",
                    "default": True,
                },
                "min_stars": {"type": "integer", "default": 5000},
                "research_brief": {
                    "type": "string",
                    "description": "Optional extra context (arXiv notes, dual review)",
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Optional cap on engine steps this run",
                },
                "auto_approve": {
                    "type": "boolean",
                    "description": "Skip human approval pause (default true for automation)",
                    "default": True,
                },
            },
            "required": ["query"],
        },
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
        "name": "compute_budget",
        "description": (
            "FutureWeaver × mission-control budget plane: plan multi-agent "
            "test-time compute, hard-limit per-agent usage, reclaim modular "
            "shares, and report agent spend on the SQLite ops board. "
            "action=plan|status|record|report|brief|rebalance|finish."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "plan | status | record | report | brief | rebalance | finish"
                    ),
                    "default": "status",
                },
                "job_id": {
                    "type": "string",
                    "description": "Ops job / task id (omit for pure plan)",
                },
                "agent": {
                    "type": "string",
                    "description": "Agent id for record/finish",
                },
                "tokens": {
                    "type": "integer",
                    "description": "Tokens for record",
                    "default": 0,
                },
                "steps": {"type": "integer", "default": 0},
                "total_tokens": {
                    "type": "integer",
                    "description": "Pool size for plan",
                },
                "strategy": {
                    "type": "string",
                    "description": "equal | weighted | modular",
                    "default": "weighted",
                },
                "agents": {
                    "type": "string",
                    "description": "Comma-separated agent roster for plan",
                },
                "hard": {
                    "type": "boolean",
                    "default": True,
                    "description": "Hard-fail when share exhausted",
                },
                "finish": {"type": "boolean", "default": False},
                "rebalance": {"type": "boolean", "default": False},
                "status": {
                    "type": "string",
                    "description": "Terminal job status when action=finish without agent",
                },
                "title": {"type": "string"},
                "goal": {"type": "string"},
                "kind": {"type": "string", "default": "task"},
                "limit": {"type": "integer", "default": 500},
            },
        },
    },
    {
        "name": "context_pack",
        "description": (
            "Build a bounded multi-source context pack (goal/grade/preference/"
            "research/repo digests/journal) — P1.4 + P1.1 preference brief. "
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
                "preference": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Include offline preference brief (arXiv 2602.04518) "
                        "when pairs exist under .nexus_state/preference_pairs.jsonl"
                    ),
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
        "name": "index_workspace",
        "description": (
            "Index offline grade fixtures + research claims into SQLite FTS "
            "(cas-style evidence context). No network; used by make mcp-smoke."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "clear": {
                    "type": "boolean",
                    "default": True,
                    "description": "Clear existing index before reindex",
                },
            },
        },
    },
    {
        "name": "search_evidence",
        "description": (
            "FTS search over indexed Grok grade claims and arXiv research "
            "snippets (Thucy path anchors). Auto-indexes fixtures if empty."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query e.g. 'Markdown marketplace'",
                },
                "k": {"type": "integer", "default": 10},
                "kind": {
                    "type": "string",
                    "description": "Optional filter: claim|grade|paper|digest",
                },
                "auto_index": {
                    "type": "boolean",
                    "default": True,
                    "description": "Index fixtures first if DB missing",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "apply_select",
        "description": (
            "Rank apply candidates by Grok grade score + FTS evidence hits, "
            "optionally emit a role-separated decision package "
            "(grader ≠ implementer ≠ verifier). Offline fixtures/digests."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional FTS query to boost matching repos",
                },
                "repo": {
                    "type": "string",
                    "description": "When set with decide=true, build package for this repo",
                },
                "min_score": {"type": "number", "default": 10.0},
                "limit": {"type": "integer", "default": 5},
                "decide": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, return decision package (roles+budget+evidence)",
                },
                "grader": {"type": "string", "default": "grok:grade"},
                "implementer": {"type": "string", "default": "worker:apply"},
                "verifier": {"type": "string", "default": "judge:verify"},
                "require_evidence": {"type": "boolean", "default": True},
                "auto_index": {"type": "boolean", "default": True},
                "use_spine": {
                    "type": "boolean",
                    "default": True,
                    "description": "Merge durable improve_spine grades + method into rank",
                },
                "use_preference": {
                    "type": "boolean",
                    "default": True,
                    "description": "Apply offline preference boost to rank",
                },
                "run_id": {
                    "type": "string",
                    "description": "Optional improve_spine run id for spine grades",
                },
            },
        },
    },
    {
        "name": "mine_eval_slice",
        "description": (
            "First apply slice (plan §5): load offline grade → append-only ledger "
            "with causal_note → claim verify → MINED→GRADED→CLAIM_OK→APPLY_CANDIDATE "
            "sandbox worktree dry-run (plan-reuse cache). No network; no promote."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "default": "wshobson/agents",
                    "description": "repo_or_paper_id from fixture",
                },
                "fixture": {
                    "type": "string",
                    "description": "Optional path to mine_eval JSON fixture",
                },
                "run_id": {"type": "string"},
                "min_score": {"type": "number", "default": 14.0},
                "test_exit_code": {"type": "integer", "default": 0},
            },
        },
    },
    {
        "name": "improve_board",
        "description": (
            "routa-lite improve board: goal, roles, ranked candidates with "
            "evidence, decision allow/deny, recent ledger traces."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
                "min_score": {"type": "number", "default": 10.0},
                "limit": {"type": "integer", "default": 5},
                "goal": {
                    "type": "string",
                    "default": "self-improve nexus-core from mined repos + arXiv",
                },
                "grader": {"type": "string"},
                "implementer": {"type": "string"},
                "verifier": {"type": "string"},
                "auto_index": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "ledger_append",
        "description": (
            "Append one immutable work_ledger row (nexus.improve_spine/v1). "
            "Plan MCP tool ledger.append — no update/delete."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "stage": {
                    "type": "string",
                    "description": "scouted|graded|apply_pending",
                },
                "agent": {"type": "string"},
                "action": {"type": "string"},
                "payload": {"type": "object"},
                "parent_id": {"type": "string", "default": ""},
            },
            "required": ["run_id", "stage", "agent", "action"],
        },
    },
    {
        "name": "ledger_list",
        "description": (
            "List append-only work_ledger events for a run "
            "(nexus.improve_spine/v1 — plan MCP tool ledger.list)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "stage": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "grade_get",
        "description": (
            "Get one durable grade_records row by repo_or_paper_id "
            "(nexus.improve_spine/v1 — plan MCP tool grade.get)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_or_paper_id": {
                    "type": "string",
                    "description": "e.g. codingagentsystem/cas or arXiv id",
                },
                "repo": {
                    "type": "string",
                    "description": "alias for repo_or_paper_id",
                },
                "run_id": {"type": "string"},
                "method": {"type": "string"},
            },
        },
    },
    {
        "name": "work_ledger",
        "description": (
            "Append-only work ledger (nexus.work_ledger/v1): dual-control "
            "mine→grade→decision→apply_accepted, causal chain, and offline "
            "first-slice. Actions: status|tail|chain|gate|first_slice|transitions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "status",
                        "tail",
                        "chain",
                        "gate",
                        "first_slice",
                        "transitions",
                    ],
                    "default": "status",
                },
                "run_id": {"type": "string"},
                "repo": {
                    "type": "string",
                    "description": "Repo for gate/first_slice (e.g. wshobson/agents)",
                },
                "limit": {"type": "integer", "default": 20},
                "score_threshold": {"type": "number"},
                "grader": {"type": "string", "default": "grok:grade"},
                "applier": {"type": "string", "default": "worker:apply"},
                "pattern_name": {"type": "string"},
                "accept": {
                    "type": "boolean",
                    "default": True,
                    "description": "gate/first_slice: accept (true) or reject path",
                },
            },
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
        "name": "run_task",
        "description": (
            "Orchestrator: start an async durable task (kind=task|research). "
            "Returns task_id immediately; poll with get_task_status. "
            "agent_mode=demo (default/auto) uses MockAgent panel; fake completes instantly; "
            "bus uses event bus if up else blocked. Does not auto-start the bus. "
            "with_plan=true runs dedicated multi-LLM Planner (arXiv 2401.07324) before "
            "orchestration; structured plan is stored on envelope and returned in status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Goal / task description",
                },
                "kind": {
                    "type": "string",
                    "description": "task | research",
                    "default": "task",
                },
                "agent_mode": {
                    "type": "string",
                    "description": "auto | demo | fake | bus",
                    "default": "auto",
                },
                "task_id": {
                    "type": "string",
                    "description": "Optional client-supplied id (sanitized)",
                },
                "wait": {
                    "type": "boolean",
                    "description": "Block until terminal (discouraged under NVFP4)",
                    "default": False,
                },
                "wait_timeout_s": {
                    "type": "number",
                    "description": "Max wait seconds when wait=true (cap 300)",
                    "default": 120,
                },
                "with_brief": {
                    "type": "boolean",
                    "description": "Research only: request brief (default false)",
                    "default": False,
                },
                "with_plan": {
                    "type": "boolean",
                    "description": (
                        "Run dedicated Planner (arXiv 2401.07324) before Orchestrator; "
                        "no tool side effects in plan phase"
                    ),
                    "default": False,
                },
                "require_plan": {
                    "type": "boolean",
                    "description": "Fail closed if Planner cannot produce a ready plan",
                    "default": False,
                },
                "plan_max_steps": {
                    "type": "integer",
                    "description": "Max Planner steps when with_plan=true",
                    "default": 5,
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "get_task_status",
        "description": (
            "Orchestrator: poll task status, cancel, or fetch logs. "
            "action=status|cancel|logs. task_id from run_task."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "description": "status | cancel | logs",
                    "default": "status",
                },
                "log_lines": {
                    "type": "integer",
                    "description": "Lines when action=logs",
                    "default": 40,
                },
            },
            "required": ["task_id"],
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
        "name": "marketplace",
        "description": (
            "Plugin marketplace (wshobson-shaped): list / validate / catalog / "
            "collisions / self_check / capabilities / portability / garden / "
            "export multi-harness registries + stubs; generate multi-harness "
            "adapters (frontmatter rewrite, command→skill, skill body cap) + "
            "validate_generated + round_trip count integrity; skillpacks as "
            "thin plugins."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "list | validate | catalog | collisions | self_check | "
                        "capabilities | portability | garden | export | "
                        "generate | validate_generated | round_trip"
                    ),
                    "default": "list",
                },
                "plugin": {
                    "type": "string",
                    "description": (
                        "Optional plugin id for validate / generate / round_trip"
                    ),
                },
                "harness": {
                    "type": "string",
                    "description": (
                        "Optional single harness for export / portability / "
                        "capabilities / generate / validate_generated / "
                        "round_trip"
                    ),
                },
                "max_privilege": {
                    "type": "string",
                    "description": "read|write|ops|admin filter (least-privilege)",
                },
                "include_skillpacks": {
                    "type": "boolean",
                    "description": (
                        "Index skillpacks/ as thin plugins (list/catalog/export/"
                        "self_check/portability/garden). Default true for "
                        "catalog/export/self_check/portability/garden; false "
                        "for round_trip smoke."
                    ),
                },
                "strict_size": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "With garden/portability/self_check: treat Codex 8KiB "
                        "skill oversize as error"
                    ),
                },
                "clean": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "With export: remove prior registry files first. "
                        "With round_trip: clean generated trees (default true)."
                    ),
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
    {
        "name": "maf_bench",
        "description": (
            "MAFBench proxy × AssetOpsBench hybrid (arXiv 2602.03128): list "
            "mechanisms, multi-domain MCP hub, framework overhead bench, "
            "JSON scenario packs with overhead gates, or fast brief "
            "(consensus_overhead_x + pack pass_rate)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "list | run | smoke | pack | packs | brief "
                        "(default: smoke)"
                    ),
                    "default": "smoke",
                },
                "mechanism": {
                    "type": "string",
                    "description": (
                        "Comma-separated mechanism ids "
                        "(single_judge,consensus,trust_log,orch_linear,"
                        "orch_dag,domain_mcp,marketplace,control_plane,"
                        "delivery_board)"
                    ),
                },
                "iters": {
                    "type": "integer",
                    "description": "Iterations per mechanism (default 5 for smoke)",
                },
                "pack": {
                    "type": "string",
                    "description": (
                        "JSON MAF scenario pack path(s), comma-separated "
                        "(AssetOpsBench shape)"
                    ),
                },
                "no_builtin": {
                    "type": "boolean",
                    "default": False,
                    "description": "With pack: skip built-in gate suite",
                },
                "discover_packs": {
                    "type": "boolean",
                    "default": False,
                    "description": "Also load *.json under .nexus_state/bench/packs",
                },
                "install_samples": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Copy fixtures/maf_bench/packs into .nexus_state/bench/packs"
                    ),
                },
                "export": {
                    "type": "boolean",
                    "default": True,
                    "description": "Write report under .nexus_state/bench",
                },
                "out_dir": {
                    "type": "string",
                    "description": "Relative export dir (default .nexus_state/bench)",
                },
            },
        },
    },
    {
        "name": "tool_agent",
        "description": (
            "Multi-LLM tool agent (arXiv 2401.07324): dedicated Planner emits a "
            "structured JSON plan (steps/tools/args) before any Caller tool "
            "execution. Actions: plan (structure only), run (mock Caller), "
            "prompt (Planner LLM block), validate (plan JSON gate), handoff "
            "(Planner → Orchestrator with_plan). Fail-closed without ready plan."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "plan | run | prompt | validate | handoff",
                    "default": "plan",
                },
                "task": {
                    "type": "string",
                    "description": "Task description for Planner",
                },
                "tools": {
                    "type": "string",
                    "description": (
                        "Comma-separated allowed tool names (default: live "
                        "read-tier catalog or built-in stubs)"
                    ),
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Max Planner steps",
                    "default": 5,
                },
                "plan_json": {
                    "type": "string",
                    "description": (
                        "Injected Planner LLM JSON (plan/run/validate/handoff); "
                        "skips heuristic when set"
                    ),
                },
                "plan_text": {
                    "type": "string",
                    "description": "Alias of plan_json (fenced JSON ok)",
                },
                "auto_ready": {
                    "type": "boolean",
                    "description": "Mark plan ready after validate (default true)",
                    "default": True,
                },
                "require_ready": {
                    "type": "boolean",
                    "description": "Handoff: fail closed if plan not ready",
                    "default": True,
                },
                "task_id": {
                    "type": "string",
                    "description": "Handoff: optional Orchestrator task id",
                },
                "agent_mode": {
                    "type": "string",
                    "description": "Handoff agent_mode: fake|demo|auto|bus (default fake)",
                    "default": "fake",
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


def _orch_enabled() -> bool:
    """NEXUS_ORCH=0 omits/refuses orchestration facades."""
    return os.environ.get("NEXUS_ORCH", "1").strip() not in ("0", "false", "no", "off")


def _listed_tools() -> list[dict[str, Any]]:
    if _orch_enabled():
        return TOOLS
    skip = {"run_task", "get_task_status"}
    return [t for t in TOOLS if t.get("name") not in skip]


def call_tool(name: str, arguments: Optional[dict[str, Any]]) -> dict[str, Any]:
    args = arguments or {}
    try:
        if name in ("run_task", "get_task_status") and not _orch_enabled():
            return _tool_result(
                json.dumps(
                    {
                        "error": "orchestrator disabled (NEXUS_ORCH=0)",
                        "code": "orch_disabled",
                    }
                ),
                is_error=True,
            )

        if name == "run_task":
            from . import orchestrator as orch

            try:
                o = orch.Orchestrator(_root())
                out = o.run_task(
                    str(args.get("description") or ""),
                    kind=str(args.get("kind") or "task"),
                    agent_mode=str(args.get("agent_mode") or "auto"),
                    task_id=str(args["task_id"]) if args.get("task_id") else None,
                    wait=bool(args.get("wait") or False),
                    wait_timeout_s=float(args.get("wait_timeout_s") or 120),
                    with_brief=bool(args.get("with_brief") or False),
                    with_plan=bool(args.get("with_plan") or False),
                    require_plan=bool(args.get("require_plan") or False),
                    plan_max_steps=int(args.get("plan_max_steps") or 5),
                    plan_text=str(args["plan_text"]) if args.get("plan_text") else None,
                    sync_fake=(str(args.get("agent_mode") or "").lower() == "fake"),
                )
                return _tool_result(json.dumps(out, indent=2, default=str)[:16000])
            except orch.OrchError as e:
                return _tool_result(
                    json.dumps({"error": str(e), "code": e.code}),
                    is_error=True,
                )
            except Exception as e:
                return _tool_result(
                    f"run_task error: {type(e).__name__}: {e}", is_error=True
                )

        if name == "get_task_status":
            from . import orchestrator as orch

            try:
                o = orch.Orchestrator(_root())
                out = o.get_task_status(
                    str(args.get("task_id") or ""),
                    action=str(args.get("action") or "status"),
                    log_lines=int(args.get("log_lines") or 40),
                )
                return _tool_result(json.dumps(out, indent=2, default=str)[:16000])
            except orch.OrchError as e:
                return _tool_result(
                    json.dumps({"error": str(e), "code": e.code}),
                    is_error=True,
                )
            except Exception as e:
                return _tool_result(
                    f"get_task_status error: {type(e).__name__}: {e}", is_error=True
                )

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

        if name == "github_mine":
            from . import github_autonomy as ga
            from . import repo_mine as rm

            q = str(args.get("query") or "").strip()
            if not q:
                return _tool_result("query required", is_error=True)
            min_stars = int(args.get("min_stars") if args.get("min_stars") is not None else 5000)
            limit = int(args.get("limit") or 15)
            lang_raw = args.get("language")
            language = None if lang_raw in ("", "any", "all", None) else str(lang_raw or "Python")
            mode = str(args.get("mode") or "search").strip().lower()
            try:
                if mode in ("full", "pipeline", "deep"):
                    pipe = rm.run_pipeline(
                        _root(),
                        query=q,
                        fetch_count=min(limit, 20),
                        language=language or "Python",
                        min_stars=min_stars,
                        max_stars=None,
                        eval_limit=min(limit, 12),
                        use_limit=min(8, limit),
                        prove=False,
                        improve=False,
                        apply_improve=False,
                        grader="heuristic",
                    )
                    slim = {
                        "ok": True,
                        "mode": "full",
                        "min_stars": min_stars,
                        "fetch": pipe.get("fetch"),
                        "evaluate": {
                            k: (pipe.get("evaluate") or {}).get(k)
                            for k in ("evaluated", "ok", "grader")
                        },
                        "use": pipe.get("use"),
                        "next": "call canonical_pipeline with this research as research_brief",
                    }
                    return _tool_result(json.dumps(slim, indent=2, default=str)[:12000])
                res = ga.search_high_star_repos(
                    q,
                    min_stars=min_stars,
                    limit=limit,
                    language=language,
                )
                res["next"] = "call canonical_pipeline(query=..., include_github_mine=false, research_brief=...) or include_github_mine=true"
                return _tool_result(json.dumps(res, indent=2)[:12000])
            except Exception as e:
                return _tool_result(f"github_mine error: {e}", is_error=True)

        if name == "canonical_pipeline":
            from . import github_autonomy as ga
            from . import unified_pipeline as up

            q = str(args.get("query") or "").strip()
            if not q:
                return _tool_result("query required", is_error=True)
            brief = str(args.get("research_brief") or "")
            include_mine = bool(args.get("include_github_mine", True))
            min_stars = int(args.get("min_stars") if args.get("min_stars") is not None else 5000)
            try:
                if include_mine and not brief.strip():
                    hs = ga.search_high_star_repos(
                        q, min_stars=min_stars, limit=12, language="Python"
                    )
                    lines = [f"GitHub ≥{min_stars}★ research ({hs.get('count')} repos):"]
                    for r in hs.get("repos") or []:
                        lines.append(
                            f"- {r.get('full_name')} ★{r.get('stars')}: {(r.get('description') or '')[:100]}"
                        )
                    brief = "\n".join(lines)
                max_steps = args.get("max_steps")
                max_steps_i = int(max_steps) if max_steps is not None else None
                res = up.run_canonical(
                    _root(),
                    query=q,
                    research_brief=brief,
                    goal_hint="MCP/agent canonical_pipeline",
                    auto_approve=bool(args.get("auto_approve", True)),
                    max_steps=max_steps_i,
                    source="mcp",
                )
                res["summary"] = up.format_pipeline_summary(res)
                return _tool_result(json.dumps(res, indent=2, default=str)[:14000])
            except Exception as e:
                return _tool_result(f"canonical_pipeline error: {e}", is_error=True)

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
            include_pref = bool(args.get("preference", True))
            if task_id:
                settings = Settings(state_dir=root / ".nexus_state", autonomy=False)
                engine = DurableEngine(settings=settings, auto_approve=True)
                rep = engine.context_pack(
                    str(task_id),
                    include_research=include_research,
                    include_repo_digests=include_repos,
                    include_preference=include_pref,
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
                include_preference=include_pref,
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

        if name == "index_workspace":
            from . import evidence_fts as efts

            root = _root()
            rep = efts.index_workspace(
                root,
                clear=bool(args.get("clear", True)),
            )
            return _tool_result(json.dumps(rep, indent=2, default=str))

        if name == "search_evidence":
            from . import evidence_fts as efts

            root = _root()
            query = str(args.get("query") or "").strip()
            if not query:
                return _tool_result("query required", is_error=True)
            kind = args.get("kind") or None
            if kind is not None:
                kind = str(kind).strip() or None
            res = efts.search_evidence(
                query,
                workdir=root,
                k=int(args.get("k") or 10),
                kind=kind,
                auto_index=bool(args.get("auto_index", True)),
            )
            return _tool_result(json.dumps(res, indent=2, default=str)[:16000])

        if name == "apply_select":
            from . import apply_select as asel

            root = _root()
            try:
                use_spine = bool(args.get("use_spine", True))
                use_preference = bool(args.get("use_preference", True))
                run_id = args.get("run_id") or None
                if bool(args.get("decide")):
                    res = asel.decision_package(
                        root,
                        repo=args.get("repo") or None,
                        query=str(args.get("query") or ""),
                        min_score=float(args.get("min_score") or 10.0),
                        grader=str(args.get("grader") or asel.DEFAULT_ROLES["grader"]),
                        implementer=str(
                            args.get("implementer") or asel.DEFAULT_ROLES["implementer"]
                        ),
                        verifier=str(
                            args.get("verifier") or asel.DEFAULT_ROLES["verifier"]
                        ),
                        require_evidence=bool(args.get("require_evidence", True)),
                        auto_index=bool(args.get("auto_index", True)),
                        use_spine=use_spine,
                        use_preference=use_preference,
                        run_id=run_id,
                    )
                else:
                    res = asel.select_candidates(
                        root,
                        query=str(args.get("query") or ""),
                        min_score=float(args.get("min_score") or 10.0),
                        limit=int(args.get("limit") or 5),
                        require_evidence=bool(args.get("require_evidence", True)),
                        auto_index=bool(args.get("auto_index", True)),
                        use_spine=use_spine,
                        use_preference=use_preference,
                        run_id=run_id,
                    )
                # Surface spine method on the JSON payload (keeps parseable MCP text)
                if isinstance(res, dict):
                    rows = (
                        (res.get("selection") or {}).get("candidates")
                        if isinstance(res.get("selection"), dict)
                        else res.get("candidates")
                    ) or []
                    methods = [
                        {
                            "repo": c.get("repo"),
                            "method": c.get("spine_method") or c.get("method"),
                            "spine_method": c.get("spine_method"),
                            "on_spine": c.get("on_spine"),
                        }
                        for c in rows
                        if isinstance(c, dict)
                        and (c.get("spine_method") or c.get("method") or c.get("on_spine"))
                    ]
                    if methods:
                        res["spine_methods"] = methods[:12]
                        res["spine_method_text"] = "; ".join(
                            f"{m.get('repo')}:{m.get('method')}"
                            for m in methods[:8]
                            if m.get("method")
                        )
                    res["use_spine"] = use_spine
                    res["use_preference"] = use_preference
                    if run_id:
                        res["run_id"] = run_id
            except Exception as e:
                return _tool_result(f"apply_select error: {e}", is_error=True)
            return _tool_result(json.dumps(res, indent=2, default=str)[:16000])

        if name == "mine_eval_slice":
            from . import mine_eval_slice as mes

            root = _root()
            try:
                res = mes.run_demo_slice(
                    root,
                    fixture=args.get("fixture") or None,
                    repo=args.get("repo") or "wshobson/agents",
                    run_id=args.get("run_id") or None,
                    min_score=float(args.get("min_score") or mes.DEFAULT_MIN_SCORE),
                    test_exit_code=int(args.get("test_exit_code") or 0),
                )
            except Exception as e:
                return _tool_result(f"mine_eval_slice error: {e}", is_error=True)
            body = mes.format_demo_report(res) + "\n\n" + json.dumps(
                res, indent=2, default=str
            )[:12000]
            return _tool_result(body, is_error=not bool(res.get("ok")))

        if name == "improve_board":
            from . import apply_select as asel

            root = _root()
            try:
                res = asel.improve_board(
                    root,
                    query=str(args.get("query") or ""),
                    min_score=float(args.get("min_score") or 10.0),
                    limit=int(args.get("limit") or 5),
                    grader=str(args.get("grader") or asel.DEFAULT_ROLES["grader"]),
                    implementer=str(
                        args.get("implementer") or asel.DEFAULT_ROLES["implementer"]
                    ),
                    verifier=str(
                        args.get("verifier") or asel.DEFAULT_ROLES["verifier"]
                    ),
                    goal=str(
                        args.get("goal")
                        or "self-improve nexus-core from mined repos + arXiv"
                    ),
                    auto_index=bool(args.get("auto_index", True)),
                )
            except Exception as e:
                return _tool_result(f"improve_board error: {e}", is_error=True)
            return _tool_result(json.dumps(res, indent=2, default=str)[:16000])

        if name in ("ledger_append", "ledger.append"):
            from . import improve_spine as spine

            root = _root()
            try:
                row = spine.mcp_ledger_append(
                    root,
                    run_id=str(args.get("run_id") or "").strip(),
                    stage=str(args.get("stage") or "").strip(),
                    agent=str(args.get("agent") or "").strip(),
                    action=str(args.get("action") or "").strip(),
                    payload=args.get("payload")
                    if isinstance(args.get("payload"), dict)
                    else None,
                    parent_id=str(args.get("parent_id") or ""),
                )
            except Exception as e:
                return _tool_result(f"ledger_append error: {e}", is_error=True)
            return _tool_result(json.dumps(row, indent=2, default=str))

        if name in ("ledger_list", "ledger.list"):
            from . import improve_spine as spine

            root = _root()
            try:
                res = spine.mcp_ledger_list(
                    root,
                    run_id=str(args.get("run_id") or "").strip() or None,
                    limit=int(args.get("limit") or 50),
                    stage=str(args.get("stage") or "").strip() or None,
                )
            except Exception as e:
                return _tool_result(f"ledger_list error: {e}", is_error=True)
            return _tool_result(json.dumps(res, indent=2, default=str)[:16000])

        if name in ("grade_get", "grade.get"):
            from . import improve_spine as spine

            root = _root()
            rid = str(
                args.get("repo_or_paper_id") or args.get("repo") or ""
            ).strip()
            if not rid:
                return _tool_result(
                    "repo_or_paper_id (or repo) required", is_error=True
                )
            try:
                res = spine.mcp_grade_get(
                    root,
                    repo_or_paper_id=rid,
                    run_id=str(args.get("run_id") or "").strip() or None,
                    method=str(args.get("method") or "").strip() or None,
                )
            except Exception as e:
                return _tool_result(f"grade_get error: {e}", is_error=True)
            return _tool_result(json.dumps(res, indent=2, default=str))

        if name == "work_ledger":
            from . import work_ledger as wl
            from .load_mine_eval import load_one

            root = _root()
            action = str(args.get("action") or "status").strip().lower()
            try:
                if action in ("status", "tail"):
                    res = wl.work_ledger_status(
                        root,
                        run_id=str(args.get("run_id") or "").strip() or None,
                        limit=int(args.get("limit") or 20),
                    )
                elif action == "chain":
                    rid = str(args.get("run_id") or "").strip()
                    if not rid:
                        return _tool_result("run_id required for chain", is_error=True)
                    with wl.WorkLedger.open(root) as led:
                        chain = led.causal_chain(rid)
                    res = {
                        "schema": wl.SCHEMA_VERSION,
                        "run_id": rid,
                        "chain": chain,
                        "text": wl.format_causal_chain(chain),
                    }
                elif action == "transitions":
                    res = {
                        "schema": wl.SCHEMA_VERSION,
                        "legal_successors": {
                            (k if k is not None else "∅"): sorted(v)
                            for k, v in wl.LEGAL_SUCCESSORS.items()
                            if k != wl.EVENT_BREAKER
                        },
                    }
                elif action in ("gate", "first_slice", "first-slice"):
                    repo = str(args.get("repo") or "").strip() or None
                    thr = args.get("score_threshold")
                    if action == "gate":
                        grade = load_one(root, repo=repo)
                        res = wl.ensure_apply_gate(
                            root,
                            grade=grade,
                            run_id=str(args.get("run_id") or "").strip() or None,
                            pattern_name=str(
                                args.get("pattern_name")
                                or grade.get("pattern")
                                or wl.DEFAULT_PATTERN
                            ),
                            score_threshold=float(thr) if thr is not None else None,
                            grader=str(args.get("grader") or wl.DEFAULT_ROLES[wl.ROLE_GRADER]),
                            applier=str(
                                args.get("applier") or wl.DEFAULT_ROLES[wl.ROLE_APPLIER]
                            ),
                            accept=bool(args.get("accept", True)),
                        )
                    else:
                        res = wl.run_first_slice(
                            root,
                            repo=repo,
                            run_id=str(args.get("run_id") or "").strip() or None,
                            score_threshold=float(thr)
                            if thr is not None
                            else wl.DEFAULT_SCORE_THRESHOLD,
                            pattern_name=str(
                                args.get("pattern_name") or wl.DEFAULT_PATTERN
                            ),
                            accept=bool(args.get("accept", True)),
                            grader=str(
                                args.get("grader") or wl.DEFAULT_ROLES[wl.ROLE_GRADER]
                            ),
                            applier=str(
                                args.get("applier") or wl.DEFAULT_ROLES[wl.ROLE_APPLIER]
                            ),
                        )
                else:
                    return _tool_result(
                        f"unknown work_ledger action: {action} "
                        "(status|tail|chain|gate|first_slice|transitions)",
                        is_error=True,
                    )
            except Exception as e:
                return _tool_result(f"work_ledger error: {e}", is_error=True)
            return _tool_result(json.dumps(res, indent=2, default=str)[:16000])

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

        if name == "marketplace":
            from . import marketplace as mp

            root = _root()
            action = str(args.get("action") or "list").lower().strip()
            plugin = str(args.get("plugin") or "").strip() or None
            max_priv = args.get("max_privilege") or None
            strict_size = bool(args.get("strict_size"))
            # Default: skillpacks indexed for catalog/export/self_check/portability/garden
            if "include_skillpacks" in args:
                include_sp = bool(args.get("include_skillpacks"))
            elif action in (
                "catalog",
                "export",
                "generate",
                "self_check",
                "self-check",
                "portability",
                "garden",
            ):
                include_sp = True
            else:
                include_sp = False
            try:
                if action == "list":
                    rows = mp.list_plugins(
                        root,
                        max_privilege=max_priv,
                        include_skillpacks=include_sp,
                    )
                    return _tool_result(
                        json.dumps(
                            {
                                "schema": mp.SCHEMA_VERSION,
                                "count": len(rows),
                                "plugins": [r.to_dict() for r in rows],
                            },
                            indent=2,
                            default=str,
                        )
                    )
                if action == "validate":
                    if plugin:
                        pdir = root / mp.DEFAULT_PLUGINS_DIR / plugin
                        rep = mp.validate_plugin(pdir)
                        data = {
                            "schema": mp.SCHEMA_VERSION,
                            "ok": rep.ok,
                            "count": 1,
                            "plugins": [rep.to_dict()],
                            "errors": sum(
                                1 for f in rep.findings if f.severity == "error"
                            ),
                            "warnings": sum(
                                1 for f in rep.findings if f.severity == "warning"
                            ),
                        }
                    else:
                        data = mp.validate_all(root)
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action == "catalog":
                    data = mp.build_catalog(root, include_skillpacks=include_sp)
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action == "collisions":
                    data = mp.collisions(root)
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action in ("self_check", "self-check"):
                    data = mp.self_check(
                        root,
                        include_skillpacks=include_sp,
                        fail_on_oversize=strict_size,
                    )
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action in ("capabilities", "capability"):
                    harnesses = None
                    if args.get("harness"):
                        harnesses = [str(args.get("harness"))]
                    data = mp.capabilities_matrix(harnesses)
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action == "portability":
                    harnesses = None
                    if args.get("harness"):
                        harnesses = [str(args.get("harness"))]
                    data = mp.portability(
                        root,
                        include_skillpacks=include_sp,
                        harnesses=harnesses,
                        fail_on_oversize=strict_size,
                    )
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action == "garden":
                    data = mp.garden(
                        root,
                        include_skillpacks=include_sp,
                        fail_on_oversize=strict_size,
                    )
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action == "export":
                    harnesses = None
                    if args.get("harness"):
                        harnesses = [str(args.get("harness"))]
                    clean = bool(args.get("clean"))
                    data = mp.export_registries(
                        root,
                        harnesses=harnesses,
                        clean=clean,
                        include_skillpacks=include_sp,
                    )
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action == "generate":
                    harnesses = None
                    if args.get("harness"):
                        harnesses = [str(args.get("harness"))]
                    clean = bool(args.get("clean"))
                    data = mp.generate_adapters(
                        root,
                        harnesses=harnesses,
                        clean=clean,
                        include_skillpacks=include_sp,
                        plugin=plugin,
                        max_privilege=max_priv,
                    )
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action in ("validate_generated", "validate-generated"):
                    harnesses = None
                    if args.get("harness"):
                        harnesses = [str(args.get("harness"))]
                    out = args.get("out") or mp.generate_adapters_root(root)
                    data = mp.validate_generated(
                        out,
                        harnesses=harnesses,
                        fail_on_oversize=strict_size if "strict_size" in args else True,
                    )
                    return _tool_result(json.dumps(data, indent=2, default=str))
                if action in ("round_trip", "round-trip"):
                    harnesses = None
                    if args.get("harness"):
                        harnesses = [str(args.get("harness"))]
                    # smoke default: no skillpacks unless explicitly true
                    if "include_skillpacks" in args:
                        rt_sp = bool(args.get("include_skillpacks"))
                    else:
                        rt_sp = False
                    clean_rt = (
                        bool(args.get("clean"))
                        if "clean" in args
                        else True
                    )
                    data = mp.round_trip(
                        root,
                        harnesses=harnesses,
                        include_skillpacks=rt_sp,
                        clean=clean_rt,
                        plugin=plugin,
                        max_privilege=max_priv,
                        fail_on_oversize=(
                            strict_size if "strict_size" in args else True
                        ),
                    )
                    return _tool_result(json.dumps(data, indent=2, default=str))
            except mp.MarketplaceError as e:
                return _tool_result(f"MarketplaceError: {e}", is_error=True)
            except Exception as e:
                return _tool_result(f"marketplace error: {e}", is_error=True)
            return _tool_result(
                f"unknown marketplace action: {action} "
                "(list|validate|catalog|collisions|self_check|"
                "capabilities|portability|garden|export|generate|"
                "validate_generated|round_trip)",
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

        if name == "maf_bench":
            from . import maf_bench as maf

            action = str(args.get("action") or "smoke").lower()
            root = _root()
            pack_raw = str(args.get("pack") or "").strip()
            pack_paths: list[str] = []
            for part in pack_raw.split(",") if pack_raw else []:
                part = part.strip()
                if not part:
                    continue
                pp = Path(part)
                pack_paths.append(str(pp if pp.is_absolute() else (root / pp)))
            include_builtin = not bool(args.get("no_builtin", False))
            discover = bool(args.get("discover_packs", False))
            install_samples = bool(args.get("install_samples", False))
            do_export = bool(args.get("export", True))
            out_dir = str(args.get("out_dir") or maf.DEFAULT_OUT_DIR).lstrip("/\\")
            if ".." in Path(out_dir).parts:
                return _tool_result(
                    "out_dir escapes project root", is_error=True
                )
            try:
                if install_samples and action in (
                    "packs",
                    "pack",
                    "list",
                    "run",
                    "smoke",
                    "brief",
                ):
                    install_result = maf.ensure_sample_maf_packs(root)
                else:
                    install_result = None

                if action == "packs":
                    found = maf.discover_maf_packs(root)
                    bundled = maf.list_bundled_maf_packs(root)
                    payload: dict[str, Any] = {
                        "schema": maf.PACK_SCHEMA,
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
                    rows = maf.list_mechanisms()
                    payload = {
                        "schema": maf.SCHEMA,
                        "paper": maf.PAPER,
                        "count": len(rows),
                        "mechanisms": rows,
                        "domain_mcp_servers": maf.list_domain_mcp_servers(),
                    }
                    if install_result is not None:
                        payload["install"] = install_result
                    return _tool_result(
                        json.dumps(payload, indent=2, default=str)
                    )

                if action == "brief":
                    iters_raw = args.get("iters")
                    iters = int(iters_raw) if iters_raw is not None else 2
                    brief = maf.maf_brief(
                        root, iters=iters, include_pack=True
                    )
                    return _tool_result(
                        json.dumps(brief, indent=2, default=str)
                    )

                mech_raw = str(args.get("mechanism") or "").strip()
                mechanisms = (
                    [m.strip() for m in mech_raw.split(",") if m.strip()]
                    if mech_raw
                    else None
                )
                iters_raw = args.get("iters")
                if action in ("pack",) or pack_paths or discover:
                    iters = int(iters_raw) if iters_raw is not None else 5
                    if install_samples:
                        discover = True
                    report = maf.run_maf_scenarios(
                        root,
                        packs=pack_paths or None,
                        include_builtin=include_builtin,
                        discover=discover,
                        iters=iters,
                        export=do_export,
                        out_dir=out_dir,
                    )
                    return _tool_result(
                        json.dumps(report, indent=2, default=str)
                    )

                if action in ("run", "smoke", "bench", "evaluate"):
                    default_iters = 5 if action == "smoke" else maf.DEFAULT_ITERS
                    iters = int(iters_raw) if iters_raw is not None else default_iters
                    report = maf.run_maf_bench(
                        root,
                        iters=iters,
                        mechanisms=mechanisms,
                        export=do_export if action != "smoke" else do_export,
                        out_dir=out_dir,
                    )
                    if action == "smoke" and not do_export:
                        # already handled by export flag
                        pass
                    return _tool_result(
                        json.dumps(report, indent=2, default=str)
                    )
            except Exception as e:
                return _tool_result(f"maf_bench error: {e}", is_error=True)
            return _tool_result(
                f"unknown maf_bench action: {action} "
                "(list|run|smoke|pack|packs|brief)",
                is_error=True,
            )

        if name == "tool_agent":
            # arXiv 2401.07324 — Planner before Caller (structure-only by default)
            from . import multi_llm_agent as mla

            action = str(args.get("action") or "plan").lower().strip()
            task = str(args.get("task") or args.get("description") or "").strip()
            tools_csv = str(args.get("tools") or "").strip()
            max_steps = int(args.get("max_steps") or 5)
            plan_json = args.get("plan_json")
            plan_text = args.get("plan_text")
            if plan_json is not None:
                plan_json = str(plan_json)
            if plan_text is not None:
                plan_text = str(plan_text)
            auto_ready = True if args.get("auto_ready") is None else bool(args.get("auto_ready"))
            require_ready = (
                True if args.get("require_ready") is None else bool(args.get("require_ready"))
            )
            task_id = str(args.get("task_id") or "").strip() or None
            agent_mode = str(args.get("agent_mode") or "fake").strip() or "fake"
            try:
                report = mla.dispatch_action(
                    action,
                    task=task,
                    tools_csv=tools_csv,
                    max_steps=max_steps,
                    plan_text=plan_text,
                    plan_json=plan_json,
                    auto_ready=auto_ready,
                    require_ready=require_ready,
                    workdir=_root(),
                    task_id=task_id,
                    agent_mode=agent_mode,
                )
                is_err = not bool(report.get("ok")) and action not in ("plan",)
                # plan with zero steps is soft-fail but still returns structure
                if action == "plan":
                    is_err = bool(report.get("error"))
                return _tool_result(
                    json.dumps(report, indent=2, default=str),
                    is_error=is_err,
                )
            except mla.PlanError as e:
                return _tool_result(f"PlanError: {e}", is_error=True)
            except mla.CallGateError as e:
                return _tool_result(f"CallGateError: {e}", is_error=True)
            except Exception as e:
                return _tool_result(f"tool_agent error: {e}", is_error=True)

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

        if name == "compute_budget":
            from .budget_plane import BudgetPlaneError, dispatch

            action = str(args.get("action") or "status").lower()
            try:
                payload = dispatch(
                    action,
                    workdir=_root(),
                    job_id=str(args.get("job_id") or ""),
                    agent=str(args.get("agent") or ""),
                    tokens=int(args.get("tokens") or 0),
                    steps=int(args.get("steps") or 0),
                    total_tokens=int(args.get("total_tokens") or 0),
                    strategy=str(args.get("strategy") or "weighted"),
                    agents=args.get("agents"),
                    hard=bool(args.get("hard", True)),
                    finish=bool(args.get("finish") or False),
                    rebalance=bool(args.get("rebalance") or False),
                    status=str(args.get("status") or ""),
                    title=str(args.get("title") or ""),
                    goal=str(args.get("goal") or ""),
                    kind=str(args.get("kind") or "task"),
                    limit=int(args.get("limit") or 500),
                )
                return _tool_result(json.dumps(payload, indent=2, default=str))
            except BudgetPlaneError as e:
                return _tool_result(f"BudgetPlaneError: {e}", is_error=True)
            except Exception as e:
                return _tool_result(f"compute_budget error: {e}", is_error=True)

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
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": _listed_tools()}}

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
    """Read one MCP message (Content-Length framed or newline JSON).

    Accepts both CRLF (\\r\\n\\r\\n) and LF (\\n\\n) header terminators —
    Grok CLI and several other clients speak LF-only Content-Length framing.
    """
    # Try Content-Length framing first
    header = b""
    while True:
        ch = sys.stdin.buffer.read(1)
        if not ch:
            return None
        header += ch
        # MCP spec is CRLF; many clients (incl. Grok CLI) use bare LF.
        if header.endswith(b"\r\n\r\n") or header.endswith(b"\n\n"):
            break
        # fallback: if no headers and looks like JSON (newline-delimited)
        if header.startswith(b"{") and b"\n" in header:
            line = header.decode("utf-8", errors="replace").strip()
            return json.loads(line)

    headers = header.decode("utf-8", errors="replace")
    length = 0
    for line in headers.replace("\r\n", "\n").split("\n"):
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
            raw = self.rfile.read(n) or b"{}"
            try:
                body = json.loads(raw)
            except Exception:
                return self._send(400, {"error": "invalid json"})
            # Full MCP JSON-RPC (what Grok CLI / streamable-HTTP clients expect)
            if self.path in ("/mcp", "/mcp/"):
                # notifications have no id and return empty 202-style OK
                if body.get("method") and body.get("id") is None:
                    handle_rpc(body)
                    return self._send(200, {"ok": True})
                resp = handle_rpc(body)
                if resp is None:
                    return self._send(200, {"ok": True})
                return self._send(200, resp)
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
