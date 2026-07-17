"""Tests for intermediate state cache + selective replay (SWE-Replay × wshobson)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import state_replay as sr
from nexus.orchestrator import Orchestrator


def _write_plugin(root: Path, plugin_id: str = "demo-plugin") -> Path:
    d = root / "plugins" / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_id,
                "version": "0.1.0",
                "description": "Demo",
                "privilege": "read",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    agents = d / "agents"
    agents.mkdir(exist_ok=True)
    (agents / "demo-agent.md").write_text(
        "---\nname: demo-agent\n---\n\n# Agent\n",
        encoding="utf-8",
    )
    commands = d / "commands"
    commands.mkdir(exist_ok=True)
    (commands / "demo-cmd.md").write_text(
        "---\nname: demo-cmd\n---\n\n# Cmd\n",
        encoding="utf-8",
    )
    skill = d / "skills" / "demo-skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo-skill\n---\n\n# Skill\n",
        encoding="utf-8",
    )
    return d


def test_state_key_and_fingerprint_stable():
    a = sr.state_key(task_id="t1", step_id="s1", kind="kv", name="x", extra="e")
    b = sr.state_key(task_id="t1", step_id="s1", kind="kv", name="x", extra="e")
    c = sr.state_key(task_id="t1", step_id="s2", kind="kv", name="x", extra="e")
    assert a == b
    assert a != c
    assert len(a) == 32
    assert sr.fingerprint({"a": 1, "b": 2}) == sr.fingerprint({"b": 2, "a": 1})
    assert sr.fingerprint({"a": 1}) != sr.fingerprint({"a": 2})


def test_capture_directory_listing(tmp_path: Path):
    sub = tmp_path / "ws"
    sub.mkdir()
    (sub / "a.txt").write_text("hello", encoding="utf-8")
    (sub / "nested").mkdir()
    (sub / "nested" / "b.txt").write_text("world", encoding="utf-8")
    snap = sr.capture_directory(sub)
    assert snap["ok"] is True
    assert snap["n_entries"] >= 2
    paths = {e["path"] for e in snap["entries"]}
    assert any("a.txt" in p for p in paths)
    # No file bodies in the snapshot
    for e in snap["entries"]:
        assert "content" not in e
        assert "body" not in e


def test_capture_marketplace_wshobson_shape(tmp_path: Path):
    _write_plugin(tmp_path)
    snap = sr.capture_marketplace(tmp_path)
    assert snap["ok"] is True
    assert snap["n_plugins"] >= 1
    assert snap["n_components"] >= 3
    kinds = {c["kind"] for c in snap["components"]}
    assert "agent" in kinds
    assert "skill" in kinds
    assert "command" in kinds
    assert snap["source_pattern"] == "wshobson/agents"


def test_state_cache_put_list_get(tmp_path: Path):
    cache = sr.StateCache.open(tmp_path)
    st = cache.capture(
        task_id="task-1",
        kind=sr.KIND_KV,
        payload={"x": 1},
        step_id="step-a",
        name="kv1",
        extra_key="fixed",
    )
    assert st.state_id
    assert st.fingerprint
    rows = cache.list("task-1")
    assert len(rows) == 1
    hit = cache.get("task-1", state_id=st.state_id)
    assert hit is not None
    assert hit.payload["x"] == 1
    hit2 = cache.lookup_key("task-1", st.key)
    assert hit2 is not None
    assert hit2.state_id == st.state_id
    idx = cache.index("task-1")
    assert idx["n_states"] == 1
    assert idx["by_kind"].get("kv") == 1


def test_capture_dir_and_market_via_cache(tmp_path: Path):
    _write_plugin(tmp_path)
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "f.txt").write_text("x", encoding="utf-8")
    cache = sr.StateCache.open(tmp_path)
    d = cache.capture_dir("t-dir", ws, step_id="s0")
    m = cache.capture_market("t-dir", step_id="s1")
    assert d.kind == sr.KIND_DIRECTORY
    assert m.kind == sr.KIND_MARKETPLACE
    assert (m.payload or {}).get("n_components", 0) >= 3
    stats = cache.stats("t-dir")
    assert stats["n_states"] == 2


def test_capture_component_step(tmp_path: Path):
    cache = sr.StateCache.open(tmp_path)
    st = cache.capture_component_step(
        "t-comp",
        kind="agent",
        name="demo-agent",
        plugin_id="demo-plugin",
        step_id="plan-1",
        payload={"status": "ready"},
    )
    assert st.kind == "agent"
    assert st.surface == "agent"
    assert st.name == "demo-agent"
    assert st.payload["payload"]["status"] == "ready"


def test_select_replay_filters_and_strategies(tmp_path: Path):
    cache = sr.StateCache.open(tmp_path)
    cache.capture(
        task_id="t-sel",
        kind=sr.KIND_DIRECTORY,
        payload={"n": 1},
        step_id="s0",
        extra_key="d1",
    )
    cache.capture_component_step(
        "t-sel", kind="agent", name="a1", step_id="s1", payload={"v": 1}
    )
    cache.capture_component_step(
        "t-sel", kind="skill", name="sk1", step_id="s2", payload={"v": 2}
    )
    cache.capture_component_step(
        "t-sel", kind="agent", name="a1", step_id="s3", payload={"v": 3}
    )
    cache.capture(
        task_id="t-sel",
        kind=sr.KIND_MARKETPLACE,
        payload={"n_plugins": 1},
        step_id="s4",
        extra_key="m1",
    )

    plan_all = sr.build_replay_plan(cache, "t-sel", strategy=sr.STRATEGY_ALL)
    assert len(plan_all.states) == 5

    plan_agents = sr.build_replay_plan(
        cache, "t-sel", surfaces=["agent"], strategy=sr.STRATEGY_ALL
    )
    assert len(plan_agents.states) == 2
    assert all(s.surface == "agent" for s in plan_agents.states)

    plan_latest = sr.build_replay_plan(
        cache, "t-sel", strategy=sr.STRATEGY_LATEST_PER_SURFACE
    )
    # directory, agent, skill, marketplace → 4 surfaces/kinds
    surfaces = {s.surface or s.kind for s in plan_latest.states}
    assert "agent" in surfaces
    assert "skill" in surfaces
    # latest agent has payload v=3
    agent_st = next(s for s in plan_latest.states if (s.surface or s.kind) == "agent")
    assert agent_st.payload["payload"]["v"] == 3

    plan_window = sr.build_replay_plan(
        cache,
        "t-sel",
        from_step="s1",
        to_step="s3",
        strategy=sr.STRATEGY_WINDOW,
    )
    assert all(s.step_id in {"s1", "s2", "s3"} for s in plan_window.states)

    plan_cap = sr.build_replay_plan(cache, "t-sel", max_states=2)
    assert len(plan_cap.states) == 2
    assert plan_cap.skipped >= 3


def test_get_or_capture_hits(tmp_path: Path):
    cache = sr.StateCache.open(tmp_path)
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"ok": True, "value": calls["n"]}

    r1 = sr.get_or_capture(
        cache,
        task_id="t-goc",
        kind=sr.KIND_KV,
        step_id="s",
        name="x",
        extra_key="stable",
        compute=compute,
    )
    assert r1["cache_hit"] is False
    assert r1["stored"] is True
    assert calls["n"] == 1

    r2 = sr.get_or_capture(
        cache,
        task_id="t-goc",
        kind=sr.KIND_KV,
        step_id="s",
        name="x",
        extra_key="stable",
        compute=compute,
    )
    assert r2["cache_hit"] is True
    assert calls["n"] == 1  # no recompute
    assert r2["result"]["value"] == 1


def test_maybe_capture_for_task_disabled(tmp_path: Path):
    assert sr.maybe_capture_for_task(tmp_path, "t1", None) is None
    assert sr.maybe_capture_for_task(tmp_path, "t1", {}) is None
    assert sr.maybe_capture_for_task(tmp_path, "t1", {"other": True}) is None


def test_maybe_capture_for_task_marketplace_and_dir(tmp_path: Path):
    _write_plugin(tmp_path)
    ws = tmp_path / "out"
    ws.mkdir()
    (ws / "a.txt").write_text("z", encoding="utf-8")
    out = sr.maybe_capture_for_task(
        tmp_path,
        "t-hook",
        {
            "state_replay": True,
            "capture_dir": "out",
        },
        step_id="init",
    )
    assert out is not None
    assert out["ok"] is True
    assert out["n_captured"] == 2
    kinds = {c["kind"] for c in out["captured"]}
    assert "marketplace" in kinds
    assert "directory" in kinds
    cache = sr.StateCache.open(tmp_path)
    assert len(cache.list("t-hook")) == 2


def test_orchestrator_state_replay_meta(tmp_path: Path):
    _write_plugin(tmp_path)
    orch = Orchestrator(tmp_path)
    status = orch.run_task(
        "demo with state replay",
        agent_mode="fake",
        sync_fake=True,
        meta={"state_replay": True, "capture_dir": "plugins"},
        task_id="orch-sr-1",
    )
    assert status["task_id"] == "orch-sr-1"
    # Envelope should record state_replay init
    from nexus.orchestrator import load_envelope

    env = load_envelope(tmp_path, "orch-sr-1")
    assert env is not None
    assert env.meta.get("state_replay") is True
    init = env.meta.get("state_replay_init") or {}
    assert init.get("n_captured", 0) >= 1
    assert env.meta.get("state_replay_paper") == "arxiv:2601.22129v2"
    # Cache on disk
    cache = sr.StateCache.open(tmp_path)
    assert len(cache.list("orch-sr-1")) >= 1


def test_clear_and_stats(tmp_path: Path):
    cache = sr.StateCache.open(tmp_path)
    cache.capture(task_id="t-clr", kind=sr.KIND_KV, payload={"a": 1}, extra_key="k")
    st = cache.stats("t-clr")
    assert st["n_states"] == 1
    out = cache.clear("t-clr")
    assert out["ok"] is True
    assert cache.list("t-clr") == []


def test_cli_capture_and_select(tmp_path: Path):
    _write_plugin(tmp_path)
    rc = sr.main(
        [
            "--workdir",
            str(tmp_path),
            "capture-market",
            "--task-id",
            "cli-t",
            "--step-id",
            "s0",
            "--json",
        ]
    )
    assert rc == 0
    rc = sr.main(
        [
            "--workdir",
            str(tmp_path),
            "select",
            "--task-id",
            "cli-t",
            "--kinds",
            "marketplace",
            "--json",
        ]
    )
    assert rc == 0
    rc = sr.main(["--workdir", str(tmp_path), "stats", "--task-id", "cli-t", "--json"])
    assert rc == 0


def test_invalid_task_id():
    with pytest.raises(sr.StateReplayError):
        sr.sanitize_task_id("../evil")
    with pytest.raises(sr.StateReplayError):
        sr.normalize_kind("not-a-kind")


def test_replay_plan_summary_dict(tmp_path: Path):
    cache = sr.StateCache.open(tmp_path)
    cache.capture(
        task_id="t-sum",
        kind=sr.KIND_OBSERVE,
        payload={"note": "hi"},
        step_id="s0",
        extra_key="o1",
    )
    plan = sr.build_replay_plan(cache, "t-sum")
    d = plan.to_dict()
    assert d["schema"] == sr.SCHEMA
    assert d["paper"] == sr.PAPER
    assert d["n_states"] == 1
    s = plan.summary()
    assert "states" not in s
    assert s["n_states"] == 1
