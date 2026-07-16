"""Worktree-isolated apply + promote-to-main (P0.5 / P0.1 — cas + forge + wshobson).

Pipeline:

  claim-verified grade
    → create isolated worktree (never dirty main mid-apply)
    → apply one Markdown skill SoT pattern (wshobson/agents shape)
    → validate skillpack structure inside worktree
    → optional **promote**: copy allowlisted files to main after re-verify
    → ledger plan_apply + apply + promote decisions
    → cleanup optional

Isolation modes:
- ``sandbox`` (default, always available): directory under
  ``.nexus_workspaces/apply_worktrees/<job_id>/`` with path jail
- ``git``: ``git worktree add`` when *source* is a git repo (optional)

Patterns (shape only, not vendored trees):
- codingagentsystem/cas, automagik-dev/forge — one worktree per apply job
- wshobson/agents — Markdown skill source-of-truth + structural validate
- lumen — content-hash ledger / idempotent apply keys
- tiger_cowork / improve_apply — path safety jail
- zenith / cycgraph — verify-before-promote (fail-closed)

CLI::

  nexus improve apply [--fixture PATH] [--pattern markdown-skill-sot-validator]
  nexus improve apply --promote   # after verify, copy pack onto main
  nexus improve promote --job-id <id>  # promote a kept worktree
  python -m nexus.worktree_apply --fixture tests/fixtures/mine_eval_sample.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .claim_verify import ClaimVerifyError, verify_claim
from .decision_ledger import DecisionLedger
from .improve_apply import PathSafetyError, safe_path
from .load_mine_eval import load_one
from .persist import atomic_write_json, atomic_write_text
from .stages import APPLY_STAGES, PROMOTE_STAGES, StageOrderError, StageRunner

SCHEMA = "nexus.worktree_apply/v1"
DEFAULT_PATTERN = "markdown-skill-sot-validator"
WORKTREE_ROOT = ".nexus_workspaces/apply_worktrees"
# Marker written on main after a successful promote (operator audit).
PROMOTE_META_NAME = "PROMOTE_META.json"

# ---------------------------------------------------------------------------
# Ported pattern catalog (content only — not whole upstream trees)
# ---------------------------------------------------------------------------

_SOT_MANIFEST = {
    "id": "markdown-sot-demo",
    "version": "0.1.0",
    "name": "Markdown skill SoT validator (demo)",
    "tags": ["self-improve", "sot", "wshobson-pattern", "read"],
    "privilege": "read",
    "harnesses": ["grok", "local", "claude"],
    "entrypoints": {"skill": "SKILL.md"},
    "source_pattern": "wshobson/agents:markdown-skill-sot",
}

_SOT_SKILL_MD = """# Skill: Markdown skill SoT validator

Ported *pattern* from wshobson/agents (single Markdown source of truth +
structural validate). This pack is materialised inside an isolated apply
worktree so main stays clean until review promotes the change.

## When to use

- Self-improve apply jobs that must prove skillpack structure offline
- Smoke tests for worktree isolation (cas / forge pattern)
- Least-privilege skill catalog demos

## Commands

```bash
nexus skillpacks validate --packs-dir skillpacks
nexus improve apply --pattern markdown-skill-sot-validator
```

## Rules

1. SKILL.md is the source of truth; generators are derived.
2. Never vendor whole upstream trees — port patterns only.
3. Apply only inside isolated worktrees; never dirty main mid-run.
4. Keep tests green; claim-verify before apply.

## Success

- `manifest.json` has id/version/name
- SKILL.md has When to use / Commands / Rules / Success
- `nexus skillpacks validate` reports ok
- Main worktree file set unchanged after apply job
"""


# cas / mission-control shaped evidence + board operator skill (pattern only)
_EVIDENCE_BOARD_MANIFEST = {
    "id": "evidence-board-ops",
    "version": "0.1.0",
    "name": "Evidence Board Ops",
    "description": (
        "Operator skill for FTS evidence search + improve board signals "
        "(continue|replan|stop) before hard apply"
    ),
    "privilege": "ops",
    "tags": ["evidence", "board", "fts", "decision"],
}

_EVIDENCE_BOARD_SKILL_MD = """# Evidence Board Ops

## When to use

- Rank mined repos with FTS evidence before apply
- Emit a terminal decision package with role separation
- Sync board signals onto the principled-stop gap board

## Commands

```bash
nexus improve select --query "durable multi-agent"
nexus improve board --sync-gaps
nexus improve decide --repo wshobson/agents
nexus improve prefer list
```

## Rules

- Grader ≠ implementer ≠ verifier (anti-collusion)
- Prefer path-anchored claims over free-text grades
- `replan` registers gaps; hard `stop` may abort the watch loop
- No vendored upstream trees — patterns only

## Success

- Board signal is one of continue|replan|stop
- Decision package schema `nexus.decision_package/v1`
- Gap board reflects signal after `--sync-gaps`
"""


# mission-control spend / ops plane skill (pattern only)
_SPEND_OPS_MANIFEST = {
    "id": "mission-control-spend-ops",
    "version": "0.1.0",
    "name": "Mission Control Spend Ops",
    "description": (
        "Operator skill for SQLite ops jobs + token spend rollups "
        "(mission-control task-costs shape; pattern only)"
    ),
    "privilege": "ops",
    "tags": ["ops", "spend", "budget", "mission-control"],
}

# soul-style immutable work ledger + dual-control gate (pattern only)
_WORK_LEDGER_MANIFEST = {
    "id": "soul-work-ledger-ops",
    "version": "0.1.0",
    "name": "Soul Work Ledger Ops",
    "description": (
        "Operator skill for append-only work ledger dual-control gates "
        "(soul/cas shape; arXiv 2601.00360 anti-collusion; pattern only)"
    ),
    "privilege": "ops",
    "tags": ["ledger", "dual-control", "handoff", "soul"],
}

_SPEND_OPS_SKILL_MD = """# Mission Control Spend Ops

## When to use

- Inspect alive / improve / mine job spend before self-approve
- Ingest usage ledger into the ops plane for operator list/show
- Gate hard apply when task token budgets are exhausted

## Commands

```bash
nexus ops list
nexus ops spend
nexus ops status
nexus task cost --task-id <id>
nexus improve board --sync-gaps
```

## Rules

- Treat spend as operator estimate, not billing truth
- Prefer fail-closed hard stop when `max_tokens` / RunBudget exhausted
- Dual-write usage with `_ops_skip` anti-loop when recording
- No vendored upstream trees — patterns only

## Success

- Ops store schema `nexus.ops/v1`
- `nexus ops spend` returns non-empty rollup after ledger ingest
- Budget deny reasons appear on decision package / board signal
"""


_WORK_LEDGER_SKILL_MD = """# Soul Work Ledger Ops

## When to use

- Gate hard apply on dual-control accept (grader ≠ applier)
- Inspect mine → grade → decision → accept causal chains
- Refuse illegal interleaving (e.g. mine → accept without grade)

## Commands

```bash
nexus improve work-loop --repo wshobson/agents
nexus improve work-ledger --run-id <id>
nexus improve apply --pattern soul-work-ledger-ops
```

## Rules

- Append-only events; no UPDATE/DELETE of work_events
- apply_accepted requires grade_recorded from a different agent/role
- Prefer decision packet score ≥ threshold before propose/accept
- No vendored upstream trees — patterns only

## Success

- Work ledger schema `nexus.work_ledger/v1`
- Illegal transitions raise TransitionError
- MCP tool `work_ledger` returns status/chain/gate
"""


# labsai/EDDI-shaped config-driven routing skill (pattern only)
_EDDI_ROUTING_MANIFEST = {
    "id": "eddi-routing-ops",
    "version": "0.1.0",
    "name": "EDDI Routing Ops",
    "description": (
        "Config-driven multi-agent routing + memory handoff skill "
        "(labsai/EDDI middleware shape; pattern only)"
    ),
    "privilege": "ops",
    "tags": ["routing", "memory", "config", "eddi", "middleware"],
}

_EDDI_ROUTING_SKILL_MD = """# EDDI Routing Ops

