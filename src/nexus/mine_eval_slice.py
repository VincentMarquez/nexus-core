"""First apply slice — prove mine→grade→claim→ledger→worktree dry-run (plan §5).

Offline loop matching ``docs/LATEST_IMPROVE_PLAN.md`` First apply slice:

  research/mine artifact → Grok-shaped grade → claim verify → durable ledger
  → APPLY_CANDIDATE worktree dry-run (plan-reuse cache)

Stages (AOAD-MAT / arXiv 2510.13343)::

  MINED → GRADED → CLAIM_OK → APPLY_CANDIDATE

Patterns (shape only, not vendored trees):
- choihyunsus/soul — immutable append-only ledger
- ahmedEid1/lumen — migration guards + decision audit
- wshobson/agents — generate/validate/smoke adapter shape
- codingagentsystem/cas / forge — worktree isolation dry-run
- Thucy (2512.03278) — claim verification against grade + tests
- CEMA (2302.10809) — causal_note on grade rows
- multi-stage plan reuse (2604.03350 / context eng 2508.08322)

Storage::

  ``.nexus_workspaces/mine_eval/slice/grades.sqlite``
  ``.nexus_workspaces/plan_reuse/cache.json``

No network in unit tests; precomputed grades from fixtures / IMPROVE_OURS.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

SCHEMA = "nexus.mine_eval_slice/v1"
DEFAULT_METHOD = "grok:grok-4.5"
DEFAULT_MIN_SCORE = 14.0
DB_NAME = "grades.sqlite"
SLICE_REL = Path(".nexus_workspaces") / "mine_eval" / "slice"

# Plan §5 action-order enum (illegal transitions raise).
SLICE_STAGES: tuple[str, ...] = (
    "mined",
    "graded",
    "claim_ok",
    "apply_candidate",
)

# Human-readable aliases used in docs/tests.
STAGE_ALIASES: dict[str, str] = {
    "MINED": "mined",
    "GRADED": "graded",
    "CLAIM_OK": "claim_ok",
    "APPLY_CANDIDATE": "apply_candidate",
}


class SliceError(RuntimeError):
    """Base error for the first-apply slice."""


class StageOrderError(SliceError):
    """Illegal stage transition (1301.6431-style invariant)."""


class MigrationError(SliceError):
    """Schema migration refused or failed (lumen-style guard)."""


class ImmutableError(SliceError):
    """Attempt to mutate an append-only grade row."""


# ---------------------------------------------------------------------------
# Paths / migration
# ---------------------------------------------------------------------------


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def slice_dir(workdir: Optional[Path | str] = None) -> Path:
    d = _root(workdir) / SLICE_REL
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path(workdir: Optional[Path | str] = None) -> Path:
    return slice_dir(workdir) / DB_NAME


def normalize_stage(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        raise StageOrderError("stage name required")
    if raw in STAGE_ALIASES:
        return STAGE_ALIASES[raw]
    key = raw.lower()
    if key in SLICE_STAGES:
        return key
    raise StageOrderError(
        f"unknown stage {name!r}; known={list(SLICE_STAGES)} "
        f"(or {[k for k in STAGE_ALIASES]})"
    )


def can_transition(current: Optional[str], nxt: str) -> bool:
    """True when *nxt* is the next stage after *current* (or first when None)."""
    target = normalize_stage(nxt)
    if current is None or str(current).strip() == "":
        return target == SLICE_STAGES[0]
    cur = normalize_stage(current)
    try:
        i = SLICE_STAGES.index(cur)
    except ValueError:
        return False
    if i + 1 >= len(SLICE_STAGES):
        return False
    return SLICE_STAGES[i + 1] == target


def assert_transition(current: Optional[str], nxt: str) -> str:
    """Raise StageOrderError on illegal transition; return normalized next."""
    target = normalize_stage(nxt)
    if not can_transition(current, target):
        cur_s = "(start)" if current is None or str(current).strip() == "" else current
        raise StageOrderError(
            f"illegal transition {cur_s} → {target}; "
            f"order={' → '.join(s.upper() for s in SLICE_STAGES)}"
        )
    return target


def migrate(workdir: Optional[Path | str] = None, *, force: bool = False) -> dict[str, Any]:
    """Create schema once. Second call is a no-op (lumen migration guard).

    Returns ``{ok, already_migrated, path, schema}``.
    """
    root = _root(workdir)
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = cur.execute(
            "SELECT value FROM meta WHERE key = ?", ("schema_version",)
        ).fetchone()
        if row is not None and not force:
            return {
                "ok": True,
                "already_migrated": True,
                "path": str(path),
                "schema": row[0],
                "guard": "refuse_double_migrate",
            }
        if row is not None and force:
            # force re-apply DDL only (tables IF NOT EXISTS); meta stays
            pass

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS grades (
              id TEXT PRIMARY KEY,
              repo_or_paper_id TEXT NOT NULL,
              score REAL NOT NULL,
              idea REAL NOT NULL,
              skill REAL NOT NULL,
              method TEXT NOT NULL DEFAULT 'grok:grok-4.5',
              causal_note TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              artifact_path TEXT NOT NULL DEFAULT '',
              stage TEXT NOT NULL DEFAULT 'graded',
              run_id TEXT NOT NULL DEFAULT '',
              content_hash TEXT NOT NULL UNIQUE
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_slice_grades_score "
            "ON grades(score DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_slice_grades_repo "
            "ON grades(repo_or_paper_id)"
        )
        # Append-only triggers
        cur.execute("DROP TRIGGER IF EXISTS slice_grades_no_update")
        cur.execute("DROP TRIGGER IF EXISTS slice_grades_no_delete")
        cur.execute(
            """
            CREATE TRIGGER slice_grades_no_update BEFORE UPDATE ON grades
            BEGIN
              SELECT RAISE(ABORT, 'slice grades are append-only; UPDATE forbidden');
            END
            """
        )
        cur.execute(
            """
            CREATE TRIGGER slice_grades_no_delete BEFORE DELETE ON grades
            BEGIN
              SELECT RAISE(ABORT, 'slice grades are append-only; DELETE forbidden');
            END
            """
        )
        if row is None:
            cur.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?)",
                ("schema_version", SCHEMA),
            )
            cur.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                ("migrated_at", str(time.time())),
            )
        conn.commit()
        return {
            "ok": True,
            "already_migrated": row is not None,
            "path": str(path),
            "schema": SCHEMA,
            "guard": "refuse_double_migrate",
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Claim verifier (Thucy-style)
# ---------------------------------------------------------------------------


@dataclass
class ClaimResult:
    """Plan §5 claim gate output: ok + reasons[] (no network)."""

    ok: bool
    reasons: list[str] = field(default_factory=list)
    score: Optional[float] = None
    idea: Optional[float] = None
    skill: Optional[float] = None
    repo_or_paper_id: Optional[str] = None
    apply_candidate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nexus.claim_result/v1",
            "ok": self.ok,
            "reasons": list(self.reasons),
            "score": self.score,
            "idea": self.idea,
            "skill": self.skill,
            "repo_or_paper_id": self.repo_or_paper_id,
            "apply_candidate": self.apply_candidate,
        }


def _num(value: Any, field: str, reasons: list[str]) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        reasons.append(f"{field} must be numeric")
        return None


def verify_claims(
    grade: Any,
    *,
    test_exit_code: Optional[int] = 0,
    min_score: float = DEFAULT_MIN_SCORE,
    require_tests_ok: bool = True,
) -> ClaimResult:
    """Verify grade + optional test exit for apply candidacy.

    Pass when score ≥ *min_score* and (if require_tests_ok) test_exit_code == 0.
    """
    reasons: list[str] = []
    if not isinstance(grade, dict):
        return ClaimResult(ok=False, reasons=["grade must be a dict"])

    rid = str(
        grade.get("repo_or_paper_id")
        or grade.get("repo")
        or grade.get("arxiv_id")
        or ""
    ).strip()
    if not rid:
        reasons.append("repo_or_paper_id/repo missing")

    score = _num(grade.get("score"), "score", reasons)
    idea = _num(grade.get("idea"), "idea", reasons)
    skill = _num(grade.get("skill"), "skill", reasons)

    if score is not None and score < float(min_score):
        reasons.append(f"score {score} below min_score {min_score}")

    tests_ok = True
    if require_tests_ok:
        if test_exit_code is None:
            reasons.append("test_exit_code required for apply candidacy")
            tests_ok = False
        elif int(test_exit_code) != 0:
            reasons.append(f"tests not ok (exit_code={test_exit_code})")
            tests_ok = False

    ok = not reasons
    apply_candidate = bool(
        ok
        and score is not None
        and score >= float(min_score)
        and tests_ok
    )
    return ClaimResult(
        ok=ok,
        reasons=reasons,
        score=score,
        idea=idea,
        skill=skill,
        repo_or_paper_id=rid or None,
        apply_candidate=apply_candidate,
    )


def classify_apply_candidates(
    grades: Sequence[dict[str, Any]],
    *,
    min_score: float = DEFAULT_MIN_SCORE,
    test_exit_code: int = 0,
) -> list[dict[str, Any]]:
    """Classify a fixture set into apply_candidate yes/no (eval light)."""
    out: list[dict[str, Any]] = []
    for g in grades:
        if not isinstance(g, dict):
            continue
        claim = verify_claims(
            g, test_exit_code=test_exit_code, min_score=min_score
        )
        rid = claim.repo_or_paper_id or str(g.get("repo") or "?")
        out.append(
            {
                "repo_or_paper_id": rid,
                "score": claim.score,
                "apply_candidate": claim.apply_candidate,
                "ok": claim.ok,
                "reasons": list(claim.reasons),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Append-only ledger
# ---------------------------------------------------------------------------


def _content_hash(
    *,
    repo_or_paper_id: str,
    score: float,
    idea: float,
    skill: float,
    method: str,
    artifact_path: str,
    causal_note: str,
) -> str:
    import hashlib

    payload = {
        "repo_or_paper_id": repo_or_paper_id,
        "score": float(score),
        "idea": float(idea),
        "skill": float(skill),
        "method": method,
        "artifact_path": artifact_path,
        "causal_note": causal_note,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def causal_note_for(grade: dict[str, Any]) -> str:
    """CEMA-style why-this-grade one-liner (2302.10809)."""
    if grade.get("causal_note"):
        return str(grade["causal_note"])[:500]
    repo = str(grade.get("repo") or grade.get("repo_or_paper_id") or "?")
    score = grade.get("score")
    idea = grade.get("idea")
    skill = grade.get("skill")
    pattern = str(grade.get("pattern") or grade.get("summary") or "").strip()
    note = f"score={score} because idea={idea}+skill={skill} for {repo}"
    if pattern:
        snippet = pattern.replace("\n", " ")[:120]
        note += f" ({snippet})"
    return note


@dataclass
class SliceLedger:
    """Append-only grade ledger for the first-apply slice."""

    workdir: Path
    conn: sqlite3.Connection

    @classmethod
    def open(cls, workdir: Optional[Path | str] = None) -> "SliceLedger":
        root = _root(workdir)
        mig = migrate(root)
        if not mig.get("ok"):
            raise MigrationError(f"migrate failed: {mig}")
        path = db_path(root)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return cls(workdir=root, conn=conn)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> "SliceLedger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "repo_or_paper_id": row["repo_or_paper_id"],
            "score": float(row["score"]),
            "idea": float(row["idea"]),
            "skill": float(row["skill"]),
            "method": row["method"],
            "causal_note": row["causal_note"] or "",
            "created_at": float(row["created_at"]),
            "artifact_path": row["artifact_path"] or "",
            "stage": row["stage"] or "graded",
            "run_id": row["run_id"] or "",
            "content_hash": row["content_hash"],
        }

    def append(
        self,
        *,
        repo_or_paper_id: str,
        score: float,
        idea: float,
        skill: float,
        method: str = DEFAULT_METHOD,
        causal_note: str = "",
        artifact_path: str = "",
        stage: str = "graded",
        run_id: str = "",
        grade_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        """Append a grade. Same content_hash returns first row (immutability)."""
        rid = str(repo_or_paper_id or "").strip()
        if not rid:
            raise SliceError("repo_or_paper_id required")
        meth = str(method or DEFAULT_METHOD).strip() or DEFAULT_METHOD
        sc, ide, sk = float(score), float(idea), float(skill)
        note = str(causal_note or "")[:500]
        path = str(artifact_path or "")
        st = normalize_stage(stage) if stage else "graded"
        ch = _content_hash(
            repo_or_paper_id=rid,
            score=sc,
            idea=ide,
            skill=sk,
            method=meth,
            artifact_path=path,
            causal_note=note,
        )
        existing = self.conn.execute(
            "SELECT * FROM grades WHERE content_hash = ?", (ch,)
        ).fetchone()
        if existing is not None:
            return self._row(existing)

        gid = str(grade_id or f"sg-{uuid.uuid4().hex[:12]}")
        ts = float(created_at if created_at is not None else time.time())
        try:
            self.conn.execute(
                """
                INSERT INTO grades(
                  id, repo_or_paper_id, score, idea, skill, method,
                  causal_note, created_at, artifact_path, stage, run_id,
                  content_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    gid,
                    rid,
                    sc,
                    ide,
                    sk,
                    meth,
                    note,
                    ts,
                    path,
                    st,
                    str(run_id or ""),
                    ch,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            existing = self.conn.execute(
                "SELECT * FROM grades WHERE content_hash = ?", (ch,)
            ).fetchone()
            if existing is not None:
                return self._row(existing)
            raise ImmutableError(f"append conflict for {rid}") from None

        row = self.conn.execute(
            "SELECT * FROM grades WHERE id = ?", (gid,)
        ).fetchone()
        if row is None:
            raise SliceError("append failed to persist")
        return self._row(row)

    def append_from_grade(
        self,
        grade: dict[str, Any],
        *,
        run_id: str = "",
        stage: str = "graded",
    ) -> dict[str, Any]:
        rid = str(
            grade.get("repo_or_paper_id")
            or grade.get("repo")
            or grade.get("arxiv_id")
            or ""
        )
        idea = float(grade.get("idea") if grade.get("idea") is not None else 0)
        skill = float(grade.get("skill") if grade.get("skill") is not None else 0)
        score = grade.get("score")
        if score is None:
            score = idea + skill
        return self.append(
            repo_or_paper_id=rid,
            score=float(score),
            idea=idea,
            skill=skill,
            method=str(grade.get("method") or DEFAULT_METHOD),
            causal_note=causal_note_for(grade),
            artifact_path=str(
                grade.get("artifact_path")
                or grade.get("path")
                or grade.get("local_path")
                or ""
            ),
            stage=stage,
            run_id=run_id,
        )

    def get(self, grade_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM grades WHERE id = ?", (str(grade_id),)
        ).fetchone()
        return self._row(row) if row else None

    def list(
        self,
        *,
        run_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if run_id:
            rows = self.conn.execute(
                "SELECT * FROM grades WHERE run_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (str(run_id), int(limit)),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM grades ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [self._row(r) for r in rows]

    def count(self, *, run_id: Optional[str] = None) -> int:
        if run_id:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM grades WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM grades").fetchone()
        return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Action-order runner
# ---------------------------------------------------------------------------


@dataclass
class SliceRunner:
    """Enforces MINED → GRADED → CLAIM_OK → APPLY_CANDIDATE."""

    completed: list[str] = field(default_factory=list)

    def current(self) -> Optional[str]:
        return self.completed[-1] if self.completed else None

    def next(self) -> Optional[str]:
        if not self.completed:
            return SLICE_STAGES[0]
        cur = self.completed[-1]
        try:
            i = SLICE_STAGES.index(cur)
        except ValueError:
            return None
        if i + 1 >= len(SLICE_STAGES):
            return None
        return SLICE_STAGES[i + 1]

    def advance(self, stage: str) -> list[str]:
        target = normalize_stage(stage)
        if target in self.completed:
            return list(self.completed)
        assert_transition(self.current(), target)
        self.completed.append(target)
        return list(self.completed)

    def is_done(self) -> bool:
        return self.next() is None and len(self.completed) == len(SLICE_STAGES)

    def status(self) -> dict[str, Any]:
        return {
            "schema": "nexus.slice_stages/v1",
            "stages": list(SLICE_STAGES),
            "completed": list(self.completed),
            "current": self.current(),
            "next": self.next(),
            "done": self.is_done(),
        }


# ---------------------------------------------------------------------------
# Smoke + demo
# ---------------------------------------------------------------------------


def _repo_key(name: Any) -> str:
    return str(name or "").strip().lower().replace("__", "/")


def _grades_from_json_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [g for g in data if isinstance(g, dict)]
    if isinstance(data, dict):
        raw = data.get("grades") or data.get("items") or data.get("candidates") or []
        if isinstance(raw, list) and raw:
            return [g for g in raw if isinstance(g, dict)]
        if data.get("repo") or data.get("score") is not None:
            return [data]
    return []


def _find_grade_in_list(
    grades: Sequence[dict[str, Any]],
    want: str,
    *,
    source: str = "",
) -> Optional[dict[str, Any]]:
    want_key = _repo_key(want)
    if not want_key:
        return None
    for g in grades:
        rid = _repo_key(g.get("repo") or g.get("repo_or_paper_id"))
        if rid == want_key:
            out = dict(g)
            if source:
                out["_fixture"] = source
            return out
    return None


def _grade_from_improve_ours(
    workdir: Path,
    repo: str,
) -> Optional[dict[str, Any]]:
    """Offline grade from IMPROVE_OURS / grade cache (no silent wrong-repo)."""
    try:
        from .grade_artifact import get_grade
    except Exception:
        return None
    g = get_grade(workdir, repo, min_score=0.0)
    if not isinstance(g, dict):
        return None
    out = dict(g)
    # Normalize to mine_eval_slice shape
    out.setdefault("repo", out.get("repo") or repo)
    out.setdefault("repo_or_paper_id", out.get("repo"))
    out.setdefault(
        "path",
        out.get("path")
        or out.get("local_path")
        or f".nexus_workspaces/mine_eval/{_repo_key(repo).replace('/', '__')}",
    )
    out["_fixture"] = "improve_ours"
    return out


def load_fixture_grade(
    workdir: Optional[Path | str] = None,
    *,
    fixture: Optional[Path | str] = None,
    repo: Optional[str] = None,
) -> dict[str, Any]:
    """Load one precomputed grade (offline; no network).

    Search order when *fixture* is unset:
      1. ``tests/fixtures/mine_eval_sample.json``
      2. ``fixtures/mine_eval/grades_with_claims.json``
      3. IMPROVE_OURS / grade cache (named *repo* only)

    When *repo* is set, never silently return a different repo — raise
    :class:`SliceError` if no match is found (mission-control / solace
    plan-slice must not fall back to wshobson).
    """
    root = _root(workdir)
    want = (repo or "").strip()
    default_repo = "wshobson/agents"

    paths: list[Path] = []
    if fixture:
        path = Path(fixture)
        if not path.is_absolute():
            path = (root / path).resolve()
        paths.append(path)
    else:
        for candidate in (
            root / "tests" / "fixtures" / "mine_eval_sample.json",
            root / "fixtures" / "mine_eval" / "grades_with_claims.json",
        ):
            if candidate.is_file():
                paths.append(candidate)

    if not paths:
        # Named repo can still come from IMPROVE_OURS without JSON fixtures.
        if want:
            from_ours = _grade_from_improve_ours(root, want)
            if from_ours is not None:
                return from_ours
        raise SliceError(
            "no grade fixture found; pass fixture= or add "
            "tests/fixtures/mine_eval_sample.json"
        )

    # Collect grades from all candidate fixtures (first file wins on collision).
    seen_repos: set[str] = set()
    all_grades: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise SliceError(f"cannot read grade fixture {path}: {e}") from e
        for g in _grades_from_json_payload(data):
            rid = _repo_key(g.get("repo") or g.get("repo_or_paper_id"))
            if not rid or rid in seen_repos:
                continue
            seen_repos.add(rid)
            all_grades.append((path, g))

    if not all_grades and not want:
        raise SliceError(f"no grades in fixture {paths[0]}")

    # Explicit repo: match across all fixtures, then IMPROVE_OURS — no wrong-repo fallback.
    if want:
        hit = _find_grade_in_list(
            [g for _, g in all_grades],
            want,
        )
        if hit is not None:
            # attach source path if we know it
            for path, g in all_grades:
                if _repo_key(g.get("repo") or g.get("repo_or_paper_id")) == _repo_key(want):
                    hit = dict(g)
                    hit["_fixture"] = str(path)
                    return hit
            hit["_fixture"] = str(paths[0])
            return hit
        from_ours = _grade_from_improve_ours(root, want)
        if from_ours is not None:
            return from_ours
        known = sorted(seen_repos) or ["(none)"]
        raise SliceError(
            f"repo {want!r} not found in grade fixtures or IMPROVE_OURS; "
            f"known={known}"
        )

    # No repo: prefer wshobson (canonical demo), else first grade.
    prefer = _find_grade_in_list(
        [g for _, g in all_grades],
        default_repo,
    )
    if prefer is not None:
        for path, g in all_grades:
            if _repo_key(g.get("repo") or g.get("repo_or_paper_id")) == _repo_key(default_repo):
                out = dict(g)
                out["_fixture"] = str(path)
                return out
        prefer["_fixture"] = str(paths[0])
        return prefer

    if not all_grades:
        raise SliceError(f"no grades in fixture {paths[0]}")
    path0, g0 = all_grades[0]
    out = dict(g0)
    out["_fixture"] = str(path0)
    return out


def format_kanban(status: dict[str, Any]) -> str:
    """Routa-lite one-line board status."""
    g = status.get("grade") or {}
    claim = status.get("claim") or {}
    stages = status.get("stage_status") or {}
    rid = g.get("repo_or_paper_id") or g.get("repo") or "?"
    score = g.get("score")
    cand = "YES" if status.get("apply_candidate") else "NO"
    done = "→".join(
        s.upper() for s in (stages.get("completed") or status.get("completed") or [])
    ) or "(none)"
    note = (g.get("causal_note") or claim.get("causal_note") or "")[:80]
    wt = status.get("worktree_apply") or {}
    cache = "hit" if wt.get("cache_hit") else ("miss" if wt else "-")
    wt_ok = wt.get("ok")
    return (
        f"[slice] {rid}  score={score}  apply_candidate={cand}  "
        f"wt={wt_ok} cache={cache}  stages={done}  causal={note!r}"
    )


# Repo → worktree pattern catalog id (first match wins).
_REPO_PATTERN_HINTS: tuple[tuple[str, str], ...] = (
    ("wshobson/agents", "markdown-skill-sot-validator"),
    ("codingagentsystem/cas", "cas-evidence-board-ops"),
    ("builderz-labs/mission-control", "mission-control-spend-ops"),
    ("choihyunsus/soul", "soul-work-ledger-ops"),
    ("labsai/eddi", "eddi-routing-ops"),
    ("wheattoast11/openrouter", "openrouter-research-ops"),
    ("mattmagg/mistersmith", "mistersmith-runtime-ops"),
    ("solacelabs/solace", "solace-mesh-events-ops"),
    ("intelligent-internet/zenith", "zenith-principled-stop-ops"),
    ("escapeboy/agent-fleet", "agent-fleet-ops"),
)


def pattern_for_repo(repo: str, *, default: Optional[str] = None) -> str:
    """Map a mined repo name to a worktree pattern catalog id."""
    from . import worktree_apply as wta

    key = str(repo or "").strip().lower().replace("__", "/")
    for needle, pid in _REPO_PATTERN_HINTS:
        if needle in key:
            return pid
    return default or wta.DEFAULT_PATTERN


def grade_for_worktree(grade: dict[str, Any], row: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Shape a slice grade into claim_verify / worktree_apply fields."""
    base = dict(grade or {})
    if row:
        base.setdefault("repo", row.get("repo_or_paper_id") or base.get("repo"))
        base.setdefault("score", row.get("score"))
        base.setdefault("idea", row.get("idea"))
        base.setdefault("skill", row.get("skill"))
        base.setdefault("method", row.get("method"))
        path = (
            row.get("artifact_path")
            or base.get("path")
            or base.get("artifact_path")
            or ""
        )
        base["path"] = str(path) or f".nexus_workspaces/mine_eval/{str(base.get('repo') or 'unknown').replace('/', '__')}"
        base.setdefault("artifact_path", base["path"])
    else:
        path = str(
            base.get("path")
            or base.get("artifact_path")
            or base.get("local_path")
            or ""
        )
        if not path:
            rid = str(base.get("repo") or base.get("repo_or_paper_id") or "unknown")
            path = f".nexus_workspaces/mine_eval/{rid.replace('/', '__')}"
        base["path"] = path
        base.setdefault("repo", base.get("repo_or_paper_id"))
    return base


def dry_run_worktree_apply(
    workdir: Optional[Path | str],
    grade: dict[str, Any],
    *,
    run_id: Optional[str] = None,
    pattern_id: Optional[str] = None,
    use_cache: bool = True,
    force: bool = False,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Sandbox worktree apply for APPLY_CANDIDATE (dry-run, no promote).

    Uses :mod:`nexus.plan_reuse` so a second call with the same fingerprint
    skips worktree materialisation. Gates (decision / work_ledger / spine)
    are off — this stage only proves isolated pattern apply + verify.
    """
    from . import plan_reuse as pr
    from . import worktree_apply as wta

    root = _root(workdir)
    g = grade_for_worktree(grade)
    repo = str(g.get("repo") or g.get("repo_or_paper_id") or "")
    pid = pattern_id or pattern_for_repo(repo)
    method = str(g.get("method") or DEFAULT_METHOD)
    score = g.get("score")
    rid = run_id or f"slice-wt-{uuid.uuid4().hex[:10]}"

    out: dict[str, Any] = {
        "schema": "nexus.slice_worktree_dry/v1",
        "ok": False,
        "dry_run": True,
        "cache_hit": False,
        "key": pr.plan_key(repo=repo, pattern=pid, score=score, method=method),
        "repo": repo,
        "pattern": pid,
        "run_id": rid,
        "apply": None,
        "verify": None,
        "error": None,
    }

    def _compute() -> dict[str, Any]:
        return wta.run_apply(
            root,
            grade=g,
            pattern_id=pid,
            run_id=rid,
            mode="sandbox",
            cleanup=cleanup,
            skip_smoke_prefix=True,
            require_path_exists=False,
            require_decision=False,
            require_work_ledger=False,
            require_spine=False,
            promote=False,
        )

    try:
        if use_cache and not force:
            bundled = pr.get_or_compute(
                root,
                repo=repo,
                pattern=pid,
                score=score,
                method=method,
                compute=_compute,
                force=False,
            )
            out["cache_hit"] = bool(bundled.get("cache_hit"))
            out["key"] = bundled.get("key") or out["key"]
            result = bundled.get("result")
            if bundled.get("cache_hit"):
                # result is the stored summary dict
                summary = result if isinstance(result, dict) else {}
                out["ok"] = bool(summary.get("ok") or summary.get("verify_ok"))
                out["apply"] = {"files_written": summary.get("files") or []}
                out["verify"] = {"ok": summary.get("verify_ok")}
                out["cached_summary"] = summary
                out["from_cache"] = True
                return out
            # miss path: result is full run_apply report
            if not isinstance(result, dict):
                out["error"] = "worktree apply returned non-dict"
                return out
            out["ok"] = bool(result.get("ok"))
            out["apply"] = result.get("apply")
            out["verify"] = result.get("verify")
            out["worktree"] = result.get("worktree")
            out["main_untouched"] = result.get("main_untouched")
            out["error"] = result.get("error")
            out["apply_report"] = {
                "ok": result.get("ok"),
                "run_id": result.get("run_id"),
                "pattern": result.get("pattern"),
                "completed": result.get("completed"),
            }
            return out

        # force / no-cache path
        result = _compute()
        summary = {
            "ok": result.get("ok"),
            "pattern": result.get("pattern") or pid,
            "run_id": result.get("run_id"),
            "files": (result.get("apply") or {}).get("files_written") or [],
            "verify_ok": (result.get("verify") or {}).get("ok"),
            "error": result.get("error"),
            "dry_run": True,
        }
        if use_cache:
            pr.store_plan(
                root,
                key=out["key"],
                repo=repo,
                pattern=pid,
                score=score,
                method=method,
                summary=summary,
            )
        out["ok"] = bool(result.get("ok"))
        out["apply"] = result.get("apply")
        out["verify"] = result.get("verify")
        out["worktree"] = result.get("worktree")
        out["main_untouched"] = result.get("main_untouched")
        out["error"] = result.get("error")
        out["apply_report"] = {
            "ok": result.get("ok"),
            "run_id": result.get("run_id"),
            "pattern": result.get("pattern"),
            "completed": result.get("completed"),
        }
        return out
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out


def run_demo_slice(
    workdir: Optional[Path | str] = None,
    *,
    fixture: Optional[Path | str] = None,
    repo: Optional[str] = None,
    run_id: Optional[str] = None,
    min_score: float = DEFAULT_MIN_SCORE,
    test_exit_code: int = 0,
    dry_run: bool = True,
    worktree_dry_run: bool = True,
    use_plan_cache: bool = True,
    pattern_id: Optional[str] = None,
) -> dict[str, Any]:
    """End-to-end first apply slice (offline).

    1. Load graded repo from fixture (EVIDENCE shape)
    2. Stage MINED → GRADED; persist grade with causal_note
    3. Claim-verify → CLAIM_OK
    4. APPLY_CANDIDATE → sandbox worktree dry-run (+ plan-reuse cache)
    5. Emit kanban one-liner; ok only if ledger + claims + dry apply pass
    """
    root = _root(workdir)
    rid = run_id or f"slice-{uuid.uuid4().hex[:10]}"
    runner = SliceRunner()
    timeline: list[dict[str, Any]] = []

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "ok": False,
        "run_id": rid,
        "workdir": str(root),
        "stages": list(SLICE_STAGES),
        "completed": [],
        "grade": None,
        "claim": None,
        "ledger_row": None,
        "apply_candidate": False,
        "dry_run": bool(dry_run),
        "worktree_apply": None,
        "plan_reuse": None,
        "kanban": "",
        "error": None,
        "timeline": timeline,
    }

    try:
        # MINED
        runner.advance("mined")
        grade = load_fixture_grade(root, fixture=fixture, repo=repo)
        timeline.append({"stage": "mined", "repo": grade.get("repo")})

        # GRADED + durable ledger
        runner.advance("graded")
        migrate(root)  # idempotent
        with SliceLedger.open(root) as led:
            row = led.append_from_grade(grade, run_id=rid, stage="graded")
            # Immutability proof: re-append returns same id
            row2 = led.append_from_grade(grade, run_id=rid, stage="graded")
            if row2["id"] != row["id"]:
                raise ImmutableError("re-append mutated ledger identity")
            if row2["created_at"] != row["created_at"]:
                raise ImmutableError("re-append mutated created_at")
            report["ledger_row"] = row
            report["ledger_count"] = led.count(run_id=rid)
        report["grade"] = {
            "repo": grade.get("repo"),
            "repo_or_paper_id": row["repo_or_paper_id"],
            "score": row["score"],
            "idea": row["idea"],
            "skill": row["skill"],
            "method": row["method"],
            "causal_note": row["causal_note"],
            "artifact_path": row["artifact_path"],
        }
        timeline.append(
            {
                "stage": "graded",
                "ledger_id": row["id"],
                "causal_note": row["causal_note"],
            }
        )

        # CLAIM_OK
        claim = verify_claims(
            {
                **grade,
                "repo_or_paper_id": row["repo_or_paper_id"],
                "score": row["score"],
                "idea": row["idea"],
                "skill": row["skill"],
            },
            test_exit_code=test_exit_code,
            min_score=min_score,
        )
        report["claim"] = claim.to_dict()
        if not claim.ok:
            report["error"] = "; ".join(claim.reasons) or "claim failed"
            report["completed"] = list(runner.completed)
            report["stage_status"] = runner.status()
            report["kanban"] = format_kanban(report)
            return report
        runner.advance("claim_ok")
        timeline.append({"stage": "claim_ok", "apply_candidate": claim.apply_candidate})

        # APPLY_CANDIDATE → worktree dry-run (sandbox; plan-reuse)
        if claim.apply_candidate:
            runner.advance("apply_candidate")
            report["apply_candidate"] = True
            wt_payload: dict[str, Any]
            if dry_run and worktree_dry_run:
                wt_grade = grade_for_worktree(grade, row)
                wt_payload = dry_run_worktree_apply(
                    root,
                    wt_grade,
                    run_id=f"{rid}-wt",
                    pattern_id=pattern_id,
                    use_cache=use_plan_cache,
                    force=False,
                    cleanup=True,
                )
            else:
                wt_payload = {
                    "schema": "nexus.slice_worktree_dry/v1",
                    "ok": True,
                    "dry_run": dry_run,
                    "skipped": "worktree_dry_run_disabled"
                    if dry_run
                    else "no_dry_run_flag_only",
                    "action": "flag_only",
                }
            report["worktree_apply"] = wt_payload
            report["plan_reuse"] = {
                "cache_hit": wt_payload.get("cache_hit"),
                "key": wt_payload.get("key"),
            }
            timeline.append(
                {
                    "stage": "apply_candidate",
                    "dry_run": dry_run,
                    "worktree_ok": wt_payload.get("ok"),
                    "cache_hit": wt_payload.get("cache_hit"),
                    "pattern": wt_payload.get("pattern"),
                    "action": "worktree_dry_run"
                    if dry_run and worktree_dry_run
                    else "flag_only",
                }
            )
            if dry_run and worktree_dry_run and not wt_payload.get("ok"):
                report["error"] = (
                    wt_payload.get("error")
                    or "worktree dry-run failed for APPLY_CANDIDATE"
                )
                report["completed"] = list(runner.completed)
                report["stage_status"] = runner.status()
                report["kanban"] = format_kanban(report)
                # stages complete but overall ok=False
                report["ok"] = False
                return report
        else:
            report["error"] = "claims ok but not apply_candidate (score/tests)"
            report["completed"] = list(runner.completed)
            report["stage_status"] = runner.status()
            report["kanban"] = format_kanban(report)
            return report

        report["completed"] = list(runner.completed)
        report["stage_status"] = runner.status()
        wt_ok = True
        if dry_run and worktree_dry_run:
            wt_ok = bool((report.get("worktree_apply") or {}).get("ok"))
        report["ok"] = bool(
            report["ledger_row"]
            and claim.ok
            and claim.apply_candidate
            and runner.is_done()
            and wt_ok
        )
        report["kanban"] = format_kanban(report)
        return report

    except (SliceError, StageOrderError, ImmutableError, MigrationError, OSError, ValueError) as e:
        report["error"] = f"{type(e).__name__}: {e}"
        report["completed"] = list(runner.completed)
        report["stage_status"] = runner.status()
        report["kanban"] = format_kanban(report)
        return report


def format_demo_report(report: dict[str, Any]) -> str:
    g = report.get("grade") or {}
    claim = report.get("claim") or {}
    wt = report.get("worktree_apply") or {}
    lines = [
        "=== NEXUS first apply slice (MINED→GRADED→CLAIM_OK→APPLY_CANDIDATE) ===",
        f"run_id:           {report.get('run_id')}",
        f"ok:               {report.get('ok')}",
        f"stages:           {' → '.join(s.upper() for s in (report.get('stages') or SLICE_STAGES))}",
        f"completed:        {', '.join(s.upper() for s in (report.get('completed') or [])) or '(none)'}",
        f"repo:             {g.get('repo_or_paper_id') or g.get('repo')}",
        f"score:            {g.get('score')} (idea={g.get('idea')} skill={g.get('skill')})",
        f"method:           {g.get('method')}",
        f"causal_note:      {g.get('causal_note')}",
        f"artifact_path:    {g.get('artifact_path')}",
        f"apply_candidate:  {report.get('apply_candidate')} (dry_run={report.get('dry_run')})",
        f"claim.ok:         {claim.get('ok')}",
    ]
    if claim.get("reasons"):
        lines.append(f"claim.reasons:    {claim.get('reasons')}")
    if report.get("ledger_row"):
        lines.append(f"ledger.id:        {report['ledger_row'].get('id')}")
    if wt:
        lines.append(
            f"worktree.ok:      {wt.get('ok')}  cache_hit={wt.get('cache_hit')}  "
            f"pattern={wt.get('pattern')}"
        )
        if wt.get("key"):
            lines.append(f"plan_reuse.key:   {wt.get('key')}")
        if wt.get("error"):
            lines.append(f"worktree.error:   {wt.get('error')}")
    if report.get("error"):
        lines.append(f"error:            {report['error']}")
    lines.append(f"kanban:           {report.get('kanban')}")
    lines.append(f"pass:             {'YES' if report.get('ok') else 'NO'}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        prog="nexus-mine-eval-slice",
        description="First apply slice: grade ledger + claims + ordered stages",
    )
    ap.add_argument("--path", default=".", help="project workdir")
    ap.add_argument("--fixture", default=None)
    ap.add_argument("--repo", default="wshobson/agents")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    ap.add_argument("--test-exit-code", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    report = run_demo_slice(
        args.path,
        fixture=args.fixture,
        repo=args.repo,
        run_id=args.run_id,
        min_score=float(args.min_score),
        test_exit_code=int(args.test_exit_code),
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_demo_report(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
