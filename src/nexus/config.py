"""Global knobs. Autonomy defaults OFF."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """Runtime settings for the public kit."""

    # Background goal loops that invent tasks — classic token sink.
    autonomy: bool = False

    # Where durable checkpoints live
    state_dir: Path = field(default_factory=lambda: Path(".nexus_state"))

    # Judge prefers a different vendor than implementer
    prefer_cross_vendor_judge: bool = True

    # Memory retrieval outage must not freeze the engine
    memory_fail_open: bool = True

    # Structural pre-gate only (required keys present)
    structural_pre_gate: bool = True

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