## When to use

- Route improve/mine workers by config (not ad-hoc if/else)
- Hand off durable memory keys between scout → grade → apply
- Validate agent graph configs before hard apply

## Commands

```bash
nexus improve status --run <id>
nexus improve board
nexus improve apply --pattern eddi-routing-ops
nexus task context --task-id <id>
```

## Rules

- Prefer declarative route tables over free-form agent chat
- Memory handoffs must cite spine/ledger keys (no silent drop)
- Fail closed when route target or privilege is missing
- No vendored upstream trees — patterns only

## Success

- Skillpack validates offline
- Route table lists scout/grade/apply agents
- Handoff keys appear in improve spine / context pack
"""


# openrouter-deep-research shape: circuit breakers + research grade loop
_OPENROUTER_RESEARCH_MANIFEST = {
    "id": "openrouter-research-ops",
    "version": "0.1.0",
    "name": "OpenRouter Research Ops",
    "description": (
        "Circuit-breaker protected research/grade loop skill "
        "(wheattoast11/openrouter-deep-research-mcp shape; pattern only)"
    ),
    "privilege": "ops",
    "tags": [
        "research",
        "circuit-breaker",
        "grade",
        "openrouter",
        "resilience",
    ],
}

_OPENROUTER_RESEARCH_SKILL_MD = """# OpenRouter Research Ops

## When to use

- Protect grade/research LLM calls with circuit breakers (fail-open after cooldown)
- Run mine → grade loops without hanging on a single provider outage
- Record breaker state under `.nexus_state/` for operator inspect

## Commands

```bash
nexus improve board
nexus improve select --query research
nexus improve apply --pattern openrouter-research-ops
nexus eval smoke --llm-judge auto
```

## Rules

- Use `nexus.circuits.CircuitBreaker` (CLOSED / OPEN / HALF_OPEN)
- Trip OPEN after consecutive grade/research failures; probe in HALF_OPEN
- Never vendor full OpenRouter MCP trees — pattern only
- Prefer offline fixtures in unit tests; live Grok judge is opt-in via env

## Success

- Skillpack validates offline
- Breaker snapshot lists grade + research circuits
- Board still ranks when research circuit is OPEN (degraded mode)
"""


# MattMagg/MisterSmith shape: supervised multi-agent runtime + hard caps
_MISTERSMITH_RUNTIME_MANIFEST = {
    "id": "mistersmith-runtime-ops",
    "version": "0.1.0",
    "name": "MisterSmith Runtime Ops",
    "description": (
        "Supervised multi-agent runtime ops: hard token/step caps, actor "
        "supervision, CLI inspect (MattMagg/MisterSmith shape; pattern only)"
    ),
    "privilege": "ops",
    "tags": [
        "runtime",
        "supervision",
        "budget",
        "hard-cap",
        "mistersmith",
        "actors",
    ],
}

_MISTERSMITH_RUNTIME_SKILL_MD = """# MisterSmith Runtime Ops

## When to use

- Enforce hard max_steps / max_tokens caps on improve and engine runs
- Supervise multi-agent workers with fail-closed budget gates
- Inspect task cost / graph / evidence after a supervised cycle

## Commands

```bash
nexus task cost --task-id <id>
nexus task graph --task-id <id> --mermaid
nexus task evidence --task-id <id>
nexus improve board
nexus improve apply --pattern mistersmith-runtime-ops
```

## Rules

- Prefer `RunBudget` + engine `task_max_tokens` / `task_max_steps` hard stops
- Actor/role separation: grader ≠ implementer ≠ verifier (anti-collusion)
- Journal budget events on exhaust; never silent continue past hard cap
- No vendored MisterSmith crates — patterns only

## Success

- Skillpack validates offline
- Cost board shows budget remaining when meta.max_tokens set
- Hard-stop fails closed (status failed + budget event)
"""


# SolaceLabs/solace-agent-mesh shape: event-driven mesh + eval matrix
_SOLACE_MESH_MANIFEST = {
    "id": "solace-mesh-events-ops",
    "version": "0.1.0",
    "name": "Solace Mesh Events Ops",
    "description": (
        "Event-driven multi-agent mesh ops: journal events, handoff, "
        "eval matrix smoke (SolaceLabs/solace-agent-mesh shape; pattern only)"
    ),
    "privilege": "ops",
    "tags": [
        "events",
        "mesh",
        "handoff",
        "journal",
        "eval",
        "solace",
    ],
}

_SOLACE_MESH_SKILL_MD = """# Solace Mesh Events Ops

## When to use

- Emit / inspect append-only task journals (`*.events.jsonl`)
- Handoff between scout → grade → apply agents with event audit
- Run offline MCP eval smoke as a mesh quality gate

## Commands

```bash
nexus task events --task-id <id>
nexus task replay --task-id <id>
nexus improve work-ledger --tail 20
nexus eval smoke --tag sample
nexus improve apply --pattern solace-mesh-events-ops
```

## Rules

- Prefer journal `handoff` / `step_complete` events over ad-hoc chat logs
- Eval matrix runs offline (fixtures); live LLM judge is env-gated
- Mesh topology is logical (agent roles), not a Solace broker dependency
- No vendored solace-agent-mesh trees — patterns only

## Success

- Skillpack validates offline
- Task events CLI returns tail of journal
- Sample eval packs PASS under `make eval-samples`
"""


# Intelligent-Internet/zenith shape: gap review + principled stop + verify-before-done
_ZENITH_STOP_MANIFEST = {
    "id": "zenith-principled-stop-ops",
    "version": "0.1.0",
    "name": "Zenith Principled Stop Ops",
    "description": (
        "Gap board + principled stop + independent verify-before-done "
        "(Intelligent-Internet/zenith shape; pattern only)"
    ),
    "privilege": "ops",
    "tags": [
        "stop",
        "gap",
        "verify",
        "replan",
        "zenith",
        "anti-premature",
    ],
}

_ZENITH_STOP_SKILL_MD = """# Zenith Principled Stop Ops

## When to use

- Prevent premature completion of long-horizon improve loops
- Sync board signal (continue|replan|stop) onto PrincipledStop gap board
- Require independent verify before promote / done

## Commands

```bash
nexus improve board --sync-gaps
nexus alive gaps --seed
nexus improve decide --repo <top>
nexus improve apply --pattern zenith-principled-stop-ops
```

## Rules

- Do not claim done without verified claim + grade (context_store gate)
- replan/stop board signals open gaps; continue closes them
- IndependentVerify before promote (fail-closed when promote_require set)
- No vendored zenith trees — patterns only

## Success

- Skillpack validates offline
- PrincipledStop records cycle progress / thrash / max_cycles
- Board SIGNAL=STOP aborts when abort_on_board_stop is on
"""


# escapeboy/agent-fleet-o shape: fleet DAG + HITL audit + dual-control accept
_AGENT_FLEET_MANIFEST = {
    "id": "agent-fleet-ops",
    "version": "0.1.0",
    "name": "Agent Fleet Ops",
    "description": (
        "Fleet DAG + HITL dual-control audit for multi-agent apply "
        "(escapeboy/agent-fleet-o shape; pattern only)"
    ),
    "privilege": "ops",
    "tags": [
        "fleet",
        "dag",
        "hitl",
        "dual-control",
        "audit",
        "agent-fleet",
    ],
}

_AGENT_FLEET_SKILL_MD = """# Agent Fleet Ops

## When to use

- Run multi-agent improve as a fleet with ordered stages (AOAD-MAT)
- Enforce dual-control accept (grader ≠ applier) before hard apply
- Export operator audit (work ledger + decision package + task DAG)

## Commands

