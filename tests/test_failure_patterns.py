"""Tests for Socratic-SWE-shaped failure pattern mining (arxiv:2606.07412v1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import failure_patterns as fp
from nexus.decision_ledger import DecisionLedger
from nexus.ops_store import OpsStore


# ---------------------------------------------------------------------------
# classify_text
# ---------------------------------------------------------------------------


def test_classify_missing_dependency():
    pids = fp.classify_text("ModuleNotFoundError: No module named 'foo_bar'")
    assert "missing_dependency_check" in pids
    assert "generic_runtime_error" not in pids


def test_classify_incorrect_api_usage():
    pids = fp.classify_text(
        "TypeError: open() got an unexpected keyword argument 'encodingg'"
    )
    assert "incorrect_api_usage" in pids


def test_classify_test_assertion():
    pids = fp.classify_text("FAILED tests/test_x.py::test_y - AssertionError: 1 == 2")
    assert "test_assertion_failure" in pids


def test_classify_empty_and_benign():
    assert fp.classify_text("") == []
    assert fp.classify_text("all good, 12 passed") == []


def test_catalog_ids_unique():
    ids = fp.list_pattern_ids()
    assert len(ids) == len(set(ids))
    assert "missing_dependency_check" in ids
    assert "incorrect_api_usage" in ids
    assert fp.pattern_rule("missing_dependency_check") is not None
    assert fp.pattern_rule("nope") is None


# ---------------------------------------------------------------------------
# decision_ledger + ops_store integration
# ---------------------------------------------------------------------------


def test_collect_decision_failures(tmp_path: Path):
    with DecisionLedger.open(tmp_path) as led:
        led.append(
            run_id="r1",
            agent="caller",
            claim="ModuleNotFoundError: No module named 'requests'",
            grade={"ok": False, "error": "ModuleNotFoundError: No module named 'requests'"},
            action="tool_fail",
        )
        led.append(
            run_id="r1",
            agent="caller",
            claim="happy path",
            grade={"ok": True, "score": 16.0},
            action="tool_ok",
        )
        led.append(
            run_id="r1",
            agent="planner",
            claim="TypeError: unexpected keyword argument 'foo'",
            grade={"ok": False},
            action="replan_fail",
        )
        traces = fp.collect_decision_traces(tmp_path, ledger=led, limit=50)

    assert len(traces) == 2
    sources = {t.source for t in traces}
    assert sources == {"decision_ledger"}
    all_pids = {p for t in traces for p in t.pattern_ids}
    assert "missing_dependency_check" in all_pids
    assert "incorrect_api_usage" in all_pids


def test_collect_ops_failures(tmp_path: Path):
    with OpsStore.open(tmp_path) as store:
        store.upsert_job(
            "job-dep-1",
            kind="task",
            title="install deps",
            status="failed",
            goal="run improve",
            meta={"error": "ModuleNotFoundError: No module named 'xyz'"},
        )
        store.upsert_job(
            "job-ok",
            kind="task",
            title="ok job",
            status="completed",
            meta={},
        )
        store.upsert_job(
            "job-dep-2",
            kind="improve",
            title="retry",
            status="failed",
            meta={"error": "ImportError: cannot import name 'Foo'"},
        )
        traces = fp.collect_ops_traces(tmp_path, store=store)

    assert len(traces) == 2
    assert all(t.source == "ops_store" for t in traces)
    assert all("missing_dependency_check" in t.pattern_ids for t in traces)


def test_analyze_recurring_min_count(tmp_path: Path):
    with DecisionLedger.open(tmp_path) as led, OpsStore.open(tmp_path) as store:
        # two missing-dep failures (ledger + ops) → recurring at min_count=2
        led.append(
            run_id="run-a",
            agent="caller",
            claim="ModuleNotFoundError: No module named 'dep_a'",
            grade={"ok": False, "error": "ModuleNotFoundError: No module named 'dep_a'"},
            action="exec_fail",
        )
        store.upsert_job(
            "j1",
            kind="task",
            status="failed",
            meta={"error": "No module named 'dep_b'"},
        )
        # single API failure → singleton at min_count=2
        led.append(
            run_id="run-a",
            agent="caller",
            claim="unexpected keyword argument 'bar'",
            grade={"ok": False},
            action="api_fail",
        )

        report = fp.analyze_failure_patterns(
            tmp_path,
            min_count=2,
            ledger=led,
            store=store,
        )

    assert report["schema"] == fp.SCHEMA
    assert report["ok"] is True
    assert report["arxiv_id"] == "2606.07412v1"
    assert report["n_traces"] == 3
    ids = [p["id"] for p in report["patterns"]]
    assert "missing_dependency_check" in ids
    assert "incorrect_api_usage" not in ids  # singleton
    assert report["singleton_count"] >= 1

    dep = next(p for p in report["patterns"] if p["id"] == "missing_dependency_check")
    assert dep["count"] >= 2
    assert dep["skill_hint"]
    assert "decision_ledger" in dep["sources"] or "ops_store" in dep["sources"]

    skills = report["skills"]
    assert skills
    assert skills[0]["skill_id"].startswith("trace-skill:")
    assert "missing_dependency_check" in skills[0]["pattern_id"]

    text = fp.format_report(report)
    assert "missing_dependency_check" in text
    brief = fp.skill_brief(report)
    assert "Trace-derived agent skills" in brief
    assert "missing_dependency_check" in brief


def test_analyze_empty_workdir(tmp_path: Path):
    report = fp.analyze_failure_patterns(tmp_path, min_count=2)
    assert report["ok"] is True
    assert report["n_traces"] == 0
    assert report["patterns"] == []
    assert report["skills"] == []
    assert "no recurring" in fp.format_report(report).lower() or "traces=0" in fp.format_report(report)


def test_classify_log_lines_multi():
    lines = [
        "ModuleNotFoundError: No module named 'a'",
        "ImportError: No module named 'b'",
        "PermissionError: Permission denied: '/etc/shadow'",
        "benign info line",
    ]
    report = fp.classify_log_lines(lines, min_count=2)
    ids = [p["id"] for p in report["patterns"]]
    assert "missing_dependency_check" in ids
    assert "permission_or_auth" not in ids  # only one


def test_action_needles_mark_failure_without_rich_text(tmp_path: Path):
    with DecisionLedger.open(tmp_path) as led:
        led.append(
            run_id="r",
            agent="gate",
            claim="promote blocked by quality gate",
            grade={},
            action="promote_denied",
        )
        traces = fp.collect_decision_traces(tmp_path, ledger=led)
    assert len(traces) == 1
    # claim has "gate" language → policy_or_gate_denied preferred over generic
    assert traces[0].pattern_ids
    assert "generic_runtime_error" not in traces[0].pattern_ids or any(
        p != "generic_runtime_error" for p in traces[0].pattern_ids
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_module_cli_catalog(capsys):
    rc = fp.main(["--catalog"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "missing_dependency_check" in out
    assert "incorrect_api_usage" in out


def test_module_cli_classify(capsys):
    rc = fp.main(
        ["--classify", "ModuleNotFoundError: No module named 'x'", "--json"]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "missing_dependency_check" in data["pattern_ids"]


def test_module_cli_analyze(tmp_path: Path, capsys):
    with DecisionLedger.open(tmp_path) as led:
        for i in range(2):
            led.append(
                run_id="cli-run",
                agent="a",
                claim=f"ModuleNotFoundError: No module named 'pkg{i}'",
                grade={"ok": False, "error": f"No module named 'pkg{i}'"},
                action="tool_fail",
            )
    rc = fp.main(["--path", str(tmp_path), "--min-count", "2", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["n_traces"] >= 2
    assert any(p["id"] == "missing_dependency_check" for p in data["patterns"])


def test_module_cli_skills_only(tmp_path: Path, capsys):
    with OpsStore.open(tmp_path) as store:
        for i in range(2):
            store.upsert_job(
                f"s{i}",
                kind="task",
                status="failed",
                meta={"error": "FileNotFoundError: No such file or directory: 'x'"},
            )
    rc = fp.main(["--path", str(tmp_path), "--min-count", "2", "--skills-only"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "file_or_path_missing" in out or "Trace-derived" in out
