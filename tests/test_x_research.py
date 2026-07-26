"""Hermetic tests for mandatory live X research input."""

from __future__ import annotations

from pathlib import Path

from nexus import x_research as xr


def test_record_verified_posts_ledger_dedupe_is_local_only(tmp_path: Path):
    posts = [
        {
            "post_id": "999",
            "author": "bob",
            "text": "coding agents on SWE-bench",
            "url": "https://x.com/bob/status/999",
            "source": "x_api_v2",
        }
    ]
    r1 = xr.record_posts(posts, query="swe", workdir=tmp_path)
    assert r1["added"] == 1
    r2 = xr.record_posts(posts, query="agents", workdir=tmp_path)
    assert r2["updated"] == 1
    assert r2["total"] == 1
    ledger = tmp_path / ".nexus_state" / "x_research" / "x_ledger.csv"
    assert ledger.is_file()
    assert "999" in ledger.read_text()
    assert "verified_x_api" in ledger.read_text()
    assert not (tmp_path / "docs" / "X_LEDGER.csv").exists()


def test_unverified_claimed_id_becomes_local_record(tmp_path: Path):
    posts = [
        {
            "post_id": "FAKE-UNVERIFIED-ID",
            "author": "model_result",
            "text": "unverified discovery",
            "url": "https://x.com/model_result/status/FAKE-UNVERIFIED-ID",
            "source": "grok_x_research_unverified",
        }
    ]
    xr.record_posts(posts, query="agents", workdir=tmp_path)
    text = xr.state_csv_path(tmp_path).read_text(encoding="utf-8")
    assert "local-" in text
    assert "unverified_model_search" in text
    assert ",false," in text
    assert not (tmp_path / "docs" / "X_LEDGER.csv").exists()


def test_public_legacy_ledger_is_never_reingested(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "X_LEDGER.csv").write_text(
        "post_id,author,text\nFAKE-LEGACY-ID,model,unverified\n",
        encoding="utf-8",
    )
    assert xr.load_rows(tmp_path) == []


def test_write_latest_review_is_local_only(tmp_path: Path):
    posts = [
        {
            "post_id": "1",
            "author": "alice",
            "text": "self-improving agents need tests",
            "url": "https://x.com/alice/status/1",
            "source": "x_api_v2",
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
    assert path == tmp_path / ".nexus_state" / "x_research" / "LATEST_X_REVIEW.md"
    assert "Local X research report" in text
    assert "alice" in text
    assert "gate_eligible: True" in text
    assert not (tmp_path / "docs" / "LATEST_X_REVIEW.md").exists()


def test_step_x_review_failure_writes_marker(tmp_path: Path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(xr, "fetch_posts", boom)
    res = xr.step_x_review(
        tmp_path, queries=["test q"], max_results=5, use_grok_themes=False
    )
    assert res["ok"] is False
    assert res["required_on_real"] is True
    assert res["verified"] is False
    assert res["gate_eligible"] is False
    assert Path(res["path"]).is_file()
    assert "FAILED" in Path(res["path"]).read_text()
    assert ".nexus_state" in res["path"]
    assert not (tmp_path / "docs" / "LATEST_X_REVIEW.md").exists()


def test_unverified_search_is_quarantined_and_gate_stays_closed(
    tmp_path: Path, monkeypatch
):
    def fallback(*a, **k):
        return (
            [
                {
                    "post_id": "FAKE-UNVERIFIED-ID",
                    "author": "model_result",
                    "text": "model-mediated discovery",
                    "url": "https://x.com/model_result/status/FAKE-UNVERIFIED-ID",
                }
            ],
            "grok_x_research_unverified",
        )

    monkeypatch.setattr(xr, "fetch_posts", fallback)
    res = xr.step_x_review(
        tmp_path, queries=["test q"], max_results=5, use_grok_themes=False
    )
    assert res["research_ok"] is True
    assert res["ok"] is False
    assert res["verified"] is False
    assert res["gate_eligible"] is False
    assert res["posts"] == 0
    assert res["quarantined_posts"] == 1
    review = Path(res["path"]).read_text(encoding="utf-8")
    assert "Quarantined discoveries" in review
    assert "cannot satisfy the research or publish gate" in review
    assert not (tmp_path / "docs" / "LATEST_X_REVIEW.md").exists()
    assert not (tmp_path / "docs" / "X_LEDGER.csv").exists()


def test_official_api_result_is_gate_eligible(tmp_path: Path, monkeypatch):
    def official(*a, **k):
        return (
            [
                {
                    "post_id": "123",
                    "author": "alice",
                    "text": "direct API result",
                    "url": "https://x.com/alice/status/123",
                }
            ],
            "x_api_v2",
        )

    monkeypatch.setattr(xr, "fetch_posts", official)
    res = xr.step_x_review(
        tmp_path, queries=["test q"], max_results=5, use_grok_themes=False
    )
    assert res["ok"] is True
    assert res["verified"] is True
    assert res["gate_eligible"] is True
    assert res["posts"] == 1
    assert res["quarantined_posts"] == 0


def test_fetch_prefers_official_api_when_bearer_is_available(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "FAKE-TEST-BEARER")
    calls: list[str] = []

    def official(*a, **k):
        calls.append("api")
        return []

    def unexpected_fallback(*a, **k):
        raise AssertionError("Grok fallback must not run after API success")

    monkeypatch.setattr(xr, "search_x_api", official)
    monkeypatch.setattr(xr, "search_via_grok", unexpected_fallback)
    posts, backend = xr.fetch_posts("test q")
    assert posts == []
    assert backend == "x_api_v2"
    assert calls == ["api"]


def test_malformed_official_api_result_cannot_open_gate(
    tmp_path: Path, monkeypatch
):
    def malformed(*a, **k):
        return (
            [
                {
                    "post_id": "123",
                    "author": "alice",
                    "text": "mismatched status URL",
                    "url": "https://x.com/alice/status/456",
                }
            ],
            "x_api_v2",
        )

    monkeypatch.setattr(xr, "fetch_posts", malformed)
    res = xr.step_x_review(
        tmp_path, queries=["test q"], max_results=5, use_grok_themes=False
    )
    assert res["research_ok"] is True
    assert res["ok"] is False
    assert res["verified"] is False
    assert res["gate_eligible"] is False
    assert res["quarantined_posts"] == 1


def test_stable_id_from_text():
    a = xr._stable_id_from_text("hello world", "u")
    b = xr._stable_id_from_text("hello world", "u")
    assert a == b
    assert a.startswith("local-")
