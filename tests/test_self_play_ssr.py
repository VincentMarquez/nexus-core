"""Tests for self-play SSR inject→repair (arXiv 2512.18552 × wshobson)."""

from __future__ import annotations

import pytest

from nexus.self_play_ssr import (
    INJECT_CATALOG,
    PLUGIN_CATALOG,
    REPAIR_CATALOG,
    SAMPLE_EXPECTED,
    SAMPLE_PROGRAMS,
    SCHEMA,
    SelfPlayError,
    build_self_play_prompt,
    catalog_self_check,
    complexity_for_round,
    inject_bug,
    list_plugins,
    pick_inject_plugin,
    repair_bug,
    run_self_play,
    run_self_play_or_report,
    self_play_brief,
    validate_plugin_ids,
    verify_source,
)


def test_schema_constant():
    assert SCHEMA == "nexus.self_play_ssr/v1"


def test_catalog_self_check_ok():
    report = catalog_self_check()
    assert report["ok"] is True
    assert report["issues"] == []
    assert report["inject_count"] >= 3
    assert report["repair_count"] >= 3
    assert "inject" in report["surfaces"]
    assert "repair" in report["surfaces"]


def test_list_plugins_filters():
    all_p = list_plugins()
    assert len(all_p) == len(PLUGIN_CATALOG)
    injects = list_plugins(surface="inject", enabled_only=True)
    assert all(p["surface"] == "inject" for p in injects)
    assert all(p["enabled_by_default"] for p in injects)
    easy = list_plugins(surface="inject", max_complexity=1)
    assert all(p["complexity"] <= 1 for p in easy)
    # noop is disabled by default
    enabled = {p["plugin_id"] for p in list_plugins(enabled_only=True)}
    assert "noop" not in enabled
    assert "noop" in REPAIR_CATALOG


def test_validate_plugin_ids():
    assert validate_plugin_ids(["flip_bool_return", "oracle_inverse"]) == []
    assert validate_plugin_ids(["nope_plugin", "flip_bool_return"]) == ["nope_plugin"]
    assert validate_plugin_ids(["", None]) == []  # type: ignore[list-item]


def test_sample_programs_pass_baseline():
    for sid, src in SAMPLE_PROGRAMS.items():
        v = verify_source(src, expected=SAMPLE_EXPECTED[sid])
        assert v["ok"], f"{sid}: {v}"


@pytest.mark.parametrize("inject_id", list(INJECT_CATALOG.keys()))
def test_each_inject_breaks_some_sample(inject_id: str):
    """Every inject plugin must successfully mutate ≥1 sample and break its test."""
    broken = False
    last_err = ""
    for sid, src in SAMPLE_PROGRAMS.items():
        try:
            ep = inject_bug(
                src,
                inject_id,
                sample_id=sid,
                expected=SAMPLE_EXPECTED[sid],
                seed=7,
            )
        except SelfPlayError as exc:
            last_err = str(exc)
            continue
        v = verify_source(ep.buggy_source, expected=ep.expected)
        if not v["ok"]:
            broken = True
            # oracle should repair
            rep = repair_bug(ep, "oracle_inverse")
            assert rep["ok"], f"{inject_id} on {sid}: oracle failed ({rep})"
            break
    assert broken, f"{inject_id} never broke a sample (last={last_err})"


def test_inject_unknown_raises():
    with pytest.raises(SelfPlayError, match="unknown inject"):
        inject_bug(SAMPLE_PROGRAMS["bool_gate"], "not_a_plugin", sample_id="bool_gate")


def test_repair_noop_fails_on_bug():
    ep = inject_bug(
        SAMPLE_PROGRAMS["bool_gate"],
        "flip_bool_return",
        sample_id="bool_gate",
        expected=True,
    )
    rep = repair_bug(ep, "noop")
    assert rep["ok"] is False
    assert rep["repair_plugin"] == "noop"


def test_restore_baseline_repairs():
    ep = inject_bug(
        SAMPLE_PROGRAMS["counter"],
        "off_by_one",
        sample_id="counter",
        expected=3,
    )
    assert not verify_source(ep.buggy_source, expected=3)["ok"]
    rep = repair_bug(ep, "restore_baseline")
    assert rep["ok"] is True
    assert rep["restored_baseline"] is True


def test_heuristic_scan_repairs_common_bugs():
    ep = inject_bug(
        SAMPLE_PROGRAMS["equality"],
        "break_equality",
        sample_id="equality",
        expected=1,
    )
    rep = repair_bug(ep, "heuristic_scan")
    assert rep["ok"] is True


def test_complexity_ramp():
    assert complexity_for_round(0, 3) == 1
    assert complexity_for_round(1, 3) == 2
    assert complexity_for_round(2, 3) == 3
    assert complexity_for_round(0, 1) == 1


