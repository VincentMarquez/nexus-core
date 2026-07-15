"""Tests for action-order stage scheduler (P0.2 / arXiv 2510.13343)."""

from __future__ import annotations

import pytest

from nexus.stages import (
    APPLY_STAGES,
    DEFAULT_STAGES,
    SMOKE_STAGES,
    StageOrderError,
    StageRunner,
    assert_can_run,
    can_run,
    next_stage,
    normalize_stages,
    predecessors,
)


def test_default_and_smoke_orders():
    assert DEFAULT_STAGES[0] == "scout"
    assert "claim_verify" in DEFAULT_STAGES
    assert SMOKE_STAGES == ("mine", "grade", "claim_verify")
    assert APPLY_STAGES == (
        "mine",
        "grade",
        "claim_verify",
        "plan_apply",
        "apply",
    )


def test_apply_slice_runner():
    r = StageRunner.apply_slice()
    assert r.next() == "mine"
    for s in APPLY_STAGES:
        r.mark_complete(s)
    assert r.is_done()


def test_refuse_out_of_order():
    with pytest.raises(StageOrderError, match="predecessors"):
        assert_can_run(SMOKE_STAGES, "grade", completed=[])
    with pytest.raises(StageOrderError, match="predecessors"):
        assert_can_run(SMOKE_STAGES, "claim_verify", completed=["mine"])
    # mine has no predecessors
    assert_can_run(SMOKE_STAGES, "mine", completed=[])
    assert can_run(SMOKE_STAGES, "grade", ["mine"]) is True


def test_runner_progress():
    r = StageRunner.smoke()
    assert r.next() == "mine"
    assert not r.is_done()
    r.mark_complete("mine")
    assert r.next() == "grade"
    r.mark_complete("grade")
    assert r.next() == "claim_verify"
    r.mark_complete("claim_verify")
    assert r.is_done()
    assert r.next() is None
    st = r.status()
    assert st["done"] is True
    assert st["completed"] == ["mine", "grade", "claim_verify"]


def test_runner_refuses_skip():
    r = StageRunner.smoke()
    with pytest.raises(StageOrderError):
        r.mark_complete("claim_verify")
    with pytest.raises(StageOrderError):
        r.mark_complete("grade")


def test_idempotent_mark():
    r = StageRunner.smoke()
    r.mark_complete("mine")
    again = r.mark_complete("mine")
    assert again == ["mine"]
    assert r.completed == ["mine"]


def test_unknown_stage():
    with pytest.raises(StageOrderError, match="unknown"):
        assert_can_run(SMOKE_STAGES, "teleport", completed=[])


def test_predecessors_and_next():
    assert predecessors(SMOKE_STAGES, "claim_verify") == ("mine", "grade")
    assert next_stage(SMOKE_STAGES, ["mine", "grade"]) == "claim_verify"
    assert next_stage(SMOKE_STAGES, list(SMOKE_STAGES)) is None


def test_normalize_dedupes():
    assert normalize_stages(["Mine", "mine", "GRADE"]) == ("mine", "grade")
