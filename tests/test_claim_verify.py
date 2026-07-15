"""Tests for Thucy-style claim verification (P0.4 / arXiv 2512.03278)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.claim_verify import (
    ClaimVerifyError,
    missing_fields,
    verify_claim,
    verify_or_report,
)


def _good(**overrides):
    base = {
        "repo": "wshobson/agents",
        "score": 16.0,
        "idea": 8.0,
        "skill": 8.0,
        "path": ".nexus_workspaces/mine_eval/wshobson__agents",
        "method": "grok:grok-4.5",
    }
    base.update(overrides)
    return base


def test_verify_passes_complete_grade():
    out = verify_claim(_good())
    assert out["ok"] is True
    assert out["score"] == 16.0
    assert out["idea"] == 8.0
    assert out["skill"] == 8.0
    assert "wshobson" in out["path"]


def test_missing_path_fails():
    with pytest.raises(ClaimVerifyError, match="path"):
        verify_claim(_good(path=""))
    with pytest.raises(ClaimVerifyError, match="missing"):
        g = _good()
        del g["path"]
        verify_claim(g)


def test_missing_score_fails():
    g = _good()
    del g["score"]
    with pytest.raises(ClaimVerifyError, match="score"):
        verify_claim(g)
    assert "score" in missing_fields(g)


def test_non_numeric_score_fails():
    with pytest.raises(ClaimVerifyError, match="score"):
        verify_claim(_good(score="high"))


def test_missing_idea_or_skill_fails():
    for key in ("idea", "skill"):
        g = _good()
        del g[key]
        with pytest.raises(ClaimVerifyError):
            verify_claim(g)


def test_verify_or_report_soft():
    bad = verify_or_report({"repo": "x"})
    assert bad["ok"] is False
    assert bad["missing"]
    good = verify_or_report(_good())
    assert good["ok"] is True


def test_require_path_exists(tmp_path: Path):
    evidence = tmp_path / "evidence" / "repo"
    evidence.mkdir(parents=True)
    rel = "evidence/repo"
    out = verify_claim(
        _good(path=rel),
        workdir=tmp_path,
        require_path_exists=True,
    )
    assert out["ok"] is True
    assert Path(out["resolved_path"]).is_dir()

    with pytest.raises(ClaimVerifyError, match="does not exist"):
        verify_claim(
            _good(path="missing/path"),
            workdir=tmp_path,
            require_path_exists=True,
        )


def test_min_score_gate():
    with pytest.raises(ClaimVerifyError, match="min_score"):
        verify_claim(_good(score=5.0), min_score=10.0)
