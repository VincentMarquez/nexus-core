"""Unit tests for independent verify-before-promote (zenith + cycgraph)."""

from __future__ import annotations

import pytest

from nexus.durability import (
    DEFAULT_VERIFY_MIN_SCORE,
    EvalGate,
    GatedMemoryWriter,
    IndependentVerify,
    TaintError,
    TaintLevel,
    TaintSet,
    VerifyError,
    promote_memory_verified,
    promote_taint_verified,
)
from nexus.memory import MemorySpine


def test_default_min_score_matches_judge():
    from nexus.judge import PASS_THRESHOLD

    assert DEFAULT_VERIFY_MIN_SCORE == PASS_THRESHOLD
    assert IndependentVerify().min_score == PASS_THRESHOLD


def test_cross_agent_required():
    v = IndependentVerify(require_cross_agent=True, min_score=0.7)
    bad = v.evaluate(
        implementer="coder",
        verifier="coder",
        score=0.95,
        decision="pass",
    )
    assert not bad.ok
    assert bad.reason == "same_agent_not_independent"

    good = v.evaluate(
        implementer="coder",
        verifier="reviewer",
        score=0.95,
        decision="pass",
    )
    assert good.ok
    assert good.cross_agent
    assert good.reason == "verify_pass"


def test_score_and_decision_and_evidence_gates():
    v = IndependentVerify(
        min_score=0.7,
        require_pass=True,
        require_evidence=True,
        require_cross_agent=True,
    )
    assert not v.evaluate(
        implementer="a", verifier="b", score=0.5, decision="pass", evidence=["e"]
    ).ok
    assert not v.evaluate(
        implementer="a", verifier="b", score=0.9, decision="revise", evidence=["e"]
    ).ok
    assert not v.evaluate(
        implementer="a", verifier="b", score=0.9, decision="pass", evidence=[]
    ).ok
    assert not v.evaluate(
        implementer="a", verifier="b", score=None, decision="pass", evidence=["e"]
    ).ok  # fail-closed
    assert v.evaluate(
        implementer="a",
        verifier="b",
        score=0.9,
        decision="pass",
        evidence=["results/demo.txt"],
    ).ok


def test_require_raises():
    v = IndependentVerify()
    with pytest.raises(VerifyError) as ei:
        v.require(implementer="x", verifier="y", score=0.1)
    assert ei.value.reason.startswith("score_below_min")
    r = v.require(implementer="x", verifier="y", score=0.9, decision="pass")
    assert r.ok


def test_same_agent_degraded_allowed():
    v = IndependentVerify(
        require_cross_agent=True,
        allow_same_agent_degraded=True,
        min_score=0.7,
    )
    r = v.evaluate(implementer="solo", verifier="solo", score=0.8, decision="pass")
    assert r.ok and r.reason == "verify_pass_degraded"
    assert not r.cross_agent


def test_promote_taint_verified():
    t = TaintSet()
    t.stamp("digest", level=TaintLevel.MINED, source="scout_repos/foo")
    with pytest.raises(TaintError):
        t.require_trusted("digest")

    v = IndependentVerify()
    denied = v.evaluate(implementer="coder", verifier="coder", score=0.99, decision="pass")
    with pytest.raises(VerifyError):
        promote_taint_verified(t, "digest", gate="human-board", verify=denied)

    ok = v.evaluate(
        implementer="coder",
        verifier="reviewer",
        score=0.9,
        decision="pass",
        evidence=["tests green"],
    )
    meta = promote_taint_verified(t, "digest", gate="ops-board", verify=ok, agent_id="reviewer")
    assert meta is not None
    assert meta.level == TaintLevel.TRUSTED
    assert meta.gate.startswith("verify:ops-board:reviewer")
    assert meta.promoted_from == "mined"
    t.require_trusted("digest")  # no raise


def test_promote_taint_soft_deny():
    from nexus.durability import VerifyResult

    t = TaintSet()
    t.stamp("k", level=TaintLevel.MINED)
    bad = VerifyResult(
        ok=False,
        implementer="a",
        verifier="b",
        score=0.1,
        decision="fail",
        reason="stub",
    )
    assert (
        promote_taint_verified(t, "k", gate="g", verify=bad, raise_on_deny=False) is None
    )


def test_promote_memory_verified():
    store = MemorySpine()
    writer = GatedMemoryWriter(store=store, gate=EvalGate(min_score=0.7, allow_trial=True))
    # trial write first
    writer.write("maybe lesson", ns="proj/lessons", score=0.2)
    assert store.search("maybe", ns="proj/lessons", k=3) == []

    v = IndependentVerify()
    bad = v.evaluate(implementer="coder", verifier="coder", score=0.99, decision="pass")
    with pytest.raises(VerifyError):
        promote_memory_verified(
            writer,
            "maybe lesson",
            ns="proj/lessons",
            verify=bad,
            gate_reason="board",
        )

    ok = v.evaluate(
        implementer="coder",
        verifier="reviewer",
        score=0.88,
        decision="pass",
    )
    r = promote_memory_verified(
        writer,
        "maybe lesson",
        ns="proj/lessons",
        verify=ok,
        gate_reason="board",
        id="lesson-1",
    )
    assert r is not None and r.retained
    assert r.reason.startswith("promote:verify:board:reviewer")
    hits = store.search("maybe lesson", ns="proj/lessons", k=3)
    assert any(h["id"] == "lesson-1" for h in hits)


def test_from_meta():
    v = IndependentVerify.from_meta(
        {
            "verify_min_score": 0.8,
            "verify_require_evidence": True,
            "verify": {"require_cross_agent": False},
        }
    )
    assert v.min_score == 0.8
    assert v.require_evidence is True
    assert v.require_cross_agent is False
