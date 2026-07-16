"""Append-only work ledger for mine → grade → gated hard-apply (First apply slice).

Prove durable self-improve loop without porting a full product:

  mine_completed → grade_recorded → decision_packet → apply_proposed
    → apply_accepted | apply_rejected

Invariants (fail-closed):
- work_events are append-only (UPDATE/DELETE forbidden)
- apply_accepted requires prior grade_recorded for the same run/repo
- grade agent role ≠ applier role (anti-collusion dual control, arXiv 2601.00360)
- apply_proposed/accepted require a decision packet with score ≥ threshold
- optional circuit breaker around external-shaped grade/research call paths

Patterns (shape only, not vendored trees):
- choihyunsus/soul — immutable work ledger
- codingagentsystem/cas / mission-control — SQLite control plane
- wheattoast11/openrouter-deep-research-mcp — circuit breakers
- ahmedEid1/lumen — decision audit + causal chain demo
- arXiv 2511.15755 — deterministic apply decision packet
- arXiv 2601.00360 — dual-control anti-collusion
- arXiv 1301.6431 — illegal transition refusal
- arXiv 2302.10809 — causal chain explain

Storage: ``.nexus_workspaces/work_ledger/work.sqlite``
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .circuits import CircuitBreaker, CircuitState

SCHEMA_VERSION = "nexus.work_ledger/v1"
DB_NAME = "work.sqlite"
LEDGER_REL = Path(".nexus_workspaces") / "work_ledger"

DEFAULT_METHOD = "grok:grok-4.5"
DEFAULT_SCORE_THRESHOLD = 15.0
DEFAULT_PATTERN = "immutable work ledger"

# Event vocabulary for the self-improve state machine
EVENT_MINE_COMPLETED = "mine_completed"
EVENT_GRADE_RECORDED = "grade_recorded"
EVENT_DECISION_PACKET = "decision_packet"
EVENT_APPLY_PROPOSED = "apply_proposed"
EVENT_APPLY_REJECTED = "apply_rejected"
EVENT_APPLY_ACCEPTED = "apply_accepted"
EVENT_BREAKER = "breaker_event"

APPLY_EVENTS = frozenset(
    {EVENT_APPLY_PROPOSED, EVENT_APPLY_REJECTED, EVENT_APPLY_ACCEPTED}
)
ALL_EVENTS = frozenset(
    {
        EVENT_MINE_COMPLETED,
        EVENT_GRADE_RECORDED,
        EVENT_DECISION_PACKET,
        EVENT_APPLY_PROPOSED,
        EVENT_APPLY_REJECTED,
        EVENT_APPLY_ACCEPTED,
        EVENT_BREAKER,
    }
)

# P0.5 interleaving invariants (arXiv 1301.6431 shape): legal worker transitions
# keyed by previous *pipeline* event (breaker is transparent).
# Empty prior allows mine or grade (offline fixtures may skip explicit mine).
LEGAL_SUCCESSORS: dict[Optional[str], frozenset[str]] = {
    None: frozenset(
        {EVENT_MINE_COMPLETED, EVENT_GRADE_RECORDED, EVENT_BREAKER}
    ),
    EVENT_MINE_COMPLETED: frozenset(
        {
            EVENT_GRADE_RECORDED,
            EVENT_MINE_COMPLETED,
            EVENT_BREAKER,
        }
    ),
    EVENT_GRADE_RECORDED: frozenset(
        {
            EVENT_DECISION_PACKET,
            EVENT_APPLY_PROPOSED,
            EVENT_APPLY_REJECTED,
            EVENT_GRADE_RECORDED,
            EVENT_MINE_COMPLETED,
            EVENT_BREAKER,
        }
    ),
    EVENT_DECISION_PACKET: frozenset(
        {
            EVENT_APPLY_PROPOSED,
            EVENT_APPLY_REJECTED,
            EVENT_DECISION_PACKET,
            EVENT_BREAKER,
        }
    ),
    EVENT_APPLY_PROPOSED: frozenset(
        {
            EVENT_APPLY_ACCEPTED,
            EVENT_APPLY_REJECTED,
            EVENT_BREAKER,
        }
    ),
    EVENT_APPLY_ACCEPTED: frozenset(
        {
            EVENT_MINE_COMPLETED,
            EVENT_GRADE_RECORDED,
            EVENT_BREAKER,
        }
    ),
    EVENT_APPLY_REJECTED: frozenset(
        {
            EVENT_MINE_COMPLETED,
            EVENT_GRADE_RECORDED,
            EVENT_DECISION_PACKET,
            EVENT_APPLY_PROPOSED,
            EVENT_BREAKER,
        }
    ),
    EVENT_BREAKER: frozenset(ALL_EVENTS),
}

ROLE_GRADER = "grader"
ROLE_APPLIER = "applier"
ROLE_MINER = "miner"

DEFAULT_ROLES = {
    ROLE_MINER: "scout:mine",
    ROLE_GRADER: "grok:grade",
    ROLE_APPLIER: "worker:apply",
}


def assert_legal_transition(
    prev: Optional[str],
    nxt: str,
    *,
    enforce: bool = True,
) -> dict[str, Any]:
    """Fail-closed interleaving check for worker event ordering (P0.5).

    Breaker events are transparent (do not change the pipeline cursor).
    Returns ``{ok, prev, next, allowed}``; raises TransitionError when illegal.
    """
    et = str(nxt or "").strip()
    if et not in ALL_EVENTS:
        raise TransitionError(f"unknown event_type: {et}")
    if et == EVENT_BREAKER:
        return {
            "ok": True,
            "prev": prev,
            "next": et,
            "allowed": sorted(ALL_EVENTS),
            "transparent": True,
        }
    key: Optional[str] = None if prev in (None, "", EVENT_BREAKER) else str(prev)
    allowed = LEGAL_SUCCESSORS.get(key, frozenset())
    out = {
        "ok": et in allowed,
        "prev": key,
        "next": et,
        "allowed": sorted(allowed),
    }
    if enforce and not out["ok"]:
        raise TransitionError(
            f"illegal transition {(key or '∅')} → {et}; "
            f"allowed={sorted(allowed)}"
        )
    return out


class WorkLedgerError(RuntimeError):
    """Invalid or rejected work-ledger operation."""


class ImmutableError(WorkLedgerError):
    """Update/delete of work events is forbidden."""


class DualControlError(WorkLedgerError):
    """Apply gate refused: missing grade or same-role collusion."""


class DecisionPacketError(WorkLedgerError):
    """Decision packet missing or below threshold."""


class TransitionError(WorkLedgerError):
    """Illegal event ordering for the improve state machine."""


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


def _norm_role(role: str) -> str:
    return str(role or "").strip().lower()


def event_content_hash(
    *,
    run_id: str,
    event_type: str,
    agent: str,
    role: str,
    repo: str,
    payload: dict[str, Any],
    parent_id: str = "",
) -> str:
    blob = _json_dumps(
        {
            "run_id": str(run_id or ""),
            "event_type": str(event_type or ""),
            "agent": str(agent or ""),
            "role": str(role or ""),
            "repo": str(repo or ""),
            "payload": payload or {},
            "parent_id": str(parent_id or ""),
        }
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Decision packet (2511.15755)
# ---------------------------------------------------------------------------


def build_decision_packet(
    *,
    source_repo: str,
    score: float,
    pattern_name: str = DEFAULT_PATTERN,
    target_module: str = "src/nexus/work_ledger.py",
    tests_to_run: Optional[Sequence[str]] = None,
    idea: Optional[float] = None,
    skill: Optional[float] = None,
    method: str = DEFAULT_METHOD,
    grade_id: str = "",
    threshold: float = DEFAULT_SCORE_THRESHOLD,
    path: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a deterministic apply decision packet (JSON-serializable)."""
    tests = list(tests_to_run or ["tests/test_work_ledger.py"])
    score_f = float(score)
    thr = float(threshold)
    packet = {
        "schema": "nexus.decision_packet/v1",
        "source_repo": str(source_repo or "").strip(),
        "score": score_f,
        "threshold": thr,
        "score_ok": score_f >= thr,
        "pattern_name": str(pattern_name or DEFAULT_PATTERN),
        "target_module": str(target_module or ""),
        "tests_to_run": tests,
        "method": str(method or DEFAULT_METHOD),
        "grade_id": str(grade_id or ""),
        "path": str(path or ""),
        "idea": float(idea) if idea is not None else None,
        "skill": float(skill) if skill is not None else None,
        "created_at": time.time(),
    }
    if extra:
        packet["extra"] = dict(extra)
    return packet


