"""MAFBench proxy — framework overhead bench (arXiv:2602.03128).

Also covers AssetOpsBench-shaped scenario packs, wshobson marketplace,
mission-control control plane, and routa delivery board smoke
(cross-pattern hybrids).
"""

from __future__ import annotations

import json
from pathlib import Path

from nexus import maf_bench as mb


def test_list_mechanisms_catalog():
    rows = mb.list_mechanisms()
    ids = {r["id"] for r in rows}
    assert ids == set(mb.MECHANISMS)
    assert "domain_mcp" in ids
    assert "marketplace" in ids
    assert "market_plan" in ids
    assert "control_plane" in ids
    assert "delivery_board" in ids
    assert all("family" in r and "description" in r for r in rows)
    families = {r["family"] for r in rows}
    assert "baseline" in families
    assert "consensus" in families
    assert "orchestration" in families
    assert "domain_mcp" in families
    assert "marketplace" in families
    assert "market_plan" in families
    assert "control_plane" in families
    assert "delivery_board" in families


def test_bench_calls_metrics_and_errors():
    calls = [
        lambda: {"ok": True, "score": 0.9},
        lambda: {"ok": True, "score": 0.5},
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    ]
    row = mb.bench_calls("demo", "baseline", calls)
    assert row["mechanism"] == "demo"
    assert row["family"] == "baseline"
    assert row["iters"] == 3
    assert row["ok_rate"] == round(2 / 3, 4)
    assert row["score"] == 0.7  # mean of 0.9, 0.5
    assert row["p50_ms"] >= 0.0
    assert row["p95_ms"] >= row["p50_ms"]
    assert row["ops_per_s"] >= 0.0


def test_run_maf_bench_offline_full(tmp_path: Path):
    report = mb.run_maf_bench(tmp_path, iters=8, export=True)
    assert report["ok"] is True
    assert report["schema"] == mb.SCHEMA
    assert report["paper"] == "2602.03128v1"
    assert report["strict_ok"] is True
    mechs = [r["mechanism"] for r in report["rows"]]
    assert mechs == list(mb.MECHANISMS)
    for r in report["rows"]:
        assert r["ok_rate"] == 1.0
        assert r["mean_ms"] >= 0.0
        assert "overhead_x" in r
    # baseline relative overhead is 1.0
    base = next(r for r in report["rows"] if r["mechanism"] == "single_judge")
    assert base["overhead_x"] == 1.0
    cons = next(r for r in report["rows"] if r["mechanism"] == "consensus")
    assert cons["n_graders"] >= 2
    dom = next(r for r in report["rows"] if r["mechanism"] == "domain_mcp")
    assert dom["pass_rate"] == 1.0
    assert dom["n_scenarios"] >= 1
    # AssetOpsBench multi-server hub (status/catalog/grade/vault)
    assert dom["n_servers"] >= 4
    assert dom["n_servers_ok"] >= 4
    assert dom["servers_ok_rate"] == 1.0
    assert report["summary"]["domain_mcp_overhead_x"] is not None
    assert report["summary"]["domain_mcp_n_servers"] >= 4
    mkt = next(r for r in report["rows"] if r["mechanism"] == "marketplace")
    assert mkt["n_plugins"] >= 1
    assert mkt["n_components"] >= 3
    assert mkt["n_errors"] == 0
    assert mkt["n_collisions"] == 0
    mplan = next(r for r in report["rows"] if r["mechanism"] == "market_plan")
    assert mplan["n_tools"] >= 3
    assert mplan["n_steps"] >= 1
    assert mplan["plan_ready"] == 1.0
    assert mplan["handoff_ok"] == 1.0
    assert mplan["kinds_ok"] == 1.0
    assert mplan["overhead_x"] is not None
    cp = next(r for r in report["rows"] if r["mechanism"] == "control_plane")
    assert cp["n_spend"] >= 1
    assert cp["total_tokens"] >= 42
    assert cp["sticky_ok"] == 1.0
    assert cp["statuses_walked"] >= 4
    db = next(r for r in report["rows"] if r["mechanism"] == "delivery_board")
    assert db["lanes_walked"] >= 5
    assert db["n_traces"] >= 5
    assert db["n_evidence"] >= 5
    assert db["n_handoffs"] >= 4
    assert db["roles_ok"] == 1.0
    assert db["signal_ok"] == 1.0
    # fixture laid out under isolated marketplace root
    fix_plugin = (
        tmp_path
        / ".nexus_state"
        / "bench"
        / "_maf_marketplace"
        / "plugins"
        / "maf-fixture"
        / "plugin.json"
    )
    assert fix_plugin.is_file()
    # isolated control-plane ops DB (never touches operator ops plane)
    ops_db = (
        tmp_path
        / ".nexus_state"
        / "bench"
        / "_maf_control_plane"
        / ".nexus_state"
        / "ops"
        / "ops.sqlite"
    )
    assert ops_db.is_file()
    # isolated delivery-board snapshots (never mutates operator board)
    board_dir = (
        tmp_path
        / ".nexus_state"
        / "bench"
        / "_maf_delivery_board"
        / "boards"
    )
    assert board_dir.is_dir()
    assert any(board_dir.glob("maf-db-*.json"))
    # export files
    exp = report["export"]
    assert Path(exp["json"]).is_file()
    assert Path(exp["md"]).is_file()
    data = json.loads(Path(exp["json"]).read_text(encoding="utf-8"))
    assert data["paper"] == "2602.03128v1"
    md = Path(exp["md"]).read_text(encoding="utf-8")
    assert "MAFBench" in md
    assert "consensus" in md
    assert "marketplace" in md
    assert "market_plan" in md
    assert "control_plane" in md
    assert "mission-control" in md
    assert "delivery_board" in md
    assert "routa" in md
    assert report["summary"]["consensus_overhead_x"] is not None
    assert report["summary"]["marketplace_overhead_x"] is not None
    assert report["summary"]["market_plan_overhead_x"] is not None
    assert report["summary"]["market_plan_handoff_ok"] == 1.0
    assert report["summary"]["control_plane_overhead_x"] is not None
    assert report["summary"]["delivery_board_overhead_x"] is not None


