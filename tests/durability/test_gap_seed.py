"""Tests for P1.5 gap-board auto-seed from improve plans."""

from __future__ import annotations

from pathlib import Path

from nexus.durability import (
    PrincipledStop,
    StopPolicy,
    board_snapshot,
    collect_plan_gaps,
    parse_plan_gaps,
    seed_gap_board,
)
from nexus.durability.gap_seed import parse_next_open_gaps, parse_status_table_gaps
from nexus import alive as al


PLAN_FIXTURE = """# Latest improve plan

## Status snapshot

| Tier | Item | Status |
|------|------|--------|
| P0 | Improve-apply phase FSM | **done** |
| P1.4 | Formal context pack | **done this session** |
| P1.5+ | Vault / supervised alive | open |
| P2 | Packaging / OpenAPI | later |

## Next open (after this slice)

1. **P1.5** Secrets vault / supervised alive stop board auto-seed
2. Modularize MCP domains + eval CLI (AssetOpsBench)
3. Packaging / OpenAPI (P2)
"""


def test_parse_status_table_open_and_done():
    rows = parse_status_table_gaps(PLAN_FIXTURE)
    by_id = {r["id"]: r for r in rows}
    assert "P0" in by_id
    assert by_id["P0"]["open"] is False
    assert by_id["P1.4"]["open"] is False
    assert by_id["P1.5"]["open"] is True  # P1.5+ normalized
    assert by_id["P2"]["open"] is True  # later → open


def test_parse_next_open_numbered():
    gaps = parse_next_open_gaps(PLAN_FIXTURE)
    ids = [g["id"] for g in gaps]
    assert "P1.5" in ids
    # non-id bullet becomes open-N
    assert any(i.startswith("open-") for i in ids) or "P2" in ids


def test_parse_inline_next_open():
    text = (
        "- next open: P1.5 vault / supervised alive · "
        "AssetOpsBench domain MCP · packaging/OpenAPI"
    )
    gaps = parse_next_open_gaps(text)
    ids = {g["id"] for g in gaps}
    assert "P1.5" in ids
    assert len(gaps) >= 2


def test_seed_preserves_closed_gaps(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "LATEST_IMPROVE_PLAN.md").write_text(PLAN_FIXTURE, encoding="utf-8")
    stopper = PrincipledStop(policy=StopPolicy(max_no_progress=99))
    # pre-close P1.5 as if operator finished it
    stopper.register_gap("P1.5", "vault")
    stopper.close_gap("P1.5", evidence="already landed")
    info = seed_gap_board(stopper, tmp_path, reopen_closed=False)
    assert stopper.gaps["P1.5"].open is False
    assert "P1.5" in info["skipped"] or "P1.5" not in info["registered"]
    # open plan gaps still registered
    assert any(g.open for g in stopper.gaps.values())


def test_seed_close_done_from_plan(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "LATEST_IMPROVE_PLAN.md").write_text(PLAN_FIXTURE, encoding="utf-8")
    stopper = PrincipledStop()
    stopper.register_gap("P0", "old open even though plan says done")
    info = seed_gap_board(stopper, tmp_path, close_done=True)
    assert stopper.gaps["P0"].open is False
    assert "P0" in info["closed"]


def test_collect_and_snapshot(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "LATEST_IMPROVE_PLAN.md").write_text(PLAN_FIXTURE, encoding="utf-8")
    items = collect_plan_gaps(tmp_path)
    assert any(i["id"] == "P1.5" for i in items)
    s = PrincipledStop()
    seed_gap_board(s, tmp_path)
    snap = board_snapshot(s)
    assert snap["counts"]["open"] >= 1
    assert snap["schema"] == "nexus.gap_seed/v1"


def test_alive_seed_gaps_helper(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "LATEST_IMPROVE_PLAN.md").write_text(PLAN_FIXTURE, encoding="utf-8")
    cfg = al.AliveConfig(goal="g", enabled=True, seed_gaps=True)
    al.save_config(cfg, tmp_path)
    out = al.seed_gaps(tmp_path)
    assert out["n_plan"] >= 1
    assert out["board"]["open"] >= 1
    board = al.gap_board(tmp_path)
    assert board["counts"]["open"] >= 1
    # close via helper
    open_id = board["open"][0]["id"]
    closed = al.close_gap(open_id, tmp_path, evidence="test")
    assert closed["closed"]["open"] is False


def test_record_principled_stop_auto_seeds(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "LATEST_IMPROVE_PLAN.md").write_text(PLAN_FIXTURE, encoding="utf-8")
    cfg = al.AliveConfig(goal="g", enabled=True, seed_gaps=True, stop_max_no_progress=99)
    al.save_config(cfg, tmp_path)
    rep = {"steps": [{"step": "mine", "used": 0}], "goal": "g"}
    dec = al._record_principled_stop(tmp_path, cfg, rep, checks={"ok": True})
    assert dec["stop"] is False
    assert dec.get("gap_seed")
    assert dec["gap_seed"]["board"]["open"] >= 1
    board = al.gap_board(tmp_path)
    assert board["counts"]["total"] >= 1


def test_parse_plan_gaps_combined():
    gaps = parse_plan_gaps(PLAN_FIXTURE)
    ids = {g["id"] for g in gaps}
    assert "P1.5" in ids
    assert "P0" in ids
