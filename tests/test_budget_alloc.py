"""Tests for multi-agent compute budget allocation (FutureWeaver pattern)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.budget_alloc import (
    PAPER,
    SCHEMA,
    STRATEGIES,
    AgentQuota,
    AllocationExhausted,
    BudgetAllocator,
    default_pipeline_agents,
    format_brief,
    plan_for_orchestrator,
)
from nexus.orchestrator import Orchestrator, OrchError, load_envelope


# ── pure allocator ──────────────────────────────────────────────────────────


def test_plan_equal_splits_tokens():
    alloc = BudgetAllocator.plan(
        ["a", "b", "c"],
        total_tokens=100,
        strategy="equal",
    )
    assert alloc.schema == SCHEMA
    assert alloc.paper == PAPER
    shares = [q.max_tokens for q in alloc.agents.values()]
    assert sum(shares) == 100
    assert max(shares) - min(shares) <= 1  # even split
    assert alloc.remaining_tokens() == 100


def test_plan_weighted_implementer_gets_most():
    alloc = plan_for_orchestrator(
        total_tokens=1000,
        agents=["planner", "implementer", "logger"],
        strategy="weighted",
    )
    assert alloc.agents["implementer"].max_tokens > alloc.agents["planner"].max_tokens
    assert alloc.agents["planner"].max_tokens > alloc.agents["logger"].max_tokens
    assert alloc.tokens_allocated() == 1000
    assert alloc.remaining_tokens() == 1000


def test_plan_modular_has_reserved_floor():
    alloc = BudgetAllocator.plan(
        ["planner", "implementer"],
        total_tokens=200,
        strategy="modular",
        reserved_fraction=0.5,
    )
    for q in alloc.agents.values():
        assert q.reserved_tokens > 0
        assert q.reserved_tokens <= q.max_tokens
        # half-ish reserved
        assert q.reserved_tokens >= q.max_tokens // 3


def test_grant_and_consume_tracks_usage():
    alloc = BudgetAllocator.plan(["x", "y"], total_tokens=100, strategy="equal")
    r = alloc.grant("x", tokens=20)
    assert r["ok"] is True
    assert r["remaining_tokens"] == alloc.agents["x"].remaining_tokens()
    assert alloc.agents["x"].tokens_used == 20
    assert alloc.tokens_used() == 20

    r2 = alloc.consume("y", tokens=10, steps=1)
    assert r2["ok"] is True
    assert alloc.agents["y"].tokens_used == 10
    assert alloc.steps_used == 1


def test_hard_limit_raises_allocation_exhausted():
    alloc = BudgetAllocator.plan(["solo"], total_tokens=50, strategy="equal", hard=True)
    alloc.consume("solo", tokens=50)
    with pytest.raises(AllocationExhausted) as ei:
        alloc.grant("solo", tokens=1)
    assert ei.value.agent == "solo"
    assert ei.value.kind == "tokens"
    assert ei.value.to_dict()["error"] == "AllocationExhausted"


def test_soft_mode_marks_without_raise():
    alloc = BudgetAllocator.plan(["solo"], total_tokens=10, strategy="equal", hard=False)
    alloc.consume("solo", tokens=10)
    r = alloc.grant("solo", tokens=5)
    assert r["ok"] is False
    assert alloc.soft_stop is True
    assert "solo" in alloc.soft_reason


def test_modular_reclaim_and_rebalance():
    alloc = BudgetAllocator.plan(
        ["a", "b", "c"],
        total_tokens=300,
        strategy="modular",
        reserved_fraction=0.5,
        weights={"a": 1, "b": 1, "c": 1},
    )
    # a uses little, then finishes → reclaims unused to residual
    alloc.consume("a", tokens=10)
    fin = alloc.finish("a", reclaim=True)
    assert fin["reclaimed_tokens"] > 0
    assert alloc.residual_tokens == fin["reclaimed_tokens"]
    assert alloc.agents["a"].finished is True
    assert alloc.agents["a"].remaining_tokens() == 0

    before_b = alloc.agents["b"].max_tokens
    reb = alloc.rebalance(targets=["b", "c"])
    assert reb["distributed"] > 0
    assert alloc.agents["b"].max_tokens >= before_b
    assert alloc.residual_tokens == reb["residual_tokens"]


def test_top_up_from_residual():
    alloc = BudgetAllocator.plan(["a", "b"], total_tokens=100, strategy="equal")
    # manually seed residual
    alloc.residual_tokens = 20
    out = alloc.top_up("a", 15)
    assert out["ok"] is True
    assert out["added"] == 15
    assert alloc.residual_tokens == 5
    assert alloc.agents["a"].max_tokens == 50 + 15


def test_serde_roundtrip():
    alloc = plan_for_orchestrator(
        total_tokens=500,
        strategy="weighted",
        total_steps=12,
    )
    alloc.consume("implementer", tokens=40, steps=2)
    d = alloc.to_dict()
    assert d["schema"] == SCHEMA
    alloc2 = BudgetAllocator.from_dict(d)
    assert alloc2.tokens_used() == 40
    assert alloc2.agents["implementer"].tokens_used == 40
    assert alloc2.total_steps == 12
    snap = alloc2.snapshot()
    assert "agents" in snap
    assert snap["paper"] == PAPER


def test_from_meta_and_spec():
    planned = BudgetAllocator.plan(["p"], total_tokens=80).to_meta()
    loaded = BudgetAllocator.from_meta({"budget_alloc": planned})
    assert loaded is not None
    assert loaded.total_tokens == 80

    from_spec = BudgetAllocator.from_spec(
        {
            "total_tokens": 200,
            "strategy": "equal",
            "agents": ["alpha", "beta"],
        }
    )
    assert set(from_spec.agents) == {"alpha", "beta"}
    assert from_spec.tokens_allocated() == 200


def test_invalid_strategy_and_empty_agents():
    with pytest.raises(ValueError, match="strategy"):
        BudgetAllocator.plan(["a"], total_tokens=10, strategy="beam")
    with pytest.raises(ValueError, match="agents"):
        BudgetAllocator.plan([], total_tokens=10)


def test_would_exceed_and_step_caps():
    alloc = BudgetAllocator.plan(
        ["a", "b"],
        total_tokens=100,
        total_steps=4,
        strategy="equal",
    )
    assert alloc.agents["a"].max_steps is not None
    assert sum(q.max_steps or 0 for q in alloc.agents.values()) == 4
    assert alloc.would_exceed("a", tokens=999) == "tokens"
    alloc.consume("a", steps=alloc.agents["a"].max_steps or 1)
    assert alloc.would_exceed("a", steps=1) == "steps"


def test_format_brief_and_defaults():
    agents = default_pipeline_agents()
    assert "implementer" in agents
    alloc = plan_for_orchestrator(total_tokens=600, agents=agents)
    text = format_brief(alloc)
    assert SCHEMA in text or "compute budget" in text
    assert "implementer" in text
    assert PAPER in text
    assert "weighted" in STRATEGIES


def test_agent_quota_snapshot():
    q = AgentQuota(agent="z", max_tokens=100, reserved_tokens=40)
    q.tokens_used = 10
    s = q.snapshot()
    assert s["remaining_tokens"] == 90
    assert s["reclaimable_tokens"] == 60  # 90 - (40-10) = 60
    q2 = AgentQuota.from_dict(q.to_dict())
    assert q2.agent == "z"


# ── orchestrator integration ────────────────────────────────────────────────


def test_orchestrator_plans_compute_budget_on_run(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "budgeted multi-agent work",
        agent_mode="fake",
        task_id="bud-1",
        sync_fake=True,
        meta={
            "compute_budget": {
                "total_tokens": 900,
                "strategy": "weighted",
                "agents": ["planner", "implementer", "tester"],
            }
        },
    )
    assert out["status"] == "completed"
    assert out.get("compute_budget_planned") is True
    cb = out.get("compute_budget") or {}
    assert cb.get("total_tokens") == 900
    assert cb.get("paper") == PAPER
    assert "implementer" in (cb.get("agents") or {})
    assert cb["agents"]["implementer"]["max_tokens"] >= cb["agents"]["planner"]["max_tokens"]

    env = load_envelope(tmp_path, "bud-1")
    assert env is not None
    assert isinstance(env.meta.get("budget_alloc"), dict)
    assert any("compute_budget" in line for line in env.log_tail)


def test_orchestrator_plan_compute_budget_helper(tmp_path: Path):
    orch = Orchestrator(tmp_path)
    snap = orch.plan_compute_budget(
        total_tokens=500,
        agents=["planner", "implementer"],
        strategy="modular",
    )
    assert snap["total_tokens"] == 500
    assert snap["strategy"] == "modular"
    assert "brief" in snap
    assert snap["agents"]["implementer"]["reserved_tokens"] > 0


def test_orchestrator_record_agent_usage_and_exhaust(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    orch.run_task(
        "track usage",
        agent_mode="fake",
        task_id="bud-2",
        sync_fake=True,
        meta={
            "compute_budget": {
                "total_tokens": 100,
                "strategy": "equal",
                "agents": ["a", "b"],
            }
        },
    )
    st = orch.get_compute_budget("bud-2")
    assert st["planned"] is True
    share = st["budget_alloc"]["agents"]["a"]["max_tokens"]

    r = orch.record_agent_usage("bud-2", "a", tokens=share // 2)
    assert r["receipt"]["ok"] is True
    assert r["budget_alloc"]["agents"]["a"]["tokens_used"] == share // 2

    # exhaust a
    orch.record_agent_usage("bud-2", "a", tokens=share - share // 2)
    with pytest.raises(OrchError) as ei:
        orch.record_agent_usage("bud-2", "a", tokens=1)
    assert ei.value.code == "budget_exhausted"


def test_orchestrator_finish_rebalance_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    orch.run_task(
        "modular collab",
        agent_mode="fake",
        task_id="bud-3",
        sync_fake=True,
        meta={
            "compute_budget": {
                "total_tokens": 300,
                "strategy": "modular",
                "agents": ["planner", "implementer", "reviewer"],
            }
        },
    )
    # planner uses little then finishes → reclaim + rebalance to implementer
    orch.record_agent_usage("bud-3", "planner", tokens=5)
    out = orch.record_agent_usage(
        "bud-3", "planner", tokens=0, finish=True, rebalance=True
    )
    assert out["finish"]["finished"] is True
    assert out["finish"]["reclaimed_tokens"] > 0
    assert out["rebalance"]["distributed"] >= 0
    # implementer should still have room
    impl = out["budget_alloc"]["agents"]["implementer"]
    assert impl["remaining_tokens"] > 0


def test_orchestrator_budget_strategy_shorthand(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "shorthand budget",
        agent_mode="fake",
        task_id="bud-4",
        sync_fake=True,
        meta={
            "budget_strategy": "equal",
            "total_tokens": 120,
            "budget_agents": ["x", "y", "z"],
        },
    )
    cb = out.get("compute_budget") or {}
    assert cb.get("strategy") == "equal"
    assert cb.get("total_tokens") == 120
    assert len(cb.get("agents") or {}) == 3


def test_orchestrator_no_budget_when_meta_omitted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "no budget",
        agent_mode="fake",
        task_id="nobud",
        sync_fake=True,
    )
    assert out.get("compute_budget_planned") is False
    st = orch.get_compute_budget("nobud")
    assert st["planned"] is False
    with pytest.raises(OrchError) as ei:
        orch.record_agent_usage("nobud", "planner", tokens=1)
    assert ei.value.code == "no_budget_alloc"


def test_invalid_total_tokens_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    orch = Orchestrator(tmp_path)
    with pytest.raises(OrchError) as ei:
        orch.run_task(
            "bad budget",
            agent_mode="fake",
            task_id="badbud",
            sync_fake=True,
            meta={"compute_budget": {"total_tokens": 0, "agents": ["a"]}},
        )
    assert ei.value.code == "budget_plan_failed"
