"""Shared verifiable harness state across active agents.

Paper: *Code as Agent Harness* — https://arxiv.org/abs/2605.18747v1

  Multi-agent harnesses need **consistent shared state** and
  **execution-based verification**. This module is a dedicated
  ``HarnessState`` object for the orchestrator: one source of truth for
  which agents are active, what shared keys they wrote, and a stable
  content hash so any peer can verify the view.

GitHub pattern (shape only — not a vendored tree):
  wshobson/agents — single-source Markdown marketplace of plugins with
  agents/*.md, skills/*/SKILL.md, commands/*.md. The catalog seeds the
  active roster (surface + plugin_id) without loading whole plugin bodies.

Novel hybrid (portfolio cross_pattern
``novel:arxiv:2605.18747v1+wshobson/agents``):

  marketplace catalog (agents|skills|commands)
                │
                ▼
         ┌──────────────────┐   ActiveAgent roster + shared KV
         │  HarnessState    │ ──► content_hash / verify
         │  (orchestrator)  │     append-only event seq
         └──────────────────┘
                │
                └── envelope.meta['harness_state'] for workers

Offline-first: pure in-memory + optional dict serde. No network.
Schema: ``nexus.harness_state/v1``

Ownership model (snapshot contract):
  The orchestrator owns the authoritative ``HarnessState``. Workers receive a
  verified snapshot via ``envelope.meta['harness_state']`` (content_hash
  checked on pass-through). Concurrent writers should use ``expected_version``
  CAS on ``put()``; full live multi-writer merge is orchestrator-side work.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

SCHEMA = "nexus.harness_state/v1"
PAPER = "arxiv:2605.18747v1"
PAPER_TITLE = "Code as Agent Harness"
SOURCE_PATTERN = "wshobson/agents"

# Marketplace-aligned surfaces (wshobson shape)
SURFACE_AGENT = "agent"
SURFACE_SKILL = "skill"
SURFACE_COMMAND = "command"
SURFACE_SYSTEM = "system"

SURFACES: frozenset[str] = frozenset(
    {SURFACE_AGENT, SURFACE_SKILL, SURFACE_COMMAND, SURFACE_SYSTEM}
)

# Agent lifecycle
STATUS_ACTIVE = "active"
STATUS_IDLE = "idle"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_LEFT = "left"

STATUSES: frozenset[str] = frozenset(
    {STATUS_ACTIVE, STATUS_IDLE, STATUS_DONE, STATUS_FAILED, STATUS_LEFT}
)

# Event kinds (activity log — not a full authenticated replay chain)
EVT_REGISTER = "register"
EVT_UNREGISTER = "unregister"
EVT_STATUS = "status"
EVT_PUT = "put"
EVT_DELETE = "delete"
EVT_SEED = "seed"

_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._@:+/-]{0,127}$")
_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$")

# Keys reserved for harness bookkeeping (agents cannot overwrite).
# Checked *before* _KEY_RE so callers get code=protected_key (leading `_`
# would otherwise fail the pattern as invalid_key).
PROTECTED_KEYS = frozenset({"_schema", "_hash", "_seq", "_task_id"})


class HarnessError(ValueError):
    """Invalid harness state operation."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "harness_error",
        key: str = "",
        agent: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.key = key
        self.agent = agent

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": type(self).__name__,
            "message": str(self),
            "code": self.code,
            "key": self.key,
            "agent": self.agent,
        }


