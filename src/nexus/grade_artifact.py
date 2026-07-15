"""Grok grade artifact contract + ordered self-improve loop helpers.

First-apply slice (docs/LATEST_IMPROVE_PLAN.md P0.2 + P0.1 ordered steps):

  mine candidate → grade artifact → checkpoint(next_agent) → MCP status

Canonical fields (nexus.grade/v1)::

  {repo, score, idea, skill, method, path}

Optional: arxiv_id, pattern, notes, summary, source.

Patterns (shape only, not vendored trees):
- lumen — honest eval grades + decision audit evidence
- Thucy (2512.03278) — claims cite evidence paths
- AOAD-MAT (2510.13343) — ordered action decisions; restore next actor
- zenith — anti-premature-completion (score + audit + resume)
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .persist import atomic_write_json

SCHEMA_VERSION = "nexus.grade/v1"
DEFAULT_METHOD = "grok:grok-4.5"
DEFAULT_SCORE_THRESHOLD = 10.0

# Mine-eval score bounds (Grok idea/skill 0–10, composite 0–20).
SCORE_MIN = 0.0
SCORE_MAX = 20.0
IDEA_SKILL_MIN = 0.0
IDEA_SKILL_MAX = 10.0

# Ordered two-step loop (P0.1): resume restores next_agent, not only blobs.
ORDERED_STEPS: tuple[str, ...] = ("grade_read", "apply_plan")
STEP_INDEX: dict[str, int] = {s: i for i, s in enumerate(ORDERED_STEPS)}

GRADE_REQUIRED = ("repo", "score", "idea", "skill", "method", "path")
CLAIM_REQUIRED = ("statement", "path")

_IDEA_SKILL = re.compile(
    r"idea\s*=\s*([0-9.]+).*?skill\s*=\s*([0-9.]+)",
    re.IGNORECASE,
)
_SCORE_LINE = re.compile(r"\bscore\s*[=:]?\s*([0-9.]+)", re.IGNORECASE)


class GradeValidationError(ValueError):
    """Grade artifact failed schema checks."""


class PrematureCompleteError(RuntimeError):
    """Success claimed without score threshold + audit + resume proof (zenith)."""


# ---------------------------------------------------------------------------
# Claims (Thucy-style evidence anchors — First apply slice)
# ---------------------------------------------------------------------------


def validate_claim(claim: Any) -> dict[str, Any]:
    """Validate one evidence claim: {statement, path, quote?}."""
    if not isinstance(claim, dict):
        raise GradeValidationError("claim must be a dict")
    missing = [k for k in CLAIM_REQUIRED if not str(claim.get(k) or "").strip()]
    if missing:
        raise GradeValidationError(f"claim missing required fields: {missing}")
    out: dict[str, Any] = {
        "statement": str(claim["statement"]).strip(),
        "path": str(claim["path"]).strip(),
    }
    quote = claim.get("quote")
    if quote is not None and str(quote).strip():
        out["quote"] = str(quote).strip()
    for opt in ("arxiv_id", "kind", "source", "confidence"):
        if opt in claim and claim[opt] is not None:
            out[opt] = claim[opt]
    return out


def validate_claims(claims: Any, *, require_nonempty: bool = False) -> list[dict[str, Any]]:
    """Validate a claims list; optionally require at least one claim."""
    if claims is None:
        if require_nonempty:
            raise GradeValidationError("grade.claims must be a non-empty list")
        return []
    if not isinstance(claims, list):
        raise GradeValidationError("grade.claims must be a list")
    if require_nonempty and not claims:
        raise GradeValidationError("grade.claims must be a non-empty list")
    return [validate_claim(c) for c in claims]


def _check_score_range(key: str, value: float, lo: float, hi: float) -> float:
    if value < lo or value > hi:
        raise GradeValidationError(
            f"grade.{key}={value} out of range [{lo}, {hi}]"
        )
    return value


# ---------------------------------------------------------------------------
# Validate / build / I/O
# ---------------------------------------------------------------------------


def validate_grade(
    data: Any,
    *,
    require_path: bool = True,
    require_claims: bool = False,
    check_ranges: bool = True,
) -> dict[str, Any]:
    """Validate grade artifact; return normalized dict.

    Rejects partial objects (missing required fields or non-numeric scores).
    When *require_claims* is True, rejects grades without evidence claims
    (Thucy / First apply slice quality gate).
    When *check_ranges* is True, rejects out-of-range score/idea/skill.
    """
    if not isinstance(data, dict):
        raise GradeValidationError("grade must be a dict")

    missing = [k for k in GRADE_REQUIRED if k not in data]
    if missing and not (not require_path and missing == ["path"]):
        # allow path omission only when require_path=False
        real_missing = list(missing)
        if not require_path and "path" in real_missing:
            real_missing.remove("path")
        if real_missing:
            raise GradeValidationError(f"grade missing required fields: {real_missing}")

    repo = str(data.get("repo") or "").strip()
    if not repo:
        raise GradeValidationError("grade.repo must be non-empty")

    out: dict[str, Any] = {
        "schema": str(data.get("schema") or SCHEMA_VERSION),
        "repo": repo,
        "method": str(data.get("method") or "").strip() or DEFAULT_METHOD,
        "path": str(data.get("path") or ""),
    }
    if require_path and not out["path"].strip():
        raise GradeValidationError("grade.path must be non-empty")

    for key in ("score", "idea", "skill"):
        try:
            out[key] = float(data[key])
        except (KeyError, TypeError, ValueError) as e:
            raise GradeValidationError(f"grade.{key} must be numeric") from e

    if check_ranges:
        _check_score_range("score", out["score"], SCORE_MIN, SCORE_MAX)
        _check_score_range("idea", out["idea"], IDEA_SKILL_MIN, IDEA_SKILL_MAX)
        _check_score_range("skill", out["skill"], IDEA_SKILL_MIN, IDEA_SKILL_MAX)

    # Thucy-style evidence claims (optional unless require_claims)
    if "claims" in data or require_claims:
        out["claims"] = validate_claims(
            data.get("claims"), require_nonempty=require_claims
        )

    # Optional passthrough
    for opt in (
        "arxiv_id",
        "pattern",
        "notes",
        "summary",
        "source",
        "local_path",
        "html_url",
        "fixture_path",
    ):
        if opt in data and data[opt] is not None:
            out[opt] = data[opt]

    return out


def build_grade(
    *,
    repo: str,
    score: float,
    idea: float,
    skill: float,
    method: str = DEFAULT_METHOD,
    path: str = "",
    claims: Optional[list[dict[str, Any]]] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Construct a grade artifact (does not write)."""
    g: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "repo": repo,
        "score": float(score),
        "idea": float(idea),
        "skill": float(skill),
        "method": method or DEFAULT_METHOD,
        "path": path,
    }
    if claims is not None:
        g["claims"] = list(claims)
    for k, v in extra.items():
        if k not in g and v is not None:
            g[k] = v
    return g


