"""Immutable mine-eval grade ledger + stage checkpoints (First apply slice).

Prove: mine digests → Grok grade → durable retain (incl. weak scores) → report.

Patterns (shape only, not vendored trees):
- choihyunsus/soul — immutable append-only ledger
- ahmedEid1/lumen — keep weak scores public; content-hash idempotency
- IBM/AssetOpsBench — evaluation CLI over grades
- papers 2510.13343 / 2604.03350 — stage checkpoints so re-grade is skippable
- paper 2302.10809 / lumen — causal ``why_selected`` audit on export

Storage under workdir:
  ``.nexus_workspaces/mine_eval/ledger/grades.sqlite``

Schema (insert-only grades; update/delete rejected)::

  grades(id, run_id, repo, score, idea, skill, method, path, digest_path,
         summary, created_at, content_hash UNIQUE)
  UNIQUE(run_id, repo, method)  — no duplicate rows for same grade key

  stage_checkpoints(run_id, stage, payload, created_at, updated_at)
    PRIMARY KEY(run_id, stage)

Policy: **retain weak scores** — no score threshold on write.
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

SCHEMA_VERSION = "nexus.grade_ledger/v1"
DEFAULT_METHOD = "grok:grok-4.5"
DB_NAME = "grades.sqlite"
LEDGER_REL = Path(".nexus_workspaces") / "mine_eval" / "ledger"
CHECKPOINT_STAGE_GRADE = "grade"


class GradeLedgerError(RuntimeError):
    """Invalid or rejected grade-ledger operation."""


class ImmutableLedgerError(GradeLedgerError):
    """Update/delete of grades is forbidden (append-only)."""


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def ledger_dir(workdir: Optional[Path | str] = None) -> Path:
    d = _root(workdir) / LEDGER_REL
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


def grade_content_hash(
    *,
    run_id: str,
    repo: str,
    method: str,
    score: float,
    idea: float,
    skill: float,
    path: str = "",
) -> str:
    """Stable SHA-256 for idempotent append (run_id, repo, method + scores)."""
    payload = {
        "run_id": str(run_id or ""),
        "repo": str(repo or ""),
        "method": str(method or DEFAULT_METHOD),
        "score": float(score),
        "idea": float(idea),
        "skill": float(skill),
        "path": str(path or ""),
    }
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()


def why_selected(row: dict[str, Any]) -> str:
    """Causal audit stub: human-readable reason from score breakdown (2302.10809)."""
    repo = str(row.get("repo") or "?")
    score = row.get("score")
    idea = row.get("idea")
    skill = row.get("skill")
    method = str(row.get("method") or DEFAULT_METHOD)
    parts = [
        f"selected {repo}",
        f"score={score} (idea={idea}+skill={skill})",
        f"method={method}",
    ]
    summary = str(row.get("summary") or "").strip()
    if summary:
        snippet = summary.replace("\n", " ")[:160]
        parts.append(f"summary={snippet}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Stage checkpoints (P0.4)
# ---------------------------------------------------------------------------


def checkpoint_dir(workdir: Optional[Path | str] = None) -> Path:
    d = ledger_dir(workdir) / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d


def checkpoint_stage(
    run_id: str,
    stage: str,
    payload: Any,
    *,
    workdir: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Persist stage checkpoint; overwrites same (run_id, stage) payload.

    Used after the ``grade`` stage so restarts skip re-grading completed repos.
    Also written into SQLite via GradeLedger when open.
    """
    rid = str(run_id or "").strip()
    st = str(stage or "").strip()
    if not rid:
        raise GradeLedgerError("run_id required for checkpoint")
    if not st:
        raise GradeLedgerError("stage required for checkpoint")

    root = _root(workdir)
    rec = {
        "schema": SCHEMA_VERSION,
        "run_id": rid,
        "stage": st,
        "payload": payload,
        "updated_at": time.time(),
    }
    # File mirror (operator-friendly)
    path = checkpoint_dir(root) / f"{rid}__{st}.json"
    from .persist import atomic_write_json

    atomic_write_json(path, rec)

    # SQLite mirror when ledger exists / can open
    with GradeLedger.open(root) as led:
        led._upsert_checkpoint(rid, st, payload, rec["updated_at"])

    return rec


