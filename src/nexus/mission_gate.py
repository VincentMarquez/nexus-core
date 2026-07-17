"""Mission-control quality gate + completion receipts + spend hard-caps.

Pattern (shape only — not a vendored tree):

  builderz-labs/mission-control
      self-hosted SQLite control plane with task governance,
      Aegis-style quality reviews before completion, spend tracking,
      and tamper-evident completion / audit receipts.

Binds to :class:`ops_store.OpsStore` (same ``ops.sqlite``) and adds:

  * ``quality_reviews`` — approved | rejected | needs_work | pending
  * ``completion_receipts`` — SHA-256 payload hash + HMAC-SHA256 signature
  * job.meta.mission_gate policy — require_review / max_tokens / require_receipt
  * fail-closed ``complete()`` and optional ``gated_record_spend()``

Schema: ``nexus.mission_gate/v1``

Stdlib-only: HMAC-SHA256 stands in for mission-control's Ed25519 receipt
shape (canonicalize → hash → sign → offline verify). No tree vendor.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .ops_store import OpsError, OpsStore, TERMINAL_JOB_STATUSES

SCHEMA = "nexus.mission_gate/v1"
SOURCE_PATTERN = "builderz-labs/mission-control"
SOURCE_URL = "https://github.com/builderz-labs/mission-control"
META_KEY = "mission_gate"
HMAC_META_KEY = "mission_gate_hmac_secret"

REVIEW_STATUSES = frozenset({"approved", "rejected", "needs_work", "pending"})
APPROVED = "approved"

# Policy defaults when enable_gate() is called without overrides.
DEFAULT_REQUIRE_REVIEW = True
DEFAULT_REQUIRE_RECEIPT = True


class MissionGateError(RuntimeError):
    """Invalid quality-gate / receipt / spend-cap operation."""

    def __init__(self, message: str, *, code: str = "mission_gate_error") -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "MissionGateError",
            "code": self.code,
            "message": str(self),
        }


# ---------------------------------------------------------------------------
# Canonical receipt (mission-control receipt-signing shape, HMAC variant)
# ---------------------------------------------------------------------------


def canonicalize(obj: Any) -> str:
    """Deterministic JSON for hashing (sorted keys, compact separators)."""

    def _sort(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _sort(value[k]) for k in sorted(value.keys())}
        if isinstance(value, (list, tuple)):
            return [_sort(v) for v in value]
        return value

    return json.dumps(_sort(obj), separators=(",", ":"), default=str)


def payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 hex of canonical payload."""
    return hashlib.sha256(canonicalize(payload).encode("utf-8")).hexdigest()


