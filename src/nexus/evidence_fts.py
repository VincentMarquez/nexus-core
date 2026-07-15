"""SQLite FTS5 evidence index for Grok grades + research claims.

First apply slice (docs/LATEST_IMPROVE_PLAN.md P0.3 + P0.4):

  fixtures / digests / arXiv notes
    → index_workspace()
    → search_evidence(query)
    → MCP tools (offline, no live Grok API)

Patterns (shape only, not vendored trees):
- codingagentsystem/cas — MCP SQLite/FTS context search
- choihyunsus/soul — simple ledger-style durable rows
- Thucy (2512.03278) — claim → evidence path anchors
- mission-control — quality-gate smoke without network
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from .grade_artifact import (
    GradeValidationError,
    SCHEMA_VERSION,
    load_grade,
    validate_grade,
)
from .memory import _tokenize

SCHEMA = "nexus.evidence_fts/v1"
DB_NAME = "evidence.sqlite"
DEFAULT_FIXTURE_RELS = (
    "fixtures/mine_eval/grades_with_claims.json",
    "tests/fixtures/mine_eval_sample.json",
)


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def store_dir(workdir: Optional[Path | str] = None) -> Path:
    d = _root(workdir) / ".nexus_state" / "evidence_fts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path(workdir: Optional[Path | str] = None) -> Path:
    return store_dir(workdir) / DB_NAME


class EvidenceIndex:
    """SQLite + FTS5 index over grade claims and research snippets."""

    def __init__(self, workdir: Optional[Path | str] = None, *, path: Optional[Path | str] = None):
        self.workdir = _root(workdir)
        self.path = Path(path) if path is not None else db_path(self.workdir)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fts = True
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._init()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> "EvidenceIndex":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS docs (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL DEFAULT 'claim',
              source TEXT NOT NULL DEFAULT '',
              repo TEXT NOT NULL DEFAULT '',
              arxiv_id TEXT NOT NULL DEFAULT '',
              path TEXT NOT NULL DEFAULT '',
              statement TEXT NOT NULL DEFAULT '',
              quote TEXT NOT NULL DEFAULT '',
              text TEXT NOT NULL DEFAULT '',
              score REAL,
              meta TEXT NOT NULL DEFAULT '{}',
              ts REAL NOT NULL
            )
            """
        )
        try:
            cur.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts "
                "USING fts5(id, statement, quote, text, repo, path)"
            )
        except sqlite3.OperationalError:
            self._fts = False
        self.conn.commit()

    def clear(self) -> None:
        self.conn.execute("DELETE FROM docs")
        if self._fts:
            try:
                self.conn.execute("DELETE FROM docs_fts")
            except sqlite3.OperationalError:
                pass
        self.conn.commit()

    def _upsert_doc(
        self,
        *,
        doc_id: str,
        kind: str,
        source: str,
        repo: str = "",
        arxiv_id: str = "",
        path: str = "",
        statement: str = "",
        quote: str = "",
        text: str = "",
        score: Optional[float] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> str:
        body = text or " ".join(x for x in (statement, quote, path, repo, arxiv_id) if x)
        now = time.time()
        self.conn.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
        if self._fts:
            try:
                self.conn.execute("DELETE FROM docs_fts WHERE id = ?", (doc_id,))
            except sqlite3.OperationalError:
                pass
        self.conn.execute(
            """
            INSERT INTO docs(
              id, kind, source, repo, arxiv_id, path, statement, quote, text,
              score, meta, ts
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                doc_id,
                kind,
                source,
                repo,
                arxiv_id,
                path,
                statement,
                quote,
                body,
                score,
                json.dumps(meta or {}, default=str, sort_keys=True),
                now,
            ),
        )
        if self._fts:
            self.conn.execute(
                "INSERT INTO docs_fts(id, statement, quote, text, repo, path) "
                "VALUES (?,?,?,?,?,?)",
                (doc_id, statement, quote, body, repo, path),
            )
        return doc_id

    def index_grade(self, grade: dict[str, Any], *, source: str = "") -> int:
        """Index one validated grade and its claims. Returns docs written."""
        g = validate_grade(grade, require_path=True, require_claims=False)
        repo = str(g.get("repo") or "")
        src = source or str(g.get("source") or g.get("path") or "")
        n = 0
        # Grade-level summary doc
        summary = str(g.get("summary") or g.get("pattern") or "")
        self._upsert_doc(
            doc_id=f"grade:{repo}",
            kind="grade",
            source=src,
            repo=repo,
            path=str(g.get("path") or ""),
            statement=summary or f"{repo} score={g.get('score')}",
            text=(
                f"{repo} score={g.get('score')} idea={g.get('idea')} "
                f"skill={g.get('skill')} method={g.get('method')} "
                f"{summary} {g.get('pattern') or ''}"
            ),
            score=float(g.get("score") or 0),
            meta={"schema": SCHEMA_VERSION, "method": g.get("method")},
        )
        n += 1
        claims = g.get("claims") or []
        for i, c in enumerate(claims):
            if not isinstance(c, dict):
                continue
            stmt = str(c.get("statement") or "").strip()
            cpath = str(c.get("path") or g.get("path") or "").strip()
            quote = str(c.get("quote") or "").strip()
            arxiv = str(c.get("arxiv_id") or g.get("arxiv_id") or "").strip()
            cid = f"claim:{repo}:{i}"
            self._upsert_doc(
                doc_id=cid,
                kind="claim",
                source=src,
                repo=repo,
                arxiv_id=arxiv,
                path=cpath,
                statement=stmt,
                quote=quote,
                text=f"{stmt} {quote} {repo} {arxiv} {cpath}",
                score=float(g.get("score") or 0),
                meta={"index": i},
            )
            n += 1
        self.conn.commit()
        return n

    def index_research_snippet(
        self,
        *,
        arxiv_id: str,
        statement: str,
        path: str = "",
        quote: str = "",
        source: str = "",
    ) -> str:
        """Index a free-standing research claim (e.g. paper decision package)."""
        aid = str(arxiv_id or "").strip()
        doc_id = f"paper:{aid or 'unknown'}:{abs(hash(statement)) % 10_000_000}"
        self._upsert_doc(
            doc_id=doc_id,
            kind="paper",
            source=source or path or "research",
            arxiv_id=aid,
            path=path or f"arxiv:{aid}",
            statement=statement,
            quote=quote,
            text=f"{aid} {statement} {quote}",
        )
        self.conn.commit()
        return doc_id

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM docs").fetchone()
        return int(row["n"] if row else 0)

    def search(self, query: str, *, k: int = 10, kind: Optional[str] = None) -> list[dict[str, Any]]:
        """FTS search over indexed evidence; falls back to token overlap."""
        q = str(query or "").strip()
        if not q:
            return []
        k = max(1, int(k))
        try:
            if self._fts:
                toks = _tokenize(q)
                fts_q = " OR ".join(toks) if toks else q.replace('"', "")
                try:
                    sql = """
                        SELECT d.*
                        FROM docs_fts f
                        JOIN docs d ON d.id = f.id
                        WHERE docs_fts MATCH ?
                    """
                    params: list[Any] = [fts_q]
                    if kind:
                        sql += " AND d.kind = ?"
                        params.append(kind)
                    sql += " LIMIT ?"
                    params.append(k * 3)
                    rows = self.conn.execute(sql, params).fetchall()
                    if rows:
                        return [self._hit(r, 1.0) for r in rows[:k]]
                except sqlite3.OperationalError:
                    pass
            # lexical fallback
            sql = "SELECT * FROM docs"
            params2: list[Any] = []
            if kind:
                sql += " WHERE kind = ?"
                params2.append(kind)
            rows = self.conn.execute(sql, params2).fetchall()
            qset = set(_tokenize(q))
            scored: list[tuple[float, Any]] = []
            for r in rows:
                blob = " ".join(
                    str(r[c] or "")
                    for c in ("statement", "quote", "text", "repo", "path", "arxiv_id")
                ).lower()
                tset = set(_tokenize(blob))
                inter = sum(1 for t in qset if t in tset or t in blob)
                if inter > 0:
                    scored.append((float(inter), r))
            scored.sort(key=lambda x: -x[0])
            return [self._hit(r, sc) for sc, r in scored[:k]]
        except Exception:
            return []

    def _hit(self, r: sqlite3.Row, score: float) -> dict[str, Any]:
        return {
            "id": r["id"],
            "kind": r["kind"],
            "source": r["source"],
            "repo": r["repo"],
            "arxiv_id": r["arxiv_id"],
            "path": r["path"],
            "statement": r["statement"],
            "quote": (r["quote"] or "")[:400],
            "score": float(r["score"]) if r["score"] is not None else score,
            "rank": float(score),
            "text": (r["text"] or "")[:500],
        }


def _load_fixture_grades(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items: list[Any]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        if isinstance(raw.get("grades"), list):
            items = list(raw["grades"])
        elif isinstance(raw.get("candidates"), list):
            items = list(raw["candidates"])
        else:
            items = [raw]
        # First-apply research claim rows (papers) ride alongside grades
        if isinstance(raw.get("research_claims"), list):
            items.extend(raw["research_claims"])
    else:
        raise GradeValidationError(f"bad fixture shape: {path}")
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # Research-only paper rows (no full grade)
        if item.get("kind") == "paper" or (
            item.get("arxiv_id") and not item.get("repo") and item.get("statement")
        ):
            out.append(item)
            continue
        try:
            # Prefer strict claims when present in fixture
            require_claims = bool(item.get("claims"))
            g = validate_grade(
                item,
                require_path=True,
                require_claims=require_claims,
            )
            g["_fixture"] = str(path)
            out.append(g)
        except GradeValidationError:
            # Soft: still try without claims requirement for older fixtures
            try:
                g = validate_grade(item, require_path=True, require_claims=False)
                g["_fixture"] = str(path)
                out.append(g)
            except GradeValidationError:
                continue
    return out


def discover_fixture_paths(workdir: Path | str) -> list[Path]:
    root = _root(workdir)
    found: list[Path] = []
    for rel in DEFAULT_FIXTURE_RELS:
        p = root / rel
        if p.is_file():
            found.append(p)
    fixtures_dir = root / "fixtures" / "mine_eval"
    if fixtures_dir.is_dir():
        for p in sorted(fixtures_dir.glob("*.json")):
            if p not in found:
                found.append(p)
    # Optional grade JSON cache
    cache = root / ".nexus_workspaces" / "grades"
    if cache.is_dir():
        for p in sorted(cache.glob("*.json")):
            found.append(p)
    return found


def index_workspace(
    workdir: Optional[Path | str] = None,
    *,
    fixture_paths: Optional[Sequence[Path | str]] = None,
    clear: bool = True,
    include_improve_ours: bool = True,
) -> dict[str, Any]:
    """Index grade fixtures + optional IMPROVE_OURS snippets into FTS.

    Offline — no network. Suitable for ``make mcp-smoke``.
    """
    root = _root(workdir)
    idx = EvidenceIndex(root)
    try:
        if clear:
            idx.clear()
        n_docs = 0
        n_grades = 0
        n_papers = 0
        sources: list[str] = []

        paths: list[Path]
        if fixture_paths is not None:
            paths = [Path(p) for p in fixture_paths]
        else:
            paths = discover_fixture_paths(root)

        for p in paths:
            if not p.is_file():
                continue
            sources.append(str(p.relative_to(root) if p.is_relative_to(root) else p))
            try:
                rows = _load_fixture_grades(p)
            except (OSError, json.JSONDecodeError, GradeValidationError):
                # single grade file
                try:
                    g = load_grade(p)
                    rows = [g]
                except (OSError, GradeValidationError):
                    continue
            for row in rows:
                if row.get("kind") == "paper" or (
                    row.get("arxiv_id")
                    and not row.get("repo")
                    and row.get("statement")
                ):
                    idx.index_research_snippet(
                        arxiv_id=str(row.get("arxiv_id") or ""),
                        statement=str(row.get("statement") or ""),
                        path=str(row.get("path") or ""),
                        quote=str(row.get("quote") or ""),
                        source=str(p),
                    )
                    n_papers += 1
                    n_docs += 1
                    continue
                written = idx.index_grade(row, source=str(p))
                n_grades += 1
                n_docs += written

        if include_improve_ours:
            ours = root / ".nexus_state" / "repo_mine" / "IMPROVE_OURS.md"
            if ours.is_file():
                try:
                    text = ours.read_text(encoding="utf-8", errors="replace")
                    # index short header blocks as digest docs
                    for part in re.split(r"(?=^##\s+)", text, flags=re.MULTILINE):
                        if not part.strip().startswith("##"):
                            continue
                        first = part.splitlines()[0].lstrip("# ").strip()
                        # "## wshobson/agents (score 16.0)"
                        m = re.match(
                            r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+).*score\s*([0-9.]+)",
                            first,
                            re.I,
                        )
                        if not m:
                            continue
                        repo = m.group(1)
                        sc = float(m.group(2))
                        body = part[:1500]
                        idx._upsert_doc(
                            doc_id=f"digest:{repo}",
                            kind="digest",
                            source=str(ours.relative_to(root)),
                            repo=repo,
                            path=str(ours.relative_to(root)),
                            statement=first,
                            text=body,
                            score=sc,
                        )
                        n_docs += 1
                    idx.conn.commit()
                    sources.append(str(ours.relative_to(root)))
                except OSError:
                    pass

        return {
            "schema": SCHEMA,
            "ok": True,
            "db": str(idx.path),
            "docs": idx.count(),
            "grades_indexed": n_grades,
            "papers_indexed": n_papers,
            "docs_written": n_docs,
            "sources": sources,
            "fts": idx._fts,
        }
    finally:
        idx.close()


def search_evidence(
    query: str,
    *,
    workdir: Optional[Path | str] = None,
    k: int = 10,
    kind: Optional[str] = None,
    auto_index: bool = False,
) -> dict[str, Any]:
    """Search the evidence FTS index. Optionally index fixtures first."""
    root = _root(workdir)
    if auto_index or not db_path(root).is_file():
        index_workspace(root)
    with EvidenceIndex(root) as idx:
        hits = idx.search(query, k=k, kind=kind)
        return {
            "schema": SCHEMA,
            "query": query,
            "count": len(hits),
            "hits": hits,
            "db": str(idx.path),
            "docs_total": idx.count(),
        }


def grade_validate_fixtures(
    workdir: Optional[Path | str] = None,
    *,
    fixture_paths: Optional[Sequence[Path | str]] = None,
    require_claims: bool = True,
) -> dict[str, Any]:
    """Schema-validate grade fixtures (make grade-validate).

    Fail closed on missing claims / out-of-range scores when require_claims.
    """
    root = _root(workdir)
    if fixture_paths is not None:
        paths = [Path(p) for p in fixture_paths]
    else:
        # Prefer claims fixture for the quality gate
        preferred = root / "fixtures" / "mine_eval" / "grades_with_claims.json"
        if preferred.is_file():
            paths = [preferred]
        else:
            paths = discover_fixture_paths(root)
    errors: list[str] = []
    ok_grades: list[dict[str, Any]] = []
    checked = 0
    for p in paths:
        if not p.is_file():
            errors.append(f"missing fixture: {p}")
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"{p}: {e}")
            continue
        items: list[Any]
        if isinstance(raw, dict) and isinstance(raw.get("grades"), list):
            items = list(raw["grades"])
            # also validate top-level research_claims if present
            for rc in raw.get("research_claims") or []:
                items.append(rc)
        elif isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = [raw]
        else:
            errors.append(f"{p}: unsupported shape")
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{p}[{i}]: not an object")
                continue
            # paper rows: require statement + path/arxiv
            if item.get("kind") == "paper" or (
                item.get("arxiv_id") and item.get("statement") and not item.get("repo")
            ):
                checked += 1
                if not str(item.get("statement") or "").strip():
                    errors.append(f"{p}[{i}]: paper missing statement")
                if not (
                    str(item.get("path") or "").strip()
                    or str(item.get("arxiv_id") or "").strip()
                ):
                    errors.append(f"{p}[{i}]: paper missing path/arxiv_id")
                else:
                    ok_grades.append(
                        {
                            "kind": "paper",
                            "arxiv_id": item.get("arxiv_id"),
                            "statement": item.get("statement"),
                        }
                    )
                continue
            checked += 1
            try:
                g = validate_grade(
                    item,
                    require_path=True,
                    require_claims=require_claims,
                    check_ranges=True,
                )
                ok_grades.append(
                    {
                        "repo": g.get("repo"),
                        "score": g.get("score"),
                        "claims": len(g.get("claims") or []),
                        "path": g.get("path"),
                    }
                )
            except GradeValidationError as e:
                errors.append(f"{p}[{i}] {item.get('repo', '?')}: {e}")
    return {
        "schema": "nexus.grade_validate/v1",
        "ok": not errors,
        "checked": checked,
        "passed": len(ok_grades),
        "errors": errors,
        "grades": ok_grades,
        "paths": [str(p) for p in paths],
    }


def smoke_search(
    workdir: Optional[Path | str] = None,
    *,
    queries: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Index fixtures + run canned searches (make mcp-smoke).

    Pass criteria: Markdown marketplace (wshobson) + deterministic decision
    package (2511.15755) must both hit.
    """
    root = _root(workdir)
    index_report = index_workspace(root)
    qs = list(
        queries
        or (
            "Markdown marketplace",
            "deterministic decision package",
        )
    )
    results: list[dict[str, Any]] = []
    missing: list[str] = []
    for q in qs:
        res = search_evidence(q, workdir=root, k=5)
        hits = res.get("hits") or []
        ok = bool(hits)
        # stronger checks for known pass criteria
        blob = json.dumps(hits).lower()
        if "markdown" in q.lower() and "marketplace" in q.lower():
            ok = ok and (
                "wshobson" in blob
                or "markdown" in blob
                and "marketplace" in blob
            )
        if "decision package" in q.lower() or "2511.15755" in q:
            ok = ok and (
                "2511.15755" in blob
                or "decision package" in blob
                or "deterministic" in blob
            )
        results.append(
            {
                "query": q,
                "ok": ok,
                "count": len(hits),
                "top": [
                    {
                        "id": h.get("id"),
                        "repo": h.get("repo"),
                        "arxiv_id": h.get("arxiv_id"),
                        "statement": (h.get("statement") or "")[:160],
                    }
                    for h in hits[:3]
                ],
            }
        )
        if not ok:
            missing.append(q)
    return {
        "schema": "nexus.mcp_smoke/v1",
        "ok": not missing and bool(index_report.get("ok")),
        "index": index_report,
        "searches": results,
        "missing": missing,
    }
