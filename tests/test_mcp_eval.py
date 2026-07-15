"""P2.3 domain MCP eval smoke — AssetOpsBench-shaped scenarios + scorers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import mcp_eval as me
from nexus import mcp_server
from nexus.cli import main as cli_main


# ---------------------------------------------------------------------------
# Scorers (unit)
# ---------------------------------------------------------------------------


def _traj(
    answer: str = "",
    *,
    is_error: bool = False,
    scenario_id: str = "s1",
) -> me.Trajectory:
    return me.Trajectory(
        run_id="r1",
        scenario_id=scenario_id,
        tool="t",
        arguments={},
        is_error=is_error,
        answer=answer,
        ms=1.0,
    )


def test_scorers_tool_ok_contains_json():
    sc = me.Scenario(
        id="a",
        domain="x",
        text="t",
        tool="t",
        scoring_method="tool_ok",
    )
    assert me.score_tool_ok(sc, _traj("hi")).ok
    assert not me.score_tool_ok(sc, _traj("hi", is_error=True)).ok

    sc2 = me.Scenario(
        id="b",
        domain="x",
        text="t",
        tool="t",
        scoring_method="contains",
        expected="PASS",
    )
    assert me.score_contains(sc2, _traj("xx PASS yy")).ok
    assert not me.score_contains(sc2, _traj("fail")).ok

    sc3 = me.Scenario(
        id="c",
        domain="x",
        text="t",
        tool="t",
        scoring_method="json_keys",
        expected=["ok", "count"],
    )
    assert me.score_json_keys(sc3, _traj('{"ok": true, "count": 3}')).ok
    assert not me.score_json_keys(sc3, _traj('{"ok": true}')).ok

    sc4 = me.Scenario(
        id="d",
        domain="x",
        text="t",
        tool="t",
        scoring_method="json_path_eq",
        expected={"ok": True},
    )
    assert me.score_json_path_eq(sc4, _traj('{"ok": true, "n": 1}')).ok
    assert not me.score_json_path_eq(sc4, _traj('{"ok": false}')).ok

    sc5 = me.Scenario(
        id="e",
        domain="x",
        text="t",
        tool="t",
        scoring_method="is_error",
        expected=True,
    )
    assert me.score_is_error(sc5, _traj("denied", is_error=True)).ok
    assert not me.score_is_error(sc5, _traj("ok", is_error=False)).ok


def test_no_secret_leak_scorer():
    sc = me.Scenario(
        id="v",
        domain="vault",
        text="t",
        tool="vault_status",
        scoring_method="no_secret_leak",
    )
    assert me.score_no_secret_leak(sc, _traj('{"present": true}')).ok
    bad = me.score_no_secret_leak(
        sc, _traj('api_key: "sk-abcdefghijklmnopqrstuvwxyz12"')
    )
    assert not bad.ok


def test_filter_scenarios_domain_and_privilege():
    suite = me.builtin_scenarios()
    ws = me.filter_scenarios(suite, domains=["workspace"])
    assert ws and all(s.domain == "workspace" for s in ws)
    reads = me.filter_scenarios(suite, max_privilege="read")
    assert all(s.privilege == "read" for s in reads)
    assert not any(s.id == "ws.write_probe" for s in reads)


# ---------------------------------------------------------------------------
# Live MCP smoke (tmp project root)
# ---------------------------------------------------------------------------


def test_builtin_suite_passes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    # minimal files some tools look for
    (tmp_path / "README.md").write_text("# tmp\n", encoding="utf-8")
    (tmp_path / "skillpacks").mkdir()
    (tmp_path / ".nexus_state" / "repo_mine").mkdir(parents=True)
    (tmp_path / ".nexus_state" / "repo_mine" / "IMPROVE_OURS.md").write_text(
        "# Improve *our* project\n\n"
        "## owner/demo (score 12.0)\n"
        "- idea=6.0 skill=6.0\n"
        "- local clone: /tmp/x\n",
        encoding="utf-8",
    )

    report = me.evaluate()
    assert report["schema"] == me.SCHEMA_VERSION
    assert report["total"] >= 10
    if not report["ok"]:
        # helpful failure detail
        pytest.fail(
            "mcp_eval failures:\n"
            + json.dumps(report.get("failures"), indent=2)
        )
    assert report["pass_rate"] == 1.0


def test_export_report(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    report = me.run_and_export(
        tmp_path,
        domains=["status", "catalog"],
        max_privilege="read",
        export=True,
    )
    assert report["ok"]
    exp = report["export"]
    assert Path(exp["report"]).is_file()
    assert Path(exp["summary"]).is_file()
    assert Path(exp["trajectories"]).is_file()
    data = json.loads(Path(exp["report"]).read_text(encoding="utf-8"))
    assert data["schema"] == me.SCHEMA_VERSION
    assert "trajectories" not in data  # slim export


def test_path_jail_scenario(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    sc = next(s for s in me.builtin_scenarios() if s.id == "ws.path_jail")
    _traj_out, res = me.run_scenario(sc)
    assert res.ok
    assert res.method == "is_error"


def test_catalog_validate_scenario(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    sc = next(s for s in me.builtin_scenarios() if s.id == "catalog.validate")
    _t, res = me.run_scenario(sc)
    assert res.ok, res.reason


# ---------------------------------------------------------------------------
# CLI + MCP surface
# ---------------------------------------------------------------------------


def test_cli_eval_list_and_smoke(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")

    rc = cli_main(["eval", "list", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["count"] >= 10
    assert data["schema"] == me.SCHEMA_VERSION

    rc = cli_main(
        [
            "eval",
            "smoke",
            "--path",
            str(tmp_path),
            "--domain",
            "status,catalog",
            "--max-privilege",
            "read",
            "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    rep = json.loads(out)
    assert rep["ok"]
    assert rep["failed"] == 0


def test_mcp_tool_mcp_eval(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")

    listed = mcp_server.call_tool("mcp_eval", {"action": "list"})
    assert listed["isError"] is False
    body = json.loads(listed["content"][0]["text"])
    assert body["count"] >= 10

    ran = mcp_server.call_tool(
        "mcp_eval",
        {
            "action": "smoke",
            "domain": "catalog",
            "max_privilege": "read",
            "export": True,
        },
    )
    assert ran["isError"] is False
    rep = json.loads(ran["content"][0]["text"])
    assert rep["ok"]
    assert rep["schema"] == me.SCHEMA_VERSION
    assert "mcp_eval" in [t["name"] for t in mcp_server.TOOLS]


def test_tool_catalog_includes_mcp_eval():
    from nexus import tool_catalog as tc

    entries = {e.name: e for e in tc.build_entries()}
    assert "mcp_eval" in entries
    assert entries["mcp_eval"].privilege == "read"
    rep = tc.validate_tools()
    assert rep.ok, [f.message for f in rep.findings if f.severity == "error"]


# ---------------------------------------------------------------------------
# P2.4 JSON scenario packs + optional llm_judge
# ---------------------------------------------------------------------------


def test_load_scenario_pack_object_and_array(tmp_path: Path):
    pack = {
        "schema": me.SCENARIO_PACK_SCHEMA,
        "name": "mini",
        "scenarios": [
            {
                "id": "custom.status",
                "domain": "status",
                "text": "status smoke from pack",
                "tool": "nexus_status",
                "arguments": {},
                "scoring_method": "contains_all",
                "expected": ["project_root=", "server=nexus-workspace"],
                "tags": ["pack", "status"],
            }
        ],
    }
    path = tmp_path / "mini_pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    rows = me.load_scenario_pack(path)
    assert len(rows) == 1
    assert rows[0].id == "custom.status"
    assert rows[0].tool == "nexus_status"

    # bare array
    arr_path = tmp_path / "arr.json"
    arr_path.write_text(
        json.dumps(
            [
                {
                    "id": "a1",
                    "type": "workspace",
                    "text": "list root",
                    "tool": "list_project_files",
                    "args": {"path": ".", "max_entries": 5},
                    "scorer": "tool_ok",
                }
            ]
        ),
        encoding="utf-8",
    )
    rows2 = me.load_scenario_pack(arr_path)
    assert rows2[0].domain == "workspace"
    assert rows2[0].arguments["max_entries"] == 5


def test_merge_and_resolve_packs_override_builtin(tmp_path: Path):
    # override status.nexus id with a pack entry
    pack_path = tmp_path / "override.json"
    me.write_scenario_pack(
        pack_path,
        [
            me.Scenario(
                id="status.nexus",
                domain="status",
                text="overridden",
                tool="nexus_status",
                scoring_method="tool_ok",
                tags=["override"],
            )
        ],
        name="override",
    )
    suite = me.resolve_scenarios(
        workdir=tmp_path,
        packs=[pack_path],
        include_builtin=True,
    )
    by_id = {s.id: s for s in suite}
    assert by_id["status.nexus"].text == "overridden"
    assert "override" in by_id["status.nexus"].tags
    # builtin still present for other ids
    assert "catalog.list" in by_id


def test_evaluate_with_pack_only(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")
    pack_path = tmp_path / "pack.json"
    pack_path.write_text(
        json.dumps(
            {
                "schema": me.SCENARIO_PACK_SCHEMA,
                "scenarios": [
                    {
                        "id": "p.status",
                        "domain": "status",
                        "text": "status",
                        "tool": "nexus_status",
                        "scoring_method": "tool_ok",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rep = me.evaluate(
        workdir=tmp_path,
        packs=[pack_path],
        include_builtin=False,
    )
    assert rep["ok"]
    assert rep["total"] == 1
    assert rep["packs"]
    assert rep["results"][0]["scenario_id"] == "p.status"


def test_discover_packs_and_cli(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    pack_dir = tmp_path / ".nexus_state" / "mcp_eval" / "packs"
    pack_dir.mkdir(parents=True)
    me.write_scenario_pack(
        pack_dir / "extra.json",
        [
            me.Scenario(
                id="disc.1",
                domain="status",
                text="d",
                tool="nexus_status",
                scoring_method="tool_ok",
            )
        ],
        name="extra",
    )
    found = me.discover_packs(tmp_path)
    assert len(found) == 1

    monkeypatch.chdir(tmp_path)
    rc = cli_main(["eval", "packs", "--path", str(tmp_path), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["count"] == 1


def test_heuristic_and_llm_judge_scorers():
    sc = me.Scenario(
        id="j1",
        domain="x",
        text="t",
        tool="t",
        scoring_method="heuristic_judge",
        expected="FFT spectrum analysis, envelope analysis, ISO 10816 severity",
    )
    good = _traj("FFT spectrum and envelope analysis with ISO 10816 severity zones")
    bad = _traj("hello world")
    assert me.score_heuristic_judge(sc, good).ok
    assert not me.score_heuristic_judge(sc, bad).ok

    # llm_judge falls back to heuristic when no callable registered
    me.set_llm_judge(None)
    sc2 = me.Scenario(
        id="j2",
        domain="x",
        text="t",
        tool="t",
        scoring_method="llm_judge",
        expected="project_root server nexus",
    )
    r = me.score_llm_judge(
        sc2, _traj("project_root=/tmp server=nexus-workspace")
    )
    assert r.ok
    assert r.method == "llm_judge"
    assert "fallback" in r.reason

    # injected judge wins
    def _fake_judge(scenario, traj):
        return me.ScorerResult(
            ok=True, score=0.99, reason="fake", method="llm_judge"
        )

    me.set_llm_judge(_fake_judge)
    try:
        r2 = me.score_llm_judge(sc2, _traj("whatever"))
        assert r2.ok and r2.reason == "fake"
    finally:
        me.set_llm_judge(None)

    # require_llm fail-closed without registration
    sc3 = me.Scenario(
        id="j3",
        domain="x",
        text="t",
        tool="t",
        scoring_method="llm_judge",
        expected={"require_llm": True, "criteria": ["x"]},
    )
    r3 = me.score_llm_judge(sc3, _traj("x"))
    assert not r3.ok
    assert r3.reason == "llm_judge_not_configured"


def test_cli_eval_pack_flag(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    pack = tmp_path / "one.json"
    pack.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "cli.pack",
                        "domain": "status",
                        "text": "s",
                        "tool": "nexus_status",
                        "scoring_method": "tool_ok",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rc = cli_main(
        [
            "eval",
            "smoke",
            "--path",
            str(tmp_path),
            "--pack",
            str(pack),
            "--no-builtin",
            "--no-export",
            "--json",
        ]
    )
    assert rc == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["ok"]
    assert rep["total"] == 1


# ---------------------------------------------------------------------------
# P2.6 sample packs + P2.5 ollama judge adapter
# ---------------------------------------------------------------------------


def test_ensure_sample_packs_from_bundled(tmp_path: Path):
    """Copy fixtures/mcp_eval/packs → .nexus_state/mcp_eval/packs (idempotent)."""
    # Build a local bundled source that mirrors repo fixtures layout
    src = tmp_path / "fixtures" / "mcp_eval" / "packs"
    src.mkdir(parents=True)
    me.write_scenario_pack(
        src / "operator_smoke.json",
        [
            me.Scenario(
                id="sample.operator.status",
                domain="status",
                text="status",
                tool="nexus_status",
                scoring_method="tool_ok",
                tags=["sample"],
            )
        ],
        name="operator_smoke",
        description="fixture sample",
    )
    (src / "readme_only.txt").write_text("ignore\n", encoding="utf-8")

    res = me.ensure_sample_packs(tmp_path, source=src)
    assert res["ok"] is True
    assert "operator_smoke.json" in res["installed"]
    dest = tmp_path / ".nexus_state" / "mcp_eval" / "packs" / "operator_smoke.json"
    assert dest.is_file()

    # second call skips existing
    res2 = me.ensure_sample_packs(tmp_path, source=src)
    assert res2["ok"]
    assert res2["installed"] == []
    assert "operator_smoke.json" in res2["skipped"]

    found = me.discover_packs(tmp_path)
    assert any(p.name == "operator_smoke.json" for p in found)

    suite = me.resolve_scenarios(
        workdir=tmp_path, include_builtin=False, discover=True
    )
    assert any(s.id == "sample.operator.status" for s in suite)


def test_list_bundled_packs_repo_fixtures():
    """Repo-shipped fixtures are discoverable when present."""
    # Prefer real repo fixtures when tests run from checkout
    repo = Path(__file__).resolve().parents[1]
    d = me.bundled_packs_dir(repo)
    if d is None:
        pytest.skip("fixtures/mcp_eval/packs not present")
    packs = me.list_bundled_packs(repo)
    names = {p.name for p in packs}
    assert "operator_smoke.json" in names
    assert "privilege_safety.json" in names
    # load without network
    rows = me.load_scenario_pack(d / "operator_smoke.json")
    assert len(rows) >= 1
    assert all(r.tool for r in rows)


def test_make_ollama_judge_falls_back_offline():
    """Ollama adapter falls back to heuristic when host is unreachable."""
    judge = me.make_ollama_judge(
        host="http://127.0.0.1:1",  # closed port
        model="gemma2",
        timeout=0.2,
        fallback_heuristic=True,
    )
    sc = me.Scenario(
        id="j",
        domain="x",
        text="t",
        tool="t",
        scoring_method="llm_judge",
        expected="project_root server nexus",
    )
    r = judge(sc, _traj("project_root=/tmp server=nexus-workspace ok"))
    assert r.method == "llm_judge"
    assert "fallback" in r.reason or r.ok
    assert r.ok  # heuristic should hit tokens

    judge_strict = me.make_ollama_judge(
        host="http://127.0.0.1:1",
        timeout=0.2,
        fallback_heuristic=False,
    )
    r2 = judge_strict(sc, _traj("project_root=/tmp"))
    assert not r2.ok
    assert "ollama_unavailable" in r2.reason


def test_configure_llm_judge_from_env(monkeypatch):
    me.set_llm_judge(None)
    monkeypatch.delenv("NEXUS_MCP_EVAL_LLM_JUDGE", raising=False)
    assert me.configure_llm_judge_from_env() is None

    monkeypatch.setenv("NEXUS_MCP_EVAL_LLM_JUDGE", "1")
    monkeypatch.setenv("NEXUS_OLLAMA_MODEL", "test-model")
    label = me.configure_llm_judge_from_env()
    assert label == "ollama:test-model"
    try:
        # registered callable should be invokable (offline fallback)
        sc = me.Scenario(
            id="e",
            domain="x",
            text="t",
            tool="t",
            scoring_method="llm_judge",
            expected="hello world",
        )
        r = me.score_llm_judge(sc, _traj("hello world from tool"))
        assert r.method == "llm_judge"
    finally:
        me.set_llm_judge(None)


def test_make_grok_judge_falls_back_offline(monkeypatch):
    """Grok adapter falls back to heuristic when CLI missing / call fails."""
    # Force "not available" path without needing the real CLI
    monkeypatch.setattr(
        "nexus.grok_worker.grok_available", lambda: False, raising=False
    )
    # Import path used inside make_grok_judge
    import nexus.grok_worker as gw

    monkeypatch.setattr(gw, "grok_available", lambda: False)

    judge = me.make_grok_judge(fallback_heuristic=True, timeout=0.1)
    sc = me.Scenario(
        id="gj",
        domain="x",
        text="t",
        tool="t",
        scoring_method="llm_judge",
        expected="project_root server nexus",
    )
    r = judge(sc, _traj("project_root=/tmp server=nexus-workspace ok"))
    assert r.method == "llm_judge"
    assert "fallback" in r.reason or r.ok
    assert r.ok

    judge_strict = me.make_grok_judge(fallback_heuristic=False, timeout=0.1)
    r2 = judge_strict(sc, _traj("project_root=/tmp"))
    assert not r2.ok
    assert "grok_unavailable" in r2.reason


def test_make_grok_judge_parses_json_response(monkeypatch):
    """Grok adapter maps structured ok/score/reason into ScorerResult."""
    import nexus.grok_worker as gw

    monkeypatch.setattr(gw, "grok_available", lambda: True)

    def _fake_prompt(prompt, **kwargs):
        return {
            "ok": True,
            "text": '{"ok": true, "score": 0.87, "reason": "criteria covered"}',
        }

    monkeypatch.setattr(gw, "grok_prompt", _fake_prompt)
    judge = me.make_grok_judge(fallback_heuristic=False)
    sc = me.Scenario(
        id="gj2",
        domain="x",
        text="t",
        tool="t",
        scoring_method="llm_judge",
        expected="ok",
    )
    r = judge(sc, _traj("all good"))
    assert r.ok is True
    assert r.score == 0.87
    assert "criteria" in r.reason


def test_configure_llm_judge_grok_and_auto(monkeypatch):
    me.set_llm_judge(None)
    import nexus.grok_worker as gw

    monkeypatch.setattr(gw, "grok_available", lambda: False)
    monkeypatch.setenv("NEXUS_MCP_EVAL_LLM_JUDGE", "grok")
    monkeypatch.setenv("NEXUS_GROK_MODEL", "grok-test")
    label = me.configure_llm_judge_from_env()
    assert label == "grok:grok-test"
    me.set_llm_judge(None)

    # auto with no grok → ollama
    monkeypatch.setenv("NEXUS_MCP_EVAL_LLM_JUDGE", "auto")
    monkeypatch.setenv("NEXUS_OLLAMA_MODEL", "auto-model")
    label2 = me.configure_llm_judge_from_env()
    assert label2 == "ollama:auto-model"
    me.set_llm_judge(None)

    # auto with grok available → grok
    monkeypatch.setattr(gw, "grok_available", lambda: True)
    monkeypatch.setattr(gw, "default_model", lambda: "grok-4.5")
    label3 = me.configure_llm_judge_from_env()
    assert label3.startswith("grok:")
    me.set_llm_judge(None)


def test_cli_install_samples(tmp_path: Path, monkeypatch, capsys):
    # local fixtures under tmp project
    src = tmp_path / "fixtures" / "mcp_eval" / "packs"
    src.mkdir(parents=True)
    me.write_scenario_pack(
        src / "operator_smoke.json",
        [
            me.Scenario(
                id="cli.sample",
                domain="status",
                text="s",
                tool="nexus_status",
                scoring_method="tool_ok",
            )
        ],
        name="operator_smoke",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    rc = cli_main(
        ["eval", "packs", "--path", str(tmp_path), "--install-samples", "--json"]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["install"]["ok"] is True
    assert out["count"] >= 1