def sign_receipt(
    payload: dict[str, Any],
    *,
    secret: str,
) -> dict[str, Any]:
    """Produce a tamper-evident receipt (hash + HMAC-SHA256).

    Shape mirrors mission-control ``signAuditRecord``:
    ``payloadHash`` + ``signature`` + key id material for offline verify.
    """
    if not isinstance(payload, dict):
        raise MissionGateError("payload must be a dict", code="invalid_payload")
    sec = str(secret or "").strip()
    if not sec:
        raise MissionGateError("signing secret required", code="secret_required")
    canonical = canonicalize(payload)
    ph = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    sig = hmac.new(
        sec.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    key_id = hashlib.sha256(sec.encode("utf-8")).hexdigest()[:16]
    return {
        "schema": SCHEMA,
        "payload_hash": ph,
        "signature": sig,
        "alg": "HMAC-SHA256",
        "key_id": key_id,
        "source_pattern": SOURCE_PATTERN,
    }


def verify_receipt(
    payload: dict[str, Any],
    receipt: dict[str, Any],
    *,
    secret: str,
) -> bool:
    """Recompute hash + HMAC; True when payload was not tampered with."""
    if not isinstance(payload, dict) or not isinstance(receipt, dict):
        return False
    sec = str(secret or "").strip()
    if not sec:
        return False
    try:
        expected = sign_receipt(payload, secret=sec)
    except MissionGateError:
        return False
    got_hash = str(receipt.get("payload_hash") or receipt.get("payloadHash") or "")
    got_sig = str(receipt.get("signature") or "")
    return (
        hmac.compare_digest(got_hash, expected["payload_hash"])
        and hmac.compare_digest(got_sig, expected["signature"])
    )


# ---------------------------------------------------------------------------
# Store wrapper
# ---------------------------------------------------------------------------


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


def _root(workdir: Optional[Path | str] = None) -> Path:
    import os

    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


@dataclass
class MissionGate:
    """Quality reviews + completion receipts + spend caps on OpsStore."""

    store: OpsStore

    @classmethod
    def open(cls, workdir: Optional[Path | str] = None) -> "MissionGate":
        store = OpsStore.open(workdir)
        gate = cls(store=store)
        gate._init_tables()
        return gate

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "MissionGate":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @property
    def workdir(self) -> Path:
        return self.store.workdir

    @property
    def conn(self) -> sqlite3.Connection:
        return self.store.conn

    def _init_tables(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_reviews (
              id TEXT PRIMARY KEY,
              job_id TEXT NOT NULL,
              reviewer TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending',
              notes TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              meta TEXT NOT NULL DEFAULT '{}',
              FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality_reviews_job "
            "ON quality_reviews(job_id, created_at DESC)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS completion_receipts (
              id TEXT PRIMARY KEY,
              job_id TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              signature TEXT NOT NULL,
              alg TEXT NOT NULL DEFAULT 'HMAC-SHA256',
              key_id TEXT NOT NULL DEFAULT '',
              payload TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL,
              FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_completion_receipts_job "
            "ON completion_receipts(job_id, created_at DESC)"
        )
        self.conn.commit()

    # -- signing secret (ops meta; never dual-written to usage) ------------

    def get_or_create_secret(self) -> str:
        """Return durable HMAC secret from ops meta (generated once)."""
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (HMAC_META_KEY,),
        ).fetchone()
        if row and str(row["value"] or "").strip():
            return str(row["value"])
        sec = secrets.token_hex(32)
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            (HMAC_META_KEY, sec),
        )
        self.conn.commit()
        return sec

    # -- policy on job.meta.mission_gate -----------------------------------

    def _policy(self, job: dict[str, Any]) -> dict[str, Any]:
        meta = job.get("meta") if isinstance(job.get("meta"), dict) else {}
        raw = meta.get(META_KEY) if isinstance(meta, dict) else None
        return dict(raw) if isinstance(raw, dict) else {}

    def _write_policy(self, job_id: str, policy: dict[str, Any]) -> dict[str, Any]:
        job = self.store.get(job_id)
        if job is None:
            raise MissionGateError(f"job not found: {job_id}", code="job_not_found")
        m = dict(job.get("meta") or {})
        m[META_KEY] = policy
        m["source_pattern"] = SOURCE_PATTERN
        self.store.upsert_job(
            job_id,
            kind=str(job.get("kind") or "task"),
            title=str(job.get("title") or job_id),
            status=str(job.get("status") or "inbox"),
            goal=str(job.get("goal") or ""),
            meta=m,
        )
        return self.store.get(job_id) or job

    def enable_gate(
        self,
        job_id: str,
        *,
        require_review: bool = DEFAULT_REQUIRE_REVIEW,
        require_receipt: bool = DEFAULT_REQUIRE_RECEIPT,
        max_tokens: Optional[int] = None,
        kind: str = "task",
        title: str = "",
        goal: str = "",
        status: str = "running",
    ) -> dict[str, Any]:
        """Ensure job exists and attach mission-gate policy (opt-in)."""
        jid = str(job_id or "").strip()
        if not jid:
            raise MissionGateError("job_id required", code="job_id_required")
        self.store.ensure_job(
            jid,
            kind=kind,
            title=title or jid,
            status=status,
            goal=goal,
        )
        job = self.store.get(jid) or {}
        policy = self._policy(job)
        policy.update(
            {
                "enabled": True,
                "require_review": bool(require_review),
                "require_receipt": bool(require_receipt),
                "schema": SCHEMA,
                "source_pattern": SOURCE_PATTERN,
            }
        )
        if max_tokens is not None:
            mt = max(0, int(max_tokens))
            policy["max_tokens"] = mt
        job = self._write_policy(jid, policy)
        return {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "job_id": jid,
            "policy": self._policy(job),
            "job": job,
        }

    def set_spend_cap(self, job_id: str, max_tokens: int) -> dict[str, Any]:
        """Set hard token cap on job (mission-control spend governance)."""
        jid = str(job_id or "").strip()
        if not jid:
            raise MissionGateError("job_id required", code="job_id_required")
        job = self.store.get(jid)
        if job is None:
            raise MissionGateError(f"job not found: {jid}", code="job_not_found")
        policy = self._policy(job)
        policy["enabled"] = True
        policy["max_tokens"] = max(0, int(max_tokens))
        policy.setdefault("require_review", DEFAULT_REQUIRE_REVIEW)
        policy.setdefault("require_receipt", DEFAULT_REQUIRE_RECEIPT)
        policy["schema"] = SCHEMA
        job = self._write_policy(jid, policy)
        return {
            "schema": SCHEMA,
            "job_id": jid,
            "max_tokens": policy["max_tokens"],
            "policy": self._policy(job),
        }

    # -- quality reviews (Aegis-shaped) ------------------------------------

    def record_review(
        self,
        job_id: str,
        *,
        reviewer: str = "aegis",
        status: str = APPROVED,
        notes: str = "",
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Record a quality review for a governed job."""
        jid = str(job_id or "").strip()
        if not jid:
            raise MissionGateError("job_id required", code="job_id_required")
        if self.store.get(jid) is None:
            raise MissionGateError(f"job not found: {jid}", code="job_not_found")
        st = str(status or "").strip().lower()
        if st not in REVIEW_STATUSES:
            raise MissionGateError(
                f"invalid review status: {status!r} "
                f"(need one of {sorted(REVIEW_STATUSES)})",
                code="invalid_review_status",
            )
        rid = f"qr-{uuid.uuid4().hex[:12]}"
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO quality_reviews(
              id, job_id, reviewer, status, notes, created_at, meta
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                jid,
                str(reviewer or "aegis").strip() or "aegis",
                st,
                str(notes or "")[:4000],
                now,
                _json_dumps(meta or {}),
            ),
        )
        # Pause board when rejected / needs_work (mission-control blocked lane).
        if st in ("rejected", "needs_work"):
            try:
                self.store.set_status(jid, "blocked", force=False)
            except OpsError:
                pass
        self.conn.commit()
        return self.get_review(rid)  # type: ignore[return-value]

    def get_review(self, review_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM quality_reviews WHERE id = ?",
            (str(review_id),),
        ).fetchone()
        if row is None:
            return None
        return self._review_dict(row)

    def latest_review(self, job_id: str) -> Optional[dict[str, Any]]:
        jid = str(job_id or "").strip()
        row = self.conn.execute(
            """
            SELECT * FROM quality_reviews
            WHERE job_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (jid,),
        ).fetchone()
        if row is None:
            return None
        return self._review_dict(row)

    def list_reviews(
        self,
        job_id: Optional[str] = None,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit or 20), 200))
        if job_id:
            rows = self.conn.execute(
                """
                SELECT * FROM quality_reviews
                WHERE job_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (str(job_id), lim),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM quality_reviews ORDER BY created_at DESC LIMIT ?",
                (lim,),
            ).fetchall()
        return [self._review_dict(r) for r in rows]

    def _review_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "reviewer": row["reviewer"],
            "status": row["status"],
            "notes": row["notes"],
            "created_at": float(row["created_at"] or 0),
            "meta": _json_loads(row["meta"]),
            "schema": SCHEMA,
        }

    # -- spend hard-cap ----------------------------------------------------

    def check_spend(
        self,
        job_id: str,
        *,
        additional_tokens: int = 0,
    ) -> dict[str, Any]:
        """Return spend vs max_tokens policy (ok when under cap or no cap)."""
        jid = str(job_id or "").strip()
        job = self.store.get(jid)
        if job is None:
            raise MissionGateError(f"job not found: {jid}", code="job_not_found")
        policy = self._policy(job)
        used = int(job.get("tokens") or 0)
        add = max(0, int(additional_tokens or 0))
        projected = used + add
        max_tok = policy.get("max_tokens")
        if max_tok is None:
            return {
                "ok": True,
                "job_id": jid,
                "tokens_used": used,
                "additional": add,
                "projected": projected,
                "max_tokens": None,
                "remaining": None,
                "capped": False,
            }
        cap = max(0, int(max_tok))
        remaining = max(0, cap - used)
        ok = projected <= cap
        return {
            "ok": ok,
            "job_id": jid,
            "tokens_used": used,
            "additional": add,
            "projected": projected,
            "max_tokens": cap,
            "remaining": remaining,
            "capped": True,
            "code": None if ok else "spend_cap_exceeded",
        }

    def gated_record_spend(
        self,
        job_id: str,
        tokens: int,
        *,
        source: str = "",
        label: str = "",
        cost: Optional[float] = None,
        meta: Optional[dict[str, Any]] = None,
        dual_write_usage: bool = False,
        kind: str = "task",
        force: bool = False,
    ) -> dict[str, Any]:
        """Attribute spend; fail-closed when projected tokens exceed max_tokens."""
        jid = str(job_id or "").strip()
        tok = max(0, int(tokens))
        chk = self.check_spend(jid, additional_tokens=tok)
        if not chk["ok"] and not force:
            raise MissionGateError(
                f"spend cap exceeded for {jid}: "
                f"projected={chk['projected']} max={chk['max_tokens']}",
                code="spend_cap_exceeded",
            )
        rec = self.store.record_spend(
            jid,
            tok,
            source=source,
            label=label,
            cost=cost,
            meta=meta,
            dual_write_usage=dual_write_usage,
            ensure=True,
            kind=kind,
        )
        return {
            "schema": SCHEMA,
            "spend": rec,
            "cap_check": chk,
            "ok": True,
        }

    # -- complete gate + receipt -------------------------------------------

    def check_complete(self, job_id: str) -> dict[str, Any]:
        """Validate whether a job may complete under mission-gate policy."""
        jid = str(job_id or "").strip()
        job = self.store.get(jid)
        if job is None:
            return {
                "ok": False,
                "job_id": jid,
                "reasons": ["job_not_found"],
                "code": "job_not_found",
            }
        policy = self._policy(job)
        reasons: list[str] = []
        enabled = bool(policy.get("enabled"))
        require_review = bool(policy.get("require_review", False)) if enabled else False
        require_receipt = bool(policy.get("require_receipt", False)) if enabled else False

        review = self.latest_review(jid)
        review_ok = True
        if require_review:
            if review is None:
                review_ok = False
                reasons.append("missing_quality_review")
            elif str(review.get("status") or "") != APPROVED:
                review_ok = False
                reasons.append(f"review_not_approved:{review.get('status')}")

        spend_chk = self.check_spend(jid, additional_tokens=0)
        spend_ok = bool(spend_chk.get("ok"))
        if not spend_ok:
            reasons.append("spend_cap_exceeded")

        cur_status = str(job.get("status") or "")
        already_terminal = cur_status in TERMINAL_JOB_STATUSES

        ok = review_ok and spend_ok
        return {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "ok": ok,
            "job_id": jid,
            "job_status": cur_status,
            "already_terminal": already_terminal,
            "enabled": enabled,
            "require_review": require_review,
            "require_receipt": require_receipt,
            "latest_review": review,
            "spend": spend_chk,
            "reasons": reasons,
            "code": None if ok else (reasons[0] if reasons else "not_ready"),
            "policy": policy,
        }

    def complete(
        self,
        job_id: str,
        *,
        force: bool = False,
        status: str = "completed",
        notes: str = "",
        issue_receipt: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Fail-closed complete with optional quality review + receipt.

        When *force* is True, skips review/spend gates (operator override).
        Terminal sticky still applies unless force path uses set_status(force=).
        """
        jid = str(job_id or "").strip()
        if not jid:
            raise MissionGateError("job_id required", code="job_id_required")
        chk = self.check_complete(jid)
        if not chk["ok"] and not force:
            raise MissionGateError(
                f"cannot complete {jid}: {','.join(chk.get('reasons') or ['not_ready'])}",
                code=str(chk.get("code") or "not_ready"),
            )
        st = str(status or "completed").strip().lower()
        if st not in ("completed", "failed", "cancelled"):
            raise MissionGateError(
                f"complete status must be terminal, got {status!r}",
                code="invalid_status",
            )
        job = self.store.set_status(jid, st, force=force)
        policy = self._policy(job or {})
        want_receipt = (
            bool(issue_receipt)
            if issue_receipt is not None
            else bool(policy.get("require_receipt", DEFAULT_REQUIRE_RECEIPT))
        )
        # Always issue when require_receipt; also when explicitly requested.
        if issue_receipt is None and not policy.get("enabled"):
            want_receipt = True  # default: emit receipt on gated complete path

        receipt_row: Optional[dict[str, Any]] = None
        if want_receipt:
            receipt_row = self.issue_completion_receipt(
                jid,
                status=st,
                notes=notes,
                review=chk.get("latest_review"),
            )

        return {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "ok": True,
            "job_id": jid,
            "job": job,
            "check": chk,
            "forced": bool(force),
            "receipt": receipt_row,
        }

    def issue_completion_receipt(
        self,
        job_id: str,
        *,
        status: str = "completed",
        notes: str = "",
        review: Optional[dict[str, Any]] = None,
        secret: Optional[str] = None,
    ) -> dict[str, Any]:
        """Sign and persist a completion receipt for *job_id*."""
        jid = str(job_id or "").strip()
        job = self.store.get(jid)
        if job is None:
            raise MissionGateError(f"job not found: {jid}", code="job_not_found")
        rev = review if review is not None else self.latest_review(jid)
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "kind": "completion_receipt",
            "job_id": jid,
            "title": job.get("title"),
            "status": status,
            "tokens": int(job.get("tokens") or 0),
            "cost": float(job.get("cost") or 0.0),
            "kind_job": job.get("kind"),
            "review_id": (rev or {}).get("id"),
            "review_status": (rev or {}).get("status"),
            "reviewer": (rev or {}).get("reviewer"),
            "notes": str(notes or "")[:2000],
            "issued_at": time.time(),
            "source_pattern": SOURCE_PATTERN,
        }
        sec = secret if secret is not None else self.get_or_create_secret()
        signed = sign_receipt(payload, secret=sec)
        rid = f"rcpt-{uuid.uuid4().hex[:12]}"
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO completion_receipts(
              id, job_id, payload_hash, signature, alg, key_id, payload, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                jid,
                signed["payload_hash"],
                signed["signature"],
                signed["alg"],
                signed["key_id"],
                _json_dumps(payload),
                now,
            ),
        )
        self.conn.commit()
        return {
            "id": rid,
            "job_id": jid,
            "created_at": now,
            "payload": payload,
            "receipt": signed,
            "schema": SCHEMA,
        }

    def latest_receipt(self, job_id: str) -> Optional[dict[str, Any]]:
        jid = str(job_id or "").strip()
        row = self.conn.execute(
            """
            SELECT * FROM completion_receipts
            WHERE job_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (jid,),
        ).fetchone()
        if row is None:
            return None
        return self._receipt_dict(row)

    def verify_stored_receipt(
        self,
        receipt_id: Optional[str] = None,
        *,
        job_id: Optional[str] = None,
        secret: Optional[str] = None,
    ) -> dict[str, Any]:
        """Verify a stored receipt against its payload + HMAC secret."""
        row = None
        if receipt_id:
            row = self.conn.execute(
                "SELECT * FROM completion_receipts WHERE id = ?",
                (str(receipt_id),),
            ).fetchone()
        elif job_id:
            row = self.conn.execute(
                """
                SELECT * FROM completion_receipts
                WHERE job_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (str(job_id),),
            ).fetchone()
        if row is None:
            return {"ok": False, "code": "receipt_not_found"}
        payload = _json_loads(row["payload"])
        receipt = {
            "payload_hash": row["payload_hash"],
            "signature": row["signature"],
            "alg": row["alg"],
            "key_id": row["key_id"],
        }
        sec = secret if secret is not None else self.get_or_create_secret()
        ok = verify_receipt(payload, receipt, secret=sec)
        return {
            "ok": ok,
            "receipt_id": row["id"],
            "job_id": row["job_id"],
            "payload_hash": row["payload_hash"],
            "code": None if ok else "verify_failed",
            "schema": SCHEMA,
        }

    def _receipt_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "payload_hash": row["payload_hash"],
            "signature": row["signature"],
            "alg": row["alg"],
            "key_id": row["key_id"],
            "payload": _json_loads(row["payload"]),
            "created_at": float(row["created_at"] or 0),
            "schema": SCHEMA,
        }

    def summary(self, job_id: Optional[str] = None) -> dict[str, Any]:
        """Compact operator board: policy + latest review + receipt + spend."""
        if job_id:
            jid = str(job_id)
            job = self.store.get(jid)
            return {
                "schema": SCHEMA,
                "source_pattern": SOURCE_PATTERN,
                "job": job,
                "policy": self._policy(job or {}) if job else {},
                "latest_review": self.latest_review(jid) if job else None,
                "latest_receipt": self.latest_receipt(jid) if job else None,
                "check_complete": self.check_complete(jid) if job else None,
            }
        n_reviews = self.conn.execute(
            "SELECT COUNT(*) AS n FROM quality_reviews"
        ).fetchone()
        n_receipts = self.conn.execute(
            "SELECT COUNT(*) AS n FROM completion_receipts"
        ).fetchone()
        return {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "ops": self.store.summary(),
            "n_reviews": int((n_reviews["n"] if n_reviews else 0) or 0),
            "n_receipts": int((n_receipts["n"] if n_receipts else 0) or 0),
        }


