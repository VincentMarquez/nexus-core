"""Tests for plan-reuse cache (multi-stage workflow reuse)."""

from __future__ import annotations

from pathlib import Path

from nexus import plan_reuse as pr


def test_plan_key_stable_and_score_band():
    a = pr.plan_key(repo="wshobson/agents", pattern="markdown-skill-sot-validator", score=16.0, method="grok:grok-4.5")
    b = pr.plan_key(repo="wshobson/agents", pattern="markdown-skill-sot-validator", score=16.4, method="grok:grok-4.5")
    c = pr.plan_key(repo="wshobson/agents", pattern="markdown-skill-sot-validator", score=15.0, method="grok:grok-4.5")
    assert a == b  # same 1.0 band (16.x)
    assert a != c
    assert len(a) == 32


def test_store_lookup_roundtrip(tmp_path: Path):
    key = pr.plan_key(repo="wshobson/agents", pattern="p1", score=16.0, method="m")
    assert pr.lookup(tmp_path, key=key) is None
    ent = pr.store_plan(
        tmp_path,
        key=key,
        repo="wshobson/agents",
        pattern="p1",
        score=16.0,
        method="m",
        summary={"ok": True, "files": ["skillpacks/x/SKILL.md"], "verify_ok": True},
    )
    assert ent["stored"] is True
    hit = pr.lookup(tmp_path, key=key)
    assert hit is not None
    assert hit["cache_hit"] is True
    assert hit["summary"]["verify_ok"] is True
    st = pr.stats(tmp_path)
    assert st["count"] == 1
    assert "wshobson/agents" in st["repos"]


def test_get_or_compute_caches_success_only(tmp_path: Path):
    calls = {"n": 0}

    def fail():
        calls["n"] += 1
        return {"ok": False, "error": "boom"}

    r1 = pr.get_or_compute(
        tmp_path,
        repo="x/y",
        pattern="p",
        score=10,
        method="m",
        compute=fail,
    )
    assert r1["cache_hit"] is False
    assert r1.get("stored") is False
    assert calls["n"] == 1

    r2 = pr.get_or_compute(
        tmp_path,
        repo="x/y",
        pattern="p",
        score=10,
        method="m",
        compute=fail,
    )
    # failure not cached → compute again
    assert r2["cache_hit"] is False
    assert calls["n"] == 2

    def ok():
        calls["n"] += 1
        return {
            "ok": True,
            "pattern": "p",
            "run_id": "r1",
            "apply": {"files_written": ["a"]},
            "verify": {"ok": True},
        }

    r3 = pr.get_or_compute(
        tmp_path,
        repo="x/y",
        pattern="p",
        score=10,
        method="m",
        compute=ok,
    )
    assert r3["cache_hit"] is False
    assert r3.get("stored") is True
    assert calls["n"] == 3

    r4 = pr.get_or_compute(
        tmp_path,
        repo="x/y",
        pattern="p",
        score=10,
        method="m",
        compute=ok,
    )
    assert r4["cache_hit"] is True
    assert calls["n"] == 3  # no recompute
    assert r4["result"]["ok"] is True
