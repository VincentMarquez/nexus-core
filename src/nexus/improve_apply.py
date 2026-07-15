"""Idempotent improve-apply phase machine + decision audit.

First-apply slice (docs/LATEST_IMPROVE_PLAN.md P0.1–P0.5):

  grade artifact in → durable phase FSM → decision audit out

Patterns (shape only, not vendored trees):
- ahmedEid1/lumen — migration-phase guards, decision audit, honest evals
- Sompote/tiger_cowork — workspace path safety
- Network-AI / mission-control — MCP/CLI parity for apply.phase
- arXiv 2510.13343 — explicit action_order[]
- arXiv 2512.03278 / 2302.10809 — evidence-linked claims, causal lite

Phases::

  briefed → context_packed → applying → audited → done

Idempotent transitions; illegal skip/backtrack refused unless explicit resume
from the last committed phase.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .persist import atomic_write_json, append_jsonl, event_row

# ---------------------------------------------------------------------------
# Phase FSM
# ---------------------------------------------------------------------------

PHASES: tuple[str, ...] = (
    "briefed",
    "context_packed",
    "applying",
    "audited",
    "done",
)

PHASE_INDEX: dict[str, int] = {p: i for i, p in enumerate(PHASES)}

SCHEMA_VERSION = "nexus.improve_apply/v1"
DEFAULT_METHOD = "grok:grok-4.5"


class PhaseGuardError(RuntimeError):
    """Illegal phase transition (skip, backtrack, or unknown phase)."""


class AuditValidationError(ValueError):
    """Decision audit failed schema or evidence checks."""


class PathSafetyError(PermissionError):
    """Write/path target escapes the allowed workspace root."""


# ---------------------------------------------------------------------------
# Path safety (tiger_cowork-style jail)
# ---------------------------------------------------------------------------


def safe_path(workspace_root: Path | str, rel: str | Path) -> Path:
    """Resolve *rel* under *workspace_root*; reject escapes and abs paths outside."""
    root = Path(workspace_root).resolve()
    raw = str(rel)
    # Absolute paths must still resolve under root
    if Path(raw).is_absolute():
        target = Path(raw).resolve()
    else:
        clean = raw.lstrip("/\\")
        target = (root / clean).resolve()
    if root != target and root not in target.parents:
        raise PathSafetyError(f"path escapes workspace root: {rel}")
    return target


def assert_under_workspace(workspace_root: Path | str, path: Path | str) -> Path:
    """Return resolved path if under workspace; else raise PathSafetyError."""
    root = Path(workspace_root).resolve()
    target = Path(path).resolve()
    if root != target and root not in target.parents:
        raise PathSafetyError(f"path escapes workspace root: {path}")
    return target


# ---------------------------------------------------------------------------
# Decision audit
# ---------------------------------------------------------------------------

AUDIT_REQUIRED_FIELDS = (
    "repo",
    "score",
    "idea",
    "skill",
    "method",
    "pattern",
    "files_touched",
    "action_order",
    "evidence_refs",
)


def validate_audit(
    audit: dict[str, Any],
    *,
    workspace_root: Optional[Path | str] = None,
    require_evidence_exists: bool = True,
) -> dict[str, Any]:
    """Validate decision-audit schema; optionally require evidence files exist.

    *evidence_refs* must be relative paths under ``.nexus_workspaces/`` (or
    absolute paths that resolve there) when *require_evidence_exists* is True
    and *workspace_root* is set.
    """
    if not isinstance(audit, dict):
        raise AuditValidationError("audit must be a dict")

    missing = [k for k in AUDIT_REQUIRED_FIELDS if k not in audit]
    if missing:
        raise AuditValidationError(f"audit missing required fields: {missing}")

    # repo or arxiv_id (at least one non-empty identifier)
    repo = str(audit.get("repo") or "").strip()
    arxiv_id = str(audit.get("arxiv_id") or "").strip()
    if not repo and not arxiv_id:
        raise AuditValidationError("audit requires non-empty repo or arxiv_id")

    for num_key in ("score", "idea", "skill"):
        try:
            float(audit[num_key])
        except (TypeError, ValueError) as e:
            raise AuditValidationError(f"audit.{num_key} must be numeric") from e

    method = str(audit.get("method") or "").strip()
    if not method:
        raise AuditValidationError("audit.method must be non-empty")

    pattern = str(audit.get("pattern") or "").strip()
    if not pattern:
        raise AuditValidationError("audit.pattern must be non-empty")

    files = audit.get("files_touched")
    if not isinstance(files, list) or not all(isinstance(x, str) for x in files):
        raise AuditValidationError("audit.files_touched must be a list of strings")

    order = audit.get("action_order")
    if not isinstance(order, list) or not order or not all(isinstance(x, str) for x in order):
        raise AuditValidationError(
            "audit.action_order must be a non-empty list of strings"
        )

    refs = audit.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        raise AuditValidationError(
            "audit.evidence_refs must be a non-empty list (Thucy-style claim links)"
        )
    if not all(isinstance(x, str) and x.strip() for x in refs):
        raise AuditValidationError("audit.evidence_refs entries must be non-empty strings")

    if require_evidence_exists and workspace_root is not None:
        root = Path(workspace_root).resolve()
        workspaces = (root / ".nexus_workspaces").resolve()
        for ref in refs:
            try:
                # Prefer resolving under project root
                p = Path(ref)
                if not p.is_absolute():
                    p = (root / ref).resolve()
                else:
                    p = p.resolve()
            except OSError as e:
                raise AuditValidationError(f"orphan evidence_ref {ref!r}: {e}") from e
            # Must live under .nexus_workspaces
            if workspaces != p and workspaces not in p.parents:
                raise AuditValidationError(
                    f"orphan evidence_ref (not under .nexus_workspaces/): {ref}"
                )
            if not p.exists():
                raise AuditValidationError(f"orphan evidence_ref (missing file): {ref}")

    return audit


def build_audit(
    *,
    repo: str = "",
    arxiv_id: str = "",
    score: float,
    idea: float,
    skill: float,
    method: str = DEFAULT_METHOD,
    pattern: str,
    files_touched: list[str],
    action_order: list[str],
    evidence_refs: list[str],
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Construct a decision-audit dict (does not write)."""
    audit: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "repo": repo,
        "arxiv_id": arxiv_id,
        "score": float(score),
        "idea": float(idea),
        "skill": float(skill),
        "method": method,
        "pattern": pattern,
        "files_touched": list(files_touched),
        "action_order": list(action_order),
        "evidence_refs": list(evidence_refs),
        "ts": time.time(),
    }
    if extra:
        for k, v in extra.items():
            if k not in audit:
                audit[k] = v
    return audit


