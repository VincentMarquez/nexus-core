"""Optional production metrics (Prometheus / OpenTelemetry).

No hard dependency: if libraries are missing, metrics are no-ops.

  export NEXUS_METRICS=1
  # optional Prometheus text file:
  export NEXUS_METRICS_PROM_FILE=.nexus_state/metrics.prom

  from nexus.metrics import counter, histogram, flush
  counter("nexus_task_completed_total").inc()
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def enabled() -> bool:
    v = (os.environ.get("NEXUS_METRICS") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


@dataclass
class _Counter:
    name: str
    value: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)

    def inc(self, n: float = 1.0) -> None:
        self.value += n
        _emit_otel_counter(self.name, n, self.labels)


@dataclass
class _Histogram:
    name: str
    samples: list[float] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)

    def observe(self, v: float) -> None:
        self.samples.append(float(v))
        _emit_otel_histogram(self.name, float(v), self.labels)


_COUNTERS: dict[str, _Counter] = {}
_HISTOGRAMS: dict[str, _Histogram] = {}


def counter(name: str, **labels: str) -> _Counter:
    key = name + "|" + ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    if key not in _COUNTERS:
        _COUNTERS[key] = _Counter(name=name, labels=dict(labels))
    return _COUNTERS[key]


def histogram(name: str, **labels: str) -> _Histogram:
    key = name + "|" + ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    if key not in _HISTOGRAMS:
        _HISTOGRAMS[key] = _Histogram(name=name, labels=dict(labels))
    return _HISTOGRAMS[key]


def record_task_event(event: str, *, status: str = "") -> None:
    if not enabled():
        return
    counter("nexus_task_events_total", event=event, status=status or "na").inc()


def record_step_latency(seconds: float, *, step: str = "") -> None:
    if not enabled():
        return
    histogram("nexus_step_seconds", step=step or "na").observe(seconds)


def _emit_otel_counter(name: str, n: float, labels: dict[str, str]) -> None:
    if not enabled():
        return
    try:
        from opentelemetry import metrics  # type: ignore

        meter = metrics.get_meter("nexus")
        c = meter.create_counter(name)
        c.add(n, attributes=labels or None)
    except Exception:
        pass


def _emit_otel_histogram(name: str, v: float, labels: dict[str, str]) -> None:
    if not enabled():
        return
    try:
        from opentelemetry import metrics  # type: ignore

        meter = metrics.get_meter("nexus")
        h = meter.create_histogram(name)
        h.record(v, attributes=labels or None)
    except Exception:
        pass


def prometheus_text() -> str:
    """Render a minimal Prometheus exposition of in-process series."""
    lines: list[str] = []
    for c in _COUNTERS.values():
        lab = ""
        if c.labels:
            lab = "{" + ",".join(f'{k}="{v}"' for k, v in sorted(c.labels.items())) + "}"
        lines.append(f"{c.name}{lab} {c.value}")
    for h in _HISTOGRAMS.values():
        lab = ""
        if h.labels:
            lab = "{" + ",".join(f'{k}="{v}"' for k, v in sorted(h.labels.items())) + "}"
        if not h.samples:
            continue
        lines.append(f"{h.name}_count{lab} {len(h.samples)}")
        lines.append(f"{h.name}_sum{lab} {sum(h.samples)}")
    return "\n".join(lines) + ("\n" if lines else "")


def flush(workdir: Optional[Path] = None) -> Optional[Path]:
    """Write Prometheus textfile if NEXUS_METRICS_PROM_FILE is set."""
    if not enabled():
        return None
    path = os.environ.get("NEXUS_METRICS_PROM_FILE")
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute() and workdir:
        p = Path(workdir) / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(prometheus_text(), encoding="utf-8")
    return p


def snapshot() -> dict[str, Any]:
    return {
        "enabled": enabled(),
        "ts": time.time(),
        "counters": {k: c.value for k, c in _COUNTERS.items()},
        "histograms": {
            k: {"count": len(h.samples), "sum": sum(h.samples) if h.samples else 0}
            for k, h in _HISTOGRAMS.items()
        },
    }
