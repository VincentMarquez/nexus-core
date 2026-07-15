"""Trust layer — provenance + verdict logging."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from .persist import atomic_write_json


@dataclass
class Provenance:
    prov_id: str
    task_id: str
    step: int
    agent: str
    vendor: str
    epistemic: str  # CONFIRMED | INFERRED | MODEL_ASSERTED
    summary: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrustLog:
    def __init__(self, path: Optional[Path] = None):
        self.path = path
        self.provenance: list[Provenance] = []
        self.verdicts: list[dict[str, Any]] = []

    def record_prov(
        self,
        *,
        task_id: str,
        step: int,
        agent: str,
        vendor: str,
        summary: str,
        epistemic: str = "MODEL_ASSERTED",
    ) -> Provenance:
        p = Provenance(
            prov_id=str(uuid.uuid4())[:8],
            task_id=task_id,
            step=step,
            agent=agent,
            vendor=vendor,
            epistemic=epistemic,
            summary=summary[:500],
        )
        self.provenance.append(p)
        self._flush()
        return p

    def record_verdict(self, task_id: str, step: int, verdict: dict[str, Any]) -> None:
        row = {"task_id": task_id, "step": step, **verdict, "ts": time.time()}
        self.verdicts.append(row)
        self._flush()

    def _flush(self) -> None:
        if not self.path:
            return
        payload = {
            "provenance": [p.to_dict() for p in self.provenance],
            "verdicts": self.verdicts,
        }
        atomic_write_json(self.path, payload)
