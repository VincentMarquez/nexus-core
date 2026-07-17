"""Tests for workspace-first routa traces + stacked review gate.

Portfolio idea: phodal/routa
"""

from __future__ import annotations

import json

import pytest

from nexus import workspace_review_board as wrb


def _dev_ready_board(
    *,
    acceptance: list[str] | None = None,
    files: list[str] | None = None,
) -> tuple[wrb.WorkspaceBoard, str]:
    # Defaults only when arg is None so explicit [] exercises empty edge cases
    if acceptance is None:
        acceptance = [
            "traces visible",
            "gate stacks three layers",
        ]
    if files is None:
        files = ["src/nexus/workspace_review_board.py"]
    board = wrb.create_board(
        "ws-test",
        "Ship stacked review gate",
        acceptance=acceptance,
    )
    cid = board.cards[0].id
    wrb.try_move_card(board, cid, "todo", force=True)
    wrb.try_move_card(board, cid, "dev", force=True)
    wrb.set_changed_files(board, cid, files)
    wrb.append_evidence(
        board,
        cid,
        kind="dev_evidence",
        ok=True,
        ref="impl:v1",
        detail="implemented module",
        lane="dev",
    )
    return board, cid


def _seed_review_evidence(board: wrb.WorkspaceBoard, cid: str) -> None:
    card = wrb.get_card(board, cid)
    for i, ac in enumerate(card.acceptance):
        wrb.append_evidence(
            board,
            cid,
            kind="ac_check",
            ok=True,
            ref=f"ac:{i + 1}",
            detail=ac,
            lane="review",
        )
    wrb.append_evidence(
        board,
        cid,
        kind="test_result",
        ok=True,
        ref="pytest:ok",
        detail="green",
        lane="review",
    )


def test_roles_distinct():
    assert wrb.roles_distinct(wrb.ROLES) is True
    assert (
        wrb.roles_distinct(
            {"coordinator": "x", "crafter": "x", "gate": "y"}
        )
        is False
    )
    assert wrb.roles_distinct({"coordinator": "only"}) is False
    # Arbitrary unrelated keys do not satisfy the triad
    assert wrb.roles_distinct({"a": "x", "b": "y", "c": "z"}) is False


def test_create_board_workspace_first():
    board = wrb.create_board("ws-1", "Build delivery board")
    d = board.to_dict()
    assert d["schema"] == wrb.SCHEMA
    assert d["source_pattern"] == "phodal/routa"
    assert d["idea_id"] == wrb.IDEA_ID
    assert d["workspace_id"] == "ws-1"
    assert d["roles_ok"] is True
    assert d["n_cards"] == 1
    assert d["cards"][0]["lane"] == "backlog"
    assert d["lane_counts"]["backlog"] == 1
    assert d["cards"][0]["traces"]
    assert d["cards"][0]["traces"][0]["action"] == "accept_goal"


def test_create_board_requires_goal():
    with pytest.raises(wrb.WorkspaceBoardError, match="goal"):
        wrb.create_board("ws", "")


def test_illegal_transition_rejected():
    board = wrb.create_board("ws", "goal")
    cid = board.cards[0].id
    res = wrb.try_move_card(board, cid, "done")
    assert res["ok"] is False
    assert res["moved"] is False
    assert "illegal" in res["reason"]
    assert board.cards[0].lane == "backlog"


def test_can_transition_happy_path():
    assert wrb.can_transition("backlog", "todo")
    assert wrb.can_transition("todo", "dev")
    assert wrb.can_transition("dev", "review")
    assert wrb.can_transition("review", "done")
    assert wrb.can_transition("review", "dev")  # reject path
    assert not wrb.can_transition("backlog", "done")
    assert not wrb.can_transition("done", "review")


def test_entry_gate_blocks_review_without_evidence():
    board = wrb.create_board("ws", "goal")
    cid = board.cards[0].id
    wrb.try_move_card(board, cid, "todo", force=True)
    wrb.try_move_card(board, cid, "dev", force=True)
    res = wrb.try_move_card(board, cid, "review")
    assert res["ok"] is False
    assert "entry_gate" in res["reason"]
    assert board.cards[0].lane == "dev"


