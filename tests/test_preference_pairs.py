"""Offline preference-pair store (arXiv 2602.04518)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus import preference_pairs as pp


def test_record_and_list_pairs(tmp_path: Path):
    row = pp.record_pair(
        tmp_path,
        better="wshobson/agents",
        worse="openai/swarm",
        criterion="score",
        better_score=16.0,
        worse_score=13.0,
        source="test",
    )
    assert row["schema"] == pp.SCHEMA
    assert row["better"] == "wshobson/agents"
    pairs = pp.list_pairs(tmp_path, limit=5)
    assert len(pairs) == 1
    assert pairs[0]["worse"] == "openai/swarm"
    assert pp.pairs_path(tmp_path).is_file()


def test_record_pair_rejects_same_ids(tmp_path: Path):
    with pytest.raises(pp.PreferenceError):
        pp.record_pair(tmp_path, better="a/b", worse="a/b")


def test_record_from_ranked_margin(tmp_path: Path):
    cands = [
        {"repo": "wshobson/agents", "score": 16.0, "rank": 16.5},
        {"repo": "openai/swarm", "score": 13.0, "rank": 13.0},
    ]
    row = pp.record_from_ranked(cands, tmp_path, min_margin=0.5)
    assert row is not None
    assert row["better"] == "wshobson/agents"
    # too-close margin → None
    close = [
        {"repo": "a/b", "score": 10.1},
        {"repo": "c/d", "score": 10.0},
    ]
    assert pp.record_from_ranked(close, tmp_path, min_margin=0.5) is None


def test_preference_boost_and_brief(tmp_path: Path):
    pp.record_pair(tmp_path, better="alpha/x", worse="beta/y", source="t")
    pp.record_pair(tmp_path, better="alpha/x", worse="gamma/z", source="t")
    assert pp.preference_boost("alpha/x", tmp_path) > 0
    assert pp.preference_boost("beta/y", tmp_path) < 0
    brief = pp.preference_brief(tmp_path)
    assert brief["n_pairs"] == 2
    assert brief["leaderboard"][0]["repo"] == "alpha/x"
    text = pp.format_brief(brief)
    assert "preference pairs" in text
    assert "alpha/x" in text


def test_prefer_cli_list_and_record(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from nexus.cli import main

    rc = main(
        [
            "improve",
            "prefer",
            "record",
            "--path",
            str(tmp_path),
            "--better",
            "a/b",
            "--worse",
            "c/d",
        ]
    )
    assert rc == 0
    rc2 = main(["improve", "prefer", "list", "--path", str(tmp_path), "--json"])
    assert rc2 == 0
