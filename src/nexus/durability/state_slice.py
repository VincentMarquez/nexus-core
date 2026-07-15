"""Zero-trust state slicing (cycgraph read_keys / write_keys pattern).

Each agent (or step) receives only the keys declared in ``read_keys`` and may
write only keys declared in ``write_keys``. Defaults are empty sets — fail-closed
least privilege. Wildcard ``*`` grants full access for trusted system agents.

Does not vendor cycgraph; pattern only.

Evidence drivers:
- wmcmahan/cycgraph — permission-scoped state, reject undeclared writes
- SECURITY.md: ``read_keys`` / ``write_keys`` default to ``[]``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


# Keys that must never be agent-writable (engine / taint bookkeeping).
PROTECTED_PREFIXES = ("_",)
PROTECTED_KEYS = frozenset({"_taint_registry", "_last_event_sequence_id"})

WILDCARD = "*"


class SliceError(PermissionError):
    """Raised when a read/write violates declared state permissions."""

    def __init__(
        self,
        message: str,
        *,
        key: str = "",
        op: str = "",
        allowed: Optional[Iterable[str]] = None,
    ) -> None:
        super().__init__(message)
        self.key = key
        self.op = op
        self.allowed = list(allowed) if allowed is not None else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "SliceError",
            "message": str(self),
            "key": self.key,
            "op": self.op,
            "allowed": list(self.allowed),
        }


def _norm_keys(keys: Optional[Iterable[str]]) -> frozenset[str]:
    if keys is None:
        return frozenset()
    out: set[str] = set()
    for k in keys:
        s = str(k).strip()
        if s:
            out.add(s)
    return frozenset(out)


def is_protected_key(key: str) -> bool:
    """True for engine-reserved keys (underscore prefix or known registry)."""
    if key in PROTECTED_KEYS:
        return True
    return any(key.startswith(p) for p in PROTECTED_PREFIXES)


@dataclass
class StateSlice:
    """Permission-scoped view over a shared durable state blob.

    Zero-trust defaults: both ``read_keys`` and ``write_keys`` empty → agent
    sees nothing and cannot write. Pass ``"*"`` in either set for full access
    on that axis (system agents only).
    """

    read_keys: frozenset[str] = field(default_factory=frozenset)
    write_keys: frozenset[str] = field(default_factory=frozenset)
    agent_id: str = ""
    # when True, protected keys are never writable even with '*'
    protect_system_keys: bool = True

    # ── factories ───────────────────────────────────────────────────────

    @classmethod
    def from_keys(
        cls,
        *,
        read_keys: Optional[Iterable[str]] = None,
        write_keys: Optional[Iterable[str]] = None,
        agent_id: str = "",
        protect_system_keys: bool = True,
    ) -> "StateSlice":
        return cls(
            read_keys=_norm_keys(read_keys),
            write_keys=_norm_keys(write_keys),
            agent_id=agent_id,
            protect_system_keys=protect_system_keys,
        )

    @classmethod
    def open_all(cls, *, agent_id: str = "system") -> "StateSlice":
        """Trusted system agent: full read/write (still blocks protected writes)."""
        return cls(
            read_keys=frozenset({WILDCARD}),
            write_keys=frozenset({WILDCARD}),
            agent_id=agent_id,
        )

    @classmethod
    def from_meta(cls, meta: Optional[dict[str, Any]], *, agent_id: str = "") -> "StateSlice":
        """Resolve permissions from task/step meta.

        Recognized shapes::

            meta["read_keys"] / meta["write_keys"]  — list of str
            meta["state_slice"] = {"read_keys": [...], "write_keys": [...]}
        """
        meta = meta or {}
        nested = meta.get("state_slice") if isinstance(meta.get("state_slice"), dict) else {}
        rk = meta.get("read_keys", nested.get("read_keys"))
        wk = meta.get("write_keys", nested.get("write_keys"))
        aid = str(meta.get("agent_id") or nested.get("agent_id") or agent_id or "")
        return cls.from_keys(read_keys=rk, write_keys=wk, agent_id=aid)

    # ── permission checks ───────────────────────────────────────────────

    def can_read(self, key: str) -> bool:
        if WILDCARD in self.read_keys:
            return True
        return key in self.read_keys

    def can_write(self, key: str) -> bool:
        if self.protect_system_keys and is_protected_key(key):
            return False
        if WILDCARD in self.write_keys:
            return True
        return key in self.write_keys

    def require_read(self, key: str) -> None:
        if not self.can_read(key):
            raise SliceError(
                f"state key {key!r} not in read_keys for agent "
                f"{self.agent_id or '?'} (zero-trust deny)",
                key=key,
                op="read",
                allowed=sorted(self.read_keys),
            )

    def require_write(self, key: str) -> None:
        if not self.can_write(key):
            reason = "protected" if is_protected_key(key) else "not in write_keys"
            raise SliceError(
                f"state key {key!r} write denied ({reason}) for agent "
                f"{self.agent_id or '?'}",
                key=key,
                op="write",
                allowed=sorted(self.write_keys),
            )

    # ── view / merge ────────────────────────────────────────────────────

    def view(self, state: dict[str, Any]) -> dict[str, Any]:
        """Return a shallow copy of *state* filtered to readable keys.

        With wildcard read, returns a shallow copy of all non-protected keys
        (protected keys stay hidden unless explicitly listed).
        """
        if not isinstance(state, dict):
            return {}
        if WILDCARD in self.read_keys:
            out: dict[str, Any] = {}
            for k, v in state.items():
                # hide protected bookkeeping from agents unless explicitly allowed
                if is_protected_key(k) and k not in self.read_keys:
                    continue
                out[k] = v
            return out
        return {k: state[k] for k in self.read_keys if k in state}

    def filter_writes(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Return only keys that pass write permission (silently drop others)."""
        if not isinstance(patch, dict):
            return {}
        return {k: v for k, v in patch.items() if self.can_write(k)}

    def merge_writes(
        self,
        state: dict[str, Any],
        patch: dict[str, Any],
        *,
        strict: bool = True,
    ) -> dict[str, Any]:
        """Apply *patch* into *state* under write permissions.

        When *strict* is True (default), any undeclared/protected key raises
        :class:`SliceError` (cycgraph reject-undeclared-writes). When False,
        forbidden keys are dropped and the rest applied.
        """
        if not isinstance(patch, dict):
            if strict:
                raise SliceError("write patch must be a dict", op="write")
            return state
        if strict:
            for k in patch:
                self.require_write(k)
            allowed = patch
        else:
            allowed = self.filter_writes(patch)
        state.update(allowed)
        return state

    def apply_write(
        self,
        state: dict[str, Any],
        key: str,
        value: Any,
        *,
        strict: bool = True,
    ) -> dict[str, Any]:
        """Write a single key under permission check."""
        if strict:
            self.require_write(key)
        elif not self.can_write(key):
            return state
        state[key] = value
        return state

    # ── serde ───────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "read_keys": sorted(self.read_keys),
            "write_keys": sorted(self.write_keys),
            "agent_id": self.agent_id,
            "protect_system_keys": self.protect_system_keys,
        }

    @classmethod
    def from_dict(cls, d: Optional[dict[str, Any]]) -> "StateSlice":
        if not d:
            return cls()
        return cls.from_keys(
            read_keys=d.get("read_keys"),
            write_keys=d.get("write_keys"),
            agent_id=str(d.get("agent_id") or ""),
            protect_system_keys=bool(d.get("protect_system_keys", True)),
        )


