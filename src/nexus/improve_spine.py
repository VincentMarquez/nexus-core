"""First apply slice: mine → Grok grade → durable ledger → resume-safe stage.

Proves research/mine → grade → ledger → checkpoint resume → demo status without
rewriting the full orchestrator.

Schema (soul-inspired append-only SQLite)::

  work_ledger(id, ts, run_id, stage, agent, action, payload_json, parent_id)
  grade_records(id, repo_or_paper_id, score, idea, skill, method, summary,
                path, created_at, run_id, content_hash)

Stage machine::

  scouted → graded → apply_pending

Checkpoint JSON so a second process resumes from ``graded`` without re-ingest.

Patterns (shape only, not vendored trees):
- choihyunsus/soul — immutable work ledger
- codingagentsystem/cas — SQLite MCP context
- ahmedEid1/lumen — phase-gated migrations + grade retain
- papers 2510.13343 / 2604.03350 — ordered stages + skip re-grade on resume
- arXiv 2302.10809 — causal-ish status export for demos

Storage: ``.nexus_workspaces/improve_spine/spine.sqlite``
Checkpoint: ``.nexus_workspaces/improve_spine/checkpoints/{run_id}.json``
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
from typing import Any, Optional, Sequence

SCHEMA_VERSION = "nexus.improve_spine/v1"
DB_NAME = "spine.sqlite"
SPINE_REL = Path(".nexus_workspaces") / "improve_spine"
DEFAULT_METHOD = "grok:grok-4.5"
DEFAULT_FIXTURE_REL = Path("tests") / "fixtures" / "mine_eval_sample.json"

# Ordered stage machine (plan §5)
STAGE_SCOUTED = "scouted"
STAGE_GRADED = "graded"
STAGE_APPLY_PENDING = "apply_pending"
STAGES: tuple[str, ...] = (STAGE_SCOUTED, STAGE_GRADED, STAGE_APPLY_PENDING)
STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}

DEFAULT_AGENTS = {
    STAGE_SCOUTED: "scout:mine",
    STAGE_GRADED: "grok:grade",
    STAGE_APPLY_PENDING: "worker:apply",
}


class SpineError(RuntimeError):
    """Invalid improve-spine operation."""


class ImmutableError(SpineError):
    """Update/delete of ledger or grade rows is forbidden."""


class StageError(SpineError):
    """Illegal stage transition or missing checkpoint."""


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def spine_dir(workdir: Optional[Path | str] = None) -> Path:
    d = _root(workdir) / SPINE_REL
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path(workdir: Optional[Path | str] = None) -> Path:
    return spine_dir(workdir) / DB_NAME


def checkpoint_dir(workdir: Optional[Path | str] = None) -> Path:
    d = spine_dir(workdir) / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d


def checkpoint_path(run_id: str, workdir: Optional[Path | str] = None) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(run_id))
    return checkpoint_dir(workdir) / f"{safe}.json"


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


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def grade_content_hash(
    *,
    run_id: str,
    repo_or_paper_id: str,
    method: str,
    score: float,
    idea: float,
    skill: float,
    path: str = "",
) -> str:
    payload = {
        "run_id": str(run_id or ""),
        "repo_or_paper_id": str(repo_or_paper_id or ""),
        "method": str(method or DEFAULT_METHOD),
        "score": float(score),
        "idea": float(idea),
        "skill": float(skill),
        "path": str(path or ""),
    }
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()


def ledger_content_hash(
    *,
    run_id: str,
    stage: str,
    agent: str,
    action: str,
    payload: dict[str, Any],
    parent_id: str = "",
) -> str:
    blob = _json_dumps(
        {
            "run_id": str(run_id or ""),
            "stage": str(stage or ""),
            "agent": str(agent or ""),
            "action": str(action or ""),
            "payload": payload or {},
            "parent_id": str(parent_id or ""),
        }
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@dataclass
class ImproveSpine:
    """Append-only work_ledger + grade_records with stage checkpoints."""

    workdir: Path
    conn: sqlite3.Connection

    @classmethod
    def open(cls, workdir: Optional[Path | str] = None) -> "ImproveSpine":
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

    def __enter__(self) -> "ImproveSpine":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS work_ledger (
              id TEXT PRIMARY KEY,
              ts REAL NOT NULL,
              run_id TEXT NOT NULL,
              stage TEXT NOT NULL,
              agent TEXT NOT NULL,
              action TEXT NOT NULL,
              payload_json TEXT NOT NULL DEFAULT '{}',
              parent_id TEXT NOT NULL DEFAULT '',
              content_hash TEXT NOT NULL UNIQUE
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_spine_ledger_run "
            "ON work_ledger(run_id, ts, id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_spine_ledger_stage "
            "ON work_ledger(stage, ts)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS grade_records (
              id TEXT PRIMARY KEY,
              repo_or_paper_id TEXT NOT NULL,
              score REAL NOT NULL,
              idea REAL NOT NULL,
              skill REAL NOT NULL,
              method TEXT NOT NULL DEFAULT 'grok:grok-4.5',
              summary TEXT NOT NULL DEFAULT '',
              path TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              run_id TEXT NOT NULL DEFAULT '',
              content_hash TEXT NOT NULL UNIQUE
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_spine_grade_repo "
            "ON grade_records(repo_or_paper_id, score DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_spine_grade_run "
            "ON grade_records(run_id, created_at)"
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
        # Append-only guards (soul pattern)
        for table in ("work_ledger", "grade_records"):
            cur.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            cur.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
            cur.execute(
                f"""
                CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table}
                BEGIN
                  SELECT RAISE(ABORT, '{table} is append-only; UPDATE forbidden');
                END
                """
            )
            cur.execute(
                f"""
                CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
                BEGIN
                  SELECT RAISE(ABORT, '{table} is append-only; DELETE forbidden');
                END
                """
            )
        self.conn.commit()

    # -- row helpers --------------------------------------------------------

    def _ledger_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "ts": float(row["ts"]),
            "run_id": row["run_id"],
            "stage": row["stage"],
            "agent": row["agent"],
            "action": row["action"],
            "payload_json": _json_loads(row["payload_json"]) or {},
            "parent_id": row["parent_id"] or "",
            "content_hash": row["content_hash"],
        }

    def _grade_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "repo_or_paper_id": row["repo_or_paper_id"],
            "score": float(row["score"]),
            "idea": float(row["idea"]),
            "skill": float(row["skill"]),
            "method": row["method"] or DEFAULT_METHOD,
            "summary": row["summary"] or "",
            "path": row["path"] or "",
            "created_at": float(row["created_at"]),
            "run_id": row["run_id"] or "",
            "content_hash": row["content_hash"],
        }

    # -- ledger.append / ledger.list ----------------------------------------

    def append(
        self,
        *,
        run_id: str,
        stage: str,
        agent: str,
        action: str,
        payload: Optional[dict[str, Any]] = None,
        parent_id: str = "",
        event_id: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> dict[str, Any]:
        """Append one work_ledger row. Idempotent on content_hash.

        No update/delete API — second append of different payload gets new id.
        """
        rid = str(run_id or "").strip()
        st = str(stage or "").strip()
        ag = str(agent or "").strip()
        act = str(action or "").strip()
        if not rid:
            raise SpineError("run_id required")
        if not st:
            raise SpineError("stage required")
        if not ag:
            raise SpineError("agent required")
        if not act:
            raise SpineError("action required")
        if st not in STAGE_ORDER and st not in ("done", "verify", "promote"):
            # allow known stages + future extensions used in payload demos
            pass
        payload_d = dict(payload or {})
        ch = ledger_content_hash(
            run_id=rid,
            stage=st,
            agent=ag,
            action=act,
            payload=payload_d,
            parent_id=str(parent_id or ""),
        )
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM work_ledger WHERE content_hash = ?", (ch,)
        )
        existing = cur.fetchone()
        if existing is not None:
            return self._ledger_row(existing)

        eid = str(event_id or _new_id())
        when = float(ts if ts is not None else time.time())
        try:
            cur.execute(
                """
                INSERT INTO work_ledger(
                  id, ts, run_id, stage, agent, action,
                  payload_json, parent_id, content_hash
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    eid,
                    when,
                    rid,
                    st,
                    ag,
                    act,
                    _json_dumps(payload_d),
                    str(parent_id or ""),
                    ch,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            cur.execute(
                "SELECT * FROM work_ledger WHERE content_hash = ?", (ch,)
            )
            row = cur.fetchone()
            if row is not None:
                return self._ledger_row(row)
            raise
        cur.execute("SELECT * FROM work_ledger WHERE id = ?", (eid,))
        row = cur.fetchone()
        assert row is not None
        return self._ledger_row(row)

    def list(
        self,
        *,
        run_id: Optional[str] = None,
        limit: int = 50,
        stage: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List work_ledger events (oldest→newest within the window)."""
        lim = max(1, min(int(limit or 50), 500))
        cur = self.conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(str(run_id))
        if stage:
            clauses.append("stage = ?")
            params.append(str(stage))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        # fetch last N then reverse so callers see chronological order
        cur.execute(
            f"""
            SELECT * FROM (
              SELECT * FROM work_ledger{where}
              ORDER BY ts DESC, id DESC
              LIMIT ?
            ) AS recent
            ORDER BY ts ASC, id ASC
            """,
            (*params, lim),
        )
        return [self._ledger_row(r) for r in cur.fetchall()]

    def get_event(self, event_id: str) -> Optional[dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM work_ledger WHERE id = ?", (str(event_id),))
        row = cur.fetchone()
        return self._ledger_row(row) if row else None

    def try_update_ledger_forbidden(self, event_id: str) -> None:
        """Test helper: attempt UPDATE (must fail)."""
        try:
            self.conn.execute(
                "UPDATE work_ledger SET agent = ? WHERE id = ?",
                ("mutated", str(event_id)),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise ImmutableError(str(e)) from e

    def try_delete_ledger_forbidden(self, event_id: str) -> None:
        """Test helper: attempt DELETE (must fail)."""
        try:
            self.conn.execute(
                "DELETE FROM work_ledger WHERE id = ?", (str(event_id),)
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise ImmutableError(str(e)) from e

    # -- grade.get / record -------------------------------------------------

    def record_grade(
        self,
        *,
        repo_or_paper_id: str,
        score: float,
        idea: float,
        skill: float,
        method: str = DEFAULT_METHOD,
        summary: str = "",
        path: str = "",
        run_id: str = "",
        grade_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        """Insert one grade_records row. Idempotent on content_hash."""
        rid = str(repo_or_paper_id or "").strip()
        if not rid:
            raise SpineError("repo_or_paper_id required")
        method_s = str(method or DEFAULT_METHOD)
        ch = grade_content_hash(
            run_id=str(run_id or ""),
            repo_or_paper_id=rid,
            method=method_s,
            score=float(score),
            idea=float(idea),
            skill=float(skill),
            path=str(path or ""),
        )
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM grade_records WHERE content_hash = ?", (ch,)
        )
        existing = cur.fetchone()
        if existing is not None:
            return self._grade_row(existing)

        gid = str(grade_id or _new_id())
        when = float(created_at if created_at is not None else time.time())
        try:
            cur.execute(
                """
                INSERT INTO grade_records(
                  id, repo_or_paper_id, score, idea, skill, method,
                  summary, path, created_at, run_id, content_hash
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    gid,
                    rid,
                    float(score),
                    float(idea),
                    float(skill),
                    method_s,
                    str(summary or ""),
                    str(path or ""),
                    when,
                    str(run_id or ""),
                    ch,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            cur.execute(
                "SELECT * FROM grade_records WHERE content_hash = ?", (ch,)
            )
            row = cur.fetchone()
            if row is not None:
                return self._grade_row(row)
            raise
        cur.execute("SELECT * FROM grade_records WHERE id = ?", (gid,))
        row = cur.fetchone()
        assert row is not None
        return self._grade_row(row)

    def get_grade(
        self,
        repo_or_paper_id: str,
        *,
        run_id: Optional[str] = None,
        method: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Fetch latest matching grade (plan MCP grade.get)."""
        rid = str(repo_or_paper_id or "").strip()
        if not rid:
            return None
        cur = self.conn.cursor()
        clauses = ["repo_or_paper_id = ?"]
        params: list[Any] = [rid]
        if run_id:
            clauses.append("run_id = ?")
            params.append(str(run_id))
        if method:
            clauses.append("method = ?")
            params.append(str(method))
        where = " AND ".join(clauses)
        cur.execute(
            f"""
            SELECT * FROM grade_records
            WHERE {where}
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            params,
        )
        row = cur.fetchone()
        return self._grade_row(row) if row else None

    def list_grades(
        self,
        *,
        run_id: Optional[str] = None,
        limit: int = 50,
        min_score: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit or 50), 500))
        cur = self.conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(str(run_id))
        if min_score is not None:
            clauses.append("score >= ?")
            params.append(float(min_score))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(
            f"""
            SELECT * FROM grade_records{where}
            ORDER BY score DESC, created_at DESC
            LIMIT ?
            """,
            (*params, lim),
        )
        return [self._grade_row(r) for r in cur.fetchall()]

    def count_grades(self, *, run_id: Optional[str] = None) -> int:
        cur = self.conn.cursor()
        if run_id:
            cur.execute(
                "SELECT COUNT(*) AS n FROM grade_records WHERE run_id = ?",
                (str(run_id),),
            )
        else:
            cur.execute("SELECT COUNT(*) AS n FROM grade_records")
        return int(cur.fetchone()["n"])

    def count_ledger(self, *, run_id: Optional[str] = None) -> int:
        cur = self.conn.cursor()
        if run_id:
            cur.execute(
                "SELECT COUNT(*) AS n FROM work_ledger WHERE run_id = ?",
                (str(run_id),),
            )
        else:
            cur.execute("SELECT COUNT(*) AS n FROM work_ledger")
        return int(cur.fetchone()["n"])


# ---------------------------------------------------------------------------
# Checkpoint / stage machine
# ---------------------------------------------------------------------------


def save_checkpoint(
    run_id: str,
    stage: str,
    *,
    workdir: Optional[Path | str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Write JSON checkpoint for resume (overwrites same run_id)."""
    rid = str(run_id or "").strip()
    st = str(stage or "").strip()
    if not rid:
        raise SpineError("run_id required for checkpoint")
    if st not in STAGE_ORDER:
        raise StageError(f"unknown stage for checkpoint: {st}; want {list(STAGES)}")
    rec = {
        "schema": SCHEMA_VERSION,
        "run_id": rid,
        "stage": st,
        "updated_at": time.time(),
        "stages": list(STAGES),
    }
    if extra:
        rec["extra"] = dict(extra)
    path = checkpoint_path(rid, workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return rec


def load_checkpoint(
    run_id: str,
    *,
    workdir: Optional[Path | str] = None,
) -> Optional[dict[str, Any]]:
    path = checkpoint_path(run_id, workdir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def next_stage(current: Optional[str]) -> Optional[str]:
    if current is None or current == "":
        return STAGE_SCOUTED
    if current not in STAGE_ORDER:
        return None
    idx = STAGE_ORDER[current]
    if idx + 1 >= len(STAGES):
        return None
    return STAGES[idx + 1]


# ---------------------------------------------------------------------------
# Ingest mine_eval (offline, no network)
# ---------------------------------------------------------------------------


def _normalize_grade_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Map fixture / IMPROVE_OURS-shaped dict → grade_records fields."""
    repo = str(
        raw.get("repo_or_paper_id")
        or raw.get("repo")
        or raw.get("paper_id")
        or raw.get("id")
        or ""
    ).strip()
    if not repo:
        raise SpineError("grade row missing repo / repo_or_paper_id")
    path = str(raw.get("path") or raw.get("local_path") or "").strip()
    if not path:
        path = f".nexus_workspaces/mine_eval/{repo.replace('/', '__')}"
    return {
        "repo_or_paper_id": repo,
        "score": float(raw.get("score") if raw.get("score") is not None else 0),
        "idea": float(raw.get("idea") if raw.get("idea") is not None else 0),
        "skill": float(raw.get("skill") if raw.get("skill") is not None else 0),
        "method": str(raw.get("method") or DEFAULT_METHOD),
        "summary": str(
            raw.get("summary") or raw.get("excerpt") or raw.get("pattern") or ""
        ),
        "path": path,
    }


def load_mine_eval_grades(
    source: Optional[Path | str] = None,
    *,
    workdir: Optional[Path | str] = None,
    repo: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Load grades from fixture JSON or a mine_eval digest path.

    Prefer explicit ``source``; else ``tests/fixtures/mine_eval_sample.json``.
    No network.
    """
    root = _root(workdir)
    path: Optional[Path] = Path(source).resolve() if source else None
    if path is None:
        candidate = root / DEFAULT_FIXTURE_REL
        if candidate.is_file():
            path = candidate
    if path is None or not path.is_file():
        # fallback: single-repo path under mine_eval is a clone, not a grade file —
        # use fixture or IMPROVE_OURS is out of scope; raise clearly
        raise SpineError(
            f"mine_eval grade source not found: {source or DEFAULT_FIXTURE_REL}"
        )

    raw = json.loads(path.read_text(encoding="utf-8"))
    items: list[Any]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        if isinstance(raw.get("grades"), list):
            items = raw["grades"]
        elif isinstance(raw.get("candidates"), list):
            items = raw["candidates"]
        elif "repo" in raw or "repo_or_paper_id" in raw or "score" in raw:
            items = [raw]
        else:
            raise SpineError(f"unrecognized mine_eval shape in {path}")
    else:
        raise SpineError(f"mine_eval must be object or list: {path}")

    out: list[dict[str, Any]] = []
    want = str(repo or "").strip().lower()
    for item in items:
        if not isinstance(item, dict):
            continue
        g = _normalize_grade_row(item)
        g["_source"] = str(path)
        if want and g["repo_or_paper_id"].lower() != want:
            # also match suffix forms codingagentsystem/cas vs codingagentsystem__cas
            alt = g["repo_or_paper_id"].replace("__", "/").lower()
            if want not in (alt, g["repo_or_paper_id"].lower()):
                continue
        out.append(g)
    if want and not out:
        raise SpineError(f"repo {repo!r} not found in {path}")
    return out


def ingest_mine_eval(
    workdir: Optional[Path | str] = None,
    *,
    run_id: Optional[str] = None,
    source: Optional[Path | str] = None,
    repo: Optional[str] = None,
    agent_scout: str = DEFAULT_AGENTS[STAGE_SCOUTED],
    agent_grade: str = DEFAULT_AGENTS[STAGE_GRADED],
    advance_to_apply_pending: bool = True,
) -> dict[str, Any]:
    """Ingest one mine_eval path into ledger + grade_records.

    Resume-safe: if checkpoint is already ``graded`` or beyond, skip re-ingest
    of grades (no duplicate grade rows).
    """
    root = _root(workdir)
    rid = str(run_id or f"spine-{_new_id()[:10]}").strip()
    cp = load_checkpoint(rid, workdir=root)
    current = str(cp.get("stage") or "") if cp else ""

    with ImproveSpine.open(root) as store:
        # Resume from graded+: do not re-ingest grades
        if current in (STAGE_GRADED, STAGE_APPLY_PENDING):
            grades = store.list_grades(run_id=rid, limit=100)
            events = store.list(run_id=rid, limit=100)
            if advance_to_apply_pending and current == STAGE_GRADED:
                parent = events[-1]["id"] if events else ""
                ev = store.append(
                    run_id=rid,
                    stage=STAGE_APPLY_PENDING,
                    agent=DEFAULT_AGENTS[STAGE_APPLY_PENDING],
                    action="mark_apply_pending",
                    payload={
                        "from_checkpoint": True,
                        "grade_count": len(grades),
                    },
                    parent_id=parent,
                )
                save_checkpoint(
                    rid,
                    STAGE_APPLY_PENDING,
                    workdir=root,
                    extra={"grade_ids": [g["id"] for g in grades]},
                )
                events = store.list(run_id=rid, limit=100)
                return {
                    "schema": SCHEMA_VERSION,
                    "ok": True,
                    "resumed": True,
                    "run_id": rid,
                    "stage": STAGE_APPLY_PENDING,
                    "grades": grades,
                    "ledger": events,
                    "ingested": 0,
                    "last_event": ev,
                }
            return {
                "schema": SCHEMA_VERSION,
                "ok": True,
                "resumed": True,
                "run_id": rid,
                "stage": current or STAGE_APPLY_PENDING,
                "grades": grades,
                "ledger": events,
                "ingested": 0,
            }

        rows = load_mine_eval_grades(source, workdir=root, repo=repo)
        if not rows:
            raise SpineError("no grades to ingest")
        # Prefer highest score when multiple and no repo filter
        if repo is None and len(rows) > 1:
            rows = sorted(rows, key=lambda r: float(r["score"]), reverse=True)[:1]

        parent = ""
        scout_ev = store.append(
            run_id=rid,
            stage=STAGE_SCOUTED,
            agent=agent_scout,
            action="ingest_mine_eval",
            payload={
                "source": rows[0].get("_source"),
                "repos": [r["repo_or_paper_id"] for r in rows],
            },
            parent_id=parent,
        )
        parent = scout_ev["id"]
        save_checkpoint(
            rid,
            STAGE_SCOUTED,
            workdir=root,
            extra={"repos": [r["repo_or_paper_id"] for r in rows]},
        )

        grade_rows: list[dict[str, Any]] = []
        for r in rows:
            g = store.record_grade(
                repo_or_paper_id=r["repo_or_paper_id"],
                score=r["score"],
                idea=r["idea"],
                skill=r["skill"],
                method=r["method"],
                summary=r["summary"],
                path=r["path"],
                run_id=rid,
            )
            grade_rows.append(g)
            g_ev = store.append(
                run_id=rid,
                stage=STAGE_GRADED,
                agent=agent_grade,
                action="record_grade",
                payload={
                    "grade_id": g["id"],
                    "repo_or_paper_id": g["repo_or_paper_id"],
                    "score": g["score"],
                    "idea": g["idea"],
                    "skill": g["skill"],
                    "method": g["method"],
                },
                parent_id=parent,
            )
            parent = g_ev["id"]

        save_checkpoint(
            rid,
            STAGE_GRADED,
            workdir=root,
            extra={"grade_ids": [g["id"] for g in grade_rows]},
        )

        stage = STAGE_GRADED
        last_ev = store.get_event(parent) or scout_ev
        if advance_to_apply_pending:
            last_ev = store.append(
                run_id=rid,
                stage=STAGE_APPLY_PENDING,
                agent=DEFAULT_AGENTS[STAGE_APPLY_PENDING],
                action="mark_apply_pending",
                payload={
                    "grade_ids": [g["id"] for g in grade_rows],
                    "top_score": max(float(g["score"]) for g in grade_rows),
                },
                parent_id=parent,
            )
            stage = STAGE_APPLY_PENDING
            save_checkpoint(
                rid,
                STAGE_APPLY_PENDING,
                workdir=root,
                extra={"grade_ids": [g["id"] for g in grade_rows]},
            )

        return {
            "schema": SCHEMA_VERSION,
            "ok": True,
            "resumed": False,
            "run_id": rid,
            "stage": stage,
            "grades": grade_rows,
            "ledger": store.list(run_id=rid, limit=100),
            "ingested": len(grade_rows),
            "last_event": last_ev,
            "source": rows[0].get("_source"),
        }


def run_first_slice(
    workdir: Optional[Path | str] = None,
    *,
    run_id: Optional[str] = None,
    source: Optional[Path | str] = None,
    repo: str = "codingagentsystem/cas",
    stop_after: Optional[str] = None,
) -> dict[str, Any]:
    """End-to-end first-slice runner with optional early stop for resume tests.

    ``stop_after`` ∈ {scouted, graded, apply_pending, None}.
    When ``stop_after=graded``, leaves checkpoint at graded so resume continues.
    """
    root = _root(workdir)
    rid = str(run_id or f"demo-{_new_id()[:8]}").strip()
    stop = str(stop_after or "").strip() or None

    if stop == STAGE_SCOUTED:
        # only scout ledger row + checkpoint
        rows = load_mine_eval_grades(source, workdir=root, repo=repo)
        if not rows:
            raise SpineError("no grades")
        with ImproveSpine.open(root) as store:
            ev = store.append(
                run_id=rid,
                stage=STAGE_SCOUTED,
                agent=DEFAULT_AGENTS[STAGE_SCOUTED],
                action="ingest_mine_eval",
                payload={
                    "source": rows[0].get("_source"),
                    "repos": [r["repo_or_paper_id"] for r in rows],
                    "stop_after": STAGE_SCOUTED,
                },
            )
        save_checkpoint(
            rid, STAGE_SCOUTED, workdir=root, extra={"repos": [rows[0]["repo_or_paper_id"]]}
        )
        return {
            "schema": SCHEMA_VERSION,
            "ok": True,
            "run_id": rid,
            "stage": STAGE_SCOUTED,
            "stopped_after": STAGE_SCOUTED,
            "ledger": [ev],
            "grades": [],
            "ingested": 0,
        }

    advance = stop != STAGE_GRADED
    result = ingest_mine_eval(
        root,
        run_id=rid,
        source=source,
        repo=repo,
        advance_to_apply_pending=advance,
    )
    if stop == STAGE_GRADED:
        result["stopped_after"] = STAGE_GRADED
    return result


def status(
    workdir: Optional[Path | str] = None,
    *,
    run_id: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Status for CLI ``nexus improve status --run <id>``."""
    root = _root(workdir)
    rid = str(run_id or "").strip()
    if not rid:
        raise SpineError("run_id required")
    cp = load_checkpoint(rid, workdir=root)
    with ImproveSpine.open(root) as store:
        events = store.list(run_id=rid, limit=limit)
        grades = store.list_grades(run_id=rid, limit=limit)
    stage = str(cp.get("stage") if cp else (events[-1]["stage"] if events else ""))
    last_grade = grades[0] if grades else None
    # grades list is score-desc; for "last" prefer latest created_at
    if grades:
        last_grade = max(grades, key=lambda g: float(g.get("created_at") or 0))
    return {
        "schema": SCHEMA_VERSION,
        "run_id": rid,
        "stage": stage,
        "checkpoint": cp,
        "grade_count": len(grades),
        "ledger_count": len(events),
        "last_grade": last_grade,
        "grades": grades,
        "ledger": events,
        "ok": bool(events or grades or cp),
    }


def format_status(report: dict[str, Any]) -> str:
    """Human-readable status (routa/mission-control evidence lite)."""
    lines = [
        f"improve spine  schema={report.get('schema')}",
        f"run_id={report.get('run_id')}  stage={report.get('stage') or '—'}",
        f"ledger_events={report.get('ledger_count', 0)}  grades={report.get('grade_count', 0)}",
    ]
    g = report.get("last_grade") or {}
    if g:
        lines.append(
            f"last_grade: {g.get('repo_or_paper_id')}  "
            f"score={g.get('score')}  idea={g.get('idea')}  skill={g.get('skill')}  "
            f"method={g.get('method')}"
        )
        if g.get("summary"):
            snip = str(g["summary"]).replace("\n", " ")[:120]
            lines.append(f"  summary: {snip}")
        if g.get("path"):
            lines.append(f"  path: {g.get('path')}")
    else:
        lines.append("last_grade: (none)")
    events: Sequence[dict[str, Any]] = report.get("ledger") or []
    if events:
        lines.append("ledger (recent):")
        for ev in events[-10:]:
            lines.append(
                f"  [{ev.get('stage')}] {ev.get('action')}  "
                f"agent={ev.get('agent')}  id={ev.get('id')}"
            )
    else:
        lines.append("ledger: (empty)")
    cp = report.get("checkpoint")
    if cp:
        lines.append(f"checkpoint: stage={cp.get('stage')}  updated_at={cp.get('updated_at')}")
    return "\n".join(lines)


def format_ingest_report(report: dict[str, Any]) -> str:
    lines = [
        f"improve spine ingest  ok={report.get('ok')}  resumed={report.get('resumed')}",
        f"run_id={report.get('run_id')}  stage={report.get('stage')}  "
        f"ingested={report.get('ingested')}",
    ]
    for g in report.get("grades") or []:
        lines.append(
            f"  grade {g.get('repo_or_paper_id')} score={g.get('score')} "
            f"method={g.get('method')}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP thin wrappers (ledger.append / ledger.list / grade.get)
# ---------------------------------------------------------------------------


def mcp_ledger_append(
    workdir: Optional[Path | str],
    *,
    run_id: str,
    stage: str,
    agent: str,
    action: str,
    payload: Optional[dict[str, Any]] = None,
    parent_id: str = "",
) -> dict[str, Any]:
    with ImproveSpine.open(workdir) as store:
        return store.append(
            run_id=run_id,
            stage=stage,
            agent=agent,
            action=action,
            payload=payload,
            parent_id=parent_id,
        )


def mcp_ledger_list(
    workdir: Optional[Path | str],
    *,
    run_id: Optional[str] = None,
    limit: int = 50,
    stage: Optional[str] = None,
) -> dict[str, Any]:
    with ImproveSpine.open(workdir) as store:
        rows = store.list(run_id=run_id, limit=limit, stage=stage)
    return {
        "schema": SCHEMA_VERSION,
        "run_id": run_id,
        "count": len(rows),
        "events": rows,
    }


def mcp_grade_get(
    workdir: Optional[Path | str],
    *,
    repo_or_paper_id: str,
    run_id: Optional[str] = None,
    method: Optional[str] = None,
) -> dict[str, Any]:
    with ImproveSpine.open(workdir) as store:
        g = store.get_grade(repo_or_paper_id, run_id=run_id, method=method)
    return {
        "schema": SCHEMA_VERSION,
        "found": g is not None,
        "grade": g,
    }