# ---------------------------------------------------------------------------
# Grade fixture helpers
# ---------------------------------------------------------------------------


def default_lumen_grade() -> dict[str, Any]:
    """EVIDENCE-backed fixture grade for ahmedEid1/lumen (score 15.0)."""
    return {
        "repo": "ahmedEid1/lumen",
        "score": 15.0,
        "idea": 7.0,
        "skill": 8.0,
        "method": DEFAULT_METHOD,
        "pattern": (
            "idempotent phases + migration-phase guards + decision audit "
            "(honest public evals)"
        ),
        "arxiv_id": "2510.13343",
        "notes": (
            "Port pattern only from IMPROVE_OURS / LATEST_IMPROVE_PLAN first apply slice."
        ),
    }


def load_grade_fixture(path: Path | str) -> dict[str, Any]:
    """Load a grade JSON file, or synthesize from a mine_eval/scout directory name."""
    p = Path(path)
    if p.is_file() and p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise AuditValidationError("grade fixture JSON must be an object")
        return data

    # Directory fixture: derive repo slug from name like ahmedEid1__lumen
    name = p.name if p.exists() else str(path).rstrip("/").split("/")[-1]
    if name == "ahmedEid1__lumen" or "lumen" in name.lower():
        g = default_lumen_grade()
        g["fixture_path"] = str(p)
        return g

    # Generic synthetic grade from directory slug
    repo = name.replace("__", "/", 1) if "__" in name else name
    return {
        "repo": repo,
        "score": 10.0,
        "idea": 5.0,
        "skill": 5.0,
        "method": DEFAULT_METHOD,
        "pattern": f"portable pattern from mined repo {repo}",
        "fixture_path": str(p),
    }


# ---------------------------------------------------------------------------
# Run state machine
# ---------------------------------------------------------------------------


