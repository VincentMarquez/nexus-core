"""Tests for forge-shaped Wish→Forge→Review multi-attempt board.

Portfolio idea: automagik-dev/forge
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import forge_board as fb


def test_normalize_lane_aliases():
    assert fb.normalize_lane("todo") == fb.LANE_WISH
    assert fb.normalize_lane("inprogress") == fb.LANE_FORGE
    assert fb.normalize_lane("in_progress") == fb.LANE_FORGE
    assert fb.normalize_lane("inreview") == fb.LANE_REVIEW
    assert fb.normalize_lane("Wish") == fb.LANE_WISH
    assert fb.normalize_lane("DONE") == fb.LANE_DONE
    assert fb.normalize_lane("archived") == fb.LANE_CANCELLED


def test_can_transition_happy_and_illegal():
    assert fb.can_transition("wish", "forge") is True
    assert fb.can_transition("forge", "review") is True
    assert fb.can_transition("review", "done") is True
    assert fb.can_transition("review", "forge") is True  # retry
    assert fb.can_transition("done", "wish") is False
    assert fb.can_transition("wish", "done") is False
    assert fb.can_transition("wish", "wish") is True


def test_create_board_requires_project():
    with pytest.raises(fb.ForgeBoardError, match="project_id"):
        fb.create_board("")


def test_create_task_wish_column():
    board = fb.create_board("proj-1", "Demo")
    task = fb.create_task(
        board,
        "Ship forge board",
        acceptance=["multi-attempt", "isolation"],
    )
    d = board.to_dict()
    assert d["schema"] == fb.SCHEMA
    assert d["source_pattern"] == "automagik-dev/forge"
    assert d["idea_id"] == fb.IDEA_ID
    assert task.lane == fb.LANE_WISH
    assert d["lane_counts"]["wish"] == 1
    assert task.acceptance == ["multi-attempt", "isolation"]


def test_create_task_requires_title():
    board = fb.create_board("p")
    with pytest.raises(fb.ForgeBoardError, match="title"):
        fb.create_task(board, "  ")


def test_start_attempt_moves_wish_to_forge(tmp_path: Path):
    board = fb.create_board("p")
    task = fb.create_task(board, "Implement feature")
    att = fb.start_attempt(
        board,
        task.id,
        executor="grok",
        agent="implementer",
        workdir=tmp_path,
        isolation="sandbox",
    )
    assert task.lane == fb.LANE_FORGE
    assert att.status == fb.ATTEMPT_RUNNING
    assert att.executor == "grok"
    assert att.isolation_mode == "sandbox"
    assert att.worktree_path
    marker = Path(att.worktree_path) / ".nexus_forge_attempt.json"
    assert marker.is_file()
    body = json.loads(marker.read_text(encoding="utf-8"))
    assert body["schema"] == fb.SCHEMA
    assert body["attempt_id"] == att.id
    assert body["executor"] == "grok"
    # isolation under forge_attempts
    assert fb.ATTEMPT_ROOT in att.worktree_path.replace("\\", "/")


def test_main_isolation_untouched_when_no_workdir():
    board = fb.create_board("p")
    task = fb.create_task(board, "Plan only")
    att = fb.start_attempt(
        board, task.id, isolation="none", workdir=None, auto_move_to_forge=True
    )
    assert att.worktree_path == ""
    assert att.isolation_mode == "none"
    assert task.lane == fb.LANE_FORGE


def test_multi_attempt_compare_and_select(tmp_path: Path):
    board = fb.create_board("p")
    task = fb.create_task(board, "Try two providers")
    a1 = fb.start_attempt(
        board,
        task.id,
        executor="local",
        agent="implementer",
        workdir=tmp_path,
    )
    fb.finish_attempt(
        board,
        a1.id,
        ok=True,
        summary="good",
        changed_files=["src/nexus/forge_board.py"],
    )
    a2 = fb.start_attempt(
        board,
        task.id,
        executor="claude_code",
        agent="test-writer",
        workdir=tmp_path,
    )
    fb.finish_attempt(
        board,
        a2.id,
        ok=False,
        summary="bad",
        error="tests red",
    )
    cmp_ = fb.compare_attempts(board, task.id)
    assert cmp_["n_attempts"] == 2
    assert cmp_["n_succeeded"] == 1
    assert cmp_["recommendation"] == a1.id

    # cannot select failed
    with pytest.raises(fb.ForgeBoardError, match="succeeded"):
        fb.select_attempt(board, task.id, a2.id)

    fb.select_attempt(board, task.id, a1.id)
    assert task.lane == fb.LANE_REVIEW
    assert task.selected_attempt_id == a1.id
    assert board.signal == fb.SIGNAL_REVIEW
    assert a1.selected is True
    assert a2.selected is False


def test_finish_attempt_idempotent_guard():
    board = fb.create_board("p")
    task = fb.create_task(board, "x")
    att = fb.start_attempt(board, task.id, isolation="none")
    fb.finish_attempt(board, att.id, ok=True, summary="once")
    with pytest.raises(fb.ForgeBoardError, match="already finished"):
        fb.finish_attempt(board, att.id, ok=True, summary="twice")


def test_review_to_done_requires_selected_success():
    board = fb.create_board("p")
    task = fb.create_task(board, "ship gate")
    # force into review without selection
    task.lane = fb.LANE_REVIEW
    move = fb.try_move_task(board, task.id, fb.LANE_DONE)
    assert move["ok"] is False
    assert "no_selected_attempt" in move["reasons"]

    att = fb.start_attempt(board, task.id, isolation="none", auto_move_to_forge=False)
    # task still review; finish + select without auto lane change
    fb.finish_attempt(board, att.id, ok=True, summary="ok")
    fb.select_attempt(board, task.id, att.id, auto_move_to_review=False)
    ship = fb.ship_task(board, task.id)
    assert ship["ok"] is True
    assert task.lane == fb.LANE_DONE
    assert board.signal == fb.SIGNAL_SHIP


def test_forge_to_review_auto_selects_sole_success():
    board = fb.create_board("p")
    task = fb.create_task(board, "solo")
    att = fb.start_attempt(board, task.id, isolation="none")
    fb.finish_attempt(
        board, att.id, ok=True, summary="only one", changed_files=["a.py"]
    )
    assert task.lane == fb.LANE_FORGE
    move = fb.try_move_task(board, task.id, fb.LANE_REVIEW)
    assert move["ok"] is True
    assert task.selected_attempt_id == att.id
    assert task.lane == fb.LANE_REVIEW


def test_forge_to_review_blocks_without_success():
    board = fb.create_board("p")
    task = fb.create_task(board, "fail only")
    att = fb.start_attempt(board, task.id, isolation="none")
    fb.finish_attempt(board, att.id, ok=False, error="boom")
    move = fb.try_move_task(board, task.id, fb.LANE_REVIEW)
    assert move["ok"] is False
    assert "no_succeeded_attempt" in move["reasons"]


def test_illegal_transition_raises():
    board = fb.create_board("p")
    task = fb.create_task(board, "jump")
    with pytest.raises(fb.ForgeBoardError, match="illegal"):
        fb.try_move_task(board, task.id, fb.LANE_DONE)


def test_cancel_and_reopen():
    board = fb.create_board("p")
    task = fb.create_task(board, "maybe later")
    move = fb.try_move_task(board, task.id, fb.LANE_CANCELLED)
    assert move["ok"] is True
    assert task.lane == fb.LANE_CANCELLED
    assert board.signal == fb.SIGNAL_CANCEL
    reopen = fb.try_move_task(board, task.id, fb.LANE_WISH)
    assert reopen["ok"] is True
    assert task.lane == fb.LANE_WISH


def test_cannot_start_on_done():
    board = fb.create_board("p")
    task = fb.create_task(board, "done")
    task.lane = fb.LANE_DONE
    with pytest.raises(fb.ForgeBoardError, match="done"):
        fb.start_attempt(board, task.id, isolation="none")


def test_from_dict_roundtrip(tmp_path: Path):
    board = fb.run_demo(tmp_path, project_id="rt")
    raw = board.to_dict()
    board2 = fb.ForgeBoard.from_dict(raw)
    assert board2.project_id == "rt"
    assert board2.tasks[0].lane == fb.LANE_DONE
    assert len(board2.tasks[0].attempts) == 2
    assert board2.tasks[0].selected_attempt_id
    # re-serialize stable schema
    assert board2.to_dict()["schema"] == fb.SCHEMA


def test_run_demo_with_sandbox(tmp_path: Path):
    board = fb.run_demo(tmp_path)
    assert board.status == "demo_complete"
    task = board.tasks[0]
    assert task.lane == fb.LANE_DONE
    assert len(task.attempts) == 2
    ok = [a for a in task.attempts if a.status == fb.ATTEMPT_SUCCEEDED]
    bad = [a for a in task.attempts if a.status == fb.ATTEMPT_FAILED]
    assert len(ok) == 1 and len(bad) == 1
    assert ok[0].worktree_path
    assert Path(ok[0].worktree_path).is_dir()
    # main tmp is not polluted with pattern files outside forge_attempts
    roots = list((tmp_path / fb.ATTEMPT_ROOT).rglob(".nexus_forge_attempt.json"))
    assert len(roots) == 2


def test_sandbox_paths_isolated_per_attempt(tmp_path: Path):
    board = fb.create_board("p")
    task = fb.create_task(board, "parallel")
    a1 = fb.start_attempt(
        board, task.id, executor="local", agent="a", workdir=tmp_path
    )
    a2 = fb.start_attempt(
        board, task.id, executor="grok", agent="b", workdir=tmp_path
    )
    assert a1.worktree_path != a2.worktree_path
    assert Path(a1.worktree_path).is_dir()
    assert Path(a2.worktree_path).is_dir()
    # writing in one does not create files in the other
    p = Path(a1.worktree_path) / "only_a.txt"
    p.write_text("a", encoding="utf-8")
    assert not (Path(a2.worktree_path) / "only_a.txt").exists()


def test_duplicate_worktree_raises(tmp_path: Path):
    board = fb.create_board("p")
    task = fb.create_task(board, "dup")
    aid = "att-fixed"
    fb.start_attempt(
        board, task.id, workdir=tmp_path, attempt_id=aid, isolation="sandbox"
    )
    with pytest.raises(fb.ForgeBoardError, match="already exists"):
        fb.create_attempt_worktree(
            tmp_path,
            task_id=task.id,
            attempt_id=aid,
            executor="local",
            agent="implementer",
            mode="sandbox",
        )


def test_maybe_build_opt_in(tmp_path: Path):
    assert fb.maybe_build_for_task(tmp_path, "t1", "g", None) is None
    assert fb.maybe_build_for_task(tmp_path, "t1", "g", {}) is None
    out = fb.maybe_build_for_task(
        tmp_path,
        "t-forge",
        "Build multi-attempt board",
        {
            "with_forge_board": True,
            "project_id": "proj-x",
            "acceptance": ["a", "b"],
            "seed_attempt": True,
            "seed_attempt_ok": True,
            "select_seed": True,
            "isolation": "none",
            "changed_files": ["src/nexus/forge_board.py"],
        },
    )
    assert out is not None
    assert out["ok"] is True
    assert out["schema"] == fb.SCHEMA
    assert out["source_pattern"] == "automagik-dev/forge"
    assert out["lane"] == fb.LANE_REVIEW
    assert out["board"]["n_tasks"] == 1
    assert "wish" in out["brief"] or "review" in out["brief"]


def test_maybe_build_seed_capped_at_review(tmp_path: Path):
    out = fb.maybe_build_for_task(
        tmp_path,
        "t2",
        "goal",
        {
            "forge_board": True,
            "start_lane": "done",
            "seed_attempt": True,
            "seed_attempt_ok": True,
            "select_seed": True,
            "isolation": "none",
        },
    )
    assert out and out["ok"]
    # done seed is capped at review (ship requires explicit gate)
    full = out["board_full"]
    task = full["tasks"][0]
    assert task["lane"] == fb.LANE_REVIEW
    assert task["meta"].get("seed_capped") == "review"


def test_format_board_contains_columns():
    board = fb.create_board("p", "T")
    fb.create_task(board, "one")
    text = fb.format_board(board)
    assert "forge board" in text
    assert "automagik-dev/forge" in text
    assert "wish" in text


def test_board_payload_compact():
    board = fb.create_board("p")
    fb.create_task(board, "x")
    payload = fb.board_payload_for_meta(board)
    assert payload["schema"] == fb.SCHEMA
    assert "tasks" in payload
    assert "brief" in payload
    assert payload["tasks"][0]["lane"] == fb.LANE_WISH


def test_changed_files_dedupe():
    board = fb.create_board("p")
    task = fb.create_task(board, "files")
    att = fb.start_attempt(board, task.id, isolation="none")
    fb.finish_attempt(
        board,
        att.id,
        ok=True,
        changed_files=["a.py", "a.py", " b.py ", "", "b.py"],
    )
    assert att.changed_files == ["a.py", "b.py"]


def test_main_demo_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    rc = fb.main(["--demo", "--workdir", str(tmp_path), "--json", "--project", "cli"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema"] == fb.SCHEMA
    assert data["project_id"] == "cli"
    assert data["tasks"][0]["lane"] == fb.LANE_DONE


def test_get_task_missing():
    board = fb.create_board("p")
    with pytest.raises(fb.ForgeBoardError, match="not found"):
        fb.get_task(board, "nope")


def test_retry_review_to_forge():
    board = fb.create_board("p")
    task = fb.create_task(board, "retry")
    att = fb.start_attempt(board, task.id, isolation="none")
    fb.finish_attempt(board, att.id, ok=True, summary="v1")
    fb.select_attempt(board, task.id, att.id)
    assert task.lane == fb.LANE_REVIEW
    back = fb.try_move_task(board, task.id, fb.LANE_FORGE, reason="retry")
    assert back["ok"] is True
    assert task.lane == fb.LANE_FORGE
    # new attempt allowed
    a2 = fb.start_attempt(
        board, task.id, executor="gemini", agent="security-expert", isolation="none"
    )
    assert a2.executor == "gemini"
    assert len(task.attempts) == 2


# ---------------------------------------------------------------------------
# Synthesis-round fixes (panel ACCEPT items)
# ---------------------------------------------------------------------------


def test_select_attempt_failed_is_noop_preserves_prior_winner():
    """F1: invalid select must not half-write selection flags."""
    board = fb.create_board("p")
    task = fb.create_task(board, "select atomic")
    a1 = fb.start_attempt(board, task.id, isolation="none", attempt_id="att-ok")
    fb.finish_attempt(board, a1.id, ok=True, summary="winner")
    a2 = fb.start_attempt(board, task.id, isolation="none", attempt_id="att-bad")
    fb.finish_attempt(board, a2.id, ok=False, error="nope")
    fb.select_attempt(board, task.id, a1.id, auto_move_to_review=False)
    assert a1.selected is True
    assert task.selected_attempt_id == a1.id
    with pytest.raises(fb.ForgeBoardError, match="succeeded"):
        fb.select_attempt(board, task.id, a2.id)
    # prior winner intact; failed attempt never flagged selected
    assert a1.selected is True
    assert a2.selected is False
    assert task.selected_attempt_id == a1.id
    cmp_ = fb.compare_attempts(board, task.id)
    selected_rows = [r for r in cmp_["attempts"] if r["selected"]]
    assert len(selected_rows) == 1
    assert selected_rows[0]["id"] == a1.id


def test_path_jail_rejects_traversal_task_id(tmp_path: Path):
    """F2: hostile task_id must not escape forge_attempts root."""
    board = fb.create_board("p")
    with pytest.raises(fb.ForgeBoardError, match="unsafe"):
        fb.create_task(board, "evil", task_id="../../../../../evil")
    with pytest.raises(fb.ForgeBoardError, match="unsafe"):
        fb.create_attempt_worktree(
            tmp_path,
            task_id="../../evil",
            attempt_id="att-y",
            executor="local",
            agent="implementer",
            mode="sandbox",
        )
    with pytest.raises(fb.ForgeBoardError, match="unsafe"):
        fb.create_attempt_worktree(
            tmp_path,
            task_id="ok-task",
            attempt_id="../escape",
            executor="local",
            agent="implementer",
            mode="sandbox",
        )
    # confirmed: nothing written outside workdir root
    outside = tmp_path.parent / "evil"
    assert not outside.exists() or not (outside / "att-y").exists()


def test_sandbox_path_stays_under_attempts_root(tmp_path: Path):
    board = fb.create_board("p")
    task = fb.create_task(board, "safe", task_id="task-safe-1")
    att = fb.start_attempt(
        board, task.id, workdir=tmp_path, attempt_id="att-safe-1", isolation="sandbox"
    )
    root = (tmp_path / fb.ATTEMPT_ROOT).resolve()
    target = Path(att.worktree_path).resolve()
    assert root in target.parents
    assert att.worktree_path.replace("\\", "/").find("..") == -1


def test_unknown_lane_raises_on_try_move():
    """F3: typo lanes must not silently succeed as already_there."""
    board = fb.create_board("p")
    task = fb.create_task(board, "lanes")
    with pytest.raises(fb.ForgeBoardError, match="unknown lane"):
        fb.try_move_task(board, task.id, "qa")
    with pytest.raises(fb.ForgeBoardError, match="unknown lane"):
        fb.try_move_task(board, task.id, "reviw")
    assert fb.can_transition("wish", "banana") is False
    assert fb.can_transition("bogus", "wish") is False
    with pytest.raises(fb.ForgeBoardError, match="unknown lane"):
        fb.normalize_lane("reviw", strict=True)


def test_no_workdir_isolation_is_none_not_sandbox():
    """F4: never claim sandbox without a real sandbox path."""
    board = fb.create_board("p")
    task = fb.create_task(board, "meta only")
    # default isolation="sandbox" but no workdir → truthful "none"
    att = fb.start_attempt(board, task.id, workdir=None)
    assert att.worktree_path == ""
    assert att.isolation_mode == "none"
    with pytest.raises(fb.ForgeBoardError, match="requires workdir"):
        fb.start_attempt(board, task.id, workdir=None, isolation="git")


def test_save_load_board_roundtrip(tmp_path: Path):
    """F5: durable kanban survives process restart via disk snapshot."""
    board = fb.run_demo(tmp_path, project_id="persist-me")
    path = fb.save_board(board, tmp_path)
    assert path.is_file()
    assert fb.BOARD_STATE_DIR in str(path).replace("\\", "/")
    loaded = fb.load_board(tmp_path, "persist-me")
    assert loaded.project_id == "persist-me"
    assert loaded.tasks[0].lane == fb.LANE_DONE
    assert loaded.tasks[0].selected_attempt_id
    assert len(loaded.tasks[0].attempts) == 2
    with pytest.raises(fb.ForgeBoardError, match="not found"):
        fb.load_board(tmp_path, "missing-project")


def test_duplicate_task_and_attempt_ids_rejected():
    """F9: id collisions raise (lookups stay unambiguous)."""
    board = fb.create_board("p")
    fb.create_task(board, "first", task_id="dup-task")
    with pytest.raises(fb.ForgeBoardError, match="duplicate task"):
        fb.create_task(board, "second", task_id="dup-task")
    t = board.tasks[0]
    fb.start_attempt(board, t.id, isolation="none", attempt_id="dup-att")
    with pytest.raises(fb.ForgeBoardError, match="duplicate attempt"):
        fb.start_attempt(board, t.id, isolation="none", attempt_id="dup-att")


def test_ship_resolves_selected_only_within_task():
    """GPT-F3: cannot ship using another task's succeeded attempt id."""
    board = fb.create_board("p")
    t1 = fb.create_task(board, "A", task_id="task-a")
    t2 = fb.create_task(board, "B", task_id="task-b")
    a1 = fb.start_attempt(board, t1.id, isolation="none", attempt_id="att-a")
    fb.finish_attempt(board, a1.id, ok=True, summary="a ok")
    # Malformed: t2 claims t1's attempt as selected while in review
    t2.lane = fb.LANE_REVIEW
    t2.selected_attempt_id = a1.id
    move = fb.try_move_task(board, t2.id, fb.LANE_DONE)
    assert move["ok"] is False
    assert "selected_attempt_missing" in move["reasons"]
    assert t2.lane == fb.LANE_REVIEW


