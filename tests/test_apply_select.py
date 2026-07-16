"""First apply slice: FTS apply select + role gate + improve board (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import apply_select as asel
from nexus import mcp_server
from nexus.durability.budgets import RunBudget


ROOT = Path(__file__).resolve().parents[1]
CLAIMS_FIXTURE = ROOT / "fixtures" / "mine_eval" / "grades_with_claims.json"


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """Isolated workdir with claims fixture + empty state dirs."""
    fx = tmp_path / "fixtures" / "mine_eval"
    fx.mkdir(parents=True)
    (fx / "grades_with_claims.json").write_text(
        CLAIMS_FIXTURE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / ".nexus_state").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Roles (anti-collusion 2601.00360)
# ---------------------------------------------------------------------------


def test_check_roles_ok_when_distinct():
    r = asel.check_roles(
        grader="grok:grade",
        implementer="worker:apply",
        verifier="judge:verify",
    )
    assert r["ok"] is True
    assert r["distinct"] is True
    assert r["collisions"] == []


def test_check_roles_detects_collusion():
    r = asel.check_roles(
        grader="same",
        implementer="same",
        verifier="other",
    )
    assert r["ok"] is False
    assert "grader==implementer" in r["collisions"]


def test_require_roles_raises():
    with pytest.raises(asel.RoleCollusionError, match="collusion"):
        asel.require_roles(
            grader="a",
            implementer="a",
            verifier="b",
        )


# ---------------------------------------------------------------------------
# Select + rank (cas FTS + Thucy claims)
# ---------------------------------------------------------------------------


def test_select_candidates_ranks_wshobson(work: Path):
    sel = asel.select_candidates(
        work,
        query="Markdown marketplace",
        min_score=10.0,
        limit=5,
        fixture=work / "fixtures" / "mine_eval" / "grades_with_claims.json",
        require_evidence=True,
        auto_index=True,
    )
    assert sel["ok"] is True
    assert sel["schema"] == asel.SCHEMA
    repos = [c["repo"] for c in sel["candidates"]]
    assert "wshobson/agents" in repos
    top = sel["candidates"][0]
    assert top["repo"] == "wshobson/agents"
    assert top["evidence_hits"] >= 1
    assert top["rank"] >= top["score"]
    # evidence should mention marketplace or wshobson-related claim
    blob = json.dumps(top["evidence"]).lower()
    assert "markdown" in blob or "marketplace" in blob or "wshobson" in blob


def test_select_skips_without_evidence_when_required(work: Path):
    # bare grade with no claims and empty FTS → skipped
    bare = work / "bare.json"
    bare.write_text(
        json.dumps(
            {
                "grades": [
                    {
                        "repo": "nobody/empty",
                        "score": 12.0,
                        "idea": 6.0,
                        "skill": 6.0,
                        "method": "test",
                        "path": ".nexus_workspaces/mine_eval/nobody__empty",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sel = asel.select_candidates(
        work,
        fixture=bare,
        min_score=10.0,
        require_evidence=True,
        auto_index=False,
    )
    assert sel["count"] == 0
    assert any(s.get("repo") == "nobody/empty" for s in sel["skipped"])


def test_rank_score_boosts_with_hits():
    g = {"score": 10.0}
    assert asel.rank_score(g, []) == 10.0
    assert asel.rank_score(g, [{"id": "1"}, {"id": "2"}]) == 11.0
    assert asel.rank_score(g, [], preference_delta=0.5) == 10.5
    assert asel.rank_score(g, [{"id": "1"}], preference_delta=-0.25) == 10.25
    assert asel.rank_score(g, [], spine_delta=asel.SPINE_BOOST) == 10.0 + asel.SPINE_BOOST
    assert asel.rank_score(
        g, [{"id": "1"}], preference_delta=0.5, spine_delta=1.0
    ) == 12.0


def test_spine_rank_delta_presence_and_align():
    g = {"score": 14.0}
    none_delta, none_meta = asel.spine_rank_delta(g, None)
    assert none_delta == 0.0
    assert none_meta["on_spine"] is False

    delta, meta = asel.spine_rank_delta(
        g,
        {
            "score": 16.5,
            "run_id": "run-a",
            "method": "grok:grok-4.5",
            "id": "g1",
        },
    )
    assert meta["on_spine"] is True
    assert meta["spine_score"] == 16.5
    # presence boost + capped (16.5-14=2.5 → cap 2.0)
    assert delta == pytest.approx(asel.SPINE_BOOST + 2.0)
    assert meta["spine_boost"] == delta
    assert meta["spine_method"] == "grok:grok-4.5"
    assert meta["spine_run_id"] == "run-a"
    assert meta["spine_grade_id"] == "g1"


def test_spine_evidence_refs_empty_without_spine():
    assert asel.spine_evidence_refs({}) == []
    assert asel.spine_evidence_refs({"repo": "x/y", "method": "fixture"}) == []


def test_spine_evidence_refs_includes_method_run():
    refs = asel.spine_evidence_refs(
        {
            "on_spine": True,
            "spine_method": "grok:grok-4.5",
            "spine_run_id": "run-a",
            "spine_grade_id": "g1",
            "spine_score": 16.0,
        }
    )
    assert "spine:method:grok:grok-4.5" in refs
    assert "spine:run:run-a" in refs
    assert "spine:grade:g1" in refs
    assert "spine:score:16.0" in refs


def test_gate_apply_decision_package_includes_spine_method():
    """Decision package evidence_refs cite durable spine method (2511.15755)."""
    cand = {
        "repo": "wshobson/agents",
        "score": 16.0,
        "method": "grok:grok-4.5",
        "path": ".nexus_workspaces/mine_eval/wshobson__agents",
        "evidence_hits": 1,
        "evidence": [
            {"path": "README.md", "statement": "Markdown marketplace"},
        ],
        "on_spine": True,
        "spine_method": "grok:grok-4.5",
        "spine_run_id": "spine-board-1",
        "spine_score": 16.0,
        "spine_boost": 1.0,
        "spine_grade_id": "grade-1",
    }
    dec = asel.gate_apply(
        cand,
        grader="grok:grade",
        implementer="worker:apply",
        verifier="judge:verify",
    )
    assert dec["ok"] is True
    assert dec["candidate"]["spine_method"] == "grok:grok-4.5"
    assert dec["candidate"]["on_spine"] is True
    assert dec["candidate"]["method"] == "grok:grok-4.5"
    refs = dec["evidence_refs"]
    assert any(r.startswith("spine:method:") for r in refs)
    assert any(r == "spine:run:spine-board-1" for r in refs)
    assert "README.md" in refs


def test_select_candidates_applies_preference_boost(work: Path):
    """Offline preference pairs (2602.04518) bias rank when use_preference=True."""
    from nexus import preference_pairs as pp

    fx = work / "fixtures" / "mine_eval" / "grades_with_claims.json"
    # Record strong preference for wshobson over any competitor
    pp.record_pair(
        work,
        better="wshobson/agents",
        worse="codingagentsystem/cas",
        better_score=16.0,
        worse_score=15.0,
        source="test",
    )
    # Extra wins so boost is clearly non-zero
    pp.record_pair(
        work,
        better="wshobson/agents",
        worse="openai/swarm",
        source="test",
    )

    sel = asel.select_candidates(
        work,
        fixture=fx,
        min_score=10.0,
        limit=5,
        require_evidence=True,
        auto_index=True,
        use_preference=True,
    )
    assert sel["ok"] is True
    assert sel["use_preference"] is True
    by_repo = {c["repo"]: c for c in sel["candidates"]}
    assert "wshobson/agents" in by_repo
    w = by_repo["wshobson/agents"]
    assert w["preference_boost"] > 0
    # rank includes preference delta above score + evidence
    assert w["rank"] >= w["score"] + w["preference_boost"] - 0.01

    sel_off = asel.select_candidates(
        work,
        fixture=fx,
        min_score=10.0,
        limit=5,
        require_evidence=True,
        auto_index=False,
        use_preference=False,
    )
    w_off = {c["repo"]: c for c in sel_off["candidates"]}["wshobson/agents"]
    assert w_off["preference_boost"] == 0.0
    assert w_off["rank"] < w["rank"]


def test_select_candidates_spine_boost_and_board(work: Path):
    """Durable improve_spine grades boost board rank (cas/soul spine wire)."""
    from nexus import improve_spine as spine

    fx = work / "fixtures" / "mine_eval" / "grades_with_claims.json"
    # Seed spine with wshobson at high durable score
    with spine.ImproveSpine.open(work) as store:
        store.record_grade(
            repo_or_paper_id="wshobson/agents",
            score=16.0,
            idea=8.0,
            skill=8.0,
            method="grok:grok-4.5",
            summary="Markdown skill marketplace",
            path="fixtures/mine_eval/grades_with_claims.json",
            run_id="spine-board-1",
        )
        store.append(
            run_id="spine-board-1",
            stage=spine.STAGE_GRADED,
            agent="grok:grade",
            action="grade",
            payload={"repo": "wshobson/agents", "score": 16.0},
        )

    sel = asel.select_candidates(
        work,
        fixture=fx,
        min_score=10.0,
        limit=5,
        require_evidence=True,
        auto_index=True,
        use_preference=False,
        use_spine=True,
        run_id="spine-board-1",
    )
    assert sel["ok"] is True
    assert sel["use_spine"] is True
    assert sel["spine_repos"] >= 1
    by_repo = {c["repo"]: c for c in sel["candidates"]}
    assert "wshobson/agents" in by_repo
    w = by_repo["wshobson/agents"]
    assert w["on_spine"] is True
    assert w["spine_score"] == 16.0
    assert w["spine_boost"] >= asel.SPINE_BOOST
    assert w["spine_method"] == "grok:grok-4.5"
    assert w["spine_run_id"] == "spine-board-1"
    assert w["rank"] >= w["score"] + asel.SPINE_BOOST - 0.01

    # decision package must cite spine method in evidence_refs
    pkg = asel.gate_apply(
        w,
        grader="grok:grade",
        implementer="worker:apply",
        verifier="judge:verify",
    )
    assert pkg["ok"] is True
    assert any("spine:method:grok:grok-4.5" in r for r in pkg["evidence_refs"])
    assert pkg["candidate"].get("spine_run_id") == "spine-board-1"

    sel_off = asel.select_candidates(
        work,
        fixture=fx,
        min_score=10.0,
        limit=5,
        require_evidence=True,
        auto_index=False,
        use_preference=False,
        use_spine=False,
    )
    w_off = {c["repo"]: c for c in sel_off["candidates"]}["wshobson/agents"]
    assert w_off["on_spine"] is False
    assert w_off["spine_boost"] == 0.0
    assert w_off["rank"] < w["rank"]

    board = asel.improve_board(
        work,
        fixture=fx,
        min_score=10.0,
        use_spine=True,
        use_preference=False,
        auto_index=False,
        run_id="spine-board-1",
    )
    assert board["use_spine"] is True
    assert board["spine_repos"] >= 1
    top = (board.get("candidates") or [{}])[0]
    assert top.get("on_spine") is True
    text = asel.format_board(board)
    assert "spine=" in text
    assert "method=grok:grok-4.5" in text
    sel_text = asel.format_selection(sel)
    assert "method=grok:grok-4.5" in sel_text


def test_decision_package_use_spine_flag(work: Path):
    """decide path honors use_spine / --no-spine (CLI parity with select/board)."""
    from nexus import improve_spine as spine

    fx = work / "fixtures" / "mine_eval" / "grades_with_claims.json"
    with spine.ImproveSpine.open(work) as store:
        store.record_grade(
            repo_or_paper_id="wshobson/agents",
            score=16.0,
            idea=8.0,
            skill=8.0,
            method="grok:grok-4.5",
            summary="Markdown skill marketplace",
            path="fixtures/mine_eval/grades_with_claims.json",
            run_id="decide-spine-1",
        )
        store.append(
            run_id="decide-spine-1",
            stage=spine.STAGE_GRADED,
            agent="grok:grade",
            action="grade",
            payload={"repo": "wshobson/agents", "score": 16.0},
        )

    on = asel.decision_package(
        work,
        repo="wshobson/agents",
        fixture=fx,
        min_score=10.0,
        require_evidence=True,
        auto_index=True,
        use_spine=True,
        use_preference=False,
        run_id="decide-spine-1",
        grader="grok:grade",
        implementer="worker:apply",
        verifier="judge:verify",
    )
    assert on.get("ok") is True
    assert on.get("use_spine") is True
    assert on["selection"].get("use_spine") is True
    cand = on.get("candidate") or {}
    assert cand.get("on_spine") is True
    assert cand.get("spine_method") == "grok:grok-4.5"
    assert any("spine:method:grok:grok-4.5" in r for r in (on.get("evidence_refs") or []))

    off = asel.decision_package(
        work,
        repo="wshobson/agents",
        fixture=fx,
        min_score=10.0,
        require_evidence=True,
        auto_index=False,
        use_spine=False,
        use_preference=False,
        grader="grok:grade",
        implementer="worker:apply",
        verifier="judge:verify",
    )
    assert off.get("use_spine") is False
    off_cand = off.get("candidate") or {}
    assert off_cand.get("on_spine") is False
    assert not any(
        str(r).startswith("spine:method:") for r in (off.get("evidence_refs") or [])
    )


# ---------------------------------------------------------------------------
# Gate / decision package
# ---------------------------------------------------------------------------


def test_gate_apply_allows_distinct_roles_with_evidence():
    cand = {
        "repo": "wshobson/agents",
        "score": 16.0,
        "path": ".nexus_workspaces/mine_eval/wshobson__agents",
        "evidence_hits": 2,
        "evidence": [
            {"path": "README.md", "statement": "Markdown marketplace"},
            {"path": "Makefile", "statement": "generate validate test"},
        ],
    }
    dec = asel.gate_apply(
        cand,
        grader="grok:grade",
        implementer="worker:apply",
        verifier="judge:verify",
    )
    assert dec["ok"] is True
    assert dec["schema"] == asel.DECISION_SCHEMA
    assert dec["confidence"] > 0
    assert dec["evidence_refs"]


def test_gate_apply_denies_same_agent():
    cand = {
        "repo": "x/y",
        "score": 15.0,
        "evidence": [{"path": "p", "statement": "s"}],
        "evidence_hits": 1,
    }
    dec = asel.gate_apply(
        cand,
        grader="same",
        implementer="same",
        verifier="same",
        require_distinct_roles=True,
    )
    assert dec["ok"] is False
    assert "collusion" in (dec.get("reason") or "")


def test_gate_apply_budget_exhausted():
    cand = {
        "repo": "x/y",
        "score": 15.0,
        "evidence": [{"path": "p", "statement": "s"}],
        "evidence_hits": 1,
    }
    bud = RunBudget(max_steps=0, hard=True)  # already exhausted
    # max_steps=0 means steps_used(0) >= 0 → exhausted before consume
    dec = asel.gate_apply(
        cand,
        grader="g",
        implementer="i",
        verifier="v",
        budget=bud,
        budget_steps=1,
    )
    assert dec["ok"] is False
    assert "budget" in (dec.get("reason") or "")


def test_decision_package_top_repo(work: Path):
    pkg = asel.decision_package(
        work,
        fixture=work / "fixtures" / "mine_eval" / "grades_with_claims.json",
        min_score=10.0,
        auto_index=True,
    )
    assert pkg["ok"] is True
    assert pkg["candidate"]["repo"] == "wshobson/agents"
    assert pkg["action_order"]
    assert pkg["action_order"][0]["action"] == "grade"
    assert any("evidence" in str(pkg).lower() for _ in [0])


def test_decision_package_named_repo(work: Path):
    pkg = asel.decision_package(
        work,
        repo="codingagentsystem/cas",
        fixture=work / "fixtures" / "mine_eval" / "grades_with_claims.json",
        auto_index=True,
    )
    assert pkg["ok"] is True
    assert pkg["candidate"]["repo"] == "codingagentsystem/cas"


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------


def test_improve_board_structure(work: Path):
    board = asel.improve_board(
        work,
        fixture=work / "fixtures" / "mine_eval" / "grades_with_claims.json",
        goal="prove board",
        auto_index=True,
    )
    assert board["schema"] == asel.BOARD_SCHEMA
    assert board["ok"] is True
    assert board["goal"] == "prove board"
    assert board["roles_ok"] is True
    assert board["candidates"]
    assert board["decision"] is not None
    assert board["decision"]["ok"] is True
    assert board["signal"] == asel.SIGNAL_CONTINUE
    text = asel.format_board(board)
    assert "improve board" in text
    assert "wshobson" in text
    assert "ALLOW" in text or "DENY" in text
    assert "CONTINUE" in text or "signal" in text.lower()


# ---------------------------------------------------------------------------
# Board signals (zenith stop/replan) + decision_for_grade
# ---------------------------------------------------------------------------


def test_board_signal_continue_on_allow():
    dec = {
        "ok": True,
        "reason": "apply_allowed",
        "confidence": 0.8,
        "candidate": {"repo": "wshobson/agents"},
    }
    sig = asel.board_signal(
        decision=dec,
        roles_ok=True,
        candidates=[{"repo": "wshobson/agents"}],
    )
    assert sig["signal"] == asel.SIGNAL_CONTINUE


def test_board_signal_stop_on_collusion():
    sig = asel.board_signal(
        decision={"ok": False, "reason": "role_collusion:grader==implementer"},
        roles_ok=False,
        candidates=[{"repo": "x/y"}],
    )
    assert sig["signal"] == asel.SIGNAL_STOP
    assert "collusion" in sig["reason"]


def test_board_signal_replan_on_no_candidates():
    sig = asel.board_signal(
        decision={"ok": False, "reason": "no_candidates"},
        roles_ok=True,
        candidates=[],
        skipped=[{"repo": "a/b", "skip_reason": "no_evidence"}],
    )
    assert sig["signal"] == asel.SIGNAL_REPLAN
    assert sig["hints"]


def test_board_signal_stop_on_principled_stop():
    sig = asel.board_signal(
        decision={"ok": True, "reason": "apply_allowed", "confidence": 0.9},
        roles_ok=True,
        candidates=[{"repo": "x/y"}],
        stop_decision={"stop": True, "reason": "gaps_closed", "detail": "done"},
    )
    assert sig["signal"] == asel.SIGNAL_STOP
    assert "principled_stop" in sig["reason"]


def test_board_signal_replan_low_confidence():
    sig = asel.board_signal(
        decision={
            "ok": True,
            "reason": "apply_allowed",
            "confidence": 0.1,
            "candidate": {"repo": "x/y"},
        },
        roles_ok=True,
        candidates=[{"repo": "x/y"}],
        low_confidence=0.35,
    )
    assert sig["signal"] == asel.SIGNAL_REPLAN
    assert "low_confidence" in sig["reason"]


def test_sync_signal_to_stop_replan_registers_gap():
    from nexus.durability.stop import PrincipledStop

    stop = PrincipledStop()
    out = asel.sync_signal_to_stop(
        stop,
        {
            "signal": asel.SIGNAL_REPLAN,
            "reason": "no_candidates",
            "detail": "empty board",
            "hints": ["lower min-score"],
        },
    )
    assert out["ok"] is True
    assert asel.BOARD_GAP_REPLAN in stop.gaps
    assert stop.gaps[asel.BOARD_GAP_REPLAN].open is True
    assert any(a["action"] == "register" for a in out["actions"])


def test_sync_signal_to_stop_hard_stop_aborts():
    from nexus.durability.stop import PrincipledStop

    stop = PrincipledStop()
    out = asel.sync_signal_to_stop(
        stop,
        {"signal": asel.SIGNAL_STOP, "reason": "role_collusion", "detail": "x"},
        abort_on_hard_stop=True,
    )
    assert out["ok"] is True
    assert asel.BOARD_GAP_STOP in stop.gaps
    assert stop.aborted is True
    assert any(a.get("action") == "abort" for a in out["actions"])


def test_sync_signal_to_stop_continue_closes_board_gaps():
    from nexus.durability.stop import PrincipledStop

    stop = PrincipledStop()
    stop.register_gap(asel.BOARD_GAP_REPLAN, "stale replan")
    stop.register_gap(asel.BOARD_GAP_STOP, "stale stop")
    out = asel.sync_signal_to_stop(
        stop,
        {"signal": asel.SIGNAL_CONTINUE, "reason": "apply_allowed"},
        close_on_continue=True,
    )
    assert out["ok"] is True
    assert stop.gaps[asel.BOARD_GAP_REPLAN].open is False
    assert stop.gaps[asel.BOARD_GAP_STOP].open is False


def test_smoke_board_sync_ok(work: Path):
    """CI smoke: board builds + signal is valid + sync path runs."""
    report = asel.smoke_board_sync(
        work,
        fixture=work / "fixtures" / "mine_eval" / "grades_with_claims.json",
        sync_gaps=True,
    )
    assert report["ok"] is True, report
    assert report["signal"] in asel.BOARD_SIGNALS
    assert report["candidates"] >= 1
    assert report["top_repo"]
    assert report.get("sync") is not None
    assert report["sync"].get("ok") is True


def test_decision_for_grade_from_claims_fixture():
    grade = {
        "repo": "wshobson/agents",
        "score": 16.0,
        "idea": 8.0,
        "skill": 8.0,
        "method": "grok:grok-4.5",
        "path": ".nexus_workspaces/mine_eval/wshobson__agents",
        "claims": [
            {
                "statement": "Markdown marketplace",
                "path": "README.md",
            }
        ],
    }
    dec = asel.decision_for_grade(grade)
    assert dec["ok"] is True
    assert dec["candidate"]["repo"] == "wshobson/agents"
    assert dec["evidence_refs"]
    assert dec["action_order"][0]["action"] == "grade"


def test_candidate_from_grade_requires_repo():
    with pytest.raises(asel.ApplySelectError):
        asel.candidate_from_grade({"score": 10})


# ---------------------------------------------------------------------------
# CLI + MCP
# ---------------------------------------------------------------------------


def test_cli_select_and_board(work: Path, capsys):
    from nexus.cli import main

    fx = str(work / "fixtures" / "mine_eval" / "grades_with_claims.json")
    rc = main(
        [
            "improve",
            "select",
            "--path",
            str(work),
            "--fixture",
            fx,
            "--query",
            "Markdown",
            "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["count"] >= 1

    rc = main(
        [
            "improve",
            "board",
            "--path",
            str(work),
            "--fixture",
            fx,
            "--json",
        ]
    )
    assert rc == 0
    board = json.loads(capsys.readouterr().out)
    assert board["schema"] == asel.BOARD_SCHEMA

    rc = main(
        [
            "improve",
            "decide",
            "--path",
            str(work),
            "--fixture",
            fx,
            "--repo",
            "wshobson/agents",
            "--json",
        ]
    )
    assert rc == 0
    dec = json.loads(capsys.readouterr().out)
    assert dec["ok"] is True


def test_mcp_apply_select_and_board(work: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(work))
    tools = {t["name"] for t in mcp_server.TOOLS}
    assert "apply_select" in tools
    assert "improve_board" in tools

    from nexus import evidence_fts as efts

    efts.index_workspace(work)

    out = mcp_server.call_tool(
        "apply_select",
        {"query": "Markdown marketplace", "min_score": 10, "limit": 3},
    )
    assert not out.get("isError")
    text = (out.get("content") or [{}])[0].get("text") or ""
    data = json.loads(text)
    assert data.get("ok") is True
    assert data.get("count", 0) >= 1
    assert any(c.get("repo") == "wshobson/agents" for c in data.get("candidates") or [])

    out2 = mcp_server.call_tool(
        "improve_board",
        {"goal": "mcp board test", "limit": 3},
    )
    assert not out2.get("isError")
    board = json.loads((out2.get("content") or [{}])[0].get("text") or "{}")
    assert board.get("schema") == asel.BOARD_SCHEMA
    assert board.get("ok") is True