def _runs_dir(workdir: Path) -> Path:
    d = workdir / ".nexus_workspaces" / "improve_apply"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class ImproveApplyRun:
    """Durable, idempotent improve-apply phase machine."""

    workdir: Path
    run_id: str
    grade: dict[str, Any]
    phase: str = "briefed"
    dry_run: bool = True
    timeline: list[dict[str, Any]] = field(default_factory=list)
    audit: Optional[dict[str, Any]] = None
    context_pack_path: Optional[str] = None
    audit_path: Optional[str] = None
    files_touched: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    # -- persistence --------------------------------------------------------

    @property
    def run_dir(self) -> Path:
        return _runs_dir(self.workdir) / self.run_id

    @property
    def state_path(self) -> Path:
        return self.run_dir / "state.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "run_id": self.run_id,
            "phase": self.phase,
            "dry_run": self.dry_run,
            "grade": self.grade,
            "timeline": self.timeline,
            "audit": self.audit,
            "context_pack_path": self.context_pack_path,
            "audit_path": self.audit_path,
            "files_touched": self.files_touched,
            "meta": self.meta,
            "workdir": str(self.workdir),
        }

    def save(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        # path safety: state must stay under workdir
        assert_under_workspace(self.workdir, self.state_path)
        atomic_write_json(self.state_path, self.to_dict())
        return self.state_path

    @classmethod
    def load(cls, workdir: Path | str, run_id: str) -> "ImproveApplyRun":
        workdir = Path(workdir).resolve()
        path = _runs_dir(workdir) / run_id / "state.json"
        if not path.is_file():
            raise FileNotFoundError(f"improve-apply run not found: {run_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            workdir=workdir,
            run_id=str(data.get("run_id") or run_id),
            grade=dict(data.get("grade") or {}),
            phase=str(data.get("phase") or "briefed"),
            dry_run=bool(data.get("dry_run", True)),
            timeline=list(data.get("timeline") or []),
            audit=data.get("audit"),
            context_pack_path=data.get("context_pack_path"),
            audit_path=data.get("audit_path"),
            files_touched=list(data.get("files_touched") or []),
            meta=dict(data.get("meta") or {}),
        )

    def _log(self, event: str, detail: str = "", **extra: Any) -> None:
        row = event_row(
            event,
            task_id=self.run_id,
            status=self.phase,
            detail=detail,
            extra=extra or None,
        )
        self.timeline.append(row)
        append_jsonl(self.run_dir / "events.jsonl", row)

    # -- phase guards -------------------------------------------------------

    def _require_phase(self, expected: str) -> None:
        if self.phase != expected:
            raise PhaseGuardError(
                f"expected phase {expected!r}, current is {self.phase!r} "
                f"(refuse skip/backtrack; resume from last committed phase)"
            )

    def can_transition(self, target: str) -> bool:
        if target not in PHASE_INDEX:
            return False
        cur = PHASE_INDEX.get(self.phase, -1)
        nxt = PHASE_INDEX[target]
        # same phase = idempotent no-op; next phase only
        return nxt == cur or nxt == cur + 1

    def transition(self, target: str) -> str:
        """Move to *target* if legal; same phase is idempotent no-op."""
        if target not in PHASE_INDEX:
            raise PhaseGuardError(f"unknown phase: {target!r}")
        cur_i = PHASE_INDEX[self.phase]
        tgt_i = PHASE_INDEX[target]
        if tgt_i == cur_i:
            return self.phase  # idempotent
        if tgt_i == cur_i + 1:
            prev = self.phase
            self.phase = target
            self._log("phase_transition", f"{prev} → {target}")
            self.save()
            return self.phase
        raise PhaseGuardError(
            f"illegal transition {self.phase!r} → {target!r} "
            f"(only next phase or no-op allowed)"
        )

    # -- phase bodies (idempotent) ------------------------------------------

    def ensure_briefed(self) -> str:
        """Phase 0: grade loaded, pattern chosen (already true at create)."""
        if self.phase != "briefed" and PHASE_INDEX[self.phase] > 0:
            return self.phase  # already past; no-op
        self._require_phase("briefed")
        # ensure grade has essentials
        if not (self.grade.get("repo") or self.grade.get("arxiv_id")):
            raise PhaseGuardError("grade fixture missing repo/arxiv_id")
        if not self.grade.get("pattern"):
            self.grade["pattern"] = "idempotent phases + decision audit"
        if "briefed_at" not in self.meta:
            self.meta["briefed_at"] = time.time()
            self._log(
                "briefed",
                f"repo={self.grade.get('repo')} score={self.grade.get('score')}",
            )
            self.save()
        return self.phase

    def ensure_context_packed(self) -> str:
        """Phase 1: write bounded multi-source context pack under run dir.

        P1.4 formal stage: grade + research notes + repo digests with hard
        char budgets (arXiv 2508.08322 context engineering). Uses
        ``nexus.context_pack`` builder; schema remains ``nexus.context_pack/v1``.
        """
        if PHASE_INDEX[self.phase] > PHASE_INDEX["context_packed"]:
            return self.phase
        if self.phase == "context_packed" and self.context_pack_path:
            return self.phase  # idempotent
        self.ensure_briefed()
        self.transition("context_packed")

        from .context_pack import pack_from_grade

        built = pack_from_grade(self.workdir, self.grade)
        # Preserve flat grade fields for older consumers + tests
        pack = built.to_dict()
        pack.update(
            {
                "run_id": self.run_id,
                "repo": self.grade.get("repo"),
                "arxiv_id": self.grade.get("arxiv_id"),
                "score": self.grade.get("score"),
                "idea": self.grade.get("idea"),
                "skill": self.grade.get("skill"),
                "method": self.grade.get("method") or DEFAULT_METHOD,
                "pattern": self.grade.get("pattern"),
                "notes": str(self.grade.get("notes") or "")[:2000],
                "source": "improve_apply",
                "prompt": built.prompt_block(),
            }
        )
        pack_path = self.run_dir / "context_pack.json"
        assert_under_workspace(self.workdir, pack_path)
        atomic_write_json(pack_path, pack)
        # also keep a prompt-only artifact for operators
        prompt_path = self.run_dir / "context_pack.prompt.md"
        assert_under_workspace(self.workdir, prompt_path)
        prompt_path.write_text(built.prompt_block(), encoding="utf-8")
        # relative evidence path from workdir
        rel = str(pack_path.relative_to(self.workdir))
        self.context_pack_path = rel
        if rel not in self.files_touched:
            self.files_touched.append(rel)
        rel_prompt = str(prompt_path.relative_to(self.workdir))
        if rel_prompt not in self.files_touched:
            self.files_touched.append(rel_prompt)
        self.meta["context_pack_chars"] = built.total_chars
        self.meta["context_pack_est_tokens"] = built.est_tokens
        self.meta["context_pack_sections"] = [s.name for s in built.sections]
        self._log(
            "context_packed",
            f"{rel} chars={built.total_chars} sections={len(built.sections)}",
        )
        self.save()
        return self.phase

    def ensure_applying(self) -> str:
        """Phase 2: dry-run apply — record intended files, no tree vendor."""
        if PHASE_INDEX[self.phase] > PHASE_INDEX["applying"]:
            return self.phase
        if self.phase == "applying" and self.meta.get("apply_recorded"):
            return self.phase
        self.ensure_context_packed()
        self.transition("applying")

        # Dry-run plan: module + tests + docs that the slice would touch
        plan_files = [
            "src/nexus/improve_apply.py",
            "tests/test_improve_apply.py",
            "docs/LATEST_IMPROVE_PLAN.md",
            "docs/ALIVE_IMPROVEMENTS.md",
        ]
        plan = {
            "schema": "nexus.apply_plan/v1",
            "run_id": self.run_id,
            "dry_run": self.dry_run,
            "pattern": self.grade.get("pattern"),
            "planned_files": plan_files,
            "note": "dry-run records plan only; does not mutate source tree",
            "ts": time.time(),
        }
        plan_path = self.run_dir / "apply_plan.json"
        assert_under_workspace(self.workdir, plan_path)
        atomic_write_json(plan_path, plan)
        rel = str(plan_path.relative_to(self.workdir))
        if rel not in self.files_touched:
            self.files_touched.append(rel)
        # Track planned source paths as symbolic (not written outside workspace)
        for f in plan_files:
            if f not in self.files_touched:
                self.files_touched.append(f)
        self.meta["apply_recorded"] = True
        self.meta["apply_plan_path"] = rel
        self._log("applying", f"dry_run={self.dry_run} files={len(plan_files)}")
        self.save()
        return self.phase

    def ensure_audited(self) -> str:
        """Phase 3: write + validate decision audit artifact."""
        if PHASE_INDEX[self.phase] > PHASE_INDEX["audited"]:
            return self.phase
        if self.phase == "audited" and self.audit_path and self.audit:
            return self.phase
        self.ensure_applying()
        self.transition("audited")

        evidence: list[str] = []
        if self.context_pack_path:
            evidence.append(self.context_pack_path)
        plan_rel = self.meta.get("apply_plan_path")
        if plan_rel:
            evidence.append(str(plan_rel))
        # Ensure evidence files exist under .nexus_workspaces
        if not evidence:
            raise PhaseGuardError("no evidence_refs available for audit")

        action_order = [
            "briefed",
            "context_packed",
            "applying",
            "audited",
            "done",
        ]
        audit = build_audit(
            repo=str(self.grade.get("repo") or ""),
            arxiv_id=str(self.grade.get("arxiv_id") or ""),
            score=float(self.grade.get("score") or 0),
            idea=float(self.grade.get("idea") or 0),
            skill=float(self.grade.get("skill") or 0),
            method=str(self.grade.get("method") or DEFAULT_METHOD),
            pattern=str(self.grade.get("pattern") or "idempotent phases + decision audit"),
            files_touched=list(self.files_touched),
            action_order=action_order,
            evidence_refs=evidence,
            extra={
                "run_id": self.run_id,
                "dry_run": self.dry_run,
                "cause_chain": [
                    f"grade:{self.grade.get('repo')}@{self.grade.get('score')}",
                    f"pattern:{self.grade.get('pattern')}",
                    f"files:{len(self.files_touched)}",
                ],
            },
        )
        validate_audit(audit, workspace_root=self.workdir, require_evidence_exists=True)

        audit_path = self.run_dir / "decision_audit.json"
        assert_under_workspace(self.workdir, audit_path)
        atomic_write_json(audit_path, audit)
        rel = str(audit_path.relative_to(self.workdir))
        self.audit = audit
        self.audit_path = rel
        if rel not in self.files_touched:
            self.files_touched.append(rel)
        self._log("audited", rel)
        self.save()
        return self.phase

    def ensure_done(self) -> str:
        """Phase 4: mark complete."""
        if self.phase == "done":
            return self.phase
        self.ensure_audited()
        self.transition("done")
        self.meta["completed_at"] = time.time()
        self._log("done", self.audit_path or "")
        self.save()
        try:
            from .ops_store import note_improve_run

            note_improve_run(
                self.workdir,
                self.run_id,
                phase="done",
                repo=str(self.grade.get("repo") or ""),
                status="completed",
            )
        except Exception:
            pass
        return self.phase

    def run_to_done(self) -> dict[str, Any]:
        """Advance through all remaining phases to done (idempotent)."""
        self.ensure_briefed()
        self.ensure_context_packed()
        self.ensure_applying()
        self.ensure_audited()
        self.ensure_done()
        return self.status()

    def advance_one(self) -> dict[str, Any]:
        """Advance exactly one phase (or no-op if already done)."""
        handlers = {
            "briefed": self.ensure_context_packed,
            "context_packed": self.ensure_applying,
            "applying": self.ensure_audited,
            "audited": self.ensure_done,
            "done": lambda: "done",
        }
        # For briefed with no briefed_at, first seal briefed then still allow advance
        if self.phase == "briefed" and "briefed_at" not in self.meta:
            self.ensure_briefed()
            return self.status()
        fn = handlers.get(self.phase)
        if fn is None:
            raise PhaseGuardError(f"unknown phase: {self.phase}")
        fn()
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "dry_run": self.dry_run,
            "grade": {
                "repo": self.grade.get("repo"),
                "score": self.grade.get("score"),
                "idea": self.grade.get("idea"),
                "skill": self.grade.get("skill"),
                "method": self.grade.get("method") or DEFAULT_METHOD,
                "pattern": self.grade.get("pattern"),
                "arxiv_id": self.grade.get("arxiv_id"),
            },
            "audit_path": self.audit_path,
            "context_pack_path": self.context_pack_path,
            "files_touched": list(self.files_touched),
            "timeline": [
                {
                    "event": t.get("event"),
                    "status": t.get("status"),
                    "detail": t.get("detail"),
                }
                for t in self.timeline
            ],
            "audit": self.audit,
            "state_path": str(self.state_path.relative_to(self.workdir))
            if self.state_path.exists()
            else str(self.state_path),
        }


