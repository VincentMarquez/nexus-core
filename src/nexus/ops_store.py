"""Mission-control-style SQLite ops plane: jobs + spend.

P1.1 from docs/LATEST_IMPROVE_PLAN.md — track mine / alive / research /
github / improve / durable-task jobs with token spend and status for
operator list/show (pattern: builderz-labs/mission-control task-costs +
task status; not a vendored tree).

Storage: ``.nexus_state/ops/ops.sqlite`` under the project workdir.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_NAME = "ops.sqlite"
SCHEMA_VERSION = "nexus.ops/v1"

JOB_KINDS = frozenset(
    {
        "mine",
        "alive",
        "research",
        "github",
        "improve",
        "task",
        "other",
    }
)

# Mission-control-inspired statuses (simplified).
JOB_STATUSES = frozenset(
    {
        "inbox",
        "running",
        "blocked",
        "completed",
        "failed",
        "cancelled",
    }
)

# Rough USD per 1k tokens for display rollups (operator estimate only).
DEFAULT_USD_PER_1K = 0.0


class OpsError(RuntimeError):
    """Invalid ops-plane operation."""


def _root(workdir: Optional[Path | str] = None) -> Path:
    import os

    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def ops_dir(workdir: Optional[Path | str] = None) -> Path:
    d = _root(workdir) / ".nexus_state" / "ops"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path(workdir: Optional[Path | str] = None) -> Path:
    return ops_dir(workdir) / DB_NAME


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, separators=(",", ":"))


def _json_loads(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def calculate_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Mission-control ``calculateStats`` shape for spend rows."""
    if not records:
        return {
            "total_tokens": 0,
            "total_cost": 0.0,
            "request_count": 0,
            "avg_tokens_per_request": 0,
            "avg_cost_per_request": 0.0,
        }
    total_tokens = sum(int(r.get("tokens") or 0) for r in records)
    total_cost = sum(float(r.get("cost") or 0.0) for r in records)
    n = len(records)
    return {
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "request_count": n,
        "avg_tokens_per_request": round(total_tokens / n) if n else 0,
        "avg_cost_per_request": round(total_cost / n, 6) if n else 0.0,
    }


def estimate_cost(tokens: int, *, usd_per_1k: float = DEFAULT_USD_PER_1K) -> float:
    """Optional cost estimate; default 0 (local/unknown pricing)."""
    try:
        rate = float(usd_per_1k or 0.0)
    except (TypeError, ValueError):
        rate = 0.0
    return round(max(0, int(tokens)) * rate / 1000.0, 6)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@dataclass
