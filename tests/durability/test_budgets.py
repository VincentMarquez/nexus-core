"""Unit tests for per-run budgets (no network)."""

from __future__ import annotations

import pytest

from nexus.durability import BudgetExhausted, RunBudget, budget_from_env, budget_from_meta


def test_max_steps_hard_fail():
    b = RunBudget(max_steps=2, hard=True)
    b.consume(steps=1)
    assert not b.exhausted()
    b.consume(steps=1)
    assert b.exhausted()
    assert b.exhausted_kind() == "steps"
    with pytest.raises(BudgetExhausted) as ei:
        b.consume(steps=1)
    assert ei.value.kind == "steps"
    assert ei.value.used >= 2
    assert ei.value.limit == 2


def test_max_tokens_and_cost():
    b = RunBudget(max_tokens=100, max_cost_usd=0.5, hard=True)
    b.consume(tokens=40, cost_usd=0.1)
    assert b.remaining_tokens() == 60
    assert abs((b.remaining_cost_usd() or 0) - 0.4) < 1e-9
    b.consume(tokens=60)
    assert b.exhausted_kind() == "tokens"
    with pytest.raises(BudgetExhausted) as ei:
        b.check()
    assert ei.value.kind == "tokens"

    b2 = RunBudget(max_cost_usd=1.0)
    b2.consume(cost_usd=1.0)
    with pytest.raises(BudgetExhausted) as ei2:
        b2.consume(cost_usd=0.01)
    assert ei2.value.kind == "cost"


def test_soft_degrade_no_raise():
    b = RunBudget(max_steps=1, hard=False)
    b.consume(steps=1)  # landing on cap is allowed
    assert b.exhausted()
    assert not b.soft_stop
    # next consume soft-marks instead of raising
    b.consume(steps=1)
    assert b.soft_stop
    assert "steps" in b.soft_reason
    assert b.steps_used == 2


def test_unlimited_when_caps_none():
    b = RunBudget()
    b.consume(steps=1000, tokens=1_000_000, cost_usd=99.0)
    assert not b.exhausted()
    assert b.remaining() == {"steps": None, "tokens": None, "cost_usd": None}


def test_snapshot_and_serde():
    b = RunBudget(max_steps=5, max_tokens=1000, max_cost_usd=2.5)
    b.consume(steps=2, tokens=100, cost_usd=0.25)
    snap = b.snapshot()
    assert snap["steps_used"] == 2
    assert snap["remaining"]["steps"] == 3
    assert snap["exhausted"] is False
    b2 = RunBudget.from_dict(b.to_dict())
    assert b2.max_steps == 5
    assert b2.tokens_used == 100
    assert abs(b2.cost_usd - 0.25) < 1e-9


def test_budget_from_meta_and_env(monkeypatch):
    meta = {
        "max_steps": 3,
        "max_tokens": 500,
        "tokens_total": 120,
        "budget": {"max_cost_usd": 1.5},
    }
    b = budget_from_meta(meta)
    assert b.max_steps == 3
    assert b.max_tokens == 500
    assert b.tokens_used == 120
    assert b.max_cost_usd == 1.5

    monkeypatch.setenv("NEXUS_MAX_STEPS", "7")
    monkeypatch.setenv("NEXUS_MAX_COST", "0.25")
    monkeypatch.delenv("NEXUS_MAX_TOKENS", raising=False)
    monkeypatch.delenv("NEXUS_MAX_TOKENS_RUN", raising=False)
    e = budget_from_env()
    assert e.max_steps == 7
    assert e.max_cost_usd == 0.25


def test_budget_exhausted_to_dict():
    err = BudgetExhausted("boom", kind="steps", used=3, limit=3)
    d = err.to_dict()
    assert d["kind"] == "steps"
    assert d["error"] == "BudgetExhausted"


def test_would_exceed_predictive():
    b = RunBudget(max_steps=2, max_tokens=10)
    b.consume(steps=1, tokens=5, check=False)
    assert b.would_exceed(steps=1) == "steps"
    assert b.would_exceed(tokens=5) == "tokens"
    assert b.would_exceed(steps=0, tokens=0) is None
