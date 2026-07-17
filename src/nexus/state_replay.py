"""Intermediate state cache + selective replay (SWE-Replay × wshobson/agents).

Paper: *SWE-Replay: Efficient Test-Time Scaling for Software Engineering Agents*
https://arxiv.org/abs/2601.22129v2

GitHub pattern (shape only — not a vendored tree):
  wshobson/agents — single-source Markdown marketplace of plugins with
  agents/*.md, skills/*/SKILL.md, commands/*.md (+ multi-harness adapters).

Novel hybrid (portfolio cross_pattern):

  orchestrator trajectory steps
                │
                ▼
         ┌──────────────────┐   IntermediateState records
         │  StateCache      │ ──► directory / kv / marketplace
         │  (SWE-Replay)    │     agent | skill | command surfaces
         └──────────────────┘
                │
                ├── capture (fingerprint + put)
                ├── select_replay (kinds / surfaces / step window)
                └── ReplayPlan for test-time re-use (no full re-run)

SWE-Replay caches intermediate agent states so test-time scaling can
selectively *replay* prior states instead of re-executing entire
trajectories. This module is a thin, offline-first cache for NEXUS:

- capture directory listings (metadata only by default — no file bodies)
- capture marketplace catalog slices (agents/skills/commands)
- capture step/component payloads keyed by (task_id, step_id, kind)
- selective replay plans filtered by kind, marketplace surface, and step range

Storage (JSONL + index, atomic)::

  ``.nexus_state/orchestrator/state_cache/<task_id>/states.jsonl``
  ``.nexus_state/orchestrator/state_cache/<task_id>/index.json``

No network; no secrets; pattern only — not a vendored upstream tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .persist import append_jsonl, atomic_write_json, read_jsonl

SCHEMA = "nexus.state_replay/v1"
PAPER = "arxiv:2601.22129v2"
SOURCE_PATTERN = "wshobson/agents"

CACHE_REL = Path(".nexus_state") / "orchestrator" / "state_cache"
DEFAULT_MAX_STATES_PER_TASK = 200
DEFAULT_MAX_DIR_ENTRIES = 500

# State kinds (what is cached)
KIND_DIRECTORY = "directory"
KIND_KV = "kv"
KIND_MARKETPLACE = "marketplace"
KIND_AGENT = "agent"
KIND_SKILL = "skill"
KIND_COMMAND = "command"
KIND_OBSERVE = "observe"
KIND_BLOB = "blob"

KINDS: frozenset[str] = frozenset(
    {
        KIND_DIRECTORY,
        KIND_KV,
        KIND_MARKETPLACE,
        KIND_AGENT,
        KIND_SKILL,
        KIND_COMMAND,
        KIND_OBSERVE,
        KIND_BLOB,
    }
)

# Marketplace surfaces (wshobson shape) — subset of kinds used as surfaces
MARKETPLACE_SURFACES: frozenset[str] = frozenset(
    {KIND_AGENT, KIND_SKILL, KIND_COMMAND}
)

# Selective replay strategies
STRATEGY_ALL = "all"
STRATEGY_LATEST_PER_KIND = "latest_per_kind"
STRATEGY_LATEST_PER_SURFACE = "latest_per_surface"
STRATEGY_WINDOW = "window"

STRATEGIES: frozenset[str] = frozenset(
    {
        STRATEGY_ALL,
        STRATEGY_LATEST_PER_KIND,
        STRATEGY_LATEST_PER_SURFACE,
        STRATEGY_WINDOW,
    }
)

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".eggs",
    }
)


class StateReplayError(RuntimeError):
    """Invalid state-replay operation."""


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def sanitize_task_id(raw: str) -> str:
    tid = str(raw or "").strip()
    if not tid or not _ID_RE.match(tid):
        raise StateReplayError(
            f"invalid task_id: {raw!r} (use [a-zA-Z0-9._-] max 64)"
        )
    if ".." in tid or "/" in tid or "\\" in tid:
        raise StateReplayError(f"invalid task_id path chars: {raw!r}")
    return tid


def cache_dir(workdir: Optional[Path | str] = None, task_id: Optional[str] = None) -> Path:
    base = _root(workdir) / CACHE_REL
    if task_id is None:
        base.mkdir(parents=True, exist_ok=True)
        return base
    d = base / sanitize_task_id(task_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def states_path(workdir: Optional[Path | str], task_id: str) -> Path:
    return cache_dir(workdir, task_id) / "states.jsonl"


def index_path(workdir: Optional[Path | str], task_id: str) -> Path:
    return cache_dir(workdir, task_id) / "index.json"


def fingerprint(payload: Any) -> str:
    """Stable content fingerprint (sha256 hex, 32 chars)."""
    if isinstance(payload, (dict, list)):
        raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    else:
        raw = str(payload if payload is not None else "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def state_key(
    *,
    task_id: str,
    step_id: str = "",
    kind: str = KIND_KV,
    surface: str = "",
    name: str = "",
    extra: str = "",
) -> str:
    """Stable cache key for an intermediate state (sha256 hex, 32 chars)."""
    payload = "|".join(
        [
            str(task_id or "").strip(),
            str(step_id or "").strip(),
            str(kind or "").strip().lower(),
            str(surface or "").strip().lower(),
            str(name or "").strip(),
            str(extra or "").strip(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def normalize_kind(kind: str) -> str:
    k = str(kind or "").strip().lower()
    if k not in KINDS:
        raise StateReplayError(f"unknown kind {kind!r}; known={sorted(KINDS)}")
    return k


def normalize_surface(surface: str) -> str:
    s = str(surface or "").strip().lower()
    if not s:
        return ""
    if s not in MARKETPLACE_SURFACES and s not in KINDS:
        # Allow free-form surfaces for kv/blob; marketplace ones are preferred
        return s
    return s


# ── Intermediate state ──────────────────────────────────────────────────────


@dataclass
class IntermediateState:
    """One cached intermediate state along an orchestrator trajectory."""

    state_id: str
    task_id: str
    kind: str
    step_id: str = ""
    surface: str = ""  # agent|skill|command when marketplace-related
    name: str = ""
    plugin_id: str = ""
    parent_id: str = ""
    key: str = ""
    fingerprint: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    schema: str = SCHEMA
    paper: str = PAPER
    source_pattern: str = SOURCE_PATTERN

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntermediateState":
        if not isinstance(data, dict):
            raise StateReplayError("state must be a dict")
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kw = {k: v for k, v in data.items() if k in known}
        kw.setdefault("payload", {})
        kw.setdefault("meta", {})
        kw.setdefault("schema", SCHEMA)
        kw.setdefault("paper", PAPER)
        kw.setdefault("source_pattern", SOURCE_PATTERN)
        if not kw.get("state_id"):
            kw["state_id"] = f"st-{uuid.uuid4().hex[:12]}"
        if not kw.get("task_id"):
            raise StateReplayError("state requires task_id")
        if not kw.get("kind"):
            kw["kind"] = KIND_KV
        return cls(**kw)


def make_state(
    *,
    task_id: str,
    kind: str = KIND_KV,
    payload: Optional[dict[str, Any]] = None,
    step_id: str = "",
    surface: str = "",
    name: str = "",
    plugin_id: str = "",
    parent_id: str = "",
    meta: Optional[dict[str, Any]] = None,
    state_id: Optional[str] = None,
    extra_key: str = "",
) -> IntermediateState:
    """Build an IntermediateState with key + fingerprint filled in."""
    tid = sanitize_task_id(task_id)
    k = normalize_kind(kind)
    surf = normalize_surface(surface) or (
        k if k in MARKETPLACE_SURFACES else ""
    )
    body = dict(payload or {})
    fp = fingerprint(body)
    key = state_key(
        task_id=tid,
        step_id=step_id,
        kind=k,
        surface=surf,
        name=name,
        extra=extra_key or fp[:8],
    )
    return IntermediateState(
        state_id=state_id or f"st-{uuid.uuid4().hex[:12]}",
        task_id=tid,
        kind=k,
        step_id=str(step_id or ""),
        surface=surf,
        name=str(name or ""),
        plugin_id=str(plugin_id or ""),
        parent_id=str(parent_id or ""),
        key=key,
        fingerprint=fp,
        payload=body,
        meta=dict(meta or {}),
    )


# ── Capturers ───────────────────────────────────────────────────────────────


def capture_directory(
    path: Path | str,
    *,
    rel_root: Optional[Path | str] = None,
    max_entries: int = DEFAULT_MAX_DIR_ENTRIES,
    include_hidden: bool = False,
    max_depth: int = 4,
) -> dict[str, Any]:
    """Snapshot directory *listing* (names, sizes, mtimes) — not file bodies.

    SWE-Replay-style intermediate workspace state without shipping blobs.
    """
    root = Path(path).resolve()
    if not root.exists():
        return {
            "ok": False,
            "error": "not_found",
            "path": str(root),
            "entries": [],
            "n_entries": 0,
        }
    if not root.is_dir():
        # Single file metadata
        try:
            st = root.stat()
            entry = {
                "path": root.name,
                "type": "file",
                "size": int(st.st_size),
                "mtime": float(st.st_mtime),
            }
        except OSError as e:
            return {
                "ok": False,
                "error": str(e),
                "path": str(root),
                "entries": [],
                "n_entries": 0,
            }
        return {
            "ok": True,
            "path": str(root),
            "entries": [entry],
            "n_entries": 1,
            "truncated": False,
        }

    base = Path(rel_root).resolve() if rel_root is not None else root
    entries: list[dict[str, Any]] = []
    truncated = False
    limit = max(1, int(max_entries))
    depth_cap = max(0, int(max_depth))

    def _walk(cur: Path, depth: int) -> None:
        nonlocal truncated
        if truncated or depth > depth_cap:
            return
        try:
            children = sorted(cur.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for child in children:
            if truncated:
                return
            name = child.name
            if not include_hidden and name.startswith("."):
                continue
            if child.is_dir() and name in _SKIP_DIR_NAMES:
                continue
            try:
                rel = str(child.relative_to(base))
            except ValueError:
                rel = name
            if child.is_dir():
                entries.append({"path": rel, "type": "dir", "size": 0, "mtime": 0.0})
                if len(entries) >= limit:
                    truncated = True
                    return
                _walk(child, depth + 1)
            else:
                try:
                    st = child.stat()
                    size = int(st.st_size)
                    mtime = float(st.st_mtime)
                except OSError:
                    size, mtime = 0, 0.0
                entries.append(
                    {
                        "path": rel,
                        "type": "file",
                        "size": size,
                        "mtime": mtime,
                    }
                )
                if len(entries) >= limit:
                    truncated = True
                    return

    _walk(root, 0)
    return {
        "ok": True,
        "path": str(root),
        "entries": entries,
        "n_entries": len(entries),
        "truncated": truncated,
        "max_depth": depth_cap,
    }


def capture_marketplace(
    workdir: Optional[Path | str] = None,
    *,
    plugins_dir: str = "plugins",
    include_skillpacks: bool = True,
) -> dict[str, Any]:
    """Snapshot marketplace catalog (agents/skills/commands) — wshobson shape.

    Uses in-tree ``marketplace.list_plugins`` when available; falls back to a
    lightweight directory scan so unit tests do not require a full garden.
    """
    root = _root(workdir)
    plugins_path = root / plugins_dir
    components: list[dict[str, Any]] = []
    plugins: list[dict[str, Any]] = []

    try:
        from . import marketplace as mp

        infos = mp.list_plugins(
            root,
            plugins_dir=plugins_dir,
            include_skillpacks=include_skillpacks,
        )
        for info in infos:
            pid = getattr(info, "id", "") or ""
            agents = list(getattr(info, "agents", None) or [])
            skills = list(getattr(info, "skills", None) or [])
            commands = list(getattr(info, "commands", None) or [])
            plugins.append(
                {
                    "id": pid,
                    "name": getattr(info, "name", "") or "",
                    "version": getattr(info, "version", "") or "",
                    "privilege": getattr(info, "privilege", "") or "",
                    "n_components": len(agents) + len(skills) + len(commands),
                    "origin": getattr(info, "origin", "") or "",
                }
            )
            for name in agents:
                components.append(
                    {
                        "kind": KIND_AGENT,
                        "name": name,
                        "plugin_id": pid,
                        "path": f"agents/{name}.md",
                    }
                )
            for name in skills:
                components.append(
                    {
                        "kind": KIND_SKILL,
                        "name": name,
                        "plugin_id": pid,
                        "path": f"skills/{name}/SKILL.md",
                    }
                )
            for name in commands:
                components.append(
                    {
                        "kind": KIND_COMMAND,
                        "name": name,
                        "plugin_id": pid,
                        "path": f"commands/{name}.md",
                    }
                )
    except Exception:
        # Lightweight fallback: scan plugins/<id>/{agents,skills,commands}
        if plugins_path.is_dir():
            for pdir in sorted(plugins_path.iterdir()):
                if not pdir.is_dir() or pdir.name.startswith("."):
                    continue
                pid = pdir.name
                plugins.append({"id": pid, "name": pid, "version": "", "privilege": ""})
                for kind, sub, pattern in (
                    (KIND_AGENT, "agents", "*.md"),
                    (KIND_COMMAND, "commands", "*.md"),
                ):
                    d = pdir / sub
                    if d.is_dir():
                        for f in sorted(d.glob(pattern)):
                            components.append(
                                {
                                    "kind": kind,
                                    "name": f.stem,
                                    "plugin_id": pid,
                                    "path": f"{sub}/{f.name}",
                                }
                            )
                skills = pdir / "skills"
                if skills.is_dir():
                    for sd in sorted(skills.iterdir()):
                        if sd.is_dir() and (sd / "SKILL.md").is_file():
                            components.append(
                                {
                                    "kind": KIND_SKILL,
                                    "name": sd.name,
                                    "plugin_id": pid,
                                    "path": f"skills/{sd.name}/SKILL.md",
                                }
                            )

    by_kind: dict[str, int] = {}
    for c in components:
        k = str(c.get("kind") or "unknown")
        by_kind[k] = by_kind.get(k, 0) + 1

    return {
        "ok": True,
        "workdir": str(root),
        "plugins_dir": plugins_dir,
        "n_plugins": len(plugins),
        "n_components": len(components),
        "by_kind": by_kind,
        "plugins": plugins,
        "components": components,
        "source_pattern": SOURCE_PATTERN,
        "paper": PAPER,
    }


def capture_component(
    *,
    kind: str,
    name: str,
    plugin_id: str = "",
    payload: Optional[dict[str, Any]] = None,
    description: str = "",
) -> dict[str, Any]:
    """Snapshot one marketplace component invocation/result payload."""
    k = normalize_kind(kind)
    if k not in MARKETPLACE_SURFACES:
        raise StateReplayError(
            f"component kind must be one of {sorted(MARKETPLACE_SURFACES)}; got {kind!r}"
        )
    body = dict(payload or {})
    return {
        "ok": True,
        "kind": k,
        "name": str(name or ""),
        "plugin_id": str(plugin_id or ""),
        "description": str(description or ""),
        "payload": body,
        "source_pattern": SOURCE_PATTERN,
    }


# ── Cache store ─────────────────────────────────────────────────────────────


@dataclass
class StateCache:
    """Per-workdir intermediate-state cache (SWE-Replay shape)."""

    workdir: Path
    max_states_per_task: int = DEFAULT_MAX_STATES_PER_TASK

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir).resolve()
        cache_dir(self.workdir)

    @classmethod
    def open(cls, workdir: Optional[Path | str] = None, **kw: Any) -> "StateCache":
        return cls(workdir=_root(workdir), **kw)

    def put(self, state: IntermediateState | dict[str, Any]) -> IntermediateState:
        """Append a state to the task journal and refresh the index."""
        st = (
            state
            if isinstance(state, IntermediateState)
            else IntermediateState.from_dict(state)
        )
        tid = sanitize_task_id(st.task_id)
        path = states_path(self.workdir, tid)
        row = st.to_dict()
        append_jsonl(path, row)
        self._refresh_index(tid)
        # Trim if over cap (rewrite journal keeping newest)
        states = self.list(tid)
        if len(states) > int(self.max_states_per_task):
            keep = states[-int(self.max_states_per_task) :]
            self._rewrite(tid, keep)
        return st

    def capture(
        self,
        *,
        task_id: str,
        kind: str,
        payload: Optional[dict[str, Any]] = None,
        step_id: str = "",
        surface: str = "",
        name: str = "",
        plugin_id: str = "",
        parent_id: str = "",
        meta: Optional[dict[str, Any]] = None,
        extra_key: str = "",
    ) -> IntermediateState:
        """Build + put an intermediate state."""
        st = make_state(
            task_id=task_id,
            kind=kind,
            payload=payload,
            step_id=step_id,
            surface=surface,
            name=name,
            plugin_id=plugin_id,
            parent_id=parent_id,
            meta=meta,
            extra_key=extra_key,
        )
        return self.put(st)

    def capture_dir(
        self,
        task_id: str,
        path: Path | str,
        *,
        step_id: str = "",
        **capture_kw: Any,
    ) -> IntermediateState:
        payload = capture_directory(path, **capture_kw)
        return self.capture(
            task_id=task_id,
            kind=KIND_DIRECTORY,
            payload=payload,
            step_id=step_id,
            name=Path(path).name,
            meta={"capturer": "directory"},
        )

    def capture_market(
        self,
        task_id: str,
        *,
        step_id: str = "",
        plugins_dir: str = "plugins",
        include_skillpacks: bool = True,
    ) -> IntermediateState:
        payload = capture_marketplace(
            self.workdir,
            plugins_dir=plugins_dir,
            include_skillpacks=include_skillpacks,
        )
        return self.capture(
            task_id=task_id,
            kind=KIND_MARKETPLACE,
            payload=payload,
            step_id=step_id,
            surface="",
            name="marketplace",
            meta={"capturer": "marketplace", "source_pattern": SOURCE_PATTERN},
        )

    def capture_component_step(
        self,
        task_id: str,
        *,
        kind: str,
        name: str,
        plugin_id: str = "",
        step_id: str = "",
        payload: Optional[dict[str, Any]] = None,
        description: str = "",
    ) -> IntermediateState:
        body = capture_component(
            kind=kind,
            name=name,
            plugin_id=plugin_id,
            payload=payload,
            description=description,
        )
        return self.capture(
            task_id=task_id,
            kind=normalize_kind(kind),
            payload=body,
            step_id=step_id,
            surface=normalize_kind(kind),
            name=name,
            plugin_id=plugin_id,
            meta={"capturer": "component", "source_pattern": SOURCE_PATTERN},
        )

    def list(self, task_id: str) -> list[IntermediateState]:
        tid = sanitize_task_id(task_id)
        rows = read_jsonl(states_path(self.workdir, tid))
        out: list[IntermediateState] = []
        for r in rows:
            try:
                out.append(IntermediateState.from_dict(r))
            except StateReplayError:
                continue
        return out

    def get(
        self,
        task_id: str,
        *,
        state_id: Optional[str] = None,
        key: Optional[str] = None,
        fingerprint_hex: Optional[str] = None,
    ) -> Optional[IntermediateState]:
        """Lookup by state_id, key, or fingerprint (latest match wins)."""
        hit: Optional[IntermediateState] = None
        for st in self.list(task_id):
            if state_id and st.state_id == state_id:
                hit = st
            elif key and st.key == key:
                hit = st
            elif fingerprint_hex and st.fingerprint == fingerprint_hex:
                hit = st
        return hit

    def lookup_key(self, task_id: str, key: str) -> Optional[IntermediateState]:
        return self.get(task_id, key=key)

    def _rewrite(self, task_id: str, states: Sequence[IntermediateState]) -> None:
        path = states_path(self.workdir, task_id)
        # Atomic rewrite of JSONL
        lines = [
            json.dumps(s.to_dict(), default=str, separators=(",", ":"))
            for s in states
        ]
        text = "\n".join(lines) + ("\n" if lines else "")
        from .persist import atomic_write_text

        atomic_write_text(path, text)
        self._refresh_index(task_id)

    def _refresh_index(self, task_id: str) -> dict[str, Any]:
        states = self.list(task_id)
        by_kind: dict[str, int] = {}
        by_surface: dict[str, int] = {}
        for st in states:
            by_kind[st.kind] = by_kind.get(st.kind, 0) + 1
            if st.surface:
                by_surface[st.surface] = by_surface.get(st.surface, 0) + 1
        idx = {
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "task_id": sanitize_task_id(task_id),
            "n_states": len(states),
            "by_kind": by_kind,
            "by_surface": by_surface,
            "updated_at": time.time(),
            "state_ids": [s.state_id for s in states[-50:]],
        }
        atomic_write_json(index_path(self.workdir, task_id), idx)
        return idx

    def index(self, task_id: str) -> dict[str, Any]:
        path = index_path(self.workdir, task_id)
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return self._refresh_index(task_id)

    def clear(self, task_id: str) -> dict[str, Any]:
        tid = sanitize_task_id(task_id)
        d = cache_dir(self.workdir, tid)
        removed = 0
        for p in (states_path(self.workdir, tid), index_path(self.workdir, tid)):
            if p.is_file():
                p.unlink()
                removed += 1
        return {"ok": True, "task_id": tid, "removed_files": removed, "dir": str(d)}

    def stats(self, task_id: Optional[str] = None) -> dict[str, Any]:
        base = cache_dir(self.workdir)
        if task_id:
            idx = self.index(task_id)
            return {
                "schema": SCHEMA,
                "paper": PAPER,
                "path": str(base),
                "task_id": sanitize_task_id(task_id),
                "n_states": idx.get("n_states", 0),
                "by_kind": idx.get("by_kind") or {},
                "by_surface": idx.get("by_surface") or {},
            }
        tasks = []
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if d.is_dir() and (d / "states.jsonl").is_file():
                    tasks.append(d.name)
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "path": str(base),
            "n_tasks": len(tasks),
            "tasks": tasks,
        }


# ── Selective replay ────────────────────────────────────────────────────────


@dataclass
class ReplayPlan:
    """Ordered subset of intermediate states for selective replay."""

    task_id: str
    strategy: str
    states: list[IntermediateState] = field(default_factory=list)
    skipped: int = 0
    filters: dict[str, Any] = field(default_factory=dict)
    schema: str = SCHEMA
    paper: str = PAPER
    source_pattern: str = SOURCE_PATTERN

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "paper": self.paper,
            "source_pattern": self.source_pattern,
            "task_id": self.task_id,
            "strategy": self.strategy,
            "n_states": len(self.states),
            "skipped": self.skipped,
            "filters": dict(self.filters),
            "states": [s.to_dict() for s in self.states],
            "state_ids": [s.state_id for s in self.states],
            "kinds": sorted({s.kind for s in self.states}),
            "surfaces": sorted({s.surface for s in self.states if s.surface}),
        }

    def summary(self) -> dict[str, Any]:
        d = self.to_dict()
        d.pop("states", None)
        return d


def select_replay(
    states: Sequence[IntermediateState | dict[str, Any]],
    *,
    kinds: Optional[Iterable[str]] = None,
    surfaces: Optional[Iterable[str]] = None,
    step_ids: Optional[Iterable[str]] = None,
    from_step: Optional[str] = None,
    to_step: Optional[str] = None,
    max_states: Optional[int] = None,
    strategy: str = STRATEGY_ALL,
    task_id: str = "",
) -> ReplayPlan:
    """Selectively choose intermediate states to replay (SWE-Replay core).

    Filters (all optional, AND-combined):
      - kinds: only these state kinds
      - surfaces: only these marketplace surfaces (agent|skill|command|…)
      - step_ids: exact step allow-list
      - from_step / to_step: inclusive window over first-seen step order
      - max_states: cap after strategy

    Strategies:
      - all: keep filter order
      - latest_per_kind: last state per kind
      - latest_per_surface: last state per surface (falls back to kind)
      - window: same as all but requires from_step/to_step semantics
    """
    strat = str(strategy or STRATEGY_ALL).strip().lower()
    if strat not in STRATEGIES:
        raise StateReplayError(
            f"unknown strategy {strategy!r}; known={sorted(STRATEGIES)}"
        )

    parsed: list[IntermediateState] = []
    for s in states:
        if isinstance(s, IntermediateState):
            parsed.append(s)
        elif isinstance(s, dict):
            try:
                parsed.append(IntermediateState.from_dict(s))
            except StateReplayError:
                continue

    kind_set = {str(k).strip().lower() for k in (kinds or []) if str(k).strip()}
    surf_set = {str(s).strip().lower() for s in (surfaces or []) if str(s).strip()}
    step_set = {str(s).strip() for s in (step_ids or []) if str(s).strip()}

    # Step order for window filter
    step_order: list[str] = []
    for st in parsed:
        sid = st.step_id or ""
        if sid and sid not in step_order:
            step_order.append(sid)

    def _in_window(step_id: str) -> bool:
        if not from_step and not to_step:
            return True
        if not step_id:
            return not from_step  # empty step only if no from bound
        if step_id not in step_order:
            return True
        i = step_order.index(step_id)
        lo = step_order.index(from_step) if from_step and from_step in step_order else 0
        hi = (
            step_order.index(to_step)
            if to_step and to_step in step_order
            else len(step_order) - 1
        )
        if lo > hi:
            lo, hi = hi, lo
        return lo <= i <= hi

    filtered: list[IntermediateState] = []
    skipped = 0
    for st in parsed:
        if kind_set and st.kind not in kind_set:
            skipped += 1
            continue
        if surf_set and (st.surface or st.kind) not in surf_set:
            skipped += 1
            continue
        if step_set and st.step_id not in step_set:
            skipped += 1
            continue
        if not _in_window(st.step_id):
            skipped += 1
            continue
        filtered.append(st)

    selected: list[IntermediateState]
    if strat == STRATEGY_LATEST_PER_KIND:
        latest: dict[str, IntermediateState] = {}
        for st in filtered:
            latest[st.kind] = st
        # Preserve first-seen kind order from filtered
        order: list[str] = []
        for st in filtered:
            if st.kind not in order:
                order.append(st.kind)
        selected = [latest[k] for k in order if k in latest]
    elif strat == STRATEGY_LATEST_PER_SURFACE:
        latest_s: dict[str, IntermediateState] = {}
        for st in filtered:
            key = st.surface or st.kind
            latest_s[key] = st
        order_s: list[str] = []
        for st in filtered:
            key = st.surface or st.kind
            if key not in order_s:
                order_s.append(key)
        selected = [latest_s[k] for k in order_s if k in latest_s]
    else:
        # all | window
        selected = list(filtered)

    if max_states is not None and int(max_states) >= 0:
        cap = int(max_states)
        if len(selected) > cap:
            skipped += len(selected) - cap
            selected = selected[-cap:] if cap else []

    tid = task_id or (parsed[0].task_id if parsed else "")
    return ReplayPlan(
        task_id=tid,
        strategy=strat,
        states=selected,
        skipped=skipped,
        filters={
            "kinds": sorted(kind_set) if kind_set else None,
            "surfaces": sorted(surf_set) if surf_set else None,
            "step_ids": sorted(step_set) if step_set else None,
            "from_step": from_step,
            "to_step": to_step,
            "max_states": max_states,
        },
    )


def build_replay_plan(
    cache: StateCache,
    task_id: str,
    **select_kw: Any,
) -> ReplayPlan:
    """Load task states from *cache* and build a selective ReplayPlan."""
    states = cache.list(task_id)
    return select_replay(states, task_id=task_id, **select_kw)


def get_or_capture(
    cache: StateCache,
    *,
    task_id: str,
    kind: str,
    step_id: str = "",
    surface: str = "",
    name: str = "",
    compute: Optional[Any] = None,
    force: bool = False,
    extra_key: str = "",
    plugin_id: str = "",
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Lookup by logical key; on miss call *compute()* and store (SWE-Replay).

    Returns ``{ok, cache_hit, key, state, result?}``.
    """
    # Provisional key without fingerprint when extra_key provided; else compute first
    if not force and extra_key:
        k = state_key(
            task_id=task_id,
            step_id=step_id,
            kind=normalize_kind(kind),
            surface=normalize_surface(surface)
            or (normalize_kind(kind) if normalize_kind(kind) in MARKETPLACE_SURFACES else ""),
            name=name,
            extra=extra_key,
        )
        hit = cache.lookup_key(task_id, k)
        if hit is not None:
            return {
                "ok": True,
                "cache_hit": True,
                "key": k,
                "state": hit.to_dict(),
                "result": hit.payload,
            }

    if compute is None:
        k_miss = state_key(
            task_id=task_id,
            step_id=step_id,
            kind=normalize_kind(kind),
            surface=surface,
            name=name,
            extra=extra_key or "miss",
        )
        return {
            "ok": False,
            "cache_hit": False,
            "key": k_miss,
            "state": None,
            "result": None,
            "error": "cache_miss_no_compute",
        }

    result = compute()
    payload: dict[str, Any]
    if isinstance(result, dict):
        payload = result
    else:
        payload = {"value": result}

    # If extra_key empty, key includes fingerprint of payload
    st = cache.capture(
        task_id=task_id,
        kind=kind,
        payload=payload,
        step_id=step_id,
        surface=surface,
        name=name,
        plugin_id=plugin_id,
        meta=meta,
        extra_key=extra_key,
    )
    return {
        "ok": True,
        "cache_hit": False,
        "key": st.key,
        "state": st.to_dict(),
        "result": payload,
        "stored": True,
    }