def load_checkpoint(
    run_id: str,
    stage: str,
    *,
    workdir: Optional[Path | str] = None,
) -> Optional[dict[str, Any]]:
    """Load checkpoint for (run_id, stage); prefer SQLite then file."""
    rid = str(run_id or "").strip()
    st = str(stage or "").strip()
    if not rid or not st:
        return None
    root = _root(workdir)
    with GradeLedger.open(root) as led:
        row = led.get_checkpoint(rid, st)
        if row is not None:
            return row
    path = checkpoint_dir(root) / f"{rid}__{st}.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            return None
    return None


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


@dataclass
class GradeLedger:
    """Append-only SQLite ledger for Grok mine grades (weak scores retained)."""

    workdir: Path
    conn: sqlite3.Connection

    @classmethod
    def open(cls, workdir: Optional[Path | str] = None) -> "GradeLedger":
        root = _root(workdir)
        path = db_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
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

    def __enter__(self) -> "GradeLedger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS grades (
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              repo TEXT NOT NULL,
              score REAL NOT NULL,
              idea REAL NOT NULL,
              skill REAL NOT NULL,
              method TEXT NOT NULL DEFAULT 'grok:grok-4.5',
              path TEXT NOT NULL DEFAULT '',
              digest_path TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              content_hash TEXT NOT NULL UNIQUE,
              UNIQUE(run_id, repo, method)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_grades_score ON grades(score DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_grades_run ON grades(run_id, created_at)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_checkpoints (
              run_id TEXT NOT NULL,
              stage TEXT NOT NULL,
              payload TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              PRIMARY KEY(run_id, stage)
            )
            """
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
        # Block accidental UPDATE/DELETE on grades (immutability guard)
        cur.execute("DROP TRIGGER IF EXISTS grades_no_update")
        cur.execute("DROP TRIGGER IF EXISTS grades_no_delete")
        cur.execute(
            """
            CREATE TRIGGER grades_no_update BEFORE UPDATE ON grades
            BEGIN
              SELECT RAISE(ABORT, 'grades are append-only; UPDATE forbidden');
            END
            """
        )
        cur.execute(
            """
            CREATE TRIGGER grades_no_delete BEFORE DELETE ON grades
            BEGIN
              SELECT RAISE(ABORT, 'grades are append-only; DELETE forbidden');
            END
            """
        )
        self.conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "repo": row["repo"],
            "score": float(row["score"]),
            "idea": float(row["idea"]),
            "skill": float(row["skill"]),
            "method": row["method"],
            "path": row["path"] or "",
            "digest_path": row["digest_path"] or "",
            "summary": row["summary"] or "",
            "created_at": float(row["created_at"]),
            "content_hash": row["content_hash"],
        }

    def append(
        self,
        *,
        run_id: str,
        repo: str,
        score: float,
        idea: float,
        skill: float,
        method: str = DEFAULT_METHOD,
        path: str = "",
        digest_path: str = "",
        summary: str = "",
        grade_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        """Append a grade. No score threshold (weak scores kept).

        Idempotent on (run_id, repo, method) and content_hash: re-append returns
        existing row without duplicating.
        """
        rid = str(run_id or "").strip()
        rname = str(repo or "").strip()
        if not rid:
            raise GradeLedgerError("run_id required")
        if not rname:
            raise GradeLedgerError("repo required")

        meth = str(method or DEFAULT_METHOD).strip() or DEFAULT_METHOD
        sc = float(score)
        ide = float(idea)
        sk = float(skill)
        pth = str(path or "")
        dig = str(digest_path or path or "")
        summ = str(summary or "")[:4000]
        ch = grade_content_hash(
            run_id=rid,
            repo=rname,
            method=meth,
            score=sc,
            idea=ide,
            skill=sk,
            path=pth,
        )

        # Prefer unique key lookup first (same run/repo/method)
        existing = self.conn.execute(
            "SELECT * FROM grades WHERE run_id=? AND repo=? AND method=?",
            (rid, rname, meth),
        ).fetchone()
        if existing is not None:
            return self._row_to_dict(existing)

        by_hash = self.conn.execute(
            "SELECT * FROM grades WHERE content_hash = ?", (ch,)
        ).fetchone()
        if by_hash is not None:
            return self._row_to_dict(by_hash)

        gid = str(grade_id or f"g-{uuid.uuid4().hex[:12]}")
        ts = float(created_at if created_at is not None else time.time())
        try:
            self.conn.execute(
                """
                INSERT INTO grades(
                  id, run_id, repo, score, idea, skill, method, path,
                  digest_path, summary, created_at, content_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (gid, rid, rname, sc, ide, sk, meth, pth, dig, summ, ts, ch),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            existing = self.conn.execute(
                "SELECT * FROM grades WHERE run_id=? AND repo=? AND method=?",
                (rid, rname, meth),
            ).fetchone()
            if existing is not None:
                return self._row_to_dict(existing)
            by_hash = self.conn.execute(
                "SELECT * FROM grades WHERE content_hash = ?", (ch,)
            ).fetchone()
            if by_hash is not None:
                return self._row_to_dict(by_hash)
            raise GradeLedgerError(
                f"append conflict for {rname} run={rid} method={meth}"
            ) from None

        row = self.conn.execute(
            "SELECT * FROM grades WHERE id = ?", (gid,)
        ).fetchone()
        if row is None:
            raise GradeLedgerError("append failed to persist")
        return self._row_to_dict(row)

    def append_from_grade(
        self,
        grade: dict[str, Any],
        *,
        run_id: str,
    ) -> dict[str, Any]:
        """Append from a nexus.grade/v1 or mine_eval dict."""
        idea = float(grade.get("idea") if grade.get("idea") is not None else 0)
        skill = float(grade.get("skill") if grade.get("skill") is not None else 0)
        score = grade.get("score")
        if score is None:
            score = idea + skill
        path = str(grade.get("path") or grade.get("local_path") or "")
        return self.append(
            run_id=run_id,
            repo=str(grade.get("repo") or ""),
            score=float(score),
            idea=idea,
            skill=skill,
            method=str(grade.get("method") or DEFAULT_METHOD),
            path=path,
            digest_path=str(grade.get("digest_path") or path),
            summary=str(
                grade.get("summary")
                or grade.get("description")
                or grade.get("pattern")
                or ""
            ),
        )

    def update(self, *args: Any, **kwargs: Any) -> None:
        """Rejected — grades are append-only (lumen/soul immutability)."""
        raise ImmutableLedgerError("grades are append-only; UPDATE forbidden")

    def delete(self, *args: Any, **kwargs: Any) -> None:
        """Rejected — grades are append-only."""
        raise ImmutableLedgerError("grades are append-only; DELETE forbidden")

    def get(self, grade_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM grades WHERE id = ?", (str(grade_id),)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list(
        self,
        *,
        run_id: Optional[str] = None,
        method: Optional[str] = None,
        limit: int = 500,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """List grades (weak included unless max_score/min_score filters query)."""
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(str(run_id))
        if method:
            clauses.append("method = ?")
            params.append(str(method))
        if min_score is not None:
            clauses.append("score >= ?")
            params.append(float(min_score))
        if max_score is not None:
            clauses.append("score <= ?")
            params.append(float(max_score))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM grades{where} "
            f"ORDER BY score DESC, created_at DESC LIMIT ?"
        )
        params.append(int(limit))
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def top(self, n: int = 10, *, run_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Top-N IMPROVE_OURS candidates by score."""
        return self.list(run_id=run_id, limit=max(1, int(n)))

    def weak(
        self,
        max_score: float = 14.0,
        *,
        run_id: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Grades at or below max_score (proves weak scores are retained)."""
        return self.list(
            run_id=run_id,
            max_score=float(max_score),
            limit=limit,
        )

    def count(self, *, run_id: Optional[str] = None) -> int:
        if run_id:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM grades WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM grades").fetchone()
        return int(row["c"] if row else 0)

    def _upsert_checkpoint(
        self,
        run_id: str,
        stage: str,
        payload: Any,
        ts: Optional[float] = None,
    ) -> None:
        now = float(ts if ts is not None else time.time())
        blob = _json_dumps(payload if payload is not None else {})
        existing = self.conn.execute(
            "SELECT created_at FROM stage_checkpoints WHERE run_id=? AND stage=?",
            (run_id, stage),
        ).fetchone()
        if existing is not None:
            self.conn.execute(
                """
                UPDATE stage_checkpoints
                SET payload=?, updated_at=?
                WHERE run_id=? AND stage=?
                """,
                (blob, now, run_id, stage),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO stage_checkpoints(
                  run_id, stage, payload, created_at, updated_at
                ) VALUES(?,?,?,?,?)
                """,
                (run_id, stage, blob, now, now),
            )
        self.conn.commit()

    def get_checkpoint(self, run_id: str, stage: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM stage_checkpoints WHERE run_id=? AND stage=?",
            (str(run_id), str(stage)),
        ).fetchone()
        if row is None:
            return None
        return {
            "schema": SCHEMA_VERSION,
            "run_id": row["run_id"],
            "stage": row["stage"],
            "payload": _json_loads(row["payload"]) or {},
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def export_md(
        self,
        *,
        n: int = 20,
        run_id: Optional[str] = None,
        include_weak: bool = True,
        weak_max: float = 14.0,
    ) -> str:
        """Markdown export for IMPROVE_OURS plan generation + why_selected audit."""
        top_rows = self.top(n=n, run_id=run_id)
        lines = [
            "# Improve *our* project from mined repos",
            "",
            f"_Generated by nexus grade export ({SCHEMA_VERSION})_",
            "",
            f"Target workdir: `{self.workdir}`",
            f"Sources (top {len(top_rows)} by score; weak scores retained):",
            "",
        ]
        for row in top_rows:
            lines.append(f"## {row['repo']} (score {row['score']})")
            lines.append(f"- idea={row['idea']} skill={row['skill']}")
            lines.append(f"- method=`{row['method']}`")
            if row.get("path"):
                lines.append(f"- path: `{row['path']}`")
            if row.get("summary"):
                lines.append(f"- {row['summary'][:500]}")
            lines.append(f"- **why_selected:** {why_selected(row)}")
            lines.append("")

        if include_weak:
            weak_rows = self.weak(max_score=weak_max, run_id=run_id, limit=50)
            # only those not already in top
            top_repos = {r["repo"] for r in top_rows}
            extras = [r for r in weak_rows if r["repo"] not in top_repos]
            if extras or weak_rows:
                lines.append("## Retained weak scores (lumen policy)")
                lines.append("")
                lines.append(
                    f"Grades with score ≤ {weak_max} are kept in the ledger "
                    "(not filtered on write)."
                )
                lines.append("")
                for row in weak_rows[:30]:
                    lines.append(
                        f"- **{row['repo']}** score={row['score']} "
                        f"(idea={row['idea']} skill={row['skill']}) "
                        f"`{row['method']}`"
                    )
                lines.append("")

        return "\n".join(lines) + "\n"

    def export_json(
        self,
        *,
        n: int = 100,
        run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        rows = self.list(run_id=run_id, limit=n)
        return {
            "schema": SCHEMA_VERSION,
            "count": len(rows),
            "grades": [
                {**r, "why_selected": why_selected(r)} for r in rows
            ],
        }


# ---------------------------------------------------------------------------
# Ingest digests → ledger
# ---------------------------------------------------------------------------


def ingest_grades(
    workdir: Optional[Path | str] = None,
    *,
    run_id: Optional[str] = None,
    fixture: Optional[Path | str] = None,
    min_score: float = 0.0,
    limit: int = 100,
) -> dict[str, Any]:
    """Load offline digests/fixtures into the append-only grade ledger.

    ``min_score`` only filters *source selection* for bulk load from IMPROVE_OURS;
    when a fixture is provided, all rows are ingested (weak retained).
    """
    root = _root(workdir)
    rid = str(run_id or f"ingest-{time.strftime('%Y%m%d%H%M%S')}")
    from .load_mine_eval import load_fixture_file, load_from_workdir

    if fixture is not None:
        grades = load_fixture_file(fixture)
    else:
        # min_score=0 for full retention when loading general digests
        grades = load_from_workdir(
            root, min_score=min_score, limit=limit, fixture=None
        )

    written: list[dict[str, Any]] = []
    with GradeLedger.open(root) as led:
        for g in grades:
            row = led.append_from_grade(g, run_id=rid)
            written.append(row)
        # Stage checkpoint after grade ingest (skip re-grade proof)
        payload = {
            "repos": [w["repo"] for w in written],
            "count": len(written),
            "methods": sorted({w["method"] for w in written}),
        }
        led._upsert_checkpoint(rid, CHECKPOINT_STAGE_GRADE, payload)

    # File checkpoint mirror (SQLite already updated)
    from .persist import atomic_write_json

    rec = {
        "schema": SCHEMA_VERSION,
        "run_id": rid,
        "stage": CHECKPOINT_STAGE_GRADE,
        "payload": payload,
        "updated_at": time.time(),
    }
    atomic_write_json(
        checkpoint_dir(root) / f"{rid}__{CHECKPOINT_STAGE_GRADE}.json", rec
    )

    return {
        "schema": SCHEMA_VERSION,
        "run_id": rid,
        "ingested": len(written),
        "repos": [w["repo"] for w in written],
        "db": str(db_path(root)),
        "checkpoint_stage": CHECKPOINT_STAGE_GRADE,
    }


def record_evaluate_results(
    results: list[dict[str, Any]],
    *,
    run_id: str,
    workdir: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Write mine ``step_evaluate`` results into the grade ledger + grade checkpoint.

    Skips entries already present for (run_id, repo, method). Safe to re-run.
    """
    root = _root(workdir)
    rid = str(run_id or "").strip() or f"eval-{int(time.time())}"
    written: list[str] = []
    skipped: list[str] = []
    prior_repos: set[str] = set()
    with GradeLedger.open(root) as led:
        # Resume: if checkpoint exists with same run_id, still allow merge
        prior = led.get_checkpoint(rid, CHECKPOINT_STAGE_GRADE)
        if prior and isinstance(prior.get("payload"), dict):
            prior_repos = {str(r) for r in (prior["payload"].get("repos") or []) if r}

        for entry in results:
            if "idea" not in entry or not entry.get("repo"):
                continue
            repo = str(entry["repo"])
            idea = float(entry["idea"])
            skill = float(entry["skill"])
            score = float(
                entry.get("score") if entry.get("score") is not None else idea + skill
            )
            method = str(entry.get("method") or DEFAULT_METHOD)
            # Check existing before append for skip reporting
            exists = led.conn.execute(
                "SELECT id FROM grades WHERE run_id=? AND repo=? AND method=?",
                (rid, repo, method),
            ).fetchone()
            if exists is not None:
                skipped.append(repo)
                continue
            led.append(
                run_id=rid,
                repo=repo,
                score=score,
                idea=idea,
                skill=skill,
                method=method,
                path=str(entry.get("path") or ""),
                digest_path=str(entry.get("path") or ""),
                summary=str(entry.get("description") or entry.get("summary") or ""),
            )
            written.append(repo)

        all_repos = sorted(prior_repos | set(written) | set(skipped))
        payload = {
            "repos": all_repos,
            "count": len(all_repos),
            "written": written,
            "skipped_duplicate": skipped,
        }
        led._upsert_checkpoint(rid, CHECKPOINT_STAGE_GRADE, payload)

    # File mirror only (SQLite already updated above)
    from .persist import atomic_write_json

    rec = {
        "schema": SCHEMA_VERSION,
        "run_id": rid,
        "stage": CHECKPOINT_STAGE_GRADE,
        "payload": payload,
        "updated_at": time.time(),
    }
    atomic_write_json(
        checkpoint_dir(root) / f"{rid}__{CHECKPOINT_STAGE_GRADE}.json", rec
    )
    return {
        "run_id": rid,
        "written": written,
        "skipped_duplicate": skipped,
        "repos": sorted(prior_repos | set(written) | set(skipped)),
        "db": str(db_path(root)),
    }


def graded_repos_from_checkpoint(
    run_id: str,
    *,
    workdir: Optional[Path | str] = None,
) -> set[str]:
    """Repos already graded for this run (for skip re-grade)."""
    cp = load_checkpoint(run_id, CHECKPOINT_STAGE_GRADE, workdir=workdir)
    if not cp:
        return set()
    payload = cp.get("payload") or {}
    if isinstance(payload, dict):
        return {str(r) for r in (payload.get("repos") or []) if r}
    return set()


# ---------------------------------------------------------------------------
# Formatting helpers (CLI)
# ---------------------------------------------------------------------------


def format_table(rows: list[dict[str, Any]], *, title: str = "") -> str:
    lines: list[str] = []
    if title:
        lines.append(title)
    if not rows:
        lines.append("(no grades)")
        return "\n".join(lines)
    lines.append(
        f"{'SCORE':>6}  {'IDEA':>5}  {'SKILL':>5}  {'METHOD':<16}  REPO"
    )
    for r in rows:
        lines.append(
            f"{r['score']:6.1f}  {r['idea']:5.1f}  {r['skill']:5.1f}  "
            f"{str(r['method'])[:16]:<16}  {r['repo']}"
        )
    return "\n".join(lines)


def format_export_with_audit(rows: list[dict[str, Any]]) -> str:
    lines = ["# Grade export (why_selected audit)", ""]
    for r in rows:
        lines.append(f"- **{r['repo']}** score={r['score']}: {why_selected(r)}")
    lines.append("")
    return "\n".join(lines)