def _new_id(prefix: str = "hs") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _json_stable(obj: Any) -> str:
    """Canonical JSON for hashing — JSON-native only, no default=str coercion.

    Rejects sets, custom objects, NaN/Inf so content_hash is deterministic
    across processes (no PYTHONHASHSEED / repr address drift).
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def ensure_json_value(value: Any, *, key: str = "") -> Any:
    """Validate + deep-copy a shared value through JSON round-trip.

    Keeps the hash domain closed and prevents mutable alias bypass of
    versioning (caller cannot mutate nested dicts after put).
    """
    try:
        blob = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return json.loads(blob)
    except (TypeError, ValueError) as e:
        raise HarnessError(
            f"non-JSON-serializable value for key {key!r}: {e}",
            code="value_not_json",
            key=key,
        ) from e


def sanitize_agent_id(raw: str) -> str:
    aid = str(raw or "").strip()
    if not aid or not _AGENT_ID_RE.match(aid):
        raise HarnessError(
            f"invalid agent_id: {raw!r}",
            code="invalid_agent_id",
            agent=str(raw or ""),
        )
    if ".." in aid:
        raise HarnessError(
            f"invalid agent_id path chars: {raw!r}",
            code="invalid_agent_id",
            agent=aid,
        )
    return aid


def sanitize_key(raw: str) -> str:
    key = str(raw or "").strip()
    if not key:
        raise HarnessError(
            f"invalid shared key: {raw!r}", code="invalid_key", key=str(raw or "")
        )
    # Reserved / underscore keys before pattern check so callers get protected_key.
    if key in PROTECTED_KEYS or key.startswith("_"):
        raise HarnessError(
            f"protected shared key: {key!r}", code="protected_key", key=key
        )
    if ".." in key:
        raise HarnessError(
            f"invalid shared key path chars: {raw!r}",
            code="invalid_key",
            key=key,
        )
    if not _KEY_RE.match(key):
        raise HarnessError(
            f"invalid shared key: {raw!r}", code="invalid_key", key=key
        )
    return key


# ── data ────────────────────────────────────────────────────────────────────


@dataclass
class ActiveAgent:
    """One agent (or marketplace component) registered in the harness."""

    agent_id: str
    role: str = "agent"
    surface: str = SURFACE_AGENT
    plugin_id: str = ""
    status: str = STATUS_ACTIVE
    privilege: str = "read"
    description: str = ""
    last_seq: int = 0
    registered_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.agent_id = sanitize_agent_id(self.agent_id)
        self.role = str(self.role or "agent").strip() or "agent"
        self.surface = str(self.surface or SURFACE_AGENT).strip().lower()
        if self.surface not in SURFACES:
            raise HarnessError(
                f"unknown surface {self.surface!r}; expected one of {sorted(SURFACES)}",
                code="invalid_surface",
                agent=self.agent_id,
            )
        self.plugin_id = str(self.plugin_id or "").strip()
        self.status = str(self.status or STATUS_ACTIVE).strip().lower()
        if self.status not in STATUSES:
            raise HarnessError(
                f"unknown status {self.status!r}; expected one of {sorted(STATUSES)}",
                code="invalid_status",
                agent=self.agent_id,
            )
        self.privilege = str(self.privilege or "read").strip().lower() or "read"
        self.description = str(self.description or "")
        if not isinstance(self.meta, dict):
            self.meta = {}

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE

    @property
    def catalog_id(self) -> str:
        """Marketplace-style id: ``surface:name@plugin`` (plugin optional)."""
        if self.plugin_id:
            return f"{self.surface}:{self.agent_id}@{self.plugin_id}"
        return f"{self.surface}:{self.agent_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "surface": self.surface,
            "plugin_id": self.plugin_id,
            "status": self.status,
            "privilege": self.privilege,
            "description": self.description,
            "last_seq": int(self.last_seq),
            "registered_at": float(self.registered_at),
            "updated_at": float(self.updated_at),
            "meta": dict(self.meta or {}),
            "catalog_id": self.catalog_id,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "ActiveAgent":
        if not isinstance(d, dict):
            raise HarnessError(
                f"agent must be a dict, got {type(d).__name__}",
                code="invalid_agent",
            )
        return cls(
            agent_id=str(d.get("agent_id") or d.get("id") or d.get("name") or ""),
            role=str(d.get("role") or "agent"),
            surface=str(d.get("surface") or SURFACE_AGENT),
            plugin_id=str(d.get("plugin_id") or d.get("plugin") or ""),
            status=str(d.get("status") or STATUS_ACTIVE),
            privilege=str(d.get("privilege") or "read"),
            description=str(d.get("description") or d.get("desc") or ""),
            last_seq=int(d.get("last_seq") or 0),
            registered_at=float(d.get("registered_at") or time.time()),
            updated_at=float(d.get("updated_at") or time.time()),
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
        )


@dataclass
class SharedValue:
    """One versioned shared key in the harness state blob."""

    key: str
    value: Any = None
    version: int = 1
    writer: str = ""
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.key = sanitize_key(self.key)
        self.version = max(1, int(self.version or 1))
        self.writer = str(self.writer or "").strip()
        self.updated_at = float(self.updated_at or time.time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "version": int(self.version),
            "writer": self.writer,
            "updated_at": float(self.updated_at),
        }

    @classmethod
    def from_dict(cls, d: Any) -> "SharedValue":
        if not isinstance(d, dict):
            raise HarnessError(
                f"shared value must be a dict, got {type(d).__name__}",
                code="invalid_value",
            )
        return cls(
            key=str(d.get("key") or ""),
            value=d.get("value"),
            version=int(d.get("version") or 1),
            writer=str(d.get("writer") or ""),
            updated_at=float(d.get("updated_at") or time.time()),
        )


@dataclass
class HarnessEvent:
    """Append-only mutation record for verify/replay."""

    seq: int
    kind: str
    agent: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": int(self.seq),
            "kind": self.kind,
            "agent": self.agent,
            "detail": dict(self.detail or {}),
            "ts": float(self.ts),
        }

    @classmethod
    def from_dict(cls, d: Any) -> "HarnessEvent":
        if not isinstance(d, dict):
            raise HarnessError("event must be a dict", code="invalid_event")
        return cls(
            seq=int(d.get("seq") or 0),
            kind=str(d.get("kind") or ""),
            agent=str(d.get("agent") or ""),
            detail=dict(d.get("detail") or {})
            if isinstance(d.get("detail"), dict)
            else {},
            ts=float(d.get("ts") or time.time()),
        )


# ── HarnessState ────────────────────────────────────────────────────────────


@dataclass
class HarnessState:
    """Shared, verifiable multi-agent harness state (orchestrator-owned).

    Tracks:
    - **active agents** (roster with marketplace surface/plugin)
    - **shared KV** (versioned values with writer attribution)
    - **event log** (append-only seq for audit/verify)
    - **content_hash** (stable SHA-256 over roster + shared values)

    Zero network; serializable via ``to_dict`` / ``from_dict`` for envelope meta.
    """

    task_id: str = ""
    agents: dict[str, ActiveAgent] = field(default_factory=dict)
    shared: dict[str, SharedValue] = field(default_factory=dict)
    events: list[HarnessEvent] = field(default_factory=list)
    seq: int = 0
    schema: str = SCHEMA
    paper: str = PAPER
    source_pattern: str = SOURCE_PATTERN
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)
    # Cap event history retained in memory / meta (tail); always ≥ 1
    max_events: int = 200
    # Monotonic per-key version counters (survive delete so re-put does not reset)
    key_versions: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            self.max_events = max(1, int(self.max_events))
        except (TypeError, ValueError):
            self.max_events = 200
        if not isinstance(self.key_versions, dict):
            self.key_versions = {}
        else:
            cleaned: dict[str, int] = {}
            for k, v in self.key_versions.items():
                try:
                    cleaned[str(k)] = max(0, int(v))
                except (TypeError, ValueError):
                    continue
            self.key_versions = cleaned

    # ── factories ───────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        task_id: str = "",
        *,
        agents: Optional[Iterable[str | dict[str, Any] | ActiveAgent]] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> "HarnessState":
        """Create empty harness state and optionally register agents."""
        hs = cls(
            task_id=str(task_id or "").strip(),
            meta=dict(meta or {}) if meta else {},
        )
        if agents is not None:
            for a in agents:
                hs.register(a)
        return hs

    # ── agents ──────────────────────────────────────────────────────────

    def register(
        self,
        agent: str | dict[str, Any] | ActiveAgent,
        *,
        role: Optional[str] = None,
        surface: Optional[str] = None,
        plugin_id: Optional[str] = None,
        privilege: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> ActiveAgent:
        """Register or re-activate an agent on the harness roster.

        Bare-string re-register **merges**: keeps existing role/surface/plugin/
        privilege/description/meta unless the caller explicitly overrides them.
        Default status on re-activate is ``active`` (re-activation).
        """
        changed: dict[str, Any] = {}
        if isinstance(agent, ActiveAgent):
            ag = agent
            existing = self.agents.get(ag.agent_id)
        elif isinstance(agent, dict):
            ag = ActiveAgent.from_dict(agent)
            existing = self.agents.get(ag.agent_id)
        else:
            aid = sanitize_agent_id(str(agent))
            existing = self.agents.get(aid)
            if existing is not None:
                # Merge: only override fields the caller explicitly passed
                new_role = existing.role if role is None else str(role or "agent")
                new_surface = (
                    existing.surface if surface is None else str(surface or SURFACE_AGENT)
                )
                new_plugin = (
                    existing.plugin_id if plugin_id is None else str(plugin_id or "")
                )
                new_priv = (
                    existing.privilege if privilege is None else str(privilege or "read")
                )
                new_desc = (
                    existing.description
                    if description is None
                    else str(description or "")
                )
                new_status = STATUS_ACTIVE if status is None else str(status or STATUS_ACTIVE)
                new_meta = (
                    dict(existing.meta or {})
                    if meta is None
                    else {**(existing.meta or {}), **dict(meta)}
                )
                if new_role != existing.role:
                    changed["role"] = {"from": existing.role, "to": new_role}
                if new_surface != existing.surface:
                    changed["surface"] = {"from": existing.surface, "to": new_surface}
                if new_plugin != existing.plugin_id:
                    changed["plugin_id"] = {"from": existing.plugin_id, "to": new_plugin}
                if new_priv != existing.privilege:
                    changed["privilege"] = {
                        "from": existing.privilege,
                        "to": new_priv,
                    }
                if new_status != existing.status:
                    changed["status"] = {"from": existing.status, "to": new_status}
                ag = ActiveAgent(
                    agent_id=aid,
                    role=new_role,
                    surface=new_surface,
                    plugin_id=new_plugin,
                    privilege=new_priv,
                    description=new_desc,
                    status=new_status,
                    meta=new_meta,
                    last_seq=existing.last_seq,
                    registered_at=existing.registered_at,
                )
            else:
                ag = ActiveAgent(
                    agent_id=aid,
                    role=role if role is not None else "agent",
                    surface=surface if surface is not None else SURFACE_AGENT,
                    plugin_id=plugin_id if plugin_id is not None else "",
                    privilege=privilege if privilege is not None else "read",
                    description=description if description is not None else "",
                    status=status if status is not None else STATUS_ACTIVE,
                    meta=dict(meta or {}) if meta else {},
                )
        if existing is not None and not isinstance(agent, str):
            # ActiveAgent / dict path: preserve registered_at / last_seq
            ag.registered_at = existing.registered_at
            ag.last_seq = existing.last_seq
            if existing.privilege != ag.privilege:
                changed["privilege"] = {
                    "from": existing.privilege,
                    "to": ag.privilege,
                }
            if existing.role != ag.role:
                changed["role"] = {"from": existing.role, "to": ag.role}
            if existing.status != ag.status:
                changed["status"] = {"from": existing.status, "to": ag.status}
        now = time.time()
        ag.updated_at = now
        self.agents[ag.agent_id] = ag
        detail: dict[str, Any] = {
            "status": ag.status,
            "surface": ag.surface,
            "plugin_id": ag.plugin_id,
            "role": ag.role,
            "privilege": ag.privilege,
            "rebind": existing is not None,
        }
        if changed:
            detail["changed"] = changed
        self._emit(
            EVT_REGISTER if existing is None else EVT_STATUS,
            agent=ag.agent_id,
            detail=detail,
        )
        return ag

    def unregister(self, agent_id: str, *, reason: str = "") -> ActiveAgent:
        """Mark agent as left (keeps roster entry for audit)."""
        aid = sanitize_agent_id(agent_id)
        ag = self.agents.get(aid)
        if ag is None:
            raise HarnessError(
                f"agent not registered: {aid}",
                code="unknown_agent",
                agent=aid,
            )
        ag.status = STATUS_LEFT
        ag.updated_at = time.time()
        self._emit(
            EVT_UNREGISTER,
            agent=aid,
            detail={"reason": str(reason or ""), "status": STATUS_LEFT},
        )
        return ag

    def set_status(self, agent_id: str, status: str) -> ActiveAgent:
        aid = sanitize_agent_id(agent_id)
        ag = self.require_agent(aid)
        st = str(status or "").strip().lower()
        if st not in STATUSES:
            raise HarnessError(
                f"unknown status {status!r}",
                code="invalid_status",
                agent=aid,
            )
        prev = ag.status
        ag.status = st
        ag.updated_at = time.time()
        self._emit(
            EVT_STATUS,
            agent=aid,
            detail={"from": prev, "to": st},
        )
        return ag

    def require_agent(self, agent_id: str) -> ActiveAgent:
        aid = sanitize_agent_id(agent_id)
        ag = self.agents.get(aid)
        if ag is None:
            raise HarnessError(
                f"agent not registered: {aid}",
                code="unknown_agent",
                agent=aid,
            )
        return ag

    def active_agents(self) -> list[ActiveAgent]:
        return [a for a in self.agents.values() if a.is_active]

    def active_ids(self) -> list[str]:
        return sorted(a.agent_id for a in self.active_agents())

    # ── shared KV ───────────────────────────────────────────────────────

    def put(
        self,
        key: str,
        value: Any,
        *,
        agent: str,
        require_active: bool = True,
        expected_version: Optional[int] = None,
    ) -> SharedValue:
        """Write a shared key; writer must be a registered (active) agent.

        Values must be JSON-serializable (closed hash domain). Nested
        structures are deep-copied via JSON round-trip.

        Optimistic concurrency: pass ``expected_version`` (current version,
        or 0 if the key is absent) to fail with ``version_conflict`` on
        concurrent writers. Versions are monotonic per key across delete/re-put.
        """
        k = sanitize_key(key)
        aid = sanitize_agent_id(agent)
        ag = self.require_agent(aid)
        if require_active and not ag.is_active:
            raise HarnessError(
                f"agent {aid} is not active (status={ag.status})",
                code="agent_not_active",
                agent=aid,
                key=k,
            )
        safe_value = ensure_json_value(value, key=k)
        now = time.time()
        prev = self.shared.get(k)
        current_v = (
            int(prev.version)
            if prev is not None
            else int(self.key_versions.get(k, 0))
        )
        if expected_version is not None and int(expected_version) != current_v:
            raise HarnessError(
                f"version conflict for {k!r}: expected={expected_version} "
                f"current={current_v}",
                code="version_conflict",
                key=k,
                agent=aid,
            )
        version = current_v + 1
        self.key_versions[k] = version
        entry = SharedValue(
            key=k, value=safe_value, version=version, writer=aid, updated_at=now
        )
        self.shared[k] = entry
        self._emit(
            EVT_PUT,
            agent=aid,
            detail={
                "key": k,
                "version": version,
                "had_prev": prev is not None,
                "expected_version": expected_version,
            },
        )
        return entry

    def get(self, key: str, default: Any = None) -> Any:
        k = sanitize_key(key)
        entry = self.shared.get(k)
        if entry is None:
            return default
        # Defensive copy so callers cannot mutate shared state by alias
        try:
            return ensure_json_value(entry.value, key=k)
        except HarnessError:
            return entry.value

    def get_entry(self, key: str) -> Optional[SharedValue]:
        k = sanitize_key(key)
        return self.shared.get(k)

    def delete(self, key: str, *, agent: str, require_active: bool = True) -> bool:
        k = sanitize_key(key)
        aid = sanitize_agent_id(agent)
        ag = self.require_agent(aid)
        if require_active and not ag.is_active:
            raise HarnessError(
                f"agent {aid} is not active (status={ag.status})",
                code="agent_not_active",
                agent=aid,
                key=k,
            )
        if k not in self.shared:
            return False
        prev_v = int(self.shared[k].version)
        # Keep monotonic counter (tombstone version) for CAS after re-put
        self.key_versions[k] = max(int(self.key_versions.get(k, 0)), prev_v)
        del self.shared[k]
        self._emit(
            EVT_DELETE,
            agent=aid,
            detail={"key": k, "tombstone_version": self.key_versions[k]},
        )
        return True

    def shared_view(self) -> dict[str, Any]:
        """Plain dict of key → current value (for agent prompts)."""
        out: dict[str, Any] = {}
        for k, v in sorted(self.shared.items()):
            try:
                out[k] = ensure_json_value(v.value, key=k)
            except HarnessError:
                out[k] = v.value
        return out

    # ── verify ──────────────────────────────────────────────────────────

    def content_hash(self) -> str:
        """Stable SHA-256 over active roster + shared values (verifiable view)."""
        payload = {
            "schema": self.schema,
            "task_id": self.task_id,
            "agents": {
                aid: {
                    "agent_id": a.agent_id,
                    "role": a.role,
                    "surface": a.surface,
                    "plugin_id": a.plugin_id,
                    "status": a.status,
                    "privilege": a.privilege,
                }
                for aid, a in sorted(self.agents.items())
            },
            "shared": {
                k: {
                    "key": v.key,
                    "value": v.value,
                    "version": v.version,
                    "writer": v.writer,
                }
                for k, v in sorted(self.shared.items())
            },
            "seq": int(self.seq),
        }
        blob = _json_stable(payload).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def verify(
        self,
        *,
        expected_hash: Optional[str] = None,
        check_events: bool = True,
        check_writers: bool = True,
    ) -> dict[str, Any]:
        """Verify internal consistency of the harness state.

        Checks:
        - event seq is contiguous 1..N (when check_events)
        - every shared writer is (or was) on the roster (when check_writers)
        - recomputed content_hash matches expected_hash when provided
        - active agents have valid surfaces/statuses

        Returns a report dict with ``ok`` bool and ``issues`` list.
        """
        issues: list[str] = []
        if int(self.seq) < 0:
            issues.append("negative_seq")
        if check_events and self.events:
            # events may be tail-truncated; only check relative continuity
            for i, ev in enumerate(self.events):
                if i == 0:
                    continue
                prev = self.events[i - 1]
                if int(ev.seq) != int(prev.seq) + 1:
                    issues.append(
                        f"event_seq_gap: seq {prev.seq} → {ev.seq} at index {i}"
                    )
            if int(self.events[-1].seq) > int(self.seq):
                issues.append(
                    f"seq_behind_events: state.seq={self.seq} "
                    f"last_event={self.events[-1].seq}"
                )

        if check_writers:
            known = set(self.agents.keys())
            for k, entry in self.shared.items():
                if entry.writer and entry.writer not in known:
                    issues.append(
                        f"orphan_writer: key={k!r} writer={entry.writer!r}"
                    )

        for aid, ag in self.agents.items():
            if ag.surface not in SURFACES:
                issues.append(f"bad_surface: agent={aid} surface={ag.surface}")
            if ag.status not in STATUSES:
                issues.append(f"bad_status: agent={aid} status={ag.status}")

        drops = int((self.meta or {}).get("deserialization_drops") or 0)
        if drops > 0:
            issues.append(f"deserialization_drops: {drops}")

        digest = self.content_hash()
        if expected_hash is not None:
            exp = str(expected_hash).strip().lower()
            if exp and exp != digest:
                issues.append(
                    f"hash_mismatch: expected={exp[:16]}… got={digest[:16]}…"
                )

        ok = len(issues) == 0
        # Pure check — does not mutate state or bump seq (hash stays stable)
        report = {
            "ok": ok,
            "schema": self.schema,
            "paper": self.paper,
            "task_id": self.task_id,
            "content_hash": digest,
            "n_agents": len(self.agents),
            "n_active": len(self.active_agents()),
            "n_shared": len(self.shared),
            "n_events": len(self.events),
            "seq": int(self.seq),
            "issues": issues,
        }
        return report

    def assert_verified(self, *, expected_hash: Optional[str] = None) -> str:
        """Raise HarnessError if verify fails; return content_hash on success."""
        report = self.verify(expected_hash=expected_hash)
        if not report["ok"]:
            raise HarnessError(
                f"harness verify failed: {report['issues'][:3]}",
                code="verify_failed",
            )
        return str(report["content_hash"])

    # ── marketplace seed (wshobson shape) ────────────────────────────────

    def seed_from_marketplace(
        self,
        workdir: Optional[Path | str] = None,
        *,
        plugins_dir: str = "plugins",
        surfaces: Optional[Sequence[str]] = None,
        max_agents: int = 64,
        status: str = STATUS_IDLE,
    ) -> dict[str, Any]:
        """Seed roster from local Markdown marketplace catalog (shape only).

        Uses in-tree ``marketplace.list_plugins`` — does not vendor wshobson.
        Agents default to ``idle`` so orchestrator can activate a subset.
        """
        want = set(surfaces or (SURFACE_AGENT, SURFACE_SKILL, SURFACE_COMMAND))
        want &= SURFACES
        registered: list[str] = []
        root = Path(workdir).resolve() if workdir is not None else None
        try:
            from . import marketplace as mp
        except Exception as e:
            return {
                "ok": False,
                "error": f"marketplace_import: {e}",
                "registered": [],
            }

        try:
            if root is not None:
                rows = mp.list_plugins(root, plugins_dir=plugins_dir, validate=False)
            else:
                rows = mp.list_plugins(Path.cwd(), plugins_dir=plugins_dir, validate=False)
        except TypeError:
            # Older list_plugins may not take plugins_dir
            try:
                rows = mp.list_plugins(root or Path.cwd(), validate=False)
            except Exception as e:
                return {"ok": False, "error": str(e)[:300], "registered": []}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300], "registered": []}

        for row in rows or []:
            if len(registered) >= max_agents:
                break
            plugin_id = str(
                getattr(row, "id", None)
                or getattr(row, "name", None)
                or (row.get("id") if isinstance(row, dict) else "")
                or ""
            ).strip()
            privilege = str(
                getattr(row, "privilege", None)
                or (row.get("privilege") if isinstance(row, dict) else None)
                or "read"
            )

            def _names(attr: str) -> list[str]:
                raw = getattr(row, attr, None)
                if raw is None and isinstance(row, dict):
                    raw = row.get(attr)
                if not raw:
                    return []
                out: list[str] = []
                for item in raw:
                    if isinstance(item, str):
                        out.append(item)
                    elif isinstance(item, dict):
                        n = str(item.get("name") or item.get("id") or "").strip()
                        if n:
                            out.append(n)
                    else:
                        n = str(getattr(item, "name", None) or getattr(item, "id", "") or "").strip()
                        if n:
                            out.append(n)
                return out

            catalog: list[tuple[str, str]] = []
            if SURFACE_AGENT in want:
                for n in _names("agents"):
                    catalog.append((SURFACE_AGENT, n))
            if SURFACE_SKILL in want:
                for n in _names("skills"):
                    catalog.append((SURFACE_SKILL, n))
            if SURFACE_COMMAND in want:
                for n in _names("commands"):
                    catalog.append((SURFACE_COMMAND, n))

            for surface, name in catalog:
                if len(registered) >= max_agents:
                    break
                # Unique agent_id: prefer bare name; disambiguate on plugin
                # *or* surface (wshobson plugins reuse names across surfaces).
                aid = name
                if aid in self.agents and (
                    self.agents[aid].plugin_id != plugin_id
                    or self.agents[aid].surface != surface
                ):
                    if self.agents[aid].plugin_id != plugin_id and plugin_id:
                        aid = f"{name}@{plugin_id}"
                    else:
                        aid = f"{name}+{surface}"
                    # Still colliding (e.g. same name@plugin different surface)
                    if aid in self.agents and (
                        self.agents[aid].plugin_id != plugin_id
                        or self.agents[aid].surface != surface
                    ):
                        aid = (
                            f"{name}+{surface}@{plugin_id}"
                            if plugin_id
                            else f"{name}+{surface}"
                        )
                try:
                    self.register(
                        aid,
                        role=surface,
                        surface=surface,
                        plugin_id=plugin_id,
                        privilege=privilege,
                        description=f"marketplace {surface} from {plugin_id or 'local'}",
                        status=status,
                        meta={"seeded_from": "marketplace", "source_name": name},
                    )
                    registered.append(aid)
                except HarnessError:
                    continue

        self._emit(
            EVT_SEED,
            agent="system",
            detail={
                "source": "marketplace",
                "n_registered": len(registered),
                "plugins_dir": plugins_dir,
            },
        )
        # system agent is not on roster unless registered — emit only
        return {
            "ok": True,
            "n_registered": len(registered),
            "registered": registered,
            "source_pattern": SOURCE_PATTERN,
        }

    # ── serde / snapshot ────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Operator-facing view (includes content_hash + active list)."""
        return {
            "schema": self.schema,
            "paper": self.paper,
            "source_pattern": self.source_pattern,
            "task_id": self.task_id,
            "content_hash": self.content_hash(),
            "seq": int(self.seq),
            "n_agents": len(self.agents),
            "n_active": len(self.active_agents()),
            "n_shared": len(self.shared),
            "n_events": len(self.events),
            "active_ids": self.active_ids(),
            "agents": {k: v.to_dict() for k, v in sorted(self.agents.items())},
            "shared": {k: v.to_dict() for k, v in sorted(self.shared.items())},
            "shared_view": self.shared_view(),
            "created_at": float(self.created_at),
            "updated_at": float(self.updated_at),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "paper": self.paper,
            "source_pattern": self.source_pattern,
            "task_id": self.task_id,
            "seq": int(self.seq),
            "content_hash": self.content_hash(),
            "agents": {k: v.to_dict() for k, v in self.agents.items()},
            "shared": {k: v.to_dict() for k, v in self.shared.items()},
            "events": [e.to_dict() for e in self.events],
            "created_at": float(self.created_at),
            "updated_at": float(self.updated_at),
            "meta": dict(self.meta or {}),
            "max_events": int(self.max_events),
            "key_versions": {k: int(v) for k, v in sorted(self.key_versions.items())},
        }

    def to_meta(self) -> dict[str, Any]:
        """Compact form for envelope.meta (tail events only)."""
        d = self.to_dict()
        # Keep last 40 events in meta to bound size
        if len(d["events"]) > 40:
            d["events"] = d["events"][-40:]
            d["events_truncated"] = True
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "HarnessState":
        if not isinstance(d, dict):
            raise HarnessError(
                f"harness_state must be a dict, got {type(d).__name__}",
                code="invalid_state",
            )
        drops = 0
        agents: dict[str, ActiveAgent] = {}
        raw_agents = d.get("agents") or {}
        if isinstance(raw_agents, dict):
            for k, v in raw_agents.items():
                try:
                    ag = ActiveAgent.from_dict(v if isinstance(v, dict) else {"agent_id": k})
                    agents[ag.agent_id] = ag
                except HarnessError:
                    drops += 1
                    continue
        elif isinstance(raw_agents, list):
            for item in raw_agents:
                try:
                    ag = ActiveAgent.from_dict(
                        item if isinstance(item, dict) else {"agent_id": str(item)}
                    )
                    agents[ag.agent_id] = ag
                except HarnessError:
                    drops += 1
                    continue

        shared: dict[str, SharedValue] = {}
        raw_shared = d.get("shared") or {}
        if isinstance(raw_shared, dict):
            for k, v in raw_shared.items():
                try:
                    if isinstance(v, dict):
                        entry = SharedValue.from_dict({**v, "key": v.get("key") or k})
                    else:
                        entry = SharedValue(key=str(k), value=v)
                    # Normalize value into JSON domain when possible
                    try:
                        entry.value = ensure_json_value(entry.value, key=entry.key)
                    except HarnessError:
                        drops += 1
                        continue
                    shared[entry.key] = entry
                except HarnessError:
                    drops += 1
                    continue

        events: list[HarnessEvent] = []
        for raw in d.get("events") or []:
            try:
                events.append(HarnessEvent.from_dict(raw))
            except HarnessError:
                drops += 1
                continue

        key_versions: dict[str, int] = {}
        raw_kv = d.get("key_versions") or {}
        if isinstance(raw_kv, dict):
            for k, v in raw_kv.items():
                try:
                    key_versions[str(k)] = max(0, int(v))
                except (TypeError, ValueError):
                    drops += 1
        # Ensure counters cover live shared entries
        for k, entry in shared.items():
            key_versions[k] = max(int(key_versions.get(k, 0)), int(entry.version))

        meta = dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {}
        if drops > 0:
            meta["deserialization_drops"] = int(meta.get("deserialization_drops") or 0) + drops

        try:
            max_events = max(1, int(d.get("max_events") or 200))
        except (TypeError, ValueError):
            max_events = 200

        return cls(
            task_id=str(d.get("task_id") or ""),
            agents=agents,
            shared=shared,
            events=events,
            seq=int(d.get("seq") or (events[-1].seq if events else 0)),
            schema=str(d.get("schema") or SCHEMA),
            paper=str(d.get("paper") or PAPER),
            source_pattern=str(d.get("source_pattern") or SOURCE_PATTERN),
            created_at=float(d.get("created_at") or time.time()),
            updated_at=float(d.get("updated_at") or time.time()),
            meta=meta,
            max_events=max_events,
            key_versions=key_versions,
        )

    # ── internals ───────────────────────────────────────────────────────

    def _emit(self, kind: str, *, agent: str = "", detail: Optional[dict[str, Any]] = None) -> HarnessEvent:
        self.seq = int(self.seq) + 1
        ev = HarnessEvent(
            seq=self.seq,
            kind=str(kind),
            agent=str(agent or ""),
            detail=dict(detail or {}),
            ts=time.time(),
        )
        self.events.append(ev)
        cap = max(1, int(self.max_events))
        if len(self.events) > cap:
            self.events = self.events[-cap:]
        self.updated_at = ev.ts
        if agent and agent in self.agents:
            self.agents[agent].last_seq = self.seq
            self.agents[agent].updated_at = ev.ts
        return ev