def test_move_to_review_with_dev_evidence():
    board, cid = _dev_ready_board()
    res = wrb.try_move_card(board, cid, "review")
    assert res["ok"] is True
    assert res["moved"] is True
    assert board.cards[0].lane == "review"
    assert board.cards[0].specialist == wrb.SPECIALISTS["review"]


def test_stacked_gate_approves_complete_card():
    board, cid = _dev_ready_board()
    wrb.try_move_card(board, cid, "review")
    _seed_review_evidence(board, cid)
    gate = wrb.evaluate_review_gate(
        board.cards[0], roles=board.roles, git_clean=True, committed=True
    )
    assert gate["ok"] is True
    assert gate["verdict"] == wrb.VERDICT_APPROVED
    assert gate["signal"] == wrb.SIGNAL_CONTINUE
    assert gate["layers"]["harness"]["ok"] is True
    assert gate["layers"]["fitness"]["ok"] is True
    assert gate["layers"]["gate"]["ok"] is True
    assert gate["ac_status"]["AC1"] == "verified"
    assert gate["ac_status"]["AC2"] == "verified"

    move = wrb.try_move_card(board, cid, "done", git_clean=True, committed=True)
    assert move["ok"] is True
    assert move["moved"] is True
    assert board.cards[0].lane == "done"
    assert board.cards[0].review_findings.get("verdict") == wrb.VERDICT_APPROVED


def test_stacked_gate_rejects_dirty_git_to_dev():
    board, cid = _dev_ready_board()
    wrb.try_move_card(board, cid, "review")
    _seed_review_evidence(board, cid)
    move = wrb.try_move_card(
        board, cid, "done", git_clean=False, committed=True
    )
    assert move["ok"] is False
    assert move["reason"] == "gate_rejected"
    # auto-routed back toward dev
    assert board.cards[0].lane == "dev"
    assert board.signal == wrb.SIGNAL_REPLAN
    assert board.cards[0].review_findings.get("verdict") == wrb.VERDICT_REJECTED


def test_stacked_gate_rejects_missing_ac():
    board, cid = _dev_ready_board(
        acceptance=["must have tests", "must document AC"]
    )
    wrb.try_move_card(board, cid, "review")
    # only test_result — no ac_check
    wrb.append_evidence(
        board,
        cid,
        kind="test_result",
        ok=True,
        ref="pytest",
        detail="green",
        lane="review",
    )
    gate = wrb.evaluate_review_gate(
        board.cards[0], roles=board.roles, git_clean=True, committed=True
    )
    assert gate["ok"] is False
    assert gate["verdict"] == wrb.VERDICT_REJECTED
    assert gate["ac_status"]["AC1"] == "missing"
    assert any("ac_check" in r or "AC1" in r for r in gate["reasons"])


def test_role_collision_fails_gate():
    board, cid = _dev_ready_board()
    board.roles = {
        "coordinator": "same",
        "crafter": "same",
        "gate": "same",
    }
    wrb.try_move_card(board, cid, "review")
    _seed_review_evidence(board, cid)
    gate = wrb.evaluate_review_gate(
        board.cards[0], roles=board.roles, git_clean=True, committed=True
    )
    assert gate["ok"] is False
    assert any("role collision" in r for r in gate["reasons"])


def test_human_escalation_signal():
    board, cid = _dev_ready_board()
    wrb.try_move_card(board, cid, "review")
    _seed_review_evidence(board, cid)
    gate = wrb.evaluate_review_gate(
        board.cards[0],
        roles=board.roles,
        git_clean=True,
        committed=True,
        human_required=True,
    )
    assert gate["ok"] is False
    assert gate["verdict"] == wrb.VERDICT_NEEDS_HUMAN
    assert gate["signal"] == wrb.SIGNAL_ESCALATE


def test_fitness_file_budget():
    board, cid = _dev_ready_board(
        files=[f"src/f{i}.py" for i in range(6)]
    )
    wrb.try_move_card(board, cid, "review")
    _seed_review_evidence(board, cid)
    gate = wrb.evaluate_review_gate(
        board.cards[0],
        roles=board.roles,
        git_clean=True,
        committed=True,
        max_changed_files=3,
    )
    assert gate["ok"] is False
    assert any("budget" in r.lower() for r in gate["reasons"])


