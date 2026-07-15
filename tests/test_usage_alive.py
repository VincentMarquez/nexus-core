from pathlib import Path

import pytest

from nexus import usage as um
from nexus import alive as al


def test_estimate_and_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    um.save_budget(um.Budget(enabled=True, daily_tokens=1000, monthly_tokens=10000, per_call_max=500), tmp_path)
    assert um.estimate_tokens("abcd") == 1
    um.record(100, source="t", workdir=tmp_path, enforce=True)
    st = um.status(tmp_path)
    assert st["totals"]["day_tokens"] == 100
    with pytest.raises(um.BudgetExceeded):
        um.check_budget(2000, tmp_path, raise_on_exceed=True)


def test_alive_init_and_dry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = al.AliveConfig(goal="test goal", queries=["agents"], enabled=True)
    al.save_config(cfg, tmp_path)
    loaded = al.load_config(tmp_path)
    assert loaded.goal == "test goal"
    rep = al.cycle_once(tmp_path, dry_run=True)
    assert rep.get("dry_run") is True