# ── orchestrator helpers ────────────────────────────────────────────────────


def default_pipeline_agents() -> list[str]:
    """Canonical NEXUS multi-agent roster for harness planning."""
    return [
        "planner",
        "adversary",
        "implementer",
        "tester",
        "reviewer",
        "logger",
    ]


def plan_for_orchestrator(
    *,
    task_id: str = "",
    agents: Optional[Iterable[str | dict[str, Any]]] = None,
    seed_marketplace: bool = False,
    workdir: Optional[Path | str] = None,
    shared: Optional[dict[str, Any]] = None,
    meta: Optional[dict[str, Any]] = None,
) -> HarnessState:
    """Build a HarnessState for orchestrator envelope.meta."""
    roster: list[str | dict[str, Any]]
    if agents is not None:
        roster = list(agents)
    else:
        roster = list(default_pipeline_agents())
    hs = HarnessState.create(
        task_id=task_id,
        agents=roster,
        meta={**(meta or {}), "source": "orchestrator"},
    )
    if seed_marketplace:
        seed_report = hs.seed_from_marketplace(workdir)
        hs.meta["marketplace_seed"] = seed_report
        hs.meta["seeded_marketplace"] = bool(seed_report.get("ok"))
        if not seed_report.get("ok"):
            hs.meta["marketplace_seed_failed"] = True
    if shared and isinstance(shared, dict):
        # Bootstrap shared keys under a system-registered writer
        if "orchestrator" not in hs.agents:
            hs.register(
                "orchestrator",
                role="system",
                surface=SURFACE_SYSTEM,
                privilege="admin",
                description="orchestrator bootstrap writer",
            )
        bootstrap_drops = 0
        for k, v in shared.items():
            try:
                hs.put(str(k), v, agent="orchestrator")
            except HarnessError:
                bootstrap_drops += 1
                continue
        if bootstrap_drops:
            hs.meta["shared_bootstrap_drops"] = bootstrap_drops
    return hs


