"""SWE-Adept two-phase planning: localization → resolution (arXiv 2603.01327v2).

Paper: *SWE-Adept: An LLM-Based Agentic Framework for Deep Codebase Analysis
and Structured Issue Resolution*
https://arxiv.org/abs/2603.01327v2

Pattern (shape only — not a vendored paper implementation):

  issue / task
       │
       ▼
  ┌─────────────────┐
  │  Localization   │  identify issue-relevant files/modules (no edits)
  └────────┬────────┘  ranked targets + locate.* steps
           │ targets[]
           ▼
  ┌─────────────────┐
  │  Resolution     │  structured fix plan against localized targets
  └────────┬────────┘  resolve.* steps (edit / test / verify)
           │
           ▼
  Orchestrator.run_task(with_swe_plan=True)
    envelope.meta["swe_adept_plan"] + engine journal seed

Repository-level SWE fails when agents jump to edits without localizing first.
This module produces an explicit multi-step *plan* that **separates**
localization (where?) from resolution (how to fix?), offline-first with a
deterministic path scorer. Optional inject of LLM localization/resolution JSON.

Fail-closed for empty goals. Localization never mutates the tree. Resolution
steps are structure-only until a Caller / worker executes them. Phase
action/prefix purity is enforced at readiness; runtime engine enforcement of
phase order is a downstream concern (plan is advisory to the worker journal).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, Sequence

SCHEMA = "nexus.swe_adept_plan/v1"
PAPER = "arxiv:2603.01327v2"

PHASE_LOCALIZATION = "localization"
PHASE_RESOLUTION = "resolution"
PHASES = frozenset({PHASE_LOCALIZATION, PHASE_RESOLUTION})

STATUS_DRAFT = "draft"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
PLAN_STATUSES = frozenset({STATUS_DRAFT, STATUS_READY, STATUS_FAILED})

STEP_PENDING = "pending"

# Clamp limits for meta/kwarg knobs (orchestrator + soft-hook)
SWE_LIMIT_MIN = 1
SWE_LIMIT_MAX = 64
# Bounded summary targets for ops/status surfaces
SUMMARY_TARGETS_CAP = 12

# Default search roots (repo-relative). Prefer code/tests over noise.
DEFAULT_SEARCH_ROOTS: tuple[str, ...] = ("src", "tests", "docs")

# Skip common junk / VCS / env while walking (also used by path sanitize)
_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        ".nexus_state",
        ".nexus_workspaces",
        "dist",
        "build",
        ".tox",
        ".eggs",
        ".idea",
        ".vscode",
    }
)

_CODE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".md",
        ".rst",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".sh",
    }
)

# Intent words that bias resolution step selection
_RESOLUTION_INTENTS = (
    "fix",
    "implement",
    "add",
    "update",
    "refactor",
    "repair",
    "resolve",
    "patch",
    "test",
    "verify",
)

_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{1,48}")


class SweAdeptPlanError(ValueError):
    """SWE-Adept plan invalid or localization failed closed."""


def clamp_swe_limit(value: Any, default: int = 8) -> int:
    """Coerce + clamp a SWE-Adept numeric knob into ``[1, 64]``."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = int(default)
    return max(SWE_LIMIT_MIN, min(n, SWE_LIMIT_MAX))


def sanitize_plan_path(path: Any) -> str:
    """Normalize a repo-relative plan path; reject abs / ``..`` / forbidden.

    Returns cleaned POSIX-ish relative path, or raises :class:`SweAdeptPlanError`.
    The synthetic fallback ``(unlocalized)`` is allowed as a resolution placeholder.
    """
    raw = str(path or "").strip().replace("\\", "/")
    if not raw:
        raise SweAdeptPlanError("empty plan path")
    if raw == "(unlocalized)":
        return raw
    # Strip leading ./ only
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw or raw in {".", "/"}:
        raise SweAdeptPlanError(f"invalid plan path: {path!r}")
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise SweAdeptPlanError(f"absolute plan path rejected: {path!r}")
    pure = PurePosixPath(raw)
    parts = pure.parts
    if any(p == ".." for p in parts):
        raise SweAdeptPlanError(f"path traversal rejected: {path!r}")
    if any(p in _SKIP_DIR_NAMES for p in parts):
        raise SweAdeptPlanError(f"forbidden path segment rejected: {path!r}")
    # Reject secret / env files the scope contract forbids (file prefixes, not dirs)
    for p in parts:
        if p == ".env" or p.startswith(".env."):
            raise SweAdeptPlanError(f"forbidden secret path rejected: {path!r}")
    # Drop empty / "." segments
    cleaned = "/".join(p for p in parts if p and p != ".")
    if not cleaned:
        raise SweAdeptPlanError(f"invalid plan path: {path!r}")
    return cleaned


def safe_plan_path(path: Any) -> Optional[str]:
    """Like :func:`sanitize_plan_path` but returns None instead of raising."""
    try:
        return sanitize_plan_path(path)
    except SweAdeptPlanError:
        return None


# ── data ───────────────────────────────────────────────────────────────────


