"""Memory spine — namespaced hybrid retrieval with RRF fusion."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _rrf(rank_lists: list[list[str]], *, k0: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for lst in rank_lists:
        for rank, doc_id in enumerate(lst):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k0 + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])


@dataclass
class Chunk:
    id: str
    text: str
    ns: str
    kind: str = "doc"
    source: str = ""
    neighbors: list[str] = field(default_factory=list)
    vector: Optional[list[float]] = None


@dataclass
class MemorySpine:
    """
    In-memory reference implementation of the NEXUS memory API.

    Production systems swap the store for SQLite FTS5 + embeddings + graphify.
    The *contract* stays: search(q, ns=..., k=...) with fail-open behavior.
    """

    chunks: dict[str, Chunk] = field(default_factory=dict)
    fail_open: bool = True

    def add(self, chunk: Chunk) -> None:
        self.chunks[chunk.id] = chunk

    def add_text(self, text: str, *, ns: str, kind: str = "doc", source: str = "", id: Optional[str] = None) -> str:
        cid = id or f"c{len(self.chunks)+1}"
        self.add(Chunk(id=cid, text=text, ns=ns, kind=kind, source=source))
        return cid

    def _lexical(self, query: str, ns: str, pool: int = 50) -> list[str]:
        q = set(_tokenize(query))
        q_raw = query.lower()
        scored: list[tuple[float, str]] = []
        for cid, ch in self.chunks.items():
            if ch.ns != ns:
                continue
            text_l = ch.text.lower()
            toks = _tokenize(ch.text)
            if not toks:
                continue
            # token overlap + substring boost (handles checkpoint/checkpoints)
            tf = sum(1 for t in toks if t in q or any(t.startswith(qt) or qt.startswith(t) for qt in q if len(qt) > 3))
            for qt in q:
                if len(qt) > 3 and qt in text_l:
                    tf += 1
            if any(w in text_l for w in q_raw.split() if len(w) > 3):
                tf += 1
            if tf <= 0:
                continue
            scored.append((tf / math.sqrt(len(toks)), cid))
        scored.sort(key=lambda x: -x[0])
        return [cid for _, cid in scored[:pool]]

    def _dense(self, query: str, ns: str, pool: int = 50) -> list[str]:
        # Optional: bag-of-words cosine if vectors absent
        q = _tokenize(query)
        if not q:
            return []
        qset = set(q)
        scored: list[tuple[float, str]] = []
        for cid, ch in self.chunks.items():
            if ch.ns != ns:
                continue
            tset = set(_tokenize(ch.text))
            if not tset:
                continue
            inter = len(qset & tset)
            if inter == 0:
                continue
            scored.append((inter / math.sqrt(len(qset) * len(tset)), cid))
        scored.sort(key=lambda x: -x[0])
        return [cid for _, cid in scored[:pool]]

    def _graph_expand(self, seed_ids: list[str], ns: str, limit: int = 12) -> list[str]:
        out: list[str] = []
        for sid in seed_ids:
            ch = self.chunks.get(sid)
            if not ch:
                continue
            for nb in ch.neighbors:
                nch = self.chunks.get(nb)
                if nch and nch.ns == ns and nb not in out and nb not in seed_ids:
                    out.append(nb)
                if len(out) >= limit:
                    return out
        return out

    def search(self, query: str, *, ns: str = "proj/demo", k: int = 5) -> list[dict[str, Any]]:
        try:
            lex = self._lexical(query, ns)
            dense = self._dense(query, ns)
            graph = self._graph_expand(lex[:5], ns)
            fused = _rrf([lex, dense, graph])
            results = []
            for cid, score in fused[:k]:
                ch = self.chunks[cid]
                results.append(
                    {
                        "id": cid,
                        "text": ch.text[:500],
                        "score": score,
                        "source": ch.source,
                        "kind": ch.kind,
                        "ns": ch.ns,
                    }
                )
            return results
        except Exception:
            if self.fail_open:
                return []
            raise

    @classmethod
    def demo(cls) -> "MemorySpine":
        m = cls()
        a = m.add_text(
            "Durable engine checkpoints each step and resumes after process death.",
            ns="proj/demo",
            kind="doc",
            source="docs/ARCHITECTURE.md",
            id="arch-durable",
        )
        b = m.add_text(
            "Rubric judge scores success_criteria with artifact evidence, not presence.",
            ns="proj/demo",
            kind="doc",
            source="docs/PIPELINE.md",
            id="arch-judge",
        )
        c = m.add_text(
            "Cascade index: read shallow system map before deep files.",
            ns="proj/demo",
            kind="doc",
            source="docs/CASCADE.md",
            id="arch-cascade",
        )
        m.chunks[a].neighbors = [b]
        m.chunks[b].neighbors = [a, c]
        m.chunks[c].neighbors = [b]
        # different namespace must not leak
        m.add_text("private tenant secret should never appear", ns="proj/other", id="secret")
        return m
