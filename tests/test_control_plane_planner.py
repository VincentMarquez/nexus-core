"""Tests for control-plane Planner (arXiv 2401.07324 × mission-control)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import control_plane_planner as cpp
from nexus import multi_llm_agent as mla
from nexus import ops_store as ops


# ── catalog ─────────────────────────────────────────────────────────────────


def test_control_plane_as_tools_shape():
    tools = cpp.control_plane_as_tools()
    names = {t["name"] for t in tools}
    assert names == set(cpp.PLANE_TOOL_NAMES)
    assert all(t.get("plane") is True for t in tools)
    assert all(t.get("source") == cpp.SOURCE_PATTERN for t in tools)
    summary = cpp.catalog_summary(tools)
    assert summary["n_tools"] == len(cpp.PLANE_TOOL_NAMES)
    assert summary["by_kind"]["governance"] >= 1
    assert summary["by_kind"]["spend"] >= 1
    assert summary["source_pattern"] == cpp.SOURCE_PATTERN


# ── Planner (no side effects) ───────────────────────────────────────────────


def test_lifecycle_plan_ready_and_ordered():
    plan = cpp.lifecycle_plan(
        "govern task lifecycle and record spend on control plane",
        job_id="job-lc-1",
        include_blocked=True,
        include_report=True,
    )
    assert plan.paper == mla.PAPER
    assert plan.meta.get("schema") == cpp.SCHEMA
    assert plan.meta.get("source_pattern") == cpp.SOURCE_PATTERN
    assert plan.planner == "control-plane-lifecycle"
    assert plan.is_ready()
    tools = [s.tool for s in plan.steps]
    assert tools[0] == cpp.TOOL_UPSERT_JOB
    assert cpp.TOOL_SET_STATUS in tools
    assert cpp.TOOL_RECORD_SPEND in tools
    assert tools[-1] == cpp.TOOL_SPEND_REPORT
    # sticky terminal walk includes completed
    statuses = [
        s.args.get("status")
        for s in plan.steps
        if s.tool == cpp.TOOL_SET_STATUS
    ]
    assert "running" in statuses
    assert "completed" in statuses
    assert all(s.args.get("job_id") == "job-lc-1" for s in plan.steps if "job_id" in s.args)


def test_plan_from_control_plane_no_sqlite_writes(tmp_path: Path, monkeypatch):
    """Planner role must never open/write the ops plane."""
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("must not open OpsStore during plan")

    monkeypatch.setattr(ops.OpsStore, "open", boom)
    plan = cpp.plan_from_control_plane(
        "govern job spend and complete on mission control board",
        job_id="pure-1",
    )
    assert plan.is_ready()
    assert plan.steps
    assert called["n"] == 0
    assert plan.meta.get("handoff") == "control_plane_planner"


def test_plan_from_injected_llm_text():
    text = json.dumps(
        {
            "task": "list control plane jobs",
            "status": "ready",
            "steps": [
                {
                    "id": 1,
                    "tool": cpp.TOOL_LIST_JOBS,
                    "args": {"kind": "task", "limit": 10},
                    "rationale": "operator board list",
                }
            ],
        }
    )
    plan = cpp.plan_from_control_plane(
        "list control plane jobs",
        plan_text=text,
    )
    assert plan.is_ready()
    assert plan.steps[0].tool == cpp.TOOL_LIST_JOBS
    assert plan.planner == "control-plane-injected"


def test_heuristic_plan_without_lifecycle():
    plan = cpp.plan_from_control_plane(
        "list jobs on the operator board",
        use_lifecycle=False,
        prefer_lifecycle=False,
        max_steps=3,
    )
    assert plan.steps
    assert plan.planner.startswith("control-plane")
    tools = {s.tool for s in plan.steps}
    # list-oriented task should prefer list_jobs
    assert cpp.TOOL_LIST_JOBS in tools or any("list" in t for t in tools)


def test_plan_payload_stamps_schema():
    plan = cpp.lifecycle_plan("spend report for governed task", job_id="p1")
    payload = cpp.plan_payload(plan)
    assert payload["control_plane_schema"] == cpp.SCHEMA
    assert payload["source_pattern"] == cpp.SOURCE_PATTERN
    assert payload["meta"]["paper"] == cpp.PAPER


# ── govern (Planner → OpsStore) ─────────────────────────────────────────────


def test_plan_and_govern_writes_job_and_spend(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    report = cpp.plan_and_govern(
        "govern task lifecycle, record spend, complete job on control plane",
        workdir=tmp_path,
        job_id="gov-1",
        use_lifecycle=True,
    )
    assert report["ok"] is True
    assert report["phase"] == "govern"
    assert report["schema"] == cpp.SCHEMA
    assert report["source_pattern"] == cpp.SOURCE_PATTERN
    assert report["job_id"] == "gov-1"
    job = report["job"]
    assert job is not None
    assert job["status"] == "completed"
    assert int(job["tokens"]) >= 1
    spend = report.get("spend") or {}
    assert int(spend.get("total_tokens") or 0) >= 1
    assert int(spend.get("request_count") or 0) >= 1

    # Sticky terminal: re-open store and try late non-force running write
    with ops.OpsStore.open(tmp_path) as store:
        late = store.set_status("gov-1", "running")
        assert late["status"] == "completed"


def test_empty_injected_plan_fail_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    text = json.dumps({"task": "x", "status": "draft", "steps": []})
    # auto_ready requires steps → PlanError
    with pytest.raises(mla.PlanError):
        cpp.plan_from_control_plane("x", plan_text=text, auto_ready=True)

    plan = cpp.plan_from_control_plane("x", plan_text=text, auto_ready=False)
    assert not plan.is_ready()
    assert plan.steps == []

    # Caller refuses non-ready plan
    with ops.OpsStore.open(tmp_path) as store:
        reg = cpp.make_ops_registry(store)
        caller = mla.Caller(registry=reg)
        with pytest.raises(mla.CallGateError):
            caller.set_plan(plan, require_ready=True)


def test_make_ops_registry_execute_all(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    plan = cpp.lifecycle_plan(
        "full governance walk",
        job_id="reg-1",
        spend_tokens=7,
        include_blocked=False,
        include_report=True,
    )
    with ops.OpsStore.open(tmp_path) as store:
        reg = cpp.make_ops_registry(store, default_job_id="reg-1")
        caller = mla.Caller(registry=reg)
        caller.set_plan(plan, require_ready=True)
        results = caller.execute_all()
    assert all(r.ok for r in results)
    assert plan.status == mla.STATUS_DONE
    with ops.OpsStore.open(tmp_path) as store:
        job = store.get("reg-1")
        assert job is not None
        assert job["status"] == "completed"
        assert job["tokens"] == 7


# ── handoff (Planner → govern → Orchestrator) ───────────────────────────────


def test_plan_and_handoff_fake_orch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    report = cpp.plan_and_handoff(
        "govern control plane job then hand off to orchestrator",
        workdir=tmp_path,
        task_id="ho-1",
        agent_mode="fake",
        govern=True,
        use_lifecycle=True,
        sync_fake=True,
    )
    assert report["schema"] == cpp.SCHEMA
    assert report["ok"] is True
    assert report["phase"] == "orchestrator"
    gov = report.get("govern") or {}
    assert gov.get("ok") is True
    job = gov.get("job") or {}
    assert job.get("status") == "completed"
    orch = report.get("orchestrator") or {}
    assert orch.get("pre_planned") in (True, 1, "true") or orch.get("status") not in (
        None,
        "failed",
    )
    assert orch.get("task_id") in ("ho-1", report.get("job_id"))


def test_plan_and_handoff_without_govern(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    report = cpp.plan_and_handoff(
        "plan only then orchestrator",
        workdir=tmp_path,
        task_id="ho-2",
        agent_mode="fake",
        govern=False,
        use_lifecycle=True,
        sync_fake=True,
    )
    assert report["ok"] is True
    assert report.get("govern") is None
    orch = report.get("orchestrator") or {}
    assert orch.get("status") not in (None, "failed")
    # Orchestrator may still stamp an ops job; govern path was skipped.
    assert report.get("phase") == "orchestrator"


# ── format + CLI ────────────────────────────────────────────────────────────


def test_format_plane_plan_and_report():
    plan = cpp.lifecycle_plan("format me", job_id="f1")
    text = cpp.format_plane_plan(plan)
    assert cpp.SCHEMA in text
    assert "plane.upsert_job" in text
    report = {
        "ok": True,
        "phase": "govern",
        "paper": cpp.PAPER,
        "source_pattern": cpp.SOURCE_PATTERN,
        "schema": cpp.SCHEMA,
        "job_id": "f1",
        "plan": plan.to_dict(),
        "job": {"status": "completed", "tokens": 3, "cost": 0.0},
        "spend": {"total_tokens": 3, "request_count": 1},
    }
    rtext = cpp.format_report(report)
    assert "ok:       True" in rtext
    assert "f1" in rtext


def test_cli_catalog_and_plan(tmp_path: Path, capsys):
    rc = cpp.main(["catalog"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "plane.upsert_job" in out

    rc = cpp.main(
        [
            "plan",
            "govern lifecycle and spend on control plane",
            "--job-id",
            "cli-1",
            "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "ready"
    assert data["steps"]


def test_cli_govern(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    rc = cpp.main(
        [
            "govern",
            "govern task spend complete on control plane",
            "--workdir",
            str(tmp_path),
            "--job-id",
            "cli-gov",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["job"]["status"] == "completed"