class OpsStore:
    """SQLite-backed control plane for jobs + attributed spend."""

    workdir: Path
    conn: sqlite3.Connection

    @classmethod
    def open(cls, workdir: Optional[Path | str] = None) -> "OpsStore":
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

    def __enter__(self) -> "OpsStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL DEFAULT 'other',
              title TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'inbox',
              goal TEXT NOT NULL DEFAULT '',
              tokens INTEGER NOT NULL DEFAULT 0,
              cost REAL NOT NULL DEFAULT 0.0,
              meta TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS spend (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL,
              tokens INTEGER NOT NULL DEFAULT 0,
              cost REAL NOT NULL DEFAULT 0.0,
              source TEXT NOT NULL DEFAULT '',
              label TEXT NOT NULL DEFAULT '',
              ts REAL NOT NULL,
              meta TEXT NOT NULL DEFAULT '{}',
              FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_spend_job ON spend(job_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_kind_status ON jobs(kind, status)"
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

    # -- jobs ---------------------------------------------------------------

    def upsert_job(
        self,
        job_id: str,
        *,
        kind: str = "other",
        title: str = "",
        status: str = "inbox",
        goal: str = "",
        meta: Optional[dict[str, Any]] = None,
        tokens: Optional[int] = None,
        cost: Optional[float] = None,
    ) -> dict[str, Any]:
        """Create or update a job row. Existing fields preserved when not passed."""
        jid = str(job_id or "").strip()
        if not jid:
            raise OpsError("job_id required")
        k = str(kind or "other").strip().lower()
        if k not in JOB_KINDS:
            k = "other"
        st = str(status or "inbox").strip().lower()
        if st not in JOB_STATUSES:
            raise OpsError(f"invalid status: {status!r}")

        now = time.time()
        existing = self.conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (jid,)
        ).fetchone()
        if existing is None:
            self.conn.execute(
                """
                INSERT INTO jobs(id, kind, title, status, goal, tokens, cost, meta, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    jid,
                    k,
                    title or jid,
                    st,
                    goal or "",
                    int(tokens or 0),
                    float(cost or 0.0),
                    _json_dumps(meta or {}),
                    now,
                    now,
                ),
            )
        else:
            new_meta = _json_loads(existing["meta"])
            if meta:
                new_meta.update(meta)
            # Preserve kind/title/goal when caller uses defaults only.
            next_kind = k if (kind and str(kind).strip().lower() in JOB_KINDS and (
                kind != "other" or existing["kind"] == "other"
            )) else existing["kind"]
            next_title = title if title else existing["title"]
            next_goal = goal if goal else existing["goal"]
            # status always applies (explicit control surface)
            next_tokens = int(tokens) if tokens is not None else int(existing["tokens"] or 0)
            next_cost = float(cost) if cost is not None else float(existing["cost"] or 0.0)
            self.conn.execute(
                """
                UPDATE jobs SET
                  kind = ?,
                  title = ?,
                  status = ?,
                  goal = ?,
                  tokens = ?,
                  cost = ?,
                  meta = ?,
                  updated_at = ?
                WHERE id = ?
                """,
                (
                    next_kind,
                    next_title,
                    st,
                    next_goal,
                    next_tokens,
                    next_cost,
                    _json_dumps(new_meta),
                    now,
                    jid,
                ),
            )
        self.conn.commit()
        return self.get(jid)  # type: ignore[return-value]

    def ensure_job(
        self,
        job_id: str,
        *,
        kind: str = "other",
        title: str = "",
        status: str = "running",
        goal: str = "",
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Idempotent create if missing; does not clobber existing status/title."""
        jid = str(job_id or "").strip()
        if not jid:
            raise OpsError("job_id required")
        row = self.conn.execute(
            "SELECT id FROM jobs WHERE id = ?", (jid,)
        ).fetchone()
        if row is None:
            return self.upsert_job(
                jid,
                kind=kind,
                title=title or jid,
                status=status,
                goal=goal,
                meta=meta,
            )
        if meta:
            existing = self.get(jid) or {}
            m = dict(existing.get("meta") or {})
            m.update(meta)
            self.conn.execute(
                "UPDATE jobs SET meta = ?, updated_at = ? WHERE id = ?",
                (_json_dumps(m), time.time(), jid),
            )
            self.conn.commit()
        return self.get(jid)  # type: ignore[return-value]

    def set_status(self, job_id: str, status: str) -> dict[str, Any]:
        st = str(status or "").strip().lower()
        if st not in JOB_STATUSES:
            raise OpsError(f"invalid status: {status!r}")
        jid = str(job_id).strip()
        row = self.conn.execute(
            "SELECT id FROM jobs WHERE id = ?", (jid,)
        ).fetchone()
        if row is None:
            raise OpsError(f"job not found: {jid}")
        self.conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (st, time.time(), jid),
        )
        self.conn.commit()
        return self.get(jid)  # type: ignore[return-value]

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        jid = str(job_id or "").strip()
        row = self.conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (jid,)
        ).fetchone()
        if row is None:
            return None
        return self._job_dict(row)

    def list_jobs(
        self,
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(str(kind).strip().lower())
        if status:
            clauses.append("status = ?")
            params.append(str(status).strip().lower())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        lim = max(1, min(int(limit or 50), 1000))
        rows = self.conn.execute(
            f"SELECT * FROM jobs{where} ORDER BY updated_at DESC LIMIT ?",
            (*params, lim),
        ).fetchall()
        return [self._job_dict(r) for r in rows]

    def _job_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "title": row["title"],
            "status": row["status"],
            "goal": row["goal"],
            "tokens": int(row["tokens"] or 0),
            "cost": float(row["cost"] or 0.0),
            "meta": _json_loads(row["meta"]),
            "created_at": float(row["created_at"] or 0),
            "updated_at": float(row["updated_at"] or 0),
        }

    # -- spend --------------------------------------------------------------

    def record_spend(
        self,
        job_id: str,
        tokens: int,
        *,
        source: str = "",
        label: str = "",
        cost: Optional[float] = None,
        meta: Optional[dict[str, Any]] = None,
        usd_per_1k: float = DEFAULT_USD_PER_1K,
        dual_write_usage: bool = False,
        ensure: bool = True,
        kind: str = "task",
    ) -> dict[str, Any]:
        """Attribute token spend to a job; roll up job.tokens/cost.

        When *dual_write_usage* is True, also append to the global usage ledger
        (``usage.record``) with ``meta.task_id = job_id``.
        """
        jid = str(job_id or "").strip()
        if not jid:
            raise OpsError("job_id required")
        tok = max(0, int(tokens))
        c = float(cost) if cost is not None else estimate_cost(tok, usd_per_1k=usd_per_1k)
        if ensure:
            self.ensure_job(jid, kind=kind, title=jid, status="running")
        elif self.get(jid) is None:
            raise OpsError(f"job not found: {jid}")

        now = time.time()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO spend(job_id, tokens, cost, source, label, ts, meta)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                jid,
                tok,
                c,
                str(source or ""),
                str(label or ""),
                now,
                _json_dumps(meta or {}),
            ),
        )
        spend_id = int(cur.lastrowid or 0)
        cur.execute(
            """
            UPDATE jobs SET
              tokens = tokens + ?,
              cost = cost + ?,
              updated_at = ?
            WHERE id = ?
            """,
            (tok, c, now, jid),
        )
        self.conn.commit()

        out: dict[str, Any] = {
            "spend_id": spend_id,
            "job_id": jid,
            "tokens": tok,
            "cost": c,
            "source": source,
            "label": label,
            "ts": now,
            "job": self.get(jid),
        }

        if dual_write_usage:
            try:
                from . import usage as um

                um.record(
                    tok,
                    source=source or "ops",
                    label=label or "",
                    meta={"task_id": jid, "_ops_skip": True, **(meta or {})},
                    workdir=self.workdir,
                    enforce=False,
                )
                out["usage_recorded"] = True
            except Exception as e:  # fail-open for operator plane
                out["usage_recorded"] = False
                out["usage_error"] = str(e)
        return out

    def spend_rows(
        self,
        job_id: Optional[str] = None,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit or 200), 5000))
        if job_id:
            rows = self.conn.execute(
                """
                SELECT * FROM spend WHERE job_id = ?
                ORDER BY ts DESC LIMIT ?
                """,
                (str(job_id), lim),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM spend ORDER BY ts DESC LIMIT ?",
                (lim,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "job_id": r["job_id"],
                    "tokens": int(r["tokens"] or 0),
                    "cost": float(r["cost"] or 0.0),
                    "source": r["source"],
                    "label": r["label"],
                    "ts": float(r["ts"] or 0),
                    "meta": _json_loads(r["meta"]),
                }
            )
        return out

    def spend_report(
        self,
        job_id: Optional[str] = None,
        *,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Mission-control-style TaskCostReport lite."""
        rows = self.spend_rows(job_id, limit=limit)
        summary = calculate_stats(rows)
        by_source: dict[str, list[dict[str, Any]]] = {}
        by_job: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            src = str(r.get("source") or "unknown")
            by_source.setdefault(src, []).append(r)
            jid = str(r.get("job_id") or "")
            by_job.setdefault(jid, []).append(r)
        jobs_out: list[dict[str, Any]] = []
        for jid, recs in by_job.items():
            job = self.get(jid) or {"id": jid, "title": jid, "status": "?"}
            jobs_out.append(
                {
                    "job_id": jid,
                    "title": job.get("title"),
                    "status": job.get("status"),
                    "kind": job.get("kind"),
                    "stats": calculate_stats(recs),
                }
            )
        jobs_out.sort(key=lambda x: -int(x["stats"]["total_tokens"]))
        return {
            "schema": SCHEMA_VERSION,
            "job_id": job_id or "",
            "summary": summary,
            "by_source": {k: calculate_stats(v) for k, v in by_source.items()},
            "jobs": jobs_out,
            "unattributed": calculate_stats([])  # reserved; ledger ingest fills later
            if job_id
            else None,
        }

    # -- ingest from usage ledger -------------------------------------------

    def ingest_usage_ledger(
        self,
        *,
        only_task_ids: Optional[set[str]] = None,
        default_kind: str = "task",
    ) -> dict[str, Any]:
        """Backfill spend from ``usage`` JSONL rows that carry ``meta.task_id``.

        Idempotent-ish: skips rows whose (job_id, ts, tokens, source) already
        exist in spend. Safe / additive.
        """
        from . import usage as um

        ledger = um._iter_ledger(self.workdir)  # noqa: SLF001 — intentional
        imported = 0
        skipped = 0
        jobs_touched: set[str] = set()
        for r in ledger:
            meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
            tid = str((meta or {}).get("task_id") or "").strip()
            if not tid:
                skipped += 1
                continue
            if only_task_ids is not None and tid not in only_task_ids:
                skipped += 1
                continue
            tok = int(r.get("tokens") or 0)
            ts = float(r.get("ts") or 0)
            source = str(r.get("source") or "")
            # de-dupe check
            exists = self.conn.execute(
                """
                SELECT 1 FROM spend
                WHERE job_id = ? AND tokens = ? AND ts = ? AND source = ?
                LIMIT 1
                """,
                (tid, tok, ts, source),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            kind = str((meta or {}).get("kind") or default_kind)
            self.ensure_job(
                tid,
                kind=kind if kind in JOB_KINDS else default_kind,
                title=tid,
                status="completed",
                meta={"ingested_from": "usage_ledger"},
            )
            # direct insert without double-counting via record_spend's ensure
            cost = float((meta or {}).get("cost") or 0.0)
            self.conn.execute(
                """
                INSERT INTO spend(job_id, tokens, cost, source, label, ts, meta)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    tok,
                    cost,
                    source,
                    str(r.get("label") or ""),
                    ts or time.time(),
                    _json_dumps({"ingested": True, **(meta or {})}),
                ),
            )
            self.conn.execute(
                """
                UPDATE jobs SET tokens = tokens + ?, cost = cost + ?, updated_at = ?
                WHERE id = ?
                """,
                (tok, cost, time.time(), tid),
            )
            imported += 1
            jobs_touched.add(tid)
        self.conn.commit()
        return {
            "imported": imported,
            "skipped": skipped,
            "jobs_touched": sorted(jobs_touched),
        }

    # -- helpers ------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Compact ops dashboard blob."""
        jobs = self.list_jobs(limit=200)
        by_status: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        total_tokens = 0
        for j in jobs:
            by_status[j["status"]] = by_status.get(j["status"], 0) + 1
            by_kind[j["kind"]] = by_kind.get(j["kind"], 0) + 1
            total_tokens += int(j.get("tokens") or 0)
        return {
            "schema": SCHEMA_VERSION,
            "db": str(db_path(self.workdir)),
            "job_count": len(jobs),
            "total_tokens": total_tokens,
            "by_status": by_status,
            "by_kind": by_kind,
            "spend_summary": self.spend_report(limit=500)["summary"],
        }


