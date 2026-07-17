"""S07 cross-run lessons tests."""

from __future__ import annotations

from pathlib import Path

from nexus import cross_run_lessons as crl
from nexus.alive import AliveConfig


def test_append_load_format(tmp_path: Path):
    crl.append_lesson(
        tmp_path,
        code="panel_timeout_or_offline",
        text="Claude/GPT timed out at 360s",
        severity="med",
        cycle_id="c1",
    )
    crl.append_lesson(
        tmp_path,
        code="implement_failed",
        text="idea X failed",
        severity="high",
        cycle_id="c1",
    )
    rows = crl.load_lessons(tmp_path, limit=10)
    assert len(rows) >= 2
    block = crl.format_lessons_block(rows, limit=5)
    assert "Cross-run lessons" in block
    assert "panel_timeout" in block or "implement_failed" in block


def test_harvest_from_report(tmp_path: Path):
    report = {
        "steps": [
            {"step": "x_live_input", "ok": False, "error": "no posts"},
            {
                "step": "implement",
                "results": [
                    {
                        "id": "wshobson/agents",
                        "ok": True,
                        "panel_critique": {"status": "panel_round1_failed"},
                        "accept_predicate": {
                            "accept": False,
                            "reasons": ["forbidden_path_hit"],
                        },
                    },
                    {"id": "arxiv:1", "ok": False, "error": "boom"},
                ],
            },
            {"step": "publish_github", "skipped": "tests not green"},
        ]
    }
    out = crl.harvest_lessons_from_report(tmp_path, report, cycle_id="cyc")
    assert out["ok"] is True
    assert out["written"] >= 3
    codes = set(out["codes"])
    assert "x_research_failed" in codes or "panel_timeout_or_offline" in codes


def test_inject_into_dual_brief():
    body = "\n".join(
        [
            "# Research brief",
            "",
            "Goal: x",
            "",
            "## 1. GitHub high-star review",
            "",
            "gh",
            "",
        ]
    )
    block = crl.format_lessons_block(
        [{"code": "engine_failed_open", "text": "engine flaked", "severity": "high"}]
    )
    out = crl.inject_into_dual_brief(body, block)
    assert "Cross-run lessons" in out
    assert out.index("Cross-run lessons") < out.index("## 1. GitHub")
    # idempotent
    out2 = crl.inject_into_dual_brief(out, block)
    assert out2.count("Cross-run lessons") == 1


def test_dedupe_load(tmp_path: Path):
    for _ in range(3):
        crl.append_lesson(
            tmp_path, code="same", text="same text", severity="low", cycle_id="c"
        )
    rows = crl.load_lessons(tmp_path, limit=10)
    assert sum(1 for r in rows if r.get("code") == "same") == 1


def test_config_disable_roundtrip():
    cfg = AliveConfig.from_dict({"cross_run_lessons_enable": False})
    assert cfg.cross_run_lessons_enable is False