```bash
nexus improve work-loop --repo wshobson/agents
nexus task dag --task-id <id> --mermaid
nexus improve decide --repo <top>
nexus improve apply --pattern agent-fleet-ops
```

## Rules

- Prefer legal stage successors (mine→grade→decision→accept)
- Dual-control: same agent/role cannot both grade and accept
- Decision package must ALLOW before plan_apply
- No vendored agent-fleet-o / Laravel trees — patterns only

## Success

- Skillpack validates offline
- Work ledger shows apply_accepted with dual-control
- Illegal transitions raise TransitionError
"""


PATTERN_CATALOG: dict[str, dict[str, Any]] = {
    DEFAULT_PATTERN: {
        "id": DEFAULT_PATTERN,
        "repo": "wshobson/agents",
        "description": (
            "Markdown skill source-of-truth pack + structural validator "
            "(wshobson/agents shape; pattern only)"
        ),
        "files": {
            "skillpacks/markdown-sot-demo/manifest.json": json.dumps(
                _SOT_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/markdown-sot-demo/SKILL.md": _SOT_SKILL_MD,
            "skillpacks/markdown-sot-demo/APPLY_META.json": None,  # filled at apply
        },
        "verify": "skillpack_validate",
        "pack_id": "markdown-sot-demo",
    },
    "cas-evidence-board-ops": {
        "id": "cas-evidence-board-ops",
        "repo": "codingagentsystem/cas",
        "description": (
            "FTS evidence + improve board operator skill "
            "(cas/mission-control/routa shape; pattern only)"
        ),
        "files": {
            "skillpacks/evidence-board-ops/manifest.json": json.dumps(
                _EVIDENCE_BOARD_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/evidence-board-ops/SKILL.md": _EVIDENCE_BOARD_SKILL_MD,
            "skillpacks/evidence-board-ops/APPLY_META.json": None,
        },
        "verify": "skillpack_validate",
        "pack_id": "evidence-board-ops",
    },
    "mission-control-spend-ops": {
        "id": "mission-control-spend-ops",
        "repo": "builderz-labs/mission-control",
        "description": (
            "SQLite ops jobs + spend rollup skill "
            "(mission-control task-costs shape; pattern only)"
        ),
        "files": {
            "skillpacks/mission-control-spend-ops/manifest.json": json.dumps(
                _SPEND_OPS_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/mission-control-spend-ops/SKILL.md": _SPEND_OPS_SKILL_MD,
            "skillpacks/mission-control-spend-ops/APPLY_META.json": None,
        },
        "verify": "skillpack_validate",
        "pack_id": "mission-control-spend-ops",
    },
    "soul-work-ledger-ops": {
        "id": "soul-work-ledger-ops",
        "repo": "choihyunsus/soul",
        "description": (
            "Append-only work ledger + dual-control gate skill "
            "(soul/cas shape; pattern only)"
        ),
        "files": {
            "skillpacks/soul-work-ledger-ops/manifest.json": json.dumps(
                _WORK_LEDGER_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/soul-work-ledger-ops/SKILL.md": _WORK_LEDGER_SKILL_MD,
            "skillpacks/soul-work-ledger-ops/APPLY_META.json": None,
        },
        "verify": "skillpack_validate",
        "pack_id": "soul-work-ledger-ops",
    },
    "eddi-routing-ops": {
        "id": "eddi-routing-ops",
        "repo": "labsai/EDDI",
        "description": (
            "Config-driven multi-agent routing + memory handoff skill "
            "(labsai/EDDI middleware shape; pattern only)"
        ),
        "files": {
            "skillpacks/eddi-routing-ops/manifest.json": json.dumps(
                _EDDI_ROUTING_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/eddi-routing-ops/SKILL.md": _EDDI_ROUTING_SKILL_MD,
            "skillpacks/eddi-routing-ops/APPLY_META.json": None,
        },
        "verify": "skillpack_validate",
        "pack_id": "eddi-routing-ops",
    },
    "openrouter-research-ops": {
        "id": "openrouter-research-ops",
        "repo": "wheattoast11/openrouter-deep-research-mcp",
        "description": (
            "Circuit-breaker protected research/grade loop skill "
            "(openrouter-deep-research-mcp shape; pattern only)"
        ),
        "files": {
            "skillpacks/openrouter-research-ops/manifest.json": json.dumps(
                _OPENROUTER_RESEARCH_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/openrouter-research-ops/SKILL.md": _OPENROUTER_RESEARCH_SKILL_MD,
            "skillpacks/openrouter-research-ops/APPLY_META.json": None,
        },
        "verify": "skillpack_validate",
        "pack_id": "openrouter-research-ops",
    },
    "mistersmith-runtime-ops": {
        "id": "mistersmith-runtime-ops",
        "repo": "MattMagg/MisterSmith",
        "description": (
            "Supervised multi-agent runtime + hard caps skill "
            "(MisterSmith shape; pattern only)"
        ),
        "files": {
            "skillpacks/mistersmith-runtime-ops/manifest.json": json.dumps(
                _MISTERSMITH_RUNTIME_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/mistersmith-runtime-ops/SKILL.md": _MISTERSMITH_RUNTIME_SKILL_MD,
            "skillpacks/mistersmith-runtime-ops/APPLY_META.json": None,
        },
        "verify": "skillpack_validate",
        "pack_id": "mistersmith-runtime-ops",
    },
    "solace-mesh-events-ops": {
        "id": "solace-mesh-events-ops",
        "repo": "SolaceLabs/solace-agent-mesh",
        "description": (
            "Event-driven mesh journal + eval matrix skill "
            "(solace-agent-mesh shape; pattern only)"
        ),
        "files": {
            "skillpacks/solace-mesh-events-ops/manifest.json": json.dumps(
                _SOLACE_MESH_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/solace-mesh-events-ops/SKILL.md": _SOLACE_MESH_SKILL_MD,
            "skillpacks/solace-mesh-events-ops/APPLY_META.json": None,
        },
        "verify": "skillpack_validate",
        "pack_id": "solace-mesh-events-ops",
    },
    "zenith-principled-stop-ops": {
        "id": "zenith-principled-stop-ops",
        "repo": "Intelligent-Internet/zenith",
        "description": (
            "Gap board + principled stop + verify-before-done skill "
            "(zenith shape; pattern only)"
        ),
        "files": {
            "skillpacks/zenith-principled-stop-ops/manifest.json": json.dumps(
                _ZENITH_STOP_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/zenith-principled-stop-ops/SKILL.md": _ZENITH_STOP_SKILL_MD,
            "skillpacks/zenith-principled-stop-ops/APPLY_META.json": None,
        },
        "verify": "skillpack_validate",
        "pack_id": "zenith-principled-stop-ops",
    },
    "agent-fleet-ops": {
        "id": "agent-fleet-ops",
        "repo": "escapeboy/agent-fleet-o",
        "description": (
            "Fleet DAG + HITL dual-control audit skill "
            "(agent-fleet-o shape; pattern only)"
        ),
        "files": {
            "skillpacks/agent-fleet-ops/manifest.json": json.dumps(
                _AGENT_FLEET_MANIFEST, indent=2
            )
            + "\n",
            "skillpacks/agent-fleet-ops/SKILL.md": _AGENT_FLEET_SKILL_MD,
            "skillpacks/agent-fleet-ops/APPLY_META.json": None,
        },
        "verify": "skillpack_validate",
        "pack_id": "agent-fleet-ops",
    },
}


class WorktreeApplyError(RuntimeError):
    """Isolation or apply failed."""


def list_patterns() -> list[dict[str, Any]]:
    """Return catalog entries (id, repo, description)."""
    out: list[dict[str, Any]] = []
    for pid, meta in PATTERN_CATALOG.items():
        out.append(
            {
                "id": pid,
                "repo": meta.get("repo"),
                "description": meta.get("description"),
                "pack_id": meta.get("pack_id"),
                "verify": meta.get("verify"),
            }
        )
    return out


def get_pattern(pattern_id: str) -> dict[str, Any]:
    key = str(pattern_id or "").strip()
    if key not in PATTERN_CATALOG:
        known = sorted(PATTERN_CATALOG)
        raise WorktreeApplyError(
            f"unknown pattern {pattern_id!r}; known={known}"
        )
    return PATTERN_CATALOG[key]


def worktrees_dir(workdir: Path | str) -> Path:
    d = Path(workdir).resolve() / WORKTREE_ROOT
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_git_repo(path: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return r.returncode == 0 and "true" in (r.stdout or "").lower()
    except (OSError, subprocess.SubprocessError):
        return False


def _git_head(path: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def create_worktree(
    workdir: Path | str,
    *,
    job_id: Optional[str] = None,
    mode: str = "auto",
    branch: Optional[str] = None,
) -> dict[str, Any]:
    """Create an isolated apply worktree; never mutates tracked files on main.

    *mode*:
      - ``sandbox``: always use ``.nexus_workspaces/apply_worktrees/<id>``
      - ``git``: require ``git worktree add`` (fails if not a git repo)
      - ``auto``: try git worktree, fall back to sandbox
    """
    source = Path(workdir).resolve()
    jid = job_id or f"apply-{uuid.uuid4().hex[:10]}"
    mode_n = (mode or "auto").strip().lower()
    if mode_n not in ("auto", "sandbox", "git"):
        raise WorktreeApplyError(f"invalid mode {mode!r}")

    target = worktrees_dir(source) / jid
    if target.exists():
        raise WorktreeApplyError(f"worktree path already exists: {target}")

    used = "sandbox"
    git_sha = ""
    branch_name = branch or f"nexus/apply/{jid}"

    want_git = mode_n in ("auto", "git")
    if want_git and _is_git_repo(source):
        # Prefer detached worktree from HEAD so main stays clean.
        # Destination must be outside the main checkout's nested path issues;
        # we keep it under .nexus_workspaces which is typically gitignored.
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "worktree",
                    "add",
                    "--detach",
                    str(target),
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if r.returncode == 0 and target.is_dir():
                used = "git"
                git_sha = _git_head(target)
            elif mode_n == "git":
                err = (r.stderr or r.stdout or "").strip()
                raise WorktreeApplyError(f"git worktree add failed: {err}")
        except WorktreeApplyError:
            raise
        except (OSError, subprocess.SubprocessError) as e:
            if mode_n == "git":
                raise WorktreeApplyError(f"git worktree add failed: {e}") from e

    if used == "sandbox":
        target.mkdir(parents=True, exist_ok=False)
        # Seed a marker so operators can see isolation root; no main files copied
        # (avoids huge trees). Pattern files are written only under this root.
        marker = {
            "schema": SCHEMA,
            "mode": "sandbox",
            "job_id": jid,
            "source": str(source),
            "created_at": time.time(),
            "note": "sandbox isolation — pattern files only (no full tree clone)",
        }
        atomic_write_json(target / ".nexus_apply_worktree.json", marker)

    meta = {
        "schema": SCHEMA,
        "job_id": jid,
        "mode": used,
        "path": str(target),
        "source": str(source),
        "branch": branch_name if used == "git" else None,
        "git_sha": git_sha or None,
        "created_at": time.time(),
    }
    atomic_write_json(target / ".nexus_apply_meta.json", meta)
    return meta


def cleanup_worktree(
    workdir: Path | str,
    job_id: str,
    *,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Remove an apply worktree (git worktree remove or rmtree)."""
    source = Path(workdir).resolve()
    jid = str(job_id)
    target = worktrees_dir(source) / jid
    info = meta or {}
    mode = str(info.get("mode") or "")
    if not mode and target.is_dir():
        # Infer from marker
        mpath = target / ".nexus_apply_meta.json"
        if mpath.is_file():
            try:
                info = json.loads(mpath.read_text(encoding="utf-8"))
                mode = str(info.get("mode") or "")
            except (json.JSONDecodeError, OSError):
                pass

    removed = False
    method = "none"
    if mode == "git" and _is_git_repo(source):
        try:
            r = subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "worktree",
                    "remove",
                    "--force",
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if r.returncode == 0:
                removed = True
                method = "git_worktree_remove"
        except (OSError, subprocess.SubprocessError):
            pass

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        removed = not target.exists()
        method = method if method != "none" else "rmtree"

    return {
        "job_id": jid,
        "path": str(target),
        "removed": removed,
        "method": method,
    }