@dataclass
class LocalizationHit:
    """One ranked file/module believed relevant to the issue."""

    path: str
    score: float
    kind: str = "file"  # file | module | dir
    reason: str = ""
    phase: str = PHASE_LOCALIZATION

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "score": float(self.score),
            "kind": str(self.kind or "file"),
            "reason": str(self.reason or ""),
            "phase": PHASE_LOCALIZATION,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "LocalizationHit":
        if not isinstance(d, dict):
            raise SweAdeptPlanError(
                f"localization hit must be a dict, got {type(d).__name__}"
            )
        path = str(d.get("path") or d.get("file") or d.get("module") or "").strip()
        if not path:
            raise SweAdeptPlanError("localization hit missing path")
        path = sanitize_plan_path(path)
        try:
            score = float(d.get("score") if d.get("score") is not None else 0.0)
        except (TypeError, ValueError):
            score = 0.0
        return cls(
            path=path,
            score=score,
            kind=str(d.get("kind") or "file"),
            reason=str(d.get("reason") or ""),
        )


@dataclass
class PhaseStep:
    """One structured planning step within a phase (not yet executed)."""

    id: int
    phase: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    status: str = STEP_PENDING
    target: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": int(self.id),
            "phase": str(self.phase),
            "action": str(self.action),
            "args": dict(self.args or {}),
            "rationale": str(self.rationale or ""),
            "status": str(self.status or STEP_PENDING),
            "target": str(self.target or ""),
        }

    @classmethod
    def from_dict(cls, d: Any, *, default_id: int = 1) -> "PhaseStep":
        if not isinstance(d, dict):
            raise SweAdeptPlanError(f"phase step must be a dict, got {type(d).__name__}")
        action = str(
            d.get("action") or d.get("tool") or d.get("name") or d.get("function") or ""
        ).strip()
        if not action:
            raise SweAdeptPlanError("phase step missing action")
        phase = str(d.get("phase") or "").strip().lower()
        if phase not in PHASES:
            # Infer from action prefix
            if action.startswith("locate.") or action.startswith("localization."):
                phase = PHASE_LOCALIZATION
            else:
                phase = PHASE_RESOLUTION
        try:
            sid = int(d.get("id") if d.get("id") is not None else default_id)
        except (TypeError, ValueError) as e:
            raise SweAdeptPlanError(f"phase step id must be int: {d.get('id')!r}") from e
        args = d.get("args") if d.get("args") is not None else d.get("arguments")
        if args is None:
            args = d.get("parameters") or {}
        if not isinstance(args, dict):
            raise SweAdeptPlanError(
                f"phase step args must be object, got {type(args).__name__}"
            )
        raw_target = str(
            d.get("target") or d.get("path") or args.get("path") or ""
        ).strip()
        target = ""
        if raw_target:
            cleaned = safe_plan_path(raw_target)
            if cleaned is None:
                raise SweAdeptPlanError(
                    f"phase step has unsafe target path: {raw_target!r}"
                )
            target = cleaned
            # Keep args.path aligned with sanitized target when present
            if "path" in args:
                args = {**args, "path": cleaned}
        return cls(
            id=sid,
            phase=phase,
            action=action,
            args=dict(args),
            rationale=str(d.get("rationale") or d.get("why") or d.get("reason") or ""),
            status=str(d.get("status") or STEP_PENDING).strip().lower() or STEP_PENDING,
            target=target,
        )


@dataclass
class PlanPhase:
    """One of the two SWE-Adept phases (localization or resolution)."""

    name: str
    status: str = STATUS_DRAFT
    steps: list[PhaseStep] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    hits: list[LocalizationHit] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": str(self.name),
            "status": str(self.status),
            "n_steps": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
            "targets": list(self.targets),
            "hits": [h.to_dict() for h in self.hits],
            "notes": str(self.notes or ""),
        }

    @classmethod
    def from_dict(cls, d: Any, *, default_name: str = PHASE_LOCALIZATION) -> "PlanPhase":
        if not isinstance(d, dict):
            raise SweAdeptPlanError(f"plan phase must be a dict, got {type(d).__name__}")
        name = str(d.get("name") or d.get("phase") or default_name).strip().lower()
        if name not in PHASES:
            name = default_name
        steps: list[PhaseStep] = []
        raw_steps = d.get("steps") or []
        if isinstance(raw_steps, list):
            for i, raw in enumerate(raw_steps, start=1):
                if isinstance(raw, dict):
                    raw = {**raw, "phase": raw.get("phase") or name}
                steps.append(PhaseStep.from_dict(raw, default_id=i))
        hits: list[LocalizationHit] = []
        for raw in d.get("hits") or []:
            if isinstance(raw, dict):
                try:
                    hits.append(LocalizationHit.from_dict(raw))
                except SweAdeptPlanError:
                    continue
        raw_targets = d.get("targets") or [h.path for h in hits]
        if not isinstance(raw_targets, list):
            raw_targets = []
        targets: list[str] = []
        for t in raw_targets:
            cleaned = safe_plan_path(t)
            if cleaned and cleaned != "(unlocalized)":
                targets.append(cleaned)
        status = str(d.get("status") or STATUS_DRAFT).strip().lower()
        if status not in PLAN_STATUSES:
            status = STATUS_DRAFT
        return cls(
            name=name,
            status=status,
            steps=steps,
            targets=targets,
            hits=hits,
            notes=str(d.get("notes") or ""),
        )


