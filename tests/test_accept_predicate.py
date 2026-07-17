"""S05 accept predicate tests."""

from __future__ import annotations

from pathlib import Path

from nexus import accept_predicate as ap
from nexus.alive import AliveConfig


def test_worker_not_ok_rejects():
    out = ap.evaluate_accept(".", {"ok": False, "id": "x"}, soft=True)
    assert out["accept"] is False
    assert "worker_not_ok" in out["reasons"]
    assert out["soft"] is True


def test_worker_ok_accepts_without_files():
    out = ap.evaluate_accept(".", {"ok": True, "id": "x"}, soft=True)
    assert out["accept"] is True
    assert "worker_ok" in out["reasons"]


def test_forbidden_path_rejects(tmp_path: Path):
    from nexus import scope_contract as sc

    c = sc.default_contract({"id": "a"})
    out = ap.evaluate_accept(
        tmp_path,
        {"ok": True},
        scope_contract=c,
        slice_files=[".nexus_state/secret.json"],
        soft=True,
    )
    assert out["accept"] is False
    assert "forbidden_path_hit" in out["reasons"]


def test_py_compile_ok(tmp_path: Path):
    src = tmp_path / "src" / "nexus"
    src.mkdir(parents=True)
    f = src / "mod.py"
    f.write_text("x = 1\n", encoding="utf-8")
    out = ap.evaluate_accept(
        tmp_path,
        {"ok": True},
        slice_files=["src/nexus/mod.py"],
        soft=True,
    )
    assert out["accept"] is True
    assert "py_compile_ok" in out["reasons"]


def test_summarize_accepts():
    results = [
        {"accept_predicate": {"accept": True}},
        {"accept_predicate": {"accept": False}},
        {},
    ]
    s = ap.summarize_accepts(results)
    assert s["evaluated"] == 2
    assert s["accepted"] == 1
    assert s["rejected"] == 1


def test_alive_config_defaults():
    cfg = AliveConfig.from_dict({})
    assert cfg.accept_predicate_enable is True
    assert cfg.cross_run_lessons_enable is True