def test_advance_from_journal_handoff_to_review_not_rubber_stamp():
    """Journal step_complete must not mint ac_check / approve without real evidence."""
    board, cid = _dev_ready_board()
    events = [
        {
            "event": "handoff",
            "from_agent": "routa:crafter",
            "to_agent": "routa:gate",
            "detail": "ready for review",
        },
        {
            "event": "step_complete",
            "agent": "routa:gate",
            "ok": True,
            "score": 0.95,
            "why": "ACs verified",
        },
    ]
    report = wrb.advance_from_journal(
        board, events, card_id=cid, git_clean=True, committed=True
    )
    assert report["ok"] is True
    assert report["n_events"] == 2
    assert report["n_moves"] >= 1
    # Handoff may enter review; step_complete claims alone cannot reach done
    assert board.cards[0].lane in ("review", "dev")
    assert board.cards[0].lane != "done"
    claim_kinds = {e.kind for e in board.cards[0].evidence}
    assert "ac_claim" in claim_kinds or "test_claim" in claim_kinds
    # No fabricated ac_check from journal refs
    for e in board.cards[0].evidence:
        if e.kind == "ac_check":
            assert not (e.ref or "").startswith("journal:")


def test_advance_from_journal_veto_routes_to_dev():
    board, cid = _dev_ready_board()
    wrb.try_move_card(board, cid, "review")
    report = wrb.advance_from_journal(
        board,
        [{"event": "veto", "agent": "gate", "detail": "reject"}],
        card_id=cid,
    )
    assert board.cards[0].lane == "dev"
    assert report["signal"] == wrb.SIGNAL_REPLAN


def test_advance_from_journal_budget_blocks():
    board = wrb.create_board("ws", "budget test")
    cid = board.cards[0].id
    report = wrb.advance_from_journal(
        board,
        [{"event": "budget", "kind": "tokens", "detail": "cap hit"}],
        card_id=cid,
    )
    assert board.cards[0].lane == wrb.LANE_BLOCKED
    assert report["signal"] == wrb.SIGNAL_REPLAN


def test_advance_from_journal_human_approve():
    """Human approve is an explicit privileged override (force), not fabricated checks."""
    board, cid = _dev_ready_board()
    wrb.try_move_card(board, cid, "review")
    report = wrb.advance_from_journal(
        board,
        [{"event": "human_decision", "approve": True, "detail": "lgtm"}],
        card_id=cid,
    )
    assert board.cards[0].lane == "done"
    assert report["ok"] is True
    assert board.cards[0].review_findings.get("override") == "human_approve"
    # Still no journal-minted ac_check
    assert not any(
        e.kind == "ac_check" and (e.ref or "").startswith("journal:")
        for e in board.cards[0].evidence
    )


def test_format_board_and_payload():
    board, cid = _dev_ready_board()
    text = wrb.format_board(board)
    assert "workspace review board" in text
    assert "phodal/routa" in text
    assert "ws-test" in text
    payload = wrb.board_payload_for_meta(board)
    assert payload["schema"] == wrb.SCHEMA
    assert payload["workspace_id"] == "ws-test"
    assert payload["n_cards"] == 1
    assert "brief" in payload
    assert payload["n_traces"] >= 1


def test_roundtrip_to_dict():
    board, _ = _dev_ready_board()
    raw = board.to_dict()
    card = wrb.WorkspaceCard.from_dict(raw["cards"][0])
    assert card.lane == "dev"
    assert card.changed_files
    assert card.traces
    assert card.evidence
    # Board-level rehydration (envelope board_full resume)
    restored = wrb.WorkspaceBoard.from_dict(raw)
    assert restored.workspace_id == board.workspace_id
    assert restored.goal == board.goal
    assert len(restored.cards) == 1
    assert restored.cards[0].lane == "dev"
    assert wrb.roles_distinct(restored.roles) is True
    assert restored.signal == board.signal


