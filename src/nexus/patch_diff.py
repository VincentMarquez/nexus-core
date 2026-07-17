"""Structural PatchDiff preflight for apply claims (arXiv 2503.15223).

Paper: *Are "Solved Issues" in SWE-bench Really Solved Correctly?*
  https://arxiv.org/abs/2503.15223v2

  SWE-bench "pass" can hide incorrect patches (test-only edits, under-scoped
  fixes, or divergence from a known-good gold). This module is a **structural
  preflight** inspired by PatchDiff: it compares candidate vs reference patch
  *shape* (paths, test-only, file-set overlap, line fingerprints) offline.
  It does **not** execute differentiating tests or claim behavioral
  equivalence (see paper §3.2 for the full PatchDiff pipeline).

GitHub pattern (shape only — not a vendored tree):
  wshobson/agents — single-source Markdown marketplace of plugins with
  named, validated building blocks. Here we keep a **check marketplace**:
  a single catalog of named differential checks (plugins) that can be
  listed, validated, and selectively enabled — same discover/validate
  shape as ``marketplace.py``, without loading upstream trees.

Novel hybrid (portfolio cross_pattern
``novel:arxiv:2503.15223v2+wshobson/agents``):

  marketplace check catalog (named plugins)
                │
                ▼
         ┌──────────────────┐   parse unified diffs
         │    PatchDiff     │ ──► compare candidate vs reference
         │  (claim_verify)  │     flag test-only / empty / diverge
         └──────────────────┘
                │
                └── claim_verify.attach report (soft) or fail-closed (hard)

Offline-first: pure text/structure. No network, no test execution harness.
Schema: ``nexus.patch_diff/v1``
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

SCHEMA = "nexus.patch_diff/v1"
PAPER = "arxiv:2503.15223v2"
PAPER_TITLE = 'Are "Solved Issues" in SWE-bench Really Solved Correctly?'
SOURCE_PATTERN = "wshobson/agents"

# Marketplace surface ids (single source for catalog_self_check).
VALID_SURFACES: tuple[str, ...] = (
    "agent",
    "skill",
    "command",
    "verify",
    "system",
)

# Path heuristics (SWE-bench style red flags).
# Dir segments: tests/, test/, __tests__/, testdata/ only — not bare
# "spec"/"fixtures"/"testing" (those false-positive on production modules).
# Filenames: test_*.py, *_test.*, *Test.*, *.test.*, *.spec.*
_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|testdata)(/|$)|"
    r"(^|/)test_[^/]+$|"
    r"(^|/)[^/]+_test\.[^/]+$|"
    r"(^|/)[^/]+Test\.[^/]+$|"
    r"(^|/).*\.test\.[^/]+$|"
    r"(^|/).*\.spec\.[^/]+$",
    re.I,
)
# Optional a/b prefix; strip trailing tab+timestamp (diff -u style).
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
_PLUS_FILE_RE = re.compile(r"^\+\+\+ (?:[ab]/)?(?P<path>[^\t]+?)(?:\t.*)?$")
_MINUS_FILE_RE = re.compile(r"^--- (?:[ab]/)?(?P<path>[^\t]+?)(?:\t.*)?$")
_HUNK_RE = re.compile(r"^@@ ")

# Verdict ranks (higher = worse). Used when ranking fail thresholds.
VERDICT_EQUIVALENT = "equivalent"
VERDICT_COMPATIBLE = "compatible"
VERDICT_DIVERGENT = "divergent"
VERDICT_SUSPICIOUS = "suspicious"
VERDICT_EMPTY = "empty"
VERDICT_SKIP = "skip"

_VERDICT_RANK = {
    VERDICT_EQUIVALENT: 0,
    VERDICT_COMPATIBLE: 1,
    VERDICT_SKIP: 2,
    VERDICT_DIVERGENT: 3,
    VERDICT_SUSPICIOUS: 4,
    VERDICT_EMPTY: 5,
}


class PatchDiffError(ValueError):
    """Invalid patch payload for differential testing."""


# ── Marketplace-style check catalog (wshobson pattern) ─────────────────────


@dataclass(frozen=True)
class CheckPlugin:
    """One named differential check in the marketplace catalog.

    Mirrors wshobson plugin discovery: id + surface + privilege + notes.
    Checks are pure predicates over structured patch views.
    """

    check_id: str
    display_name: str
    surface: str = "verify"  # see VALID_SURFACES
    severity: str = "warn"  # info | warn | fail
    description: str = ""
    enabled_by_default: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "display_name": self.display_name,
            "surface": self.surface,
            "severity": self.severity,
            "description": self.description,
            "enabled_by_default": self.enabled_by_default,
        }


# Single source of truth for differential checks (marketplace catalog).
CHECK_CATALOG: dict[str, CheckPlugin] = {
    "empty_patch": CheckPlugin(
        check_id="empty_patch",
        display_name="Empty patch",
        severity="fail",
        description="Candidate has no file changes (empty or whitespace-only).",
    ),
    "test_only": CheckPlugin(
        check_id="test_only",
        display_name="Test-only changes",
        severity="fail",
        description=(
            "Candidate only touches test/fixture paths — classic SWE-bench "
            "false-pass risk (arXiv 2503.15223)."
        ),
    ),
    "no_production": CheckPlugin(
        check_id="no_production",
        display_name="No production files",
        severity="warn",
        description="No non-test source files appear in the candidate patch.",
    ),
    "file_set_mismatch": CheckPlugin(
        check_id="file_set_mismatch",
        display_name="File-set mismatch",
        severity="warn",
        description="Candidate and reference touch disjoint or weakly overlapping files.",
    ),
    "missing_reference_files": CheckPlugin(
        check_id="missing_reference_files",
        display_name="Missing reference files",
        severity="warn",
        description="Candidate omits files present in the reference/gold patch.",
    ),
    "extra_files": CheckPlugin(
        check_id="extra_files",
        display_name="Extra files vs reference",
        severity="info",
        description="Candidate edits files not present in the reference patch.",
    ),
    "content_divergence": CheckPlugin(
        check_id="content_divergence",
        display_name="Content divergence",
        severity="warn",
        description="Same files, different hunk fingerprints vs reference.",
    ),
    "identical_reference": CheckPlugin(
        check_id="identical_reference",
        display_name="Identical to reference",
        severity="info",
        description=(
            "Candidate body fingerprints match the reference "
            "(requires at least one non-empty content fingerprint)."
        ),
        enabled_by_default=True,
    ),
    "reference_unparseable": CheckPlugin(
        check_id="reference_unparseable",
        display_name="Reference unparseable",
        severity="fail",
        description=(
            "A reference/gold patch string was provided but parsed to an "
            "empty view (corrupt/truncated/non-diff text)."
        ),
    ),
}


def list_checks(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    """List marketplace check plugins (discover surface)."""
    out: list[dict[str, Any]] = []
    for plugin in CHECK_CATALOG.values():
        if enabled_only and not plugin.enabled_by_default:
            continue
        out.append(plugin.to_dict())
    return sorted(out, key=lambda r: r["check_id"])


def validate_check_ids(check_ids: Sequence[str]) -> list[str]:
    """Return unknown check ids (empty list ⇒ valid catalog selection)."""
    unknown: list[str] = []
    for cid in check_ids:
        key = str(cid or "").strip()
        if key and key not in CHECK_CATALOG:
            unknown.append(key)
    return unknown


def catalog_self_check() -> dict[str, Any]:
    """Structural gate over the check marketplace (wshobson validate shape)."""
    issues: list[str] = []
    for cid, plugin in CHECK_CATALOG.items():
        if plugin.check_id != cid:
            issues.append(f"id_mismatch:{cid}")
        if plugin.severity not in ("info", "warn", "fail"):
            issues.append(f"bad_severity:{cid}")
        if plugin.surface not in VALID_SURFACES:
            issues.append(f"bad_surface:{cid}")
    return {
        "schema": SCHEMA,
        "ok": not issues,
        "count": len(CHECK_CATALOG),
        "issues": issues,
        "checks": [p.check_id for p in CHECK_CATALOG.values()],
    }


# ── Unified-diff parse ─────────────────────────────────────────────────────


@dataclass
class FileChange:
    """One file touched by a unified diff."""

    path: str
    is_test: bool = False
    added_lines: int = 0
    removed_lines: int = 0
    hunk_count: int = 0
    # Stable fingerprint of +/- content lines (order-preserving).
    content_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "is_test": self.is_test,
            "added_lines": self.added_lines,
            "removed_lines": self.removed_lines,
            "hunk_count": self.hunk_count,
            "content_fingerprint": self.content_fingerprint,
        }


@dataclass
class PatchView:
    """Structured view of a unified (or free-form) patch."""

    files: dict[str, FileChange] = field(default_factory=dict)
    raw_sha256: str = ""
    empty: bool = True
    source_label: str = ""

    @property
    def paths(self) -> set[str]:
        return set(self.files.keys())

    @property
    def test_paths(self) -> set[str]:
        return {p for p, f in self.files.items() if f.is_test}

    @property
    def production_paths(self) -> set[str]:
        return {p for p, f in self.files.items() if not f.is_test}

    def to_dict(self) -> dict[str, Any]:
        return {
            "empty": self.empty,
            "source_label": self.source_label,
            "raw_sha256": self.raw_sha256,
            "file_count": len(self.files),
            "test_file_count": len(self.test_paths),
            "production_file_count": len(self.production_paths),
            "paths": sorted(self.paths),
            "test_paths": sorted(self.test_paths),
            "production_paths": sorted(self.production_paths),
            "files": {p: f.to_dict() for p, f in sorted(self.files.items())},
        }


def is_test_path(path: str) -> bool:
    """Heuristic: path looks like a test/fixture file."""
    p = str(path or "").replace("\\", "/").strip()
    if not p:
        return False
    return bool(_TEST_PATH_RE.search(p))


def _normalize_path(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def parse_unified_diff(
    text: str | None,
    *,
    source_label: str = "candidate",
) -> PatchView:
    """Parse a unified diff into a :class:`PatchView`.

    Tolerates free-form text: ``diff --git``, ``+++ b/path``, or bare
    ``--- a/`` / ``+++ b/`` headers. Non-diff payloads yield an empty view
    (callers treat empty as a red flag when a patch was expected).
    """
    raw = text if isinstance(text, str) else ""
    view = PatchView(
        raw_sha256=_sha256_text(raw) if raw else "",
        source_label=source_label,
        empty=True,
    )
    if not raw.strip():
        return view

    current: Optional[str] = None
    in_hunk = False
    content_bufs: dict[str, list[str]] = {}

    def _ensure(path: str) -> FileChange:
        path = _normalize_path(path)
        if path not in view.files:
            view.files[path] = FileChange(path=path, is_test=is_test_path(path))
            content_bufs[path] = []
        return view.files[path]

    def _plausible_header_path(path: str) -> bool:
        """Reject mid-hunk noise like ``+++ i`` while allowing real paths."""
        p = (path or "").strip()
        if not p:
            return False
        if p == "/dev/null":
            return True
        if "/" in p or "\\" in p:
            return True
        # Bare filename with extension (Makefile-less single-segment sources).
        base = p.rsplit("/", 1)[-1]
        return "." in base

    for line in raw.splitlines():
        m_git = _DIFF_HEADER_RE.match(line)
        if m_git:
            in_hunk = False
            current = _normalize_path(m_git.group("b") or m_git.group("a"))
            _ensure(current)
            continue
        m_plus = _PLUS_FILE_RE.match(line)
        if m_plus:
            path = m_plus.group("path").strip()
            # Outside hunks always accept; inside hunks only path-like headers
            # (multi-file bare diffs restart; ``+++ i`` content stays content).
            if path and (not in_hunk or _plausible_header_path(path)):
                in_hunk = False
                if path != "/dev/null":
                    current = _normalize_path(path)
                    _ensure(current)
                continue
        m_minus = _MINUS_FILE_RE.match(line)
        if m_minus:
            path = m_minus.group("path").strip()
            if path and (not in_hunk or _plausible_header_path(path)):
                in_hunk = False
                if path != "/dev/null" and current is None:
                    current = _normalize_path(path)
                    _ensure(current)
                elif path != "/dev/null" and in_hunk is False and current is not None:
                    # New file section in multi-file diff: switch current on +++ usually.
                    pass
                continue
        if _HUNK_RE.match(line):
            in_hunk = True
            if current:
                _ensure(current).hunk_count += 1
            continue
        if current is None:
            continue
        fc = _ensure(current)
        if line.startswith("+") and not line.startswith("+++"):
            fc.added_lines += 1
            content_bufs[current].append(line)
        elif line.startswith("-") and not line.startswith("---"):
            fc.removed_lines += 1
            content_bufs[current].append(line)

    for path, buf in content_bufs.items():
        if path in view.files:
            view.files[path].content_fingerprint = _sha256_text("\n".join(buf))[:16]

    view.empty = len(view.files) == 0
    return view


def parse_file_list(
    paths: Sequence[str] | None,
    *,
    source_label: str = "candidate",
) -> PatchView:
    """Build a PatchView from an explicit file path list (no hunk bodies)."""
    view = PatchView(source_label=source_label, empty=True)
    if not paths:
        return view
    for raw in paths:
        path = _normalize_path(str(raw or ""))
        if not path:
            continue
        view.files[path] = FileChange(path=path, is_test=is_test_path(path))
    view.empty = len(view.files) == 0
    view.raw_sha256 = _sha256_text("\n".join(sorted(view.paths)))
    return view


# ── Differential compare ───────────────────────────────────────────────────


def _default_check_ids() -> list[str]:
    return [c.check_id for c in CHECK_CATALOG.values() if c.enabled_by_default]


def _finding(
    check_id: str,
    *,
    triggered: bool,
    detail: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    plugin = CHECK_CATALOG.get(check_id)
    row: dict[str, Any] = {
        "check_id": check_id,
        "triggered": bool(triggered),
        "severity": plugin.severity if plugin else "warn",
        "display_name": plugin.display_name if plugin else check_id,
        "detail": detail,
    }
    if extra:
        row.update(extra)
    return row


def compare_patches(
    candidate: str | PatchView | None,
    reference: str | PatchView | None = None,
    *,
    checks: Optional[Sequence[str]] = None,
    candidate_files: Optional[Sequence[str]] = None,
    reference_files: Optional[Sequence[str]] = None,
    min_overlap: float = 0.0,
) -> dict[str, Any]:
    """Differentially compare *candidate* vs optional *reference* patch.

    Parameters
    ----------
    candidate / reference:
        Unified-diff text or pre-parsed :class:`PatchView`.
    checks:
        Subset of marketplace check ids (default: all enabled_by_default).
    candidate_files / reference_files:
        Optional explicit path lists used when diff text is absent.
    min_overlap:
        When a reference exists, require Jaccard file-set overlap ≥ this
        value or flag ``file_set_mismatch``. When *min_overlap* > 0 and
        the threshold is breached (or the gold is unparseable), report
        ``ok=False`` so hard-mode claim_verify can refuse apply.

    Returns a ``nexus.patch_diff/v1`` report with ``ok``, ``verdict``, and
    per-check findings. Does not raise on red flags (callers decide hard/soft).
    """
    check_ids = list(checks) if checks is not None else _default_check_ids()
    unknown = validate_check_ids(check_ids)
    if unknown:
        raise PatchDiffError(f"unknown patch_diff checks: {unknown}")

    # Resolve views
    if isinstance(candidate, PatchView):
        cand = candidate
    elif candidate_files and not (isinstance(candidate, str) and candidate.strip()):
        cand = parse_file_list(candidate_files, source_label="candidate")
    else:
        cand = parse_unified_diff(
            candidate if isinstance(candidate, str) else None,
            source_label="candidate",
        )
        if cand.empty and candidate_files:
            cand = parse_file_list(candidate_files, source_label="candidate")

    ref: Optional[PatchView] = None
    ref_unparseable = False
    if isinstance(reference, PatchView):
        ref = reference
    elif reference is not None or reference_files:
        had_ref_text = isinstance(reference, str) and str(reference).strip()
        if reference_files and not had_ref_text:
            ref = parse_file_list(reference_files, source_label="reference")
        else:
            ref = parse_unified_diff(
                reference if isinstance(reference, str) else None,
                source_label="reference",
            )
            if ref.empty and reference_files:
                ref = parse_file_list(reference_files, source_label="reference")
            elif ref.empty and had_ref_text:
                # Gold string provided but not a parseable unified diff.
                ref_unparseable = True

    findings: list[dict[str, Any]] = []
    flags: list[str] = []

    def run(cid: str) -> bool:
        return cid in check_ids

    # --- empty_patch ---
    if run("empty_patch"):
        trig = cand.empty
        findings.append(
            _finding(
                "empty_patch",
                triggered=trig,
                detail="candidate has no file changes" if trig else "candidate has files",
            )
        )
        if trig:
            flags.append("empty_patch")

    # --- test_only ---
    if run("test_only"):
        trig = (not cand.empty) and (len(cand.production_paths) == 0) and (
            len(cand.test_paths) > 0
        )
        findings.append(
            _finding(
                "test_only",
                triggered=trig,
                detail=(
                    f"only test paths: {sorted(cand.test_paths)[:12]}"
                    if trig
                    else "has production paths or empty"
                ),
                extra={"test_paths": sorted(cand.test_paths)},
            )
        )
        if trig:
            flags.append("test_only")

    # --- no_production ---
    if run("no_production"):
        trig = (not cand.empty) and len(cand.production_paths) == 0
        findings.append(
            _finding(
                "no_production",
                triggered=trig,
                detail="no production files in candidate" if trig else "production files present",
            )
        )
        if trig and "test_only" not in flags:
            flags.append("no_production")

    # --- reference_unparseable (before other ref checks) ---
    if run("reference_unparseable"):
        trig = ref_unparseable
        findings.append(
            _finding(
                "reference_unparseable",
                triggered=trig,
                detail=(
                    "reference/gold text provided but not a parseable unified diff"
                    if trig
                    else (
                        "no unparseable reference"
                        if (ref is not None and not ref.empty) or reference is None
                        else "reference empty without corrupt text"
                    ),
                ),
            )
        )
        if trig:
            flags.append("reference_unparseable")

    # Reference-aware checks
    overlap = 0.0
    jaccard = 0.0
    shared: set[str] = set()
    only_cand: set[str] = set()
    only_ref: set[str] = set()
    content_divergent_files: list[str] = []
    identical = False
    overlap_breach = False

    if ref is not None and not ref.empty:
        shared = cand.paths & ref.paths
        only_cand = cand.paths - ref.paths
        only_ref = ref.paths - cand.paths
        union = cand.paths | ref.paths
        jaccard = (len(shared) / len(union)) if union else 1.0
        overlap = jaccard
        if min_overlap > 0 and jaccard < float(min_overlap):
            overlap_breach = True

        if run("missing_reference_files"):
            trig = len(only_ref) > 0
            findings.append(
                _finding(
                    "missing_reference_files",
                    triggered=trig,
                    detail=f"missing vs reference: {sorted(only_ref)[:20]}",
                    extra={"missing": sorted(only_ref)},
                )
            )
            if trig:
                flags.append("missing_reference_files")

        if run("extra_files"):
            trig = len(only_cand) > 0
            findings.append(
                _finding(
                    "extra_files",
                    triggered=trig,
                    detail=f"extra vs reference: {sorted(only_cand)[:20]}",
                    extra={"extra": sorted(only_cand)},
                )
            )
            # info severity — do not auto-flag as failure unless requested

        if run("file_set_mismatch"):
            # Weak overlap: no shared files, or below min_overlap when set.
            trig = (len(shared) == 0 and len(union) > 0) or overlap_breach
            findings.append(
                _finding(
                    "file_set_mismatch",
                    triggered=trig,
                    detail=f"jaccard={jaccard:.3f} shared={len(shared)} min_overlap={min_overlap}",
                    extra={
                        "jaccard": round(jaccard, 4),
                        "min_overlap": float(min_overlap),
                        "overlap_breach": overlap_breach,
                        "shared": sorted(shared),
                        "only_candidate": sorted(only_cand),
                        "only_reference": sorted(only_ref),
                    },
                )
            )
            if trig:
                flags.append("file_set_mismatch")

        if run("content_divergence"):
            for path in sorted(shared):
                cfp = cand.files[path].content_fingerprint
                rfp = ref.files[path].content_fingerprint
                # Only compare when both sides have body fingerprints
                if cfp and rfp and cfp != rfp:
                    content_divergent_files.append(path)
            trig = len(content_divergent_files) > 0
            findings.append(
                _finding(
                    "content_divergence",
                    triggered=trig,
                    detail=(
                        f"divergent files: {content_divergent_files[:20]}"
                        if trig
                        else "shared files match fingerprints (or no body)"
                    ),
                    extra={"divergent_files": content_divergent_files},
                )
            )
            if trig:
                flags.append("content_divergence")

        if run("identical_reference"):
            # Path-only / fingerprint-less views must not claim content equality.
            has_body = any(f.content_fingerprint for f in cand.files.values())
            raw_match = (
                has_body
                and (not cand.empty)
                and bool(cand.raw_sha256)
                and cand.raw_sha256 == ref.raw_sha256
            )
            fp_match = (
                has_body
                and cand.paths == ref.paths
                and not content_divergent_files
                and len(only_cand) == 0
                and len(only_ref) == 0
                and not cand.empty
                and all(
                    cand.files[p].content_fingerprint
                    == ref.files[p].content_fingerprint
                    for p in shared
                    if cand.files[p].content_fingerprint
                    or ref.files[p].content_fingerprint
                )
            )
            identical = bool(raw_match or fp_match)
            findings.append(
                _finding(
                    "identical_reference",
                    triggered=identical,
                    detail=(
                        "candidate matches reference (body fingerprints)"
                        if identical
                        else (
                            "path-only match — not equivalent without body"
                            if (not has_body and cand.paths == ref.paths and not cand.empty)
                            else "not identical"
                        )
                    ),
                )
            )
    else:
        # No usable reference — mark reference checks as not run (skip).
        # Unparseable gold already emitted its own finding above.
        skip_detail = (
            "reference provided but unparseable"
            if ref_unparseable
            else "no reference patch provided"
        )
        for cid in (
            "missing_reference_files",
            "extra_files",
            "file_set_mismatch",
            "content_divergence",
            "identical_reference",
        ):
            if run(cid):
                findings.append(
                    _finding(
                        cid,
                        triggered=False,
                        detail=skip_detail,
                        extra={"skipped": True, "reference_unparseable": ref_unparseable},
                    )
                )
        # Explicit min_overlap with corrupt gold is a policy fail-open to close.
        if ref_unparseable and min_overlap > 0:
            overlap_breach = True

    # Verdict synthesis
    verdict = VERDICT_COMPATIBLE
    if cand.empty:
        verdict = VERDICT_EMPTY
    elif "test_only" in flags or "no_production" in flags:
        verdict = VERDICT_SUSPICIOUS
    elif identical:
        verdict = VERDICT_EQUIVALENT
    elif any(
        f in flags
        for f in ("content_divergence", "file_set_mismatch", "missing_reference_files")
    ):
        verdict = VERDICT_DIVERGENT
    # Corrupt gold alone does not force empty/suspicious; fail finding sets ok=False.
    # Candidate-only (or unparseable ref) with no structural red flags → compatible.

    # ok: no fail-severity finding, not empty/suspicious, and no min_overlap breach
    fail_triggered = [
        f
        for f in findings
        if f.get("triggered") and f.get("severity") == "fail" and not f.get("skipped")
    ]
    ok = (
        len(fail_triggered) == 0
        and not overlap_breach
        and verdict not in (VERDICT_EMPTY, VERDICT_SUSPICIOUS)
    )

    return {
        "schema": SCHEMA,
        "ok": ok,
        "verdict": verdict,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "flags": flags,
        "findings": findings,
        "checks_run": check_ids,
        "overlap_jaccard": round(overlap, 4),
        "overlap_breach": overlap_breach,
        "min_overlap": float(min_overlap),
        "shared_files": sorted(shared),
        "only_candidate": sorted(only_cand),
        "only_reference": sorted(only_ref),
        "candidate": cand.to_dict(),
        "reference": ref.to_dict() if ref is not None else None,
        "fail_count": len(fail_triggered),
        "warn_count": sum(
            1
            for f in findings
            if f.get("triggered") and f.get("severity") == "warn" and not f.get("skipped")
        ),
        "verdict_rank": _VERDICT_RANK.get(verdict, 99),
    }


def extract_patch_payload(grade: Any) -> dict[str, Any]:
    """Pull candidate/reference patch fields from a grade / claim dict.

    Recognized keys (first hit wins per side) — **explicit** only, to avoid
    attaching bogus patch_diff reports to unrelated grades that carry a
    generic ``files`` or ``diff`` field:

      candidate: patch, candidate_patch, unified_diff, patch_text
      reference: reference_patch, gold_patch, expected_patch, ref_patch
      file lists:  patch_files / changed_files
                   reference_files / gold_files

    List items must be non-empty strings (dicts/None skipped, not stringified).
    """
    if not isinstance(grade, dict):
        return {"has_payload": False}

    def _first_str(*keys: str) -> Optional[str]:
        for k in keys:
            if k in grade and grade[k] is not None:
                v = grade[k]
                if isinstance(v, str) and v.strip():
                    return v
        return None

    def _first_list(*keys: str) -> Optional[list[str]]:
        for k in keys:
            if k in grade and grade[k] is not None:
                v = grade[k]
                if isinstance(v, (list, tuple)) and v:
                    out = [
                        x.strip()
                        for x in v
                        if isinstance(x, str) and x.strip()
                    ]
                    if out:
                        return out
        return None

    # Intentionally omit generic ``diff`` / ``files`` (false positives on grades).
    candidate = _first_str(
        "patch", "candidate_patch", "unified_diff", "patch_text"
    )
    reference = _first_str(
        "reference_patch", "gold_patch", "expected_patch", "ref_patch"
    )
    cand_files = _first_list("patch_files", "changed_files")
    ref_files = _first_list("reference_files", "gold_files")

    has = bool(candidate or reference or cand_files or ref_files)
    return {
        "has_payload": has,
        "candidate": candidate,
        "reference": reference,
        "candidate_files": cand_files,
        "reference_files": ref_files,
    }


def diff_from_grade(
    grade: Any,
    *,
    checks: Optional[Sequence[str]] = None,
    min_overlap: float = 0.0,
) -> Optional[dict[str, Any]]:
    """Run PatchDiff when *grade* carries a patch payload; else return None."""
    payload = extract_patch_payload(grade)
    if not payload.get("has_payload"):
        return None
    return compare_patches(
        payload.get("candidate"),
        payload.get("reference"),
        checks=checks,
        candidate_files=payload.get("candidate_files"),
        reference_files=payload.get("reference_files"),
        min_overlap=min_overlap,
    )


def patch_diff_or_report(
    candidate: str | None = None,
    reference: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Soft wrapper: never raises PatchDiffError for empty inputs."""
    try:
        return compare_patches(candidate, reference, **kwargs)
    except PatchDiffError as e:
        return {
            "schema": SCHEMA,
            "ok": False,
            "verdict": VERDICT_SKIP,
            "flags": ["error"],
            "error": str(e),
            "findings": [],
        }


__all__ = [
    "SCHEMA",
    "PAPER",
    "CHECK_CATALOG",
    "CheckPlugin",
    "FileChange",
    "PatchView",
    "PatchDiffError",
    "VALID_SURFACES",
    "list_checks",
    "validate_check_ids",
    "catalog_self_check",
    "is_test_path",
    "parse_unified_diff",
    "parse_file_list",
    "compare_patches",
    "extract_patch_payload",
    "diff_from_grade",
    "patch_diff_or_report",
]