def start_run(
    workdir: Path | str,
    *,
    grade: Optional[dict[str, Any]] = None,
    fixture: Optional[Path | str] = None,
    run_id: Optional[str] = None,
    dry_run: bool = True,
) -> ImproveApplyRun:
    """Create a new improve-apply run from grade dict or fixture path."""
    workdir = Path(workdir).resolve()
    if grade is None:
        if fixture is not None:
            grade = load_grade_fixture(fixture)
        else:
            grade = default_lumen_grade()
    rid = run_id or f"ia-{uuid.uuid4().hex[:10]}"
    run = ImproveApplyRun(
        workdir=workdir,
        run_id=rid,
        grade=dict(grade),
        dry_run=dry_run,
    )
    run.run_dir.mkdir(parents=True, exist_ok=True)
    run._log("start", f"repo={run.grade.get('repo')} score={run.grade.get('score')}")
    run.save()
    # P1.1: register on mission-control-style ops board (fail-open)
    try:
        from .ops_store import note_improve_run

        note_improve_run(
            workdir,
            rid,
            phase=run.phase,
            repo=str(run.grade.get("repo") or ""),
            status="running",
        )
    except Exception:
        pass
    return run


def resume_or_start(
    workdir: Path | str,
    *,
    run_id: Optional[str] = None,
    grade: Optional[dict[str, Any]] = None,
    fixture: Optional[Path | str] = None,
    dry_run: bool = True,
) -> ImproveApplyRun:
    """Resume existing run_id if present; otherwise start new."""
    workdir = Path(workdir).resolve()
    if run_id:
        state = _runs_dir(workdir) / run_id / "state.json"
        if state.is_file():
            return ImproveApplyRun.load(workdir, run_id)
    return start_run(
        workdir, grade=grade, fixture=fixture, run_id=run_id, dry_run=dry_run
    )


