"""Forge-shaped kanban control plane with multi-attempt worktree isolation.

Pattern from **automagik-dev/forge** (shape only — not a vendored monorepo):

  Wish → Forge → Review → Done   (persistent kanban, not chat history)
  Multiple **attempts** per task (different executor + agent)
  Each attempt isolated in a sandbox (or optional git worktree)
  Human/operator **selects** a winning attempt before ship

Forge product maps columns::

  todo → Wish,  inprogress → Forge,  inreview → Review,  done → Done

NEXUS keeps the product names as first-class lane ids so operator boards
read like the upstream control plane without pulling Rust/Axum/TS trees.

Schema: ``nexus.forge_board/v1``

Offline-first. Complements :mod:`nexus.worktree_apply` (single apply job)
and :mod:`nexus.workspace_review_board` (routa stacked gate) with the
**multi-attempt × isolated worktree** product shape.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

SCHEMA = "nexus.forge_board/v1"
SOURCE_PATTERN = "automagik-dev/forge"
SOURCE_URL = "https://github.com/automagik-dev/forge"
IDEA_ID = "automagik-dev/forge"

# Product kanban columns (forge display names as ids)
LANE_WISH = "wish"
LANE_FORGE = "forge"
LANE_REVIEW = "review"
LANE_DONE = "done"
LANE_CANCELLED = "cancelled"

LANES: tuple[str, ...] = (
    LANE_WISH,
    LANE_FORGE,
    LANE_REVIEW,
    LANE_DONE,
    LANE_CANCELLED,
)
ALL_LANES = frozenset(LANES)

# Map forge TaskStatus enum → product lanes (single source of truth for aliases)
FORGE_STATUS_MAP: dict[str, str] = {
    "todo": LANE_WISH,
    "inprogress": LANE_FORGE,
    "inreview": LANE_REVIEW,
    "done": LANE_DONE,
    "cancelled": LANE_CANCELLED,
    "canceled": LANE_CANCELLED,  # US spelling
    # product-lane aliases
    "wish": LANE_WISH,
    "forge": LANE_FORGE,
    "review": LANE_REVIEW,
    "archived": LANE_CANCELLED,
}

BOARD_STATE_DIR = ".nexus_state/forge_boards"

# Happy-path + escape transitions (fail-closed elsewhere)
_FORWARD: dict[str, frozenset[str]] = {
    LANE_WISH: frozenset({LANE_FORGE, LANE_CANCELLED}),
    LANE_FORGE: frozenset({LANE_REVIEW, LANE_WISH, LANE_CANCELLED}),
    LANE_REVIEW: frozenset({LANE_DONE, LANE_FORGE, LANE_CANCELLED}),
    LANE_DONE: frozenset(),  # terminal
    LANE_CANCELLED: frozenset({LANE_WISH}),  # reopen
}

# Attempt lifecycle
ATTEMPT_PENDING = "pending"
ATTEMPT_RUNNING = "running"
ATTEMPT_SUCCEEDED = "succeeded"
ATTEMPT_FAILED = "failed"
ATTEMPT_STATUSES = frozenset(
    {ATTEMPT_PENDING, ATTEMPT_RUNNING, ATTEMPT_SUCCEEDED, ATTEMPT_FAILED}
)

# Default executors (forge provider layer — names only, no network)
DEFAULT_EXECUTORS: tuple[str, ...] = (
    "grok",
    "local",
    "claude_code",
    "codex",
    "gemini",
    "cursor_agent",
)

# Default agent specializations (forge agent layer)
DEFAULT_AGENTS: tuple[str, ...] = (
    "implementer",
    "test-writer",
    "security-expert",
    "refactor-specialist",
    "reviewer",
)

ATTEMPT_ROOT = ".nexus_workspaces/forge_attempts"

SIGNAL_CONTINUE = "continue"
SIGNAL_REVIEW = "review"
SIGNAL_SHIP = "ship"
SIGNAL_REPLAN = "replan"
SIGNAL_CANCEL = "cancel"


class ForgeBoardError(ValueError):
    """Board / task / attempt invalid for forge control-plane handoff."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _strip_lane_key(raw: str) -> str:
    """Normalize separators so ``in_progress`` / ``in-progress`` match."""
    return (
        str(raw or "")
        .strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
    )


# Pre-normalized alias table derived from FORGE_STATUS_MAP (no drift)
_LANE_ALIASES: dict[str, str] = {
    _strip_lane_key(k): v for k, v in FORGE_STATUS_MAP.items()
}
# product lane ids always resolve to themselves
for _lane in LANES:
    _LANE_ALIASES[_strip_lane_key(_lane)] = _lane


def _safe_component(s: str, *, kind: str = "id") -> str:
    """Sanitize a single filesystem path component (fail-closed path jail).

    Rejects empty, ``.`` / ``..``, absolute-looking, and traversal-shaped ids.
    Non-alphanumeric chars (except ``._-``) become ``_``.
    """
    raw = str(s or "").strip()
    if not raw:
        raise ForgeBoardError(f"empty {kind} component")
    # Absolute / UNC / drive-letter shapes never belong in a relative component
    if raw.startswith(("/", "\\")) or (len(raw) >= 2 and raw[1] == ":"):
        raise ForgeBoardError(f"unsafe {kind}: {raw!r}")
    # Path separators and parent-dir tokens are never valid components
    if "/" in raw or "\\" in raw or raw in {".", ".."} or ".." in raw:
        raise ForgeBoardError(f"unsafe {kind}: {raw!r}")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
    cleaned = cleaned.strip(".")
    if not cleaned or cleaned in {".", ".."} or ".." in cleaned:
        raise ForgeBoardError(f"unsafe {kind}: {raw!r}")
    return cleaned