@dataclass
class SweAdeptPlan:
    """Full two-phase plan: localization first, then resolution."""

    task: str
    localization: PlanPhase = field(
        default_factory=lambda: PlanPhase(name=PHASE_LOCALIZATION)
    )
    resolution: PlanPhase = field(
        default_factory=lambda: PlanPhase(name=PHASE_RESOLUTION)
    )
    status: str = STATUS_DRAFT
    planner: str = "heuristic"
    schema: str = SCHEMA
    paper: str = PAPER
    created_at: float = field(default_factory=time.time)
    notes: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        loc = self.localization.to_dict()
        res = self.resolution.to_dict()
        all_steps = list(self.localization.steps) + list(self.resolution.steps)
        return {
            "schema": self.schema,
            "paper": self.paper,
            "task": self.task,
            "status": self.status,
            "planner": self.planner,
            "phases": [PHASE_LOCALIZATION, PHASE_RESOLUTION],
            "localization": loc,
            "resolution": res,
            "n_localization_steps": len(self.localization.steps),
            "n_resolution_steps": len(self.resolution.steps),
            "n_steps": len(all_steps),
            "targets": list(self.localization.targets),
            "created_at": self.created_at,
            "notes": self.notes,
            "meta": dict(self.meta or {}),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, d: Any) -> "SweAdeptPlan":
        if not isinstance(d, dict):
            raise SweAdeptPlanError(f"plan must be a dict, got {type(d).__name__}")
        task = str(d.get("task") or d.get("goal") or d.get("issue") or "").strip()
        loc_raw = d.get("localization") or d.get(PHASE_LOCALIZATION) or {}
        res_raw = d.get("resolution") or d.get(PHASE_RESOLUTION) or {}
        localization = (
            PlanPhase.from_dict(loc_raw, default_name=PHASE_LOCALIZATION)
            if isinstance(loc_raw, dict)
            else PlanPhase(name=PHASE_LOCALIZATION)
        )
        resolution = (
            PlanPhase.from_dict(res_raw, default_name=PHASE_RESOLUTION)
            if isinstance(res_raw, dict)
            else PlanPhase(name=PHASE_RESOLUTION)
        )
        status = str(d.get("status") or STATUS_DRAFT).strip().lower()
        if status not in PLAN_STATUSES:
            status = STATUS_DRAFT
        return cls(
            task=task,
            localization=localization,
            resolution=resolution,
            status=status,
            planner=str(d.get("planner") or "injected"),
            schema=str(d.get("schema") or SCHEMA),
            paper=str(d.get("paper") or PAPER),
            created_at=float(d.get("created_at") or time.time()),
            notes=str(d.get("notes") or ""),
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
        )

    def is_ready(self) -> bool:
        return (
            self.status == STATUS_READY
            and bool(self.localization.targets or self.localization.steps)
            and bool(self.resolution.steps)
        )

    def all_steps(self) -> list[PhaseStep]:
        return list(self.localization.steps) + list(self.resolution.steps)


# ── tokenization / scoring ──────────────────────────────────────────────────


def tokenize_issue(text: str) -> set[str]:
    """Lowercase tokens from issue text (identifiers + words)."""
    raw = str(text or "")
    toks = {m.group(0).lower() for m in _TOKEN_RE.finditer(raw)}
    # Split snake/camel-ish pieces further
    extra: set[str] = set()
    for t in list(toks):
        for part in re.split(r"[_\-.]+", t):
            if len(part) > 1:
                extra.add(part)
        # camelCase split
        for part in re.findall(r"[a-z]+|[A-Z][a-z]*", t):
            if len(part) > 1:
                extra.add(part.lower())
    toks |= extra
    # Drop ultra-common stopwords that add noise to path scoring
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "into",
        "when",
        "then",
        "than",
        "have",
        "been",
        "will",
        "should",
        "could",
        "would",
        "must",
        "also",
        "only",
        "just",
        "file",
        "files",
        "code",
        "issue",
        "error",
        "bug",
        "fix",
        "implement",
        "add",
        "update",
        "please",
        "need",
        "needs",
        "using",
        "module",
        "function",
        "class",
        "test",
        "tests",
    }
    return {t for t in toks if t not in stop and len(t) > 1}


def _path_tokens(rel: str) -> set[str]:
    p = Path(rel)
    parts: list[str] = []
    for part in p.parts:
        parts.append(part)
        stem = Path(part).stem
        if stem != part:
            parts.append(stem)
        for piece in re.split(r"[_\-.]+", stem):
            if piece:
                parts.append(piece)
    return {x.lower() for x in parts if len(x) > 1}


def score_path(rel_path: str, issue_tokens: set[str]) -> tuple[float, str]:
    """Lexical score of a relative path against issue tokens + short reason.

    Root/suffix priors only apply after a real token match so a nonempty repo
    cannot manufacture localization targets for unrelated issues.
    """
    if not issue_tokens:
        return 0.0, "no issue tokens"
    ptoks = _path_tokens(rel_path)
    if not ptoks:
        return 0.0, "empty path tokens"
    score = 0.0
    matched: list[str] = []
    for t in issue_tokens:
        if t in ptoks:
            score += 3.0
            matched.append(t)
            continue
        for pt in ptoks:
            if t in pt or pt in t:
                score += 1.0
                matched.append(f"{t}~{pt}")
                break
    if not matched:
        # No lexical evidence → not a localization target
        return 0.0, "no token match"
    # Prefer source over docs slightly when scores equal later (tie-break only)
    lower = rel_path.replace("\\", "/").lower()
    if lower.startswith("src/"):
        score += 0.3
    elif lower.startswith("tests/"):
        score += 0.2
    elif lower.startswith("docs/"):
        score += 0.05
    if Path(rel_path).suffix.lower() in {".py", ".ts", ".go", ".rs"}:
        score += 0.1
    reason = "match:" + ",".join(matched[:6])
    return score, reason