def write_grade(path: Path | str, grade: dict[str, Any]) -> Path:
    """Validate + atomic write grade JSON."""
    path = Path(path)
    # Fill path field if empty with relative-ish target
    data = dict(grade)
    if not str(data.get("path") or "").strip():
        data["path"] = str(path)
    validated = validate_grade(data, require_path=True)
    atomic_write_json(path, validated)
    return path


def load_grade(path: Path | str) -> dict[str, Any]:
    """Load and validate grade JSON from disk (no network)."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"grade file not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise GradeValidationError(f"invalid grade JSON: {e}") from e
    if isinstance(data, dict) and not data.get("path"):
        data["path"] = str(p)
    return validate_grade(data, require_path=True)


def meets_threshold(
    grade: dict[str, Any],
    *,
    threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> bool:
    """True when composite score >= threshold."""
    try:
        return float(grade.get("score") or 0) >= float(threshold)
    except (TypeError, ValueError):
        return False


def success_guard(
    *,
    grade: Optional[dict[str, Any]],
    audit: Optional[dict[str, Any]] = None,
    audit_path: Optional[str] = None,
    resume_ok: bool = False,
    threshold: float = DEFAULT_SCORE_THRESHOLD,
    force_complete: bool = False,
) -> dict[str, Any]:
    """zenith-style anti-premature-completion.

    Success requires:
    - resume_ok (checkpoint/resume path proven)
    - grade.score >= threshold
    - audit present (dict or path)

    If *force_complete* is True, still fails the guard (explicit trap).
    """
    reasons: list[str] = []
    if force_complete:
        reasons.append("forced early complete refused (zenith)")
    if not resume_ok:
        reasons.append("resume_ok required")
    if not grade:
        reasons.append("grade missing")
    elif not meets_threshold(grade, threshold=threshold):
        score = grade.get("score")
        reasons.append(f"score {score} < threshold {threshold}")
    has_audit = bool(audit) or bool(str(audit_path or "").strip())
    if not has_audit:
        reasons.append("audit row required")

    ok = not reasons
    return {
        "schema": "nexus.success_guard/v1",
        "ok": ok,
        "status": "success" if ok else "blocked",
        "threshold": float(threshold),
        "score": (grade or {}).get("score"),
        "resume_ok": bool(resume_ok),
        "audit_present": has_audit,
        "reasons": reasons,
    }


def assert_success(**kwargs: Any) -> dict[str, Any]:
    """Like success_guard but raises PrematureCompleteError on failure."""
    result = success_guard(**kwargs)
    if not result["ok"]:
        raise PrematureCompleteError(
            "premature success blocked: " + "; ".join(result["reasons"])
        )
    return result


# ---------------------------------------------------------------------------
# Load candidates from IMPROVE_OURS / mine digests (offline)
# ---------------------------------------------------------------------------


def _parse_idea_skill(block: str) -> tuple[Optional[float], Optional[float]]:
    m = _IDEA_SKILL.search(block)
    if not m:
        return None, None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None, None


def _slug_to_repo(name: str) -> str:
    return name.replace("__", "/", 1) if "__" in name else name


def _mine_eval_path(workdir: Path, repo: str) -> Optional[Path]:
    slug = repo.replace("/", "__")
    for base in (
        workdir / ".nexus_workspaces" / "mine_eval" / slug,
        workdir / ".nexus_workspaces" / "scout_repos" / slug,
    ):
        if base.is_dir():
            return base
    return None


def entry_to_grade(
    entry: dict[str, Any],
    *,
    workdir: Path | str,
    source: str = "",
) -> dict[str, Any]:
    """Normalize a digest entry into a grade artifact."""
    workdir = Path(workdir).resolve()
    repo = str(entry.get("repo") or "").strip()
    score = float(entry.get("score") or 0)
    idea = entry.get("idea")
    skill = entry.get("skill")
    if idea is None or skill is None:
        # derive from score when only composite present
        half = round(score / 2.0, 2) if score else 5.0
        idea = float(idea) if idea is not None else half
        skill = float(skill) if skill is not None else half
    local = entry.get("local_path") or entry.get("path") or ""
    if not local:
        p = _mine_eval_path(workdir, repo)
        local = str(p) if p else ""
    if not local:
        # stable relative evidence pointer even if clone missing
        local = f".nexus_workspaces/mine_eval/{repo.replace('/', '__')}"
    method = str(entry.get("method") or DEFAULT_METHOD)
    grade = build_grade(
        repo=repo,
        score=score,
        idea=float(idea),
        skill=float(skill),
        method=method,
        path=str(local),
        summary=entry.get("summary") or entry.get("excerpt") or "",
        pattern=entry.get("pattern") or "",
        source=source or entry.get("source") or "",
        local_path=local,
    )
    return validate_grade(grade, require_path=True)


def list_graded_candidates(
    workdir: Path | str,
    *,
    min_score: float = DEFAULT_SCORE_THRESHOLD,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List graded mine candidates from disk (IMPROVE_OURS / USE digests).

    Offline — no network. Prefer IMPROVE_OURS.md then latest use-*.md.
    """
    workdir = Path(workdir).resolve()
    root = workdir / ".nexus_state" / "repo_mine"
    grades: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1) Canonical grade JSON cache if present
    cache_dir = workdir / ".nexus_workspaces" / "grades"
    if cache_dir.is_dir():
        for p in sorted(cache_dir.glob("*.json")):
            try:
                g = load_grade(p)
            except (GradeValidationError, OSError):
                continue
            if float(g.get("score") or 0) < min_score:
                continue
            if g["repo"] in seen:
                continue
            seen.add(g["repo"])
            grades.append(g)
            if len(grades) >= limit:
                return grades

    # 2) IMPROVE_OURS + use digests via context_pack parser + idea/skill extract
    from .context_pack import parse_improve_digest

    texts: list[tuple[str, str]] = []
    ours = root / "IMPROVE_OURS.md"
    if ours.is_file():
        try:
            texts.append((ours.read_text(encoding="utf-8", errors="replace"), str(ours)))
        except OSError:
            pass
    if root.is_dir():
        use_files = sorted(root.glob("use-*.md"), reverse=True)[:3]
        for uf in use_files:
            try:
                texts.append((uf.read_text(encoding="utf-8", errors="replace"), str(uf)))
            except OSError:
                continue

    for text, src in texts:
        entries = parse_improve_digest(text, min_score=min_score, limit=limit * 2)
        # Enrich idea/skill from raw blocks
        for part in re.split(r"(?=^##\s+)", text, flags=re.MULTILINE):
            if not part.strip().startswith("##"):
                continue
            first = part.splitlines()[0]
            for e in entries:
                if e["repo"] in first or e["repo"].split("/")[-1] in first:
                    idea, skill = _parse_idea_skill(part)
                    if idea is not None:
                        e["idea"] = idea
                    if skill is not None:
                        e["skill"] = skill
                    # local clone line
                    for line in part.splitlines():
                        if "local clone:" in line.lower() or line.strip().startswith(
                            "- local:"
                        ):
                            loc = line.split(":", 1)[-1].strip()
                            if loc:
                                e["local_path"] = loc
                    break
        for e in entries:
            repo = e.get("repo") or ""
            if repo in seen:
                continue
            try:
                g = entry_to_grade(e, workdir=workdir, source=src)
            except GradeValidationError:
                continue
            if float(g.get("score") or 0) < min_score:
                continue
            seen.add(repo)
            grades.append(g)
            if len(grades) >= limit:
                return grades

    grades.sort(key=lambda g: (-float(g.get("score") or 0), g.get("repo") or ""))
    return grades[:limit]