def normalize_lane(
    raw: str | None,
    *,
    default: str = LANE_WISH,
    strict: bool = False,
) -> str:
    """Map forge/status aliases onto product lane ids.

    *strict*: raise :class:`ForgeBoardError` on unrecognized input (command
    paths). Soft default remains for hydration / display.
    """
    if raw is None or str(raw).strip() == "":
        if strict:
            raise ForgeBoardError(f"unknown lane: {raw!r}")
        return default if default in ALL_LANES else LANE_WISH
    key = _strip_lane_key(str(raw))
    lane = _LANE_ALIASES.get(key)
    if lane is not None:
        return lane
    if strict:
        raise ForgeBoardError(f"unknown lane: {raw!r}")
    return default if default in ALL_LANES else LANE_WISH


def can_transition(from_lane: str, to_lane: str) -> bool:
    """Return True if *from_lane* → *to_lane* is allowed (identity always ok).

    Unknown lanes fail closed (return False) so typos never look legal.
    """
    try:
        src = normalize_lane(from_lane, strict=True)
        dst = normalize_lane(to_lane, strict=True)
    except ForgeBoardError:
        return False
    if src == dst:
        return True  # identity no-op (including terminal lanes)
    return dst in _FORWARD.get(src, frozenset())


@dataclass
class ForgeAttempt:
    """One isolated execution try on a task (provider + agent + worktree)."""

    id: str
    task_id: str
    executor: str = "local"
    agent: str = "implementer"
    status: str = ATTEMPT_PENDING
    worktree_path: str = ""
    isolation_mode: str = "sandbox"  # sandbox | git | none
    branch: str = ""
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    selected: bool = False
    error: str = ""
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "executor": self.executor,
            "agent": self.agent,
            "status": self.status,
            "worktree_path": self.worktree_path,
            "isolation_mode": self.isolation_mode,
            "branch": self.branch,
            "summary": self.summary,
            "changed_files": list(self.changed_files),
            "selected": bool(self.selected),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ForgeAttempt":
        st = str(d.get("status") or ATTEMPT_PENDING).strip().lower()
        if st not in ATTEMPT_STATUSES:
            st = ATTEMPT_PENDING
        files = d.get("changed_files") or []
        if not isinstance(files, (list, tuple)):
            files = []
        return cls(
            id=str(d.get("id") or _new_id("att")),
            task_id=str(d.get("task_id") or ""),
            executor=str(d.get("executor") or "local").strip() or "local",
            agent=str(d.get("agent") or "implementer").strip() or "implementer",
            status=st,
            worktree_path=str(d.get("worktree_path") or ""),
            isolation_mode=str(d.get("isolation_mode") or "sandbox"),
            branch=str(d.get("branch") or ""),
            summary=str(d.get("summary") or ""),
            changed_files=[str(f) for f in files if str(f).strip()],
            selected=bool(d.get("selected")),
            error=str(d.get("error") or ""),
            created_at=float(d.get("created_at") or _now()),
            updated_at=float(d.get("updated_at") or _now()),
            meta=dict(d.get("meta") or {})
            if isinstance(d.get("meta"), dict)
            else {},
        )


@dataclass
class ForgeTask:
    """Kanban card: Wish → Forge → Review → Done with attempt history."""

    id: str
    title: str
    description: str = ""
    lane: str = LANE_WISH
    acceptance: list[str] = field(default_factory=list)
    attempts: list[ForgeAttempt] = field(default_factory=list)
    selected_attempt_id: str = ""
    history: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "lane": self.lane,
            "status": self.lane,  # forge-compat alias
            "acceptance": list(self.acceptance),
            "attempts": [a.to_dict() for a in self.attempts],
            "attempt_count": len(self.attempts),
            "selected_attempt_id": self.selected_attempt_id,
            "has_in_progress_attempt": any(
                a.status == ATTEMPT_RUNNING for a in self.attempts
            ),
            "has_succeeded_attempt": any(
                a.status == ATTEMPT_SUCCEEDED for a in self.attempts
            ),
            "last_attempt_failed": bool(
                self.attempts and self.attempts[-1].status == ATTEMPT_FAILED
            ),
            "history": list(self.history),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ForgeTask":
        lane = normalize_lane(d.get("lane") or d.get("status") or LANE_WISH)
        if lane not in ALL_LANES:
            lane = LANE_WISH
        acc = d.get("acceptance") or []
        if not isinstance(acc, (list, tuple)):
            acc = []
        attempts_raw = d.get("attempts") or []
        attempts: list[ForgeAttempt] = []
        if isinstance(attempts_raw, list):
            for raw in attempts_raw:
                if isinstance(raw, dict):
                    attempts.append(ForgeAttempt.from_dict(raw))
        hist = d.get("history") or []
        if not isinstance(hist, (list, tuple)):
            hist = []
        return cls(
            id=str(d.get("id") or _new_id("task")),
            title=str(d.get("title") or ""),
            description=str(d.get("description") or ""),
            lane=lane,
            acceptance=[str(a) for a in acc if str(a).strip()],
            attempts=attempts,
            selected_attempt_id=str(d.get("selected_attempt_id") or ""),
            history=[str(h) for h in hist],
            created_at=float(d.get("created_at") or _now()),
            updated_at=float(d.get("updated_at") or _now()),
            meta=dict(d.get("meta") or {})
            if isinstance(d.get("meta"), dict)
            else {},
        )


