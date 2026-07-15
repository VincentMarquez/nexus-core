"""Unit tests for DurableAgent step wrapper (no network)."""

from __future__ import annotations

import pytest

from nexus.durability import (
    BudgetExhausted,
    DurableAgent,
    RunBudget,
    TaintError,
    TaintLevel,
)


def test_step_budget_hard_stop():
    agent = DurableAgent(budget=RunBudget(max_steps=2, hard=True))
    r1 = agent.run_step(lambda: "a")
    r2 = agent.run_step(lambda: "b")
    assert r1.ok and r2.ok
    r3 = agent.run_step(lambda: "c")
    assert not r3.ok
    assert r3.budget_exhausted
    assert r3.budget_kind == "steps"
    assert "budget" in r3.error.lower() or "exhausted" in r3.error.lower()


def test_step_budget_raises_when_not_stopping():
    agent = DurableAgent(
        budget=RunBudget(max_steps=1, hard=True),
        stop_on_budget=False,
    )
    agent.run_step(lambda: 1)
    with pytest.raises(BudgetExhausted):
        agent.run_step(lambda: 2)


def test_mined_write_not_trusted_until_promote():
    agent = DurableAgent(budget=RunBudget(max_steps=10))
    agent.write(
        "idea",
        {"score": 14.0},
        source=".nexus_workspaces/scout_repos/wmcmahan__cycgraph",
    )
    assert agent.taint.level_of("idea") is TaintLevel.MINED
    with pytest.raises(TaintError):
        agent.require_trusted("idea")
    agent.promote("idea", gate="eval-grade>=10")
    assert agent.require_trusted("idea")["score"] == 14.0


def test_run_step_stamps_write_key():
    agent = DurableAgent(budget=RunBudget(max_steps=5))
    r = agent.run_step(
        lambda: {"ok": True},
        write_key="mcp_result",
        source="mcp:arxiv/search",
    )
    assert r.ok
    assert "mcp_result" in r.taint_stamped
    assert agent.taint.level_of("mcp_result") is TaintLevel.EXTERNAL_MCP
    with pytest.raises(TaintError):
        agent.read("mcp_result", require_trusted=True)


def test_token_cost_accrual_exhausts():
    agent = DurableAgent(budget=RunBudget(max_tokens=50, hard=True))
    r = agent.run_step(lambda: "x", tokens=50)
    assert r.ok
    assert r.budget_exhausted  # hit cap on usage after work
    r2 = agent.run_step(lambda: "y", tokens=1)
    assert not r2.ok and r2.budget_exhausted


def test_from_meta_and_meta_patch():
    agent = DurableAgent.from_meta(
        {"max_steps": 4, "max_tokens": 200, "tokens_total": 10},
        use_env=False,
    )
    assert agent.budget.max_steps == 4
    assert agent.budget.tokens_used == 10
    agent.write("m", 1, source="mined:foo")
    patch = agent.meta_patch()
    assert patch["run_budget"]["max_steps"] == 4
    assert "_taint_registry" in patch
    assert patch["_taint_registry"]["registry"]["m"]["level"] == "mined"


def test_soft_budget_controlled_stop():
    agent = DurableAgent(budget=RunBudget(max_steps=1, hard=False))
    r1 = agent.run_step(lambda: "ok")
    assert r1.ok
    r2 = agent.run_step(lambda: "nope")
    assert not r2.ok
    assert r2.budget_exhausted