# ---------------------------------------------------------------------------
# Functional helpers (soft hooks for planners / orchestrators)
# ---------------------------------------------------------------------------


def enable_mission_gate(
    workdir: Optional[Path | str],
    job_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    with MissionGate.open(workdir) as gate:
        return gate.enable_gate(job_id, **kwargs)


def complete_with_gate(
    workdir: Optional[Path | str],
    job_id: str,
    *,
    force: bool = False,
    status: str = "completed",
    notes: str = "",
) -> dict[str, Any]:
    with MissionGate.open(workdir) as gate:
        return gate.complete(job_id, force=force, status=status, notes=notes)


# ---------------------------------------------------------------------------
# Module CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="python -m nexus.mission_gate",
        description=(
            "Mission-control quality gate + completion receipts + spend caps "
            f"({SOURCE_PATTERN})"
        ),
    )
    p.add_argument(
        "--workdir",
        default=None,
        help="project root (default: cwd / NEXUS_PROJECT_ROOT)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("enable", help="enable gate policy on a job")
    pe.add_argument("job_id")
    pe.add_argument("--max-tokens", type=int, default=None)
    pe.add_argument("--no-review", action="store_true")
    pe.add_argument("--title", default="")
    pe.add_argument("--goal", default="")
    pe.add_argument("--json", action="store_true")

    pr = sub.add_parser("review", help="record a quality review")
    pr.add_argument("job_id")
    pr.add_argument("--reviewer", default="aegis")
    pr.add_argument(
        "--status",
        default=APPROVED,
        choices=sorted(REVIEW_STATUSES),
    )
    pr.add_argument("--notes", default="")
    pr.add_argument("--json", action="store_true")

    pc = sub.add_parser("check", help="check if job may complete")
    pc.add_argument("job_id")
    pc.add_argument("--json", action="store_true")

    pd = sub.add_parser("complete", help="gated complete + receipt")
    pd.add_argument("job_id")
    pd.add_argument("--force", action="store_true")
    pd.add_argument("--notes", default="")
    pd.add_argument("--json", action="store_true")

    ps = sub.add_parser("spend", help="gated record_spend (hard cap)")
    ps.add_argument("job_id")
    ps.add_argument("tokens", type=int)
    ps.add_argument("--source", default="cli")
    ps.add_argument("--label", default="")
    ps.add_argument("--force", action="store_true")
    ps.add_argument("--json", action="store_true")

    pcap = sub.add_parser("cap", help="set spend hard-cap max_tokens")
    pcap.add_argument("job_id")
    pcap.add_argument("max_tokens", type=int)
    pcap.add_argument("--json", action="store_true")

    pv = sub.add_parser("verify", help="verify latest stored receipt")
    pv.add_argument("job_id")
    pv.add_argument("--json", action="store_true")

    psum = sub.add_parser("summary", help="operator board summary")
    psum.add_argument("job_id", nargs="?", default=None)
    psum.add_argument("--json", action="store_true")

    args = p.parse_args(list(argv) if argv is not None else None)
    root = _root(args.workdir)

    with MissionGate.open(root) as gate:
        if args.cmd == "enable":
            out = gate.enable_gate(
                args.job_id,
                require_review=not args.no_review,
                max_tokens=args.max_tokens,
                title=args.title,
                goal=args.goal,
            )
            if args.json:
                print(json.dumps(out, indent=2, default=str))
            else:
                pol = out.get("policy") or {}
                print(
                    f"enabled {out['job_id']} require_review={pol.get('require_review')} "
                    f"max_tokens={pol.get('max_tokens')}"
                )
            return 0

        if args.cmd == "review":
            out = gate.record_review(
                args.job_id,
                reviewer=args.reviewer,
                status=args.status,
                notes=args.notes,
            )
            if args.json:
                print(json.dumps(out, indent=2, default=str))
            else:
                print(
                    f"review {out['id']} job={out['job_id']} "
                    f"status={out['status']} by={out['reviewer']}"
                )
            return 0

        if args.cmd == "check":
            out = gate.check_complete(args.job_id)
            if args.json:
                print(json.dumps(out, indent=2, default=str))
            else:
                print(
                    f"ok={out['ok']} job={out['job_id']} "
                    f"reasons={out.get('reasons')}"
                )
            return 0 if out["ok"] else 2

        if args.cmd == "complete":
            try:
                out = gate.complete(
                    args.job_id,
                    force=bool(args.force),
                    notes=args.notes,
                )
            except MissionGateError as e:
                print(f"error: {e} ({e.code})", flush=True)
                return 2
            if args.json:
                print(json.dumps(out, indent=2, default=str))
            else:
                rcpt = out.get("receipt") or {}
                print(
                    f"completed {out['job_id']} "
                    f"receipt={rcpt.get('id')} "
                    f"hash={(rcpt.get('receipt') or {}).get('payload_hash', '')[:12]}"
                )
            return 0

        if args.cmd == "spend":
            try:
                out = gate.gated_record_spend(
                    args.job_id,
                    int(args.tokens),
                    source=args.source,
                    label=args.label,
                    force=bool(args.force),
                )
            except MissionGateError as e:
                print(f"error: {e} ({e.code})", flush=True)
                return 2
            if args.json:
                print(json.dumps(out, indent=2, default=str))
            else:
                s = out.get("spend") or {}
                print(
                    f"spend job={s.get('job_id')} tokens={s.get('tokens')} "
                    f"job_total={(s.get('job') or {}).get('tokens')}"
                )
            return 0

        if args.cmd == "cap":
            out = gate.set_spend_cap(args.job_id, int(args.max_tokens))
            if args.json:
                print(json.dumps(out, indent=2, default=str))
            else:
                print(f"cap {out['job_id']} max_tokens={out['max_tokens']}")
            return 0

        if args.cmd == "verify":
            out = gate.verify_stored_receipt(job_id=args.job_id)
            if args.json:
                print(json.dumps(out, indent=2, default=str))
            else:
                print(
                    f"verify ok={out['ok']} job={out.get('job_id')} "
                    f"receipt={out.get('receipt_id')}"
                )
            return 0 if out.get("ok") else 2

        if args.cmd == "summary":
            out = gate.summary(args.job_id)
            if args.json:
                print(json.dumps(out, indent=2, default=str))
            else:
                print(json.dumps(out, indent=2, default=str))
            return 0

    p.error(f"unknown cmd {args.cmd}")
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    return _cli(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "SCHEMA",
    "SOURCE_PATTERN",
    "SOURCE_URL",
    "META_KEY",
    "REVIEW_STATUSES",
    "APPROVED",
    "MissionGateError",
    "MissionGate",
    "canonicalize",
    "payload_hash",
    "sign_receipt",
    "verify_receipt",
    "enable_mission_gate",
    "complete_with_gate",
    "main",
]