def validate_decision_packet(
    packet: Optional[dict[str, Any]],
    *,
    threshold: float = DEFAULT_SCORE_THRESHOLD,
    require_grade_id: bool = False,
) -> dict[str, Any]:
    """Validate decision packet; raise DecisionPacketError if unusable."""
    if not isinstance(packet, dict) or not packet:
        raise DecisionPacketError("decision packet required")
    repo = str(packet.get("source_repo") or "").strip()
    if not repo:
        raise DecisionPacketError("decision packet missing source_repo")
    try:
        score = float(packet.get("score"))
    except (TypeError, ValueError) as e:
        raise DecisionPacketError("decision packet score must be numeric") from e
    thr = float(packet.get("threshold") if packet.get("threshold") is not None else threshold)
    if score < thr:
        raise DecisionPacketError(
            f"score {score} below threshold {thr} for {repo}"
        )
    if require_grade_id and not str(packet.get("grade_id") or "").strip():
        raise DecisionPacketError("decision packet requires grade_id")
    pattern = str(packet.get("pattern_name") or "").strip()
    if not pattern:
        raise DecisionPacketError("decision packet missing pattern_name")
    return {
        "ok": True,
        "source_repo": repo,
        "score": score,
        "threshold": thr,
        "pattern_name": pattern,
        "grade_id": str(packet.get("grade_id") or ""),
    }


# ---------------------------------------------------------------------------
# Circuit-breaker protected call (grade/research path stub)
# ---------------------------------------------------------------------------


def protected_call(
    breaker: CircuitBreaker,
    name: str,
    fn: Callable[[], Any],
    *,
    on_blocked: Optional[Callable[[], Any]] = None,
) -> Any:
    """Run ``fn`` under circuit breaker; no live network required.

    - OPEN and not cooled down → raise WorkLedgerError (or call on_blocked)
    - failure → record_failure and re-raise
    - success → record_success
    """
    if not breaker.can_execute(name):
        if on_blocked is not None:
            return on_blocked()
        state = breaker.get(name).state.value
        raise WorkLedgerError(f"circuit {state} for {name}; call blocked")
    try:
        result = fn()
    except Exception as e:
        breaker.record_failure(name, str(e))
        raise
    breaker.record_success(name)
    return result


def make_grade_breaker(
    *,
    path: Optional[Path] = None,
    failure_threshold: int = 3,
    cooldown_s: float = 30.0,
) -> CircuitBreaker:
    """Factory for grade/research breakers (openrouter-deep-research pattern)."""
    return CircuitBreaker(
        failure_threshold=failure_threshold,
        cooldown_s=cooldown_s,
        path=path,
    )


# ---------------------------------------------------------------------------
# Work ledger
# ---------------------------------------------------------------------------


