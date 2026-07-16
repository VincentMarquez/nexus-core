"""Tests for First apply slice: work ledger + dual-control + breaker + decision packet."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.circuits import CircuitBreaker, CircuitState
from nexus.work_ledger import (
    DEFAULT_SCORE_THRESHOLD,
    DualControlError,
    ImmutableError,
    WorkLedger,
    WorkLedgerError,
    build_decision_packet,
    format_causal_chain,
    format_slice_report,
    make_grade_breaker,
    protected_call,
    run_first_slice,
    validate_decision_packet,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mine_eval_sample.json"


# ---------------------------------------------------------------------------
# Append-only + basic events
# ---------------------------------------------------------------------------


def test_append_only_no_update_delete(tmp_path: Path):
    with WorkLedger.open(tmp_path) as led:
        ev = led.record_mine(
            run_id="r1",
            repo="labsai/EDDI",
            score=17.0,
            path=".nexus_workspaces/scout_repos/labsai__EDDI",
        )
        assert ev["event_type"] == "mine_completed"
        assert led.count(run_id="r1") == 1

        with pytest.raises(ImmutableError):
            led.try_update_forbidden(ev["id"])
        with pytest.raises(ImmutableError):
            led.try_delete_forbidden(ev["id"])

        # row still present
        assert led.get(ev["id"]) is not None
        assert led.get(ev["id"])["agent"] != "mutated"


def test_idempotent_content_hash(tmp_path: Path):
    with WorkLedger.open(tmp_path) as led:
        a = led.record_mine(run_id="r", repo="x/y", score=15.0, path="p")
        b = led.record_mine(run_id="r", repo="x/y", score=15.0, path="p")
        assert a["id"] == b["id"]
        assert led.count() == 1


def test_illegal_apply_accepted_without_grade(tmp_path: Path):
    with WorkLedger.open(tmp_path) as led:
        packet = build_decision_packet(
            source_repo="labsai/EDDI",
            score=17.0,
            grade_id="",
        )
        with pytest.raises(DualControlError, match="grade_recorded"):
            led.accept_apply(run_id="r1", packet=packet, agent="worker:apply")


def test_dual_control_same_role_refused(tmp_path: Path):
    with WorkLedger.open(tmp_path) as led:
        led.record_mine(run_id="r1", repo="choihyunsus/soul", score=15.0)
        g = led.record_grade(
            run_id="r1",
            repo="choihyunsus/soul",
            score=15.0,
            idea=7.0,
            skill=8.0,
            method="grok:grok-4.5",
            agent="same-agent",
            role="grader",
        )
        packet = build_decision_packet(
            source_repo="choihyunsus/soul",
            score=15.0,
            grade_id=g["id"],
            pattern_name="immutable work ledger",
        )
        # same role as grader
        with pytest.raises(DualControlError, match="same role"):
            led.accept_apply(
                run_id="r1",
                packet=packet,
                agent="other-agent",
                role="grader",
            )
        # same agent as grader
        with pytest.raises(DualControlError, match="same agent"):
            led.accept_apply(
                run_id="r1",
                packet=packet,
                agent="same-agent",
                role="applier",
            )


def test_dual_control_accept_ok(tmp_path: Path):
    with WorkLedger.open(tmp_path) as led:
        mine = led.record_mine(run_id="r1", repo="labsai/EDDI", score=17.0)
        g = led.record_grade(
            run_id="r1",
            repo="labsai/EDDI",
            score=17.0,
            idea=8.0,
            skill=9.0,
            agent="grok:grade",
            role="grader",
            parent_id=mine["id"],
        )
        packet = build_decision_packet(
            source_repo="labsai/EDDI",
            score=17.0,
            grade_id=g["id"],
            pattern_name="immutable work ledger",
            target_module="src/nexus/work_ledger.py",
        )
        led.record_decision(run_id="r1", packet=packet, agent="worker:apply")
        prop = led.propose_apply(run_id="r1", packet=packet, agent="worker:apply")
        acc = led.accept_apply(
            run_id="r1",
            packet=packet,
            agent="worker:apply",
            role="applier",
            parent_id=prop["id"],
        )
        assert acc["event_type"] == "apply_accepted"
        assert acc["payload"]["grade_id"] == g["id"]
        assert led.count(run_id="r1") >= 5


def test_decision_packet_below_threshold(tmp_path: Path):
    packet = build_decision_packet(
        source_repo="openai/swarm",
        score=13.0,
        threshold=15.0,
    )
    assert packet["score_ok"] is False
    with pytest.raises(Exception, match="below threshold"):
        validate_decision_packet(packet, threshold=15.0)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_opens_after_n_failures(tmp_path: Path):
    path = tmp_path / "br.json"
    br = make_grade_breaker(path=path, failure_threshold=2, cooldown_s=60.0)
    assert br.can_execute("grade:x")

    def boom() -> None:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        protected_call(br, "grade:x", boom)
    assert br.can_execute("grade:x")  # 1 fail — still closed at threshold 2

    with pytest.raises(RuntimeError):
        protected_call(br, "grade:x", boom)
    assert br.get("grade:x").state == CircuitState.OPEN
    assert not br.can_execute("grade:x")

    with pytest.raises(WorkLedgerError, match="circuit OPEN"):
        protected_call(br, "grade:x", lambda: "ok")


def test_circuit_breaker_recovers_half_open(tmp_path: Path):
    br = CircuitBreaker(failure_threshold=1, cooldown_s=0.0)
    with pytest.raises(RuntimeError):
        protected_call(br, "g", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert br.get("g").state == CircuitState.OPEN
    # cooldown 0 → half-open probe allowed
    assert br.can_execute("g")
    assert protected_call(br, "g", lambda: 42) == 42
    assert br.get("g").state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Integration: fixture → grade → decision → accept/reject
# ---------------------------------------------------------------------------


def test_integration_first_slice_wshobson(tmp_path: Path):
    # Copy fixture into workdir-relative path resolution via absolute fixture
    report = run_first_slice(
        tmp_path,
        fixture=FIXTURE,
        repo="wshobson/agents",
        run_id="int-wshobson",
        score_threshold=15.0,
        pattern_name="immutable work ledger",
        accept=True,
    )
    assert report["ok"] is True, report.get("error")
    assert report["repo"] == "wshobson/agents"
    assert report["accepted"] is True
    types = [e["event_type"] for e in report["events"]]
    assert "mine_completed" in types
    assert "grade_recorded" in types
    assert "decision_packet" in types
    assert "apply_proposed" in types
    assert "apply_accepted" in types
    pkt = report["decision_packet"]
    assert pkt["score"] == 16.0
    assert pkt["pattern_name"] == "immutable work ledger"
    assert pkt["grade_id"]
    chain = report["chain"]
    assert len(chain) >= 4
    text = format_causal_chain(chain)
    assert "graded wshobson/agents" in text
    assert "accepted apply" in text


def test_integration_reject_path(tmp_path: Path):
    report = run_first_slice(
        tmp_path,
        fixture=FIXTURE,
        repo="codingagentsystem/cas",
        accept=False,
    )
    assert report["ok"] is True
    assert report["rejected"] is True
    assert report["accepted"] is False
    types = [e["event_type"] for e in report["events"]]
    assert "apply_rejected" in types
    assert "apply_accepted" not in types


def test_integration_score_below_threshold_rejects(tmp_path: Path):
    # Force high threshold so cas 15.0 fails
    report = run_first_slice(
        tmp_path,
        fixture=FIXTURE,
        repo="codingagentsystem/cas",
        score_threshold=16.5,
        accept=True,
    )
    assert report["ok"] is True
    assert report["rejected"] is True
    types = [e["event_type"] for e in report["events"]]
    assert "apply_rejected" in types
    assert "apply_accepted" not in types


def test_causal_chain_and_report_format(tmp_path: Path):
    report = run_first_slice(
        tmp_path,
        fixture=FIXTURE,
        repo="wshobson/agents",
    )
    text = format_slice_report(report)
    assert "work-ledger first-slice" in text
    assert "wshobson/agents" in text
    assert "Causal chain" in text


def test_handoff_recorded(tmp_path: Path):
    with WorkLedger.open(tmp_path) as led:
        ev = led.record_mine(run_id="r", repo="a/b", score=15.0)
        ho = led.handoff(
            run_id="r",
            from_agent="scout:mine",
            to_agent="grok:grade",
            reason="next",
            event_id=ev["id"],
        )
        assert ho["from_agent"] == "scout:mine"
        assert ho["to_agent"] == "grok:grade"


def test_default_threshold_matches_plan():
    assert DEFAULT_SCORE_THRESHOLD == 15.0


def test_cli_work_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    # Ensure fixture is absolute so load works from tmp workdir
    from nexus.cli import main

    code = main(
        [
            "improve",
            "work-loop",
            "--path",
            str(tmp_path),
            "--fixture",
            str(FIXTURE),
            "--repo",
            "wshobson/agents",
            "--json",
        ]
    )
    assert code == 0


# ---------------------------------------------------------------------------
# P0.5 interleaving + ensure_apply_gate (worktree/alive wire)
# ---------------------------------------------------------------------------


def test_illegal_transition_mine_to_accept(tmp_path: Path):
    from nexus.work_ledger import TransitionError, assert_legal_transition

    with pytest.raises(TransitionError, match="illegal transition"):
        assert_legal_transition("mine_completed", "apply_accepted")
    # empty → accept also illegal
    with pytest.raises(TransitionError):
        assert_legal_transition(None, "apply_accepted")
    # legal happy path steps
    assert assert_legal_transition(None, "mine_completed")["ok"]
    assert assert_legal_transition("mine_completed", "grade_recorded")["ok"]
    assert assert_legal_transition("grade_recorded", "decision_packet")["ok"]
    assert assert_legal_transition("decision_packet", "apply_proposed")["ok"]
    assert assert_legal_transition("apply_proposed", "apply_accepted")["ok"]


def test_append_refuses_illegal_interleaving(tmp_path: Path):
    from nexus.work_ledger import TransitionError

    with WorkLedger.open(tmp_path) as led:
        led.record_mine(run_id="r1", repo="a/b", score=16.0)
        with pytest.raises(TransitionError, match="illegal transition"):
            led.append(
                run_id="r1",
                event_type="decision_packet",
                agent="worker:apply",
                role="applier",
                repo="a/b",
                payload={"packet": {"source_repo": "a/b", "score": 16}},
            )


def test_ensure_apply_gate_accepts_dual_control(tmp_path: Path):
    from nexus.work_ledger import ensure_apply_gate

    grade = {
        "repo": "wshobson/agents",
        "score": 16.0,
        "idea": 8.0,
        "skill": 8.0,
        "method": "grok:grok-4.5",
        "path": ".nexus_workspaces/scout_repos/wshobson__agents",
        "pattern": "markdown skill SoT",
    }
    gate = ensure_apply_gate(
        tmp_path,
        grade=grade,
        run_id="gate-1",
        grader="grok:grade",
        applier="worker:apply",
        score_threshold=15.0,
    )
    assert gate["ok"] is True, gate.get("error")
    assert gate["accepted"] is True
    types = [e["event_type"] for e in gate["events"]]
    assert "apply_accepted" in types
    # idempotent re-entry
    gate2 = ensure_apply_gate(
        tmp_path,
        grade=grade,
        run_id="gate-1",
        grader="grok:grade",
        applier="worker:apply",
        score_threshold=15.0,
    )
    assert gate2.get("cached") is True
    assert gate2["accepted"] is True


def test_ensure_apply_gate_dual_control_collusion(tmp_path: Path):
    from nexus.work_ledger import ensure_apply_gate

    grade = {
        "repo": "choihyunsus/soul",
        "score": 15.0,
        "idea": 7.0,
        "skill": 8.0,
        "method": "x",
        "path": "p",
    }
    gate = ensure_apply_gate(
        tmp_path,
        grade=grade,
        run_id="collude",
        grader="same-agent",
        applier="same-agent",
        score_threshold=10.0,
    )
    assert gate["accepted"] is False
    assert gate["ok"] is False
    assert "DualControl" in (gate.get("error") or "")


def test_mcp_work_ledger_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    from nexus import mcp_server
    from nexus.work_ledger import ensure_apply_gate

    names = {t["name"] for t in mcp_server.TOOLS}
    assert "work_ledger" in names

    st = mcp_server.call_tool("work_ledger", {"action": "status"})
    assert st.get("isError") is not True
    tr = mcp_server.call_tool("work_ledger", {"action": "transitions"})
    assert tr.get("isError") is not True
    body = tr.get("content", [{}])[0].get("text") or tr.get("text") or ""
    assert "legal_successors" in body or "mine_completed" in body

    # seed a run then chain
    ensure_apply_gate(
        tmp_path,
        grade={
            "repo": "labsai/EDDI",
            "score": 17.0,
            "idea": 8.0,
            "skill": 9.0,
            "method": "g",
            "path": "p",
        },
        run_id="mcp-wl-1",
        score_threshold=15.0,
    )
    chain = mcp_server.call_tool(
        "work_ledger", {"action": "chain", "run_id": "mcp-wl-1"}
    )
    assert chain.get("isError") is not True
