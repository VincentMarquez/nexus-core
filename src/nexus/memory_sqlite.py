"""SQLite FTS5 memory spine — durable namespaced retrieval (no cloud)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from .memory import MemorySpine, _tokenize


class SqliteMemory:
    """Drop-in search API compatible with MemorySpine.search()."""

    def __init__(self, path: Path | str, *, fail_open: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fail_open = fail_open
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
              text TEXT NOT NULL
            )
            """
        )
        try:
            cur.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id, ns, text)"
            )
        except sqlite3.OperationalError:
            self._fts = False
        self.conn.commit()

    def add_text(
        self,
        text: str,
        *,
        ns: str,
        kind: str = "doc",
        source: str = "",
        id: Optional[str] = None,
    ) -> str:
        cid = id or f"c{int(self.conn.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]) + 1}"
        self.conn.execute("DELETE FROM chunks WHERE id = ?", (cid,))
        if self._fts:
            try:
                self.conn.execute("DELETE FROM chunks_fts WHERE id = ?", (cid,))
            except sqlite3.OperationalError:
                pass
        self.conn.execute(
            "INSERT INTO chunks(id, ns, kind, source, text) VALUES (?,?,?,?,?)",
            (cid, ns, kind, source, text),
        )
        if self._fts:
            self.conn.execute(
                "INSERT INTO chunks_fts(id, ns, text) VALUES (?,?,?)",
                (cid, ns, text),
            )
        self.conn.commit()
        return cid

    def search(self, query: str, *, ns: str = "proj/demo", k: int = 5) -> list[dict[str, Any]]:
        try:
            if self._fts and query.strip():
                toks = _tokenize(query)
                # FTS5 query: quote tokens
                if toks:
                    q = " OR ".join(toks)
                else:
                    q = query.replace('"', "")
                try:
                    rows = self.conn.execute(
                        """
                        SELECT c.id, c.ns, c.kind, c.source, c.text
                        FROM chunks_fts f
                        JOIN chunks c ON c.id = f.id
                        WHERE chunks_fts MATCH ? AND c.ns = ?
                        LIMIT ?
                        """,
                        (q, ns, k),
                    ).fetchall()
                    if rows:
                        return [
                            {
                                "id": r["id"],
                                "text": r["text"][:500],
                                "score": 1.0,
                                "source": r["source"],
                                "kind": r["kind"],
                                "ns": r["ns"],
                            }
                            for r in rows
                        ]
                except sqlite3.OperationalError:
                    pass
            rows = self.conn.execute(
                "SELECT id, ns, kind, source, text FROM chunks WHERE ns = ?", (ns,)
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
                scored.append((float(inter), r))
            scored.sort(key=lambda x: -x[0])
            return [
                {
                    "id": r["id"],
                    "text": r["text"][:500],
                    "score": sc,
                    "source": r["source"],
                    "kind": r["kind"],
                    "ns": r["ns"],
                }
                for sc, r in scored[:k]
            ]
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
