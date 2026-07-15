"""Unit tests for principled stopping (zenith gap / no-progress discipline)."""

from __future__ import annotations

import pytest

from nexus.durability import (
    REASON_ABORT,
    REASON_BUDGET,
    REASON_CONTINUE,
    REASON_GAPS_CLOSED,
    REASON_MAX_CYCLES,
    REASON_NO_PROGRESS,
    GapItem,
    PrincipledStop,
    StopPolicy,
    cycle_progressed,
    default_stop_path,
)


def test_policy_from_meta_and_dict():
    p = StopPolicy.from_meta(
        {
            "stop_max_no_progress": 5,
            "stop_max_cycles": 10,
            "stop_when_gaps_closed": False,
            "stop": {"stop_on_tests_red": True},
        }
    )
    assert p.max_no_progress == 5
    assert p.max_cycles == 10
    assert p.stop_when_gaps_closed is False
    assert p.stop_on_tests_red is True
    assert StopPolicy.from_dict(p.to_dict()).max_no_progress == 5


def test_register_close_reopen_gaps():
    s = PrincipledStop()
    s.register_gap("P0.4", "principled stop")
    s.register_gap("P0.5", "independent verify")
    assert s.gap_counts() == {"open": 2, "closed": 0, "total": 2}
    s.close_gap("P0.4", evidence="landed")
    assert s.gaps["P0.4"].open is False
    assert s.gaps["P0.4"].evidence == "landed"
    s.reopen_gap("P0.4", evidence="residual gap found")
    assert s.gaps["P0.4"].open is True
    with pytest.raises(KeyError):
        s.close_gap("missing")
    with pytest.raises(ValueError):
        s.register_gap("")


def test_sync_gaps_close_missing():
    s = PrincipledStop()
    s.register_gap("a")
    s.register_gap("b")
    s.sync_gaps([{"id": "a", "description": "keep"}], close_missing=True)
    assert s.gaps["a"].open is True
    assert s.gaps["b"].open is False


def test_stop_when_all_gaps_closed():
    s = PrincipledStop(policy=StopPolicy(max_no_progress=99, stop_when_gaps_closed=True))
    s.register_gap("g1")
    d = s.record_cycle(progressed=True)
    assert not d.stop
    assert d.reason == REASON_CONTINUE
    s.close_gap("g1", evidence="done")
    d = s.record_cycle(progressed=True)
    assert d.stop and d.reason == REASON_GAPS_CLOSED


def test_no_progress_thrash_stop():
    s = PrincipledStop(policy=StopPolicy(max_no_progress=3, stop_when_gaps_closed=False))
    s.register_gap("still-open")  # open gap should not prevent no-progress stop
    assert not s.record_cycle(progressed=False).stop
    assert not s.record_cycle(progressed=False).stop
    d = s.record_cycle(progressed=False)
    assert d.stop and d.reason == REASON_NO_PROGRESS
    assert d.no_progress_streak == 3
    # progress resets streak
    s2 = PrincipledStop(policy=StopPolicy(max_no_progress=2, stop_when_gaps_closed=False))
    s2.record_cycle(progressed=False)
    s2.record_cycle(progressed=True)
    assert s2.no_progress_streak == 0
    assert not s2.record_cycle(progressed=False).stop


def test_max_cycles_and_budget_and_abort():
    s = PrincipledStop(policy=StopPolicy(max_cycles=2, max_no_progress=99, stop_when_gaps_closed=False))
    assert not s.record_cycle(progressed=True).stop
    d = s.record_cycle(progressed=True)
    assert d.stop and d.reason == REASON_MAX_CYCLES

    s2 = PrincipledStop(policy=StopPolicy(max_no_progress=99, stop_on_budget=True))
    d = s2.evaluate(progressed=True, budget_ok=False)
    assert d.stop and d.reason == REASON_BUDGET

    s3 = PrincipledStop()
    d = s3.abort("operator halt")
    assert d.stop and d.reason == REASON_ABORT
    assert "operator" in d.detail


def test_tests_red_optional():
    s = PrincipledStop(policy=StopPolicy(stop_on_tests_red=True, max_no_progress=99))
    d = s.evaluate(progressed=True, tests_ok=False)
    assert d.stop and d.reason == "tests_red"
    s2 = PrincipledStop(policy=StopPolicy(stop_on_tests_red=False, max_no_progress=99))
    assert not s2.evaluate(progressed=True, tests_ok=False).stop


def test_empty_gap_board_does_not_premature_stop():
    """Without registered gaps, don't stop for gaps_closed (avoid premature stop)."""
    s = PrincipledStop(policy=StopPolicy(max_no_progress=99, stop_when_gaps_closed=True))
    d = s.record_cycle(progressed=True)
    assert not d.stop
    assert d.reason == REASON_CONTINUE


def test_persist_roundtrip(tmp_path):
    path = default_stop_path(tmp_path)
    s = PrincipledStop(policy=StopPolicy(max_no_progress=4))
    s.register_gap("x", "desc")
    s.record_cycle(progressed=False, note="n1")
    s.save(path)
    loaded = PrincipledStop.load(path)
    assert loaded.cycle == 1
    assert loaded.no_progress_streak == 1
    assert "x" in loaded.gaps
    assert loaded.policy.max_no_progress == 4
    assert loaded.history and loaded.history[0].get("note") == "n1"
    # missing file → fresh
    assert PrincipledStop.load(tmp_path / "nope.json").cycle == 0


def test_cycle_progressed_heuristic():
    assert not cycle_progressed({})
    assert not cycle_progressed({"blocked": "budget"})
    assert cycle_progressed({"progressed": True})
    assert cycle_progressed(
        {"steps": [{"step": "self_approve_apply", "ok": True, "apply": {"status": "completed"}}]}
    )
    assert cycle_progressed(
        {"steps": [{"step": "publish_github", "pushed": True}]}
    )
    assert not cycle_progressed(
        {"steps": [{"step": "self_approve_apply", "skipped": "self_approve=false"}]}
    )
    assert not cycle_progressed(
        {"steps": [{"step": "mine", "used": 3}, {"step": "improvements_log", "path": "/x"}]}
    )
    assert cycle_progressed({"applied": {"status": "ok"}})


def test_gap_item_from_dict():
    g = GapItem.from_dict({"id": "a", "description": "d", "open": False})
    assert g.id == "a" and g.open is False
    assert "id" in g.to_dict()