# ── localization (phase 1) ──────────────────────────────────────────────────


def _iter_candidate_paths(
    root: Path,
    *,
    search_roots: Sequence[str] = DEFAULT_SEARCH_ROOTS,
    max_files: int = 4000,
) -> list[str]:
    """Walk repo for candidate relative paths (read-only)."""
    root = Path(root).resolve()
    out: list[str] = []
    roots = list(search_roots) if search_roots else list(DEFAULT_SEARCH_ROOTS)
    # If none of the preferred roots exist, scan top-level files only
    existing = [r for r in roots if (root / r).is_dir()]
    if not existing:
        for p in sorted(root.iterdir()):
            if p.is_file() and p.suffix.lower() in _CODE_SUFFIXES:
                out.append(p.name)
            if len(out) >= max_files:
                break
        return out

    for rel_root in existing:
        base = root / rel_root
        for dirpath, dirnames, filenames in _walk_safe(base):
            # prune in-place; sort for deterministic walk / max_files cap
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d not in _SKIP_DIR_NAMES and not d.startswith(".")
            )
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                suf = Path(fn).suffix.lower()
                if suf and suf not in _CODE_SUFFIXES:
                    continue
                full = Path(dirpath) / fn
                try:
                    rel = str(full.relative_to(root)).replace("\\", "/")
                except ValueError:
                    continue
                out.append(rel)
                if len(out) >= max_files:
                    return out
    return out


def _walk_safe(base: Path):
    """os.walk-like generator that tolerates permission errors."""
    import os

    try:
        yield from os.walk(base)
    except OSError:
        return


def localize(
    issue: str,
    *,
    workdir: Optional[Path | str] = None,
    search_roots: Sequence[str] = DEFAULT_SEARCH_ROOTS,
    max_targets: int = 8,
    max_files: int = 4000,
    hints: Optional[Sequence[str]] = None,
) -> PlanPhase:
    """Phase 1: identify issue-relevant files/modules (no mutations).

    Offline heuristic: rank paths by token overlap with the issue text.
    *hints* (explicit paths from the issue or caller) are boosted.
    """
    issue = str(issue or "").strip()
    if not issue:
        raise SweAdeptPlanError("issue/task must be non-empty for localization")

    root = Path(workdir or Path.cwd()).resolve()
    tokens = tokenize_issue(issue)
    # Also pull explicit path-like fragments from the issue
    path_hints = list(hints or [])
    for m in re.finditer(
        r"(?:src|tests|docs|lib|pkg)/[A-Za-z0-9_./\-]+\.[A-Za-z0-9]+",
        issue,
    ):
        path_hints.append(m.group(0).replace("\\", "/"))
    for m in re.finditer(r"`([^`\n]{3,120})`", issue):
        frag = m.group(1).strip()
        if "/" in frag or frag.endswith((".py", ".md", ".ts", ".go")):
            path_hints.append(frag.replace("\\", "/"))

    candidates = _iter_candidate_paths(
        root, search_roots=search_roots, max_files=int(max_files)
    )
    # Ensure explicit *safe* hints are candidates even if outside walk
    safe_hints: list[str] = []
    for h in path_hints:
        cleaned = safe_plan_path(str(h).strip())
        if cleaned and cleaned != "(unlocalized)":
            safe_hints.append(cleaned)
            if cleaned not in candidates:
                candidates.append(cleaned)

    ranked: list[LocalizationHit] = []
    hint_set = set(safe_hints)
    for rel in candidates:
        cleaned_rel = safe_plan_path(rel)
        if not cleaned_rel or cleaned_rel == "(unlocalized)":
            continue
        sc, reason = score_path(cleaned_rel, tokens)
        if cleaned_rel in hint_set:
            # Explicit path hints still need path to be repo-shaped; boost only
            # when the path appears under workdir or already scored as a match.
            if sc > 0 or (root / cleaned_rel).exists():
                sc += 5.0
                reason = (reason + ";explicit_hint") if reason else "explicit_hint"
        if sc <= 0:
            continue
        kind = "module" if cleaned_rel.endswith("__init__.py") else "file"
        if cleaned_rel.endswith("/"):
            kind = "dir"
        ranked.append(
            LocalizationHit(path=cleaned_rel, score=sc, kind=kind, reason=reason)
        )
    ranked.sort(key=lambda h: (-h.score, h.path))
    top = ranked[: max(1, int(max_targets))] if ranked else []

    steps: list[PhaseStep] = [
        PhaseStep(
            id=1,
            phase=PHASE_LOCALIZATION,
            action="locate.scan",
            args={
                "search_roots": list(search_roots),
                "n_candidates": len(candidates),
            },
            rationale="enumerate candidate files under search roots (read-only)",
        ),
        PhaseStep(
            id=2,
            phase=PHASE_LOCALIZATION,
            action="locate.rank",
            args={
                "tokens": sorted(tokens)[:40],
                "max_targets": int(max_targets),
            },
            rationale="score paths by issue-token affinity (agent-directed focus)",
        ),
    ]
    for i, hit in enumerate(top, start=3):
        steps.append(
            PhaseStep(
                id=i,
                phase=PHASE_LOCALIZATION,
                action="locate.confirm",
                args={"path": hit.path, "score": hit.score},
                rationale=hit.reason or f"score={hit.score:.1f}",
                target=hit.path,
            )
        )

    status = STATUS_READY if top else STATUS_DRAFT
    notes = (
        f"localized {len(top)} target(s) from {len(candidates)} candidate(s)"
        if top
        else "no path matches; resolution will use issue-only fallback"
    )
    return PlanPhase(
        name=PHASE_LOCALIZATION,
        status=status,
        steps=steps,
        targets=[h.path for h in top],
        hits=top,
        notes=notes,
    )


