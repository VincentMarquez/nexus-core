"""Eval-gated cross-run memory writes (cycgraph verified-lessons pattern).

Lessons / facts only enter durable retained memory when an eval score meets a
threshold (aligned with :data:`nexus.judge.PASS_THRESHOLD`). Below-threshold
candidates may land in a trial namespace and later be promoted (on better
outcomes) or left out of the retained store.

Does not vendor cycgraph; pattern only.

Evidence drivers:
- wmcmahan/cycgraph — eval-gated retention (verified lessons)
- arXiv preference / value systems — score thresholds before promote
- NEXUS ``RubricJudge`` PASS/REVISE cutoffs
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

# Keep gate numbers in lockstep with the rubric judge defaults.
try:
    from nexus.judge import PASS_THRESHOLD as _DEFAULT_MIN_SCORE
except Exception:  # pragma: no cover — import isolation for unit tests
    _DEFAULT_MIN_SCORE = 0.7

DEFAULT_MIN_SCORE = float(_DEFAULT_MIN_SCORE)
TRIAL_NS_SUFFIX = "/trial"
TRIAL_KIND = "trial"
RETAINED_KIND = "lesson"


class MemoryWriteDenied(PermissionError):
    """Raised when an eval gate refuses a durable memory write."""

    def __init__(
        self,
        message: str,
        *,
        score: Optional[float] = None,
        min_score: float = DEFAULT_MIN_SCORE,
        decision: str = "",
        ns: str = "",
    ) -> None:
        super().__init__(message)
        self.score = score
        self.min_score = min_score
        self.decision = decision
        self.ns = ns

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "MemoryWriteDenied",
            "message": str(self),
            "score": self.score,
            "min_score": self.min_score,
            "decision": self.decision,
            "ns": self.ns,
        }


@runtime_checkable
class MemoryStore(Protocol):
    """Minimal contract shared by MemorySpine / SqliteMemory."""

    def add_text(
        self,
        text: str,
        *,
        ns: str,
        kind: str = "doc",
        source: str = "",
        id: Optional[str] = None,
    ) -> str: ...


@dataclass
class EvalGate:
    """Score / decision gate for durable memory retention.

    Parameters
    ----------
    min_score:
        Minimum eval score (0..1) required to enter *retained* memory.
        Defaults to the rubric judge pass threshold (0.7).
    require_pass:
        When True, also require ``decision == "pass"`` if a decision is supplied.
    fail_closed:
        When True (default), missing / non-numeric scores are denied rather
        than allowed — matches cycgraph "fails closed by default" for gates.
    allow_trial:
        When True, denied retained writes may still land in a trial namespace.
        When False, denied writes raise :class:`MemoryWriteDenied`.
    """

    min_score: float = DEFAULT_MIN_SCORE
    require_pass: bool = False
    fail_closed: bool = True
    allow_trial: bool = True

    def allows(
        self,
        score: Optional[float] = None,
        decision: Optional[str] = None,
    ) -> bool:
        """Return True when the candidate may enter retained memory."""
        if score is None:
            return not self.fail_closed
        try:
            s = float(score)
        except (TypeError, ValueError):
            return not self.fail_closed
        if s < float(self.min_score):
            return False
        if self.require_pass and decision is not None:
            if str(decision).strip().lower() != "pass":
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_score": float(self.min_score),
            "require_pass": bool(self.require_pass),
            "fail_closed": bool(self.fail_closed),
            "allow_trial": bool(self.allow_trial),
        }

    @classmethod
    def from_meta(cls, meta: Optional[dict[str, Any]] = None) -> "EvalGate":
        """Build from task.meta keys: ``memory_min_score``, ``memory_require_pass``, …"""
        meta = meta or {}
        gate = meta.get("eval_gate") if isinstance(meta.get("eval_gate"), dict) else {}
        min_score = meta.get("memory_min_score", gate.get("min_score", DEFAULT_MIN_SCORE))
        require_pass = meta.get(
            "memory_require_pass",
            gate.get("require_pass", False),
        )
        fail_closed = meta.get(
            "memory_fail_closed",
            gate.get("fail_closed", True),
        )
        allow_trial = meta.get(
            "memory_allow_trial",
            gate.get("allow_trial", True),
        )
        try:
            ms = float(min_score)
        except (TypeError, ValueError):
            ms = DEFAULT_MIN_SCORE
        return cls(
            min_score=ms,
            require_pass=bool(require_pass),
            fail_closed=bool(fail_closed),
            allow_trial=bool(allow_trial),
        )


@dataclass
class WriteResult:
    """Outcome of a gated memory write attempt."""

    ok: bool
    retained: bool
    trial: bool
    denied: bool
    chunk_id: str = ""
    ns: str = ""
    kind: str = ""
    score: Optional[float] = None
    min_score: float = DEFAULT_MIN_SCORE
    decision: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "retained": self.retained,
            "trial": self.trial,
            "denied": self.denied,
            "chunk_id": self.chunk_id,
            "ns": self.ns,
            "kind": self.kind,
            "score": self.score,
            "min_score": self.min_score,
            "decision": self.decision,
            "reason": self.reason,
        }


def trial_namespace(ns: str, *, suffix: str = TRIAL_NS_SUFFIX) -> str:
    """Map a retained namespace to its trial sibling (idempotent)."""
    base = (ns or "proj/default").rstrip("/")
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


def retained_namespace(ns: str, *, suffix: str = TRIAL_NS_SUFFIX) -> str:
    """Strip trial suffix to recover the retained namespace."""
    base = (ns or "proj/default").rstrip("/")
    if base.endswith(suffix):
        return base[: -len(suffix)] or "proj/default"
    return base


@dataclass
class GatedMemoryWriter:
    """Wrap a memory store so writes are eval-gated before retention.

    Typical use::

        writer = GatedMemoryWriter(store=SqliteMemory(path), gate=EvalGate())
        r = writer.write(
            "Prefer atomic rename for checkpoints",
            ns="proj/lessons",
            score=0.85,
            decision="pass",
            source="task:abc/step:review",
        )
        assert r.retained
    """

    store: MemoryStore
    gate: EvalGate = field(default_factory=EvalGate)
    trial_suffix: str = TRIAL_NS_SUFFIX
    # audit log of write attempts (in-process; not durable by itself)
    history: list[dict[str, Any]] = field(default_factory=list)

    def write(
        self,
        text: str,
        *,
        ns: str,
        score: Optional[float] = None,
        decision: Optional[str] = None,
        kind: str = "",
        source: str = "",
        id: Optional[str] = None,
        force: bool = False,
        raise_on_deny: bool = False,
        ts: Optional[float] = None,
    ) -> WriteResult:
        """Attempt a durable write under the eval gate.

        - ``force=True`` bypasses the gate (operator / human promote path).
        - On gate pass → retained namespace with kind ``lesson`` (or caller kind).
        - On gate fail + ``allow_trial`` → trial namespace with kind ``trial``.
        - On gate fail + not allow_trial → denied (optionally raises).
        """
        text = text if text is not None else ""
        decision_s = str(decision or "").strip().lower()
        score_f: Optional[float]
        try:
            score_f = None if score is None else float(score)
        except (TypeError, ValueError):
            score_f = None

        allowed = force or self.gate.allows(score_f, decision_s or None)
        min_score = float(self.gate.min_score)

        if allowed:
            target_ns = retained_namespace(ns, suffix=self.trial_suffix)
            target_kind = kind or RETAINED_KIND
            cid = self._add(
                text,
                ns=target_ns,
                kind=target_kind,
                source=source,
                id=id,
                ts=ts,
            )
            result = WriteResult(
                ok=True,
                retained=True,
                trial=False,
                denied=False,
                chunk_id=cid,
                ns=target_ns,
                kind=target_kind,
                score=score_f,
                min_score=min_score,
                decision=decision_s,
                reason="force" if force else "eval_pass",
            )
            self._record(result)
            return result

        # Gate failed
        if self.gate.allow_trial:
            target_ns = trial_namespace(ns, suffix=self.trial_suffix)
            target_kind = kind or TRIAL_KIND
            cid = self._add(
                text,
                ns=target_ns,
                kind=target_kind,
                source=source,
                id=id,
                ts=ts,
            )
            result = WriteResult(
                ok=True,
                retained=False,
                trial=True,
                denied=False,
                chunk_id=cid,
                ns=target_ns,
                kind=target_kind,
                score=score_f,
                min_score=min_score,
                decision=decision_s,
                reason=self._deny_reason(score_f, decision_s),
            )
            self._record(result)
            return result

        reason = self._deny_reason(score_f, decision_s)
        result = WriteResult(
            ok=False,
            retained=False,
            trial=False,
            denied=True,
            chunk_id="",
            ns=ns,
            kind=kind or "",
            score=score_f,
            min_score=min_score,
            decision=decision_s,
            reason=reason,
        )
        self._record(result)
        if raise_on_deny:
            raise MemoryWriteDenied(
                f"memory write denied: {reason}",
                score=score_f,
                min_score=min_score,
                decision=decision_s,
                ns=ns,
            )
        return result

    def promote(
        self,
        text: str,
        *,
        ns: str,
        score: Optional[float] = None,
        decision: str = "pass",
        source: str = "",
        id: Optional[str] = None,
        gate_reason: str = "promote",
    ) -> WriteResult:
        """Explicit elevation of a lesson into retained memory.

        *gate_reason* is required (audit trail; mirrors taint.promote).
        """
        reason = (gate_reason or "").strip()
        if not reason:
            raise MemoryWriteDenied(
                "promote requires a non-empty gate_reason",
                score=score,
                min_score=float(self.gate.min_score),
                decision=decision,
                ns=ns,
            )
        src = source or f"promote:{reason}"
        # force=True bypasses score so operator can promote after human review
        result = self.write(
            text,
            ns=retained_namespace(ns, suffix=self.trial_suffix),
            score=score if score is not None else float(self.gate.min_score),
            decision=decision or "pass",
            kind=RETAINED_KIND,
            source=src,
            id=id,
            force=True,
        )
        result.reason = f"promote:{reason}"
        # last history entry was from write(); patch reason for audit
        if self.history:
            self.history[-1]["reason"] = result.reason
        return result

    def record_outcome(
        self,
        *,
        chunk_id: str,
        score: float,
        decision: str = "",
        text: str = "",
        ns: str = "",
        source: str = "",
    ) -> WriteResult:
        """Re-evaluate a trial lesson against a later run outcome.

        If the new score passes the gate and *text* is provided, rewrite into
        retained memory. Otherwise return a denied/keep-trial result without
        mutating the store (eviction is left to the operator).
        """
        allowed = self.gate.allows(score, decision or None)
        if allowed and text:
            return self.write(
                text,
                ns=retained_namespace(ns or "proj/lessons", suffix=self.trial_suffix),
                score=score,
                decision=decision or "pass",
                kind=RETAINED_KIND,
                source=source or f"outcome:{chunk_id}",
                id=chunk_id or None,
            )
        result = WriteResult(
            ok=False,
            retained=False,
            trial=not allowed,
            denied=not allowed,
            chunk_id=chunk_id,
            ns=ns,
            kind=TRIAL_KIND if not allowed else "",
            score=float(score),
            min_score=float(self.gate.min_score),
            decision=str(decision or ""),
            reason="outcome_pass_no_text" if allowed else self._deny_reason(float(score), str(decision or "")),
        )
        self._record(result)
        return result

    # ── internals ───────────────────────────────────────────────────────

    def _add(
        self,
        text: str,
        *,
        ns: str,
        kind: str,
        source: str,
        id: Optional[str],
        ts: Optional[float],
    ) -> str:
        kwargs: dict[str, Any] = {
            "ns": ns,
            "kind": kind,
            "source": source,
            "id": id,
        }
        # SqliteMemory accepts ts=; MemorySpine does not — probe gently
        try:
            return self.store.add_text(text, **kwargs, ts=ts if ts is not None else time.time())  # type: ignore[call-arg]
        except TypeError:
            return self.store.add_text(text, **kwargs)

    def _deny_reason(self, score: Optional[float], decision: str) -> str:
        if score is None:
            return "missing_score" if self.gate.fail_closed else "no_score_open"
        if score < float(self.gate.min_score):
            return f"score_below_min ({score:.3f} < {float(self.gate.min_score):.3f})"
        if self.gate.require_pass and decision != "pass":
            return f"decision_not_pass ({decision or 'empty'})"
        return "denied"

    def _record(self, result: WriteResult) -> None:
        entry = result.to_dict()
        entry["ts"] = time.time()
        self.history.append(entry)
