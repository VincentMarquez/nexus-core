"""Tests for paper_improve — offline (no network, no LLM)."""

from __future__ import annotations

import json
from pathlib import Path

from nexus import paper_improve as pi


NOTE = """# arXiv improve — demo

## Papers

1. **Multi-Agent Group Review for Code Repair Benchmarks** — `2501.00001v1`
   https://arxiv.org/abs/2501.00001v1
2. **Underwater Basket Weaving with Drones** — `2501.00002v1`
   https://arxiv.org/abs/2501.00002v1
"""


def _write_note(tmp_path: Path) -> Path:
    d = tmp_path / ".nexus_state" / "arxiv_improve"
    d.mkdir(parents=True)
    note = d / "improve-rx-test.md"
    note.write_text(NOTE, encoding="utf-8")
    return note


def test_parse_note_papers(tmp_path: Path):
    note = _write_note(tmp_path)
    papers = pi.parse_note_papers(note)
    assert [p["id"] for p in papers] == ["2501.00001v1", "2501.00002v1"]
    assert papers[0]["title"].startswith("Multi-Agent Group Review")


def test_heuristic_prefers_relevant_paper(tmp_path: Path):
    capsule = pi.repo_capsule(tmp_path)
    relevant = {
        "id": "2501.00001v1",
        "title": "Multi-Agent Group Review for Code Repair Benchmarks",
        "summary": "We improve SWE-bench resolve rate with multi-agent group review, "
        "budget-aware pipelines and self-check gating for code repair.",
    }
    irrelevant = {
        "id": "2501.00002v1",
        "title": "Underwater Basket Weaving with Drones",
        "summary": "Aquatic craft techniques with quadcopters and reeds.",
    }
    s_rel = pi.score_paper_heuristic(relevant, capsule)
    s_irr = pi.score_paper_heuristic(irrelevant, capsule)
    assert s_rel["applicability"] > s_irr["applicability"]
    assert s_rel["method"] == "heuristic"


def test_to_grade_shape():
    g = pi.to_grade(
        {"id": "2501.00001v1", "title": "T"},
        {"applicability": 7.5, "effort": 3, "target_area": "alive",
         "concrete_change": "do X", "rationale": "because", "method": "heuristic"},
    )
    assert g["repo_or_paper_id"] == "arxiv:2501.00001v1"
    assert g["score"] == 7.5
    assert g["skill"] == 7
    assert g["claims"][0]["path"].endswith("2501.00001v1")


def test_step_paper_improve_offline(tmp_path: Path, monkeypatch):
    _write_note(tmp_path)
    # no network: abstracts come back as errors -> heuristic on title only
    monkeypatch.setattr(
        pi, "fetch_abstract",
        lambda root, pid, delay=0: {"id": pid, "error": "offline"},
    )
    res = pi.step_paper_improve(tmp_path, use_llm=False, min_score=99.0)
    assert res["ok"] is True
    assert res["papers"] == 2
    assert res["read"] == 0
    assert res["applicable"] == 0  # min_score forced high
    grades = json.loads(Path(res["grades_path"]).read_text())["grades"]
    assert len(grades) == 2
    assert all(g["repo_or_paper_id"].startswith("arxiv:") for g in grades)
    plan = Path(res["plan"]).read_text()
    assert "PAPER_IMPROVE" in plan and "| rank |" in plan


def test_step_paper_improve_no_note(tmp_path: Path):
    res = pi.step_paper_improve(tmp_path, use_llm=False)
    assert res["ok"] is False
    assert "note" in res["error"]
