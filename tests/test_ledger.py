"""Tests for immutable agent decision ledger (P0.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.decision_ledger import DecisionLedger, LedgerError, content_hash


def test_append_and_tail(tmp_path: Path):
    with DecisionLedger.open(tmp_path) as led:
        row = led.append(
            run_id="run-1",
            agent="mine",
            claim="loaded wshobson/agents",
            evidence_refs=[".nexus_workspaces/mine_eval/wshobson__agents"],
            grade={"repo": "wshobson/agents", "score": 16.0},
            action="mine_load",
        )
        assert row["run_id"] == "run-1"
        assert row["agent"] == "mine"
        assert row["content_hash"]
        assert led.count(run_id="run-1") == 1

        led.append(
            run_id="run-1",
            agent="grade",
            claim="accepted grade",
            evidence_refs=[".nexus_workspaces/mine_eval/wshobson__agents"],
            grade={"score": 16.0, "idea": 8.0, "skill": 8.0},
            action="grade_accept",
        )
        tail = led.tail(limit=5, run_id="run-1")
        assert len(tail) == 2
        agents = {r["agent"] for r in tail}
        assert agents == {"mine", "grade"}

        ordered = led.list_run("run-1")
        assert [r["agent"] for r in ordered] == ["mine", "grade"]


def test_idempotent_by_content_hash(tmp_path: Path):
    with DecisionLedger.open(tmp_path) as led:
        a = led.append(
            run_id="r",
            agent="claim_verify",
            claim="verified",
            evidence_refs=["p"],
            grade={"score": 16.0},
            action="claim_pass",
        )
        b = led.append(
            run_id="r",
            agent="claim_verify",
            claim="verified",
            evidence_refs=["p"],
            grade={"score": 16.0},
            action="claim_pass",
        )
        assert a["id"] == b["id"]
        assert a["content_hash"] == b["content_hash"]
        assert led.count() == 1


def test_content_hash_stable():
    h1 = content_hash(
        run_id="r",
        agent="mine",
        claim="c",
        evidence_refs=["a", "b"],
        grade={"score": 1.0},
        action="x",
    )
    h2 = content_hash(
        run_id="r",
        agent="mine",
        claim="c",
        evidence_refs=["a", "b"],
        grade={"score": 1.0},
        action="x",
    )
    assert h1 == h2
    h3 = content_hash(
        run_id="r",
        agent="mine",
        claim="other",
        evidence_refs=["a", "b"],
        grade={"score": 1.0},
        action="x",
    )
    assert h1 != h3


def test_requires_run_and_agent(tmp_path: Path):
    with DecisionLedger.open(tmp_path) as led:
        with pytest.raises(LedgerError, match="run_id"):
            led.append(run_id="", agent="mine")
        with pytest.raises(LedgerError, match="agent"):
            led.append(run_id="r", agent="")


def test_get_by_id_and_hash(tmp_path: Path):
    with DecisionLedger.open(tmp_path) as led:
        row = led.append(
            run_id="r2",
            agent="mine",
            claim="c",
            action="mine_load",
        )
        assert led.get(row["id"])["claim"] == "c"
        assert led.by_hash(row["content_hash"])["id"] == row["id"]
        assert led.get("missing") is None