def maybe_init_for_task(
    workdir: Optional[Path | str],
    task_id: str,
    meta: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """If meta requests harness_state, build and return summary + full state.

    Trigger keys on meta:
      - ``harness_state``: ``True`` (build fresh) or a planned dict with ``agents``
      - ``with_harness_state``: truthy
      - ``enable_harness_state``: truthy

    Unrecognized truthy ``harness_state`` values (e.g. ``1``, ``"yes"``) return
    an explicit ``ok=False`` error rather than silently disabling.

    Optional:
      - ``harness_agents``: list of agent ids / dicts
      - ``harness_from_marketplace``: seed marketplace roster
      - ``harness_shared``: initial shared KV dict
      - ``harness_pipeline``: use default_pipeline_agents when no harness_agents

    Returns summary dict (with ``state`` full payload) or None when disabled.
    """
    if not meta or not isinstance(meta, dict):
        return None
    raw_existing = meta.get("harness_state")
    flag_enabled = bool(
        meta.get("with_harness_state") or meta.get("enable_harness_state")
    )
    planned = isinstance(raw_existing, dict) and raw_existing.get("agents") is not None
    build_fresh = raw_existing is True

    # Unrecognized harness_state payload → explicit error (not silent no-op)
    if (
        "harness_state" in meta
        and raw_existing is not None
        and raw_existing is not False
        and not planned
        and not build_fresh
        and not isinstance(raw_existing, dict)
    ):
        return {
            "ok": False,
            "error": "unrecognized harness_state value "
            f"(type={type(raw_existing).__name__}); "
            "use True or a planned dict with 'agents'",
            "schema": SCHEMA,
            "paper": PAPER,
            "task_id": str(task_id or ""),
        }

    enabled = flag_enabled or planned or build_fresh
    # Dict without agents alone does not enable unless flags set
    if not enabled:
        return None

    # Pass-through already planned state — verify embedded content_hash
    if planned:
        try:
            hs = HarnessState.from_dict(raw_existing)
            if task_id and not hs.task_id:
                hs.task_id = str(task_id)
            embedded = str(raw_existing.get("content_hash") or "") or None
            report = hs.verify(expected_hash=embedded)
            return {
                "ok": report["ok"],
                "schema": SCHEMA,
                "paper": PAPER,
                "source_pattern": SOURCE_PATTERN,
                "task_id": hs.task_id or str(task_id or ""),
                "content_hash": report["content_hash"],
                "n_agents": report["n_agents"],
                "n_active": report["n_active"],
                "n_shared": report["n_shared"],
                "active_ids": hs.active_ids(),
                "verify_ok": report["ok"],
                "issues": report["issues"],
                "state": hs.to_meta(),
                "brief": format_brief(hs),
                "expected_hash_checked": embedded is not None,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"{type(e).__name__}: {e}"[:400],
                "schema": SCHEMA,
                "paper": PAPER,
                "task_id": str(task_id or ""),
            }

    agents = meta.get("harness_agents")
    if agents is None and meta.get("harness_pipeline", True):
        agents = default_pipeline_agents()
    seed_mkt = bool(meta.get("harness_from_marketplace"))
    shared = meta.get("harness_shared") if isinstance(meta.get("harness_shared"), dict) else None

    try:
        hs = plan_for_orchestrator(
            task_id=str(task_id or ""),
            agents=agents,
            seed_marketplace=seed_mkt,
            workdir=workdir,
            shared=shared,
            meta={"trigger": "maybe_init_for_task"},
        )
        report = hs.verify()
        seed_meta = (hs.meta or {}).get("marketplace_seed")
        return {
            "ok": True,
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "task_id": hs.task_id,
            "content_hash": report["content_hash"],
            "n_agents": report["n_agents"],
            "n_active": report["n_active"],
            "n_shared": report["n_shared"],
            "active_ids": hs.active_ids(),
            "verify_ok": report["ok"],
            "issues": report["issues"],
            "state": hs.to_meta(),
            "brief": format_brief(hs),
            "seeded_marketplace": seed_mkt,
            "marketplace_seed": seed_meta,
            "marketplace_seed_ok": (
                bool(seed_meta.get("ok")) if isinstance(seed_meta, dict) else None
            ),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}"[:400],
            "schema": SCHEMA,
            "paper": PAPER,
            "task_id": str(task_id or ""),
        }


