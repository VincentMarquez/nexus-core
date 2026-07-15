"""Optional metrics module (no OTel required)."""

import os

from nexus import metrics as m


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NEXUS_METRICS", raising=False)
    assert m.enabled() is False
    m.counter("t").inc()  # no-op path still works


def test_counter_and_prom(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_METRICS", "1")
    monkeypatch.setenv("NEXUS_METRICS_PROM_FILE", str(tmp_path / "m.prom"))
    # reset module stores
    m._COUNTERS.clear()
    m._HISTOGRAMS.clear()
    m.counter("nexus_test_total", kind="unit").inc(2)
    m.histogram("nexus_test_seconds").observe(0.5)
    text = m.prometheus_text()
    assert "nexus_test_total" in text
    path = m.flush()
    assert path is not None and path.is_file()
    snap = m.snapshot()
    assert snap["enabled"] is True
