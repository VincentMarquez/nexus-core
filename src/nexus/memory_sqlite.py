"""SQLite FTS5 memory spine — durable namespaced retrieval (no cloud).

Optional exponential decay on chunk age (half-life days) mirrors decay-aware
shared memory patterns from openclaw-hawkins without coupling to that stack.
"""

from __future__ import annotations

import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from .memory import MemorySpine, _tokenize


class SqliteMemory:
    """Drop-in search API compatible with MemorySpine.search()."""

    def __init__(
        self,
        path: Path | str,
        *,
        fail_open: bool = True,
        decay_half_life_days: float = 0.0,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fail_open = fail_open
        # 0 = decay disabled (default, preserves legacy score ordering)
        self.decay_half_life_days = float(decay_half_life_days or 0.0)
        self._fts = True
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
              id TEXT PRIMARY KEY,
              ns TEXT NOT NULL,
              kind TEXT NOT NULL DEFAULT 'doc',
              source TEXT NOT NULL DEFAULT '',
              text TEXT NOT NULL,
              ts REAL
            )
            """
        )
        # migrate older DBs created before ts column
        cols = {r[1] for r in cur.execute("PRAGMA table_info(chunks)").fetchall()}
        if "ts" not in cols:
            cur.execute("ALTER TABLE chunks ADD COLUMN ts REAL")
            cur.execute(
                "UPDATE chunks SET ts = ? WHERE ts IS NULL",
                (time.time(),),
            )
        try:
            cur.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id, ns, text)"
            )
        except sqlite3.OperationalError:
            self._fts = False
        self.conn.commit()

    def _decay_weight(self, ts: Optional[float], *, now: Optional[float] = None) -> float:
        """Return multiplier in (0, 1] from age; 1.0 when decay disabled or ts missing."""
        if self.decay_half_life_days <= 0:
            return 1.0
        now = time.time() if now is None else now
        try:
            age_days = max(0.0, (now - float(ts or now)) / 86400.0)
        except (TypeError, ValueError):
            return 1.0
        # exp(-ln(2) * age / half_life) → 0.5 at half-life
        return math.exp(-math.log(2.0) * age_days / self.decay_half_life_days)

    def add_text(
        self,
        text: str,
        *,
        ns: str,
        kind: str = "doc",
        source: str = "",
        id: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> str:
        cid = id or f"c{int(self.conn.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]) + 1}"
        self.conn.execute("DELETE FROM chunks WHERE id = ?", (cid,))
        if self._fts:
            try:
                self.conn.execute("DELETE FROM chunks_fts WHERE id = ?", (cid,))
            except sqlite3.OperationalError:
                pass
        stamp = float(ts if ts is not None else time.time())
        self.conn.execute(
            "INSERT INTO chunks(id, ns, kind, source, text, ts) VALUES (?,?,?,?,?,?)",
            (cid, ns, kind, source, text, stamp),
        )
        if self._fts:
            self.conn.execute(
                "INSERT INTO chunks_fts(id, ns, text) VALUES (?,?,?)",
                (cid, ns, text),
            )
        self.conn.commit()
        return cid

    def _hit(self, r: Any, score: float) -> dict[str, Any]:
        ts = None
        try:
            ts = r["ts"]
        except (KeyError, IndexError):
            ts = None
        return {
            "id": r["id"],
            "text": r["text"][:500],
            "score": score,
            "source": r["source"],
            "kind": r["kind"],
            "ns": r["ns"],
            "ts": ts,
        }

    def search(self, query: str, *, ns: str = "proj/demo", k: int = 5) -> list[dict[str, Any]]:
        try:
            now = time.time()
            if self._fts and query.strip():
                toks = _tokenize(query)
                # FTS5 query: quote tokens
                if toks:
                    q = " OR ".join(toks)
                else:
                    q = query.replace('"', "")
                try:
                    # over-fetch then re-rank by decay when enabled
                    fetch_n = max(k * 4, k) if self.decay_half_life_days > 0 else k
                    rows = self.conn.execute(
                        """
                        SELECT c.id, c.ns, c.kind, c.source, c.text, c.ts
                        FROM chunks_fts f
                        JOIN chunks c ON c.id = f.id
                        WHERE chunks_fts MATCH ? AND c.ns = ?
                        LIMIT ?
                        """,
                        (q, ns, fetch_n),
                    ).fetchall()
                    if rows:
                        scored = []
                        for r in rows:
                            base = 1.0
                            w = self._decay_weight(r["ts"], now=now)
                            scored.append((base * w, r))
                        scored.sort(key=lambda x: -x[0])
                        return [self._hit(r, sc) for sc, r in scored[:k]]
                except sqlite3.OperationalError:
                    pass
            rows = self.conn.execute(
                "SELECT id, ns, kind, source, text, ts FROM chunks WHERE ns = ?", (ns,)
            ).fetchall()
            qset = set(_tokenize(query))
            scored: list[tuple[float, Any]] = []
            for r in rows:
                text_l = (r["text"] or "").lower()
                tset = set(_tokenize(r["text"] or ""))
                inter = 0
                for qt in qset:
                    if qt in tset or any(t.startswith(qt) or qt.startswith(t) for t in tset if len(qt) > 3):
                        inter += 1
                    elif len(qt) > 3 and qt in text_l:
                        inter += 1
                if inter <= 0:
                    continue
                base = float(inter)
                w = self._decay_weight(r["ts"] if "ts" in r.keys() else None, now=now)
                scored.append((base * w, r))
            scored.sort(key=lambda x: -x[0])
            return [self._hit(r, sc) for sc, r in scored[:k]]
        except Exception:
            if self.fail_open:
                return []
            raise

    def seed_demo(self) -> None:
        if self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]:
            return
        self.add_text(
            "Durable engine checkpoints each step and resumes after process death.",
            ns="proj/demo",
            source="docs/ARCHITECTURE.md",
            id="arch-durable",
        )
        self.add_text(
            "Rubric judge scores success_criteria with artifact evidence, not presence.",
            ns="proj/demo",
            source="docs/PIPELINE.md",
            id="arch-judge",
        )
        self.add_text(
            "Cascade index: read shallow system map before deep files.",
            ns="proj/demo",
            source="docs/CASCADE.md",
            id="arch-cascade",
        )
        self.add_text(
            "private tenant secret should never appear",
            ns="proj/other",
            id="secret",
        )

    @classmethod
    def demo(cls, path: Path | str = ".nexus_state/memory.db") -> "SqliteMemory":
        m = cls(path)
        m.seed_demo()
        return m


def open_memory(path: Optional[Path | str] = None, *, sqlite: bool = True) -> Any:
    if sqlite:
        return SqliteMemory.demo(Path(path or ".nexus_state/memory.db"))
    return MemorySpine.demo()
