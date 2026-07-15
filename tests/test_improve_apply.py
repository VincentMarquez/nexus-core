"""Tests for improve-apply phase FSM, decision audit, and path safety.

First apply slice: grade → durable phases → decision audit (lumen + tiger_cowork).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import improve_apply as ia
from nexus import mcp_server


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def test_safe_path_under_workspace(tmp_path: Path):
    p = ia.safe_path(tmp_path, "a/b.txt")
    assert p == (tmp_path / "a" / "b.txt").resolve()
    p.parent.mkdir(parents=True)
    p.write_text("ok", encoding="utf-8")
    assert p.read_text(encoding="utf-8") == "ok"


def test_safe_path_rejects_escape(tmp_path: Path):
    with pytest.raises(ia.PathSafetyError):
        ia.safe_path(tmp_path, "../outside.txt")
    with pytest.raises(ia.PathSafetyError):
        ia.safe_path(tmp_path, "/etc/passwd")


def test_assert_under_workspace_rejects_sibling(tmp_path: Path):
    sibling = tmp_path.parent / f"escape-{tmp_path.name}"
    with pytest.raises(ia.PathSafetyError):
        ia.assert_under_workspace(tmp_path, sibling)


# ---------------------------------------------------------------------------
# Phase FSM
# ---------------------------------------------------------------------------


def test_phase_fsm_valid_transitions_and_idempotent(tmp_path: Path):
    run = ia.start_run(tmp_path, grade=ia.default_lumen_grade(), run_id="t-fsm")
    assert run.phase == "briefed"

    # seal briefed (idempotent)
    assert run.ensure_briefed() == "briefed"
    assert run.ensure_briefed() == "briefed"

    assert run.ensure_context_packed() == "context_packed"
    assert run.ensure_context_packed() == "context_packed"  # no-op

    assert run.ensure_applying() == "applying"
    assert run.ensure_applying() == "applying"

    assert run.ensure_audited() == "audited"
    assert run.ensure_audited() == "audited"

    assert run.ensure_done() == "done"
    assert run.ensure_done() == "done"

    # re-run full pipeline is idempotent
    st = run.run_to_done()
    assert st["phase"] == "done"
    assert st["audit_path"]
    assert (tmp_path / st["audit_path"]).is_file()


def test_phase_fsm_illegal_skip_raises(tmp_path: Path):
    run = ia.start_run(tmp_path, grade=ia.default_lumen_grade(), run_id="t-skip")
    with pytest.raises(ia.PhaseGuardError):
        run.transition("applying")  # skip context_packed
    with pytest.raises(ia.PhaseGuardError):
        run.transition("done")
    # same phase ok
    assert run.transition("briefed") == "briefed"
    # next ok
    assert run.transition("context_packed") == "context_packed"
    # backtrack refused
    with pytest.raises(ia.PhaseGuardError):
        run.transition("briefed")


def test_advance_one_steps(tmp_path: Path):
    run = ia.start_run(tmp_path, grade=ia.default_lumen_grade(), run_id="t-one")
    # first advance seals briefed
    st = run.advance_one()
    assert st["phase"] == "briefed"
    st = run.advance_one()
    assert st["phase"] == "context_packed"
    st = run.advance_one()
    assert st["phase"] == "applying"
    st = run.advance_one()
    assert st["phase"] == "audited"
    st = run.advance_one()
    assert st["phase"] == "done"
    st = run.advance_one()
    assert st["phase"] == "done"


# ---------------------------------------------------------------------------
# Audit schema
# ---------------------------------------------------------------------------


def test_audit_schema_required_fields():
    with pytest.raises(ia.AuditValidationError):
        ia.validate_audit({"repo": "x"})  # missing most fields

    bad = ia.build_audit(
        repo="ahmedEid1/lumen",
        score=15.0,
        idea=7.0,
        skill=8.0,
        pattern="idempotent phases + decision audit",
        files_touched=["a.py"],
        action_order=["briefed", "done"],
        evidence_refs=[".nexus_workspaces/improve_apply/x/context_pack.json"],
    )
    # orphan — file missing
    with pytest.raises(ia.AuditValidationError, match="orphan|missing"):
        ia.validate_audit(bad, workspace_root=Path("/tmp"), require_evidence_exists=True)


def test_audit_rejects_orphan_outside_workspaces(tmp_path: Path):
    (tmp_path / "outside.txt").write_text("nope", encoding="utf-8")
    audit = ia.build_audit(
        repo="ahmedEid1/lumen",
        score=15.0,
        idea=7.0,
        skill=8.0,
        pattern="p",
        files_touched=[],
        action_order=["briefed"],
        evidence_refs=["outside.txt"],  # not under .nexus_workspaces
    )
    with pytest.raises(ia.AuditValidationError, match="orphan|nexus_workspaces"):
        ia.validate_audit(audit, workspace_root=tmp_path, require_evidence_exists=True)


def test_audit_accepts_valid_evidence(tmp_path: Path):
    ws = tmp_path / ".nexus_workspaces" / "improve_apply" / "r1"
    ws.mkdir(parents=True)
    evid = ws / "context_pack.json"
    evid.write_text("{}", encoding="utf-8")
    rel = str(evid.relative_to(tmp_path))
    audit = ia.build_audit(
        repo="ahmedEid1/lumen",
        arxiv_id="2510.13343",
        score=15.0,
        idea=7.0,
        skill=8.0,
        method="grok:grok-4.5",
        pattern="idempotent phases + decision audit",
        files_touched=[rel],
        action_order=["briefed", "context_packed", "applying", "audited", "done"],
        evidence_refs=[rel],
    )
    out = ia.validate_audit(audit, workspace_root=tmp_path, require_evidence_exists=True)
    assert out["repo"] == "ahmedEid1/lumen"
    assert out["score"] == 15.0


# ---------------------------------------------------------------------------
# Integration: fixture → dry-run → audit → done
# ---------------------------------------------------------------------------


def test_integration_lumen_fixture_to_done(tmp_path: Path):
    # Simulate mine_eval fixture directory
    fixture = tmp_path / ".nexus_workspaces" / "mine_eval" / "ahmedEid1__lumen"
    fixture.mkdir(parents=True)
    (fixture / "README.md").write_text("# lumen fixture\n", encoding="utf-8")

    status = ia.run_demo(
        tmp_path,
        fixture=fixture,
        run_id="demo-lumen",
        show_audit=True,
        dry_run=True,
    )
    assert status["phase"] == "done"
    assert status["grade"]["repo"] == "ahmedEid1/lumen"
    assert float(status["grade"]["score"]) == 15.0
    assert status["audit_path"]
    audit_path = tmp_path / status["audit_path"]
    assert audit_path.is_file()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["method"].startswith("grok:")
    assert "idempotent" in audit["pattern"].lower() or "decision audit" in audit["pattern"].lower()
    assert audit["action_order"][0] == "briefed"
    assert audit["action_order"][-1] == "done"
    assert audit["evidence_refs"]
    # re-run does not corrupt
    status2 = ia.run_demo(tmp_path, run_id="demo-lumen", show_audit=False)
    assert status2["phase"] == "done"
    assert status2["audit_path"] == status["audit_path"]
    audit2 = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit2["repo"] == audit["repo"]
    assert "demo_text" in status
    assert "self-improve" in status["demo_text"].lower() or "phase" in status["demo_text"].lower()


def test_resume_from_disk(tmp_path: Path):
    run = ia.start_run(tmp_path, grade=ia.default_lumen_grade(), run_id="resume-me")
    run.ensure_briefed()
    run.ensure_context_packed()
    loaded = ia.ImproveApplyRun.load(tmp_path, "resume-me")
    assert loaded.phase == "context_packed"
    st = loaded.run_to_done()
    assert st["phase"] == "done"


def test_list_runs(tmp_path: Path):
    ia.start_run(tmp_path, run_id="a")
    ia.start_run(tmp_path, run_id="b")
    rows = ia.list_runs(tmp_path)
    ids = {r["run_id"] for r in rows}
    assert "a" in ids and "b" in ids


# ---------------------------------------------------------------------------
# MCP + CLI surface
# ---------------------------------------------------------------------------


def test_mcp_apply_phase_tool(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    # tools/list includes apply_phase
    tools = mcp_server.handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    names = [t["name"] for t in tools["result"]["tools"]]
    assert "apply_phase" in names

    res = mcp_server.call_tool(
        "apply_phase",
        {"advance": "all", "dry_run": True, "run_id": "mcp-ia-1"},
    )
    assert res["isError"] is False
    body = json.loads(res["content"][0]["text"])
    assert body["phase"] == "done"
    assert body["audit_path"]
    assert body["grade"]["repo"] == "ahmedEid1/lumen"

    # status only
    res2 = mcp_server.call_tool(
        "apply_phase",
        {"advance": "status", "run_id": "mcp-ia-1"},
    )
    body2 = json.loads(res2["content"][0]["text"])
    assert body2["phase"] == "done"


def test_cli_demo_self_improve_slice(tmp_path: Path, monkeypatch):
    from nexus.cli import main

    monkeypatch.chdir(tmp_path)
    # ensure workdir uses tmp
    rc = main(
        [
            "demo",
            "self-improve-slice",
            "--workdir",
            str(tmp_path),
            "--run-id",
            "cli-slice",
            "--show-audit",
        ]
    )
    assert rc == 0
    state = (
        tmp_path
        / ".nexus_workspaces"
        / "improve_apply"
        / "cli-slice"
        / "state.json"
    )
    assert state.is_file()
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["phase"] == "done"