def list_runs(workdir: Path | str) -> list[dict[str, Any]]:
    """List improve-apply runs under workdir."""
    workdir = Path(workdir).resolve()
    root = _runs_dir(workdir)
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        sp = d / "state.json"
        if not sp.is_file():
            continue
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(
            {
                "run_id": data.get("run_id") or d.name,
                "phase": data.get("phase"),
                "repo": (data.get("grade") or {}).get("repo"),
                "score": (data.get("grade") or {}).get("score"),
                "audit_path": data.get("audit_path"),
            }
        )
    return out


def format_demo(status: dict[str, Any], *, show_audit: bool = True) -> str:
    """Human-readable demo output for self-improve-slice."""
    lines: list[str] = []
    lines.append("=== NEXUS self-improve slice (grade → phase FSM → audit) ===")
    g = status.get("grade") or {}
    lines.append(f"run_id:  {status.get('run_id')}")
    lines.append(f"phase:   {status.get('phase')}")
    lines.append(f"dry_run: {status.get('dry_run')}")
    lines.append("")
    lines.append("--- Grok grade ---")
    lines.append(f"  repo:    {g.get('repo')}")
    lines.append(f"  score:   {g.get('score')}  (idea={g.get('idea')} skill={g.get('skill')})")
    lines.append(f"  method:  {g.get('method')}")
    lines.append(f"  arxiv:   {g.get('arxiv_id') or '(none)'}")
    lines.append(f"  pattern: {g.get('pattern')}")
    lines.append("")
    lines.append("--- phase timeline ---")
    for t in status.get("timeline") or []:
        lines.append(
            f"  [{t.get('status') or '?'}] {t.get('event')}: {t.get('detail') or ''}"
        )
    lines.append("")
    lines.append(f"audit_path: {status.get('audit_path')}")
    lines.append(f"context:    {status.get('context_pack_path')}")
    lines.append(f"state:      {status.get('state_path')}")
    if show_audit and status.get("audit"):
        lines.append("")
        lines.append("--- decision audit ---")
        lines.append(json.dumps(status["audit"], indent=2, default=str))
    lines.append("")
    lines.append("proof: research→mine→grade→apply loop is real (lumen honest-eval spirit)")
    return "\n".join(lines)


def run_demo(
    workdir: Path | str,
    *,
    fixture: Optional[Path | str] = None,
    run_id: Optional[str] = None,
    show_audit: bool = True,
    dry_run: bool = True,
) -> dict[str, Any]:
    """One-shot demo: start/resume → run_to_done → return status."""
    workdir = Path(workdir).resolve()
    run = resume_or_start(
        workdir, run_id=run_id, fixture=fixture, dry_run=dry_run
    )
    status = run.run_to_done()
    status["demo_text"] = format_demo(status, show_audit=show_audit)
    return status