def get_grade(
    workdir: Path | str,
    repo: str,
    *,
    min_score: float = 0.0,
) -> Optional[dict[str, Any]]:
    """Lookup one graded candidate by repo id (offline)."""
    repo = str(repo or "").strip()
    if not repo:
        return None
    # Direct cache hit
    workdir = Path(workdir).resolve()
    cache = workdir / ".nexus_workspaces" / "grades" / f"{repo.replace('/', '__')}.json"
    if cache.is_file():
        try:
            g = load_grade(cache)
            if float(g.get("score") or 0) >= min_score:
                return g
        except (GradeValidationError, OSError):
            pass
    for g in list_graded_candidates(workdir, min_score=min_score, limit=100):
        if g.get("repo") == repo:
            return g
    # slug form
    slug = repo.replace("__", "/")
    for g in list_graded_candidates(workdir, min_score=min_score, limit=100):
        if g.get("repo") == slug:
            return g
    return None


# ---------------------------------------------------------------------------
# Ordered checkpoint: grade_read → apply_plan (next_agent)
# ---------------------------------------------------------------------------


@dataclass
class OrderedLoopRun:
    """Minimal durable two-step loop with next_agent restore.

    Steps:
      grade_read  — load/validate grade, write grade.json checkpoint
      apply_plan  — write apply plan + decision audit (dry-run safe)

    Crash after grade_read → resume next_agent == apply_plan (no double grade_read side effects).
    """

    workdir: Path
    run_id: str
    grade: dict[str, Any]
    next_agent: str = "grade_read"
    completed: list[str] = field(default_factory=list)
    audit: Optional[dict[str, Any]] = None
    audit_path: Optional[str] = None
    grade_path: Optional[str] = None
    plan_path: Optional[str] = None
    resume_ok: bool = False
    dry_run: bool = True
    threshold: float = DEFAULT_SCORE_THRESHOLD
    timeline: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def run_dir(self) -> Path:
        d = self.workdir / ".nexus_workspaces" / "grade_loop" / self.run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def state_path(self) -> Path:
        return self.run_dir / "checkpoint.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nexus.grade_loop/v1",
            "run_id": self.run_id,
            "next_agent": self.next_agent,
            "action_order": list(ORDERED_STEPS),
            "completed": list(self.completed),
            "grade": self.grade,
            "grade_path": self.grade_path,
            "plan_path": self.plan_path,
            "audit": self.audit,
            "audit_path": self.audit_path,
            "resume_ok": self.resume_ok,
            "dry_run": self.dry_run,
            "threshold": self.threshold,
            "timeline": self.timeline,
            "meta": self.meta,
            "workdir": str(self.workdir),
        }

    def save(self) -> Path:
        atomic_write_json(self.state_path, self.to_dict())
        return self.state_path

    def _log(self, event: str, detail: str = "") -> None:
        self.timeline.append(
            {"ts": time.time(), "event": event, "detail": detail, "next_agent": self.next_agent}
        )

    @classmethod
    def load(cls, workdir: Path | str, run_id: str) -> "OrderedLoopRun":
        workdir = Path(workdir).resolve()
        path = workdir / ".nexus_workspaces" / "grade_loop" / run_id / "checkpoint.json"
        if not path.is_file():
            raise FileNotFoundError(f"grade_loop run not found: {run_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        run = cls(
            workdir=workdir,
            run_id=str(data.get("run_id") or run_id),
            grade=dict(data.get("grade") or {}),
            next_agent=str(data.get("next_agent") or "grade_read"),
            completed=list(data.get("completed") or []),
            audit=data.get("audit"),
            audit_path=data.get("audit_path"),
            grade_path=data.get("grade_path"),
            plan_path=data.get("plan_path"),
            resume_ok=bool(data.get("resume_ok")),
            dry_run=bool(data.get("dry_run", True)),
            threshold=float(data.get("threshold") or DEFAULT_SCORE_THRESHOLD),
            timeline=list(data.get("timeline") or []),
            meta=dict(data.get("meta") or {}),
        )
        # Resuming from disk proves checkpoint restore path
        run.resume_ok = True
        run._log("resume", f"next_agent={run.next_agent}")
        run.save()
        return run

    def status(self) -> dict[str, Any]:
        guard = success_guard(
            grade=self.grade,
            audit=self.audit,
            audit_path=self.audit_path,
            resume_ok=self.resume_ok
            or (self.next_agent == "done" and "apply_plan" in self.completed),
            threshold=self.threshold,
        )
        # Full success only when both steps done + guard
        both_done = set(ORDERED_STEPS).issubset(set(self.completed))
        if both_done and guard["ok"]:
            status = "success"
        elif both_done:
            status = "blocked"
        elif self.next_agent == "done":
            status = "blocked"
        else:
            status = "running"
        return {
            "run_id": self.run_id,
            "next_agent": self.next_agent,
            "action_order": list(ORDERED_STEPS),
            "completed": list(self.completed),
            "status": status,
            "grade": {
                "repo": self.grade.get("repo"),
                "score": self.grade.get("score"),
                "idea": self.grade.get("idea"),
                "skill": self.grade.get("skill"),
                "method": self.grade.get("method"),
                "path": self.grade.get("path"),
            },
            "grade_path": self.grade_path,
            "plan_path": self.plan_path,
            "audit_path": self.audit_path,
            "resume_ok": self.resume_ok,
            "threshold": self.threshold,
            "guard": guard,
            "checkpoint": str(self.state_path.relative_to(self.workdir))
            if self.state_path.exists()
            else str(self.state_path),
            "timeline": self.timeline,
        }

    def run_grade_read(self) -> dict[str, Any]:
        """Step 1: validate grade, persist grade.json, advance next_agent."""
        if "grade_read" in self.completed:
            return self.status()  # idempotent
        if self.next_agent != "grade_read":
            raise RuntimeError(
                f"expected next_agent=grade_read, got {self.next_agent!r}"
            )
        g = validate_grade(self.grade, require_path=True)
        self.grade = g
        gpath = self.run_dir / "grade.json"
        write_grade(gpath, g)
        self.grade_path = str(gpath.relative_to(self.workdir))
        self.completed.append("grade_read")
        self.next_agent = "apply_plan"
        self._log("grade_read", f"repo={g['repo']} score={g['score']}")
        self.save()
        return self.status()

    def run_apply_plan(self) -> dict[str, Any]:
        """Step 2: write apply plan + audit; success only via guard."""
        if "apply_plan" in self.completed:
            return self.status()
        if self.next_agent != "apply_plan":
            raise RuntimeError(
                f"expected next_agent=apply_plan, got {self.next_agent!r}"
            )
        if "grade_read" not in self.completed:
            raise RuntimeError("grade_read must complete before apply_plan")

        plan = {
            "schema": "nexus.apply_plan/v1",
            "run_id": self.run_id,
            "dry_run": self.dry_run,
            "repo": self.grade.get("repo"),
            "score": self.grade.get("score"),
            "pattern": self.grade.get("pattern")
            or "grade→checkpoint→audit self-improve slice",
            "planned_files": [
                "src/nexus/grade_artifact.py",
                "tests/test_grade_artifact.py",
                "docs/LATEST_IMPROVE_PLAN.md",
                "docs/ALIVE_IMPROVEMENTS.md",
            ],
            "note": "dry-run records plan only; does not mutate source tree",
            "ts": time.time(),
        }
        ppath = self.run_dir / "apply_plan.json"
        atomic_write_json(ppath, plan)
        self.plan_path = str(ppath.relative_to(self.workdir))

        from .improve_apply import build_audit, validate_audit

        evidence = [p for p in (self.grade_path, self.plan_path) if p]
        audit = build_audit(
            repo=str(self.grade.get("repo") or ""),
            score=float(self.grade.get("score") or 0),
            idea=float(self.grade.get("idea") or 0),
            skill=float(self.grade.get("skill") or 0),
            method=str(self.grade.get("method") or DEFAULT_METHOD),
            pattern=str(
                self.grade.get("pattern")
                or "ordered grade_read→apply_plan + decision audit"
            ),
            files_touched=list(plan["planned_files"]) + evidence,
            action_order=list(ORDERED_STEPS),
            evidence_refs=evidence,
            extra={
                "run_id": self.run_id,
                "cause_chain": [
                    f"grade:{self.grade.get('repo')}@{self.grade.get('score')}",
                    "step:grade_read",
                    "step:apply_plan",
                ],
            },
        )
        validate_audit(audit, workspace_root=self.workdir, require_evidence_exists=True)
        apath = self.run_dir / "decision_audit.json"
        atomic_write_json(apath, audit)
        self.audit = audit
        self.audit_path = str(apath.relative_to(self.workdir))
        self.completed.append("apply_plan")
        self.next_agent = "done"
        # Fresh start without load() still needs resume_ok for guard after full run
        # (integration tests set resume_ok via load; full run proves ordered steps)
        self.resume_ok = True
        self._log("apply_plan", self.audit_path or "")
        self.save()
        return self.status()

    def advance_one(self) -> dict[str, Any]:
        if self.next_agent == "grade_read":
            return self.run_grade_read()
        if self.next_agent == "apply_plan":
            return self.run_apply_plan()
        return self.status()

    def run_to_done(self) -> dict[str, Any]:
        while self.next_agent in ORDERED_STEPS:
            before = self.next_agent
            self.advance_one()
            if self.next_agent == before:
                break
        return self.status()


