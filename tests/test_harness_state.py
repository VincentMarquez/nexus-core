"""Tests for shared verifiable harness state (arXiv 2605.18747 × wshobson)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import harness_state as hs
from nexus.harness_state import (
    PAPER,
    SCHEMA,
    SOURCE_PATTERN,
    ActiveAgent,
    HarnessError,
    HarnessState,
    default_pipeline_agents,
    ensure_json_value,
    format_brief,
    maybe_init_for_task,
    plan_for_orchestrator,
)


def _write_plugin(
    root: Path,
    plugin_id: str = "demo-plugin",
    *,
    agent_name: str = "durable-operator",
    skill_name: str = "demo-skill",
    command_name: str = "demo-cmd",
) -> Path:
    d = root / "plugins" / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_id,
                "version": "0.1.0",
                "description": "Harness state test plugin",
                "privilege": "read",
                "tags": ["test", "harness"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    agents = d / "agents"
    agents.mkdir(exist_ok=True)
    (agents / f"{agent_name}.md").write_text(
        f"---\nname: {agent_name}\n---\n\n# {agent_name}\n",
        encoding="utf-8",
    )
    commands = d / "commands"
    commands.mkdir(exist_ok=True)
    (commands / f"{command_name}.md").write_text(
        f"---\nname: {command_name}\n---\n\n# /{command_name}\n",
        encoding="utf-8",
    )
    skill = d / "skills" / skill_name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {skill_name}\n---\n\n# Skill {skill_name}\n",
        encoding="utf-8",
    )
    return d


# ── pure unit ───────────────────────────────────────────────────────────────


def test_create_register_and_active_ids():
    state = HarnessState.create("t1", agents=["planner", "implementer"])
    assert state.schema == SCHEMA
    assert state.paper == PAPER
    assert state.source_pattern == SOURCE_PATTERN
    assert set(state.active_ids()) == {"planner", "implementer"}
    assert state.seq == 2  # one register event each


def test_shared_put_get_versioning():
    state = HarnessState.create("t2", agents=["a", "b"])
    e1 = state.put("goal", "ship it", agent="a")
    assert e1.version == 1
    assert state.get("goal") == "ship it"
    e2 = state.put("goal", "ship it v2", agent="b")
    assert e2.version == 2
    assert e2.writer == "b"
    entry = state.get_entry("goal")
    assert entry is not None and entry.version == 2
    assert state.shared_view()["goal"] == "ship it v2"


def test_put_requires_registered_active_agent():
    state = HarnessState.create("t3", agents=["a"])
    with pytest.raises(HarnessError) as ei:
        state.put("k", 1, agent="ghost")
    assert ei.value.code == "unknown_agent"

    state.set_status("a", "done")
    with pytest.raises(HarnessError) as ei2:
        state.put("k", 1, agent="a")
    assert ei2.value.code == "agent_not_active"

    # allow inactive when require_active=False
    state.put("k", 1, agent="a", require_active=False)
    assert state.get("k") == 1


def test_content_hash_stable_and_changes_on_mutation():
    state = HarnessState.create("t4", agents=["x", "y"])
    h1 = state.content_hash()
    h2 = state.content_hash()
    assert h1 == h2
    assert len(h1) == 64

    state.put("flag", True, agent="x")
    h3 = state.content_hash()
    assert h3 != h1

    # round-trip preserves hash of agents+shared (seq included)
    back = HarnessState.from_dict(state.to_dict())
    assert back.content_hash() == state.content_hash()


def test_verify_ok_and_hash_mismatch():
    state = plan_for_orchestrator(task_id="t5", agents=["planner", "tester"])
    report = state.verify()
    assert report["ok"] is True
    assert report["n_active"] == 2
    assert report["content_hash"] == state.content_hash()

    bad = state.verify(expected_hash="0" * 64)
    assert bad["ok"] is False
    assert any("hash_mismatch" in i for i in bad["issues"])

    with pytest.raises(HarnessError) as ei:
        state.assert_verified(expected_hash="deadbeef")
    assert ei.value.code == "verify_failed"


def test_verify_orphan_writer():
    state = HarnessState.create("t6", agents=["a"])
    state.put("k", 1, agent="a")
    # forge orphan writer
    state.shared["k"].writer = "not-on-roster"
    report = state.verify(check_writers=True)
    assert report["ok"] is False
    assert any("orphan_writer" in i for i in report["issues"])


def test_unregister_and_delete():
    state = HarnessState.create("t7", agents=["a", "b"])
    state.put("tmp", 1, agent="a")
    assert state.delete("tmp", agent="b") is True
    assert state.get("tmp", default="gone") == "gone"
    state.unregister("a", reason="done")
    assert state.agents["a"].status == "left"
    assert "a" not in state.active_ids()


def test_protected_and_invalid_keys():
    state = HarnessState.create("t8", agents=["a"])
    with pytest.raises(HarnessError) as ei:
        state.put("_schema", 1, agent="a")
    assert ei.value.code == "protected_key"
    with pytest.raises(HarnessError):
        state.put("", 1, agent="a")
    with pytest.raises(HarnessError):
        sanitize = hs.sanitize_agent_id
        sanitize("../etc")
    with pytest.raises(HarnessError) as ei_key:
        hs.sanitize_key("a/../b")
    assert ei_key.value.code == "invalid_key"


def test_active_agent_catalog_id():
    ag = ActiveAgent(
        agent_id="durable-operator",
        surface="agent",
        plugin_id="nexus-durable",
    )
    assert ag.catalog_id == "agent:durable-operator@nexus-durable"
    bare = ActiveAgent(agent_id="planner", surface="agent")
    assert bare.catalog_id == "agent:planner"


def test_serde_to_meta_truncates_events():
    state = HarnessState.create("t9", agents=["a"], meta={"x": 1})
    state.max_events = 500
    for i in range(50):
        state.put(f"k{i}", i, agent="a")
    meta = state.to_meta()
    assert meta["schema"] == SCHEMA
    assert meta.get("events_truncated") is True
    assert len(meta["events"]) == 40
    # from_dict still works
    back = HarnessState.from_dict(meta)
    assert back.task_id == "t9"
    assert "a" in back.agents


def test_format_brief_contains_hash_and_agents():
    state = plan_for_orchestrator(task_id="brief-1")
    state.put("phase", "localize", agent="planner")
    text = format_brief(state)
    assert "harness state" in text
    assert "planner" in text
    assert "hash=" in text
    assert PAPER in text or "2605.18747" in text


def test_default_pipeline_agents():
    roster = default_pipeline_agents()
    assert "implementer" in roster
    assert "adversary" in roster
    assert len(roster) >= 4


def test_reject_non_json_value_at_put():
    state = HarnessState.create("json-1", agents=["a"])
    with pytest.raises(HarnessError) as ei:
        state.put("bad", {1, 2, 3}, agent="a")
    assert ei.value.code == "value_not_json"
    with pytest.raises(HarnessError):
        state.put("nan", float("nan"), agent="a")
    # JSON-native still works
    state.put("ok", {"nested": [1, True, None]}, agent="a")
    assert state.get("ok")["nested"] == [1, True, None]


def test_put_get_defensive_copy():
    state = HarnessState.create("alias-1", agents=["a"])
    nested = {"x": 1}
    state.put("blob", nested, agent="a")
    nested["x"] = 99  # must not mutate stored value
    assert state.get("blob")["x"] == 1
    got = state.get("blob")
    got["x"] = 42
    assert state.get("blob")["x"] == 1
    h1 = state.content_hash()
    # ensure_json_value is the public validator
    assert ensure_json_value({"a": 1}) == {"a": 1}


def test_reregister_merges_metadata():
    state = HarnessState.create("reg-1")
    state.register(
        "a",
        privilege="admin",
        plugin_id="core",
        role="lead",
        surface="agent",
    )
    assert state.agents["a"].privilege == "admin"
    # bare re-register must not wipe privilege/role/plugin
    state.register("a")
    ag = state.agents["a"]
    assert ag.privilege == "admin"
    assert ag.plugin_id == "core"
    assert ag.role == "lead"
    assert ag.status == "active"
    # explicit override is auditable
    state.register("a", privilege="read")
    assert state.agents["a"].privilege == "read"
    last = state.events[-1]
    assert last.detail.get("changed", {}).get("privilege", {}).get("from") == "admin"


def test_expected_version_cas_and_monotonic_after_delete():
    state = HarnessState.create("cas-1", agents=["a", "b"])
    e1 = state.put("k", "v1", agent="a")
    assert e1.version == 1
    with pytest.raises(HarnessError) as ei:
        state.put("k", "stale", agent="b", expected_version=0)
    assert ei.value.code == "version_conflict"
    e2 = state.put("k", "v2", agent="b", expected_version=1)
    assert e2.version == 2
    assert state.delete("k", agent="a") is True
    # version counter survives delete — re-put is v3, not v1
    e3 = state.put("k", "v3", agent="a", expected_version=2)
    assert e3.version == 3
    # wrong CAS after delete
    with pytest.raises(HarnessError) as ei2:
        state.put("k", "nope", agent="a", expected_version=1)
    assert ei2.value.code == "version_conflict"


def test_max_events_zero_clamps_not_unbounded():
    state = HarnessState.create("cap-1", agents=["a"])
    state.max_events = 0  # __post_init__ already ran; clamp in _emit / field
    # force clamp like constructor would
    state.__post_init__()
    assert state.max_events >= 1
    for i in range(20):
        state.put(f"k{i}", i, agent="a")
    assert len(state.events) <= state.max_events


def test_from_dict_surfaces_deserialization_drops():
    state = HarnessState.create("drop-1", agents=["a"])
    state.put("ok", 1, agent="a")
    d = state.to_dict()
    d["agents"]["bad"] = {"agent_id": "../evil"}
    d["shared"]["nope"] = {"key": "_secret", "value": 1}
    back = HarnessState.from_dict(d)
    assert (back.meta or {}).get("deserialization_drops", 0) >= 1
    report = back.verify()
    assert report["ok"] is False
    assert any("deserialization_drops" in i for i in report["issues"])


def test_harness_error_to_dict_uses_class_name():
    err = HarnessError("x", code="c", key="k", agent="a")
    d = err.to_dict()
    assert d["error"] == "HarnessError"
    assert d["code"] == "c"


# ── marketplace seed ────────────────────────────────────────────────────────


def test_seed_from_marketplace(tmp_path: Path):
    _write_plugin(tmp_path)
    state = HarnessState.create("mkt-1")
    out = state.seed_from_marketplace(tmp_path, status=hs.STATUS_IDLE)
    assert out["ok"] is True
    assert out["n_registered"] >= 1
    # marketplace components start idle
    assert any(a.status == "idle" for a in state.agents.values())
    # surfaces from marketplace
    surfaces = {a.surface for a in state.agents.values()}
    assert "agent" in surfaces or "skill" in surfaces or "command" in surfaces
    report = state.verify()
    assert report["ok"] is True


def test_seed_same_name_across_surfaces(tmp_path: Path):
    """wshobson plugins reuse names across agent/skill/command — all kept."""
    _write_plugin(
        tmp_path,
        plugin_id="collide",
        agent_name="deploy",
        skill_name="deploy",
        command_name="deploy",
    )
    state = HarnessState.create("mkt-collide")
    out = state.seed_from_marketplace(tmp_path, status=hs.STATUS_IDLE)
    assert out["ok"] is True
    assert out["n_registered"] == 3
    assert len(state.agents) == 3
    surfaces = {a.surface for a in state.agents.values()}
    assert surfaces == {"agent", "skill", "command"}


def test_plan_for_orchestrator_with_shared_and_marketplace(tmp_path: Path):
    _write_plugin(tmp_path, agent_name="reviewer-bot")
    state = plan_for_orchestrator(
        task_id="plan-1",
        agents=["planner"],
        seed_marketplace=True,
        workdir=tmp_path,
        shared={"mission": "improve harness"},
    )
    assert "planner" in state.agents
    assert "orchestrator" in state.agents  # bootstrap writer
    assert state.get("mission") == "improve harness"
    assert state.verify()["ok"] is True
    seed = (state.meta or {}).get("marketplace_seed")
    assert isinstance(seed, dict) and seed.get("ok") is True


# ── maybe_init + orchestrator wire ──────────────────────────────────────────


def test_maybe_init_disabled_returns_none():
    assert maybe_init_for_task(None, "t", None) is None
    assert maybe_init_for_task(None, "t", {}) is None
    assert maybe_init_for_task(None, "t", {"with_harness_state": False}) is None


def test_maybe_init_unrecognized_harness_state_errors():
    out = maybe_init_for_task(None, "t", {"harness_state": 1})
    assert out is not None
    assert out["ok"] is False
    assert "unrecognized" in (out.get("error") or "")


def test_maybe_init_builds_pipeline():
    out = maybe_init_for_task(
        None,
        "init-1",
        {"with_harness_state": True, "harness_shared": {"step": "start"}},
    )
    assert out is not None
    assert out["ok"] is True
    assert out["schema"] == SCHEMA
    assert out["paper"] == PAPER
    assert out["n_active"] >= 1
    assert out["content_hash"]
    assert "state" in out
    assert "planner" in out["active_ids"]
    # shared bootstrap
    state = HarnessState.from_dict(out["state"])
    assert state.get("step") == "start"
    assert state.verify(expected_hash=out["content_hash"])["ok"] is True


def test_maybe_init_pass_through_existing():
    seed = plan_for_orchestrator(task_id="pt-1", agents=["only-me"])
    out = maybe_init_for_task(
        None,
        "pt-1",
        {"harness_state": seed.to_meta()},
    )
    assert out is not None and out["ok"] is True
    assert out["active_ids"] == ["only-me"]
    assert out.get("expected_hash_checked") is True


def test_maybe_init_pass_through_detects_tamper():
    seed = plan_for_orchestrator(task_id="tamper-1", agents=["a"])
    seed.put("goal", "honest", agent="a")
    raw = seed.to_meta()
    # Mutate shared value but keep old content_hash
    if isinstance(raw.get("shared"), dict) and "goal" in raw["shared"]:
        raw["shared"]["goal"]["value"] = "TAMPERED"
    out = maybe_init_for_task(None, "tamper-1", {"harness_state": raw})
    assert out is not None
    assert out["ok"] is False
    assert out.get("verify_ok") is False
    assert any("hash_mismatch" in i for i in (out.get("issues") or []))


def test_orchestrator_attaches_harness_state(tmp_path: Path, monkeypatch):
    orch_mod = pytest.importorskip("nexus.orchestrator")
    Orchestrator = orch_mod.Orchestrator
    load_envelope = orch_mod.load_envelope

    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "track shared harness state",
        kind="task",
        agent_mode="fake",
        task_id="hs-orch-1",
        sync_fake=True,
        meta={
            "with_harness_state": True,
            "harness_agents": ["planner", "implementer", "reviewer"],
            "harness_shared": {"objective": "green tests"},
        },
    )
    assert out["task_id"] == "hs-orch-1"
    # status surface
    assert out.get("harness_state_ok") is True
    summary = out.get("harness_state_summary") or {}
    # 3 requested agents + orchestrator bootstrap writer for harness_shared
    n_agents = summary.get("n_agents") or (out.get("harness_state") or {}).get(
        "n_agents"
    )
    assert n_agents is not None and int(n_agents) >= 3
    assert "2605.18747" in str(summary.get("paper") or "")

    env = load_envelope(tmp_path, "hs-orch-1")
    assert env is not None
    assert env.meta.get("harness_state_paper") == "arxiv:2605.18747v1"
    raw = env.meta.get("harness_state")
    assert isinstance(raw, dict)
    loaded = HarnessState.from_dict(raw)
    assert {"planner", "implementer", "reviewer"} <= set(loaded.active_ids())
    assert loaded.get("objective") == "green tests"
    assert loaded.verify()["ok"] is True
    init = env.meta.get("harness_state_init") or {}
    assert init.get("content_hash") == loaded.content_hash()
    assert env.meta.get("harness_state_brief")


def test_orchestrator_harness_opt_in_only(tmp_path: Path, monkeypatch):
    orch_mod = pytest.importorskip("nexus.orchestrator")
    Orchestrator = orch_mod.Orchestrator
    load_envelope = orch_mod.load_envelope

    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "no harness by default",
        kind="task",
        agent_mode="fake",
        task_id="hs-off",
        sync_fake=True,
    )
    assert out.get("harness_state_ok") is not True
    env = load_envelope(tmp_path, "hs-off")
    assert env is not None
    assert "harness_state" not in (env.meta or {}) or not env.meta.get(
        "harness_state_init"
    )


def test_orchestrator_marketplace_seed(tmp_path: Path, monkeypatch):
    orch_mod = pytest.importorskip("nexus.orchestrator")
    Orchestrator = orch_mod.Orchestrator
    load_envelope = orch_mod.load_envelope

    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    _write_plugin(tmp_path, plugin_id="ops-pack", agent_name="ops-agent")
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "seed harness from marketplace",
        kind="task",
        agent_mode="fake",
        task_id="hs-mkt",
        sync_fake=True,
        meta={
            "with_harness_state": True,
            "harness_agents": ["planner"],
            "harness_from_marketplace": True,
        },
    )
    assert out.get("harness_state_ok") is True
    env = load_envelope(tmp_path, "hs-mkt")
    assert env is not None
    loaded = HarnessState.from_dict(env.meta["harness_state"])
    # pipeline agent + marketplace seed
    assert "planner" in loaded.agents
    assert len(loaded.agents) >= 2
    assert loaded.verify()["ok"] is True
