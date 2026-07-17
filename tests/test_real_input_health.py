"""S08 real input soft publish gate."""

from __future__ import annotations

from nexus.alive import AliveConfig, _real_input_health


def test_health_ok_when_both_pass():
    cfg = AliveConfig()
    report = {
        "steps": [
            {"step": "x_live_input", "ok": True},
            {"step": "canonical_engine", "ok": True},
        ]
    }
    h = _real_input_health(report, cfg)
    assert h["x_ok"] is True
    assert h["engine_ok"] is True
    assert h["publish_allowed"] is True


def test_health_blocks_publish_on_x_fail():
    cfg = AliveConfig(real_gate_publish=True, real_gate_override=False)
    report = {
        "steps": [
            {"step": "x_live_input", "ok": False, "error": "no posts"},
            {"step": "canonical_engine", "ok": True},
        ]
    }
    h = _real_input_health(report, cfg)
    assert h["x_ok"] is False
    assert h["publish_allowed"] is False


def test_health_blocks_publish_on_engine_fail():
    cfg = AliveConfig(real_gate_publish=True)
    report = {
        "steps": [
            {"step": "x_live_input", "ok": True},
            {"step": "canonical_engine", "error": "boom"},
        ]
    }
    h = _real_input_health(report, cfg)
    assert h["engine_ok"] is False
    assert h["publish_allowed"] is False


def test_override_allows_publish():
    cfg = AliveConfig(real_gate_publish=True, real_gate_override=True)
    report = {
        "steps": [
            {"step": "x_live_input", "ok": False},
            {"step": "canonical_engine", "ok": False},
        ]
    }
    h = _real_input_health(report, cfg)
    assert h["publish_allowed"] is True
    assert h["override"] is True


def test_gate_off_allows_publish():
    cfg = AliveConfig(real_gate_publish=False)
    report = {
        "steps": [
            {"step": "x_live_input", "ok": False},
            {"step": "canonical_engine", "ok": False},
        ]
    }
    h = _real_input_health(report, cfg)
    assert h["publish_allowed"] is True


def test_x_disabled_skips_x_requirement():
    cfg = AliveConfig(x_review=False)
    report = {"steps": [{"step": "canonical_engine", "ok": True}]}
    h = _real_input_health(report, cfg)
    assert h["x_ok"] is True
    assert h["x_note"] == "x_review_disabled"


def test_config_roundtrip():
    cfg = AliveConfig.from_dict(
        {"real_gate_publish": False, "real_gate_override": True}
    )
    assert cfg.real_gate_publish is False
    assert cfg.real_gate_override is True