def format_brief(hs: HarnessState) -> str:
    """One-screen operator brief of harness state."""
    snap = hs.snapshot()
    lines = [
        f"harness state ({snap['schema']}) paper={snap['paper']}",
        f"  task={snap['task_id'] or '-'} seq={snap['seq']} "
        f"active={snap['n_active']}/{snap['n_agents']} shared={snap['n_shared']}",
        f"  hash={snap['content_hash'][:16]}… pattern={snap['source_pattern']}",
    ]
    for aid in snap["active_ids"][:12]:
        a = snap["agents"].get(aid) or {}
        lines.append(
            f"  - {aid}: {a.get('surface', '?')}"
            f"{'@' + a['plugin_id'] if a.get('plugin_id') else ''}"
            f" role={a.get('role')} status={a.get('status')}"
        )
    if snap["n_active"] > 12:
        lines.append(f"  … +{snap['n_active'] - 12} more active")
    for k, entry in list(sorted(snap["shared"].items()))[:8]:
        lines.append(
            f"  kv {k}=v{entry.get('version')} writer={entry.get('writer')}"
        )
    return "\n".join(lines)


__all__ = [
    "SCHEMA",
    "PAPER",
    "PAPER_TITLE",
    "SOURCE_PATTERN",
    "SURFACES",
    "STATUSES",
    "SURFACE_AGENT",
    "SURFACE_SKILL",
    "SURFACE_COMMAND",
    "SURFACE_SYSTEM",
    "STATUS_ACTIVE",
    "STATUS_IDLE",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_LEFT",
    "HarnessError",
    "ActiveAgent",
    "SharedValue",
    "HarnessEvent",
    "HarnessState",
    "default_pipeline_agents",
    "plan_for_orchestrator",
    "maybe_init_for_task",
    "format_brief",
    "sanitize_agent_id",
    "sanitize_key",
    "ensure_json_value",
]