def new_job_id(prefix: str = "ops") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def note_alive_cycle(
    workdir: Optional[Path | str],
    report: dict[str, Any],
    *,
    tokens: int = 0,
) -> Optional[dict[str, Any]]:
    """Upsert an alive-cycle job from a cycle report (fail-open)."""
    try:
        root = _root(workdir)
        with OpsStore.open(root) as store:
            cycle = int(report.get("cycle") or report.get("n") or 0)
            jid = str(
                report.get("ops_job_id")
                or report.get("job_id")
                or f"alive-cycle-{cycle or int(time.time())}"
            )
            status = "blocked" if report.get("blocked") else (
                "completed" if report.get("ok") else "failed"
            )
            if report.get("stopped"):
                status = "completed"
            goal = str(
                (report.get("goal") or (report.get("config") or {}).get("goal") or "")
            )[:500]
            store.upsert_job(
                jid,
                kind="alive",
                title=f"alive cycle {cycle}" if cycle else "alive cycle",
                status=status if status in JOB_STATUSES else "completed",
                goal=goal,
                meta={
                    "stopped": bool(report.get("stopped")),
                    "stop_reason": report.get("stop_reason"),
                    "ok": bool(report.get("ok")),
                },
            )
            if tokens > 0:
                store.record_spend(
                    jid,
                    tokens,
                    source="alive",
                    label="cycle",
                    dual_write_usage=False,
                    ensure=False,
                    kind="alive",
                )
            return store.get(jid)
    except Exception:
        return None


def note_improve_run(
    workdir: Optional[Path | str],
    run_id: str,
    *,
    phase: str = "running",
    repo: str = "",
    status: str = "running",
) -> Optional[dict[str, Any]]:
    """Register an improve-apply run on the ops board (fail-open)."""
    try:
        root = _root(workdir)
        st = status
        if phase == "done":
            st = "completed"
        with OpsStore.open(root) as store:
            return store.upsert_job(
                run_id,
                kind="improve",
                title=f"improve-apply {repo or run_id}",
                status=st if st in JOB_STATUSES else "running",
                goal=f"apply pattern from {repo}" if repo else "improve-apply",
                meta={"phase": phase, "repo": repo},
            )
    except Exception:
        return None
