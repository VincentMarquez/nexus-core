"""Taint labels for durable state keys (cycgraph taint-tracking pattern).

Untrusted sources (mined repos, external MCP, user-supplied blobs) are labeled
so they cannot be read as ``trusted`` without an explicit promote gate.

Does not vendor cycgraph; pattern only.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional


class TaintLevel(str, Enum):
    """Trust rank for a state key (lower ordinal = more trusted)."""

    TRUSTED = "trusted"
    USER = "user"
    MINED = "mined"
    EXTERNAL_MCP = "external_mcp"
    DERIVED = "derived"

    @classmethod
    def parse(cls, value: Any) -> "TaintLevel":
        if isinstance(value, cls):
            return value
        s = str(value or "trusted").strip().lower()
        for m in cls:
            if m.value == s:
                return m
        # unknown labels degrade to derived (never silently trusted)
        return cls.DERIVED

    def is_trusted(self) -> bool:
        return self is TaintLevel.TRUSTED

    def rank(self) -> int:
        """Higher = less trusted (for least-privilege merge)."""
        order = {
            TaintLevel.TRUSTED: 0,
            TaintLevel.USER: 1,
            TaintLevel.DERIVED: 2,
            TaintLevel.MINED: 3,
            TaintLevel.EXTERNAL_MCP: 4,
        }
        return order.get(self, 99)


# Levels that may never be silently elevated.
UNTRUSTED_LEVELS = frozenset(
    {
        TaintLevel.MINED,
        TaintLevel.EXTERNAL_MCP,
        TaintLevel.DERIVED,
        TaintLevel.USER,
    }
)


class TaintError(RuntimeError):
    """Raised on illegal trust elevation or untrusted read-as-trusted."""

    def __init__(
        self,
        message: str,
        *,
        key: str = "",
        level: Optional[TaintLevel] = None,
    ) -> None:
        super().__init__(message)
        self.key = key
        self.level = level

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "TaintError",
            "message": str(self),
            "key": self.key,
            "level": self.level.value if self.level else None,
        }


@dataclass
class TaintMeta:
    level: TaintLevel = TaintLevel.TRUSTED
    source: str = ""
    agent_id: str = ""
    created_at: float = field(default_factory=time.time)
    promoted_from: str = ""
    gate: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "source": self.source,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "promoted_from": self.promoted_from,
            "gate": self.gate,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaintMeta":
        return cls(
            level=TaintLevel.parse(d.get("level")),
            source=str(d.get("source") or ""),
            agent_id=str(d.get("agent_id") or ""),
            created_at=float(d.get("created_at") or time.time()),
            promoted_from=str(d.get("promoted_from") or ""),
            gate=str(d.get("gate") or ""),
        )


# Reserved registry key (cycgraph ``_taint_registry`` shape).
TAINT_REGISTRY_KEY = "_taint_registry"


@dataclass
class TaintSet:
    """In-memory taint registry for durable state blobs.

    Unknown keys default to *default_level* (``trusted`` for internal engine
    state; callers should stamp mined/MCP writes explicitly).
    """

    registry: dict[str, TaintMeta] = field(default_factory=dict)
    default_level: TaintLevel = TaintLevel.TRUSTED

    # ── core API ────────────────────────────────────────────────────────

    def stamp(
        self,
        key: str,
        level: TaintLevel | str,
        *,
        source: str = "",
        agent_id: str = "",
    ) -> TaintMeta:
        """Label *key* with a taint level (overwrites prior label)."""
        if key == TAINT_REGISTRY_KEY:
            raise TaintError("cannot stamp the taint registry key itself", key=key)
        meta = TaintMeta(
            level=TaintLevel.parse(level),
            source=source,
            agent_id=agent_id,
            created_at=time.time(),
        )
        self.registry[key] = meta
        return meta

    def stamp_mined(self, key: str, *, source: str = "", agent_id: str = "") -> TaintMeta:
        return self.stamp(key, TaintLevel.MINED, source=source or "mined", agent_id=agent_id)

    def stamp_mcp(self, key: str, *, source: str = "", agent_id: str = "") -> TaintMeta:
        return self.stamp(
            key,
            TaintLevel.EXTERNAL_MCP,
            source=source or "external_mcp",
            agent_id=agent_id,
        )

    def level_of(self, key: str) -> TaintLevel:
        meta = self.registry.get(key)
        if meta is None:
            return self.default_level
        return meta.level

    def info(self, key: str) -> Optional[TaintMeta]:
        return self.registry.get(key)

    def is_tainted(self, key: str) -> bool:
        """True when key is present and not TRUSTED."""
        meta = self.registry.get(key)
        if meta is None:
            return self.default_level is not TaintLevel.TRUSTED
        return not meta.level.is_trusted()

    def is_trusted(self, key: str) -> bool:
        return self.level_of(key).is_trusted()

    def require_trusted(self, key: str) -> None:
        """Refuse reading *key* as trusted when labeled otherwise.

        Acceptance: mined (and other untrusted) state cannot be read as trusted
        without an explicit :meth:`promote`.
        """
        level = self.level_of(key)
        if not level.is_trusted():
            raise TaintError(
                f"state key {key!r} is {level.value}; not readable as trusted "
                f"(call promote() with an explicit gate)",
                key=key,
                level=level,
            )

    def promote(
        self,
        key: str,
        *,
        gate: str,
        agent_id: str = "",
    ) -> TaintMeta:
        """Explicit elevation to TRUSTED. *gate* is required (audit trail)."""
        gate = (gate or "").strip()
        if not gate:
            raise TaintError(
                "promote requires a non-empty gate reason",
                key=key,
                level=self.level_of(key),
            )
        prev = self.level_of(key)
        meta = TaintMeta(
            level=TaintLevel.TRUSTED,
            source="promote",
            agent_id=agent_id,
            created_at=time.time(),
            promoted_from=prev.value,
            gate=gate,
        )
        self.registry[key] = meta
        return meta

    def propagate(
        self,
        input_keys: Iterable[str],
        output_keys: Iterable[str],
        *,
        agent_id: str = "",
    ) -> dict[str, TaintMeta]:
        """If any input is untrusted, mark all outputs DERIVED (cycgraph shape)."""
        dirty = False
        worst = TaintLevel.TRUSTED
        for k in input_keys:
            lvl = self.level_of(k)
            if not lvl.is_trusted():
                dirty = True
                if lvl.rank() > worst.rank():
                    worst = lvl
        if not dirty:
            return {}
        new: dict[str, TaintMeta] = {}
        for ok in output_keys:
            if ok == TAINT_REGISTRY_KEY:
                continue
            meta = TaintMeta(
                level=TaintLevel.DERIVED,
                source=f"derived_from={worst.value}",
                agent_id=agent_id,
                created_at=time.time(),
            )
            self.registry[ok] = meta
            new[ok] = meta
        return new

    # ── embedding into state / task.meta ────────────────────────────────

    def embed(self, state: dict[str, Any]) -> dict[str, Any]:
        """Write registry into *state* under ``_taint_registry`` (mutates)."""
        state[TAINT_REGISTRY_KEY] = self.to_dict()
        return state

    @classmethod
    def extract(cls, state: dict[str, Any]) -> "TaintSet":
        raw = state.get(TAINT_REGISTRY_KEY)
        if isinstance(raw, dict):
            # tolerate either full TaintSet dict or bare key→meta map
            if "registry" in raw or "default_level" in raw:
                return cls.from_dict(raw)
            return cls.from_dict({"registry": raw})
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_level": self.default_level.value,
            "registry": {k: v.to_dict() for k, v in self.registry.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaintSet":
        if not d:
            return cls()
        reg_in = d.get("registry") or {}
        registry: dict[str, TaintMeta] = {}
        if isinstance(reg_in, dict):
            for k, v in reg_in.items():
                if isinstance(v, dict):
                    registry[str(k)] = TaintMeta.from_dict(v)
                else:
                    registry[str(k)] = TaintMeta(level=TaintLevel.parse(v))
        return cls(
            registry=registry,
            default_level=TaintLevel.parse(d.get("default_level", "trusted")),
        )


def infer_source_level(source: str) -> TaintLevel:
    """Heuristic: path/url-ish source string → taint level."""
    s = (source or "").lower()
    if not s:
        return TaintLevel.TRUSTED
    if "mcp" in s or "external" in s:
        return TaintLevel.EXTERNAL_MCP
    if (
        "mined" in s
        or "scout_repos" in s
        or "mine_eval" in s
        or "/.nexus_workspaces/" in s
        or s.startswith("github:")
        or "repo_mine" in s
    ):
        return TaintLevel.MINED
    if s in {"user", "human", "stdin"} or s.startswith("user:"):
        return TaintLevel.USER
    return TaintLevel.DERIVED
