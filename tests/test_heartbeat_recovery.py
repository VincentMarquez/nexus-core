import json
from pathlib import Path

from nexus import heartbeat as hb
from nexus import recovery as rec


def test_probe_network_shape():
    n = hb.probe_network()
    assert "online" in n and "checks" in n
    assert isinstance(n["checks"], list)


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = hb.init_config("https://hc-ping.com/test-uuid", tmp_path, host_id="lab1")
    assert p.is_file()
    cfg = hb.load_config(tmp_path)
    assert cfg.ping_url.endswith("test-uuid")
    assert cfg.host_id == "lab1"


def test_beat_once_dry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hb.init_config("https://example.invalid/ping", tmp_path)
    res = hb.beat_once(tmp_path, dry_run=True)
    assert res["ping"].get("dry_run") is True


def test_beat_once_no_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # no config
    res = hb.beat_once(tmp_path)
    assert res["ping"].get("skipped") is True
    assert (tmp_path / ".nexus_state" / "last_heartbeat.json").is_file()


def test_cron_line_contains_heartbeat():
    line = hb.cron_line(project_root=Path("/tmp/proj"), interval_min=5)
    assert "heartbeat once" in line
    assert "crontab" not in line


def test_recovery_network_diagnose():
    r = rec.network_diagnose()
    assert r.action == "network"
    assert r.steps


def test_wifi_without_flag_is_safe():
    r = rec.wifi_recover(allow_reconnect=False)
    assert r.action == "wifi"
    # if online ok; if offline message mentions allow-reconnect
    if not r.ok:
        assert "allow-reconnect" in r.message


def test_reboot_refused_without_gates():
    r = rec.reboot_machine(allow_reboot=False)
    assert r.ok is False
    assert "allow-reboot" in r.message
    r2 = rec.reboot_machine(allow_reboot=True)  # still needs env
    assert r2.ok is False
    assert "NEXUS_ALLOW_REBOOT" in r2.message