@dataclass
class ForgeBoard:
    """Project-scoped Wish/Forge/Review control plane."""

    project_id: str
    title: str = ""
    tasks: list[ForgeTask] = field(default_factory=list)
    signal: str = SIGNAL_CONTINUE
    status: str = "ready"
    notes: str = ""
    ts: float = field(default_factory=_now)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "source_url": SOURCE_URL,
            "idea_id": IDEA_ID,
            "project_id": self.project_id,
            "title": self.title,
            "tasks": [t.to_dict() for t in self.tasks],
            "n_tasks": len(self.tasks),
            "lane_counts": lane_counts(self),
            "signal": self.signal,
            "status": self.status,
            "notes": self.notes,
            "ts": self.ts,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ForgeBoard":
        tasks_raw = d.get("tasks") or []
        tasks: list[ForgeTask] = []
        if isinstance(tasks_raw, list):
            for raw in tasks_raw:
                if isinstance(raw, dict):
                    tasks.append(ForgeTask.from_dict(raw))
        return cls(
            project_id=str(d.get("project_id") or "project"),
            title=str(d.get("title") or ""),
            tasks=tasks,
            signal=str(d.get("signal") or SIGNAL_CONTINUE),
            status=str(d.get("status") or "ready"),
            notes=str(d.get("notes") or ""),
            ts=float(d.get("ts") or _now()),
            meta=dict(d.get("meta") or {})
            if isinstance(d.get("meta"), dict)
            else {},
        )


# ---------------------------------------------------------------------------
# Board helpers
# ---------------------------------------------------------------------------


def lane_counts(board: ForgeBoard) -> dict[str, int]:
    counts = {lane: 0 for lane in LANES}
    for t in board.tasks:
        lane = normalize_lane(t.lane)
        counts[lane] = counts.get(lane, 0) + 1
    return counts


def create_board(
    project_id: str,
    title: str = "",
    *,
    meta: Optional[dict[str, Any]] = None,
) -> ForgeBoard:
    pid = str(project_id or "").strip()
    if not pid:
        raise ForgeBoardError("project_id required")
    return ForgeBoard(
        project_id=pid,
        title=str(title or pid),
        notes="forge kanban control plane (wish→forge→review→done)",
        meta={
            "idea_id": IDEA_ID,
            "source_pattern": SOURCE_PATTERN,
            **(dict(meta) if meta else {}),
        },
    )


def get_task(board: ForgeBoard, task_id: str) -> ForgeTask:
    tid = str(task_id or "").strip()
    for t in board.tasks:
        if t.id == tid:
            return t
    raise ForgeBoardError(f"task not found: {tid!r}")


def get_attempt(board: ForgeBoard, attempt_id: str) -> tuple[ForgeTask, ForgeAttempt]:
    aid = str(attempt_id or "").strip()
    for t in board.tasks:
        for a in t.attempts:
            if a.id == aid:
                return t, a
    raise ForgeBoardError(f"attempt not found: {aid!r}")


def create_task(
    board: ForgeBoard,
    title: str,
    *,
    description: str = "",
    acceptance: Optional[Sequence[str]] = None,
    task_id: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
) -> ForgeTask:
    """Create a Wish-column task (planning phase)."""
    ttl = str(title or "").strip()
    if not ttl:
        raise ForgeBoardError("task title required")
    tid = str(task_id or _new_id("task")).strip()
    if not tid:
        raise ForgeBoardError("task id required")
    # Reject path-hostile ids even for pure in-memory tasks (same as FS jail)
    _safe_component(tid, kind="task_id")
    for existing in board.tasks:
        if existing.id == tid:
            raise ForgeBoardError(f"duplicate task id: {tid!r}")
    task = ForgeTask(
        id=tid,
        title=ttl,
        description=str(description or ""),
        lane=LANE_WISH,
        acceptance=[str(a).strip() for a in (acceptance or []) if str(a).strip()],
        history=[f"created→{LANE_WISH}"],
        meta=dict(meta or {}),
    )
    board.tasks.append(task)
    board.ts = _now()
    return task