def snapshot_main_fingerprint(workdir: Path | str, rel_paths: list[str]) -> dict[str, str]:
    """Hash selected relative paths under main workdir (for dirty-main checks)."""
    root = Path(workdir).resolve()
    out: dict[str, str] = {}
    for rel in rel_paths:
        p = root / rel
        if not p.is_file():
            out[rel] = "missing"
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        out[rel] = h
    return out


def apply_pattern_files(
    worktree_path: Path | str,
    pattern_id: str = DEFAULT_PATTERN,
    *,
    grade: Optional[dict[str, Any]] = None,
    job_id: str = "",
) -> dict[str, Any]:
    """Write pattern files into *worktree_path* with path jail (never outside)."""
    wt = Path(worktree_path).resolve()
    if not wt.is_dir():
        raise WorktreeApplyError(f"worktree path missing: {wt}")
    pattern = get_pattern(pattern_id)
    written: list[str] = []
    files = dict(pattern.get("files") or {})

    # Fill APPLY_META dynamically under the pattern's pack path
    pack_id = str(pattern.get("pack_id") or "pack")
    apply_meta = {
        "schema": SCHEMA,
        "pattern": pattern_id,
        "repo": pattern.get("repo"),
        "job_id": job_id,
        "pack_id": pack_id,
        "applied_at": time.time(),
        "grade": {
            "repo": (grade or {}).get("repo"),
            "score": (grade or {}).get("score"),
            "idea": (grade or {}).get("idea"),
            "skill": (grade or {}).get("skill"),
            "path": (grade or {}).get("path"),
            "method": (grade or {}).get("method"),
        },
    }
    meta_rel = f"skillpacks/{pack_id}/APPLY_META.json"
    # Prefer catalog key if present (None placeholder); else inject by pack_id
    meta_keys = [k for k, v in files.items() if k.endswith("APPLY_META.json")]
    if meta_keys:
        for k in meta_keys:
            files[k] = json.dumps(apply_meta, indent=2, default=str) + "\n"
    else:
        files[meta_rel] = json.dumps(apply_meta, indent=2, default=str) + "\n"

    for rel, content in files.items():
        if content is None:
            continue
        try:
            dest = safe_path(wt, rel)
        except PathSafetyError as e:
            raise WorktreeApplyError(str(e)) from e
        if isinstance(content, (dict, list)):
            atomic_write_json(dest, content)
        else:
            atomic_write_text(dest, str(content))
        written.append(rel)

    return {
        "pattern": pattern_id,
        "pack_id": pattern.get("pack_id"),
        "files_written": written,
        "worktree": str(wt),
    }


def verify_in_worktree(
    worktree_path: Path | str,
    pattern_id: str = DEFAULT_PATTERN,
) -> dict[str, Any]:
    """Run pattern verification inside the worktree (offline, no network)."""
    from . import skillpacks as sp

    wt = Path(worktree_path).resolve()
    pattern = get_pattern(pattern_id)
    verify = str(pattern.get("verify") or "skillpack_validate")
    pack_id = str(pattern.get("pack_id") or "")

    if verify == "skillpack_validate":
        pack_dir = wt / "skillpacks" / pack_id
        if not pack_dir.is_dir():
            return {
                "ok": False,
                "verify": verify,
                "error": f"pack dir missing: {pack_dir}",
            }
        rep = sp.validate_pack(pack_dir)
        # Require structural ok; also require APPLY_META present
        meta_ok = (pack_dir / "APPLY_META.json").is_file()
        return {
            "ok": bool(rep.ok and meta_ok),
            "verify": verify,
            "pack_id": pack_id,
            "validate": rep.to_dict(),
            "apply_meta_present": meta_ok,
        }

    return {"ok": False, "verify": verify, "error": f"unknown verify mode {verify}"}