def test_run_maf_bench_subset_and_unknown(tmp_path: Path):
    report = mb.run_maf_bench(
        tmp_path,
        iters=3,
        mechanisms=["orch_dag", "consensus"],
        export=False,
    )
    assert report["ok"] is True
    assert [r["mechanism"] for r in report["rows"]] == ["orch_dag", "consensus"]
    bad = mb.run_maf_bench(tmp_path, mechanisms=["nope"], export=False)
    assert bad["ok"] is False
    assert "unknown" in bad["error"]


def test_smoke_short(tmp_path: Path):
    report = mb.smoke(tmp_path, iters=3)
    assert report["ok"] is True
    assert "export" not in report
    assert len(report["rows"]) == len(mb.MECHANISMS)


def test_format_report_table():
    report = {
        "schema": mb.SCHEMA,
        "paper": mb.PAPER,
        "paper_url": mb.PAPER_URL,
        "ok": True,
        "iters": 5,
        "wall_ms": 12.3,
        "rows": [
            {
                "mechanism": "single_judge",
                "family": "baseline",
                "ok_rate": 1.0,
                "p50_ms": 0.1,
                "p95_ms": 0.2,
                "mean_ms": 0.15,
                "ops_per_s": 1000.0,
                "overhead_x": 1.0,
            }
        ],
        "summary": {
            "baseline_mean_ms": 0.15,
            "consensus_overhead_x": None,
            "slowest": "single_judge",
        },
    }
    text = mb.format_report(report)
    assert "| single_judge |" in text
    assert "2602.03128" in text


