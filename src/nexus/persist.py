"""Crash-safe on-disk persistence helpers.

Patterns ported (shape only, not vendored code):
- Durable Functions / Temporal-style write-then-rename checkpoints
  (DurableMultiAgentTemplate, DriftQ-Core, Rojak durable state)
- Append-only audit/event streams (edict AuditLog, MisterSmith operator surfaces)

Never use for secrets; callers own redaction.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Optional


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> None:
    """Write *text* atomically via temp file + os.replace (POSIX-atomic rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_json(path: Path | str, data: Any, *, indent: int = 2) -> None:
    """JSON-serialize *data* and write atomically."""
    payload = json.dumps(data, indent=indent, default=str)
    if not payload.endswith("\n"):
        payload += "\n"
    atomic_write_text(path, payload)


def append_jsonl(path: Path | str, row: dict[str, Any]) -> None:
    """Append one JSON object as a line (audit / event journal)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, default=str, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass


def read_jsonl(
    path: Path | str,
    *,
    limit: Optional[int] = None,
    reverse: bool = False,
) -> list[dict[str, Any]]:
    """Load JSONL rows; skip corrupt lines. *limit* keeps first N (or last N if reverse)."""
    path = Path(path)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    if reverse:
        rows = list(reversed(rows))
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return rows


def event_row(
    event: str,
    *,
    task_id: str = "",
    step: Optional[int] = None,
    agent: str = "",
    status: str = "",
    detail: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a standard task-event dict (edict-style who/when/what)."""
    row: dict[str, Any] = {
        "ts": time.time(),
        "event": event,
        "task_id": task_id,
    }
    if step is not None:
        row["step"] = int(step)
    if agent:
        row["agent"] = agent
    if status:
        row["status"] = status
    if detail:
        row["detail"] = detail[:500]
    if extra:
        for k, v in extra.items():
            if k not in row:
                row[k] = v
    return row


def iter_jsonl(path: Path | str) -> Iterable[dict[str, Any]]:
    """Yield JSONL dicts lazily."""
    path = Path(path)
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj
