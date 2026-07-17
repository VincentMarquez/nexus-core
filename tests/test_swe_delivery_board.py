"""Tests for SWE-Adept × routa delivery board hybrid.

Portfolio idea: novel:arxiv:2603.01327v2+phodal/routa
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import swe_adept_plan as sap
from nexus import swe_delivery_board as sdb
from nexus.orchestrator import Orchestrator, load_envelope


def _mini_repo(tmp_path: Path) -> Path:
    (tmp_path / "src" / "nexus").mkdir(parents=True)
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "src" / "nexus" / "orchestrator.py").write_text(
        '"""Orchestrator façade."""\nSCHEMA = "nexus.orchestrator/v1"\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / "nexus" / "swe_adept_plan.py").write_text(
        '"""SWE-Adept planner."""\n',
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_orchestrator.py").write_text(
        "def test_orch():\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "README.md").write_text("# docs\n", encoding="utf-8")
    return tmp_path


def test_roles_distinct():
    assert sdb.roles_distinct(sdb.ROLES) is True
    assert sdb.roles_distinct({"a": "x", "b": "x", "c": "y"}) is False
    assert sdb.roles_distinct({"a": "only"}) is False


def test_plan_to_board_separates_localization_and_resolution(tmp_path: Path):
    root = _mini_repo(tmp_path)
    plan = sap.build_swe_adept_plan(
        "Implement localization planning in the orchestrator module",
        workdir=root,
        max_targets=4,
    )
    board = sdb.plan_to_board(plan, card_id="c1")
    d = board.to_dict()
    assert d["schema"] == sdb.SCHEMA
    assert d["paper"] == sap.PAPER
    assert d["source_pattern"] == "phodal/routa"
    assert d["idea_id"] == sdb.IDEA_ID
    assert d["roles_ok"] is True
    assert "todo" in d["lane_history"]  # localization lane
    assert any(lane in d["lane_history"] for lane in ("dev", "review", "done"))
    # localization before resolution in history
    todo_i = d["lane_history"].index("todo")
    later = [l for l in d["lane_history"][todo_i + 1 :] if l in ("dev", "review", "done")]
    assert later, "resolution lanes must follow localization"
    assert d["localization"]["targets"]
    assert any("orchestrator" in t for t in d["localization"]["targets"])
    assert d["resolution"]["n_steps"] >= 1
    assert d["signal"] in ("continue", "replan")
    # traces cover both phases
    phases = {t.get("phase") for t in d["traces"]}
    assert sap.PHASE_LOCALIZATION in phases
    assert sap.PHASE_RESOLUTION in phases
    # evidence includes localization targets
    kinds = {e.get("kind") for e in d["evidence"]}
    assert "localization_target" in kinds


def test_build_board_for_issue(tmp_path: Path):
    root = _mini_repo(tmp_path)
    board = sdb.build_board_for_issue(
        "Fix swe_adept_plan localization scoring",
        workdir=root,
        card_id="issue-1",
        max_targets=3,
    )
    assert board.card.id == "issue-1"
    assert board.card.lane in sdb.ALL_LANES
    assert board.status in ("ready", "draft")
    text = sdb.format_board(board)
    assert "SWE delivery board" in text
    assert "localization targets" in text.lower() or "localization" in text.lower()
    lean = sdb.board_payload_for_meta(board)
    assert lean["schema"] == sdb.SCHEMA
    assert lean["n_targets"] >= 1
    assert lean["lane"] == board.card.lane


def test_empty_plan_raises():
    empty = sap.SweAdeptPlan(task="")
    with pytest.raises(sdb.DeliveryBoardError):
        sdb.plan_to_board(empty)


def test_maybe_build_opt_in(tmp_path: Path):
    root = _mini_repo(tmp_path)
    assert sdb.maybe_build_for_task(root, "t", "orchestrator fix", {}) is None
    out = sdb.maybe_build_for_task(
        root,
        "t",
        "Fix localization in orchestrator",
        {"with_swe_plan": True, "swe_max_targets": 3},
    )
    assert out is not None
    assert out["ok"] is True
    assert out["paper"] == sap.PAPER
    assert out["board"]["source_pattern"] == "phodal/routa"
    assert out["n_targets"] >= 1
    assert out["lane"] in sdb.ALL_LANES


def test_maybe_build_reuses_plan_result(tmp_path: Path):
    root = _mini_repo(tmp_path)
    plan = sap.build_swe_adept_plan(
        "orchestrator localization",
        workdir=root,
        max_targets=2,
    )
    plan_result = {
        "ok": True,
        "plan": sap.plan_payload_for_meta(plan),
        "n_targets": len(plan.localization.targets),
    }
    out = sdb.maybe_build_for_task(
        root,
        "reuse",
        "orchestrator localization",
        {"with_swe_plan": True},
        plan_result=plan_result,
    )
    assert out and out["ok"]
    assert out["n_targets"] == len(plan.localization.targets)


def test_module_main_brief(tmp_path: Path, capsys):
    root = _mini_repo(tmp_path)
    rc = sdb.main(
        [
            "orchestrator localization",
            "--path",
            str(root),
            "--brief",
            "--max-targets",
            "2",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "SWE delivery board" in out


def test_module_main_json(tmp_path: Path, capsys):
    root = _mini_repo(tmp_path)
    rc = sdb.main(
        ["orchestrator localization", "--path", str(root), "--json", "--max-targets", "2"]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == sdb.SCHEMA
    assert data["source_pattern"] == "phodal/routa"


def test_orchestrator_attaches_delivery_board(tmp_path: Path, monkeypatch):
    root = _mini_repo(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    out = orch.run_task(
        "Implement localization vs resolution planning in the orchestrator",
        kind="task",
        agent_mode="fake",
        task_id="board-1",
        with_swe_plan=True,
        swe_max_targets=4,
        sync_fake=True,
    )
    assert out.get("swe_adept") is True
    board = out.get("delivery_board") or {}
    assert board.get("schema") == sdb.SCHEMA or board.get("source_pattern") == "phodal/routa"
    summary = out.get("delivery_board_summary") or {}
    assert summary.get("source_pattern") == "phodal/routa"
    assert summary.get("lane") in sdb.ALL_LANES or summary.get("lane") is not None

    env = load_envelope(root, "board-1")
    assert env is not None
    assert env.meta.get("swe_delivery_board") is True
    assert env.meta.get("delivery_board_pattern") == "phodal/routa"
    logs = orch.get_task_status("board-1", action="logs").get("logs") or []
    assert any("delivery_board" in str(line).lower() for line in logs)
    assert any(str(line).startswith("localize:") for line in logs)


def test_action_lane_mapping():
    assert sdb._action_lane("locate.scan", sap.PHASE_LOCALIZATION) == "todo"
    assert sdb._action_lane("resolve.edit", sap.PHASE_RESOLUTION) == "dev"
    assert sdb._action_lane("resolve.verify", sap.PHASE_RESOLUTION) == "review"
    assert sdb._action_lane("resolve.checkpoint", sap.PHASE_RESOLUTION) == "done"


def test_maybe_build_explicit_board_opt_out(tmp_path: Path):
    """with_delivery_board=False must disable board even when SWE plan is on."""
    root = _mini_repo(tmp_path)
    out = sdb.maybe_build_for_task(
        root,
        "opt-out",
        "Fix localization in orchestrator",
        {"with_swe_plan": True, "with_delivery_board": False, "swe_max_targets": 3},
    )
    assert out is None


def test_orchestrator_board_opt_out(tmp_path: Path, monkeypatch):
    root = _mini_repo(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    out = orch.run_task(
        "Implement localization in the orchestrator module",
        kind="task",
        agent_mode="fake",
        task_id="board-off",
        with_swe_plan=True,
        with_delivery_board=False,
        swe_max_targets=3,
        sync_fake=True,
    )
    assert out.get("swe_adept") is True
    assert not out.get("delivery_board")
    env = load_envelope(root, "board-off")
    assert env is not None
    assert env.meta.get("swe_adept") is True
    assert env.meta.get("swe_delivery_board") is not True
    assert env.meta.get("with_delivery_board") is False
    assert env.meta.get("swe_plan_status") == "ok"


def test_orchestrator_require_targets_fail_closed(tmp_path: Path, monkeypatch):
    root = _mini_repo(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    from nexus.orchestrator import OrchError

    with pytest.raises(OrchError) as ei:
        orch.run_task(
            "zzzznonexistenttokenqqq nothing matches",
            kind="task",
            agent_mode="fake",
            task_id="req-fail",
            with_swe_plan=True,
            swe_require_targets=True,
            swe_max_targets=3,
            sync_fake=True,
        )
    assert ei.value.code == "swe_plan_failed"


def test_orchestrator_plan_survives_board_exception(tmp_path: Path, monkeypatch):
    """Board crash must not wipe a successful SWE plan (AG-F2)."""
    root = _mini_repo(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))

    import nexus.swe_delivery_board as sdb_mod

    def _boom(*_a, **_k):
        raise TypeError("synthetic board crash")

    monkeypatch.setattr(sdb_mod, "maybe_build_for_task", _boom)
    orch = Orchestrator(root)
    out = orch.run_task(
        "Implement localization planning in the orchestrator",
        kind="task",
        agent_mode="fake",
        task_id="board-crash",
        with_swe_plan=True,
        swe_max_targets=3,
        sync_fake=True,
    )
    assert out.get("swe_adept") is True
    assert not out.get("delivery_board")
    env = load_envelope(root, "board-crash")
    assert env is not None
    assert env.meta.get("swe_adept_plan")
    assert env.meta.get("swe_plan_status") == "ok"
    assert env.meta.get("delivery_board_error")
    logs = orch.get_task_status("board-crash", action="logs").get("logs") or []
    assert any("board: degraded" in str(line) for line in logs)


def test_walk_no_duplicate_same_lane_traces(tmp_path: Path):
    root = _mini_repo(tmp_path)
    plan = sap.build_swe_adept_plan(
        "Implement localization in orchestrator",
        workdir=root,
        max_targets=2,
    )
    board = sdb.plan_to_board(plan, card_id="trace-1")
    d = board.to_dict()
    # Per resolution step: exactly one step-trace with step_id (no stay-branch dup)
    res_step_traces = [
        t
        for t in d["traces"]
        if t.get("phase") == sap.PHASE_RESOLUTION and t.get("step_id") is not None
    ]
    assert len(res_step_traces) == len(plan.resolution.steps)
    # card.lane must match history tail
    assert d["card"]["lane"] == d["lane_history"][-1]
    lean = sdb.board_payload_for_meta(board)
    assert isinstance(lean["brief"], str)
    assert isinstance(lean["brief_lines"], list)


def test_maybe_build_reuses_plan_without_workdir_tree(tmp_path: Path):
    """Reuse path must not re-localize — empty workdir + plan_result still boards."""
    root = _mini_repo(tmp_path)
    plan = sap.build_swe_adept_plan(
        "orchestrator localization",
        workdir=root,
        max_targets=2,
    )
    plan_result = {
        "ok": True,
        "plan": sap.plan_payload_for_meta(plan),
        "n_targets": len(plan.localization.targets),
    }
    empty = tmp_path / "empty_wd"
    empty.mkdir()
    out = sdb.maybe_build_for_task(
        empty,
        "reuse-empty",
        "orchestrator localization",
        {"with_swe_plan": True},
        plan_result=plan_result,
    )
    assert out and out["ok"]
    assert out["n_targets"] == len(plan.localization.targets)


def test_mcp_run_task_delivery_board_knobs(tmp_path: Path, monkeypatch):
    root = _mini_repo(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    monkeypatch.chdir(root)
    from nexus import mcp_server as mcp

    # Explicit opt-out via args key present
    res = mcp.call_tool(
        "run_task",
        {
            "description": "Implement localization in the orchestrator",
            "agent_mode": "fake",
            "task_id": "mcp-board-off",
            "with_swe_plan": True,
            "with_delivery_board": False,
            "swe_max_targets": 3,
        },
    )
    assert res.get("isError") is not True
    text = res["content"][0]["text"]
    data = json.loads(text)
    assert data.get("swe_adept") is True or data.get("swe_plan_status") == "ok"
    assert not data.get("delivery_board")

    # Default-on when knob omitted
    res2 = mcp.call_tool(
        "run_task",
        {
            "description": "Implement localization in the orchestrator module again",
            "agent_mode": "fake",
            "task_id": "mcp-board-on",
            "with_swe_plan": True,
            "swe_max_targets": 3,
        },
    )
    assert res2.get("isError") is not True
    data2 = json.loads(res2["content"][0]["text"])
    assert data2.get("delivery_board") or data2.get("delivery_board_summary")


def test_mcp_json_bounded_always_valid():
    from nexus.mcp_server import _mcp_json_bounded

    huge = {
        "task_id": "t1",
        "status": "running",
        "swe_adept_plan": {"blob": "x" * 20000},
        "delivery_board": {"blob": "y" * 20000},
        "swe_adept_summary": {"n_targets": 3},
        "delivery_board_summary": {"lane": "todo"},
    }
    text = _mcp_json_bounded(huge, limit=2000)
    data = json.loads(text)  # must parse
    assert data.get("truncated") is True
    assert data.get("task_id") == "t1"


def test_sanitize_rejects_env_secret_paths():
    with pytest.raises(sap.SweAdeptPlanError):
        sap.sanitize_plan_path(".env")
    with pytest.raises(sap.SweAdeptPlanError):
        sap.sanitize_plan_path("src/.env")
    with pytest.raises(sap.SweAdeptPlanError):
        sap.sanitize_plan_path("src/.env.local")
    assert sap.safe_plan_path("src/nexus/orchestrator.py") == "src/nexus/orchestrator.py"
