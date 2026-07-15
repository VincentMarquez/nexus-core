"""DAG / depends_on step policy (P1.2 multi-agent task DAG)."""

import pytest

from nexus.steps import StepDef, StepPolicy, completed_set


def test_default_has_depends_on():
    p = StepPolicy.default()
    assert p.get(2).depends_on == (1,)
    assert 6 in p.get(8).depends_on and 7 in p.get(8).depends_on
    assert p.has_dag() is True
    p.validate()  # no unknown deps / cycles


def test_topo_default():
    p = StepPolicy.default()
    order = p.topo_numbers()
    assert order[0] == 1
    assert order[-1] == 10
    assert order.index(8) > order.index(6)
    assert order.index(8) > order.index(7)


def test_ready_linear_fallback():
    p = StepPolicy(
        steps=[
            StepDef(1, "a", "a", "operator"),
            StepDef(2, "b", "b", "planner"),
        ]
    )
    assert [s.number for s in p.ready(set(), current_step=0)] == [1]
    assert [s.number for s in p.ready(set(), current_step=1)] == [2]
    assert p.has_dag() is False


def test_ready_dag_parallel():
    p = StepPolicy(
        steps=[
            StepDef(1, "root", "r", "operator"),
            StepDef(2, "left", "l", "planner", depends_on=(1,)),
            StepDef(3, "right", "r", "adversary", depends_on=(1,)),
            StepDef(4, "join", "j", "reviewer", depends_on=(2, 3)),
        ]
    )
    assert [s.number for s in p.ready(set())] == [1]
    assert sorted(s.number for s in p.ready({1})) == [2, 3]
    assert [s.number for s in p.ready({1, 2, 3})] == [4]
    # next_ready is deterministic lowest number
    assert p.next_ready({1}).number == 2
    blocked = p.blocked({1})
    assert [b.number for b in blocked] == [4]
    assert p.prior_keys(p.get(4)) == (2, 3)


def test_completed_set_prefers_outputs():
    assert completed_set({1: {}, 3: {}}, current_step=5) == {1, 3}
    assert completed_set({}, current_step=3) == {1, 2, 3}
    assert completed_set(None, current_step=0) == set()


def test_validate_unknown_dep():
    p = StepPolicy(
        steps=[
            StepDef(1, "a", "a", "operator"),
            StepDef(2, "b", "b", "planner", depends_on=(99,)),
        ]
    )
    with pytest.raises(ValueError, match="unknown step 99"):
        p.validate()


def test_dag_snapshot_and_mermaid():
    p = StepPolicy(
        steps=[
            StepDef(1, "root", "r", "operator"),
            StepDef(2, "left", "l", "planner", depends_on=(1,)),
            StepDef(3, "right", "r", "adversary", depends_on=(1,)),
            StepDef(4, "join", "j", "reviewer", depends_on=(2, 3)),
        ]
    )
    snap = p.dag_snapshot(completed={1}, action_order=["1:root"])
    assert snap["schema"] == "nexus.dag/v1"
    assert snap["ready"] == [2, 3]
    assert snap["n_blocked"] == 1
    assert snap["action_order"] == ["1:root"]
    assert "flowchart" in snap["mermaid"]
    assert "s1 --> s2" in snap["mermaid"]
    assert "s2 --> s4" in snap["mermaid"]
