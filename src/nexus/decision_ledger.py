"""Immutable agent decision ledger (soul + lumen patterns).

P0.1 from docs/LATEST_IMPROVE_PLAN.md — append-only SQLite audit of agent
decisions for the self-improve loop (mine → grade → claim_verify → …).

Storage: ``.nexus_state/ledger/decisions.sqlite`` under the project workdir.

Schema::

  agent_decisions(
    id, run_id, agent, claim, evidence_refs, grade, action,
    content_hash, created_at
  )

Idempotent append by ``content_hash`` (lumen-style): re-appending the same
decision returns the existing row instead of duplicating.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = "nexus.decision_ledger/v1"
DB_NAME = "decisions.sqlite"


class LedgerError(RuntimeError):
    """Invalid ledger operation."""


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def ledger_dir(workdir: Optional[Path | str] = None) -> Path:
    d = _root(workdir) / ".nexus_state" / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path(workdir: Optional[Path | str] = None) -> Path:
    return ledger_dir(workdir) / DB_NAME


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, sort_keys=True, separators=(",", ":"))


def _json_loads(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return None


def content_hash(
    *,
    run_id: str,
    agent: str,
    claim: str,
    evidence_refs: list[str] | tuple[str, ...] | None,
    grade: dict[str, Any] | None,
    action: str,
) -> str:
    """Stable SHA-256 of decision payload (for idempotent append)."""
    payload = {
        "run_id": str(run_id or ""),
        "agent": str(agent or ""),
        "claim": str(claim or ""),
        "evidence_refs": list(evidence_refs or []),
        "grade": grade or {},
        "action": str(action or ""),
    }
    blob = _json_dumps(payload).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass
class DecisionLedger:
    """Append-only SQLite ledger for agent decisions."""

    workdir: Path
    conn: sqlite3.Connection

    @classmethod
    def open(cls, workdir: Optional[Path | str] = None) -> "DecisionLedger":
        root = _root(workdir)
        path = db_path(root)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        store = cls(workdir=root, conn=conn)
        store._init()
        return store

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> "DecisionLedger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_decisions (
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              agent TEXT NOT NULL,
              claim TEXT NOT NULL DEFAULT '',
              evidence_refs TEXT NOT NULL DEFAULT '[]',
              grade TEXT NOT NULL DEFAULT '{}',
              action TEXT NOT NULL DEFAULT '',
              content_hash TEXT NOT NULL UNIQUE,
              created_at REAL NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_run "
            "ON agent_decisions(run_id, created_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_agent "
            "ON agent_decisions(agent, created_at)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES(?, ?)",
            ("schema", SCHEMA_VERSION),
        )
        self.conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "agent": row["agent"],
            "claim": row["claim"],
            "evidence_refs": _json_loads(row["evidence_refs"]) or [],
            "grade": _json_loads(row["grade"]) or {},
            "action": row["action"],
            "content_hash": row["content_hash"],
            "created_at": float(row["created_at"]),
        }

    def append(
        self,
        *,
        run_id: str,
        agent: str,
        claim: str = "",
        evidence_refs: Optional[list[str]] = None,
        grade: Optional[dict[str, Any]] = None,
        action: str = "",
        decision_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        """Append a decision. Same content_hash → return existing row (idempotent)."""
        rid = str(run_id or "").strip()
        ag = str(agent or "").strip()
        if not rid:
            raise LedgerError("run_id required")
        if not ag:
            raise LedgerError("agent required")

        refs = [str(x) for x in (evidence_refs or []) if str(x).strip()]
        grade_obj = dict(grade or {})
        act = str(action or "").strip()
        ch = content_hash(
            run_id=rid,
            agent=ag,
            claim=str(claim or ""),
            evidence_refs=refs,
            grade=grade_obj,
            action=act,
        )

        existing = self.conn.execute(
            "SELECT * FROM agent_decisions WHERE content_hash = ?", (ch,)
        ).fetchone()
        if existing is not None:
            return self._row_to_dict(existing)

        did = str(decision_id or f"dec-{uuid.uuid4().hex[:12]}")
        ts = float(created_at if created_at is not None else time.time())
        try:
            self.conn.execute(
                """
                INSERT INTO agent_decisions(
                  id, run_id, agent, claim, evidence_refs, grade,
                  action, content_hash, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    did,
                    rid,
                    ag,
                    str(claim or ""),
                    _json_dumps(refs),
                    _json_dumps(grade_obj),
                    act,
                    ch,
                    ts,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            # Race or unique collision: re-fetch by content_hash
            existing = self.conn.execute(
                "SELECT * FROM agent_decisions WHERE content_hash = ?", (ch,)
            ).fetchone()
            if existing is not None:
                return self._row_to_dict(existing)
            raise LedgerError(f"append conflict for content_hash={ch[:12]}") from None

        row = self.conn.execute(
            "SELECT * FROM agent_decisions WHERE id = ?", (did,)
        ).fetchone()
        if row is None:
            raise LedgerError("append failed to persist")
        return self._row_to_dict(row)

    def get(self, decision_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM agent_decisions WHERE id = ?",
            (str(decision_id),),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def by_hash(self, content_hash_value: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM agent_decisions WHERE content_hash = ?",
            (str(content_hash_value),),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_run(
        self,
        run_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM agent_decisions
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (str(run_id), max(1, int(limit))),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def tail(self, *, limit: int = 20, run_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Last N decisions (newest first), optionally filtered by run_id."""
        n = max(1, int(limit))
        if run_id:
            rows = self.conn.execute(
                """
                SELECT * FROM agent_decisions
                WHERE run_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (str(run_id), n),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM agent_decisions
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (n,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self, *, run_id: Optional[str] = None) -> int:
        if run_id:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM agent_decisions WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM agent_decisions"
            ).fetchone()
        return int(row["n"] if row else 0)


def open_ledger(workdir: Optional[Path | str] = None) -> DecisionLedger:
    """Convenience: open ledger at workdir (caller should close)."""
    return DecisionLedger.open(workdir)