def test_run_self_play_oracle_green():
    report = run_self_play(
        max_rounds=3,
        seed=42,
        repair_plugin="oracle_inverse",
    )
    assert report["schema"] == SCHEMA
    assert report["rounds_completed"] >= 1
    assert report["rounds_repaired"] == report["rounds_completed"]
    assert report["mean_reward"] > 0
    assert report["ok"] is True
    assert report["catalog"]["ok"] is True
    for rnd in report["rounds"]:
        assert rnd["ok"] is True
        assert rnd["reward"] >= 0.5
        assert rnd["episode"]["inject_plugin"] in INJECT_CATALOG


def test_run_self_play_noop_not_all_repaired():
    report = run_self_play(
        max_rounds=2,
        seed=1,
        repair_plugin="noop",
        require_inject_fails=True,
    )
    assert report["rounds_completed"] >= 1
    assert report["rounds_repaired"] == 0
    assert report["ok"] is False
    assert report["mean_reward"] == 0.0


def test_run_self_play_or_report_soft():
    bad = run_self_play_or_report(max_rounds=0)
    assert bad["ok"] is False
    assert bad["error"]
    good = run_self_play_or_report(max_rounds=1, seed=0)
    assert good["rounds_completed"] >= 1


def test_custom_sources():
    src = "x = 1\nresult = x + 1\n"
    report = run_self_play(
        max_rounds=1,
        seed=3,
        sample_ids=["tiny"],
        sources={"tiny": src},
        expected_map={"tiny": 2},
        repair_plugin="oracle_inverse",
    )
    assert report["rounds_completed"] == 1
    assert report["rounds_repaired"] == 1


def test_build_self_play_prompt_contains_marketplace(tmp_path):
    prompt = build_self_play_prompt(tmp_path, max_rounds=2, goal_extra="Focus on unit tests.")
    assert "self-play" in prompt.lower() or "Self-play" in prompt
    assert "flip_bool_return" in prompt
    assert "oracle_inverse" in prompt
    assert "2512.18552" in prompt
    assert "Focus on unit tests" in prompt
    assert str(tmp_path.resolve()) in prompt


def test_self_play_brief():
    brief = self_play_brief(max_rounds=2, seed=0)
    assert brief["schema"] == SCHEMA
    assert brief["catalog_ok"] is True
    assert brief["dry_run"]["rounds_completed"] >= 1
    assert isinstance(brief["plugins"], list)
    assert len(brief["plugins"]) >= 4


def test_grok_worker_offline_hook(tmp_path):
    from nexus.grok_worker import grok_self_play_ssr

    out = grok_self_play_ssr(tmp_path, max_rounds=2, offline_only=True)
    assert out["schema"] == SCHEMA
    assert out["mode"] == "offline"
    assert out["offline"]["rounds_completed"] >= 1
    assert out["offline_ok"] is True
    assert out["ok"] is True
    assert out["agentic"] is None
    assert out["agentic_ok"] is None


# ── Synthesis regressions (panel critiques) ────────────────────────────────


def test_position_anchor_off_by_one_does_not_corrupt_identifier():
    """Inject must edit the matched literal span, not the first substring hit."""
    src = "a2b = 2\nresult = a2b\n"
    ep = inject_bug(src, "off_by_one", sample_id="custom", expected=2, seed=1)
    # Matched word-boundary literal is the standalone `2`, not the `2` inside `a2b`.
    assert "a2b = 3" in ep.buggy_source or ep.buggy_source.startswith("a2b = 3")
    assert "a3b" not in ep.buggy_source
    assert "literal 2 → 3" in ep.mutation_note
    # Oracle restores via position hint.
    rep = repair_bug(ep, "oracle_inverse")
    assert rep["ok"] is True
    assert rep["repaired_source"] == src or verify_source(rep["repaired_source"], expected=2)["ok"]


def test_oracle_multi_operator_equality_round_trips():
    """Oracle must restore the matched comparison span when multiple ops exist.

    Classic F1 repro: source has `!=` *before* the `==` that inject flips. An
    unanchored ``str.replace(" != ", …)`` would invert the wrong operator.
    """
    src = (
        "def f(a, b, c):\n"
        "    if a != b:\n"
        "        return 0\n"
        "    if a == c:\n"
        "        return 1\n"
        "    return 2\n"
        "\n"
        "result = f(3, 3, 3)\n"
    )
    # baseline: a==b so skip first; a==c → return 1
    assert verify_source(src, expected=1)["ok"]
    ep = inject_bug(src, "break_equality", sample_id="custom", expected=1, seed=0)
    # Inject flips first ` == ` (a == c) → a != c → return 2
    assert not verify_source(ep.buggy_source, expected=1)["ok"]
    assert ep.inverse_hint.startswith("pos:")
    rep = repair_bug(ep, "oracle_inverse")
    assert rep["ok"] is True
    assert verify_source(rep["repaired_source"], expected=1)["ok"]
    assert rep["restored_baseline"] is True


def test_oracle_fallback_when_hint_broken():
    """Broken inverse hint must fall back to baseline restore (oracle infallible)."""
    ep = inject_bug(
        SAMPLE_PROGRAMS["equality"],
        "break_equality",
        sample_id="equality",
        expected=1,
    )
    ep.inverse_hint = "pos:0:3:3:XXX"  # nonsense span
    rep = repair_bug(ep, "oracle_inverse")
    assert rep["ok"] is True
    assert rep["restored_baseline"] is True
    assert "fallback" in rep["note"]


def test_verify_source_timeout_and_systemexit():
    hung = verify_source("while True:\n    pass\n", expected=None, timeout_s=0.2)
    assert hung["ok"] is False
    assert "timeout" in (hung["error"] or "")

    exited = verify_source("raise SystemExit(7)\n", expected=0, timeout_s=1.0)
    assert exited["ok"] is False
    assert "SystemExit" in (exited["error"] or "")


def test_verify_source_blocks_import():
    bad = verify_source("import os\nresult = 1\n", expected=1, timeout_s=1.0)
    assert bad["ok"] is False


def test_run_self_play_rejects_inject_as_repair():
    with pytest.raises(SelfPlayError, match="not a repair surface"):
        run_self_play(max_rounds=1, repair_plugin="off_by_one")
    soft = run_self_play_or_report(max_rounds=1, repair_plugin="off_by_one")
    assert soft["ok"] is False
    assert soft["error"]
    blank = run_self_play_or_report(max_rounds=1, repair_plugin="")
    assert blank["ok"] is False


def test_self_play_brief_reuses_report():
    offline = run_self_play(max_rounds=1, seed=0, repair_plugin="oracle_inverse")
    brief = self_play_brief(max_rounds=1, report=offline)
    assert brief["dry_run"]["rounds_completed"] == offline["rounds_completed"]
    assert brief["dry_run"]["ok"] == offline["ok"]


def test_pick_inject_prefers_highest_complexity_under_cap():
    # named prefs: typo_name (3), off_by_one (1) — at cap=3 should pick typo_name
    pid = pick_inject_plugin("named", complexity_cap=3, seed=0, round_index=0)
    assert pid == "typo_name"
    # at cap=1 only off_by_one from prefs fits
    pid_easy = pick_inject_plugin("named", complexity_cap=1, seed=0, round_index=0)
    assert pid_easy == "off_by_one"
    assert INJECT_CATALOG[pid_easy].complexity <= 1


def test_inject_expected_none_is_legitimate():
    src = "value = None\nresult = value\n"
    ep = inject_bug(src, "typo_name", sample_id="custom", expected=None, seed=1)
    assert ep.expected is None
    assert ep.buggy_source != src
    assert not verify_source(ep.buggy_source, expected=None)["ok"]


def test_grok_worker_agentic_ok_reflects_failure(tmp_path, monkeypatch):
    from nexus import grok_worker

    monkeypatch.setattr(grok_worker, "grok_available", lambda: True)
    monkeypatch.setattr(
        grok_worker,
        "grok_prompt",
        lambda *a, **k: {
            "ok": False,
            "returncode": 1,
            "text": "failed agentic run",
            "error": "timeout",
            "model": "test",
        },
    )
    monkeypatch.setattr(grok_worker, "_git_porcelain", lambda wd: [])
    out = grok_worker.grok_self_play_ssr(tmp_path, max_rounds=2)
    assert out["mode"] == "agentic"
    assert out["offline_ok"] is True
    assert out["agentic_ok"] is False
    assert out["ok"] is False
    assert out["agentic"]["text_head"]
    assert out["agentic"]["text_len"] > 0


def test_grok_worker_agentic_dirty_fails(tmp_path, monkeypatch):
    from nexus import grok_worker

    monkeypatch.setattr(grok_worker, "grok_available", lambda: True)
    monkeypatch.setattr(
        grok_worker,
        "grok_prompt",
        lambda *a, **k: {
            "ok": True,
            "returncode": 0,
            "text": "round summary reward=1.0",
            "error": None,
            "model": "test",
        },
    )
    monkeypatch.setattr(
        grok_worker, "_git_porcelain", lambda wd: [" M src/nexus/foo.py"]
    )
    out = grok_worker.grok_self_play_ssr(tmp_path, max_rounds=1)
    assert out["mode"] == "agentic"
    assert out["agentic"]["ok"] is True
    assert out["agentic"]["clean"] is False
    assert out["agentic_ok"] is False
    assert out["ok"] is False
    assert out["agentic"]["dirty_files"]


def test_grok_worker_clamps_max_rounds(tmp_path):
    from nexus.grok_worker import grok_self_play_ssr

    out = grok_self_play_ssr(tmp_path, max_rounds=0, offline_only=True)
    assert out["max_rounds"] == 1
    assert out["mode"] == "offline"
    # soft path — no raise
    assert "offline" in out
