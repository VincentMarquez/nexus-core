"""Tests for grade artifact contract + ordered grade_read→apply_plan loop.

First apply slice: P0.1 ordered steps, P0.2 grade schema, P0.3 MCP tools,
P0.4 anti-premature success, P0.5 audit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import grade_artifact as ga
from nexus import mcp_server


# ---------------------------------------------------------------------------
# Grade schema
# ---------------------------------------------------------------------------


def test_validate_grade_requires_fields():
    with pytest.raises(ga.GradeValidationError, match="missing"):
        ga.validate_grade({"repo": "a/b"})
    with pytest.raises(ga.GradeValidationError):
        ga.validate_grade(
            {
                "repo": "a/b",
                "score": "x",
                "idea": 1,
                "skill": 1,
                "method": "m",
                "path": "p",
            }
        )


def test_grade_roundtrip(tmp_path: Path):
    g = ga.build_grade(
        repo="builderz-labs/mission-control",
        score=15.0,
        idea=7.0,
        skill=8.0,
        method="grok:grok-4.5",
        path=str(tmp_path / "mine" / "mc"),
        pattern="ops control plane",
    )
    path = tmp_path / "grade.json"
    ga.write_grade(path, g)
    loaded = ga.load_grade(path)
    assert loaded["repo"] == "builderz-labs/mission-control"
    assert loaded["score"] == 15.0
    assert loaded["idea"] == 7.0
    assert loaded["skill"] == 8.0
    assert loaded["method"] == "grok:grok-4.5"
    assert loaded["path"]
    assert loaded["schema"] == ga.SCHEMA_VERSION


def test_validate_rejects_empty_repo():
    with pytest.raises(ga.GradeValidationError, match="repo"):
        ga.validate_grade(
            {
                "repo": "  ",
                "score": 10,
                "idea": 5,
                "skill": 5,
                "method": "m",
                "path": "p",
            }
        )


# ---------------------------------------------------------------------------
# Offline list from IMPROVE_OURS digests
# ---------------------------------------------------------------------------


def test_list_graded_from_improve_ours(tmp_path: Path):
    root = tmp_path / ".nexus_state" / "repo_mine"
    root.mkdir(parents=True)
    (root / "IMPROVE_OURS.md").write_text(
        """# Improve our project

## wshobson/agents (score 15.0)
- idea=7.0 skill=8.0
- A multi-harness agentic plugin marketplace.
- local clone: /tmp/scout/wshobson__agents

## builderz-labs/mission-control (score 15.0)
- idea=7.0 skill=8.0
- SQLite-backed agent control plane.
- local clone: /tmp/scout/mission-control

