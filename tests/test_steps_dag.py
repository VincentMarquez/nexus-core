"""DAG / depends_on step policy."""

from nexus.steps import StepDef, StepPolicy


def test_default_has_depends_on():
    p = StepPolicy.default()
    assert p.get(2).depends_on == (1,)
    assert 6 in p.get(8).depends_on and 7 in p.get(8).depends_on


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