def test_unknown_lane_rejected():
    board = wrb.create_board("ws", "goal")
    cid = board.cards[0].id
    res = wrb.try_move_card(board, cid, "reviw")
    assert res["ok"] is False
    assert res["moved"] is False
    assert "unknown lane" in res["reason"]
    assert board.cards[0].lane == "backlog"


def test_ac_ref_exact_match_no_prefix_hazard():
    """AC1 must not match evidence ref ac:10 when ≥10 acceptance criteria."""
    acceptance = [f"criterion-{i}" for i in range(1, 11)]
    board, cid = _dev_ready_board(acceptance=acceptance)
    wrb.try_move_card(board, cid, "review")
    for i in range(1, 11):
        wrb.append_evidence(
            board,
            cid,
            kind="ac_check",
            ok=(i != 10),
            ref=f"ac:{i}",
            detail=acceptance[i - 1],
            lane="review",
        )
    wrb.append_evidence(
        board, cid, kind="test_result", ok=True, ref="pytest", detail="green", lane="review"
    )
    gate = wrb.evaluate_review_gate(
        board.cards[0], roles=board.roles, git_clean=True, committed=True
    )
    assert gate["ac_status"]["AC1"] == "verified"
    assert gate["ac_status"]["AC10"] == "failed"
    assert gate["ok"] is False


def test_fitness_latest_wins_allows_convergence():
    """A failed check later superseded by a pass must not permanently wedge."""
    board, cid = _dev_ready_board()
    wrb.try_move_card(board, cid, "review")
    _seed_review_evidence(board, cid)
    # Historical failure
    wrb.append_evidence(
        board, cid, kind="test_result", ok=False, ref="pytest:ok", detail="red", lane="review"
    )
    gate_fail = wrb.evaluate_review_gate(
        board.cards[0], roles=board.roles, git_clean=True, committed=True
    )
    assert gate_fail["ok"] is False
    # Superseding pass (same kind+ref)
    wrb.append_evidence(
        board, cid, kind="test_result", ok=True, ref="pytest:ok", detail="green", lane="review"
    )
    gate_ok = wrb.evaluate_review_gate(
        board.cards[0], roles=board.roles, git_clean=True, committed=True
    )
    assert gate_ok["ok"] is True
    assert gate_ok["verdict"] == wrb.VERDICT_APPROVED


def test_journal_non_numeric_score_does_not_crash():
    board, cid = _dev_ready_board()
    wrb.try_move_card(board, cid, "review")
    report = wrb.advance_from_journal(
        board,
        [{"event": "step_complete", "score": "high", "why": "non-numeric"}],
        card_id=cid,
    )
    assert report["ok"] is True
    assert board.cards[0].lane == "review"  # not good enough to attempt done


def test_norm_without_kind_does_not_block():
    board = wrb.create_board("ws", "norm test")
    cid = board.cards[0].id
    report = wrb.advance_from_journal(
        board,
        [{"event": "norm", "detail": "benign"}],
        card_id=cid,
    )
    assert board.cards[0].lane == "backlog"
    assert report["ok"] is True


def test_git_flags_unobserved_not_attested():
    board, cid = _dev_ready_board()
    wrb.try_move_card(board, cid, "review")
    _seed_review_evidence(board, cid)
    move = wrb.try_move_card(board, cid, "done")  # no git_clean/committed
    assert move["ok"] is True
    harness = (move.get("gate") or {}).get("layers", {}).get("harness") or {}
    assert harness.get("git_clean") is None
    assert harness.get("committed") is None


def test_maybe_build_for_task_opt_in():
    assert wrb.maybe_build_for_task(".", "t1", "goal", None) is None
    assert wrb.maybe_build_for_task(".", "t1", "goal", {}) is None
    assert (
        wrb.maybe_build_for_task(
            ".", "t1", "goal", {"with_workspace_board": False}
        )
        is None
    )
    # Any-True wins over sibling False alias
    out_alias = wrb.maybe_build_for_task(
        ".",
        "t1",
        "Ship board",
        {"with_workspace_board": True, "routa_board": False, "start_lane": "todo"},
    )
    assert out_alias is not None and out_alias["ok"] is True
    out = wrb.maybe_build_for_task(
        ".",
        "t1",
        "Ship board",
        {
            "with_workspace_board": True,
            "workspace_id": "ws-orch",
            "acceptance": ["done"],
            "changed_files": ["a.py"],
            "start_lane": "dev",
        },
    )
    assert out is not None
    assert out["ok"] is True
    assert out["workspace_id"] == "ws-orch"
    assert out["lane"] == "dev"
    assert out["board"]["primary_lane"] == "dev"
    assert "brief" in out