def slice_from_step(
    step: Any,
    *,
    agent_id: str = "",
    meta: Optional[dict[str, Any]] = None,
) -> StateSlice:
    """Build a StateSlice from a StepDef-like object + optional task meta.

    Prefer step attributes ``read_keys`` / ``write_keys`` / ``output_keys``;
    fall back to meta. When only ``output_keys`` exist, use them as write_keys
    (and as read_keys of prior outputs is left to the caller).
    """
    rk: Optional[Iterable[str]] = None
    wk: Optional[Iterable[str]] = None
    if step is not None:
        rk = getattr(step, "read_keys", None)
        wk = getattr(step, "write_keys", None)
        if wk is None:
            ok = getattr(step, "output_keys", None)
            if ok:
                wk = ok
        aid = agent_id or str(getattr(step, "agent", "") or "")
        if isinstance(aid, list):
            aid = aid[0] if aid else ""
    else:
        aid = agent_id
    if meta:
        nested = StateSlice.from_meta(meta, agent_id=aid)
        if rk is None and nested.read_keys:
            rk = nested.read_keys
        if wk is None and nested.write_keys:
            wk = nested.write_keys
        if not aid:
            aid = nested.agent_id
    return StateSlice.from_keys(read_keys=rk, write_keys=wk, agent_id=str(aid or ""))