## low/score (score 3.0)
- idea=1.0 skill=2.0
- should be filtered
""",
        encoding="utf-8",
    )
    # plant mine_eval dirs so path resolves
    for slug in ("wshobson__agents", "builderz-labs__mission-control"):
        d = tmp_path / ".nexus_workspaces" / "mine_eval" / slug
        d.mkdir(parents=True)
        (d / "README.md").write_text("x", encoding="utf-8")

    rows = ga.list_graded_candidates(tmp_path, min_score=10.0, limit=10)
    repos = {r["repo"] for r in rows}
    assert "wshobson/agents" in repos
    assert "builderz-labs/mission-control" in repos
    assert "low/score" not in repos
    for r in rows:
        assert r["score"] >= 10.0
        assert r["idea"] is not None
        assert r["skill"] is not None
        assert r["method"]
        assert r["path"]

    one = ga.get_grade(tmp_path, "wshobson/agents")
    assert one is not None
    assert one["score"] == 15.0
    assert one["idea"] == 7.0
    assert one["skill"] == 8.0


# ---------------------------------------------------------------------------
# Ordered checkpoint: grade_read → apply_plan + crash resume
# ---------------------------------------------------------------------------


def test_checkpoint_preserves_next_agent(tmp_path: Path):
    grade = ga.build_grade(
        repo="ahmedEid1/lumen",
        score=15.0,
        idea=7.0,
        skill=8.0,
        path=str(tmp_path / ".nexus_workspaces" / "mine_eval" / "ahmedEid1__lumen"),
    )
    (tmp_path / ".nexus_workspaces" / "mine_eval" / "ahmedEid1__lumen").mkdir(
        parents=True
    )
    run = ga.start_ordered_loop(tmp_path, grade=grade, run_id="cp-1")
    assert run.next_agent == "grade_read"
    st = run.run_grade_read()
    assert st["next_agent"] == "apply_plan"
    assert "grade_read" in st["completed"]
    # simulate crash: reload from disk
    resumed = ga.resume_ordered_loop(tmp_path, "cp-1")
    assert resumed.next_agent == "apply_plan"
    assert resumed.resume_ok is True
    cp = ga.get_run_checkpoint(tmp_path, "cp-1")
    assert cp["next_agent"] == "apply_plan"
    assert "grade_read" in (cp.get("action_order") or ga.ORDERED_STEPS)


def test_resume_apply_plan_once_no_double(tmp_path: Path):
    grade = ga.build_grade(
        repo="ahmedEid1/lumen",
        score=15.0,
        idea=7.0,
        skill=8.0,
        path=str(tmp_path / ".nexus_workspaces" / "mine_eval" / "lumen"),
        pattern="decision audit",
    )
    (tmp_path / ".nexus_workspaces" / "mine_eval" / "lumen").mkdir(parents=True)
    run = ga.start_ordered_loop(tmp_path, grade=grade, run_id="once-1")
    run.run_grade_read()
    mid = ga.resume_ordered_loop(tmp_path, "once-1")
    st1 = mid.run_apply_plan()
    assert st1["status"] == "success"
    assert st1["audit_path"]
    # second apply is idempotent (no double audit rewrite of action)
    st2 = mid.run_apply_plan()
    assert st2["status"] == "success"
    assert st2["completed"].count("apply_plan") == 1
    # grade_read cannot re-run as next
    assert mid.next_agent == "done"


def test_success_guard_blocks_premature(tmp_path: Path):
    grade = ga.build_grade(
        repo="x/y", score=15.0, idea=7.0, skill=8.0, path="p"
    )
    # missing audit + resume
    g = ga.success_guard(grade=grade, resume_ok=False, audit=None)
    assert g["ok"] is False
    assert g["status"] == "blocked"

    # force complete always blocked
    g2 = ga.success_guard(
        grade=grade,
        resume_ok=True,
        audit={"repo": "x/y"},
        force_complete=True,
    )
    assert g2["ok"] is False

    # low score
    low = ga.build_grade(repo="x/y", score=3.0, idea=1.0, skill=2.0, path="p")
    g3 = ga.success_guard(
        grade=low, resume_ok=True, audit={"ok": True}, threshold=10.0
    )
    assert g3["ok"] is False

    with pytest.raises(ga.PrematureCompleteError):
        ga.assert_success(grade=grade, resume_ok=False, audit=None)


def test_full_loop_success_and_board(tmp_path: Path):
    grade = ga.build_grade(
        repo="IBM/AssetOpsBench",
        score=15.0,
        idea=8.0,
        skill=7.0,
        path=str(tmp_path / ".nexus_workspaces" / "mine_eval" / "IBM__AssetOpsBench"),
        pattern="MCP domain servers",
    )
    (tmp_path / ".nexus_workspaces" / "mine_eval" / "IBM__AssetOpsBench").mkdir(
        parents=True
    )
    run = ga.start_ordered_loop(tmp_path, grade=grade, run_id="full-1")
    st = run.run_to_done()
    assert st["status"] == "success"
    assert st["guard"]["ok"] is True
    board = ga.format_board(st)
    assert "review:   pass" in board or "review: pass" in board.replace("  ", " ")
    assert "IBM/AssetOpsBench" in board
    assert "grade_read" in board
    # status via helper
    st2 = ga.get_run_status(tmp_path, "full-1")
    assert st2["status"] == "success"


# ---------------------------------------------------------------------------
# MCP contract tools
# ---------------------------------------------------------------------------


def test_mcp_grade_tools(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    root = tmp_path / ".nexus_state" / "repo_mine"
    root.mkdir(parents=True)
    (root / "IMPROVE_OURS.md").write_text(
        """## ahmedEid1/lumen (score 15.0)
- idea=7.0 skill=8.0
- decision audit loop
- local clone: {p}/.nexus_workspaces/mine_eval/ahmedEid1__lumen
""".format(p=tmp_path),
        encoding="utf-8",
    )
    d = tmp_path / ".nexus_workspaces" / "mine_eval" / "ahmedEid1__lumen"
    d.mkdir(parents=True)

    tools = mcp_server.handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    names = [t["name"] for t in tools["result"]["tools"]]
    for need in (
        "list_graded_candidates",
        "get_grade",
        "get_run_checkpoint",
        "get_run_status",
    ):
        assert need in names

    listed = mcp_server.call_tool(
        "list_graded_candidates", {"min_score": 10.0, "limit": 5}
    )
    assert listed["isError"] is False
    body = json.loads(listed["content"][0]["text"])
    assert body["count"] >= 1
    assert body["candidates"][0]["repo"] == "ahmedEid1/lumen"

    got = mcp_server.call_tool("get_grade", {"repo": "ahmedEid1/lumen"})
    assert got["isError"] is False
    g = json.loads(got["content"][0]["text"])
    assert g["score"] == 15.0
    assert g["idea"] == 7.0

    # start loop + checkpoint after grade_read
    run = ga.start_ordered_loop(
        tmp_path,
        grade=ga.get_grade(tmp_path, "ahmedEid1/lumen"),
        run_id="mcp-run",
    )
    run.run_grade_read()
    cp = mcp_server.call_tool("get_run_checkpoint", {"run_id": "mcp-run"})
    assert cp["isError"] is False
    cpb = json.loads(cp["content"][0]["text"])
    assert cpb["next_agent"] == "apply_plan"

    run.run_apply_plan()
    st = mcp_server.call_tool("get_run_status", {"run_id": "mcp-run"})
    assert st["isError"] is False
    stb = json.loads(st["content"][0]["text"])
    assert stb["status"] == "success"
    assert stb["audit_path"]


def test_mcp_missing_run_is_error(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    bad = mcp_server.call_tool("get_run_status", {"run_id": "nope"})
    assert bad["isError"] is True