def test_maybe_build_start_lane_done_capped_at_review():
    out = wrb.maybe_build_for_task(
        ".",
        "t1",
        "Ship board",
        {"with_workspace_board": True, "start_lane": "done"},
    )
    assert out is not None and out["ok"] is True
    assert out["lane"] == "review"
    card = (out.get("board_full") or {}).get("cards") or [{}]
    assert (card[0].get("review_findings") or {}).get("verdict") == "SEEDED"


def test_maybe_build_empty_goal_fails():
    out = wrb.maybe_build_for_task(
        ".", "t1", "", {"with_workspace_board": True}
    )
    assert out is not None
    assert out["ok"] is False
    assert "goal" in out["error"]


def test_cli_main_json(capsys):
    rc = wrb.main(["Ship it", "--workspace", "ws-cli", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == wrb.SCHEMA
    assert data["workspace_id"] == "ws-cli"


def test_cli_main_demo_gate(capsys):
    rc = wrb.main(["--demo-gate", "--workspace", "ws-demo"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "APPROVED" in out or "verdict=APPROVED" in out
    assert "done" in out.lower() or "lane=done" in out


def test_append_trace_and_evidence():
    board = wrb.create_board("ws", "goal")
    cid = board.cards[0].id
    tr = wrb.append_trace(board, cid, action="note", detail="hello")
    assert tr.action == "note"
    assert len(board.cards[0].traces) >= 2
    ev = wrb.append_evidence(
        board, cid, kind="note", ok=True, ref="r1", detail="d"
    )
    assert ev.ok is True
    assert board.cards[0].evidence[-1].ref == "r1"


def test_orchestrator_attaches_workspace_board(tmp_path, monkeypatch):
    """Opt-in meta.with_workspace_board lands on envelope + status."""
    from pathlib import Path

    from nexus.orchestrator import Orchestrator, load_envelope

    root = Path(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    out = orch.run_task(
        "Ship workspace-first review board",
        kind="task",
        agent_mode="fake",
        task_id="ws-board-1",
        sync_fake=True,
        meta={
            "with_workspace_board": True,
            "workspace_id": "ws-orch",
            "acceptance": ["gate stacks layers"],
            "start_lane": "todo",
        },
    )
    assert out.get("workspace_review_board_ok") is True
    summary = out.get("workspace_review_board_summary") or {}
    assert summary.get("workspace_id") == "ws-orch"
    assert summary.get("lane") == "todo"
    assert summary.get("source_pattern") == "phodal/routa"
    assert out.get("workspace_review_board_brief")

    env = load_envelope(root, "ws-board-1")
    assert env is not None
    assert env.meta.get("workspace_review_board_pattern") == "phodal/routa"
    init = env.meta.get("workspace_review_board_init") or {}
    assert init.get("lane") == "todo"
    assert init.get("workspace_id") == "ws-orch"
    raw = env.meta.get("workspace_review_board")
    assert isinstance(raw, dict)
    assert raw.get("primary_lane") == "todo"


def test_orchestrator_skips_workspace_board_by_default(tmp_path, monkeypatch):
    from pathlib import Path

    from nexus.orchestrator import Orchestrator, load_envelope

    root = Path(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    out = orch.run_task(
        "No board unless opted in",
        kind="task",
        agent_mode="fake",
        task_id="ws-board-off",
        sync_fake=True,
        meta={},
    )
    assert out.get("workspace_review_board_ok") is not True
    env = load_envelope(root, "ws-board-off")
    assert env is not None
    assert not env.meta.get("workspace_review_board_init")