def test_git_mode_requires_repo_auto_records_fallback(tmp_path: Path):
    """F10: forced git fails in non-repo; auto falls back with breadcrumb."""
    # tmp_path is not a git repo — forced git must not soft-succeed as sandbox
    with pytest.raises(fb.ForgeBoardError, match="git"):
        fb.create_attempt_worktree(
            tmp_path,
            task_id="t-git",
            attempt_id="a-git",
            executor="local",
            agent="implementer",
            mode="git",
        )
    # auto → sandbox with recorded reason
    board = fb.create_board("p")
    task = fb.create_task(board, "auto iso", task_id="t-auto")
    att = fb.start_attempt(
        board,
        task.id,
        workdir=tmp_path,
        isolation="auto",
        attempt_id="a-auto",
    )
    assert att.isolation_mode == "sandbox"
    assert att.worktree_path
    assert Path(att.worktree_path).is_dir()
    assert "git_fallback_error" in att.meta
    assert "sandbox" in str(att.meta["git_fallback_error"]).lower()


def test_normalize_lane_uses_forge_status_map():
    """F7: exported map is the single alias source (incl. US canceled)."""
    assert fb.normalize_lane("canceled") == fb.LANE_CANCELLED
    assert fb.FORGE_STATUS_MAP["canceled"] == fb.LANE_CANCELLED
    assert fb.normalize_lane("in-progress") == fb.LANE_FORGE