def test_cli_eval_maf(tmp_path: Path, capsys):
    from nexus.cli import main

    rc = main(
        [
            "eval",
            "maf",
            "--path",
            str(tmp_path),
            "--iters",
            "4",
            "--no-export",
            "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema"] == mb.SCHEMA
    assert data["ok"] is True
    assert len(data["rows"]) == len(mb.MECHANISMS)


def test_cli_eval_maf_list(capsys):
    from nexus.cli import main

    rc = main(["eval", "maf", "--list", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == len(mb.MECHANISMS)
    assert any(m["id"] == "consensus" for m in data["mechanisms"])
    assert any(m["id"] == "domain_mcp" for m in data["mechanisms"])
    assert any(m["id"] == "marketplace" for m in data["mechanisms"])
    assert any(m["id"] == "market_plan" for m in data["mechanisms"])
    assert any(m["id"] == "control_plane" for m in data["mechanisms"])
    assert any(m["id"] == "delivery_board" for m in data["mechanisms"])


def test_overhead_gate_scorer():
    sc = mb.MafScenario(
        id="t1",
        domain="consensus",
        text="gate",
        mechanism="consensus",
        expected={"min_ok_rate": 1.0, "max_overhead_x": 5.0, "min_n_graders": 2},
    )
    ok_row = {
        "ok_rate": 1.0,
        "overhead_x": 2.5,
        "n_graders": 3,
        "mean_ms": 1.0,
    }
    gate = mb.score_overhead_gate(sc, ok_row)
    assert gate.ok is True
    assert gate.score == 1.0

    bad_row = dict(ok_row, overhead_x=50.0)
    gate2 = mb.score_overhead_gate(sc, bad_row)
    assert gate2.ok is False
    assert "overhead_x" in gate2.reason


def test_load_maf_pack_and_builtin(tmp_path: Path):
    pack = {
        "schema": mb.PACK_SCHEMA,
        "name": "unit",
        "scenarios": [
            {
                "id": "u.consensus",
                "type": "consensus",
                "domain": "framework",
                "text": "consensus gate",
                "mechanism": "consensus",
                "expected": {"min_ok_rate": 1.0, "max_overhead_x": 100.0},
            }
        ],
    }
    path = tmp_path / "unit_pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    rows = mb.load_maf_pack(path)
    assert len(rows) == 1
    assert rows[0].mechanism == "consensus"
    assert "pack" in rows[0].tags

    builtin = mb.builtin_maf_scenarios()
    assert any(s.mechanism == "domain_mcp" for s in builtin)
    assert any(s.mechanism == "consensus" for s in builtin)
    assert any(s.mechanism == "marketplace" for s in builtin)
    assert any(s.mechanism == "market_plan" for s in builtin)
    assert any(s.mechanism == "control_plane" for s in builtin)
    assert any(s.mechanism == "delivery_board" for s in builtin)


def test_run_maf_scenarios_builtin_and_pack(tmp_path: Path):
    # install bundled sample into tmp workdir via ensure (from real fixtures)
    bundled = mb.list_bundled_maf_packs()
    assert bundled, "fixtures/maf_bench/packs should ship a sample pack"
    inst = mb.ensure_sample_maf_packs(tmp_path)
    assert inst["ok"] is True
    assert inst["installed"]

    # pack-only (no builtin) using discovered runtime packs
    report = mb.run_maf_scenarios(
        tmp_path,
        include_builtin=False,
        discover=True,
        iters=3,
        export=True,
    )
    assert report["schema"] == mb.PACK_SCHEMA
    assert report["ok"] is True
    assert report["pass_rate"] == 1.0
    assert report["total"] >= 1
    assert any(r["mechanism"] == "domain_mcp" for r in report["results"])
    assert any(r["mechanism"] == "marketplace" for r in report["results"])
    assert any(r["mechanism"] == "market_plan" for r in report["results"])
    assert any(r["mechanism"] == "control_plane" for r in report["results"])
    assert any(r["mechanism"] == "delivery_board" for r in report["results"])
    exp = report["export"]
    assert Path(exp["json"]).is_file()
    md = Path(exp["md"]).read_text(encoding="utf-8")
    assert "AssetOpsBench" in md
    assert "wshobson" in md.lower()
    assert "mission-control" in md.lower() or "control_plane" in md
    assert "routa" in md.lower() or "delivery_board" in md

    # builtin pack smoke
    smoke = mb.pack_smoke(tmp_path, iters=2)
    assert smoke["ok"] is True
    assert smoke["total"] == len(mb.builtin_maf_scenarios())


def test_run_maf_scenarios_unknown_mechanism(tmp_path: Path):
    sc = mb.MafScenario(
        id="bad",
        domain="x",
        text="nope",
        mechanism="not_a_real_mech",
        expected={"min_ok_rate": 1.0},
    )
    report = mb.run_maf_scenarios(
        tmp_path,
        scenarios=[sc],
        include_builtin=False,
        iters=1,
        export=False,
    )
    assert report["ok"] is False
    assert "unknown" in (report.get("error") or "")


def test_cli_eval_maf_pack(tmp_path: Path, capsys):
    from nexus.cli import main

    # write a minimal pack under tmp
    pack = {
        "schema": mb.PACK_SCHEMA,
        "scenarios": [
            {
                "id": "cli.orch",
                "type": "orchestration",
                "domain": "framework",
                "text": "dag",
                "mechanism": "orch_dag",
                "expected": {"min_ok_rate": 1.0},
            }
        ],
    }
    p = tmp_path / "cli_pack.json"
    p.write_text(json.dumps(pack), encoding="utf-8")
    rc = main(
        [
            "eval",
            "maf",
            "--path",
            str(tmp_path),
            "--pack",
            str(p),
            "--no-builtin",
            "--iters",
            "3",
            "--no-export",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == mb.PACK_SCHEMA
    assert data["ok"] is True
    assert data["total"] == 1
    assert data["results"][0]["mechanism"] == "orch_dag"


def test_mcp_tool_maf_bench(tmp_path: Path, monkeypatch):
    from nexus import mcp_server

    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    # list
    out = mcp_server.call_tool("maf_bench", {"action": "list"})
    assert out.get("isError") is not True
    data = json.loads(out["content"][0]["text"])
    assert data["count"] == len(mb.MECHANISMS)
    assert any(m["id"] == "domain_mcp" for m in data["mechanisms"])
    assert any(m["id"] == "marketplace" for m in data["mechanisms"])
    assert any(m["id"] == "market_plan" for m in data["mechanisms"])
    assert any(m["id"] == "control_plane" for m in data["mechanisms"])
    assert any(m["id"] == "delivery_board" for m in data["mechanisms"])

    # smoke (short)
    out2 = mcp_server.call_tool(
        "maf_bench",
        {"action": "smoke", "iters": 2, "export": False},
    )
    assert out2.get("isError") is not True
    data2 = json.loads(out2["content"][0]["text"])
    assert data2["ok"] is True
    assert data2["schema"] == mb.SCHEMA

    # install samples + packs list
    out3 = mcp_server.call_tool(
        "maf_bench",
        {"action": "packs", "install_samples": True},
    )
    assert out3.get("isError") is not True
    data3 = json.loads(out3["content"][0]["text"])
    assert data3["schema"] == mb.PACK_SCHEMA
    assert data3.get("install", {}).get("ok") is True

    # pack mode with discover
    out4 = mcp_server.call_tool(
        "maf_bench",
        {
            "action": "pack",
            "discover_packs": True,
            "no_builtin": True,
            "iters": 2,
            "export": False,
        },
    )
    assert out4.get("isError") is not True
    data4 = json.loads(out4["content"][0]["text"])
    assert data4["schema"] == mb.PACK_SCHEMA
    assert data4["ok"] is True
    assert data4["pass_rate"] == 1.0


def test_tool_catalog_has_maf_bench():
    from nexus.tool_catalog import TOOL_PRIVILEGE

    assert TOOL_PRIVILEGE.get("maf_bench") == "read"


def test_list_domain_mcp_servers():
    rows = mb.list_domain_mcp_servers()
    assert len(rows) >= 4
    ids = {r["id"] for r in rows}
    assert {"status", "catalog", "grade", "vault"} <= ids
    analogues = {r["assetops_analogue"] for r in rows}
    # AssetOpsBench multi-server analogues (pattern only)
    assert analogues & {"utilities", "iot", "fmsr", "wo"}


def test_domain_mcp_multi_server_hub(tmp_path: Path):
    report = mb.run_maf_bench(
        tmp_path,
        iters=2,
        mechanisms=["single_judge", "domain_mcp"],
        export=False,
    )
    assert report["ok"] is True
    dom = report["rows"][1]
    assert dom["mechanism"] == "domain_mcp"
    assert dom["ok_rate"] == 1.0
    assert dom["n_servers"] >= 4
    assert dom["n_servers_ok"] == dom["n_servers"]
    assert dom["servers_ok_rate"] == 1.0
    assert dom["pass_rate"] == 1.0
    assert dom["n_scenarios"] >= 4  # at least one per server
    assert "status" in str(dom.get("server_ids") or "")


def test_domain_mcp_overhead_gate_n_servers():
    sc = mb.MafScenario(
        id="hub1",
        domain="domain_mcp",
        text="multi-server gate",
        mechanism="domain_mcp",
        expected={
            "min_ok_rate": 1.0,
            "min_pass_rate": 1.0,
            "min_n_servers": 4,
            "min_servers_ok_rate": 1.0,
        },
    )
    ok_row = {
        "ok_rate": 1.0,
        "pass_rate": 1.0,
        "n_servers": 4,
        "servers_ok_rate": 1.0,
        "mean_ms": 1.0,
    }
    gate = mb.score_overhead_gate(sc, ok_row)
    assert gate.ok is True
    bad = dict(ok_row, n_servers=1)
    gate2 = mb.score_overhead_gate(sc, bad)
    assert gate2.ok is False
    assert "n_servers" in gate2.reason


def test_maf_brief_offline(tmp_path: Path):
    brief = mb.maf_brief(tmp_path, iters=2, include_pack=True)
    assert brief["schema"] == mb.BRIEF_SCHEMA
    assert brief["ok"] is True
    assert brief["paper"] == "2602.03128v1"
    assert brief["consensus_overhead_x"] is not None
    assert brief["domain_mcp_overhead_x"] is not None
    assert brief["domain_mcp_n_servers"] >= 4
    assert brief["domain_mcp_pass_rate"] == 1.0
    assert brief["pack_ok"] is True
    assert brief["pack_pass_rate"] == 1.0
    assert brief["pack_total"] >= 2  # baseline + consensus + domain_mcp
    text = mb.format_brief(brief)
    assert "consensus_overhead_x" in text
    assert "domain_mcp" in text


def test_cli_eval_maf_brief(tmp_path: Path, capsys):
    from nexus.cli import main

    rc = main(
        [
            "eval",
            "maf",
            "--path",
            str(tmp_path),
            "--brief",
            "--iters",
            "2",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == mb.BRIEF_SCHEMA
    assert data["ok"] is True
    assert data["domain_mcp_n_servers"] >= 4


def test_mcp_tool_maf_brief(tmp_path: Path, monkeypatch):
    from nexus import mcp_server

    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    out = mcp_server.call_tool(
        "maf_bench",
        {"action": "brief", "iters": 2},
    )
    assert out.get("isError") is not True
    data = json.loads(out["content"][0]["text"])
    assert data["schema"] == mb.BRIEF_SCHEMA
    assert data["ok"] is True
    assert data["pack_pass_rate"] == 1.0


def test_alive_self_check_includes_maf_brief(tmp_path: Path, monkeypatch):
    """Alive _run_checks surfaces advisory MAFBench brief metrics."""
    from nexus import alive as al

    # Avoid running full project checks (make test etc.) — stub them.
    class _FakeCheck:
        def __init__(self, name: str, ok: bool = True):
            self.name = name
            self.ok = ok
            self.returncode = 0 if ok else 1

    def _fake_run_project_checks(workdir, timeout_each=180):
        return [_FakeCheck("unit", True)]

    monkeypatch.setattr(
        "nexus.github_community.run_project_checks",
        _fake_run_project_checks,
    )
    # No plugins/ → marketplace soft-skipped
    result = al._run_checks(tmp_path)
    names = [c["name"] for c in result["checks"]]
    assert "maf_brief" in names
    brief_row = next(c for c in result["checks"] if c["name"] == "maf_brief")
    assert brief_row.get("advisory") is True
    # Advisory never fails overall self_check
    assert brief_row.get("ok") is True
    assert brief_row.get("brief_ok") is True
    assert brief_row.get("consensus_overhead_x") is not None
    assert brief_row.get("domain_mcp_n_servers") >= 4
    assert brief_row.get("pack_pass_rate") == 1.0
    assert result.get("ok") is True


def test_ensure_maf_marketplace_fixture_layout(tmp_path: Path):
    mroot = mb.ensure_maf_marketplace_fixture(tmp_path)
    plugin = mroot / "plugins" / "maf-fixture"
    assert (plugin / "plugin.json").is_file()
    assert (plugin / "agents" / "maf-bench-agent.md").is_file()
    assert (plugin / "commands" / "maf-smoke.md").is_file()
    assert (plugin / "skills" / "maf-catalog" / "SKILL.md").is_file()
    # idempotent
    mroot2 = mb.ensure_maf_marketplace_fixture(tmp_path)
    assert mroot2 == mroot


def test_marketplace_mechanism_subset(tmp_path: Path):
    report = mb.run_maf_bench(
        tmp_path,
        iters=3,
        mechanisms=["single_judge", "marketplace"],
        export=False,
    )
    assert report["ok"] is True
    mechs = [r["mechanism"] for r in report["rows"]]
    assert mechs == ["single_judge", "marketplace"]
    mkt = report["rows"][1]
    assert mkt["ok_rate"] == 1.0
    assert mkt["n_plugins"] >= 1
    assert mkt["n_agents"] >= 1
    assert mkt["n_skills"] >= 1
    assert mkt["n_commands"] >= 1
    assert mkt["overhead_x"] is not None
    assert mkt["harness_count"] >= 1


def test_marketplace_overhead_gate_scorer():
    sc = mb.MafScenario(
        id="mkt1",
        domain="marketplace",
        text="gate",
        mechanism="marketplace",
        expected={
            "min_ok_rate": 1.0,
            "min_n_plugins": 1,
            "min_n_components": 3,
            "max_n_errors": 0,
            "max_n_collisions": 0,
            "max_overhead_x": 50.0,
        },
    )
    ok_row = {
        "ok_rate": 1.0,
        "n_plugins": 1,
        "n_components": 3,
        "n_errors": 0,
        "n_collisions": 0,
        "overhead_x": 2.0,
        "mean_ms": 1.0,
    }
    gate = mb.score_overhead_gate(sc, ok_row)
    assert gate.ok is True
    bad = dict(ok_row, n_components=1)
    gate2 = mb.score_overhead_gate(sc, bad)
    assert gate2.ok is False
    assert "n_components" in gate2.reason


def test_market_plan_mechanism_subset(tmp_path: Path):
    """arXiv 2602.03128 × wshobson: catalog → Planner → Orchestrator handoff."""
    report = mb.run_maf_bench(
        tmp_path,
        iters=3,
        mechanisms=["single_judge", "market_plan"],
        export=False,
    )
    assert report["ok"] is True
    mechs = [r["mechanism"] for r in report["rows"]]
    assert mechs == ["single_judge", "market_plan"]
    row = report["rows"][1]
    assert row["ok_rate"] == 1.0
    assert row["n_tools"] >= 3
    assert row["n_plugins"] >= 1
    assert row["n_steps"] >= 1
    assert row["plan_ready"] == 1.0
    assert row["handoff_ok"] == 1.0
    assert row["kinds_ok"] == 1.0
    assert row["pre_planned"] == 1.0
    assert row["schema_ok"] == 1.0
    assert row["overhead_x"] is not None
    assert report["summary"]["market_plan_overhead_x"] is not None
    assert report["summary"]["market_plan_handoff_ok"] == 1.0
    assert report["summary"]["market_plan_n_steps"] >= 1


def test_market_plan_overhead_gate_scorer():
    sc = mb.MafScenario(
        id="mp1",
        domain="market_plan",
        text="gate",
        mechanism="market_plan",
        expected={
            "min_ok_rate": 1.0,
            "min_n_tools": 3,
            "min_n_steps": 1,
            "min_plan_ready": 1.0,
            "min_handoff_ok": 1.0,
            "min_kinds_ok": 1.0,
            "min_pre_planned": 1.0,
            "max_overhead_x": 5000.0,
        },
    )
    ok_row = {
        "ok_rate": 1.0,
        "n_tools": 3,
        "n_steps": 3,
        "plan_ready": 1.0,
        "handoff_ok": 1.0,
        "kinds_ok": 1.0,
        "pre_planned": 1.0,
        "overhead_x": 100.0,
        "mean_ms": 20.0,
    }
    gate = mb.score_overhead_gate(sc, ok_row)
    assert gate.ok is True
    bad = dict(ok_row, plan_ready=0.0)
    gate2 = mb.score_overhead_gate(sc, bad)
    assert gate2.ok is False
    assert "plan_ready" in gate2.reason
    bad_ho = dict(ok_row, handoff_ok=0.0)
    gate3 = mb.score_overhead_gate(sc, bad_ho)
    assert gate3.ok is False
    assert "handoff_ok" in gate3.reason


def test_cli_eval_maf_market_plan(tmp_path: Path, capsys):
    from nexus.cli import main

    rc = main(
        [
            "eval",
            "maf",
            "--path",
            str(tmp_path),
            "--mechanism",
            "market_plan",
            "--iters",
            "2",
            "--no-export",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert [r["mechanism"] for r in data["rows"]] == ["market_plan"]
    assert data["rows"][0]["handoff_ok"] == 1.0


def test_ensure_maf_control_plane_root(tmp_path: Path):
    root = mb.ensure_maf_control_plane_root(tmp_path)
    assert root.is_dir()
    assert root.name == "_maf_control_plane"
    # idempotent
    root2 = mb.ensure_maf_control_plane_root(tmp_path)
    assert root2 == root


def test_control_plane_mechanism_subset(tmp_path: Path):
    report = mb.run_maf_bench(
        tmp_path,
        iters=3,
        mechanisms=["single_judge", "control_plane"],
        export=False,
    )
    assert report["ok"] is True
    mechs = [r["mechanism"] for r in report["rows"]]
    assert mechs == ["single_judge", "control_plane"]
    cp = report["rows"][1]
    assert cp["ok_rate"] == 1.0
    assert cp["n_spend"] >= 1
    assert cp["total_tokens"] >= 42
    assert cp["sticky_ok"] == 1.0
    assert cp["statuses_walked"] >= 4
    assert cp["n_jobs"] >= 1
    assert cp["overhead_x"] is not None
    assert report["summary"]["control_plane_overhead_x"] is not None
    ops_db = (
        tmp_path
        / ".nexus_state"
        / "bench"
        / "_maf_control_plane"
        / ".nexus_state"
        / "ops"
        / "ops.sqlite"
    )
    assert ops_db.is_file()


def test_control_plane_overhead_gate_scorer():
    sc = mb.MafScenario(
        id="cp1",
        domain="control_plane",
        text="gate",
        mechanism="control_plane",
        expected={
            "min_ok_rate": 1.0,
            "min_n_spend": 1,
            "min_total_tokens": 42,
            "min_sticky_ok": 1.0,
            "min_statuses_walked": 4,
            "max_overhead_x": 50.0,
        },
    )
    ok_row = {
        "ok_rate": 1.0,
        "n_spend": 1,
        "total_tokens": 42,
        "sticky_ok": 1.0,
        "statuses_walked": 4,
        "overhead_x": 3.0,
        "mean_ms": 1.0,
    }
    gate = mb.score_overhead_gate(sc, ok_row)
    assert gate.ok is True
    bad = dict(ok_row, sticky_ok=0.0)
    gate2 = mb.score_overhead_gate(sc, bad)
    assert gate2.ok is False
    assert "sticky_ok" in gate2.reason


def test_ensure_maf_delivery_board_root(tmp_path: Path):
    root = mb.ensure_maf_delivery_board_root(tmp_path)
    assert root.is_dir()
    assert root.name == "_maf_delivery_board"
    assert (root / "boards").is_dir()
    assert (root / "traces").is_dir()
    # idempotent
    root2 = mb.ensure_maf_delivery_board_root(tmp_path)
    assert root2 == root


def test_delivery_board_mechanism_subset(tmp_path: Path):
    report = mb.run_maf_bench(
        tmp_path,
        iters=3,
        mechanisms=["single_judge", "delivery_board"],
        export=False,
    )
    assert report["ok"] is True
    mechs = [r["mechanism"] for r in report["rows"]]
    assert mechs == ["single_judge", "delivery_board"]
    db = report["rows"][1]
    assert db["ok_rate"] == 1.0
    assert db["lanes_walked"] >= 5
    assert db["n_traces"] >= 5
    assert db["n_evidence"] >= 5
    assert db["n_handoffs"] >= 4
    assert db["roles_ok"] == 1.0
    assert db["signal_ok"] == 1.0
    assert db["sticky_ok"] == 1.0
    assert db["overhead_x"] is not None
    assert report["summary"]["delivery_board_overhead_x"] is not None
    board_dir = (
        tmp_path
        / ".nexus_state"
        / "bench"
        / "_maf_delivery_board"
        / "boards"
    )
    snaps = list(board_dir.glob("maf-db-*.json"))
    assert len(snaps) >= 1
    snap = json.loads(snaps[0].read_text(encoding="utf-8"))
    assert snap.get("mechanism") == "delivery_board"
    assert snap.get("pattern") == "phodal/routa"
    assert snap.get("lanes") == list(mb.DELIVERY_LANES)
    assert snap.get("signal") == "continue"


def test_delivery_board_overhead_gate_scorer():
    sc = mb.MafScenario(
        id="db1",
        domain="delivery_board",
        text="gate",
        mechanism="delivery_board",
        expected={
            "min_ok_rate": 1.0,
            "min_lanes_walked": 5,
            "min_n_traces": 5,
            "min_n_evidence": 5,
            "min_n_handoffs": 4,
            "min_roles_ok": 1.0,
            "min_signal_ok": 1.0,
            "max_overhead_x": 50.0,
        },
    )
    ok_row = {
        "ok_rate": 1.0,
        "lanes_walked": 5,
        "n_traces": 5,
        "n_evidence": 5,
        "n_handoffs": 4,
        "roles_ok": 1.0,
        "signal_ok": 1.0,
        "overhead_x": 4.0,
        "mean_ms": 1.0,
    }
    gate = mb.score_overhead_gate(sc, ok_row)
    assert gate.ok is True
    bad = dict(ok_row, lanes_walked=2)
    gate2 = mb.score_overhead_gate(sc, bad)
    assert gate2.ok is False
    assert "lanes_walked" in gate2.reason
    bad_sig = dict(ok_row, signal_ok=0.0)
    gate3 = mb.score_overhead_gate(sc, bad_sig)
    assert gate3.ok is False
    assert "signal_ok" in gate3.reason