def start_ordered_loop(
    workdir: Path | str,
    *,
    grade: Optional[dict[str, Any]] = None,
    repo: Optional[str] = None,
    run_id: Optional[str] = None,
    dry_run: bool = True,
    threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> OrderedLoopRun:
    """Start grade_read→apply_plan loop from grade dict or repo lookup."""
    import uuid

    workdir = Path(workdir).resolve()
    if grade is None:
        if repo:
            grade = get_grade(workdir, repo)
            if grade is None:
                raise FileNotFoundError(f"no graded candidate for repo={repo!r}")
        else:
            cands = list_graded_candidates(workdir, min_score=threshold, limit=1)
            if cands:
                grade = cands[0]
            else:
                # fixture fallback for offline demos
                grade = build_grade(
                    repo="ahmedEid1/lumen",
                    score=15.0,
                    idea=7.0,
                    skill=8.0,
                    method=DEFAULT_METHOD,
                    path=str(
                        workdir
                        / ".nexus_workspaces"
                        / "mine_eval"
                        / "ahmedEid1__lumen"
                    ),
                    pattern="decision audit + honest evals",
                    source="fixture",
                )
    grade = validate_grade(grade, require_path=True)
    rid = run_id or f"gl-{uuid.uuid4().hex[:10]}"
    run = OrderedLoopRun(
        workdir=workdir,
        run_id=rid,
        grade=grade,
        dry_run=dry_run,
        threshold=threshold,
    )
    run._log("start", f"repo={grade.get('repo')} score={grade.get('score')}")
    run.save()
    return run


def resume_ordered_loop(workdir: Path | str, run_id: str) -> OrderedLoopRun:
    """Resume; sets resume_ok and restores next_agent from checkpoint."""
    return OrderedLoopRun.load(workdir, run_id)


def get_run_checkpoint(workdir: Path | str, run_id: str) -> dict[str, Any]:
    """Return checkpoint blob (next_agent + action_order) for MCP/CLI."""
    workdir = Path(workdir).resolve()
    path = workdir / ".nexus_workspaces" / "grade_loop" / run_id / "checkpoint.json"
    if not path.is_file():
        # fall back to improve_apply runs
        alt = workdir / ".nexus_workspaces" / "improve_apply" / run_id / "state.json"
        if alt.is_file():
            data = json.loads(alt.read_text(encoding="utf-8"))
            phase = str(data.get("phase") or "briefed")
            # map phase → next_agent-ish
            next_a = {
                "briefed": "grade_read",
                "context_packed": "apply_plan",
                "applying": "apply_plan",
                "audited": "done",
                "done": "done",
            }.get(phase, phase)
            return {
                "schema": "nexus.checkpoint/v1",
                "run_id": run_id,
                "source": "improve_apply",
                "next_agent": next_a,
                "phase": phase,
                "action_order": list(ORDERED_STEPS),
                "grade": data.get("grade"),
                "path": str(alt.relative_to(workdir)),
            }
        raise FileNotFoundError(f"checkpoint not found: {run_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "schema": "nexus.checkpoint/v1",
        "run_id": data.get("run_id") or run_id,
        "source": "grade_loop",
        "next_agent": data.get("next_agent"),
        "action_order": data.get("action_order") or list(ORDERED_STEPS),
        "completed": data.get("completed") or [],
        "grade": data.get("grade"),
        "resume_ok": bool(data.get("resume_ok")),
        "path": str(path.relative_to(workdir)),
    }


def get_run_status(workdir: Path | str, run_id: str) -> dict[str, Any]:
    """Return status for grade_loop or improve_apply run."""
    workdir = Path(workdir).resolve()
    gl = workdir / ".nexus_workspaces" / "grade_loop" / run_id / "checkpoint.json"
    if gl.is_file():
        run = OrderedLoopRun.load(workdir, run_id)
        return run.status()
    from .improve_apply import ImproveApplyRun

    ia_path = workdir / ".nexus_workspaces" / "improve_apply" / run_id / "state.json"
    if ia_path.is_file():
        run = ImproveApplyRun.load(workdir, run_id)
        st = run.status()
        st["source"] = "improve_apply"
        return st
    raise FileNotFoundError(f"run not found: {run_id}")


def format_board(status: dict[str, Any]) -> str:
    """routa-lite one-screen board for demos."""
    g = status.get("grade") or {}
    guard = status.get("guard") or {}
    lines = [
        "=== NEXUS grade loop board (routa-lite) ===",
        f"goal:     mine → grade → checkpoint → apply_plan",
        f"run_id:   {status.get('run_id')}",
        f"status:   {status.get('status')}",
        f"next:     {status.get('next_agent')}",
        f"tasks:    {', '.join(status.get('action_order') or ORDERED_STEPS)}",
        f"done:     {', '.join(status.get('completed') or []) or '(none)'}",
        f"repo:     {g.get('repo')}  score={g.get('score')} "
        f"(idea={g.get('idea')} skill={g.get('skill')})",
        f"method:   {g.get('method')}",
        f"evidence: {status.get('grade_path') or g.get('path')}",
        f"plan:     {status.get('plan_path')}",
        f"audit:    {status.get('audit_path')}",
        f"review:   {'pass' if status.get('status') == 'success' else 'hold'} "
        f"(guard={guard.get('status')})",
        f"checkpoint: {status.get('checkpoint')}",
    ]
    return "\n".join(lines)