def attempts_root(workdir: Path | str) -> Path:
    d = Path(workdir).resolve() / ATTEMPT_ROOT
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_attempt_marker(
    root: Path,
    *,
    attempt_id: str,
    task_id: str,
    executor: str,
    agent: str,
    mode: str,
    source: str,
) -> None:
    marker = {
        "schema": SCHEMA,
        "attempt_id": attempt_id,
        "task_id": task_id,
        "executor": executor,
        "agent": agent,
        "mode": mode,
        "source": source,
        "created_at": _now(),
        "note": "forge attempt isolation — pattern only (no full tree clone)",
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / ".nexus_forge_attempt.json").write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def create_attempt_worktree(
    workdir: Path | str,
    *,
    task_id: str,
    attempt_id: str,
    executor: str,
    agent: str,
    mode: str = "sandbox",
) -> dict[str, Any]:
    """Create an isolated attempt directory (sandbox default; optional git).

    *mode*:
      - ``sandbox`` (default): ``.nexus_workspaces/forge_attempts/<task>/<attempt>/``
        (directory isolation only — shares the git working tree index unless
        callers also use ``git`` / ``auto``)
      - ``git``: reuse :func:`worktree_apply.create_worktree` when available
      - ``auto``: try git, fall back to sandbox (records ``git_fallback_error``)
      - ``none``: no filesystem root (dry metadata only)

    *task_id* / *attempt_id* are path-jailed via :func:`_safe_component`.
    """
    source = Path(workdir).resolve()
    mode_n = (mode or "sandbox").strip().lower()
    if mode_n not in ("sandbox", "git", "none", "auto"):
        raise ForgeBoardError(f"invalid isolation mode: {mode!r}")

    safe_tid = _safe_component(task_id, kind="task_id")
    safe_aid = _safe_component(attempt_id, kind="attempt_id")

    if mode_n == "none":
        return {
            "mode": "none",
            "path": "",
            "branch": "",
            "attempt_id": safe_aid,
            "task_id": safe_tid,
        }

    used = "sandbox"
    path = ""
    branch = f"nexus/forge/{safe_tid}/{safe_aid}"
    git_sha = ""
    git_fallback_error = ""

    if mode_n in ("git", "auto"):
        try:
            from .worktree_apply import create_worktree

            meta = create_worktree(
                source,
                job_id=f"forge-{safe_aid}",
                mode="git" if mode_n == "git" else "auto",
                branch=branch,
            )
            used = str(meta.get("mode") or "sandbox")
            path = str(meta.get("path") or "")
            branch = str(meta.get("branch") or branch)
            git_sha = str(meta.get("git_sha") or "")
            # Forced git: refuse soft sandbox fallback from worktree_apply
            if mode_n == "git" and used != "git":
                raise ForgeBoardError(
                    f"git worktree isolation failed: helper returned mode={used!r}"
                )
            if path and used == "git":
                _write_attempt_marker(
                    Path(path),
                    attempt_id=safe_aid,
                    task_id=safe_tid,
                    executor=executor,
                    agent=agent,
                    mode=used,
                    source=str(source),
                )
                return {
                    "mode": used,
                    "path": path,
                    "branch": branch,
                    "git_sha": git_sha or None,
                    "attempt_id": safe_aid,
                    "task_id": safe_tid,
                }
            if path and mode_n == "auto" and used != "sandbox":
                # auto got a real git worktree
                _write_attempt_marker(
                    Path(path),
                    attempt_id=safe_aid,
                    task_id=safe_tid,
                    executor=executor,
                    agent=agent,
                    mode=used,
                    source=str(source),
                )
                return {
                    "mode": used,
                    "path": path,
                    "branch": branch,
                    "git_sha": git_sha or None,
                    "attempt_id": safe_aid,
                    "task_id": safe_tid,
                }
            if mode_n == "git":
                raise ForgeBoardError("git worktree creation returned empty path")
            # auto path: helper soft-fell to sandbox — record and continue below
            if mode_n == "auto" and used == "sandbox":
                git_fallback_error = (
                    git_fallback_error
                    or "worktree_apply returned sandbox (no git worktree)"
                )
        except ForgeBoardError:
            raise
        except Exception as e:  # noqa: BLE001 — fall back to sandbox unless forced
            if mode_n == "git":
                raise ForgeBoardError(f"git worktree isolation failed: {e}") from e
            used = "sandbox"
            git_fallback_error = f"{type(e).__name__}: {e}"[:400]

    # sandbox — path-jailed under attempts_root
    root = attempts_root(source)
    target = (root / safe_tid / safe_aid).resolve()
    if root != target and root not in target.parents:
        raise ForgeBoardError(f"path escapes attempt root: {target}")
    if target.exists():
        raise ForgeBoardError(f"attempt worktree already exists: {target}")
    _write_attempt_marker(
        target,
        attempt_id=safe_aid,
        task_id=safe_tid,
        executor=executor,
        agent=agent,
        mode="sandbox",
        source=str(source),
    )
    out: dict[str, Any] = {
        "mode": "sandbox",
        "path": str(target),
        "branch": "",
        "attempt_id": safe_aid,
        "task_id": safe_tid,
        "source": str(source),
    }
    if git_fallback_error:
        out["git_fallback_error"] = git_fallback_error
    return out


