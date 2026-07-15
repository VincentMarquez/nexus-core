"""SQLite MCP persistent context + verify-before-done self-improve loop.

First apply slice (docs/LATEST_IMPROVE_PLAN.md):

  runs / stages / context_kv / claims / grades  (SQLite)
    → ordered stage machine
    → independent verify + grade required before done
    → demo-loop CLI + MCP context_get/set/handoff

Patterns (shape only, not vendored trees):
- codingagentsystem/cas — SQLite-backed MCP persistent context + handoffs
- ahmedEid1/lumen — migration discipline for SQLite schemas
- Intelligent-Internet/zenith — anti–premature-completion / verify-before-done
- choihyunsus/soul — handoff + immutable-ish ledger fields
- arXiv 2510.13343 (AOAD-MAT) — order of action decisions
- arXiv 2511.15755 — deterministic orchestration / fixed stage graph
- arXiv 2512.03278 (Thucy) — claim + evidence refs before done
- arXiv 2302.10809 (CEMA) — lightweight decision log lines

Storage: ``.nexus_state/context/context.sqlite`` under the project workdir.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

SCHEMA_VERSION = "nexus.context_store/v1"
DB_NAME = "context.sqlite"

# Ordered self-improve stages (plan § First apply slice).
LOOP_STAGES: tuple[str, ...] = (
    "research_ingest",
    "mine_rank",
    "plan_item",
    "apply",
    "verify",
    "grade",
    "done",
)

# Terminal statuses (not advanced via mark_complete the same way).
TERMINAL = frozenset({"done", "retry"})

# Stages that must complete before done is legal.
DONE_REQUIRE_COMPLETED: tuple[str, ...] = (
    "research_ingest",
    "mine_rank",
    "plan_item",
    "apply",
    "verify",
    "grade",
)


class ContextStoreError(RuntimeError):
    """Invalid context-store operation."""


class StageOrderError(ContextStoreError):
    """Illegal stage transition or premature done."""


class VerifyError(ContextStoreError):
    """Independent verification failed."""


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def store_dir(workdir: Optional[Path | str] = None) -> Path:
    d = _root(workdir) / ".nexus_state" / "context"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path(workdir: Optional[Path | str] = None) -> Path:
    return store_dir(workdir) / DB_NAME


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


def normalize_stage(name: str) -> str:
    return str(name or "").strip().lower()


def stage_index(name: str, stages: Sequence[str] = LOOP_STAGES) -> int:
    key = normalize_stage(name)
    order = tuple(normalize_stage(s) for s in stages)
    try:
        return order.index(key)
    except ValueError as e:
        raise StageOrderError(f"unknown stage {name!r}; known={list(order)}") from e


def can_advance(
    current: str,
    target: str,
    *,
    stages: Sequence[str] = LOOP_STAGES,
    completed: Iterable[str] = (),
) -> bool:
    """True when *target* is the next incomplete stage (or already done)."""
    order = [normalize_stage(s) for s in stages]
    tgt = normalize_stage(target)
    if tgt not in order:
        return False
    done = {normalize_stage(x) for x in completed}
    if tgt in done:
        return True
    # Next incomplete stage only
    for s in order:
        if s not in done:
            return s == tgt
    return False


# ---------------------------------------------------------------------------
# ContextStore
# ---------------------------------------------------------------------------


@dataclass
class ContextStore:
    """SQLite-backed MCP context: runs, stages, kv, claims, grades."""

    workdir: Path
    conn: sqlite3.Connection

    @classmethod
    def open(cls, workdir: Optional[Path | str] = None) -> "ContextStore":
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

    def __enter__(self) -> "ContextStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- schema --------------------------------------------------------------

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY,
              goal TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'planned',
              current_stage TEXT NOT NULL DEFAULT 'research_ingest',
              meta TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS stages (
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              stage TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              detail TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL,
              UNIQUE(run_id, stage)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_stages_run ON stages(run_id, created_at)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS context_kv (
              run_id TEXT NOT NULL,
              key TEXT NOT NULL,
              value TEXT NOT NULL DEFAULT '',
              agent TEXT NOT NULL DEFAULT '',
              updated_at REAL NOT NULL,
              PRIMARY KEY (run_id, key)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              claim TEXT NOT NULL DEFAULT '',
              evidence_paths TEXT NOT NULL DEFAULT '[]',
              verified INTEGER NOT NULL DEFAULT 0,
              detail TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_claims_run ON claims(run_id, created_at)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS grades (
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              total REAL NOT NULL DEFAULT 0,
              idea REAL NOT NULL DEFAULT 0,
              skill REAL NOT NULL DEFAULT 0,
              method TEXT NOT NULL DEFAULT '',
              detail TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_grades_run ON grades(run_id, created_at)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              why TEXT NOT NULL DEFAULT '',
              detail TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL
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
        self.conn.commit()

    # -- runs ----------------------------------------------------------------

    def create_run(
        self,
        *,
        goal: str = "",
        run_id: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        rid = str(run_id or f"ctx-{uuid.uuid4().hex[:12]}")
        existing = self.get_run(rid)
        if existing is not None:
            return existing
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO runs(id, goal, status, current_stage, meta, created_at, updated_at)
            VALUES(?, ?, 'planned', 'research_ingest', ?, ?, ?)
            """,
            (rid, str(goal or ""), _json_dumps(meta or {}), now, now),
        )
        # seed stage rows
        for stage in LOOP_STAGES:
            if stage == "done":
                continue
            self.conn.execute(
                """
                INSERT OR IGNORE INTO stages(id, run_id, stage, status, detail, created_at)
                VALUES(?, ?, ?, 'pending', '{}', ?)
                """,
                (f"{rid}:{stage}", rid, stage, now),
            )
        self.conn.commit()
        row = self.get_run(rid)
        if row is None:
            raise ContextStoreError("create_run failed to persist")
        return row

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM runs WHERE id = ?", (str(run_id),)
        ).fetchone()
        return self._run_dict(row) if row else None

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM runs
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        return [self._run_dict(r) for r in rows]

    def _run_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "goal": row["goal"],
            "status": row["status"],
            "current_stage": row["current_stage"],
            "meta": _json_loads(row["meta"]) or {},
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _touch_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        current_stage: Optional[str] = None,
    ) -> None:
        now = time.time()
        run = self.get_run(run_id)
        if run is None:
            raise ContextStoreError(f"unknown run: {run_id}")
        st = status if status is not None else run["status"]
        cur = current_stage if current_stage is not None else run["current_stage"]
        self.conn.execute(
            """
            UPDATE runs SET status = ?, current_stage = ?, updated_at = ?
            WHERE id = ?
            """,
            (st, cur, now, str(run_id)),
        )
        self.conn.commit()

    # -- stages --------------------------------------------------------------

    def completed_stages(self, run_id: str) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT stage FROM stages
            WHERE run_id = ? AND status = 'completed'
            ORDER BY created_at ASC
            """,
            (str(run_id),),
        ).fetchall()
        return [str(r["stage"]) for r in rows]

    def stage_timeline(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM stages WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (str(run_id),),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "stage": r["stage"],
                    "status": r["status"],
                    "detail": _json_loads(r["detail"]) or {},
                    "created_at": float(r["created_at"]),
                }
            )
        return out

    def next_stage(self, run_id: str) -> Optional[str]:
        done = set(self.completed_stages(run_id))
        for s in LOOP_STAGES:
            if s == "done":
                continue
            if s not in done:
                return s
        return "done" if "done" not in done else None

    def mark_stage(
        self,
        run_id: str,
        stage: str,
        *,
        status: str = "completed",
        detail: Optional[dict[str, Any]] = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Mark a stage. Enforces order unless *force*. Rejects premature done."""
        rid = str(run_id)
        run = self.get_run(rid)
        if run is None:
            raise ContextStoreError(f"unknown run: {rid}")
        if run["status"] in ("done", "failed"):
            raise StageOrderError(f"run {rid} is terminal ({run['status']})")

        key = normalize_stage(stage)
        if key == "retry":
            self._touch_run(rid, status="retry", current_stage="retry")
            return {"run_id": rid, "stage": "retry", "status": "retry"}

        if key == "done":
            return self.mark_done(rid, detail=detail)

        if key not in LOOP_STAGES:
            raise StageOrderError(f"unknown stage {stage!r}")

        completed = self.completed_stages(rid)
        if not force and not can_advance(
            run["current_stage"], key, completed=completed
        ):
            nxt = self.next_stage(rid)
            raise StageOrderError(
                f"stage {key!r} refused: next expected {nxt!r} "
                f"(completed={completed})"
            )

        now = time.time()
        self.conn.execute(
            """
            INSERT INTO stages(id, run_id, stage, status, detail, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, stage) DO UPDATE SET
              status = excluded.status,
              detail = excluded.detail,
              created_at = excluded.created_at
            """,
            (
                f"{rid}:{key}",
                rid,
                key,
                str(status or "completed"),
                _json_dumps(detail or {}),
                now,
            ),
        )
        self.conn.commit()

        if status == "completed":
            nxt = self.next_stage(rid)
            self._touch_run(
                rid,
                status="running",
                current_stage=nxt or key,
            )
        return {
            "run_id": rid,
            "stage": key,
            "status": status,
            "completed": self.completed_stages(rid),
            "next": self.next_stage(rid),
        }

    def mark_done(
        self,
        run_id: str,
        *,
        detail: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Mark run done only when verify passed + grade present (zenith)."""
        rid = str(run_id)
        run = self.get_run(rid)
        if run is None:
            raise ContextStoreError(f"unknown run: {rid}")

        completed = set(self.completed_stages(rid))
        missing = [s for s in DONE_REQUIRE_COMPLETED if s not in completed]
        if missing:
            raise StageOrderError(
                f"done refused: incomplete stages {missing} "
                f"(need verify+grade and prior stages)"
            )

        # Independent gates: verified claim + grade row
        claims = self.list_claims(rid)
        verified = [c for c in claims if c.get("verified")]
        if not verified:
            raise StageOrderError(
                "done refused: no verified claim (independent verify required)"
            )
        grades = self.list_grades(rid)
        if not grades:
            raise StageOrderError("done refused: no grade row present")

        now = time.time()
        self.conn.execute(
            """
            INSERT INTO stages(id, run_id, stage, status, detail, created_at)
            VALUES(?, ?, 'done', 'completed', ?, ?)
            ON CONFLICT(run_id, stage) DO UPDATE SET
              status = 'completed',
              detail = excluded.detail,
              created_at = excluded.created_at
            """,
            (f"{rid}:done", rid, _json_dumps(detail or {}), now),
        )
        self.conn.commit()
        self._touch_run(rid, status="done", current_stage="done")
        return {
            "run_id": rid,
            "stage": "done",
            "status": "done",
            "claims": len(verified),
            "grades": len(grades),
            "ok": True,
        }

    # -- context kv / handoff ------------------------------------------------

    def context_set(
        self,
        run_id: str,
        key: str,
        value: Any,
        *,
        agent: str = "",
    ) -> dict[str, Any]:
        rid = str(run_id)
        if self.get_run(rid) is None:
            raise ContextStoreError(f"unknown run: {rid}")
        k = str(key or "").strip()
        if not k:
            raise ContextStoreError("context key required")
        now = time.time()
        raw = value if isinstance(value, str) else _json_dumps(value)
        self.conn.execute(
            """
            INSERT INTO context_kv(run_id, key, value, agent, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(run_id, key) DO UPDATE SET
              value = excluded.value,
              agent = excluded.agent,
              updated_at = excluded.updated_at
            """,
            (rid, k, raw, str(agent or ""), now),
        )
        self.conn.commit()
        return {"run_id": rid, "key": k, "value": raw, "agent": agent, "updated_at": now}

    def context_get(
        self,
        run_id: str,
        key: Optional[str] = None,
    ) -> Any:
        rid = str(run_id)
        if key is None or str(key).strip() == "":
            rows = self.conn.execute(
                """
                SELECT key, value, agent, updated_at FROM context_kv
                WHERE run_id = ?
                ORDER BY key ASC
                """,
                (rid,),
            ).fetchall()
            return {
                r["key"]: {
                    "value": r["value"],
                    "agent": r["agent"],
                    "updated_at": float(r["updated_at"]),
                }
                for r in rows
            }
        row = self.conn.execute(
            """
            SELECT key, value, agent, updated_at FROM context_kv
            WHERE run_id = ? AND key = ?
            """,
            (rid, str(key)),
        ).fetchone()
        if row is None:
            return None
        parsed = _json_loads(row["value"])
        return {
            "key": row["key"],
            "value": parsed if parsed is not None else row["value"],
            "raw": row["value"],
            "agent": row["agent"],
            "updated_at": float(row["updated_at"]),
        }

    def handoff(
        self,
        run_id: str,
        *,
        from_agent: str,
        to_agent: str,
        summary: str = "",
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Record agent handoff in context_kv + decision log (swarm/cas shape)."""
        rid = str(run_id)
        if self.get_run(rid) is None:
            raise ContextStoreError(f"unknown run: {rid}")
        body = {
            "from": str(from_agent or ""),
            "to": str(to_agent or ""),
            "summary": str(summary or ""),
            "payload": payload or {},
            "ts": time.time(),
        }
        self.context_set(rid, "handoff.last", body, agent=str(from_agent or ""))
        self.context_set(
            rid,
            f"handoff.{to_agent or 'next'}",
            body,
            agent=str(from_agent or ""),
        )
        self.log_decision(
            rid,
            why=f"handoff {from_agent} → {to_agent}: {summary}".strip(),
            detail=body,
        )
        return body

    # -- claims / grades / decisions -----------------------------------------

    def add_claim(
        self,
        run_id: str,
        claim: str,
        *,
        evidence_paths: Optional[Sequence[str]] = None,
        verified: bool = False,
        detail: Optional[dict[str, Any]] = None,
        claim_id: Optional[str] = None,
    ) -> dict[str, Any]:
        rid = str(run_id)
        if self.get_run(rid) is None:
            raise ContextStoreError(f"unknown run: {rid}")
        cid = str(claim_id or f"cl-{uuid.uuid4().hex[:12]}")
        now = time.time()
        paths = [str(p) for p in (evidence_paths or []) if str(p).strip()]
        self.conn.execute(
            """
            INSERT INTO claims(
              id, run_id, claim, evidence_paths, verified, detail, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cid,
                rid,
                str(claim or ""),
                _json_dumps(paths),
                1 if verified else 0,
                _json_dumps(detail or {}),
                now,
            ),
        )
        self.conn.commit()
        return self.get_claim(cid) or {"id": cid}

    def get_claim(self, claim_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM claims WHERE id = ?", (str(claim_id),)
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "claim": row["claim"],
            "evidence_paths": _json_loads(row["evidence_paths"]) or [],
            "verified": bool(row["verified"]),
            "detail": _json_loads(row["detail"]) or {},
            "created_at": float(row["created_at"]),
        }

    def list_claims(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM claims WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (str(run_id),),
        ).fetchall()
        return [self.get_claim(r["id"]) for r in rows if self.get_claim(r["id"])]

    def set_claim_verified(
        self,
        claim_id: str,
        *,
        verified: bool = True,
        detail: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        row = self.get_claim(claim_id)
        if row is None:
            raise ContextStoreError(f"unknown claim: {claim_id}")
        d = dict(row.get("detail") or {})
        if detail:
            d.update(detail)
        self.conn.execute(
            """
            UPDATE claims SET verified = ?, detail = ? WHERE id = ?
            """,
            (1 if verified else 0, _json_dumps(d), str(claim_id)),
        )
        self.conn.commit()
        return self.get_claim(claim_id) or row

    def add_grade(
        self,
        run_id: str,
        *,
        total: float = 0.0,
        idea: float = 0.0,
        skill: float = 0.0,
        method: str = "stub:demo",
        detail: Optional[dict[str, Any]] = None,
        grade_id: Optional[str] = None,
    ) -> dict[str, Any]:
        rid = str(run_id)
        if self.get_run(rid) is None:
            raise ContextStoreError(f"unknown run: {rid}")
        gid = str(grade_id or f"gr-{uuid.uuid4().hex[:12]}")
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO grades(
              id, run_id, total, idea, skill, method, detail, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gid,
                rid,
                float(total),
                float(idea),
                float(skill),
                str(method or ""),
                _json_dumps(detail or {}),
                now,
            ),
        )
        self.conn.commit()
        return self.get_grade(gid) or {"id": gid}

    def get_grade(self, grade_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM grades WHERE id = ?", (str(grade_id),)
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "total": float(row["total"]),
            "idea": float(row["idea"]),
            "skill": float(row["skill"]),
            "method": row["method"],
            "detail": _json_loads(row["detail"]) or {},
            "created_at": float(row["created_at"]),
        }

    def list_grades(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id FROM grades WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (str(run_id),),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            g = self.get_grade(r["id"])
            if g:
                out.append(g)
        return out

    def log_decision(
        self,
        run_id: str,
        why: str,
        *,
        detail: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        rid = str(run_id)
        did = f"dec-{uuid.uuid4().hex[:12]}"
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO decisions(id, run_id, why, detail, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (did, rid, str(why or ""), _json_dumps(detail or {}), now),
        )
        self.conn.commit()
        return {
            "id": did,
            "run_id": rid,
            "why": why,
            "detail": detail or {},
            "created_at": now,
        }

    def list_decisions(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM decisions WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (str(run_id),),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "run_id": r["run_id"],
                "why": r["why"],
                "detail": _json_loads(r["detail"]) or {},
                "created_at": float(r["created_at"]),
            }
            for r in rows
        ]

    # -- verify --------------------------------------------------------------

    def verify_claims(
        self,
        run_id: str,
        *,
        require_paths_exist: bool = True,
        claim_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Independent verification: claim paths exist under workdir (Thucy).

        Does not run network; path existence is the default offline gate.
        Optional fixed test command can be attached via detail later.
        """
        rid = str(run_id)
        claims = self.list_claims(rid)
        if claim_id:
            claims = [c for c in claims if c["id"] == claim_id]
        if not claims:
            raise VerifyError("no claims to verify")

        root = self.workdir
        results: list[dict[str, Any]] = []
        all_ok = True
        for c in claims:
            paths = list(c.get("evidence_paths") or [])
            missing: list[str] = []
            if require_paths_exist:
                if not paths:
                    missing.append("(no evidence_paths)")
                for p in paths:
                    pp = Path(p)
                    if not pp.is_absolute():
                        pp = (root / p).resolve()
                    if not pp.exists():
                        missing.append(str(p))
            ok = not missing
            all_ok = all_ok and ok
            updated = self.set_claim_verified(
                c["id"],
                verified=ok,
                detail={"missing": missing, "verified_at": time.time()},
            )
            results.append(
                {
                    "claim_id": c["id"],
                    "ok": ok,
                    "missing": missing,
                    "claim": updated.get("claim"),
                }
            )

        return {
            "run_id": rid,
            "ok": all_ok,
            "results": results,
            "n_verified": sum(1 for r in results if r["ok"]),
        }

    # -- status / snapshot ---------------------------------------------------

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run is None:
            raise ContextStoreError(f"unknown run: {run_id}")
        return {
            "schema": SCHEMA_VERSION,
            "run": run,
            "completed": self.completed_stages(run_id),
            "next": self.next_stage(run_id),
            "timeline": self.stage_timeline(run_id),
            "claims": self.list_claims(run_id),
            "grades": self.list_grades(run_id),
            "decisions": self.list_decisions(run_id),
            "context": self.context_get(run_id),
        }


# ---------------------------------------------------------------------------
# Demo loop — proves restart-safe durable stages + verify-before-done
# ---------------------------------------------------------------------------


@dataclass
class DemoLoopResult:
    ok: bool
    run_id: str
    status: str
    stages_completed: list[str] = field(default_factory=list)
    grade: Optional[dict[str, Any]] = None
    claims: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    resumed: bool = False
    error: Optional[str] = None
    db_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nexus.demo_loop/v1",
            "ok": self.ok,
            "run_id": self.run_id,
            "status": self.status,
            "stages_completed": list(self.stages_completed),
            "grade": self.grade,
            "claims": list(self.claims),
            "decisions": list(self.decisions),
            "timeline": list(self.timeline),
            "resumed": self.resumed,
            "error": self.error,
            "db_path": self.db_path,
        }


def run_demo_loop(
    workdir: Optional[Path | str] = None,
    *,
    run_id: Optional[str] = None,
    goal: str = "prove durable MCP context + verify-before-done",
    stop_after: Optional[str] = None,
    grade_total: float = 15.0,
) -> dict[str, Any]:
    """Create/resume a demo self-improve run through ordered stages.

    *stop_after*: if set, stop after completing that stage (for restart demos).
    Resume: pass the same *run_id* and omit/advance *stop_after*.
    """
    root = _root(workdir)
    # Evidence artifact so path verify succeeds offline
    evidence_dir = root / ".nexus_workspaces" / "demo_loop"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / "loop_proved.txt"

    with ContextStore.open(root) as store:
        existing = store.get_run(run_id) if run_id else None
        resumed = existing is not None
        run = existing or store.create_run(goal=goal, run_id=run_id)
        rid = run["id"]
        store.log_decision(
            rid,
            why="demo-loop start" if not resumed else "demo-loop resume",
            detail={"goal": goal, "resumed": resumed, "stop_after": stop_after},
        )

        # Stage handlers (docs-only / no-op apply)
        handlers: dict[str, Any] = {
            "research_ingest": lambda: _stage_research(store, rid, root),
            "mine_rank": lambda: _stage_mine(store, rid),
            "plan_item": lambda: _stage_plan(store, rid),
            "apply": lambda: _stage_apply(store, rid, evidence_path, root),
            "verify": lambda: _stage_verify(store, rid),
            "grade": lambda: _stage_grade(store, rid, grade_total),
        }

        err: Optional[str] = None
        try:
            while True:
                if run.get("status") == "done":
                    break
                nxt = store.next_stage(rid)
                if nxt is None or nxt == "done":
                    # attempt done gate
                    store.mark_done(
                        rid,
                        detail={"source": "demo_loop"},
                    )
                    break
                handlers[nxt]()
                store.mark_stage(rid, nxt, status="completed")
                if stop_after and normalize_stage(stop_after) == nxt:
                    store.log_decision(
                        rid,
                        why=f"demo-loop stop_after={nxt}",
                        detail={"current": nxt},
                    )
                    break
                run = store.get_run(rid) or run
        except (ContextStoreError, VerifyError) as e:
            err = str(e)

        snap = store.status(rid)
        grades = snap.get("grades") or []
        result = DemoLoopResult(
            ok=err is None and snap["run"]["status"] == "done",
            run_id=rid,
            status=str(snap["run"]["status"]),
            stages_completed=list(snap.get("completed") or []),
            grade=grades[-1] if grades else None,
            claims=list(snap.get("claims") or []),
            decisions=list(snap.get("decisions") or []),
            timeline=list(snap.get("timeline") or []),
            resumed=resumed,
            error=err,
            db_path=str(db_path(root)),
        )
        # Partial progress without error (stop_after) is ok for restart demos
        if err is None and stop_after and result.status != "done":
            result.ok = True
        return result.to_dict()


def _stage_research(store: ContextStore, rid: str, root: Path) -> None:
    store.context_set(
        rid,
        "research.summary",
        {
            "papers": 10,
            "note": "stub research ingest for demo-loop",
            "workdir": str(root),
        },
        agent="research",
    )
    store.handoff(
        rid,
        from_agent="research",
        to_agent="mine",
        summary="research notes ready for mine rank",
    )
    store.log_decision(rid, why="selected research_ingest stage (demo)")


def _stage_mine(store: ContextStore, rid: str) -> None:
    store.context_set(
        rid,
        "mine.top",
        {"repo": "codingagentsystem/cas", "score": 16.0, "pattern": "sqlite-mcp-context"},
        agent="mine",
    )
    store.handoff(
        rid,
        from_agent="mine",
        to_agent="planner",
        summary="top repo cas for SQLite MCP context",
    )
    store.log_decision(
        rid,
        why="ranked codingagentsystem/cas for SQLite MCP context pattern",
        detail={"score": 16.0},
    )


def _stage_plan(store: ContextStore, rid: str) -> None:
    store.context_set(
        rid,
        "plan.item",
        {
            "title": "durable MCP context + verify-before-done",
            "files": ["src/nexus/context_store.py"],
        },
        agent="planner",
    )
    store.handoff(
        rid,
        from_agent="planner",
        to_agent="apply",
        summary="plan_item ready",
    )


def _stage_apply(
    store: ContextStore,
    rid: str,
    evidence_path: Path,
    root: Path,
) -> None:
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        f"loop proved at {time.time():.0f}\nrun_id={rid}\n",
        encoding="utf-8",
    )
    rel = str(evidence_path.relative_to(root)) if evidence_path.is_relative_to(root) else str(evidence_path)
    store.add_claim(
        rid,
        "loop proved: demo apply wrote evidence artifact",
        evidence_paths=[rel],
        verified=False,
        detail={"kind": "demo_apply"},
    )
    store.context_set(rid, "apply.artifact", {"path": rel}, agent="apply")
    store.handoff(
        rid,
        from_agent="apply",
        to_agent="verify",
        summary=f"apply wrote {rel}",
    )


def _stage_verify(store: ContextStore, rid: str) -> None:
    rep = store.verify_claims(rid, require_paths_exist=True)
    if not rep.get("ok"):
        raise VerifyError(f"verify failed: {rep}")
    store.context_set(rid, "verify.report", rep, agent="verify")
    store.handoff(
        rid,
        from_agent="verify",
        to_agent="grade",
        summary=f"verified {rep.get('n_verified')} claims",
    )


def _stage_grade(store: ContextStore, rid: str, total: float) -> None:
    g = store.add_grade(
        rid,
        total=float(total),
        idea=min(8.0, float(total) / 2),
        skill=min(8.0, float(total) / 2),
        method="stub:demo-loop",
        detail={"note": "offline grade stub; Grok re-grade is next PR"},
    )
    store.context_set(rid, "grade.last", g, agent="grade")
    store.log_decision(
        rid,
        why=f"recorded grade total={total}",
        detail=g,
    )


def format_demo_report(report: dict[str, Any]) -> str:
    lines = [
        "=== NEXUS improve demo-loop ===",
        f"run_id:  {report.get('run_id')}",
        f"status:  {report.get('status')}",
        f"ok:      {'YES' if report.get('ok') else 'NO'}",
        f"resumed: {report.get('resumed')}",
        f"stages:  {' → '.join(report.get('stages_completed') or [])}",
        f"db:      {report.get('db_path')}",
    ]
    if report.get("error"):
        lines.append(f"error:   {report['error']}")
    g = report.get("grade") or {}
    if g:
        lines.append(
            f"grade:   total={g.get('total')} idea={g.get('idea')} "
            f"skill={g.get('skill')} method={g.get('method')}"
        )
    claims = report.get("claims") or []
    lines.append(f"claims:  {len(claims)} (verified={sum(1 for c in claims if c.get('verified'))})")
    for c in claims[:5]:
        lines.append(f"  - {c.get('claim')} paths={c.get('evidence_paths')}")
    dec = report.get("decisions") or []
    if dec:
        lines.append("decisions:")
        for d in dec[-5:]:
            lines.append(f"  - {d.get('why')}")
    tl = report.get("timeline") or []
    if tl:
        lines.append("timeline:")
        for t in tl:
            lines.append(f"  [{t.get('status')}] {t.get('stage')}")
    return "\n".join(lines)


def open_store(workdir: Optional[Path | str] = None) -> ContextStore:
    """Convenience: open store (caller should close)."""
    return ContextStore.open(workdir)
