"""arXiv CSV ledger — skip papers already seen."""

from __future__ import annotations

from pathlib import Path

from nexus import arxiv_client
from nexus import arxiv_ledger as al


def _paper(aid: str, title: str = "T") -> arxiv_client.Paper:
    return arxiv_client.Paper(
        arxiv_id=aid,
        title=title,
        summary="abstract",
        abs_url=f"https://arxiv.org/abs/{aid}",
    )


def test_record_and_seen(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "docs").mkdir()
    (tmp_path / ".nexus_state").mkdir()

    rec = al.record_papers(
        [_paper("2203.08975v2", "Comm survey"), _paper("2401.07324v3", "Multi-LLM")],
        query="multi agent",
        notes_path="notes.md",
        workdir=tmp_path,
    )
    assert rec["added"] == 2
    assert rec["total"] == 2
    assert (tmp_path / "docs" / "ARXIV_LEDGER.csv").is_file()
    assert (tmp_path / "docs" / "ARXIV_LEDGER.md").is_file()

    seen = al.seen_ids(tmp_path)
    # version stripped
    assert "2203.08975" in seen
    assert "2401.07324" in seen

    # second record bumps times_seen, no new id
    rec2 = al.record_papers([_paper("2203.08975v1")], query="again", workdir=tmp_path)
    assert rec2["added"] == 0
    assert rec2["updated"] == 1
    assert rec2["total"] == 2


def test_filter_new(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "docs").mkdir()
    al.record_papers([_paper("1111.11111")], workdir=tmp_path)
    papers = [_paper("1111.11111"), _paper("2222.22222"), _paper("3333.33333")]
    fresh, old = al.filter_new(papers, tmp_path)
    assert [p.arxiv_id for p in fresh] == ["2222.22222", "3333.33333"]
    assert [p.arxiv_id for p in old] == ["1111.11111"]


def test_canon_strips_version():
    assert al._canon_id("https://arxiv.org/abs/2203.08975v2") == "2203.08975"
    assert al._canon_id("arXiv:2401.07324v3") == "2401.07324"