def test_orchestrator_attaches_forge_board(tmp_path, monkeypatch):
    """F6: opt-in meta.with_forge_board lands on envelope + status."""
    from pathlib import Path

    from nexus.orchestrator import Orchestrator, load_envelope

    root = Path(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    out = orch.run_task(
        "Ship multi-attempt forge board",
        kind="task",
        agent_mode="fake",
        task_id="forge-board-1",
        sync_fake=True,
        meta={
            "with_forge_board": True,
            "project_id": "proj-orch",
            "acceptance": ["select before ship"],
            "seed_attempt": True,
            "seed_attempt_ok": True,
            "select_seed": True,
            "isolation": "none",
            "changed_files": ["src/nexus/forge_board.py"],
        },
    )
    assert out.get("forge_board_ok") is True
    summary = out.get("forge_board_summary") or {}
    assert summary.get("project_id") == "proj-orch"
    assert summary.get("source_pattern") == "automagik-dev/forge"
    assert out.get("forge_board_brief")

    env = load_envelope(root, "forge-board-1")
    assert env is not None
    assert env.meta.get("forge_board_pattern") == "automagik-dev/forge"
    init = env.meta.get("forge_board_init") or {}
    assert init.get("project_id") == "proj-orch"
    assert init.get("lane") == fb.LANE_REVIEW
    raw = env.meta.get("forge_board")
    assert isinstance(raw, dict)
    assert raw.get("n_tasks") == 1


def test_orchestrator_skips_forge_board_by_default(tmp_path, monkeypatch):
    from pathlib import Path

    from nexus.orchestrator import Orchestrator, load_envelope

    root = Path(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    out = orch.run_task(
        "No forge board unless opted in",
        kind="task",
        agent_mode="fake",
        task_id="forge-board-off",
        sync_fake=True,
        meta={},
    )
    assert out.get("forge_board_ok") is not True
    env = load_envelope(root, "forge-board-off")
    assert env is not None
    assert not env.meta.get("forge_board_init")
