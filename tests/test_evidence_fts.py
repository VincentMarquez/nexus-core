"""First apply slice: grade claims + MCP FTS evidence index (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import evidence_fts as efts
from nexus import grade_artifact as ga
from nexus import mcp_server


ROOT = Path(__file__).resolve().parents[1]
CLAIMS_FIXTURE = ROOT / "fixtures" / "mine_eval" / "grades_with_claims.json"


# ---------------------------------------------------------------------------
# Grade schema: claims + ranges
# ---------------------------------------------------------------------------


def test_validate_grade_requires_claims_when_asked():
    bare = {
        "repo": "a/b",
        "score": 12.0,
        "idea": 6.0,
        "skill": 6.0,
        "method": "grok:grok-4.5",
        "path": ".nexus_workspaces/mine_eval/a__b",
    }
    # backward compatible without require_claims
    g = ga.validate_grade(bare, require_path=True, require_claims=False)
    assert "claims" not in g or g.get("claims") == []
    with pytest.raises(ga.GradeValidationError, match="claims"):
        ga.validate_grade(bare, require_path=True, require_claims=True)


def test_validate_grade_rejects_out_of_range_scores():
    with pytest.raises(ga.GradeValidationError, match="out of range"):
        ga.validate_grade(
            {
                "repo": "a/b",
                "score": 99.0,
                "idea": 6.0,
                "skill": 6.0,
                "method": "m",
                "path": "p",
            }
        )
    with pytest.raises(ga.GradeValidationError, match="out of range"):
        ga.validate_grade(
            {
                "repo": "a/b",
                "score": 10.0,
                "idea": 11.0,
                "skill": 5.0,
                "method": "m",
                "path": "p",
            }
        )


def test_validate_claim_shape():
    c = ga.validate_claim(
        {
            "statement": "Markdown marketplace",
            "path": "README.md",
            "quote": "single Markdown source",
        }
    )
    assert c["statement"].startswith("Markdown")
    assert c["path"] == "README.md"
    assert "single" in c["quote"]
    with pytest.raises(ga.GradeValidationError, match="statement"):
        ga.validate_claim({"path": "x"})


def test_grade_with_claims_roundtrip(tmp_path: Path):
    g = ga.build_grade(
        repo="wshobson/agents",
        score=16.0,
        idea=8.0,
        skill=8.0,
        path=str(tmp_path / "w"),
        claims=[
            {
                "statement": "Markdown marketplace for agents/skills",
                "path": "README.md",
                "quote": "single Markdown source",
            }
        ],
    )
    path = tmp_path / "grade.json"
    ga.write_grade(path, ga.validate_grade(g, require_claims=True))
    loaded = ga.load_grade(path)
    assert loaded["score"] == 16.0
    assert len(loaded["claims"]) == 1
    assert "Markdown" in loaded["claims"][0]["statement"]


# ---------------------------------------------------------------------------
# Fixtures + grade-validate
# ---------------------------------------------------------------------------


def test_claims_fixture_exists_and_validates():
    assert CLAIMS_FIXTURE.is_file()
    rep = efts.grade_validate_fixtures(ROOT, require_claims=True)
    assert rep["ok"] is True, rep.get("errors")
    assert rep["checked"] >= 3  # 2 grades + research claims
    repos = {g.get("repo") for g in rep["grades"] if g.get("repo")}
    assert "wshobson/agents" in repos


def test_grade_validate_fails_on_bad_fixture(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "grades": [
                    {
                        "repo": "x/y",
                        "score": 50.0,  # out of range
                        "idea": 5.0,
                        "skill": 5.0,
                        "method": "m",
                        "path": "p",
                        "claims": [{"statement": "s", "path": "p"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rep = efts.grade_validate_fixtures(
        tmp_path, fixture_paths=[bad], require_claims=True
    )
    assert rep["ok"] is False
    assert any("out of range" in e for e in rep["errors"])


# ---------------------------------------------------------------------------
# FTS index + search
# ---------------------------------------------------------------------------


def test_index_and_search_marketplace_and_decision_package(tmp_path: Path):
    # copy claims fixture into isolated workdir
    dest = tmp_path / "fixtures" / "mine_eval"
    dest.mkdir(parents=True)
    (dest / "grades_with_claims.json").write_text(
        CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    rep = efts.index_workspace(tmp_path, include_improve_ours=False)
    assert rep["ok"] is True
    assert rep["docs"] >= 3
    assert rep["grades_indexed"] >= 2
    assert rep["papers_indexed"] >= 1

    m = efts.search_evidence("Markdown marketplace", workdir=tmp_path, k=5)
    assert m["count"] >= 1
    blob = json.dumps(m["hits"]).lower()
    assert "wshobson" in blob or "markdown" in blob

    d = efts.search_evidence(
        "deterministic decision package", workdir=tmp_path, k=5
    )
    assert d["count"] >= 1
    blob2 = json.dumps(d["hits"]).lower()
    assert "2511.15755" in blob2 or "decision package" in blob2


def test_smoke_search_pass_criteria():
    """Project-level smoke: both pass-criteria queries must hit fixtures."""
    rep = efts.smoke_search(ROOT)
    assert rep["ok"] is True, rep
    qs = {s["query"]: s for s in rep["searches"]}
    assert qs["Markdown marketplace"]["ok"] is True
    assert qs["deterministic decision package"]["ok"] is True


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_mcp_index_and_search_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dest = tmp_path / "fixtures" / "mine_eval"
    dest.mkdir(parents=True)
    (dest / "grades_with_claims.json").write_text(
        CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    names = {t["name"] for t in mcp_server.TOOLS}
    assert "index_workspace" in names
    assert "search_evidence" in names

    idx = mcp_server.call_tool("index_workspace", {"clear": True})
    assert idx.get("isError") is not True
    body = json.loads(idx["content"][0]["text"])
    assert body.get("ok") is True
    assert body.get("docs", 0) >= 3

    search = mcp_server.call_tool(
        "search_evidence",
        {"query": "Markdown marketplace", "k": 5, "auto_index": False},
    )
    assert search.get("isError") is not True
    sbody = json.loads(search["content"][0]["text"])
    assert sbody["count"] >= 1
