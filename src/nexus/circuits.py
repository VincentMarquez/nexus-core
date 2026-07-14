"""Circuit breakers — CLOSED / OPEN / HALF_OPEN health for agents & services."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class CircuitState(str, Enum):
    CLOSED = "CLOSED"  # healthy
    OPEN = "OPEN"  # failing — skip
    HALF_OPEN = "HALF_OPEN"  # probe once


@dataclass
class Circuit:
    name: str
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    successes: int = 0
    opened_at: float = 0.0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass
class CircuitBreaker:
    """
    Simple breaker:
      - trip OPEN after `failure_threshold` consecutive failures
      - after `cooldown_s`, allow one HALF_OPEN probe
      - success in HALF_OPEN → CLOSED; failure → OPEN again
    """

    failure_threshold: int = 3
    cooldown_s: float = 30.0
    circuits: dict[str, Circuit] = field(default_factory=dict)
    path: Optional[Path] = None

    def get(self, name: str) -> Circuit:
        if name not in self.circuits:
            self.circuits[name] = Circuit(name=name)
        return self.circuits[name]

    def can_execute(self, name: str) -> bool:
        c = self.get(name)
        if c.state == CircuitState.CLOSED:
            return True
        if c.state == CircuitState.OPEN:
            if time.time() - c.opened_at >= self.cooldown_s:
                c.state = CircuitState.HALF_OPEN
                self._flush()
                return True
            return False
        # HALF_OPEN — allow one probe
        return True

    def record_success(self, name: str) -> None:
        c = self.get(name)
        c.successes += 1
        c.failures = 0
        c.last_error = ""
        c.state = CircuitState.CLOSED
        self._flush()

    def record_failure(self, name: str, error: str = "") -> None:
        c = self.get(name)
        c.failures += 1
        c.last_error = (error or "")[:300]
        if c.state == CircuitState.HALF_OPEN or c.failures >= self.failure_threshold:
            c.state = CircuitState.OPEN
            c.opened_at = time.time()
        self._flush()

    def snapshot(self) -> dict[str, Any]:
        return {n: c.to_dict() for n, c in self.circuits.items()}

    def _flush(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path, **kwargs: Any) -> "CircuitBreaker":
        br = cls(path=path, **kwargs)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for name, row in data.items():
                    br.circuits[name] = Circuit(
                        name=name,
                        state=CircuitState(row.get("state", "CLOSED")),
                        failures=int(row.get("failures") or 0),
                        successes=int(row.get("successes") or 0),
                        opened_at=float(row.get("opened_at") or 0),
                        last_error=str(row.get("last_error") or ""),
                    )
            except Exception:
                pass
        return br
