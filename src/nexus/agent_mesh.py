"""In-process event-driven agent mesh (SolaceLabs/solace-agent-mesh shape).

Portable patterns only — **no Solace broker, no Google ADK, no vendored tree**.

Solace Agent Mesh is strong for enterprise multi-agent systems: topic-scoped
A2A traffic, agent-card discovery, TTL health, and decoupled request/status/
response. Its Solace coupling limits reuse outside that stack.

This module keeps the *shape* offline and in-process:

  namespace/mesh/v1/discovery/agentcards
  namespace/mesh/v1/agent/request/{name}
  namespace/mesh/v1/agent/status/{name}/{task_id}
  namespace/mesh/v1/agent/response/{name}/{task_id}
  namespace/mesh/v1/events/{event_type}

  AgentCard (name + capabilities) ──announce──► AgentRegistry (TTL)
        │                                            │
        ▼                                            ▼
   AgentMesh pub/sub  ── wildcard topics (* / >) ── handlers
        │
        └── delegate(capability) → peer request/reply

Use for tests, dry-run meshes, and CLI smoke (``nexus mesh`` /
``python -m nexus.agent_mesh``). Designed to wire orchestrator handoffs
later (integration pending). Live Solace/HTTP transports can map the same
topic strings; prefer ``request_and_wait`` for portable request/reply.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

SCHEMA = "nexus.agent_mesh/v1"
SOURCE_PATTERN = "SolaceLabs/solace-agent-mesh"
MESH_VERSION = "v1"
DEFAULT_NAMESPACE = "nexus"
DEFAULT_TTL_S = 90.0

# Event kinds (mesh verbs)
KIND_DISCOVERY = "discovery"
KIND_REQUEST = "request"
KIND_STATUS = "status"
KIND_RESPONSE = "response"
KIND_SYSTEM = "system"

KINDS: frozenset[str] = frozenset(
    {KIND_DISCOVERY, KIND_REQUEST, KIND_STATUS, KIND_RESPONSE, KIND_SYSTEM}
)

Handler = Callable[["MeshEvent"], Optional[dict[str, Any]]]

_log = logging.getLogger(__name__)

__all__ = [
    "SCHEMA",
    "SOURCE_PATTERN",
    "MESH_VERSION",
    "DEFAULT_NAMESPACE",
    "DEFAULT_TTL_S",
    "KIND_DISCOVERY",
    "KIND_REQUEST",
    "KIND_STATUS",
    "KIND_RESPONSE",
    "KIND_SYSTEM",
    "KINDS",
    "MeshError",
    "AgentCard",
    "MeshEvent",
    "AgentRegistry",
    "AgentMesh",
    "mesh_base_topic",
    "discovery_topic",
    "agent_request_topic",
    "agent_status_topic",
    "agent_response_topic",
    "system_event_topic",
    "topic_match",
    "build_demo_mesh",
    "main",
]


class MeshError(ValueError):
    """Invalid mesh operation (topic, card, or routing)."""


# ── topics (Solace A2A shape, broker-free) ───────────────────────────────────


def _sanitize_segment(
    value: str,
    *,
    label: str = "segment",
    allow_slash: bool = False,
) -> str:
    """Validate one topic level (or hierarchical namespace when *allow_slash*).

    Agent names, task ids, and event types must be a **single** level so
    ``request/*`` wildcards and status subtrees cannot be spoofed via ``/``.
    """
    s = str(value or "").strip().strip("/")
    if not s:
        raise MeshError(f"{label} cannot be empty")
    if ".." in s or any(ch in s for ch in (" ", "\t", "\n")):
        raise MeshError(f"{label} has invalid characters: {value!r}")
    # Single level: alphanumeric + _.-  |  namespace may include /
    pat = r"[A-Za-z0-9_./-]+" if allow_slash else r"[A-Za-z0-9_.-]+"
    if not re.fullmatch(pat, s):
        raise MeshError(f"{label} has invalid characters: {value!r}")
    if not allow_slash and "/" in s:
        raise MeshError(f"{label} must be a single topic level (no '/'): {value!r}")
    return s


def mesh_base_topic(namespace: str = DEFAULT_NAMESPACE) -> str:
    """Base prefix for all mesh topics: ``{namespace}/mesh/v1``."""
    ns = _sanitize_segment(namespace, label="namespace", allow_slash=True)
    return f"{ns}/mesh/{MESH_VERSION}"


def discovery_topic(namespace: str = DEFAULT_NAMESPACE) -> str:
    """Topic for agent-card discovery announcements."""
    return f"{mesh_base_topic(namespace)}/discovery/agentcards"


def agent_request_topic(agent_name: str, *, namespace: str = DEFAULT_NAMESPACE) -> str:
    """Topic for sending requests to a specific agent."""
    name = _sanitize_segment(agent_name, label="agent_name")
    return f"{mesh_base_topic(namespace)}/agent/request/{name}"


def agent_status_topic(
    agent_name: str,
    task_id: str,
    *,
    namespace: str = DEFAULT_NAMESPACE,
) -> str:
    """Topic for status updates from an agent about a task."""
    name = _sanitize_segment(agent_name, label="agent_name")
    tid = _sanitize_segment(task_id, label="task_id")
    return f"{mesh_base_topic(namespace)}/agent/status/{name}/{tid}"


def agent_response_topic(
    agent_name: str,
    task_id: str,
    *,
    namespace: str = DEFAULT_NAMESPACE,
) -> str:
    """Topic for final responses from an agent about a task."""
    name = _sanitize_segment(agent_name, label="agent_name")
    tid = _sanitize_segment(task_id, label="task_id")
    return f"{mesh_base_topic(namespace)}/agent/response/{name}/{tid}"


def system_event_topic(event_type: str, *, namespace: str = DEFAULT_NAMESPACE) -> str:
    """Topic for system-level mesh events (health, config, …)."""
    et = _sanitize_segment(event_type, label="event_type")
    return f"{mesh_base_topic(namespace)}/events/{et}"


def topic_match(pattern: str, topic: str) -> bool:
    """Match Solace-style wildcards: ``*`` one level, ``>`` multi-level tail.

    Levels are ``/``-separated. ``>`` may only appear as the final segment and
    matches **one or more** trailing levels (Solace semantics — not zero).
    """
    if not pattern or not topic:
        return False
    p_parts = pattern.split("/")
    t_parts = topic.split("/")
    i = j = 0
    while i < len(p_parts) and j < len(t_parts):
        p = p_parts[i]
        if p == ">":
            # ``>`` must be final pattern segment and consume ≥1 topic level
            return i == len(p_parts) - 1 and j < len(t_parts)
        if p == "*":
            i += 1
            j += 1
            continue
        if p != t_parts[j]:
            return False
        i += 1
        j += 1
    # Trailing ``>`` with no remaining topic levels → no match (needs ≥1)
    if i < len(p_parts) and p_parts[i] == ">" and i == len(p_parts) - 1:
        return j < len(t_parts)
    return i == len(p_parts) and j == len(t_parts)


# ── data ────────────────────────────────────────────────────────────────────


def _new_id(prefix: str = "mesh") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now() -> float:
    return time.time()


@dataclass
class AgentCard:
    """Capability advertisement for peer discovery (A2A agent-card shape)."""

    name: str
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    version: str = "0.1.0"
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Single-level name (no '/'); reject empty / path tricks early
        self.name = _sanitize_segment(str(self.name or "").strip(), label="agent_name")
        self.description = str(self.description or "")
        self.capabilities = [
            str(c).strip().lower() for c in (self.capabilities or []) if str(c).strip()
        ]
        self.skills = [str(s).strip() for s in (self.skills or []) if str(s).strip()]
        self.version = str(self.version or "0.1.0")
        if not isinstance(self.meta, dict):
            self.meta = {}

    def has_capability(self, cap: str) -> bool:
        c = str(cap or "").strip().lower()
        if not c:
            return False
        return c in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "skills": list(self.skills),
            "version": self.version,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentCard":
        if not isinstance(d, dict):
            raise MeshError("AgentCard requires a dict")
        return cls(
            name=str(d.get("name") or ""),
            description=str(d.get("description") or ""),
            capabilities=list(d.get("capabilities") or []),
            skills=list(d.get("skills") or []),
            version=str(d.get("version") or "0.1.0"),
            meta=dict(d.get("meta") or {}),
        )


@dataclass
class MeshEvent:
    """One mesh message (discovery / request / status / response / system)."""

    kind: str
    topic: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""
    correlation_id: str = ""
    task_id: str = ""
    target: str = ""
    ts: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.kind = str(self.kind or "").strip().lower()
        if self.kind not in KINDS:
            raise MeshError(f"unknown mesh event kind: {self.kind!r}")
        self.topic = str(self.topic or "")
        self.source = str(self.source or "").strip()
        if not self.source:
            raise MeshError("MeshEvent.source is required")
        self.payload = dict(self.payload or {})
        self.event_id = self.event_id or _new_id("evt")
        self.correlation_id = str(self.correlation_id or "")
        self.task_id = str(self.task_id or "")
        self.target = str(self.target or "")
        self.ts = float(self.ts or _now())
        if not isinstance(self.meta, dict):
            self.meta = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "kind": self.kind,
            "topic": self.topic,
            "source": self.source,
            "payload": dict(self.payload),
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "task_id": self.task_id,
            "target": self.target,
            "ts": self.ts,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MeshEvent":
        if not isinstance(d, dict):
            raise MeshError("MeshEvent requires a dict")
        return cls(
            kind=str(d.get("kind") or ""),
            topic=str(d.get("topic") or ""),
            source=str(d.get("source") or ""),
            payload=dict(d.get("payload") or {}),
            event_id=str(d.get("event_id") or ""),
            correlation_id=str(d.get("correlation_id") or ""),
            task_id=str(d.get("task_id") or ""),
            target=str(d.get("target") or ""),
            ts=float(d.get("ts") or 0.0),
            meta=dict(d.get("meta") or {}),
        )


# ── registry ────────────────────────────────────────────────────────────────


@dataclass
class AgentRegistry:
    """Thread-safe agent-card store with TTL heartbeats (SAM registry shape)."""

    ttl_s: float = DEFAULT_TTL_S
    on_added: Optional[Callable[[AgentCard], None]] = None
    on_removed: Optional[Callable[[str], None]] = None
    _items: dict[str, AgentCard] = field(default_factory=dict, repr=False)
    _last_seen: dict[str, float] = field(default_factory=dict, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def add_or_update(self, card: AgentCard | dict[str, Any]) -> bool:
        """Register or refresh a card. Returns True if newly discovered."""
        if isinstance(card, dict):
            card = AgentCard.from_dict(card)
        if not isinstance(card, AgentCard):
            raise MeshError("add_or_update requires AgentCard or dict")
        with self._lock:
            is_new = card.name not in self._items
            self._items[card.name] = card
            self._last_seen[card.name] = _now()
        if is_new and self.on_added:
            try:
                self.on_added(card)
            except Exception:
                _log.exception("registry on_added failed for %s", card.name)
        return is_new

    def heartbeat(self, agent_name: str) -> bool:
        """Refresh last-seen without changing the card. False if unknown."""
        name = str(agent_name or "").strip()
        with self._lock:
            if name not in self._items:
                return False
            self._last_seen[name] = _now()
            return True

    def get(self, agent_name: str) -> Optional[AgentCard]:
        with self._lock:
            return self._items.get(str(agent_name or "").strip())

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._items.keys())

    def list_cards(self, *, healthy_only: bool = False) -> list[AgentCard]:
        with self._lock:
            out: list[AgentCard] = []
            for name in sorted(self._items.keys()):
                if healthy_only and self._is_expired_unlocked(name):
                    continue
                out.append(self._items[name])
            return out

    def last_seen(self, agent_name: str) -> Optional[float]:
        with self._lock:
            return self._last_seen.get(str(agent_name or "").strip())

    def check_ttl(self, agent_name: str) -> tuple[bool, float]:
        """Return (is_expired, seconds_since_last_seen). Unknown → (True, 0)."""
        name = str(agent_name or "").strip()
        with self._lock:
            if name not in self._last_seen:
                return True, 0.0
            age = _now() - float(self._last_seen[name])
            return age > float(self.ttl_s), round(age, 3)

    def _is_expired_unlocked(self, name: str) -> bool:
        ts = self._last_seen.get(name)
        if ts is None:
            return True
        return (_now() - float(ts)) > float(self.ttl_s)

    def expire_stale(self) -> list[str]:
        """Remove cards past TTL. Returns removed names."""
        removed: list[str] = []
        with self._lock:
            for name in list(self._items.keys()):
                if self._is_expired_unlocked(name):
                    del self._items[name]
                    self._last_seen.pop(name, None)
                    removed.append(name)
        for name in removed:
            if self.on_removed:
                try:
                    self.on_removed(name)
                except Exception:
                    _log.exception("registry on_removed failed for %s", name)
        return sorted(removed)

    def remove(self, agent_name: str) -> bool:
        name = str(agent_name or "").strip()
        with self._lock:
            if name not in self._items:
                return False
            del self._items[name]
            self._last_seen.pop(name, None)
        if self.on_removed:
            try:
                self.on_removed(name)
            except Exception:
                _log.exception("registry on_removed failed for %s", name)
        return True

    def find_by_capability(
        self,
        capability: str,
        *,
        healthy_only: bool = True,
        exclude: Optional[Sequence[str]] = None,
    ) -> list[AgentCard]:
        """Peers advertising *capability* (case-insensitive), sorted by name."""
        cap = str(capability or "").strip().lower()
        if not cap:
            return []
        skip = {str(x).strip() for x in (exclude or []) if str(x).strip()}
        out: list[AgentCard] = []
        for card in self.list_cards(healthy_only=healthy_only):
            if card.name in skip:
                continue
            if card.has_capability(cap):
                out.append(card)
        return out

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": SCHEMA,
                "ttl_s": float(self.ttl_s),
                "agents": {
                    name: {
                        "card": card.to_dict(),
                        "last_seen": self._last_seen.get(name),
                        "expired": self._is_expired_unlocked(name),
                    }
                    for name, card in sorted(self._items.items())
                },
                "n_agents": len(self._items),
            }


# ── mesh bus ────────────────────────────────────────────────────────────────


@dataclass
class AgentMesh:
    """In-process pub/sub mesh with discovery + capability delegation.

    No network. Handlers run synchronously on publish (deterministic tests).
    History and reply correlation store are retained for audit (capped).
    """

    namespace: str = DEFAULT_NAMESPACE
    ttl_s: float = DEFAULT_TTL_S
    max_history: int = 500
    max_replies: int = 0  # 0 → use max_history
    registry: AgentRegistry = field(default_factory=AgentRegistry)
    _subs: list[tuple[str, Handler]] = field(default_factory=list, repr=False)
    _history: list[MeshEvent] = field(default_factory=list, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _replies: "OrderedDict[str, MeshEvent]" = field(
        default_factory=OrderedDict, repr=False
    )
    _agent_handlers: dict[str, Handler] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.namespace = _sanitize_segment(
            self.namespace, label="namespace", allow_slash=True
        )
        self.ttl_s = float(self.ttl_s if self.ttl_s is not None else DEFAULT_TTL_S)
        self.max_history = max(1, int(self.max_history or 500))
        self.max_replies = max(
            1, int(self.max_replies or self.max_history or 500)
        )
        # Honor explicit registry TTL: only push mesh→registry when registry
        # still has the default; otherwise registry wins (never clobber).
        reg_ttl = float(self.registry.ttl_s)
        if abs(reg_ttl - DEFAULT_TTL_S) < 1e-9 and abs(self.ttl_s - DEFAULT_TTL_S) > 1e-9:
            self.registry.ttl_s = self.ttl_s
        elif abs(reg_ttl - self.ttl_s) > 1e-9:
            self.ttl_s = reg_ttl
        # Registry removal must drop bound request handlers (no zombie peers)
        prev_removed = self.registry.on_removed

        def _on_removed(name: str) -> None:
            self._drop_agent_sub(name)
            if prev_removed is not None:
                prev_removed(name)

        self.registry.on_removed = _on_removed

    # —— topics ——

    def base_topic(self) -> str:
        return mesh_base_topic(self.namespace)

    def discovery_topic(self) -> str:
        return discovery_topic(self.namespace)

    # —— subscribe / publish ——

    def subscribe(self, pattern: str, handler: Handler) -> None:
        """Subscribe *handler* to topics matching Solace-style *pattern*."""
        if not callable(handler):
            raise MeshError("handler must be callable")
        pat = str(pattern or "").strip()
        if not pat:
            raise MeshError("subscribe pattern cannot be empty")
        with self._lock:
            self._subs.append((pat, handler))

    def unsubscribe_all(self) -> None:
        with self._lock:
            self._subs.clear()
            self._agent_handlers.clear()

    def _drop_agent_sub(self, agent_name: str) -> bool:
        """Remove the bound request handler for *agent_name* (if any)."""
        name = str(agent_name or "").strip()
        with self._lock:
            handler = self._agent_handlers.pop(name, None)
            if handler is None:
                return False
            self._subs = [(p, h) for (p, h) in self._subs if h is not handler]
            return True

    def _record_handler_error(
        self,
        *,
        source: str,
        where: str,
        err: BaseException,
        topic: str = "",
    ) -> None:
        """Log + append a system error event (no re-dispatch — avoid storms)."""
        _log.exception("agent_mesh handler error in %s", where)
        try:
            evt = MeshEvent(
                kind=KIND_SYSTEM,
                topic=system_event_topic("handler_error", namespace=self.namespace),
                source=str(source or "mesh"),
                payload={
                    "ok": False,
                    "where": where,
                    "error": f"{type(err).__name__}: {err}",
                    "topic": topic,
                },
            )
            with self._lock:
                self._history.append(evt)
                if len(self._history) > self.max_history:
                    self._history = self._history[-self.max_history :]
        except Exception:
            _log.exception("failed to record handler error event")

    def _store_reply(self, correlation_id: str, evt: MeshEvent) -> None:
        cid = str(correlation_id or "")
        if not cid:
            return
        with self._lock:
            if cid in self._replies:
                del self._replies[cid]
            self._replies[cid] = evt
            while len(self._replies) > self.max_replies:
                self._replies.popitem(last=False)

    def publish(self, event: MeshEvent | dict[str, Any]) -> MeshEvent:
        """Publish an event to matching subscribers; append to history."""
        if isinstance(event, dict):
            event = MeshEvent.from_dict(event)
        if not isinstance(event, MeshEvent):
            raise MeshError("publish requires MeshEvent or dict")
        if not event.topic:
            raise MeshError("event.topic is required")

        with self._lock:
            self._history.append(event)
            if len(self._history) > self.max_history:
                self._history = self._history[-self.max_history :]
            subs = list(self._subs)

        for pattern, handler in subs:
            if topic_match(pattern, event.topic):
                try:
                    handler(event)
                except Exception as exc:
                    # Fail-open for individual handlers (mesh keeps running)
                    self._record_handler_error(
                        source=event.source or "mesh",
                        where="publish.handler",
                        err=exc,
                        topic=event.topic,
                    )
        return event

    def history(
        self,
        *,
        kind: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> list[MeshEvent]:
        lim = max(1, int(limit or 50))
        with self._lock:
            rows = list(self._history)
        if kind:
            k = str(kind).strip().lower()
            rows = [e for e in rows if e.kind == k]
        if source:
            s = str(source).strip()
            rows = [e for e in rows if e.source == s]
        return rows[-lim:]

    # —— discovery ——

    def announce(self, card: AgentCard | dict[str, Any]) -> MeshEvent:
        """Register card + publish discovery event (agent-card advertisement)."""
        if isinstance(card, dict):
            card = AgentCard.from_dict(card)
        is_new = self.registry.add_or_update(card)
        evt = MeshEvent(
            kind=KIND_DISCOVERY,
            topic=self.discovery_topic(),
            source=card.name,
            payload={"card": card.to_dict(), "is_new": is_new},
            meta={"namespace": self.namespace},
        )
        return self.publish(evt)

    def heartbeat(self, agent_name: str) -> bool:
        """Refresh registry TTL and emit a system heartbeat event."""
        ok = self.registry.heartbeat(agent_name)
        if not ok:
            return False
        self.publish(
            MeshEvent(
                kind=KIND_SYSTEM,
                topic=system_event_topic("heartbeat", namespace=self.namespace),
                source=agent_name,
                payload={"agent": agent_name, "ok": True},
            )
        )
        return True

    # —— request / status / response ——

    def request(
        self,
        to_agent: str,
        payload: dict[str, Any],
        *,
        from_agent: str = "orchestrator",
        task_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> MeshEvent:
        """Publish a request to *to_agent* (does not wait for a handler reply)."""
        target = _sanitize_segment(to_agent, label="to_agent")
        src = str(from_agent or "orchestrator").strip() or "orchestrator"
        tid = (
            _sanitize_segment(task_id, label="task_id")
            if task_id
            else _new_id("task")
        )
        cid = str(correlation_id or _new_id("corr"))
        evt = MeshEvent(
            kind=KIND_REQUEST,
            topic=agent_request_topic(target, namespace=self.namespace),
            source=src,
            target=target,
            task_id=tid,
            correlation_id=cid,
            payload=dict(payload or {}),
            meta=dict(meta or {}),
        )
        return self.publish(evt)

    def request_and_wait(
        self,
        to_agent: str,
        payload: dict[str, Any],
        *,
        timeout: float = 5.0,
        poll_s: float = 0.01,
        from_agent: str = "orchestrator",
        task_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> Optional[MeshEvent]:
        """Publish a request and wait up to *timeout* for a correlated response.

        In-process handlers still complete inline on ``request()``; the poll
        loop keeps the same contract for a future async/broker transport.
        """
        req = self.request(
            to_agent,
            payload,
            from_agent=from_agent,
            task_id=task_id,
            correlation_id=correlation_id,
            meta=meta,
        )
        deadline = _now() + max(0.0, float(timeout))
        poll = max(0.0, float(poll_s))
        while True:
            reply = self.get_reply(req.correlation_id)
            if reply is not None:
                return reply
            now = _now()
            if now >= deadline:
                return None
            if poll > 0:
                time.sleep(min(poll, max(0.0, deadline - now)))
            else:
                return None

    def status(
        self,
        agent_name: str,
        task_id: str,
        payload: dict[str, Any],
        *,
        correlation_id: str = "",
        is_final: bool = False,
    ) -> MeshEvent:
        """Publish a status update for *task_id* from *agent_name*."""
        name = _sanitize_segment(agent_name, label="agent_name")
        tid = _sanitize_segment(task_id, label="task_id")
        body = dict(payload or {})
        body["is_final"] = bool(is_final)
        return self.publish(
            MeshEvent(
                kind=KIND_STATUS,
                topic=agent_status_topic(name, tid, namespace=self.namespace),
                source=name,
                task_id=tid,
                correlation_id=str(correlation_id or ""),
                payload=body,
            )
        )

    def respond(
        self,
        agent_name: str,
        task_id: str,
        payload: dict[str, Any],
        *,
        correlation_id: str = "",
        ok: bool = True,
    ) -> MeshEvent:
        """Publish a final response for *task_id* from *agent_name*."""
        name = _sanitize_segment(agent_name, label="agent_name")
        tid = _sanitize_segment(task_id, label="task_id")
        body = dict(payload or {})
        body["ok"] = bool(ok)
        evt = MeshEvent(
            kind=KIND_RESPONSE,
            topic=agent_response_topic(name, tid, namespace=self.namespace),
            source=name,
            task_id=tid,
            correlation_id=str(correlation_id or ""),
            payload=body,
        )
        if evt.correlation_id:
            self._store_reply(evt.correlation_id, evt)
        return self.publish(evt)

    def get_reply(
        self, correlation_id: str, *, consume: bool = False
    ) -> Optional[MeshEvent]:
        """Fetch the latest response stored for *correlation_id* (if any).

        When *consume* is True the entry is removed (one-shot reply).
        """
        cid = str(correlation_id or "")
        with self._lock:
            if consume:
                return self._replies.pop(cid, None)
            return self._replies.get(cid)

    # —— capability delegation ——

    def bind_agent(
        self,
        card: AgentCard | dict[str, Any],
        handler: Handler,
    ) -> AgentCard:
        """Subscribe *handler* then announce *card* (atomic readiness).

        Re-binding the same name replaces the previous handler (idempotent).
        Handler return values (dict) are auto-published as responses for
        request events only.
        """
        if not callable(handler):
            raise MeshError("handler must be callable")
        if isinstance(card, dict):
            card = AgentCard.from_dict(card)
        if not isinstance(card, AgentCard):
            raise MeshError("bind_agent requires AgentCard or dict")
        # Validate topic / single-level name before mutating subscriptions
        req_topic = agent_request_topic(card.name, namespace=self.namespace)
        agent_name = card.name

        def _wrapped(evt: MeshEvent) -> Optional[dict[str, Any]]:
            if evt.kind != KIND_REQUEST:
                return None
            if evt.target and evt.target != agent_name:
                return None
            result = handler(evt)
            if isinstance(result, dict):
                self.respond(
                    agent_name,
                    evt.task_id or _new_id("task"),
                    result,
                    correlation_id=evt.correlation_id,
                    ok=bool(result.get("ok", True)),
                )
            return result

        # Install (or replace) handler before discovery so peers can route
        with self._lock:
            old = self._agent_handlers.pop(agent_name, None)
            if old is not None:
                self._subs = [(p, h) for (p, h) in self._subs if h is not old]
            self._subs.append((req_topic, _wrapped))
            self._agent_handlers[agent_name] = _wrapped
        self.announce(card)
        return card

    def unbind_agent(self, agent_name: str) -> bool:
        """Drop request subscription and remove *agent_name* from the registry.

        Returns True if a bound handler or registry entry was present.
        """
        name = str(agent_name or "").strip()
        if not name:
            return False
        dropped = self._drop_agent_sub(name)
        # registry.remove triggers on_removed → _drop_agent_sub again (idempotent)
        removed = self.registry.remove(name)
        return dropped or removed

    def delegate(
        self,
        capability: str,
        payload: dict[str, Any],
        *,
        from_agent: str = "orchestrator",
        task_id: Optional[str] = None,
        exclude: Optional[Sequence[str]] = None,
        prefer: Optional[str] = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Route a request to a healthy peer advertising *capability*.

        Returns a result dict::

            {
              "ok": bool,
              "schema": SCHEMA,
              "peer": str | None,
              "request": MeshEvent.to_dict() | None,
              "response": MeshEvent.to_dict() | None,
              "error": str | None,
              "candidates": [names...],
            }
        """
        cap = str(capability or "").strip().lower()
        if not cap:
            return {
                "ok": False,
                "schema": SCHEMA,
                "peer": None,
                "request": None,
                "response": None,
                "error": "capability is required",
                "candidates": [],
            }

        self.registry.expire_stale()
        peers = self.registry.find_by_capability(
            cap, healthy_only=True, exclude=exclude
        )
        names = [p.name for p in peers]
        if prefer:
            pref = str(prefer).strip()
            peers = sorted(peers, key=lambda c: (0 if c.name == pref else 1, c.name))
        if not peers:
            return {
                "ok": False,
                "schema": SCHEMA,
                "peer": None,
                "request": None,
                "response": None,
                "error": f"no healthy peer for capability {cap!r}",
                "candidates": names,
            }

        peer = peers[0]
        body = dict(payload or {})
        body.setdefault("capability", cap)
        # Build request via request_and_wait for transport-honest correlation
        req = self.request(
            peer.name,
            body,
            from_agent=from_agent,
            task_id=task_id,
        )
        # Inline handlers already stored a reply; poll covers delayed replies
        deadline = _now() + max(0.0, float(timeout))
        reply: Optional[MeshEvent] = self.get_reply(req.correlation_id)
        while reply is None and _now() < deadline:
            time.sleep(0.01)
            reply = self.get_reply(req.correlation_id)
        return {
            "ok": bool(reply and reply.payload.get("ok", True)) if reply else False,
            "schema": SCHEMA,
            "peer": peer.name,
            "request": req.to_dict(),
            "response": reply.to_dict() if reply else None,
            "error": None if reply else "no response from peer handler",
            "candidates": names,
        }

    def snapshot(self) -> dict[str, Any]:
        """Operator view: registry + topic base + recent history counts."""
        with self._lock:
            n_hist = len(self._history)
            n_subs = len(self._subs)
            by_kind: dict[str, int] = {}
            for e in self._history:
                by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        return {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "namespace": self.namespace,
            "base_topic": self.base_topic(),
            "ttl_s": float(self.ttl_s),
            "n_subscriptions": n_subs,
            "n_history": n_hist,
            "history_by_kind": by_kind,
            "registry": self.registry.to_dict(),
        }


def build_demo_mesh(
    *,
    namespace: str = DEFAULT_NAMESPACE,
    ttl_s: float = DEFAULT_TTL_S,
) -> AgentMesh:
    """Small offline mesh: researcher + implementer + tester peers.

    Useful for docs/CLI smoke without a broker.
    """
    mesh = AgentMesh(namespace=namespace, ttl_s=ttl_s)

    def research_handler(evt: MeshEvent) -> dict[str, Any]:
        q = str((evt.payload or {}).get("query") or evt.payload.get("objective") or "")
        return {
            "ok": True,
            "agent": "researcher",
            "notes": f"researched: {q[:200]}",
            "citations": [],
        }

    def implement_handler(evt: MeshEvent) -> dict[str, Any]:
        obj = str((evt.payload or {}).get("objective") or "")
        return {
            "ok": True,
            "agent": "implementer",
            "artifact": "results/demo_artifact.txt",
            "notes": f"implement: {obj[:200]}",
        }

    def test_handler(evt: MeshEvent) -> dict[str, Any]:
        return {
            "ok": True,
            "agent": "tester",
            "pass_fail": "pass",
            "notes": "offline mesh test gate",
        }

    mesh.bind_agent(
        AgentCard(
            name="researcher",
            description="Offline research peer",
            capabilities=["research", "arxiv", "search"],
            skills=["literature-scan"],
        ),
        research_handler,
    )
    mesh.bind_agent(
        AgentCard(
            name="implementer",
            description="Offline implement peer",
            capabilities=["implement", "code", "edit"],
            skills=["write-artifact"],
        ),
        implement_handler,
    )
    mesh.bind_agent(
        AgentCard(
            name="tester",
            description="Offline test peer",
            capabilities=["test", "verify", "eval"],
            skills=["pytest-smoke"],
        ),
        test_handler,
    )
    return mesh


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI: ``python -m nexus.agent_mesh [demo|topics]``."""
    import json
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    cmd = (args[0] if args else "demo").strip().lower()

    if cmd in ("-h", "--help", "help"):
        print("usage: python -m nexus.agent_mesh [demo|topics|snapshot]")
        return 0

    if cmd == "topics":
        ns = DEFAULT_NAMESPACE
        print(f"base:       {mesh_base_topic(ns)}")
        print(f"discovery:  {discovery_topic(ns)}")
        print(f"request:    {agent_request_topic('AGENT', namespace=ns)}")
        print(f"status:     {agent_status_topic('AGENT', 'TASK', namespace=ns)}")
        print(f"response:   {agent_response_topic('AGENT', 'TASK', namespace=ns)}")
        return 0

    mesh = build_demo_mesh()
    if cmd == "snapshot":
        print(json.dumps(mesh.snapshot(), indent=2, sort_keys=True))
        return 0

    # demo: research → implement → test via capability delegation
    r1 = mesh.delegate("research", {"query": "event-driven agent mesh"})
    r2 = mesh.delegate("implement", {"objective": "port solace mesh pattern"})
    r3 = mesh.delegate("test", {"suite": "offline"})
    out = {
        "schema": SCHEMA,
        "source_pattern": SOURCE_PATTERN,
        "ok": all(x.get("ok") for x in (r1, r2, r3)),
        "steps": [
            {"capability": "research", **{k: r1[k] for k in ("ok", "peer", "error")}},
            {"capability": "implement", **{k: r2[k] for k in ("ok", "peer", "error")}},
            {"capability": "test", **{k: r3[k] for k in ("ok", "peer", "error")}},
        ],
        "snapshot": mesh.snapshot(),
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