# ── resolution (phase 2) ────────────────────────────────────────────────────


def _resolution_actions(issue: str) -> list[str]:
    """Pick ordered resolution action family from issue verbs."""
    low = (issue or "").lower()
    actions = ["resolve.read", "resolve.edit"]
    if any(k in low for k in ("test", "pytest", "verify", "assert", "ci")):
        actions.append("resolve.test")
    else:
        # Default SWE loop still ends with a verification step
        actions.append("resolve.verify")
    if any(k in low for k in ("commit", "pr", "pull request", "branch")):
        actions.append("resolve.checkpoint")
    # Ensure at least edit intent when fix/implement words present
    if not any(k in low for k in _RESOLUTION_INTENTS):
        # still fine — structure is the point
        pass
    return actions


def plan_resolution(
    issue: str,
    targets: Sequence[str],
    *,
    max_steps: int = 12,
    tools: Optional[Iterable[Any]] = None,
) -> PlanPhase:
    """Phase 2: structured fix plan against localized targets (no execution).

    Emits a full action lifecycle (read→edit→verify/test[…]) per covered
    target. ``max_steps`` budgets whole target units so a target is never cut
    mid-lifecycle. ``resolution.targets`` lists only targets that received steps.
    """
    issue = str(issue or "").strip()
    if not issue:
        raise SweAdeptPlanError("issue/task must be non-empty for resolution")

    targets_list: list[str] = []
    for t in targets or []:
        cleaned = safe_plan_path(str(t).strip()) if str(t).strip() else None
        if cleaned and cleaned != "(unlocalized)" and cleaned not in targets_list:
            targets_list.append(cleaned)
    if not targets_list:
        # Fallback single synthetic target so resolution still has structure
        targets_list = ["(unlocalized)"]

    actions = _resolution_actions(issue)
    per_target = max(1, len(actions))
    budget = max(1, int(max_steps))
    # Need at least one full lifecycle for mark_ready. When the budget is
    # smaller than one lifecycle, still emit a single complete lifecycle for
    # the first target (honour the structural minimum) rather than zero steps
    # with a misleading "resolution phase has no steps" failure.
    if budget < per_target:
        max_targets_covered = 1
    else:
        max_targets_covered = max(1, budget // per_target)
    covered = targets_list[:max_targets_covered]
    dropped = targets_list[max_targets_covered:]

    steps: list[PhaseStep] = []
    sid = 1
    for path in covered:
        for action in actions:
            rationale = {
                "resolve.read": f"inspect localized target before edit: {path}",
                "resolve.edit": f"apply minimal fix at localized target: {path}",
                "resolve.test": f"run tests covering localized target: {path}",
                "resolve.verify": f"verify issue resolved for: {path}",
                "resolve.checkpoint": f"checkpoint code state after edit: {path}",
            }.get(action, f"{action} on {path}")
            steps.append(
                PhaseStep(
                    id=sid,
                    phase=PHASE_RESOLUTION,
                    action=action,
                    args={"path": path, "issue": issue[:200]},
                    rationale=rationale,
                    target=path if path != "(unlocalized)" else "",
                )
            )
            sid += 1

    tool_names: list[str] = []
    for t in tools or []:
        if isinstance(t, str) and t.strip():
            tool_names.append(t.strip())
        elif isinstance(t, dict):
            n = str(t.get("name") or t.get("tool") or "").strip()
            if n:
                tool_names.append(n)

    covered_real = [t for t in covered if t != "(unlocalized)"]
    notes = (
        f"resolution over {len(covered_real)} target(s), {len(steps)} step(s)"
        f" (lifecycle={per_target}/target)"
    )
    if dropped:
        notes += f"; dropped {len(dropped)} target(s) over budget"
    if tool_names:
        notes += f"; tools={','.join(tool_names[:8])}"

    return PlanPhase(
        name=PHASE_RESOLUTION,
        status=STATUS_READY if steps else STATUS_DRAFT,
        steps=steps,
        targets=covered_real,
        hits=[],
        notes=notes,
    )


# ── full plan ───────────────────────────────────────────────────────────────


def build_swe_adept_plan(
    issue: str,
    *,
    workdir: Optional[Path | str] = None,
    search_roots: Sequence[str] = DEFAULT_SEARCH_ROOTS,
    max_targets: int = 8,
    max_resolution_steps: int = 12,
    max_files: int = 4000,
    hints: Optional[Sequence[str]] = None,
    tools: Optional[Iterable[Any]] = None,
    auto_ready: bool = True,
    planner: str = "heuristic",
) -> SweAdeptPlan:
    """Build a structured localization → resolution plan (no tool execution)."""
    issue = str(issue or "").strip()
    if not issue:
        raise SweAdeptPlanError("issue/task must be non-empty")

    loc = localize(
        issue,
        workdir=workdir,
        search_roots=search_roots,
        max_targets=max_targets,
        max_files=max_files,
        hints=hints,
    )
    res = plan_resolution(
        issue,
        loc.targets,
        max_steps=max_resolution_steps,
        tools=tools,
    )
    plan = SweAdeptPlan(
        task=issue,
        localization=loc,
        resolution=res,
        status=STATUS_DRAFT,
        planner=str(planner or "heuristic"),
        notes=(
            f"SWE-Adept two-phase plan: localization({len(loc.targets)} targets) "
            f"→ resolution({len(res.steps)} steps)"
        ),
        meta={
            "paper": PAPER,
            "phases": [PHASE_LOCALIZATION, PHASE_RESOLUTION],
            "handoff": "orchestrator",
            "max_targets": int(max_targets),
            "max_resolution_steps": int(max_resolution_steps),
            "workdir": str(Path(workdir).resolve()) if workdir else "",
        },
    )
    if auto_ready and (loc.targets or loc.steps) and res.steps:
        # Ready when we have structure for both phases (targets optional if
        # localization steps exist for observability).
        plan.status = STATUS_READY
        if loc.status == STATUS_DRAFT and loc.steps:
            loc.status = STATUS_READY
        if res.status != STATUS_READY and res.steps:
            res.status = STATUS_READY
    return plan


def parse_swe_plan_json(text: str) -> SweAdeptPlan:
    """Parse LLM / injected JSON into a :class:`SweAdeptPlan`."""
    if not text or not str(text).strip():
        raise SweAdeptPlanError("empty plan text")
    text = str(text).strip()

    def _try(s: str) -> Optional[SweAdeptPlan]:
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            return None
        if isinstance(obj, dict):
            return SweAdeptPlan.from_dict(obj)
        return None

    plan = _try(text)
    if plan is not None:
        return plan
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        plan = _try(m.group(1))
        if plan is not None:
            return plan
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        plan = _try(m.group(0))
        if plan is not None:
            return plan
    raise SweAdeptPlanError("could not parse SWE-Adept plan JSON from text")


def mark_ready(plan: SweAdeptPlan, *, require_targets: bool = False) -> SweAdeptPlan:
    """Validate phase separation and mark plan ready (fail-closed on empty).

    Enforces phase tags **and** action purity so injected plans cannot place
    ``resolve.edit`` under localization (or ``locate.*`` under resolution).
    """
    if not plan.task:
        raise SweAdeptPlanError("plan.task required")
    if not plan.localization.steps and not plan.localization.targets:
        raise SweAdeptPlanError("localization phase empty")
    if require_targets and not plan.localization.targets:
        raise SweAdeptPlanError("localization produced no targets")
    if not plan.resolution.steps:
        raise SweAdeptPlanError("resolution phase has no steps")
    # Sanitize localization targets (drop hostile; fail if require_targets)
    clean_targets: list[str] = []
    for t in plan.localization.targets:
        cleaned = safe_plan_path(t)
        if cleaned and cleaned != "(unlocalized)":
            clean_targets.append(cleaned)
    plan.localization.targets = clean_targets
    if require_targets and not plan.localization.targets:
        raise SweAdeptPlanError("localization produced no valid targets")
    # Enforce phase tags + action/prefix purity
    for s in plan.localization.steps:
        if s.phase != PHASE_LOCALIZATION:
            raise SweAdeptPlanError(
                f"localization step {s.id} has phase={s.phase!r}"
            )
        if not (
            s.action.startswith("locate.") or s.action.startswith("localization.")
        ):
            raise SweAdeptPlanError(
                f"localization step {s.id} has non-locate action {s.action!r}"
            )
    for s in plan.resolution.steps:
        if s.phase != PHASE_RESOLUTION:
            raise SweAdeptPlanError(
                f"resolution step {s.id} has phase={s.phase!r}"
            )
        if not (
            s.action.startswith("resolve.") or s.action.startswith("resolution.")
        ):
            raise SweAdeptPlanError(
                f"resolution step {s.id} has non-resolve action {s.action!r}"
            )
    # Require at least one edit/verify style action in resolution for readiness
    res_actions = {s.action for s in plan.resolution.steps}
    if not any(
        a.startswith("resolve.edit")
        or a.startswith("resolve.verify")
        or a.startswith("resolve.test")
        or a.startswith("resolve.patch")
        for a in res_actions
    ):
        raise SweAdeptPlanError(
            "resolution phase lacks edit/verify/test action (incomplete lifecycle)"
        )
    plan.localization.status = STATUS_READY
    plan.resolution.status = STATUS_READY
    plan.status = STATUS_READY
    return plan


def format_brief(plan: SweAdeptPlan) -> str:
    """Human-readable two-phase brief for logs / journal seed."""
    lines = [
        f"SWE-Adept plan ({plan.paper}) status={plan.status} planner={plan.planner}",
        f"task: {plan.task[:160]}",
        f"## {PHASE_LOCALIZATION} ({len(plan.localization.targets)} targets)",
    ]
    for h in plan.localization.hits[:8]:
        lines.append(f"  - {h.path}  score={h.score:.1f}  ({h.reason[:60]})")
    if not plan.localization.hits and plan.localization.targets:
        for t in plan.localization.targets[:8]:
            lines.append(f"  - {t}")
    lines.append(
        f"## {PHASE_RESOLUTION} ({len(plan.resolution.steps)} steps)"
    )
    for s in plan.resolution.steps[:12]:
        tgt = f" @ {s.target}" if s.target else ""
        lines.append(f"  {s.id}. {s.action}{tgt}")
    return "\n".join(lines)


def plan_payload_for_meta(plan: SweAdeptPlan) -> dict[str, Any]:
    """JSON-safe lean payload for envelope / ops meta.

    Step lists are truncated for storage; ``n_*`` counters always reflect the
    full plan totals so envelope top-level counts stay consistent.
    """
    d = plan.to_dict()
    all_loc = [
        s
        for s in (d.get("localization") or {}).get("steps") or []
        if isinstance(s, dict)
    ]
    all_res = [
        s
        for s in (d.get("resolution") or {}).get("steps") or []
        if isinstance(s, dict)
    ]
    n_loc = len(all_loc)
    n_res = len(all_res)
    n_targets = len(d.get("targets") or [])
    lean_loc_steps = [
        {
            "id": s.get("id"),
            "phase": PHASE_LOCALIZATION,
            "action": s.get("action"),
            "target": s.get("target") or "",
            "rationale": (s.get("rationale") or "")[:160],
            "status": s.get("status") or STEP_PENDING,
        }
        for s in all_loc
    ][:20]
    lean_res_steps = [
        {
            "id": s.get("id"),
            "phase": PHASE_RESOLUTION,
            "action": s.get("action"),
            "target": s.get("target") or "",
            "args": {"path": (s.get("args") or {}).get("path")}
            if isinstance(s.get("args"), dict)
            else {},
            "rationale": (s.get("rationale") or "")[:160],
            "status": s.get("status") or STEP_PENDING,
        }
        for s in all_res
    ][:30]
    hits = [
        {
            "path": h.get("path"),
            "score": h.get("score"),
            "kind": h.get("kind"),
            "reason": (h.get("reason") or "")[:120],
        }
        for h in (d.get("localization") or {}).get("hits") or []
        if isinstance(h, dict)
    ][:SUMMARY_TARGETS_CAP]
    targets_full = list(d.get("targets") or [])
    return {
        "schema": d.get("schema") or SCHEMA,
        "paper": d.get("paper") or PAPER,
        "task": d.get("task") or "",
        "status": d.get("status") or STATUS_DRAFT,
        "planner": d.get("planner") or "heuristic",
        "phases": [PHASE_LOCALIZATION, PHASE_RESOLUTION],
        "targets": targets_full[:20],
        "n_targets": n_targets,
        "n_localization_steps": n_loc,
        "n_resolution_steps": n_res,
        "n_steps": n_loc + n_res,
        "localization": {
            "name": PHASE_LOCALIZATION,
            "status": (d.get("localization") or {}).get("status"),
            "targets": targets_full[:20],
            "hits": hits,
            "n_steps": n_loc,
            "steps": lean_loc_steps,
            "notes": (d.get("localization") or {}).get("notes") or "",
        },
        "resolution": {
            "name": PHASE_RESOLUTION,
            "status": (d.get("resolution") or {}).get("status"),
            "n_steps": n_res,
            "steps": lean_res_steps,
            "notes": (d.get("resolution") or {}).get("notes") or "",
        },
        "notes": d.get("notes") or "",
        "brief": format_brief(plan),
        "meta": {
            "handoff": "orchestrator",
            "paper": PAPER,
            "phases": [PHASE_LOCALIZATION, PHASE_RESOLUTION],
        },
    }


def as_tool_plan_steps(plan: SweAdeptPlan) -> list[dict[str, Any]]:
    """Map SWE-Adept phases onto multi_llm_agent-shaped tool plan steps.

    Localization actions stay first; resolution follows. Enables optional
    with_plan handoff while preserving phase tags in step meta/rationale.
    """
    out: list[dict[str, Any]] = []
    sid = 1
    for s in plan.all_steps():
        out.append(
            {
                "id": sid,
                "tool": s.action,
                "args": dict(s.args or {}),
                "rationale": f"[{s.phase}] {s.rationale}"[:200],
                "status": s.status or STEP_PENDING,
                "phase": s.phase,
            }
        )
        sid += 1
    return out


# ── orchestrator soft hook ──────────────────────────────────────────────────


def maybe_build_for_task(
    workdir: Optional[Path | str],
    task_id: str,
    goal: str,
    meta: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """If meta requests SWE-Adept planning, build localization→resolution plan.

    Trigger keys on meta:
      - ``swe_adept`` / ``with_swe_plan`` / ``swe_plan``: truthy

    Optional:
      - ``swe_max_targets`` (int, default 8)
      - ``swe_max_resolution_steps`` (int, default 12)
      - ``swe_search_roots`` (list[str])
      - ``swe_hints`` (list[str] paths)
      - ``swe_plan_text`` / ``swe_plan`` dict: inject instead of heuristic
      - ``swe_require_targets`` (bool): fail closed if localization empty
    """
    if not meta or not isinstance(meta, dict):
        return None
    enabled = bool(
        meta.get("swe_adept")
        or meta.get("with_swe_plan")
        or meta.get("swe_plan") is True
        or (isinstance(meta.get("swe_plan"), dict))
        or meta.get("swe_plan_text")
    )
    # Explicit False disables even if other keys set oddly
    if meta.get("with_swe_plan") is False and meta.get("swe_adept") is False:
        return None
    if not enabled:
        return None

    require_targets = bool(meta.get("swe_require_targets"))
    max_targets = clamp_swe_limit(meta.get("swe_max_targets"), 8)
    max_res = clamp_swe_limit(meta.get("swe_max_resolution_steps"), 12)
    roots = meta.get("swe_search_roots") or list(DEFAULT_SEARCH_ROOTS)
    if not isinstance(roots, (list, tuple)):
        roots = list(DEFAULT_SEARCH_ROOTS)
    hints = meta.get("swe_hints") if isinstance(meta.get("swe_hints"), list) else None

    try:
        injected = meta.get("swe_plan")
        plan_text = meta.get("swe_plan_text")
        if isinstance(injected, dict):
            plan = SweAdeptPlan.from_dict(injected)
            if not plan.task:
                plan.task = str(goal or "")
            plan.planner = plan.planner or "injected"
            # Always validate — do not trust declared status="ready"
            mark_ready(plan, require_targets=require_targets)
        elif plan_text:
            plan = parse_swe_plan_json(str(plan_text))
            if not plan.task:
                plan.task = str(goal or "")
            plan.planner = plan.planner or "injected"
            mark_ready(plan, require_targets=require_targets)
        else:
            plan = build_swe_adept_plan(
                str(goal or ""),
                workdir=workdir,
                search_roots=[str(r) for r in roots],
                max_targets=max_targets,
                max_resolution_steps=max_res,
                hints=hints,
                auto_ready=True,
            )
            if require_targets and not plan.localization.targets:
                raise SweAdeptPlanError(
                    "localization produced no targets (swe_require_targets)"
                )
            # Re-validate invariants even when auto_ready already set status
            mark_ready(plan, require_targets=require_targets)
    except SweAdeptPlanError as e:
        return {
            "ok": False,
            "schema": SCHEMA,
            "paper": PAPER,
            "task_id": str(task_id or ""),
            "error": str(e),
            "status": STATUS_FAILED,
        }

    payload = plan_payload_for_meta(plan)
    return {
        "ok": True,
        "schema": SCHEMA,
        "paper": PAPER,
        "task_id": str(task_id or ""),
        "status": plan.status,
        "n_targets": len(plan.localization.targets),
        "n_localization_steps": len(plan.localization.steps),
        "n_resolution_steps": len(plan.resolution.steps),
        "targets": list(plan.localization.targets)[:20],
        "brief": payload.get("brief"),
        "plan": payload,
        "phases": [PHASE_LOCALIZATION, PHASE_RESOLUTION],
    }


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="python -m nexus.swe_adept_plan",
        description=(
            "SWE-Adept two-phase planner (localization → resolution); "
            f"{PAPER}"
        ),
    )
    p.add_argument("issue", nargs="?", default="", help="Issue / task text")
    p.add_argument(
        "--path",
        default=".",
        help="Repo root to localize against (default: cwd)",
    )
    p.add_argument("--max-targets", type=int, default=8)
    p.add_argument("--max-resolution-steps", type=int, default=12)
    p.add_argument(
        "--roots",
        default="src,tests,docs",
        help="Comma-separated search roots",
    )
    p.add_argument("--json", action="store_true", help="Print full JSON plan")
    p.add_argument("--brief", action="store_true", help="Print brief only")
    args = p.parse_args(list(argv) if argv is not None else None)

    issue = str(args.issue or "").strip()
    if not issue:
        issue = "Implement structured localization and resolution planning"
    roots = [r.strip() for r in str(args.roots).split(",") if r.strip()]
    plan = build_swe_adept_plan(
        issue,
        workdir=args.path,
        search_roots=roots or list(DEFAULT_SEARCH_ROOTS),
        max_targets=int(args.max_targets),
        max_resolution_steps=int(args.max_resolution_steps),
    )
    if args.brief and not args.json:
        print(format_brief(plan))
        return 0
    if args.json:
        print(plan.to_json())
        return 0
    print(format_brief(plan))
    print()
    print(plan.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SCHEMA",
    "PAPER",
    "PHASE_LOCALIZATION",
    "PHASE_RESOLUTION",
    "SUMMARY_TARGETS_CAP",
    "SweAdeptPlanError",
    "LocalizationHit",
    "PhaseStep",
    "PlanPhase",
    "SweAdeptPlan",
    "clamp_swe_limit",
    "sanitize_plan_path",
    "safe_plan_path",
    "tokenize_issue",
    "score_path",
    "localize",
    "plan_resolution",
    "build_swe_adept_plan",
    "parse_swe_plan_json",
    "mark_ready",
    "format_brief",
    "plan_payload_for_meta",
    "as_tool_plan_steps",
    "maybe_build_for_task",
    "main",
]