def start_attempt(
    board: ForgeBoard,
    task_id: str,
    *,
    executor: str = "local",
    agent: str = "implementer",
    workdir: Optional[Path | str] = None,
    isolation: str = "sandbox",
    attempt_id: Optional[str] = None,
    auto_move_to_forge: bool = True,
) -> ForgeAttempt:
    """Open a new attempt on a task (Forge column execution).

    When *workdir* is set, materializes an isolated attempt root. Multiple
    attempts may run with different executor/agent pairs for comparison.
    """
    task = get_task(board, task_id)
    if task.lane == LANE_DONE:
        raise ForgeBoardError("cannot start attempt on done task")
    if task.lane == LANE_CANCELLED:
        raise ForgeBoardError("cannot start attempt on cancelled task")

    exe = str(executor or "local").strip() or "local"
    ag = str(agent or "implementer").strip() or "implementer"
    aid = str(attempt_id or _new_id("att")).strip()
    if not aid:
        raise ForgeBoardError("attempt id required")
    _safe_component(aid, kind="attempt_id")
    # Board-wide unique attempt ids (get_attempt resolves first match)
    for t in board.tasks:
        for a in t.attempts:
            if a.id == aid:
                raise ForgeBoardError(f"duplicate attempt id: {aid!r}")

    wt_path = ""
    iso_mode = "none"
    branch = ""
    att_meta: dict[str, Any] = {"source_pattern": SOURCE_PATTERN}
    if workdir is not None:
        meta = create_attempt_worktree(
            workdir,
            task_id=task.id,
            attempt_id=aid,
            executor=exe,
            agent=ag,
            mode=isolation,
        )
        wt_path = str(meta.get("path") or "")
        iso_mode = str(meta.get("mode") or "sandbox")
        branch = str(meta.get("branch") or "")
        if meta.get("git_fallback_error"):
            att_meta["git_fallback_error"] = meta["git_fallback_error"]
        # Prefer jailed ids returned by create_attempt_worktree
        aid = str(meta.get("attempt_id") or aid)
    else:
        # No workdir ⇒ no real isolation; never claim "sandbox" without a path.
        iso_req = (isolation or "none").strip().lower()
        if iso_req == "git":
            raise ForgeBoardError("isolation=git requires workdir")
        if iso_req not in ("none", "sandbox", "auto", ""):
            raise ForgeBoardError(f"invalid isolation mode: {isolation!r}")
        iso_mode = "none"

    attempt = ForgeAttempt(
        id=aid,
        task_id=task.id,
        executor=exe,
        agent=ag,
        status=ATTEMPT_RUNNING,
        worktree_path=wt_path,
        isolation_mode=iso_mode,
        branch=branch,
        meta=att_meta,
    )
    task.attempts.append(attempt)
    task.updated_at = _now()
    task.history.append(f"attempt_start:{aid}:{exe}/{ag}")

    if auto_move_to_forge and task.lane == LANE_WISH:
        task.lane = LANE_FORGE
        task.history.append(f"{LANE_WISH}→{LANE_FORGE}")
        board.signal = SIGNAL_CONTINUE

    board.ts = _now()
    return attempt


def finish_attempt(
    board: ForgeBoard,
    attempt_id: str,
    *,
    ok: bool,
    summary: str = "",
    changed_files: Optional[Sequence[str]] = None,
    error: str = "",
) -> ForgeAttempt:
    """Mark an attempt succeeded or failed (does not auto-select)."""
    task, attempt = get_attempt(board, attempt_id)
    if attempt.status not in (ATTEMPT_PENDING, ATTEMPT_RUNNING):
        raise ForgeBoardError(
            f"attempt {attempt_id!r} already finished: {attempt.status}"
        )
    attempt.status = ATTEMPT_SUCCEEDED if ok else ATTEMPT_FAILED
    attempt.summary = str(summary or "")[:500]
    attempt.error = str(error or "")[:400] if not ok else ""
    if changed_files is not None:
        cleaned: list[str] = []
        seen: set[str] = set()
        for f in changed_files:
            s = str(f).strip()
            if s and s not in seen:
                seen.add(s)
                cleaned.append(s)
        attempt.changed_files = cleaned
    attempt.updated_at = _now()
    task.updated_at = _now()
    task.history.append(
        f"attempt_finish:{attempt_id}:{'ok' if ok else 'fail'}"
    )
    board.ts = _now()
    return attempt


def select_attempt(
    board: ForgeBoard,
    task_id: str,
    attempt_id: str,
    *,
    auto_move_to_review: bool = True,
) -> ForgeAttempt:
    """Operator chooses the winning attempt for Review (forge review phase).

    Validate-then-mutate: a rejected select is a true no-op (no half-written
    selection flags / selected_attempt_id drift).
    """
    task = get_task(board, task_id)
    if task.lane == LANE_DONE:
        raise ForgeBoardError("cannot change selection on done task")
    aid = str(attempt_id)
    target = next((a for a in task.attempts if a.id == aid), None)
    if target is None:
        raise ForgeBoardError(f"attempt {attempt_id!r} not on task {task_id!r}")
    if target.status != ATTEMPT_SUCCEEDED:
        raise ForgeBoardError(
            f"can only select a succeeded attempt (got {target.status})"
        )
    # Mutate only after both checks pass
    for a in task.attempts:
        a.selected = a is target
    task.selected_attempt_id = target.id
    task.updated_at = _now()
    task.history.append(f"select:{target.id}")
    if auto_move_to_review and task.lane in (LANE_WISH, LANE_FORGE):
        prev = task.lane
        task.lane = LANE_REVIEW
        task.history.append(f"{prev}→{LANE_REVIEW}")
        board.signal = SIGNAL_REVIEW
    board.ts = _now()
    return target