@dataclass
class WorkLedger:
    """Append-only SQLite work ledger for the improve state machine."""

    workdir: Path
    conn: sqlite3.Connection
    score_threshold: float = DEFAULT_SCORE_THRESHOLD

    @classmethod
    def open(
        cls,
        workdir: Optional[Path | str] = None,
        *,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> "WorkLedger":
        root = _root(workdir)
        path = db_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        store = cls(workdir=root, conn=conn, score_threshold=float(score_threshold))
        store._init()
        return store

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> "WorkLedger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS work_events (
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              agent TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT '',
              repo TEXT NOT NULL DEFAULT '',
              payload TEXT NOT NULL DEFAULT '{}',
              parent_id TEXT NOT NULL DEFAULT '',
              content_hash TEXT NOT NULL UNIQUE,
              created_at REAL NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_run "
            "ON work_events(run_id, created_at, id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_type "
            "ON work_events(event_type, created_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_repo "
            "ON work_events(repo, event_type)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS handoffs (
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              from_agent TEXT NOT NULL,
              to_agent TEXT NOT NULL,
              reason TEXT NOT NULL DEFAULT '',
              event_id TEXT NOT NULL DEFAULT '',
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
        # Append-only guards (soul / grade_ledger pattern)
        cur.execute("DROP TRIGGER IF EXISTS work_events_no_update")
        cur.execute("DROP TRIGGER IF EXISTS work_events_no_delete")
        cur.execute(
            """
            CREATE TRIGGER work_events_no_update BEFORE UPDATE ON work_events
            BEGIN
              SELECT RAISE(ABORT, 'work_events are append-only; UPDATE forbidden');
            END
            """
        )
        cur.execute(
            """
            CREATE TRIGGER work_events_no_delete BEFORE DELETE ON work_events
            BEGIN
              SELECT RAISE(ABORT, 'work_events are append-only; DELETE forbidden');
            END
            """
        )
        self.conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "event_type": row["event_type"],
            "agent": row["agent"],
            "role": row["role"] or "",
            "repo": row["repo"] or "",
            "payload": _json_loads(row["payload"]) or {},
            "parent_id": row["parent_id"] or "",
            "content_hash": row["content_hash"],
            "created_at": float(row["created_at"]),
        }

    def append(
        self,
        *,
        run_id: str,
        event_type: str,
        agent: str,
        role: str = "",
        repo: str = "",
        payload: Optional[dict[str, Any]] = None,
        parent_id: str = "",
        event_id: Optional[str] = None,
        created_at: Optional[float] = None,
        enforce_gates: bool = True,
    ) -> dict[str, Any]:
        """Append a work event. Idempotent on content_hash.

        When ``enforce_gates`` is True (default), apply_* events run dual-control
        and decision-packet checks.
        """
        rid = str(run_id or "").strip()
        et = str(event_type or "").strip()
        ag = str(agent or "").strip()
        if not rid:
            raise WorkLedgerError("run_id required")
        if not et:
            raise WorkLedgerError("event_type required")
        if et not in ALL_EVENTS:
            raise WorkLedgerError(f"unknown event_type: {et}")
        if not ag:
            raise WorkLedgerError("agent required")

        role_s = str(role or "").strip()
        repo_s = str(repo or "").strip()
        body = dict(payload or {})
        parent = str(parent_id or "").strip()

        if enforce_gates:
            # Dual-control / packet checks first so callers get precise errors
            if et in APPLY_EVENTS:
                self._gate_apply(
                    run_id=rid,
                    event_type=et,
                    agent=ag,
                    role=role_s,
                    repo=repo_s,
                    payload=body,
                )
            # P0.5: refuse illegal worker interleaving for this run (+ repo when set)
            prev = self._last_pipeline_event(run_id=rid, repo=repo_s)
            prev_type = prev.get("event_type") if prev else None
            assert_legal_transition(prev_type, et, enforce=True)

        ch = event_content_hash(
            run_id=rid,
            event_type=et,
            agent=ag,
            role=role_s,
            repo=repo_s,
            payload=body,
            parent_id=parent,
        )
        existing = self.conn.execute(
            "SELECT * FROM work_events WHERE content_hash = ?", (ch,)
        ).fetchone()
        if existing is not None:
            return self._row_to_dict(existing)

        eid = str(event_id or f"we-{uuid.uuid4().hex[:12]}")
        ts = float(created_at if created_at is not None else time.time())
        try:
            self.conn.execute(
                """
                INSERT INTO work_events(
                  id, run_id, event_type, agent, role, repo,
                  payload, parent_id, content_hash, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eid,
                    rid,
                    et,
                    ag,
                    role_s,
                    repo_s,
                    _json_dumps(body),
                    parent,
                    ch,
                    ts,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            msg = str(e).lower()
            if "append-only" in msg or "forbidden" in msg:
                raise ImmutableError(str(e)) from e
            existing = self.conn.execute(
                "SELECT * FROM work_events WHERE content_hash = ?", (ch,)
            ).fetchone()
            if existing is not None:
                return self._row_to_dict(existing)
            raise WorkLedgerError(f"append conflict: {e}") from e

        row = self.conn.execute(
            "SELECT * FROM work_events WHERE id = ?", (eid,)
        ).fetchone()
        if row is None:
            raise WorkLedgerError("append failed to persist")
        return self._row_to_dict(row)

    def _find_grade(
        self,
        *,
        run_id: str,
        repo: str = "",
        grade_id: str = "",
    ) -> Optional[dict[str, Any]]:
        rows = self.list_run(run_id, event_type=EVENT_GRADE_RECORDED)
        if grade_id:
            for r in rows:
                if r["id"] == grade_id:
                    return r
                if str((r.get("payload") or {}).get("grade_id") or "") == grade_id:
                    return r
        if repo:
            for r in reversed(rows):
                if r.get("repo") == repo:
                    return r
        return rows[-1] if rows else None

    def _last_pipeline_event(
        self,
        *,
        run_id: str,
        repo: str = "",
    ) -> Optional[dict[str, Any]]:
        """Most recent non-breaker event for run (optionally filtered by repo)."""
        rows = self.list_run(run_id, limit=500)
        for r in reversed(rows):
            if r.get("event_type") == EVENT_BREAKER:
                continue
            if repo and r.get("repo") and r.get("repo") != repo:
                continue
            return r
        return None

    def last_pipeline_type(
        self, run_id: str, *, repo: str = ""
    ) -> Optional[str]:
        ev = self._last_pipeline_event(run_id=run_id, repo=repo)
        return str(ev["event_type"]) if ev else None

    def _gate_apply(
        self,
        *,
        run_id: str,
        event_type: str,
        agent: str,
        role: str,
        repo: str,
        payload: dict[str, Any],
    ) -> None:
        """Fail-closed gates for apply_proposed / apply_rejected / apply_accepted."""
        grade_id = str(payload.get("grade_id") or "").strip()
        grade = self._find_grade(run_id=run_id, repo=repo, grade_id=grade_id)

        if event_type == EVENT_APPLY_ACCEPTED:
            if grade is None:
                raise DualControlError(
                    "apply_accepted requires prior grade_recorded "
                    f"(run_id={run_id}, repo={repo or '?'})"
                )
            # Dual control: applier role/agent must differ from grader
            grade_role = _norm_role(grade.get("role") or ROLE_GRADER)
            grade_agent = _norm_role(grade.get("agent") or "")
            apply_role = _norm_role(role or ROLE_APPLIER)
            apply_agent = _norm_role(agent)
            if apply_role and grade_role and apply_role == grade_role:
                raise DualControlError(
                    f"dual-control: same role cannot grade and accept "
                    f"(role={apply_role})"
                )
            if apply_agent and grade_agent and apply_agent == grade_agent:
                raise DualControlError(
                    f"dual-control: same agent cannot grade and accept "
                    f"(agent={apply_agent})"
                )
            # Decision packet required for accept
            packet = payload.get("decision_packet")
            if packet is None and grade_id:
                # look up recorded decision_packet event
                for ev in self.list_run(run_id, event_type=EVENT_DECISION_PACKET):
                    p = ev.get("payload") or {}
                    if str(p.get("grade_id") or "") == grade_id or (
                        repo and ev.get("repo") == repo
                    ):
                        packet = p.get("packet") or p
                        break
            if packet is None and "score" in payload:
                packet = payload
            validate_decision_packet(
                packet if isinstance(packet, dict) else None,
                threshold=self.score_threshold,
            )
            # Ensure grade_id is stamped for audit
            if not grade_id:
                payload["grade_id"] = grade["id"]
            payload.setdefault("grader_agent", grade.get("agent"))
            payload.setdefault("grader_role", grade.get("role"))

        if event_type == EVENT_APPLY_PROPOSED:
            # Prefer explicit packet; soft-require grade when present
            packet = payload.get("decision_packet") or payload.get("packet")
            if packet is None and {"source_repo", "score", "pattern_name"} <= set(
                payload.keys()
            ):
                packet = payload
            if packet is not None:
                validate_decision_packet(
                    packet if isinstance(packet, dict) else None,
                    threshold=self.score_threshold,
                )
            elif grade is None and not payload.get("allow_ungraded"):
                raise TransitionError(
                    "apply_proposed without grade_recorded or decision_packet"
                )

    # -- typed helpers -------------------------------------------------------

    def record_mine(
        self,
        *,
        run_id: str,
        repo: str,
        score: float,
        path: str = "",
        agent: str = DEFAULT_ROLES[ROLE_MINER],
        role: str = ROLE_MINER,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        payload = {
            "repo": repo,
            "score": float(score),
            "path": path,
            **(extra or {}),
        }
        return self.append(
            run_id=run_id,
            event_type=EVENT_MINE_COMPLETED,
            agent=agent,
            role=role,
            repo=repo,
            payload=payload,
        )

    def record_grade(
        self,
        *,
        run_id: str,
        repo: str,
        score: float,
        idea: float,
        skill: float,
        method: str = DEFAULT_METHOD,
        path: str = "",
        agent: str = DEFAULT_ROLES[ROLE_GRADER],
        role: str = ROLE_GRADER,
        parent_id: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        payload = {
            "repo": repo,
            "score": float(score),
            "idea": float(idea),
            "skill": float(skill),
            "method": method,
            "path": path,
            "total": float(score),
            **(extra or {}),
        }
        return self.append(
            run_id=run_id,
            event_type=EVENT_GRADE_RECORDED,
            agent=agent,
            role=role,
            repo=repo,
            payload=payload,
            parent_id=parent_id,
        )

    def record_decision(
        self,
        *,
        run_id: str,
        packet: dict[str, Any],
        agent: str = DEFAULT_ROLES[ROLE_APPLIER],
        role: str = ROLE_APPLIER,
        parent_id: str = "",
    ) -> dict[str, Any]:
        validate_decision_packet(packet, threshold=self.score_threshold)
        repo = str(packet.get("source_repo") or "")
        return self.append(
            run_id=run_id,
            event_type=EVENT_DECISION_PACKET,
            agent=agent,
            role=role,
            repo=repo,
            payload={"packet": packet, "grade_id": packet.get("grade_id") or ""},
            parent_id=parent_id,
        )

    def propose_apply(
        self,
        *,
        run_id: str,
        packet: dict[str, Any],
        agent: str = DEFAULT_ROLES[ROLE_APPLIER],
        role: str = ROLE_APPLIER,
        parent_id: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        validate_decision_packet(packet, threshold=self.score_threshold)
        repo = str(packet.get("source_repo") or "")
        return self.append(
            run_id=run_id,
            event_type=EVENT_APPLY_PROPOSED,
            agent=agent,
            role=role,
            repo=repo,
            payload={
                "decision_packet": packet,
                "grade_id": str(packet.get("grade_id") or ""),
                "note": note or f"propose pattern {packet.get('pattern_name')}",
            },
            parent_id=parent_id,
        )

    def accept_apply(
        self,
        *,
        run_id: str,
        packet: dict[str, Any],
        agent: str = DEFAULT_ROLES[ROLE_APPLIER],
        role: str = ROLE_APPLIER,
        parent_id: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        """Accept apply — dual-control + grade gate enforced."""
        validate_decision_packet(packet, threshold=self.score_threshold)
        repo = str(packet.get("source_repo") or "")
        return self.append(
            run_id=run_id,
            event_type=EVENT_APPLY_ACCEPTED,
            agent=agent,
            role=role,
            repo=repo,
            payload={
                "decision_packet": packet,
                "grade_id": str(packet.get("grade_id") or ""),
                "note": note or "apply accepted under dual-control",
            },
            parent_id=parent_id,
        )

    def reject_apply(
        self,
        *,
        run_id: str,
        repo: str,
        reason: str,
        agent: str = DEFAULT_ROLES[ROLE_APPLIER],
        role: str = ROLE_APPLIER,
        grade_id: str = "",
        parent_id: str = "",
    ) -> dict[str, Any]:
        return self.append(
            run_id=run_id,
            event_type=EVENT_APPLY_REJECTED,
            agent=agent,
            role=role,
            repo=repo,
            payload={"reason": reason, "grade_id": grade_id},
            parent_id=parent_id,
            enforce_gates=False,  # rejection always allowed
        )

    def handoff(
        self,
        *,
        run_id: str,
        from_agent: str,
        to_agent: str,
        reason: str = "",
        event_id: str = "",
    ) -> dict[str, Any]:
        hid = f"ho-{uuid.uuid4().hex[:12]}"
        ts = time.time()
        self.conn.execute(
            """
            INSERT INTO handoffs(id, run_id, from_agent, to_agent, reason, event_id, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hid,
                str(run_id),
                str(from_agent),
                str(to_agent),
                str(reason or ""),
                str(event_id or ""),
                ts,
            ),
        )
        self.conn.commit()
        return {
            "id": hid,
            "run_id": run_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "reason": reason,
            "event_id": event_id,
            "created_at": ts,
        }

    # -- query ---------------------------------------------------------------

    def get(self, event_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM work_events WHERE id = ?", (str(event_id),)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_run(
        self,
        run_id: str,
        *,
        event_type: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        n = max(1, int(limit))
        if event_type:
            rows = self.conn.execute(
                """
                SELECT * FROM work_events
                WHERE run_id = ? AND event_type = ?
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (str(run_id), str(event_type), n),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM work_events
                WHERE run_id = ?
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (str(run_id), n),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def tail(
        self, *, limit: int = 20, run_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        n = max(1, int(limit))
        if run_id:
            rows = self.conn.execute(
                """
                SELECT * FROM work_events
                WHERE run_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (str(run_id), n),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM work_events
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (n,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self, *, run_id: Optional[str] = None) -> int:
        if run_id:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM work_events WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM work_events"
            ).fetchone()
        return int(row["n"] if row else 0)

    def try_update_forbidden(self, event_id: str) -> None:
        """Test helper: attempt UPDATE (must raise ImmutableError)."""
        try:
            self.conn.execute(
                "UPDATE work_events SET agent = ? WHERE id = ?",
                ("mutated", str(event_id)),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise ImmutableError(str(e)) from e

    def try_delete_forbidden(self, event_id: str) -> None:
        """Test helper: attempt DELETE (must raise ImmutableError)."""
        try:
            self.conn.execute(
                "DELETE FROM work_events WHERE id = ?", (str(event_id),)
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise ImmutableError(str(e)) from e

    def causal_chain(self, run_id: str) -> list[dict[str, Any]]:
        """Lumen-style causal audit chain for one improve run (2302.10809)."""
        events = self.list_run(run_id)
        chain: list[dict[str, Any]] = []
        for i, ev in enumerate(events):
            because = None
            if ev.get("parent_id"):
                because = ev["parent_id"]
            elif i > 0:
                because = events[i - 1]["id"]
            why = _why_event(ev)
            chain.append(
                {
                    "seq": i + 1,
                    "event_id": ev["id"],
                    "event_type": ev["event_type"],
                    "agent": ev["agent"],
                    "role": ev["role"],
                    "repo": ev["repo"],
                    "because_of_event_id": because,
                    "why": why,
                    "created_at": ev["created_at"],
                }
            )
        return chain


def _why_event(ev: dict[str, Any]) -> str:
    et = ev.get("event_type")
    repo = ev.get("repo") or "?"
    payload = ev.get("payload") or {}
    if et == EVENT_MINE_COMPLETED:
        return f"mined {repo} score={payload.get('score')}"
    if et == EVENT_GRADE_RECORDED:
        return (
            f"graded {repo} method={payload.get('method')} "
            f"idea={payload.get('idea')} skill={payload.get('skill')} "
            f"total={payload.get('score')}"
        )
    if et == EVENT_DECISION_PACKET:
        pkt = payload.get("packet") or payload
        return (
            f"decision for {pkt.get('source_repo')}: "
            f"pattern={pkt.get('pattern_name')} score_ok={pkt.get('score_ok')}"
        )
    if et == EVENT_APPLY_PROPOSED:
        return f"proposed apply for {repo}: {payload.get('note') or ''}"
    if et == EVENT_APPLY_ACCEPTED:
        return f"accepted apply for {repo} under dual-control"
    if et == EVENT_APPLY_REJECTED:
        return f"rejected apply for {repo}: {payload.get('reason')}"
    if et == EVENT_BREAKER:
        return f"breaker {payload.get('name')} → {payload.get('state')}"
    return f"{et} by {ev.get('agent')}"


def format_causal_chain(chain: list[dict[str, Any]]) -> str:
    """Human-readable lumen-style audit for demos."""
    if not chain:
        return "(empty causal chain)"
    lines = ["Causal chain (work ledger):"]
    for step in chain:
        because = step.get("because_of_event_id") or "—"
        lines.append(
            f"  {step['seq']}. [{step['event_type']}] {step['why']} "
            f"(agent={step['agent']} role={step['role']} because_of={because})"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Integration: first-slice loop (offline, fixture-driven)
# ---------------------------------------------------------------------------


@dataclass
class FirstSliceResult:
    ok: bool
    run_id: str
    repo: str
    events: list[dict[str, Any]] = field(default_factory=list)
    decision_packet: Optional[dict[str, Any]] = None
    chain: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    accepted: bool = False
    rejected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "ok": self.ok,
            "run_id": self.run_id,
            "repo": self.repo,
            "events": self.events,
            "decision_packet": self.decision_packet,
            "chain": self.chain,
            "error": self.error,
            "accepted": self.accepted,
            "rejected": self.rejected,
        }


def _load_fixture_grade(
    workdir: Path,
    *,
    fixture: Optional[Path | str] = None,
    repo: Optional[str] = None,
) -> dict[str, Any]:
    """Load one offline grade row (fixture or IMPROVE_OURS digest)."""
    from .load_mine_eval import load_one

    return load_one(workdir, repo=repo, fixture=fixture)


def run_first_slice(
    workdir: Path | str,
    *,
    fixture: Optional[Path | str] = None,
    repo: Optional[str] = None,
    run_id: Optional[str] = None,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    pattern_name: str = DEFAULT_PATTERN,
    target_module: str = "src/nexus/work_ledger.py",
    accept: bool = True,
    grader: str = DEFAULT_ROLES[ROLE_GRADER],
    applier: str = DEFAULT_ROLES[ROLE_APPLIER],
    miner: str = DEFAULT_ROLES[ROLE_MINER],
    breaker: Optional[CircuitBreaker] = None,
    simulate_grade_failures: int = 0,
) -> dict[str, Any]:
    """End-to-end offline proof: mine → grade → decision → propose → accept/reject.

    Uses fixture grades (e.g. labsai/EDDI 17.0 or wshobson/agents 16.0).
    Circuit breaker exercises the grade call path with optional fake failures.
    """
    root = _root(workdir)
    rid = run_id or f"wslice-{uuid.uuid4().hex[:10]}"
    br = breaker or make_grade_breaker(
        path=ledger_dir(root) / "breaker_grade.json",
        failure_threshold=3,
        cooldown_s=0.0,
    )
    result = FirstSliceResult(ok=False, run_id=rid, repo="")

    try:
        with WorkLedger.open(root, score_threshold=score_threshold) as led:
            # --- mine (offline digest load) ---
            grade_row = _load_fixture_grade(root, fixture=fixture, repo=repo)
            result.repo = str(grade_row.get("repo") or "")
            path = str(grade_row.get("path") or "")
            score = float(grade_row.get("score") or 0)
            idea = float(grade_row.get("idea") or 0)
            skill = float(grade_row.get("skill") or 0)
            method = str(grade_row.get("method") or DEFAULT_METHOD)

            mine_ev = led.record_mine(
                run_id=rid,
                repo=result.repo,
                score=score,
                path=path,
                agent=miner,
            )
            result.events.append(mine_ev)
            led.handoff(
                run_id=rid,
                from_agent=miner,
                to_agent=grader,
                reason="mine_completed → grade",
                event_id=mine_ev["id"],
            )

            # --- grade under circuit breaker (stub external call) ---
            fail_budget = {"n": int(simulate_grade_failures)}

            def _grade_call() -> dict[str, Any]:
                if fail_budget["n"] > 0:
                    fail_budget["n"] -= 1
                    raise RuntimeError("simulated grade provider failure")
                return {
                    "repo": result.repo,
                    "score": score,
                    "idea": idea,
                    "skill": skill,
                    "method": method,
                    "path": path,
                }

            graded = protected_call(br, "grade:grok-4.5", _grade_call)
            grade_ev = led.record_grade(
                run_id=rid,
                repo=result.repo,
                score=float(graded["score"]),
                idea=float(graded["idea"]),
                skill=float(graded["skill"]),
                method=str(graded["method"]),
                path=str(graded.get("path") or ""),
                agent=grader,
                parent_id=mine_ev["id"],
            )
            result.events.append(grade_ev)
            led.handoff(
                run_id=rid,
                from_agent=grader,
                to_agent=applier,
                reason="grade_recorded → decide/apply",
                event_id=grade_ev["id"],
            )

            # --- decision packet ---
            packet = build_decision_packet(
                source_repo=result.repo,
                score=float(graded["score"]),
                pattern_name=pattern_name
                or str(grade_row.get("pattern") or DEFAULT_PATTERN),
                target_module=target_module,
                tests_to_run=["tests/test_work_ledger.py"],
                idea=float(graded["idea"]),
                skill=float(graded["skill"]),
                method=str(graded["method"]),
                grade_id=grade_ev["id"],
                threshold=score_threshold,
                path=str(graded.get("path") or ""),
            )
            result.decision_packet = packet

            if not packet["score_ok"]:
                rej = led.reject_apply(
                    run_id=rid,
                    repo=result.repo,
                    reason=f"score {packet['score']} < threshold {score_threshold}",
                    agent=applier,
                    grade_id=grade_ev["id"],
                    parent_id=grade_ev["id"],
                )
                result.events.append(rej)
                result.rejected = True
                result.chain = led.causal_chain(rid)
                result.ok = True  # loop proved even on reject path
                return result.to_dict()

            dec_ev = led.record_decision(
                run_id=rid,
                packet=packet,
                agent=applier,
                parent_id=grade_ev["id"],
            )
            result.events.append(dec_ev)

            prop = led.propose_apply(
                run_id=rid,
                packet=packet,
                agent=applier,
                parent_id=dec_ev["id"],
                note=f"pattern note: {pattern_name}",
            )
            result.events.append(prop)

            if accept:
                acc = led.accept_apply(
                    run_id=rid,
                    packet=packet,
                    agent=applier,
                    parent_id=prop["id"],
                )
                result.events.append(acc)
                result.accepted = True
            else:
                rej = led.reject_apply(
                    run_id=rid,
                    repo=result.repo,
                    reason="operator rejected proposal",
                    agent=applier,
                    grade_id=grade_ev["id"],
                    parent_id=prop["id"],
                )
                result.events.append(rej)
                result.rejected = True

            result.chain = led.causal_chain(rid)
            result.ok = True
            return result.to_dict()
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
        result.ok = False
        return result.to_dict()


def format_slice_report(report: dict[str, Any]) -> str:
    lines = [
        f"work-ledger first-slice  ok={report.get('ok')}  run_id={report.get('run_id')}",
        f"  repo={report.get('repo')}  accepted={report.get('accepted')}  "
        f"rejected={report.get('rejected')}",
    ]
    if report.get("error"):
        lines.append(f"  error: {report['error']}")
    pkt = report.get("decision_packet") or {}
    if pkt:
        lines.append(
            f"  packet: pattern={pkt.get('pattern_name')!r} "
            f"score={pkt.get('score')} thr={pkt.get('threshold')} "
            f"target={pkt.get('target_module')}"
        )
    events = report.get("events") or []
    if events:
        lines.append("  events:")
        for ev in events:
            lines.append(
                f"    - {ev.get('event_type'):<18} agent={ev.get('agent')} "
                f"id={ev.get('id')}"
            )
    chain = report.get("chain") or []
    if chain:
        lines.append(format_causal_chain(chain))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Integration: worktree_apply / alive self_approve gate
# ---------------------------------------------------------------------------


def ensure_apply_gate(
    workdir: Path | str,
    *,
    grade: dict[str, Any],
    run_id: Optional[str] = None,
    pattern_name: str = DEFAULT_PATTERN,
    target_module: str = "src/nexus/work_ledger.py",
    score_threshold: Optional[float] = None,
    grader: str = DEFAULT_ROLES[ROLE_GRADER],
    applier: str = DEFAULT_ROLES[ROLE_APPLIER],
    miner: str = DEFAULT_ROLES[ROLE_MINER],
    accept: bool = True,
    tests_to_run: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Record mine→grade→decision→propose→accept|reject for a graded repo.

    Used by ``worktree_apply.run_apply`` and ``alive`` self_approve before hard
    apply. Fail-closed on dual-control collusion, score threshold, or illegal
    transitions. Idempotent on content_hash when the same packet is re-gated.
    """
    root = _root(workdir)
    rid = str(run_id or f"wgate-{uuid.uuid4().hex[:10]}")
    repo = str(grade.get("repo") or "").strip()
    if not repo:
        return {
            "schema": SCHEMA_VERSION,
            "ok": False,
            "accepted": False,
            "rejected": False,
            "run_id": rid,
            "repo": "",
            "error": "grade.repo required",
            "events": [],
            "decision_packet": None,
            "chain": [],
        }
    try:
        score = float(grade.get("score") if grade.get("score") is not None else 0)
    except (TypeError, ValueError):
        score = 0.0
    try:
        idea = float(grade.get("idea") if grade.get("idea") is not None else 0)
    except (TypeError, ValueError):
        idea = 0.0
    try:
        skill = float(grade.get("skill") if grade.get("skill") is not None else 0)
    except (TypeError, ValueError):
        skill = 0.0
    method = str(grade.get("method") or DEFAULT_METHOD)
    path = str(grade.get("path") or "")
    thr = float(
        score_threshold
        if score_threshold is not None
        else DEFAULT_SCORE_THRESHOLD
    )
    pat = str(
        pattern_name
        or grade.get("pattern")
        or grade.get("pattern_name")
        or DEFAULT_PATTERN
    )
    tests = list(tests_to_run or ["tests/test_work_ledger.py"])
    out: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "ok": False,
        "accepted": False,
        "rejected": False,
        "run_id": rid,
        "repo": repo,
        "error": None,
        "events": [],
        "decision_packet": None,
        "chain": [],
        "score_threshold": thr,
        "grader": grader,
        "applier": applier,
    }
    try:
        with WorkLedger.open(root, score_threshold=thr) as led:
            # Fast path: already accepted this run/repo
            for ev in led.list_run(rid, event_type=EVENT_APPLY_ACCEPTED):
                if ev.get("repo") == repo:
                    out["ok"] = True
                    out["accepted"] = True
                    out["events"] = led.list_run(rid)
                    out["chain"] = led.causal_chain(rid)
                    out["decision_packet"] = (ev.get("payload") or {}).get(
                        "decision_packet"
                    )
                    out["cached"] = True
                    return out

            # Resume-safe cursor for this run/repo (P0.5 interleaving)
            cursor = led.last_pipeline_type(rid, repo=repo)
            events_for_repo = [
                e
                for e in led.list_run(rid)
                if not repo or e.get("repo") in ("", repo)
            ]
            out["events"] = list(events_for_repo)
            out["resumed_from"] = cursor

            mine_ev: Optional[dict[str, Any]] = None
            grade_ev: Optional[dict[str, Any]] = None
            for e in events_for_repo:
                if e.get("event_type") == EVENT_MINE_COMPLETED:
                    mine_ev = e
                elif e.get("event_type") == EVENT_GRADE_RECORDED:
                    grade_ev = e

            if cursor is None or cursor in (
                EVENT_APPLY_ACCEPTED,
                EVENT_APPLY_REJECTED,
            ):
                # Fresh cycle (or after terminal apply)
                mine_ev = led.record_mine(
                    run_id=rid,
                    repo=repo,
                    score=score,
                    path=path,
                    agent=miner,
                )
                out["events"].append(mine_ev)
                cursor = EVENT_MINE_COMPLETED

            if cursor == EVENT_MINE_COMPLETED:
                grade_ev = led.record_grade(
                    run_id=rid,
                    repo=repo,
                    score=score,
                    idea=idea,
                    skill=skill,
                    method=method,
                    path=path,
                    agent=grader,
                    role=ROLE_GRADER,
                    parent_id=(mine_ev or {}).get("id") or "",
                )
                out["events"].append(grade_ev)
                cursor = EVENT_GRADE_RECORDED

            if grade_ev is None:
                # Offline start at grade without mine (LEGAL_SUCCESSORS allows)
                if cursor is None:
                    grade_ev = led.record_grade(
                        run_id=rid,
                        repo=repo,
                        score=score,
                        idea=idea,
                        skill=skill,
                        method=method,
                        path=path,
                        agent=grader,
                        role=ROLE_GRADER,
                    )
                    out["events"].append(grade_ev)
                    cursor = EVENT_GRADE_RECORDED
                else:
                    grade_ev = led._find_grade(run_id=rid, repo=repo)

            if grade_ev is None:
                out["error"] = "grade_recorded missing after resume"
                out["ok"] = False
                return out

            packet = build_decision_packet(
                source_repo=repo,
                score=score,
                pattern_name=pat,
                target_module=target_module,
                tests_to_run=tests,
                idea=idea,
                skill=skill,
                method=method,
                grade_id=grade_ev["id"],
                threshold=thr,
                path=path,
            )
            out["decision_packet"] = packet

            if not packet["score_ok"] or not accept:
                reason = (
                    f"score {packet['score']} < threshold {thr}"
                    if not packet["score_ok"]
                    else "operator/applier declined accept"
                )
                rej = led.reject_apply(
                    run_id=rid,
                    repo=repo,
                    reason=reason,
                    agent=applier,
                    role=ROLE_APPLIER,
                    grade_id=grade_ev["id"],
                    parent_id=grade_ev["id"],
                )
                out["events"].append(rej)
                out["rejected"] = True
                out["ok"] = True
                out["chain"] = led.causal_chain(rid)
                out["error"] = reason if not packet["score_ok"] else None
                return out

            if cursor == EVENT_GRADE_RECORDED:
                dec_ev = led.record_decision(
                    run_id=rid,
                    packet=packet,
                    agent=applier,
                    role=ROLE_APPLIER,
                    parent_id=grade_ev["id"],
                )
                out["events"].append(dec_ev)
                cursor = EVENT_DECISION_PACKET
            else:
                dec_ev = None
                for e in reversed(events_for_repo):
                    if e.get("event_type") == EVENT_DECISION_PACKET:
                        dec_ev = e
                        break

            if cursor == EVENT_DECISION_PACKET:
                prop = led.propose_apply(
                    run_id=rid,
                    packet=packet,
                    agent=applier,
                    role=ROLE_APPLIER,
                    parent_id=(dec_ev or grade_ev)["id"],
                    note=f"gate propose pattern={pat}",
                )
                out["events"].append(prop)
                cursor = EVENT_APPLY_PROPOSED
            else:
                prop = None
                for e in reversed(led.list_run(rid, event_type=EVENT_APPLY_PROPOSED)):
                    if e.get("repo") == repo:
                        prop = e
                        break

            if cursor == EVENT_APPLY_PROPOSED:
                acc = led.accept_apply(
                    run_id=rid,
                    packet=packet,
                    agent=applier,
                    role=ROLE_APPLIER,
                    parent_id=(prop or grade_ev)["id"],
                    note="gate accept under dual-control",
                )
                out["events"].append(acc)
                out["accepted"] = True
                out["ok"] = True
                out["chain"] = led.causal_chain(rid)
                led.handoff(
                    run_id=rid,
                    from_agent=grader,
                    to_agent=applier,
                    reason="grade → apply accepted",
                    event_id=acc["id"],
                )
                return out

            out["error"] = f"unexpected cursor after resume: {cursor}"
            out["ok"] = False
            out["chain"] = led.causal_chain(rid)
            return out
    except (WorkLedgerError, DualControlError, DecisionPacketError, TransitionError) as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["ok"] = False
        out["accepted"] = False
        return out
    except Exception as e:  # noqa: BLE001 — surface as gate deny
        out["error"] = f"{type(e).__name__}: {e}"
        out["ok"] = False
        out["accepted"] = False
        return out


def work_ledger_status(
    workdir: Path | str,
    *,
    run_id: Optional[str] = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Operator/MCP snapshot of the work ledger."""
    root = _root(workdir)
    path = db_path(root)
    with WorkLedger.open(root) as led:
        events = led.tail(limit=limit, run_id=run_id)
        chain = led.causal_chain(run_id) if run_id else []
        return {
            "schema": SCHEMA_VERSION,
            "path": str(path),
            "count": led.count(run_id=run_id),
            "run_id": run_id,
            "events": events,
            "chain": chain,
            "legal_successors": {
                (k if k is not None else "∅"): sorted(v)
                for k, v in LEGAL_SUCCESSORS.items()
                if k != EVENT_BREAKER
            },
        }