# ── Orchestrator soft hook ──────────────────────────────────────────────────


def maybe_capture_for_task(
    workdir: Optional[Path | str],
    task_id: str,
    meta: Optional[dict[str, Any]],
    *,
    step_id: str = "init",
) -> Optional[dict[str, Any]]:
    """If meta requests state_replay, capture marketplace (+ optional dir).

    Trigger keys on meta:
      - ``state_replay``: truthy
      - ``with_state_replay``: truthy
      - ``capture_marketplace``: truthy (implies state_replay)
      - ``capture_dir``: path string relative to workdir

    Returns a small summary dict or None when disabled.
    """
    if not meta or not isinstance(meta, dict):
        return None
    enabled = bool(
        meta.get("state_replay")
        or meta.get("with_state_replay")
        or meta.get("capture_marketplace")
        or meta.get("capture_dir")
    )
    if not enabled:
        return None

    cache = StateCache.open(workdir)
    captured: list[dict[str, Any]] = []

    if meta.get("capture_marketplace") or meta.get("state_replay") or meta.get(
        "with_state_replay"
    ):
        st = cache.capture_market(task_id, step_id=step_id)
        captured.append(
            {
                "state_id": st.state_id,
                "kind": st.kind,
                "key": st.key,
                "n_components": (st.payload or {}).get("n_components"),
            }
        )

    cap_dir = meta.get("capture_dir")
    if cap_dir:
        root = _root(workdir)
        target = (root / str(cap_dir)).resolve()
        # Jail: must stay under workdir
        try:
            target.relative_to(root)
        except ValueError:
            return {
                "ok": False,
                "error": "capture_dir_outside_workdir",
                "task_id": task_id,
            }
        st = cache.capture_dir(task_id, target, step_id=step_id)
        captured.append(
            {
                "state_id": st.state_id,
                "kind": st.kind,
                "key": st.key,
                "n_entries": (st.payload or {}).get("n_entries"),
            }
        )

    return {
        "ok": True,
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "task_id": sanitize_task_id(task_id),
        "step_id": step_id,
        "n_captured": len(captured),
        "captured": captured,
        "index": cache.index(task_id),
    }


