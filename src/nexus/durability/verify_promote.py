"""Independent verification gate before trust / memory promotion.

Implementer scores alone must not elevate taint → trusted or trial → retained
memory. A separate verifier path (different agent when required) must pass
with score ≥ threshold and optional evidence — zenith independent validation
+ cycgraph promote-gate discipline.

Does not vendor upstream trees; pattern only.

Evidence drivers:
- Intelligent-Internet/zenith — independent validators before closure / promote
- wmcmahan/cycgraph — eval-gated retention; explicit promote with gate reason
- arXiv 2303.16641 — adversarial hierarchy (untrusted until verified)
- NEXUS RubricJudge cross-vendor preference
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .eval_memory import (
    DEFAULT_MIN_SCORE,
    GatedMemoryWriter,
    MemoryWriteDenied,
    WriteResult,
)
from .taint import TaintError, TaintMeta, TaintSet

try:
    from nexus.judge import PASS_THRESHOLD as _PASS
except Exception:  # pragma: no cover
    _PASS = DEFAULT_MIN_SCORE

DEFAULT_VERIFY_MIN_SCORE = float(_PASS)


class VerifyError(PermissionError):
    """Raised when independent verification refuses a promote."""

    def __init__(
        self,
        message: str,
        *,
        implementer: str = "",
        verifier: str = "",
        score: Optional[float] = None,
        decision: str = "",
        reason: str = "",
    ) -> None:
        super().__init__(message)
        self.implementer = implementer
        self.verifier = verifier
        self.score = score
        self.decision = decision
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "VerifyError",
            "message": str(self),
            "implementer": self.implementer,
            "verifier": self.verifier,
            "score": self.score,
            "decision": self.decision,
            "reason": self.reason,
        }


@dataclass
class VerifyResult:
    """Outcome of an independent verification check."""

    ok: bool
    implementer: str = ""
    verifier: str = ""
    score: Optional[float] = None
    decision: str = ""
    reason: str = ""
    cross_agent: bool = False
    evidence: list[str] = field(default_factory=list)
    min_score: float = DEFAULT_VERIFY_MIN_SCORE
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "implementer": self.implementer,
            "verifier": self.verifier,
            "score": self.score,
            "decision": self.decision,
            "reason": self.reason,
            "cross_agent": self.cross_agent,
            "evidence": list(self.evidence),
            "min_score": self.min_score,
            "ts": self.ts,
        }


@dataclass
class IndependentVerify:
    """Gate: separate verifier must pass before promote.

    Parameters
    ----------
    min_score:
        Minimum verifier score (aligned with judge PASS_THRESHOLD).
    require_pass:
        When True, require ``decision == "pass"`` if decision is supplied.
    require_cross_agent:
        When True, implementer and verifier agent ids must differ.
    fail_closed:
        Missing / non-numeric scores are denied (default True).
    require_evidence:
        When True, at least one evidence string/path is required.
    allow_same_agent_degraded:
        When True, same-agent verify is allowed but marked degraded (ok still
        requires score). When False (default), same agent fails if
        require_cross_agent.
    """

    min_score: float = DEFAULT_VERIFY_MIN_SCORE
    require_pass: bool = True
    require_cross_agent: bool = True
    fail_closed: bool = True
    require_evidence: bool = False
    allow_same_agent_degraded: bool = False

    def evaluate(
        self,
        *,
        implementer: str,
        verifier: str,
        score: Optional[float] = None,
        decision: Optional[str] = None,
        evidence: Optional[list[str]] = None,
    ) -> VerifyResult:
        """Return whether independent verification passes (does not promote)."""
        imp = (implementer or "").strip()
        ver = (verifier or "").strip()
        decision_s = str(decision or "").strip().lower()
        ev = [str(e) for e in (evidence or []) if str(e).strip()]
        score_f: Optional[float]
        try:
            score_f = None if score is None else float(score)
        except (TypeError, ValueError):
            score_f = None

        cross = bool(imp and ver and imp != ver)
        min_s = float(self.min_score)

        # identity / independence
        if not ver:
            return VerifyResult(
                ok=False,
                implementer=imp,
                verifier=ver,
                score=score_f,
                decision=decision_s,
                reason="missing_verifier",
                cross_agent=False,
                evidence=ev,
                min_score=min_s,
            )
        if self.require_cross_agent and imp and ver and imp == ver:
            if not self.allow_same_agent_degraded:
                return VerifyResult(
                    ok=False,
                    implementer=imp,
                    verifier=ver,
                    score=score_f,
                    decision=decision_s,
                    reason="same_agent_not_independent",
                    cross_agent=False,
                    evidence=ev,
                    min_score=min_s,
                )
            # degraded path continues to score checks

        if score_f is None:
            if self.fail_closed:
                return VerifyResult(
                    ok=False,
                    implementer=imp,
                    verifier=ver,
                    score=None,
                    decision=decision_s,
                    reason="missing_score",
                    cross_agent=cross,
                    evidence=ev,
                    min_score=min_s,
                )
        elif score_f < min_s:
            return VerifyResult(
                ok=False,
                implementer=imp,
                verifier=ver,
                score=score_f,
                decision=decision_s,
                reason=f"score_below_min ({score_f:.3f} < {min_s:.3f})",
                cross_agent=cross,
                evidence=ev,
                min_score=min_s,
            )

        if self.require_pass and decision is not None and decision_s and decision_s != "pass":
            return VerifyResult(
                ok=False,
                implementer=imp,
                verifier=ver,
                score=score_f,
                decision=decision_s,
                reason=f"decision_not_pass ({decision_s})",
                cross_agent=cross,
                evidence=ev,
                min_score=min_s,
            )

        if self.require_evidence and not ev:
            return VerifyResult(
                ok=False,
                implementer=imp,
                verifier=ver,
                score=score_f,
                decision=decision_s,
                reason="missing_evidence",
                cross_agent=cross,
                evidence=ev,
                min_score=min_s,
            )

        degraded = self.require_cross_agent and imp == ver and self.allow_same_agent_degraded
        reason = "verify_pass_degraded" if degraded else "verify_pass"
        return VerifyResult(
            ok=True,
            implementer=imp,
            verifier=ver,
            score=score_f if score_f is not None else min_s,
            decision=decision_s or "pass",
            reason=reason,
            cross_agent=cross,
            evidence=ev,
            min_score=min_s,
        )

    def require(
        self,
        *,
        implementer: str,
        verifier: str,
        score: Optional[float] = None,
        decision: Optional[str] = None,
        evidence: Optional[list[str]] = None,
    ) -> VerifyResult:
        """Like :meth:`evaluate` but raises :class:`VerifyError` on failure."""
        result = self.evaluate(
            implementer=implementer,
            verifier=verifier,
            score=score,
            decision=decision,
            evidence=evidence,
        )
        if not result.ok:
            raise VerifyError(
                f"independent verify denied: {result.reason}",
                implementer=result.implementer,
                verifier=result.verifier,
                score=result.score,
                decision=result.decision,
                reason=result.reason,
            )
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_score": float(self.min_score),
            "require_pass": bool(self.require_pass),
            "require_cross_agent": bool(self.require_cross_agent),
            "fail_closed": bool(self.fail_closed),
            "require_evidence": bool(self.require_evidence),
            "allow_same_agent_degraded": bool(self.allow_same_agent_degraded),
        }

    @classmethod
    def from_meta(cls, meta: Optional[dict[str, Any]] = None) -> "IndependentVerify":
        meta = meta or {}
        gate = meta.get("verify") if isinstance(meta.get("verify"), dict) else {}
        min_score = meta.get("verify_min_score", gate.get("min_score", DEFAULT_VERIFY_MIN_SCORE))
        try:
            ms = float(min_score)
        except (TypeError, ValueError):
            ms = DEFAULT_VERIFY_MIN_SCORE
        return cls(
            min_score=ms,
            require_pass=bool(meta.get("verify_require_pass", gate.get("require_pass", True))),
            require_cross_agent=bool(
                meta.get("verify_require_cross_agent", gate.get("require_cross_agent", True))
            ),
            fail_closed=bool(meta.get("verify_fail_closed", gate.get("fail_closed", True))),
            require_evidence=bool(
                meta.get("verify_require_evidence", gate.get("require_evidence", False))
            ),
            allow_same_agent_degraded=bool(
                meta.get(
                    "verify_allow_same_agent_degraded",
                    gate.get("allow_same_agent_degraded", False),
                )
            ),
        )


def promote_taint_verified(
    taint: TaintSet,
    key: str,
    *,
    gate: str,
    verify: VerifyResult,
    agent_id: str = "",
    raise_on_deny: bool = True,
) -> Optional[TaintMeta]:
    """Promote taint key to trusted only when *verify* passed.

    Gate string is composed as ``verify:<gate>:<verifier>`` for audit.
    """
    if not verify.ok:
        if raise_on_deny:
            raise VerifyError(
                f"cannot promote taint {key!r}: verify not ok ({verify.reason})",
                implementer=verify.implementer,
                verifier=verify.verifier,
                score=verify.score,
                decision=verify.decision,
                reason=verify.reason,
            )
        return None
    g = (gate or "").strip()
    if not g:
        raise TaintError("promote requires a non-empty gate reason", key=key)
    composed = f"verify:{g}:{verify.verifier or 'anon'}"
    return taint.promote(key, gate=composed, agent_id=agent_id or verify.verifier)


def promote_memory_verified(
    writer: GatedMemoryWriter,
    text: str,
    *,
    ns: str,
    verify: VerifyResult,
    gate_reason: str,
    source: str = "",
    id: Optional[str] = None,
    raise_on_deny: bool = True,
) -> Optional[WriteResult]:
    """Promote text into retained memory only when *verify* passed."""
    if not verify.ok:
        if raise_on_deny:
            raise VerifyError(
                f"cannot promote memory: verify not ok ({verify.reason})",
                implementer=verify.implementer,
                verifier=verify.verifier,
                score=verify.score,
                decision=verify.decision,
                reason=verify.reason,
            )
        return None
    reason = (gate_reason or "").strip()
    if not reason:
        raise MemoryWriteDenied(
            "promote requires a non-empty gate_reason",
            score=verify.score,
            decision=verify.decision,
            ns=ns,
        )
    composed = f"verify:{reason}:{verify.verifier or 'anon'}"
    return writer.promote(
        text,
        ns=ns,
        score=verify.score if verify.score is not None else float(writer.gate.min_score),
        decision=verify.decision or "pass",
        source=source or f"verify_promote:{verify.verifier}",
        id=id,
        gate_reason=composed,
    )
