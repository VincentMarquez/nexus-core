"""Hermetic tests for mandatory live X research input."""

from __future__ import annotations

from pathlib import Path

from nexus import x_research as xr


def test_record_posts_ledger_dedupe(tmp_path: Path):
    posts = [
        {
            "post_id": "999",
            "author": "bob",
            "text": "coding agents on SWE-bench",
            "url": "https://x.com/bob/status/999",
            "source": "test",
        }
    ]
    r1 = xr.record_posts(posts, query="swe", workdir=tmp_path)
    assert r1["added"] == 1
    r2 = xr.record_posts(posts, query="agents", workdir=tmp_path)
    assert r2["updated"] == 1
    assert r2["total"] == 1
    assert (tmp_path / "docs" / "X_LEDGER.csv").is_file()
    assert "999" in (tmp_path / "docs" / "X_LEDGER.csv").read_text()


def test_write_latest_review(tmp_path: Path):
    posts = [
        {
            "post_id": "1",
            "author": "alice",
            "text": "self-improving agents need tests",
            "url": "https://x.com/alice/status/1",
        }
    ]
    path = xr.write_latest_review(
        tmp_path,
        queries=["self-improve"],
        posts=posts,
        backend="test",
        ledger={"added": 1, "updated": 0, "total": 1},
        themes="- tests matter",
    )
    text = path.read_text(encoding="utf-8")
    assert "Live X research" in text
    assert "alice" in text
    assert "mandatory" in text.lower()


def test_step_x_review_failure_writes_marker(tmp_path: Path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(xr, "fetch_posts", boom)
    res = xr.step_x_review(tmp_path, queries=["test q"], max_results=5, use_grok_themes=False)
    assert res["ok"] is False
    assert res["required_on_real"] is True
    assert Path(res["path"]).is_file()
    assert "FAILED" in Path(res["path"]).read_text()


def test_stable_id_from_text():
    a = xr._stable_id_from_text("hello world", "u")
    b = xr._stable_id_from_text("hello world", "u")
    assert a == b
    assert a.startswith("x")
