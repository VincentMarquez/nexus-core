"""Unit tests for zero-trust state slicing (no network)."""

from __future__ import annotations

import pytest

from nexus.durability import (
    DurableAgent,
    RunBudget,
    SliceError,
    StateSlice,
    is_protected_key,
    slice_from_step,
)


def test_zero_trust_default_sees_nothing():
    sl = StateSlice()  # empty read/write
    state = {"goal": "ship", "secret": "x", "_taint_registry": {}}
    assert sl.view(state) == {}
    assert not sl.can_read("goal")
    assert not sl.can_write("goal")
    with pytest.raises(SliceError) as ei:
        sl.require_write("goal")
    assert ei.value.op == "write"
    assert ei.value.key == "goal"


def test_read_keys_filter_view():
    sl = StateSlice.from_keys(read_keys=["goal", "plan"], write_keys=["plan"])
    state = {"goal": "ship", "plan": "a", "secret": "nope", "_taint_registry": {"x": 1}}
    view = sl.view(state)
    assert view == {"goal": "ship", "plan": "a"}
    assert "secret" not in view
    assert "_taint_registry" not in view


def test_wildcard_read_hides_protected():
    sl = StateSlice.open_all(agent_id="system")
    state = {"goal": 1, "_taint_registry": {"a": 1}, "_internal": True}
    view = sl.view(state)
    assert view["goal"] == 1
    assert "_taint_registry" not in view
    assert "_internal" not in view


def test_strict_merge_rejects_undeclared_write():
    sl = StateSlice.from_keys(write_keys=["plan"], agent_id="planner")
    state: dict = {"goal": "x"}
    sl.merge_writes(state, {"plan": "ok"})
    assert state["plan"] == "ok"
    with pytest.raises(SliceError) as ei:
        sl.merge_writes(state, {"artifacts": "bad"})
    assert ei.value.key == "artifacts"
    assert "artifacts" not in state


def test_non_strict_filter_drops_forbidden():
    sl = StateSlice.from_keys(write_keys=["plan"])
    state: dict = {}
    sl.merge_writes(state, {"plan": 1, "secret": 2}, strict=False)
    assert state == {"plan": 1}


def test_protected_keys_never_writable():
    sl = StateSlice.open_all()
    assert is_protected_key("_taint_registry")
    assert is_protected_key("_anything")
    with pytest.raises(SliceError):
        sl.require_write("_taint_registry")
    with pytest.raises(SliceError):
        sl.apply_write({}, "_internal", 1)


def test_from_meta_and_serde():
    sl = StateSlice.from_meta(
        {"read_keys": ["a"], "write_keys": ["b"], "agent_id": "w"},
    )
    assert sl.can_read("a") and sl.can_write("b")
    assert not sl.can_read("b")
    d = sl.to_dict()
    sl2 = StateSlice.from_dict(d)
    assert sl2.read_keys == sl.read_keys
    assert sl2.write_keys == sl.write_keys


def test_nested_state_slice_meta():
    sl = StateSlice.from_meta(
        {"state_slice": {"read_keys": ["goal"], "write_keys": ["notes"]}},
        agent_id="logger",
    )
    assert sl.can_read("goal") and sl.can_write("notes")
    assert sl.agent_id == "logger"


def test_slice_from_step_output_keys():
    class FakeStep:
        output_keys = ("artifacts", "notes")
        agent = "implementer"

    sl = slice_from_step(FakeStep())
    assert sl.can_write("artifacts") and sl.can_write("notes")
    assert not sl.can_write("secret")
    assert sl.agent_id == "implementer"


def test_durable_agent_enforces_slice():
    agent = DurableAgent(
        budget=RunBudget(max_steps=10),
        slice=StateSlice.from_keys(
            read_keys=["goal"],
            write_keys=["plan"],
            agent_id="planner",
        ),
        state={"goal": "ship it", "secret": "hidden"},
        agent_id="planner",
    )
    assert agent.view() == {"goal": "ship it"}
    with pytest.raises(SliceError):
        agent.read("secret")
    assert agent.read("goal") == "ship it"
    agent.write("plan", {"steps": 3})
    assert agent.state["plan"]["steps"] == 3
    with pytest.raises(SliceError):
        agent.write("secret", "leak")


def test_durable_agent_run_step_slice_denied():
    agent = DurableAgent(
        budget=RunBudget(max_steps=5),
        slice=StateSlice.from_keys(write_keys=["ok_key"], agent_id="w"),
        agent_id="w",
    )
    r = agent.run_step(lambda: {"x": 1}, write_key="forbidden")
    assert not r.ok
    assert r.slice_denied
    assert "forbidden" in r.error or "write" in r.error.lower()
    assert "forbidden" not in agent.state

    r2 = agent.run_step(lambda: {"x": 2}, write_key="ok_key")
    assert r2.ok
    assert agent.state["ok_key"] == {"x": 2}


def test_open_agent_backward_compatible():
    """Default DurableAgent (no explicit slice) still allows ordinary writes."""
    agent = DurableAgent(budget=RunBudget(max_steps=3))
    agent.write("anything", 42)
    assert agent.state["anything"] == 42
    # protected still blocked
    with pytest.raises(SliceError):
        agent.write("_taint_registry", {})


def test_from_meta_slice_optional():
    open_agent = DurableAgent.from_meta({"max_steps": 2}, use_env=False)
    assert not open_agent._slice_explicit
    open_agent.write("x", 1)

    scoped = DurableAgent.from_meta(
        {"max_steps": 2, "read_keys": ["a"], "write_keys": ["b"]},
        use_env=False,
        agent_id="scoped",
    )
    assert scoped._slice_explicit
    assert scoped.view() == {}
    scoped.state["a"] = 9
    assert scoped.view() == {"a": 9}
    with pytest.raises(SliceError):
        scoped.write("c", 3)


def test_meta_patch_includes_slice_when_explicit():
    agent = DurableAgent(
        budget=RunBudget(max_steps=1),
        slice=StateSlice.from_keys(read_keys=["g"], write_keys=["p"]),
    )
    patch = agent.meta_patch()
    assert "state_slice" in patch
    assert "g" in patch["state_slice"]["read_keys"]
