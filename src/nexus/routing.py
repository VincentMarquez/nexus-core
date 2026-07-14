"""Load vendor map + static routing table from data/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"


def _load(name: str) -> dict[str, Any]:
    path = _DATA / name
    if not path.exists():
        # installed package fallback: empty
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def vendor_map() -> dict[str, str]:
    return dict(_load("vendor_map.json"))


def routing_table() -> dict[str, Any]:
    return dict(_load("routing_table.json"))


def preferred_agents(role: str) -> list[str]:
    table = routing_table()
    roles = table.get("roles") or {}
    return list(roles.get(role) or [role])