def compare_attempts(board: ForgeBoard, task_id: str) -> dict[str, Any]:
    """Side-by-side attempt summary for Review column."""
    task = get_task(board, task_id)
    rows = []
    for a in task.attempts:
        rows.append(
            {
                "id": a.id,
                "executor": a.executor,
                "agent": a.agent,
                "status": a.status,
                "selected": a.selected or a.id == task.selected_attempt_id,
                "n_changed_files": len(a.changed_files),
                "changed_files": list(a.changed_files),
                "summary": a.summary,
                "error": a.error,
                "isolation_mode": a.isolation_mode,
                "worktree_path": a.worktree_path,
            }
        )
    succeeded = [r for r in rows if r["status"] == ATTEMPT_SUCCEEDED]
    return {
        "schema": SCHEMA,
        "task_id": task.id,
        "title": task.title,
        "lane": task.lane,
        "n_attempts": len(rows),
        "n_succeeded": len(succeeded),
        "selected_attempt_id": task.selected_attempt_id,
        "attempts": rows,
        "recommendation": (
            succeeded[0]["id"]
            if len(succeeded) == 1
            else (task.selected_attempt_id or (succeeded[0]["id"] if succeeded else ""))
        ),
    }


def try_move_task(
    board: ForgeBoard,
    task_id: str,
    to_lane: str,
    *,
    force: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    """Move a task across Wish/Forge/Review/Done with entry gates.

    Gates (unless *force*):
      - wish→forge: always allowed (planning complete)
      - forge→review: requires ≥1 succeeded attempt + selected attempt
      - review→done: requires selected succeeded attempt
      - review→forge: retry (more attempts)
    """
    task = get_task(board, task_id)
    src = normalize_lane(task.lane, strict=True)
    # Fail closed on typos — never treat unknown lanes as already_there
    dst = normalize_lane(to_lane, strict=True)
    if src == dst:
        return {"ok": True, "moved": False, "lane": src, "reason": "already_there"}

    if not can_transition(src, dst) and not force:
        raise ForgeBoardError(f"illegal transition {src!r} → {dst!r}")

    reasons: list[str] = []
    if not force:
        if dst == LANE_REVIEW:
            ok_atts = [a for a in task.attempts if a.status == ATTEMPT_SUCCEEDED]
            if not ok_atts:
                reasons.append("no_succeeded_attempt")
            if not task.selected_attempt_id:
                # auto-pick sole success for convenience
                if len(ok_atts) == 1:
                    select_attempt(
                        board, task.id, ok_atts[0].id, auto_move_to_review=False
                    )
                else:
                    reasons.append("no_selected_attempt")
        if dst == LANE_DONE:
            if not task.selected_attempt_id:
                reasons.append("no_selected_attempt")
            else:
                # Resolve winner only within this task (never cross-task)
                att = next(
                    (
                        a
                        for a in task.attempts
                        if a.id == task.selected_attempt_id
                    ),
                    None,
                )
                if att is None:
                    reasons.append("selected_attempt_missing")
                elif att.status != ATTEMPT_SUCCEEDED:
                    reasons.append(f"selected_not_succeeded:{att.status}")
        if reasons:
            return {
                "ok": False,
                "moved": False,
                "lane": src,
                "target": dst,
                "reasons": reasons,
            }

    task.lane = dst
    task.updated_at = _now()
    note = reason or "move"
    task.history.append(f"{src}→{dst}:{note}")
    if dst == LANE_DONE:
        board.signal = SIGNAL_SHIP
    elif dst == LANE_REVIEW:
        board.signal = SIGNAL_REVIEW
    elif dst == LANE_CANCELLED:
        board.signal = SIGNAL_CANCEL
    elif dst == LANE_FORGE:
        board.signal = SIGNAL_CONTINUE
    elif dst == LANE_WISH:
        board.signal = SIGNAL_REPLAN
    board.ts = _now()
    return {"ok": True, "moved": True, "from": src, "lane": dst, "reason": note}


def ship_task(board: ForgeBoard, task_id: str) -> dict[str, Any]:
    """Mark Review→Done when a succeeded attempt is selected.

    This is a **lane gate** only — it does not merge/promote worktree files
    into the main tree. Promotion remains a separate
    :mod:`nexus.worktree_apply` concern (deferred full ship adapter).
    """
    return try_move_task(board, task_id, LANE_DONE, reason="ship")


def board_state_path(root: Path | str, project_id: str) -> Path:
    """Path for durable board snapshot under ``.nexus_state/forge_boards/``."""
    pid = _safe_component(str(project_id or "").strip() or "project", kind="project_id")
    return Path(root).resolve() / BOARD_STATE_DIR / f"{pid}.json"


def save_board(board: ForgeBoard, root: Path | str) -> Path:
    """Atomically persist *board* under *root* (survives process restart)."""
    from .persist import atomic_write_json

    path = board_state_path(root, board.project_id)
    atomic_write_json(path, board.to_dict())
    board.ts = _now()
    return path


def load_board(root: Path | str, project_id: str) -> ForgeBoard:
    """Load a previously saved board; raises if missing or corrupt."""
    path = board_state_path(root, project_id)
    if not path.is_file():
        raise ForgeBoardError(f"board not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ForgeBoardError(f"board load failed: {e}") from e
    if not isinstance(data, dict):
        raise ForgeBoardError("invalid board file: expected object")
    return ForgeBoard.from_dict(data)


def run_demo(
    workdir: Optional[Path | str] = None,
    *,
    project_id: str = "forge-demo",
) -> ForgeBoard:
    """Happy-path Wish→Forge→Review→Done with two competing attempts."""
    board = create_board(project_id, "Forge multi-attempt demo")
    task = create_task(
        board,
        "Port forge kanban control plane",
        description="Wish→Forge→Review with worktree-isolated attempts",
        acceptance=[
            "kanban lanes wish/forge/review/done",
            "multiple attempts per task",
            "isolation marker under forge_attempts",
        ],
    )
    # Attempt A: local implementer
    a1 = start_attempt(
        board,
        task.id,
        executor="local",
        agent="implementer",
        workdir=workdir,
        isolation="sandbox" if workdir else "none",
    )
    finish_attempt(
        board,
        a1.id,
        ok=True,
        summary="implemented forge_board skeleton",
        changed_files=["src/nexus/forge_board.py"],
    )
    # Attempt B: different provider/agent (fails — compare surface)
    a2 = start_attempt(
        board,
        task.id,
        executor="claude_code",
        agent="test-writer",
        workdir=workdir,
        isolation="sandbox" if workdir else "none",
    )
    finish_attempt(
        board,
        a2.id,
        ok=False,
        summary="tests incomplete",
        error="missing assertion on select_attempt",
    )
    select_attempt(board, task.id, a1.id)
    ship_task(board, task.id)
    board.status = "demo_complete"
    board.notes = (
        f"selected={a1.id} executor={a1.executor}/{a1.agent} "
        f"rejected={a2.id}"
    )
    return board


def format_board(board: ForgeBoard) -> str:
    """Human-readable kanban brief."""
    counts = lane_counts(board)
    lines = [
        f"forge board  project={board.project_id}  signal={board.signal}",
        f"  pattern={SOURCE_PATTERN}  schema={SCHEMA}",
        "  lanes: "
        + "  ".join(f"{k}={counts.get(k, 0)}" for k in LANES if k != LANE_CANCELLED),
    ]
    for t in board.tasks:
        sel = t.selected_attempt_id or "-"
        lines.append(
            f"  [{t.lane:9}] {t.id}  {t.title!r}  "
            f"attempts={len(t.attempts)} selected={sel}"
        )
        for a in t.attempts:
            mark = "*" if (a.selected or a.id == t.selected_attempt_id) else " "
            lines.append(
                f"    {mark} {a.id}  {a.executor}/{a.agent}  "
                f"status={a.status}  files={len(a.changed_files)}  "
                f"iso={a.isolation_mode}"
            )
    return "\n".join(lines)


def board_payload_for_meta(board: ForgeBoard) -> dict[str, Any]:
    """Compact operator payload for orchestrator meta / MCP."""
    d = board.to_dict()
    return {
        "schema": SCHEMA,
        "source_pattern": SOURCE_PATTERN,
        "idea_id": IDEA_ID,
        "project_id": d["project_id"],
        "title": d["title"],
        "signal": d["signal"],
        "status": d["status"],
        "n_tasks": d["n_tasks"],
        "lane_counts": d["lane_counts"],
        "tasks": [
            {
                "id": t["id"],
                "title": t["title"],
                "lane": t["lane"],
                "attempt_count": t["attempt_count"],
                "selected_attempt_id": t["selected_attempt_id"],
                "has_in_progress_attempt": t["has_in_progress_attempt"],
                "has_succeeded_attempt": t["has_succeeded_attempt"],
            }
            for t in d["tasks"]
        ],
        "brief": format_board(board),
    }


def maybe_build_for_task(
    workdir: Any,
    task_id: str,
    goal: str,
    meta: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Opt-in builder for orchestrator (``with_forge_board`` / ``forge_board``)."""
    if not meta or not isinstance(meta, dict):
        return None
    flags = ("with_forge_board", "forge_board", "automagik_forge")
    if not any(bool(meta.get(k)) for k in flags):
        return None

    project = str(
        meta.get("project_id") or meta.get("project") or task_id or "project"
    ).strip()
    acceptance = (
        meta.get("acceptance") if isinstance(meta.get("acceptance"), list) else None
    )
    try:
        board = create_board(project, str(goal or project))
        task = create_task(
            board,
            str(goal or "forge task").strip() or "forge task",
            description=str(meta.get("description") or ""),
            acceptance=acceptance,
            task_id=str(task_id or _new_id("task")),
        )
        # Optional seed attempt
        if meta.get("seed_attempt") or meta.get("start_lane") in (
            LANE_FORGE,
            LANE_REVIEW,
            "forge",
            "review",
            "inprogress",
            "inreview",
        ):
            exe = str(meta.get("executor") or "local")
            ag = str(meta.get("agent") or "implementer")
            iso = str(meta.get("isolation") or "none")
            wd = workdir if iso != "none" else None
            att = start_attempt(
                board,
                task.id,
                executor=exe,
                agent=ag,
                workdir=wd,
                isolation=iso if wd is not None else "none",
            )
            if meta.get("seed_attempt_ok"):
                files = meta.get("changed_files")
                finish_attempt(
                    board,
                    att.id,
                    ok=True,
                    summary=str(meta.get("seed_summary") or "seeded"),
                    changed_files=list(files) if isinstance(files, (list, tuple)) else None,
                )
                if meta.get("select_seed") or normalize_lane(
                    str(meta.get("start_lane") or "")
                ) in (LANE_REVIEW, LANE_DONE):
                    select_attempt(board, task.id, att.id)
        start = meta.get("start_lane") or meta.get("lane")
        if start:
            target = normalize_lane(str(start))
            if target in (LANE_FORGE, LANE_REVIEW, LANE_DONE) and task.lane != target:
                # walk with force only for seed placement up to review
                order = [LANE_WISH, LANE_FORGE, LANE_REVIEW]
                if target == LANE_DONE:
                    target = LANE_REVIEW
                    task.meta["seed_capped"] = "review"
                if target in order and task.lane in order:
                    idx_t = order.index(target)
                    idx_s = order.index(task.lane) if task.lane in order else 0
                    for lane in order[idx_s + 1 : idx_t + 1]:
                        try_move_task(
                            board,
                            task.id,
                            lane,
                            force=True,
                            reason="seed_start_lane",
                        )

        payload = board_payload_for_meta(board)
        return {
            "ok": True,
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "idea_id": IDEA_ID,
            "task_id": str(task_id or ""),
            "project_id": board.project_id,
            "status": board.status,
            "signal": board.signal,
            "lane": board.tasks[0].lane if board.tasks else None,
            "board": payload,
            "board_full": board.to_dict(),
            "brief": format_board(board),
        }
    except ForgeBoardError as e:
        return {
            "ok": False,
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "task_id": str(task_id or ""),
            "error": str(e),
            "status": "failed",
        }


__all__ = [
    "SCHEMA",
    "SOURCE_PATTERN",
    "SOURCE_URL",
    "IDEA_ID",
    "LANES",
    "ALL_LANES",
    "LANE_WISH",
    "LANE_FORGE",
    "LANE_REVIEW",
    "LANE_DONE",
    "LANE_CANCELLED",
    "FORGE_STATUS_MAP",
    "BOARD_STATE_DIR",
    "ATTEMPT_PENDING",
    "ATTEMPT_RUNNING",
    "ATTEMPT_SUCCEEDED",
    "ATTEMPT_FAILED",
    "ATTEMPT_STATUSES",
    "DEFAULT_EXECUTORS",
    "DEFAULT_AGENTS",
    "ATTEMPT_ROOT",
    "SIGNAL_CONTINUE",
    "SIGNAL_REVIEW",
    "SIGNAL_SHIP",
    "SIGNAL_REPLAN",
    "SIGNAL_CANCEL",
    "ForgeBoardError",
    "ForgeAttempt",
    "ForgeTask",
    "ForgeBoard",
    "normalize_lane",
    "can_transition",
    "lane_counts",
    "create_board",
    "get_task",
    "get_attempt",
    "create_task",
    "attempts_root",
    "create_attempt_worktree",
    "start_attempt",
    "finish_attempt",
    "select_attempt",
    "compare_attempts",
    "try_move_task",
    "ship_task",
    "board_state_path",
    "save_board",
    "load_board",
    "run_demo",
    "format_board",
    "board_payload_for_meta",
    "maybe_build_for_task",
    "main",
]


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import tempfile

    p = argparse.ArgumentParser(
        prog="python -m nexus.forge_board",
        description=(
            "Forge-shaped Wish→Forge→Review kanban with multi-attempt isolation "
            f"({SOURCE_PATTERN})"
        ),
    )
    p.add_argument("goal", nargs="?", default="", help="Demo project / task title")
    p.add_argument("--project", default="forge-demo", help="Project id")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--demo",
        action="store_true",
        help="Run Wish→Forge→Review→Done with two attempts + sandbox",
    )
    p.add_argument(
        "--workdir",
        default="",
        help="Workdir for attempt sandboxes (default: temp for --demo)",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.demo or not str(args.goal or "").strip():
        wd: Optional[str]
        ephemeral = False
        if args.workdir:
            wd = str(args.workdir)
        else:
            # ephemeral sandbox root so demo does not dirty repo by default
            wd = tempfile.mkdtemp(prefix="nexus-forge-demo-")
            ephemeral = True
        board = run_demo(wd, project_id=str(args.project))
        if args.json:
            print(json.dumps(board.to_dict(), indent=2, default=str))
        else:
            print(format_board(board))
            print(f"notes: {board.notes}")
            if ephemeral:
                print(f"workdir: {wd}")
            cmp_ = compare_attempts(board, board.tasks[0].id)
            print(
                f"compare: n_attempts={cmp_['n_attempts']} "
                f"n_succeeded={cmp_['n_succeeded']} "
                f"selected={cmp_['selected_attempt_id']}"
            )
        return 0

    board = create_board(str(args.project), str(args.goal))
    create_task(board, str(args.goal), description="wish column seed")
    if args.json:
        print(json.dumps(board.to_dict(), indent=2, default=str))
    else:
        print(format_board(board))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