def pattern_rel_paths(pattern_id: str = DEFAULT_PATTERN) -> list[str]:
    """Allowlisted relative paths a pattern may write (excluding dynamic None)."""
    pattern = get_pattern(pattern_id)
    out: list[str] = []
    for rel, content in (pattern.get("files") or {}).items():
        if content is None:
            # Dynamic files filled at apply time — still allowlisted by key.
            out.append(str(rel))
            continue
        out.append(str(rel))
    return out


def promote_to_main(
    workdir: Path | str,
    worktree_path: Path | str,
    pattern_id: str = DEFAULT_PATTERN,
    *,
    force: bool = False,
    job_id: str = "",
    grade: Optional[dict[str, Any]] = None,
    require_verify: bool = True,
) -> dict[str, Any]:
    """Copy verified pattern files from *worktree_path* onto main *workdir*.

    Fail-closed (zenith / cycgraph promote discipline):
    - worktree must pass ``verify_in_worktree`` when *require_verify*
    - only allowlisted pattern relative paths are copied
    - refuses overwrite of differing content unless *force*
    - identical content is treated as idempotent success
    - re-verifies the pack under main after copy

    Never vendors whole trees — only the small pattern file set.
    """
    root = Path(workdir).resolve()
    wt = Path(worktree_path).resolve()
    pid = pattern_id or DEFAULT_PATTERN
    if not wt.is_dir():
        raise WorktreeApplyError(f"worktree path missing: {wt}")
    # Refuse promoting from outside the designated worktree root (path safety).
    wt_root = worktrees_dir(root)
    try:
        wt.relative_to(wt_root)
    except ValueError as e:
        raise WorktreeApplyError(
            f"promote refused: worktree not under {wt_root} (got {wt})"
        ) from e

    verify_wt: dict[str, Any] = {"ok": True, "skipped": True}
    if require_verify:
        verify_wt = verify_in_worktree(wt, pid)
        if not verify_wt.get("ok"):
            raise WorktreeApplyError(
                f"promote refused: worktree verify failed: "
                f"{verify_wt.get('error') or verify_wt}"
            )

    rels = pattern_rel_paths(pid)
    if not rels:
        raise WorktreeApplyError(f"promote refused: pattern {pid!r} has no files")

    copied: list[str] = []
    skipped_same: list[str] = []
    overwritten: list[str] = []
    for rel in rels:
        try:
            src = safe_path(wt, rel)
            dest = safe_path(root, rel)
        except PathSafetyError as e:
            raise WorktreeApplyError(str(e)) from e
        if not src.is_file():
            raise WorktreeApplyError(
                f"promote refused: source missing in worktree: {rel}"
            )
        data = src.read_bytes()
        if dest.is_file():
            existing = dest.read_bytes()
            if existing == data:
                skipped_same.append(rel)
                continue
            if not force:
                raise WorktreeApplyError(
                    f"promote refused: main already has different {rel} "
                    f"(pass force=True to overwrite)"
                )
            overwritten.append(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish: write temp then rename within dest parent
        tmp = dest.with_name(dest.name + f".promotetmp-{uuid.uuid4().hex[:8]}")
        try:
            tmp.write_bytes(data)
            tmp.replace(dest)
        except OSError:
            if tmp.exists():
                tmp.unlink(missing_ok=True)  # type: ignore[arg-type]
            raise
        copied.append(rel)

    # Operator audit marker next to pack (not in pattern catalog on purpose —
    # written only on main after promote).
    pattern = get_pattern(pid)
    pack_id = str(pattern.get("pack_id") or "pack")
    try:
        meta_dest = safe_path(root, f"skillpacks/{pack_id}/{PROMOTE_META_NAME}")
    except PathSafetyError as e:
        raise WorktreeApplyError(str(e)) from e
    promote_meta = {
        "schema": SCHEMA,
        "action": "promote_to_main",
        "pattern": pid,
        "pack_id": pack_id,
        "job_id": job_id,
        "worktree": str(wt),
        "promoted_at": time.time(),
        "copied": copied,
        "skipped_same": skipped_same,
        "overwritten": overwritten,
        "force": bool(force),
        "grade": {
            "repo": (grade or {}).get("repo"),
            "score": (grade or {}).get("score"),
            "idea": (grade or {}).get("idea"),
            "skill": (grade or {}).get("skill"),
            "path": (grade or {}).get("path"),
            "method": (grade or {}).get("method"),
        },
        "verify_worktree": {
            "ok": verify_wt.get("ok"),
            "verify": verify_wt.get("verify"),
        },
    }
    atomic_write_json(meta_dest, promote_meta)

    # Independent re-verify on main (implementer=worktree apply, verifier=main).
    verify_main = verify_in_worktree(root, pid)
    if not verify_main.get("ok"):
        raise WorktreeApplyError(
            f"promote refused: main re-verify failed after copy: "
            f"{verify_main.get('error') or verify_main}"
        )

    return {
        "ok": True,
        "schema": SCHEMA,
        "action": "promote_to_main",
        "pattern": pid,
        "pack_id": pack_id,
        "job_id": job_id,
        "worktree": str(wt),
        "main": str(root),
        "copied": copied,
        "skipped_same": skipped_same,
        "overwritten": overwritten,
        "files": copied + skipped_same,
        "promote_meta": str(meta_dest.relative_to(root)),
        "verify_worktree": verify_wt,
        "verify_main": verify_main,
        "force": bool(force),
    }


def resolve_worktree(
    workdir: Path | str,
    job_id: str,
) -> dict[str, Any]:
    """Load meta for an existing apply worktree by *job_id*."""
    source = Path(workdir).resolve()
    jid = str(job_id or "").strip()
    if not jid:
        raise WorktreeApplyError("job_id required")
    target = worktrees_dir(source) / jid
    if not target.is_dir():
        raise WorktreeApplyError(f"worktree not found: {target}")
    meta: dict[str, Any] = {
        "job_id": jid,
        "path": str(target),
        "source": str(source),
        "mode": "sandbox",
    }
    mpath = target / ".nexus_apply_meta.json"
    if mpath.is_file():
        try:
            loaded = json.loads(mpath.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta.update(loaded)
                meta["path"] = str(target)
        except (json.JSONDecodeError, OSError):
            pass
    return meta


def run_promote(
    workdir: Path | str,
    *,
    job_id: str,
    pattern_id: str = DEFAULT_PATTERN,
    force: bool = False,
    grade: Optional[dict[str, Any]] = None,
    ledger: Optional[DecisionLedger] = None,
    cleanup: bool = False,
) -> dict[str, Any]:
    """Promote a kept worktree pack onto main (standalone promote stage)."""
    workdir = Path(workdir).resolve()
    jid = str(job_id or "").strip()
    pid = pattern_id or DEFAULT_PATTERN
    own_ledger = ledger is None
    store = ledger or DecisionLedger.open(workdir)
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "ok": False,
        "run_id": jid,
        "action": "promote",
        "pattern": pid,
        "promote": None,
        "cleanup": None,
        "error": None,
        "ledger_tail": [],
    }
    try:
        meta = resolve_worktree(workdir, jid)
        result = promote_to_main(
            workdir,
            meta["path"],
            pid,
            force=force,
            job_id=jid,
            grade=grade,
            require_verify=True,
        )
        report["promote"] = result
        report["worktree"] = meta
        store.append(
            run_id=jid,
            agent="promote",
            claim=(
                f"promoted {pid} to main copied={len(result.get('copied') or [])} "
                f"same={len(result.get('skipped_same') or [])} "
                f"verify_main=ok"
            ),
            evidence_refs=list(result.get("files") or [])
            + [str(result.get("promote_meta") or "")],
            grade={
                "repo": (grade or {}).get("repo"),
                "score": (grade or {}).get("score"),
                "path": (grade or {}).get("path"),
                "pattern": pid,
            },
            action="promote_to_main",
        )
        report["ok"] = bool(result.get("ok"))
        report["ledger_tail"] = store.tail(limit=8, run_id=jid)
        if cleanup:
            report["cleanup"] = cleanup_worktree(workdir, jid, meta=meta)
        return report
    except (WorktreeApplyError, PathSafetyError, FileNotFoundError, ValueError) as e:
        report["error"] = f"{type(e).__name__}: {e}"
        try:
            report["ledger_tail"] = store.tail(limit=8, run_id=jid)
        except Exception:
            report["ledger_tail"] = []
        return report
    finally:
        if own_ledger:
            store.close()


def run_apply(
    workdir: Path | str,
    *,
    fixture: Optional[Path | str] = None,
    repo: Optional[str] = None,
    pattern_id: str = DEFAULT_PATTERN,
    run_id: Optional[str] = None,
    mode: str = "auto",
    cleanup: bool = True,
    require_path_exists: bool = False,
    ledger: Optional[DecisionLedger] = None,
    skip_smoke_prefix: bool = False,
    grade: Optional[dict[str, Any]] = None,
    promote: bool = False,
    promote_force: bool = False,
    require_decision: bool = True,
    require_work_ledger: Optional[bool] = None,
    require_spine: Optional[bool] = None,
    work_ledger_threshold: Optional[float] = None,
    grader: str = "grok:grade",
    implementer: str = "worker:apply",
    verifier: str = "judge:verify",
    require_distinct_roles: bool = True,
    max_steps: Optional[int] = None,
    max_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """Full ordered apply: mine→grade→claim_verify→decision→plan_apply→apply [(→promote)].

    When *skip_smoke_prefix* is True and *grade* is provided, starts at
    plan_apply (assumes prior stages already completed externally).

    When *require_decision* is True (default), builds a
    ``nexus.decision_package/v1`` via :func:`apply_select.decision_for_grade`
    after claim_verify and fail-closes if the gate denies (role collusion,
    missing evidence, budget). Soft board signal ``replan`` also blocks apply
    when require_decision is set.

    When *require_work_ledger* is True (default: same as require_decision),
    records mine→grade→decision→propose→accept on the append-only work ledger
    under dual-control (grader ≠ applier) before plan_apply.

    When *require_spine* is True (default: same as require_decision),
    ensures the grade is on ``improve_spine`` (and dual-writes grade_ledger)
    before plan_apply.

    When *promote* is True, after worktree verify the allowlisted pack is
    copied onto main and re-verified (PROMOTE_STAGES). Isolation still holds
    during apply; main only changes at the explicit promote step.
    """
    workdir = Path(workdir).resolve()
    rid = run_id or f"apply-{uuid.uuid4().hex[:10]}"
    pid = pattern_id or DEFAULT_PATTERN
    do_promote = bool(promote)
    use_work_ledger = (
        bool(require_decision)
        if require_work_ledger is None
        else bool(require_work_ledger)
    )
    use_spine = (
        bool(require_decision) if require_spine is None else bool(require_spine)
    )
    runner = (
        StageRunner.promote_slice() if do_promote else StageRunner.apply_slice()
    )
    stages = list(PROMOTE_STAGES if do_promote else APPLY_STAGES)
    timeline: list[dict[str, Any]] = []
    own_ledger = ledger is None
    store = ledger or DecisionLedger.open(workdir)
    wt_meta: Optional[dict[str, Any]] = None
    main_before: dict[str, str] = {}
    # Paths that must remain untouched on main *during apply* (isolation proof).
    # When promote=True these may change only after the promote stage.
    watch_paths = [
        "skillpacks/markdown-sot-demo/manifest.json",
        "skillpacks/markdown-sot-demo/SKILL.md",
        "src/nexus/worktree_apply.py",
    ]

    def _log(event: str, detail: str = "") -> None:
        timeline.append(
            {
                "ts": time.time(),
                "event": event,
                "detail": detail,
                "next": runner.next(),
            }
        )

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "ok": False,
        "run_id": rid,
        "workdir": str(workdir),
        "pattern": pid,
        "stages": stages,
        "promote_requested": do_promote,
        "require_decision": bool(require_decision),
        "require_work_ledger": use_work_ledger,
        "require_spine": use_spine,
        "completed": [],
        "grade": None,
        "claim": None,
        "decision": None,
        "signal": None,
        "work_ledger": None,
        "spine": None,
        "worktree": None,
        "apply": None,
        "verify": None,
        "promote": None,
        "main_untouched": None,
        "cleanup": None,
        "ledger_tail": [],
        "timeline": timeline,
        "error": None,
    }

    try:
        # --- mine / grade / claim_verify (or accept preloaded grade) ---
        if skip_smoke_prefix and grade is not None:
            for s in ("mine", "grade", "claim_verify"):
                if s not in runner.completed:
                    runner.completed.append(s)
            g = grade
            claim = verify_claim(
                g,
                workdir=workdir,
                require_path_exists=require_path_exists,
            )
            report["grade"] = {
                "repo": g.get("repo"),
                "score": g.get("score"),
                "idea": g.get("idea"),
                "skill": g.get("skill"),
                "method": g.get("method"),
                "path": g.get("path"),
                "pattern": g.get("pattern"),
            }
            report["claim"] = claim
            _log("preload", f"repo={g.get('repo')}")
        else:
            runner.assert_can_run("mine")
            g = load_one(workdir, repo=repo, fixture=fixture)
            store.append(
                run_id=rid,
                agent="mine",
                claim=f"loaded grade for {g.get('repo')}",
                evidence_refs=[str(g.get("path") or "")],
                grade={
                    "repo": g.get("repo"),
                    "score": g.get("score"),
                    "path": g.get("path"),
                },
                action="mine_load",
            )
            runner.mark_complete("mine")
            _log("mine", f"repo={g.get('repo')} score={g.get('score')}")

            runner.assert_can_run("grade")
            store.append(
                run_id=rid,
                agent="grade",
                claim=(
                    f"grade artifact score={g.get('score')} "
                    f"idea={g.get('idea')} skill={g.get('skill')}"
                ),
                evidence_refs=[str(g.get("path") or "")],
                grade={
                    "repo": g.get("repo"),
                    "score": g.get("score"),
                    "idea": g.get("idea"),
                    "skill": g.get("skill"),
                    "method": g.get("method"),
                    "path": g.get("path"),
                },
                action="grade_accept",
            )
            runner.mark_complete("grade")
            _log("grade", f"method={g.get('method')}")
            report["grade"] = {
                "repo": g.get("repo"),
                "score": g.get("score"),
                "idea": g.get("idea"),
                "skill": g.get("skill"),
                "method": g.get("method"),
                "path": g.get("path"),
                "pattern": g.get("pattern"),
            }

            runner.assert_can_run("claim_verify")
            claim = verify_claim(
                g,
                workdir=workdir,
                require_path_exists=require_path_exists,
            )
            store.append(
                run_id=rid,
                agent="claim_verify",
                claim=f"verified claim for {g.get('repo')}",
                evidence_refs=[str(g.get("path") or "")],
                grade={
                    "repo": g.get("repo"),
                    "score": claim["score"],
                    "idea": claim["idea"],
                    "skill": claim["skill"],
                    "path": claim["path"],
                },
                action="claim_pass",
            )
            runner.mark_complete("claim_verify")
            _log("claim_verify", "ok")
            report["claim"] = claim

        # --- decision package (2511.15755) before plan_apply ---
        from . import apply_select as asel

        decision = asel.decision_for_grade(
            g,
            grader=grader,
            implementer=implementer,
            verifier=verifier,
            require_distinct_roles=require_distinct_roles,
            max_steps=max_steps,
            max_tokens=max_tokens,
        )
        sig = asel.board_signal(
            decision=decision,
            roles_ok=bool(
                asel.check_roles(
                    grader=grader,
                    implementer=implementer,
                    verifier=verifier,
                    require_distinct=require_distinct_roles,
                ).get("ok")
            ),
            candidates=[asel.candidate_from_grade(g)],
        )
        decision = {**decision, "signal": sig}
        report["decision"] = decision
        report["signal"] = sig.get("signal")
        store.append(
            run_id=rid,
            agent="decide",
            claim=(
                f"decision ok={decision.get('ok')} reason={decision.get('reason')} "
                f"signal={sig.get('signal')} conf={decision.get('confidence')}"
            ),
            evidence_refs=list(decision.get("evidence_refs") or [])[
                :8
            ]
            + [str(g.get("path") or "")],
            grade={
                "repo": g.get("repo"),
                "score": g.get("score"),
                "path": g.get("path"),
                "pattern": pid,
            },
            action="decision_package",
        )
        _log(
            "decision",
            f"ok={decision.get('ok')} signal={sig.get('signal')} "
            f"reason={decision.get('reason')}",
        )
        if require_decision:
            if not decision.get("ok"):
                raise WorktreeApplyError(
                    f"decision denied: {decision.get('reason')}"
                )
            if sig.get("signal") == asel.SIGNAL_STOP:
                raise WorktreeApplyError(
                    f"board signal stop: {sig.get('reason')}"
                )
            if sig.get("signal") == asel.SIGNAL_REPLAN:
                raise WorktreeApplyError(
                    f"board signal replan: {sig.get('reason')}"
                )

        # --- improve_spine grade ensure + dual-write grade_ledger ---
        if use_spine:
            from . import improve_spine as spine

            spine_gate = spine.require_spine_grade(
                workdir,
                repo=str(g.get("repo") or ""),
                run_id=rid,
                auto_ensure=g,
            )
            report["spine"] = {
                "ok": spine_gate.get("ok"),
                "accepted": spine_gate.get("accepted"),
                "run_id": spine_gate.get("run_id")
                or (spine_gate.get("ensure") or {}).get("run_id")
                or rid,
                "repo": spine_gate.get("repo"),
                "score": spine_gate.get("score"),
                "error": spine_gate.get("error"),
                "created": (spine_gate.get("ensure") or {}).get("created"),
                "dual_write": (spine_gate.get("ensure") or {}).get("dual_write"),
            }
            store.append(
                run_id=rid,
                agent="improve_spine",
                claim=(
                    f"spine accepted={spine_gate.get('accepted')} "
                    f"ok={spine_gate.get('ok')} err={spine_gate.get('error')}"
                ),
                evidence_refs=[str(g.get("path") or ""), "improve_spine"],
                grade={
                    "repo": g.get("repo"),
                    "score": g.get("score"),
                    "path": g.get("path"),
                    "pattern": pid,
                },
                action="spine_gate",
            )
            _log(
                "spine",
                f"accepted={spine_gate.get('accepted')} "
                f"err={spine_gate.get('error')}",
            )
            if not spine_gate.get("accepted"):
                raise WorktreeApplyError(
                    f"spine grade denied: {spine_gate.get('error') or 'not accepted'}"
                )

        # --- work ledger dual-control accept (soul / 2601.00360) ---
        if use_work_ledger:
            from . import work_ledger as wl

            # When decision package already allowed the candidate, cap the
            # ledger threshold at grade score so dual-control is the hard gate
            # (score was already ranked by apply_select / board).
            thr = work_ledger_threshold
            if thr is None:
                try:
                    score_f = float(g.get("score") or 0)
                except (TypeError, ValueError):
                    score_f = 0.0
                thr = (
                    min(wl.DEFAULT_SCORE_THRESHOLD, score_f)
                    if score_f > 0
                    else wl.DEFAULT_SCORE_THRESHOLD
                )
            wl_gate = wl.ensure_apply_gate(
                workdir,
                grade=g,
                run_id=rid,
                pattern_name=str(g.get("pattern") or pid),
                target_module="src/nexus/worktree_apply.py",
                score_threshold=float(thr),
                grader=grader,
                applier=implementer,
                accept=True,
                tests_to_run=[
                    "tests/test_worktree_apply.py",
                    "tests/test_work_ledger.py",
                ],
            )
            report["work_ledger"] = {
                "ok": wl_gate.get("ok"),
                "accepted": wl_gate.get("accepted"),
                "rejected": wl_gate.get("rejected"),
                "run_id": wl_gate.get("run_id"),
                "repo": wl_gate.get("repo"),
                "error": wl_gate.get("error"),
                "cached": wl_gate.get("cached"),
                "event_types": [
                    e.get("event_type") for e in (wl_gate.get("events") or [])
                ],
            }
            store.append(
                run_id=rid,
                agent="work_ledger",
                claim=(
                    f"work_ledger accepted={wl_gate.get('accepted')} "
                    f"ok={wl_gate.get('ok')} err={wl_gate.get('error')}"
                ),
                evidence_refs=[str(g.get("path") or ""), "work_ledger"],
                grade={
                    "repo": g.get("repo"),
                    "score": g.get("score"),
                    "path": g.get("path"),
                    "pattern": pid,
                },
                action="work_ledger_gate",
            )
            _log(
                "work_ledger",
                f"accepted={wl_gate.get('accepted')} err={wl_gate.get('error')}",
            )
            if not wl_gate.get("accepted"):
                raise WorktreeApplyError(
                    "work_ledger denied: "
                    f"{wl_gate.get('error') or wl_gate.get('rejected') or 'not accepted'}"
                )

        # Snapshot main before apply (isolation invariant)
        main_before = snapshot_main_fingerprint(workdir, watch_paths)

        # --- plan_apply: create worktree + choose pattern ---
        runner.assert_can_run("plan_apply")
        get_pattern(pid)  # validate catalog entry
        wt_meta = create_worktree(workdir, job_id=rid, mode=mode)
        report["worktree"] = wt_meta
        store.append(
            run_id=rid,
            agent="plan_apply",
            claim=f"planned isolated apply pattern={pid} mode={wt_meta.get('mode')}",
            evidence_refs=[
                str(g.get("path") or ""),
                str(wt_meta.get("path") or ""),
            ],
            grade={
                "repo": g.get("repo"),
                "score": g.get("score"),
                "path": g.get("path"),
                "pattern": pid,
            },
            action="plan_worktree",
        )
        runner.mark_complete("plan_apply")
        _log("plan_apply", f"mode={wt_meta.get('mode')} path={wt_meta.get('path')}")

        # --- apply: materialise pattern + verify inside worktree ---
        runner.assert_can_run("apply")
        applied = apply_pattern_files(
            wt_meta["path"],
            pid,
            grade=g,
            job_id=rid,
        )
        report["apply"] = applied
        verify = verify_in_worktree(wt_meta["path"], pid)
        report["verify"] = verify
        if not verify.get("ok"):
            raise WorktreeApplyError(
                f"verify failed in worktree: {verify.get('error') or verify}"
            )

        # Isolation: main watch paths unchanged
        main_after = snapshot_main_fingerprint(workdir, watch_paths)
        untouched = main_before == main_after
        report["main_untouched"] = {
            "ok": untouched,
            "before": main_before,
            "after": main_after,
        }
        if not untouched:
            raise WorktreeApplyError(
                "isolation violated: main workdir files changed during apply"
            )

        # Pattern files must exist under worktree; main fingerprint already proves
        # isolation when those paths were missing or unchanged on main.
        pack_id = str(get_pattern(pid).get("pack_id") or "markdown-sot-demo")
        wt_pack = Path(wt_meta["path"]) / "skillpacks" / pack_id / "SKILL.md"
        if not wt_pack.is_file():
            # Fallback: any SKILL.md written by this pattern under skillpacks/
            skill_hits = list(
                Path(wt_meta["path"]).glob("skillpacks/*/SKILL.md")
            )
            if not skill_hits:
                raise WorktreeApplyError(
                    f"pattern SKILL.md missing from worktree (pack_id={pack_id})"
                )
            wt_pack = skill_hits[0]

        store.append(
            run_id=rid,
            agent="apply",
            claim=(
                f"applied {pid} in worktree files={len(applied.get('files_written') or [])} "
                f"verify=ok main_untouched={untouched}"
            ),
            evidence_refs=list(applied.get("files_written") or [])
            + [str(wt_meta.get("path") or "")],
            grade={
                "repo": g.get("repo"),
                "score": g.get("score"),
                "path": g.get("path"),
                "pattern": pid,
            },
            action="apply_worktree",
        )
        runner.mark_complete("apply")
        _log("apply", f"files={applied.get('files_written')}")

        # --- promote: copy allowlisted files onto main (optional) ---
        if do_promote:
            runner.assert_can_run("promote")
            prom = promote_to_main(
                workdir,
                wt_meta["path"],
                pid,
                force=promote_force,
                job_id=rid,
                grade=g,
                require_verify=True,
            )
            report["promote"] = prom
            if not prom.get("ok"):
                raise WorktreeApplyError(
                    f"promote failed: {prom.get('error') or prom}"
                )
            store.append(
                run_id=rid,
                agent="promote",
                claim=(
                    f"promoted {pid} to main copied={len(prom.get('copied') or [])} "
                    f"same={len(prom.get('skipped_same') or [])} "
                    f"verify_main=ok"
                ),
                evidence_refs=list(prom.get("files") or [])
                + [str(prom.get("promote_meta") or "")],
                grade={
                    "repo": g.get("repo"),
                    "score": g.get("score"),
                    "path": g.get("path"),
                    "pattern": pid,
                },
                action="promote_to_main",
            )
            runner.mark_complete("promote")
            _log(
                "promote",
                f"copied={prom.get('copied')} meta={prom.get('promote_meta')}",
            )

        report["completed"] = list(runner.completed)
        report["ok"] = (
            runner.is_done()
            and bool(verify.get("ok"))
            and untouched
            and (bool((report.get("promote") or {}).get("ok")) if do_promote else True)
        )
        report["stage_status"] = runner.status()
        report["ledger_tail"] = store.tail(limit=12, run_id=rid)
        return report

    except (
        StageOrderError,
        ClaimVerifyError,
        WorktreeApplyError,
        FileNotFoundError,
        ValueError,
        PathSafetyError,
    ) as e:
        report["error"] = f"{type(e).__name__}: {e}"
        report["completed"] = list(runner.completed)
        report["stage_status"] = runner.status()
        try:
            report["ledger_tail"] = store.tail(limit=12, run_id=rid)
        except Exception:
            report["ledger_tail"] = []
        _log("error", report["error"])
        return report
    finally:
        if cleanup and wt_meta and wt_meta.get("path"):
            try:
                report["cleanup"] = cleanup_worktree(
                    workdir, wt_meta.get("job_id") or rid, meta=wt_meta
                )
            except Exception as ce:  # noqa: BLE001 — best-effort cleanup
                report["cleanup"] = {"removed": False, "error": str(ce)}
        if own_ledger:
            store.close()


def format_report(report: dict[str, Any]) -> str:
    """Human-readable apply board."""
    g = report.get("grade") or {}
    wt = report.get("worktree") or {}
    dec = report.get("decision") or {}
    lines = [
        "=== NEXUS improve apply (worktree-isolated) ===",
        f"run_id:    {report.get('run_id')}",
        f"ok:        {report.get('ok')}",
        f"stages:    {' → '.join(report.get('stages') or APPLY_STAGES)}",
        f"completed: {', '.join(report.get('completed') or []) or '(none)'}",
        f"pattern:   {report.get('pattern')}",
        f"repo:      {g.get('repo')}  score={g.get('score')} "
        f"(idea={g.get('idea')} skill={g.get('skill')})",
        f"decision:  ok={dec.get('ok')} reason={dec.get('reason')} "
        f"signal={report.get('signal') or (dec.get('signal') or {}).get('signal')}",
        f"worktree:  mode={wt.get('mode')} path={wt.get('path')}",
    ]
    app = report.get("apply") or {}
    if app:
        lines.append(f"files:     {', '.join(app.get('files_written') or [])}")
    ver = report.get("verify") or {}
    if ver:
        lines.append(f"verify:    ok={ver.get('ok')} mode={ver.get('verify')}")
    mu = report.get("main_untouched") or {}
    if mu:
        lines.append(f"main clean:{mu.get('ok')}")
    prom = report.get("promote") or {}
    if prom:
        lines.append(
            f"promote:   ok={prom.get('ok')} "
            f"copied={len(prom.get('copied') or [])} "
            f"same={len(prom.get('skipped_same') or [])} "
            f"meta={prom.get('promote_meta')}"
        )
    if report.get("cleanup"):
        c = report["cleanup"]
        lines.append(f"cleanup:   removed={c.get('removed')} via={c.get('method')}")
    if report.get("error"):
        lines.append(f"error:     {report['error']}")
    tail = report.get("ledger_tail") or []
    lines.append(f"ledger:    {len(tail)} recent decision(s)")
    for row in reversed(tail):
        lines.append(
            f"  [{row.get('agent')}] {row.get('action')}: {row.get('claim')}"
        )
    lines.append(f"pass:      {'YES' if report.get('ok') else 'NO'}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="nexus-worktree-apply",
        description="Worktree-isolated apply of one Markdown skill SoT pattern",
    )
    ap.add_argument("--path", default=".", help="project workdir")
    ap.add_argument("--fixture", default=None, help="grade JSON fixture")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--run-id", default=None)
    ap.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=f"pattern id (default: {DEFAULT_PATTERN})",
    )
    ap.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "sandbox", "git"],
        help="isolation mode (default: auto)",
    )
    ap.add_argument(
        "--keep",
        action="store_true",
        help="do not cleanup worktree after apply",
    )
    ap.add_argument(
        "--promote",
        action="store_true",
        help="after verify, promote allowlisted pack files onto main",
    )
    ap.add_argument(
        "--promote-force",
        action="store_true",
        dest="promote_force",
        help="overwrite differing main files during promote",
    )
    ap.add_argument(
        "--job-id",
        default=None,
        dest="job_id",
        help="with --promote-only: promote an existing kept worktree",
    )
    ap.add_argument(
        "--promote-only",
        action="store_true",
        dest="promote_only",
        help="promote existing worktree by --job-id (no re-apply)",
    )
    ap.add_argument("--require-path-exists", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--list-patterns",
        action="store_true",
        help="list available patterns and exit",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.list_patterns:
        rows = list_patterns()
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                print(f"{r['id']}: {r.get('repo')} — {r.get('description')}")
        return 0

    workdir = Path(args.path).resolve()

    if args.promote_only:
        if not args.job_id:
            print("error: --promote-only requires --job-id", file=sys.stderr)
            return 2
        report = run_promote(
            workdir,
            job_id=args.job_id,
            pattern_id=args.pattern,
            force=bool(args.promote_force),
            cleanup=not args.keep,
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(format_report({**report, "stages": ["promote"]}))
        return 0 if report.get("ok") else 1

    fixture = args.fixture
    if fixture is None:
        candidate = workdir / "tests" / "fixtures" / "mine_eval_sample.json"
        if candidate.is_file():
            fixture = str(candidate)

    report = run_apply(
        workdir,
        fixture=fixture,
        repo=args.repo,
        pattern_id=args.pattern,
        run_id=args.run_id,
        mode=args.mode,
        cleanup=not args.keep,
        require_path_exists=bool(args.require_path_exists),
        promote=bool(args.promote),
        promote_force=bool(args.promote_force),
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_report(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