# ── Module CLI ──────────────────────────────────────────────────────────────


def _load_json(path: Optional[str]) -> Any:
    if not path:
        raise StateReplayError("--file required")
    p = Path(path)
    if not p.is_file():
        raise StateReplayError(f"file not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        prog="nexus.state_replay",
        description="SWE-Replay intermediate state cache + selective replay",
    )
    ap.add_argument("--workdir", default=".", help="project workdir")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cap_d = sub.add_parser("capture-dir", help="capture directory listing state")
    p_cap_d.add_argument("--task-id", required=True)
    p_cap_d.add_argument("--path", required=True)
    p_cap_d.add_argument("--step-id", default="")
    p_cap_d.add_argument("--json", action="store_true")

    p_cap_m = sub.add_parser(
        "capture-market", help="capture marketplace catalog (wshobson shape)"
    )
    p_cap_m.add_argument("--task-id", required=True)
    p_cap_m.add_argument("--step-id", default="")
    p_cap_m.add_argument("--plugins-dir", default="plugins")
    p_cap_m.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="list cached states for a task")
    p_list.add_argument("--task-id", required=True)
    p_list.add_argument("--json", action="store_true")

    p_sel = sub.add_parser("select", help="selective replay plan")
    p_sel.add_argument("--task-id", required=True)
    p_sel.add_argument("--kinds", default="", help="comma-separated kinds")
    p_sel.add_argument("--surfaces", default="", help="comma-separated surfaces")
    p_sel.add_argument(
        "--strategy",
        default=STRATEGY_ALL,
        choices=sorted(STRATEGIES),
    )
    p_sel.add_argument("--max-states", type=int, default=None)
    p_sel.add_argument("--from-step", default=None)
    p_sel.add_argument("--to-step", default=None)
    p_sel.add_argument("--json", action="store_true")

    p_stats = sub.add_parser("stats", help="cache stats")
    p_stats.add_argument("--task-id", default=None)
    p_stats.add_argument("--json", action="store_true")

    p_clear = sub.add_parser("clear", help="clear task state cache")
    p_clear.add_argument("--task-id", required=True)
    p_clear.add_argument("--json", action="store_true")

    args = ap.parse_args(list(argv) if argv is not None else None)
    cache = StateCache.open(args.workdir)

    try:
        if args.cmd == "capture-dir":
            st = cache.capture_dir(args.task_id, args.path, step_id=args.step_id)
            if args.json:
                print(json.dumps(st.to_dict(), indent=2, default=str))
            else:
                print(
                    f"ok state_id={st.state_id} kind={st.kind} "
                    f"n={(st.payload or {}).get('n_entries')} key={st.key}"
                )
            return 0

        if args.cmd == "capture-market":
            st = cache.capture_market(
                args.task_id,
                step_id=args.step_id,
                plugins_dir=args.plugins_dir,
            )
            if args.json:
                print(json.dumps(st.to_dict(), indent=2, default=str))
            else:
                print(
                    f"ok state_id={st.state_id} kind={st.kind} "
                    f"plugins={(st.payload or {}).get('n_plugins')} "
                    f"components={(st.payload or {}).get('n_components')}"
                )
            return 0

        if args.cmd == "list":
            states = cache.list(args.task_id)
            if args.json:
                print(
                    json.dumps(
                        {
                            "schema": SCHEMA,
                            "task_id": args.task_id,
                            "n_states": len(states),
                            "states": [s.to_dict() for s in states],
                        },
                        indent=2,
                        default=str,
                    )
                )
            else:
                print(f"task={args.task_id} n_states={len(states)}")
                for s in states:
                    print(
                        f"  [{s.step_id or '-'}] {s.state_id} {s.kind}"
                        f"{'@' + s.surface if s.surface else ''}"
                        f" {s.name or ''}"
                    )
            return 0

        if args.cmd == "select":
            kinds = [x for x in args.kinds.split(",") if x.strip()] or None
            surfaces = [x for x in args.surfaces.split(",") if x.strip()] or None
            plan = build_replay_plan(
                cache,
                args.task_id,
                kinds=kinds,
                surfaces=surfaces,
                strategy=args.strategy,
                max_states=args.max_states,
                from_step=args.from_step,
                to_step=args.to_step,
            )
            if args.json:
                print(json.dumps(plan.to_dict(), indent=2, default=str))
            else:
                s = plan.summary()
                print(
                    f"task={s['task_id']} strategy={s['strategy']} "
                    f"n={s['n_states']} skipped={s['skipped']} "
                    f"kinds={s['kinds']} surfaces={s['surfaces']}"
                )
                for st in plan.states:
                    print(f"  - {st.state_id} {st.kind} step={st.step_id or '-'}")
            return 0

        if args.cmd == "stats":
            st = cache.stats(args.task_id)
            if args.json:
                print(json.dumps(st, indent=2, default=str))
            else:
                print(
                    f"schema={st.get('schema')} path={st.get('path')} "
                    f"tasks={st.get('n_tasks', st.get('task_id'))} "
                    f"states={st.get('n_states', '-')}"
                )
            return 0

        if args.cmd == "clear":
            out = cache.clear(args.task_id)
            if args.json:
                print(json.dumps(out, indent=2))
            else:
                print(f"cleared task={out['task_id']} files={out['removed_files']}")
            return 0

    except StateReplayError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SCHEMA",
    "PAPER",
    "SOURCE_PATTERN",
    "KINDS",
    "MARKETPLACE_SURFACES",
    "STRATEGIES",
    "KIND_DIRECTORY",
    "KIND_KV",
    "KIND_MARKETPLACE",
    "KIND_AGENT",
    "KIND_SKILL",
    "KIND_COMMAND",
    "KIND_OBSERVE",
    "KIND_BLOB",
    "STRATEGY_ALL",
    "STRATEGY_LATEST_PER_KIND",
    "STRATEGY_LATEST_PER_SURFACE",
    "STRATEGY_WINDOW",
    "StateReplayError",
    "IntermediateState",
    "StateCache",
    "ReplayPlan",
    "fingerprint",
    "state_key",
    "normalize_kind",
    "make_state",
    "capture_directory",
    "capture_marketplace",
    "capture_component",
    "select_replay",
    "build_replay_plan",
    "get_or_capture",
    "maybe_capture_for_task",
    "cache_dir",
    "main",
]
