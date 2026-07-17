"""Experience Bank — SWE-Exp-shaped repair pattern store.

Paper: *SWE-Exp: Experience-Driven Software Issue Resolution*
https://arxiv.org/abs/2507.23361v2

SWE-Exp accumulates abstracted experiences from past issue resolutions so
agents try proven repair approaches first. This module is a small,
offline-first port of that *shape* for NEXUS:

  issue text / type
        │
        ▼
  classify → issue_type
        │
        ▼
  Experience Bank (success + failure rows)
        │
        ▼
  recommend approaches ranked by smoothed success rate
        │
        ▼
  brief: "If issue type X, try approach Y first"

Storage (append-only JSONL under the project workdir)::

  ``.nexus_state/experience_bank.jsonl``

Runtime state under ``.nexus_state/`` is intentional (persist convention);
callers pass a workdir so tests stay isolated. No network; no secrets.
Pattern only — not a vendored upstream tree.
Schema: ``nexus.experience_bank/v1``

``confidence`` and ``ts`` are stored as metadata for future recency/trust
weighting; v1 Laplace scoring uses success/failure/prior *counts* only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from .persist import append_jsonl, read_jsonl

SCHEMA = "nexus.experience_bank/v1"
ARXIV_ID = "2507.23361v2"
ARXIV_URL = "https://arxiv.org/abs/2507.23361v2"
SOURCE_TITLE = "SWE-Exp: Experience-Driven Software Issue Resolution"

DEFAULT_REL = Path(".nexus_state") / "experience_bank.jsonl"
DEFAULT_RECOMMEND_LIMIT = 5
DEFAULT_LOAD_LIMIT = 200
# Caps for recommend/stats windows (newest rows kept when reverse=False).
RECOMMEND_LOAD_CAP = 5000
STATS_LOAD_CAP = 10000
# Abstracted harvest fallback (no per-repo unique approach strings).
HARVEST_DEFAULT_SUCCESS_APPROACH = (
    "Implement landed via standard tests/verify path"
)

# Outcomes stored on rows.
OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_PRIOR = "prior"  # soft seed / catalog prior (weak evidence)

_VALID_OUTCOMES = frozenset({OUTCOME_SUCCESS, OUTCOME_FAILURE, OUTCOME_PRIOR})

# Lightweight issue-type catalog (aligned with failure_patterns ids where useful).
# Regexes map free-form issue text → issue_type for recommend/record.
# Order encodes priority: first matching rule wins (most-specific catalog first).
ISSUE_TYPE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "missing_dependency",
        "missing dependency",
        (
            r"ModuleNotFoundError",
            r"ImportError",
            r"No module named",
            r"missing dependency",
            r"pip install",
        ),
    ),
    (
        "incorrect_api_usage",
        "incorrect API usage",
        (
            r"unexpected keyword argument",
            r"TypeError:.*argument",
            r"AttributeError:.*object has no attribute",
            r"wrong signature",
            r"not callable",
        ),
    ),
    (
        "test_assertion_failure",
        "test assertion failure",
        (
            r"AssertionError",
            r"FAILED\s+[\w./:-]+",
            r"[1-9]\d* failed",
            r"test failed",
            r"assert .+ ==",
        ),
    ),
    (
        "file_or_path_missing",
        "file or path missing",
        (
            r"FileNotFoundError",
            r"No such file or directory",
            r"ENOENT",
            r"path does not exist",
        ),
    ),
    (
        "syntax_or_parse_error",
        "syntax or parse error",
        (
            r"SyntaxError",
            r"IndentationError",
            r"JSONDecodeError",
            r"invalid syntax",
            r"parse error",
        ),
    ),
    (
        "timeout_or_hang",
        "timeout or hang",
        (r"TimeoutError", r"timed?\s*out", r"deadline exceeded", r"hung"),
    ),
    (
        "permission_or_auth",
        "permission or auth",
        (
            r"PermissionError",
            r"Permission denied",
            r"401\b",
            r"403\b",
            r"Unauthorized",
        ),
    ),
    (
        "budget_or_rate_limit",
        "budget or rate limit",
        (r"rate limit", r"429\b", r"budget exceeded", r"token limit", r"max_tokens"),
    ),
    (
        "policy_or_gate_denied",
        "policy or gate denied",
        (r"policy denied", r"gate denied", r"quality.?gate", r"veto", r"not approved"),
    ),
    (
        "network_or_connectivity",
        "network or connectivity",
        (r"ConnectionError", r"ConnectionRefused", r"Network is unreachable", r"URLError"),
    ),
)

# Soft prior approaches (SWE-Exp: try Y first for issue type X).
# Seeded as outcome=prior so live success/failure can outweigh them.
DEFAULT_PRIORS: tuple[tuple[str, str], ...] = (
    (
        "missing_dependency",
        "Verify imports/deps exist (or add install/check step); fail closed on ModuleNotFoundError.",
    ),
    (
        "incorrect_api_usage",
        "Check function/method signatures against source or stubs before calling; prefer typed adapters.",
    ),
    (
        "test_assertion_failure",
        "Read the failing assertion and expected vs actual; fix the minimal unit under test first.",
    ),
    (
        "file_or_path_missing",
        "Resolve paths under the workdir jail; assert Path.exists() before read/write.",
    ),
    (
        "syntax_or_parse_error",
        "Validate generated code/JSON/YAML with a parser before promotion; keep patches small.",
    ),
    (
        "timeout_or_hang",
        "Set explicit timeouts on subprocess/network tools; fail-fast with partial logs.",
    ),
    (
        "permission_or_auth",
        "Check privilege/auth gates before privileged ops; surface 401/403 as operator blocks.",
    ),
    (
        "budget_or_rate_limit",
        "Respect spend/rate caps; shrink context and batch work before retrying.",
    ),
    (
        "policy_or_gate_denied",
        "Satisfy gate preconditions (review, domain, evidence) before promote/complete.",
    ),
    (
        "network_or_connectivity",
        "Prefer offline fixtures in unit tests; probe once then degrade to cache/heuristic.",
    ),
    (
        "generic_repair",
        "Reproduce with the smallest failing case; change one layer at a time; re-run tests.",
    ),
)


class ExperienceBankError(ValueError):
    """Invalid experience bank input or operation."""


@dataclass
class Experience:
    """One abstracted repair experience (success, failure, or soft prior)."""

    id: str
    issue_type: str
    approach: str
    outcome: str
    abstract: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)
    evidence: str = ""
    confidence: float = 0.5
    repo: str = ""
    run_id: str = ""
    ts: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["schema"] = SCHEMA
        return d

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "Experience":
        tags = row.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]
        try:
            conf = float(row.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        try:
            ts = float(row.get("ts") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        return cls(
            id=str(row.get("id") or ""),
            issue_type=_norm_issue_type(str(row.get("issue_type") or "generic_repair")),
            approach=str(row.get("approach") or "")[:500],
            outcome=_norm_outcome(str(row.get("outcome") or OUTCOME_SUCCESS)),
            abstract=str(row.get("abstract") or "")[:500],
            source=str(row.get("source") or "")[:80],
            tags=[str(t)[:40] for t in tags][:12],
            evidence=str(row.get("evidence") or "")[:400],
            confidence=conf,
            repo=str(row.get("repo") or "")[:120],
            run_id=str(row.get("run_id") or "")[:80],
            ts=ts,
            meta=dict(meta),
        )


@dataclass
class ApproachRank:
    """Ranked repair approach for an issue type."""

    issue_type: str
    approach: str
    score: float
    successes: int = 0
    failures: int = 0
    priors: int = 0
    n: int = 0
    abstract: str = ""
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Paths / normalisation
# ---------------------------------------------------------------------------


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def bank_path(workdir: Optional[Path | str] = None) -> Path:
    """Path to the append-only experience JSONL store."""
    return _root(workdir) / DEFAULT_REL


def _norm_issue_type(raw: str) -> str:
    s = str(raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9_./+-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("._")
    return (s or "generic_repair")[:80]


def _norm_outcome(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if s in _VALID_OUTCOMES:
        return s
    if s in ("ok", "pass", "passed", "success", "succeeded", "true", "1", "win"):
        return OUTCOME_SUCCESS
    if s in ("fail", "failed", "failure", "error", "false", "0", "lose"):
        return OUTCOME_FAILURE
    if s in ("seed", "catalog", "soft", "hint", "default"):
        return OUTCOME_PRIOR
    raise ExperienceBankError(
        f"outcome must be one of {sorted(_VALID_OUTCOMES)} (got {raw!r})"
    )


def _norm_approach(raw: str) -> str:
    text = " ".join(str(raw or "").split())
    if not text:
        raise ExperienceBankError("approach is required")
    return text[:500]


def make_abstract(issue_type: str, approach: str, *, outcome: str = OUTCOME_SUCCESS) -> str:
    """Build the SWE-Exp style rule string."""
    it = _norm_issue_type(issue_type)
    ap = _norm_approach(approach).rstrip(" .;:")
    if outcome == OUTCOME_FAILURE:
        return f"If issue type `{it}`, avoid approach: {ap}"
    return f"If issue type `{it}`, try approach first: {ap}"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_COMPILED_ISSUE: list[tuple[str, tuple[re.Pattern[str], ...]]] | None = None


def _issue_compiled() -> list[tuple[str, tuple[re.Pattern[str], ...]]]:
    global _COMPILED_ISSUE
    if _COMPILED_ISSUE is None:
        out: list[tuple[str, tuple[re.Pattern[str], ...]]] = []
        for issue_id, _label, regexes in ISSUE_TYPE_RULES:
            out.append((issue_id, tuple(re.compile(r, re.I | re.M) for r in regexes)))
        _COMPILED_ISSUE = out
    return _COMPILED_ISSUE


def classify_issue(text: str) -> str:
    """Map free-form issue / error text to a canonical issue_type.

    Rules are ordered by priority; the first matching catalog id wins.
    Unmapped ``failure_patterns`` ids degrade to ``generic_repair`` (no
    orphan issue types without priors).
    """
    if not text or not str(text).strip():
        return "generic_repair"
    blob = str(text)
    for issue_id, patterns in _issue_compiled():
        if any(p.search(blob) for p in patterns):
            return issue_id
    # Reuse failure_patterns catalog when available (optional soft dep).
    try:
        from . import failure_patterns as fp

        pids = fp.classify_text(blob)
        if pids:
            # Map pattern ids → issue types (most are 1:1 after trimming suffixes).
            pid = pids[0]
            mapping = {
                "missing_dependency_check": "missing_dependency",
                "incorrect_api_usage": "incorrect_api_usage",
                "file_or_path_missing": "file_or_path_missing",
                "permission_or_auth": "permission_or_auth",
                "test_assertion_failure": "test_assertion_failure",
                "timeout_or_hang": "timeout_or_hang",
                "syntax_or_parse_error": "syntax_or_parse_error",
                "network_or_connectivity": "network_or_connectivity",
                "budget_or_rate_limit": "budget_or_rate_limit",
                "policy_or_gate_denied": "policy_or_gate_denied",
                "generic_runtime_error": "generic_repair",
            }
            # Unmapped pids must not mint orphan types outside the catalog.
            return mapping.get(pid, "generic_repair")
    except Exception:
        pass
    return "generic_repair"


def list_issue_types() -> list[str]:
    """Known issue types (catalog + generic)."""
    ids = [r[0] for r in ISSUE_TYPE_RULES]
    if "generic_repair" not in ids:
        ids.append("generic_repair")
    return ids


# ---------------------------------------------------------------------------
# Persist / load
# ---------------------------------------------------------------------------


def record(
    workdir: Optional[Path | str] = None,
    *,
    issue_type: str = "",
    approach: str,
    outcome: str = OUTCOME_SUCCESS,
    issue_text: str = "",
    abstract: str = "",
    source: str = "manual",
    tags: Optional[Sequence[str]] = None,
    evidence: str = "",
    confidence: Optional[float] = None,
    repo: str = "",
    run_id: str = "",
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append one abstracted repair experience. Fail-closed on empty approach."""
    ap = _norm_approach(approach)
    oc = _norm_outcome(outcome)
    if issue_type:
        it = _norm_issue_type(issue_type)
    elif issue_text:
        it = classify_issue(issue_text)
    else:
        it = "generic_repair"

    if confidence is None:
        conf = {"success": 0.7, "failure": 0.7, "prior": 0.3}.get(oc, 0.5)
    else:
        try:
            conf = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError) as e:
            raise ExperienceBankError(f"invalid confidence: {confidence!r}") from e

    abs_text = (abstract or "").strip() or make_abstract(it, ap, outcome=oc)
    exp = Experience(
        id=f"exp-{uuid.uuid4().hex[:12]}",
        issue_type=it,
        approach=ap,
        outcome=oc,
        abstract=abs_text[:500],
        source=str(source or "manual")[:80],
        tags=[str(t)[:40] for t in (tags or [])][:12],
        evidence=str(evidence or issue_text or "")[:400],
        confidence=conf,
        repo=str(repo or "")[:120],
        run_id=str(run_id or "")[:80],
        ts=time.time(),
        meta=dict(meta or {}),
    )
    row = exp.to_dict()
    path = bank_path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(path, row)
    return row


def load(
    workdir: Optional[Path | str] = None,
    *,
    limit: int = DEFAULT_LOAD_LIMIT,
    issue_type: Optional[str] = None,
    outcome: Optional[str] = None,
    source: Optional[str] = None,
    reverse: bool = True,
) -> list[dict[str, Any]]:
    """Load experience rows (newest-first by default).

    Skips corrupt lines, rows without an approach, and rows whose stored
    outcome cannot be normalised (fail-open — one foreign/hand-written
    row must not take down filtered reads).

    When *limit* is set and *reverse* is False (oldest-first presentation),
    the **newest** *limit* rows are kept so append-only growth does not
    silently drop recent experience.
    """
    path = bank_path(workdir)
    rows = read_jsonl(path, limit=None, reverse=False)
    out: list[dict[str, Any]] = []
    want_it = _norm_issue_type(issue_type) if issue_type else None
    want_oc: Optional[str] = None
    if outcome is not None and str(outcome).strip() != "":
        want_oc = _norm_outcome(outcome)  # caller filter — fail-closed
    want_src = str(source).strip() if source else None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not row.get("approach"):
            continue
        if want_it and _norm_issue_type(str(row.get("issue_type") or "")) != want_it:
            continue
        if want_oc is not None:
            raw_oc = row.get("outcome")
            if raw_oc is None or str(raw_oc).strip() == "":
                continue
            try:
                row_oc = _norm_outcome(str(raw_oc))
            except ExperienceBankError:
                continue  # unknown/corrupt outcome — skip, do not raise
            if row_oc != want_oc:
                continue
        if want_src and str(row.get("source") or "") != want_src:
            continue
        out.append(row)
    if reverse:
        # Newest-first: reverse then take head.
        out = list(reversed(out))
        if limit is not None and limit >= 0:
            out = out[:limit]
    else:
        # Oldest-first presentation, but keep the *newest* window so
        # recommend/stats do not forget recent lessons at scale.
        if limit is not None and limit >= 0:
            out = out[-limit:] if limit > 0 else []
    return out


def seed_priors(
    workdir: Optional[Path | str] = None,
    *,
    force: bool = False,
    source: str = "catalog_prior",
) -> dict[str, Any]:
    """Seed soft prior approaches once (idempotent unless *force*).

    Priors give recommend() a cold-start ranking: "If issue type X, try Y first".
    Live success/failure rows outweigh priors via Laplace scoring.
    """
    path = bank_path(workdir)
    existing = load(workdir, limit=5000, source=source) if path.is_file() else []
    if existing and not force:
        return {
            "ok": True,
            "seeded": 0,
            "skipped": True,
            "reason": "priors already present",
            "existing": len(existing),
        }
    written = 0
    for issue_type, approach in DEFAULT_PRIORS:
        record(
            workdir,
            issue_type=issue_type,
            approach=approach,
            outcome=OUTCOME_PRIOR,
            source=source,
            confidence=0.3,
            tags=["prior", "swe-exp"],
            evidence="DEFAULT_PRIORS catalog",
        )
        written += 1
    return {"ok": True, "seeded": written, "skipped": False, "path": str(path)}


# ---------------------------------------------------------------------------
# Ranking / recommend
# ---------------------------------------------------------------------------


def _approach_key(approach: str) -> str:
    return " ".join(str(approach or "").lower().split())[:500]


def _score_bucket(successes: int, failures: int, priors: int) -> float:
    """Laplace-smoothed success score with weak prior mass.

    - success counts as +1 evidence for the approach
    - failure counts as +1 evidence against
    - prior counts as +0.25 soft success (catalog hint)

    Note: row ``confidence`` / ``ts`` are metadata-only in v1 (not scored).
    """
    s = float(successes) + 0.25 * float(priors)
    f = float(failures)
    # Laplace α=1 on a Bernoulli: (s+1)/(s+f+2)
    return (s + 1.0) / (s + f + 2.0)


def _row_outcome(row: dict[str, Any]) -> Optional[str]:
    """Normalise a stored row outcome; None if missing/invalid (skip row)."""
    raw = row.get("outcome")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return _norm_outcome(str(raw))
    except ExperienceBankError:
        return None


def _in_memory_priors(issue_type: Optional[str] = None) -> list[dict[str, Any]]:
    """Catalog priors as in-memory rows (no disk write). Optionally filter by type."""
    want = _norm_issue_type(issue_type) if issue_type else None
    out: list[dict[str, Any]] = []
    for i, (issue_t, approach) in enumerate(DEFAULT_PRIORS):
        if want and issue_t != want:
            continue
        out.append(
            {
                "id": f"prior-{i}",
                "issue_type": issue_t,
                "approach": approach,
                "outcome": OUTCOME_PRIOR,
                "abstract": make_abstract(issue_t, approach, outcome=OUTCOME_PRIOR),
                "source": "catalog_prior",
                "confidence": 0.3,
            }
        )
    return out


def _has_success_for(rows: Sequence[dict[str, Any]], issue_type: str) -> bool:
    """True if *rows* contain at least one success for *issue_type*."""
    want = _norm_issue_type(issue_type)
    for row in rows:
        if _norm_issue_type(str(row.get("issue_type") or "")) != want:
            continue
        if _row_outcome(row) == OUTCOME_SUCCESS:
            return True
    return False


def aggregate(
    rows: Sequence[dict[str, Any]],
    *,
    issue_type: Optional[str] = None,
) -> list[ApproachRank]:
    """Aggregate experience rows into ranked approaches."""
    want = _norm_issue_type(issue_type) if issue_type else None
    # (issue_type, approach_key) → stats
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        oc = _row_outcome(row)
        if oc is None:
            continue  # never default missing/invalid outcome to success
        it = _norm_issue_type(str(row.get("issue_type") or "generic_repair"))
        if want and it != want:
            continue
        ap = str(row.get("approach") or "").strip()
        if not ap:
            continue
        key = (it, _approach_key(ap))
        bucket = buckets.get(key)
        if bucket is None:
            stored_abs = str(row.get("abstract") or "").strip()
            bucket = {
                "issue_type": it,
                "approach": ap,
                "successes": 0,
                "failures": 0,
                "priors": 0,
                "ids": [],
                "abstract": stored_abs or make_abstract(it, ap, outcome=oc),
            }
            buckets[key] = bucket
        if oc == OUTCOME_SUCCESS:
            bucket["successes"] += 1
            bucket["abstract"] = make_abstract(
                it, bucket["approach"], outcome=OUTCOME_SUCCESS
            )
        elif oc == OUTCOME_FAILURE:
            bucket["failures"] += 1
            # Keep success-flavoured abstract if any success already seen;
            # otherwise prefer avoid wording for failure-only buckets.
            if bucket["successes"] == 0:
                bucket["abstract"] = make_abstract(
                    it, bucket["approach"], outcome=OUTCOME_FAILURE
                )
        else:
            bucket["priors"] += 1
        rid = str(row.get("id") or "")
        if rid and len(bucket["ids"]) < 8:
            bucket["ids"].append(rid)

    ranks: list[ApproachRank] = []
    for bucket in buckets.values():
        s = int(bucket["successes"])
        f = int(bucket["failures"])
        p = int(bucket["priors"])
        # Failure-dominant: surface avoid abstract even if a stale stored abstract said "try".
        abstract = str(bucket["abstract"])
        if f > s:
            abstract = make_abstract(
                str(bucket["issue_type"]), str(bucket["approach"]), outcome=OUTCOME_FAILURE
            )
        score = _score_bucket(s, f, p)
        ranks.append(
            ApproachRank(
                issue_type=str(bucket["issue_type"]),
                approach=str(bucket["approach"]),
                score=round(score, 6),
                successes=s,
                failures=f,
                priors=p,
                n=s + f + p,
                abstract=abstract,
                evidence_ids=list(bucket["ids"]),
            )
        )
    ranks.sort(key=lambda r: (-r.score, -r.successes, r.failures, r.approach))
    return ranks


def recommend(
    workdir: Optional[Path | str] = None,
    *,
    issue_type: str = "",
    issue_text: str = "",
    limit: int = DEFAULT_RECOMMEND_LIMIT,
    include_priors_seed: bool = True,
    rows: Optional[Sequence[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Recommend repair approaches for an issue type / text.

    Returns ranked approach dicts (score descending). Catalog priors are
    merged **per issue type** in memory (no disk write) whenever the bank
    has no success evidence for that type — so a partially populated bank
    still answers every catalog type (SWE-Exp cold-start).
    """
    it = _norm_issue_type(issue_type) if issue_type else classify_issue(issue_text)
    if rows is None:
        loaded = load(workdir, limit=RECOMMEND_LOAD_CAP, reverse=False)
    else:
        loaded = list(rows)

    work = list(loaded)
    # Per-type cold start: inject priors when this issue type has no successes.
    if include_priors_seed and not _has_success_for(work, it):
        work = work + _in_memory_priors(it)

    ranks = aggregate(work, issue_type=it)
    # If nothing matched this issue type, fall back to generic_repair ranks.
    if not ranks and it != "generic_repair":
        work_g = list(loaded)
        if include_priors_seed and not _has_success_for(work_g, "generic_repair"):
            work_g = work_g + _in_memory_priors("generic_repair")
        ranks = aggregate(work_g, issue_type="generic_repair")
    lim = max(0, int(limit))
    return [r.to_dict() for r in ranks[:lim]]


def format_recommend_block(
    recommendations: Sequence[dict[str, Any]],
    *,
    issue_type: str = "",
    limit: int = DEFAULT_RECOMMEND_LIMIT,
) -> str:
    """Markdown brief for prompts / dual-review / context packs."""
    lim = max(0, int(limit))
    rows = list(recommendations)[:lim]
    if not rows:
        return ""
    it = issue_type or str(rows[0].get("issue_type") or "generic_repair")
    lines = [
        "## Experience Bank (SWE-Exp — try proven repairs first)",
        "",
        f"Issue type: `{it}` · arXiv:{ARXIV_ID}",
        "",
        "Abstracted experiences (ranked by smoothed success rate):",
        "",
    ]
    for i, r in enumerate(rows, 1):
        ap = (r.get("approach") or "").replace("\n", " ")[:200]
        score = r.get("score")
        try:
            s = int(r.get("successes", 0) or 0)
        except (TypeError, ValueError):
            s = 0
        try:
            f = int(r.get("failures", 0) or 0)
        except (TypeError, ValueError):
            f = 0
        r_it = str(r.get("issue_type") or it)
        if f > s:
            abstract = make_abstract(r_it, ap or "unknown", outcome=OUTCOME_FAILURE)
            tag = "AVOID"
        else:
            abstract = (
                r.get("abstract")
                or make_abstract(r_it, ap or "unknown", outcome=OUTCOME_SUCCESS)
            )
            abstract = str(abstract).replace("\n", " ")[:240]
            tag = "TRY"
        abstract = str(abstract).replace("\n", " ")[:240]
        lines.append(
            f"{i}. **[{tag}] score={score}** (ok={s}/fail={f}) — {abstract}"
        )
        if ap and ap not in abstract:
            lines.append(f"   approach: {ap}")
    lines.append("")
    lines.append(
        "Policy: try higher-scored approaches first; deprioritise / avoid approaches "
        "with repeated failures for this issue type."
    )
    lines.append("")
    return "\n".join(lines)


def stats(workdir: Optional[Path | str] = None) -> dict[str, Any]:
    """Operator snapshot of the bank (newest window; reports truncation)."""
    all_rows = load(workdir, limit=None, reverse=False)
    n_total = len(all_rows)
    rows = (
        all_rows[-STATS_LOAD_CAP:]
        if n_total > STATS_LOAD_CAP
        else all_rows
    )
    by_outcome: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    for r in rows:
        oc = _row_outcome(r)
        if oc is None:
            oc = "unknown"
        by_outcome[oc] += 1
        by_type[_norm_issue_type(str(r.get("issue_type") or "generic_repair"))] += 1
    return {
        "schema": SCHEMA,
        "arxiv_id": ARXIV_ID,
        "path": str(bank_path(workdir)),
        "n": len(rows),
        "n_total": n_total,
        "truncated": n_total > STATS_LOAD_CAP,
        "by_outcome": dict(sorted(by_outcome.items())),
        "by_issue_type": dict(sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


# ---------------------------------------------------------------------------
# Harvest helpers (lightweight — no hard deps on ledger/ops)
# ---------------------------------------------------------------------------


def record_from_repair(
    workdir: Optional[Path | str] = None,
    *,
    ok: bool,
    issue_text: str = "",
    issue_type: str = "",
    approach: str,
    source: str = "repair",
    repo: str = "",
    run_id: str = "",
    evidence: str = "",
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Convenience: record success/failure from a repair attempt."""
    return record(
        workdir,
        issue_type=issue_type,
        issue_text=issue_text,
        approach=approach,
        outcome=OUTCOME_SUCCESS if ok else OUTCOME_FAILURE,
        source=source,
        repo=repo,
        run_id=run_id,
        evidence=evidence or issue_text,
        meta=meta,
    )


def _as_bool_ok(val: Any) -> Optional[bool]:
    """Strict-ish truth parse for harvest status. None → skip row."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if val == 1:
            return True
        if val == 0:
            return False
        return None
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "1", "yes", "ok", "success", "passed", "pass"):
            return True
        if s in ("false", "0", "no", "fail", "failure", "failed", "error"):
            return False
    return None


def harvest_from_implement_results(
    workdir: Optional[Path | str],
    results: Sequence[dict[str, Any]],
    *,
    run_id: str = "",
    source: str = "implement",
) -> dict[str, Any]:
    """Harvest repair experiences from implement step result dicts. Fail-open.

    Approaches are kept *abstracted*: when a result lacks a structured
    approach field, successes share one constant bucket string (repo id
    lives in ``repo`` / ``meta``); unstructured failures are skipped so
    rankings are not polluted by per-rid n=1 singleton approaches.
    """
    written = 0
    skipped = 0
    ids: list[str] = []
    for r in results or []:
        if not isinstance(r, dict):
            skipped += 1
            continue
        rid = str(r.get("id") or r.get("repo") or r.get("idea_id") or "?")
        ok = _as_bool_ok(r.get("ok"))
        if ok is None:
            skipped += 1
            continue
        err = str(r.get("error") or "")
        # Prefer explicit approach fields when workers provide them.
        approach = str(
            r.get("approach")
            or r.get("repair_approach")
            or r.get("pattern")
            or r.get("summary")
            or ""
        ).strip()
        if not approach:
            if ok:
                # Constant abstraction — rid stays in repo/meta, not approach text.
                approach = HARVEST_DEFAULT_SUCCESS_APPROACH
            else:
                # No transferable failure pattern → skip (do not fabricate).
                skipped += 1
                continue
        issue_text = err or str(r.get("issue") or r.get("goal") or rid)
        try:
            row = record_from_repair(
                workdir,
                ok=ok,
                issue_text=issue_text,
                issue_type=str(r.get("issue_type") or ""),
                approach=approach[:500],
                source=source,
                repo=rid[:120],
                run_id=run_id,
                evidence=err[:400] if err else str(r.get("detail") or "")[:400],
                meta={"implement_id": rid},
            )
            written += 1
            ids.append(str(row.get("id") or ""))
        except Exception:
            skipped += 1
            continue
    return {"ok": True, "written": written, "skipped": skipped, "ids": ids}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m nexus.experience_bank",
        description="SWE-Exp Experience Bank — store/recommend repair patterns",
    )
    p.add_argument(
        "--path",
        default=".",
        help="project workdir (bank at .nexus_state/experience_bank.jsonl)",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("record", help="append one experience")
    rec.add_argument("--issue-type", default="", help="canonical issue type id")
    rec.add_argument("--issue-text", default="", help="free text to classify")
    rec.add_argument("--approach", required=True, help="repair approach tried")
    rec.add_argument(
        "--outcome",
        default=OUTCOME_SUCCESS,
        choices=sorted(_VALID_OUTCOMES),
    )
    rec.add_argument("--source", default="cli")
    rec.add_argument("--repo", default="")
    rec.add_argument("--evidence", default="")

    recm = sub.add_parser("recommend", help="rank approaches for an issue")
    recm.add_argument("--issue-type", default="")
    recm.add_argument("--issue-text", default="")
    recm.add_argument("--limit", type=int, default=DEFAULT_RECOMMEND_LIMIT)
    recm.add_argument(
        "--seed",
        action="store_true",
        help="persist catalog priors before ranking",
    )

    sub.add_parser("list", help="list recent experiences").add_argument(
        "--limit", type=int, default=20
    )
    sub.add_parser("stats", help="bank snapshot")
    sub.add_parser("seed", help="persist DEFAULT_PRIORS once")
    sub.add_parser("types", help="list known issue types")

    args = p.parse_args(list(argv) if argv is not None else None)
    root = Path(args.path)

    if args.cmd == "types":
        types = list_issue_types()
        if args.json:
            print(json.dumps(types, indent=2))
        else:
            for t in types:
                print(t)
        return 0

    if args.cmd == "seed":
        out = seed_priors(root)
        print(json.dumps(out, indent=2) if args.json else out)
        return 0

    if args.cmd == "stats":
        st = stats(root)
        if args.json:
            print(json.dumps(st, indent=2))
        else:
            print(f"experience_bank n={st['n']} path={st['path']}")
            for k, v in (st.get("by_outcome") or {}).items():
                print(f"  outcome {k}: {v}")
            for k, v in list((st.get("by_issue_type") or {}).items())[:12]:
                print(f"  type {k}: {v}")
        return 0

    if args.cmd == "list":
        rows = load(root, limit=int(args.limit))
        if args.json:
            print(json.dumps(rows, indent=2, default=str))
        else:
            for r in rows:
                print(
                    f"{r.get('id')} [{r.get('outcome')}] "
                    f"{r.get('issue_type')}: {(r.get('approach') or '')[:80]}"
                )
        return 0

    if args.cmd == "record":
        row = record(
            root,
            issue_type=args.issue_type,
            issue_text=args.issue_text,
            approach=args.approach,
            outcome=args.outcome,
            source=args.source,
            repo=args.repo,
            evidence=args.evidence,
        )
        if args.json:
            print(json.dumps(row, indent=2, default=str))
        else:
            print(f"recorded {row['id']} {row['outcome']} {row['issue_type']}")
            print(row.get("abstract") or "")
        return 0

    if args.cmd == "recommend":
        if args.seed:
            seed_priors(root)
        ranks = recommend(
            root,
            issue_type=args.issue_type,
            issue_text=args.issue_text,
            limit=int(args.limit),
        )
        it = args.issue_type or (
            ranks[0]["issue_type"] if ranks else classify_issue(args.issue_text)
        )
        if args.json:
            print(json.dumps({"issue_type": it, "recommendations": ranks}, indent=2))
        else:
            print(format_recommend_block(ranks, issue_type=it, limit=int(args.limit)))
        return 0

    return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    return _cli(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "SCHEMA",
    "ARXIV_ID",
    "ARXIV_URL",
    "SOURCE_TITLE",
    "OUTCOME_SUCCESS",
    "OUTCOME_FAILURE",
    "OUTCOME_PRIOR",
    "DEFAULT_PRIORS",
    "ISSUE_TYPE_RULES",
    "HARVEST_DEFAULT_SUCCESS_APPROACH",
    "RECOMMEND_LOAD_CAP",
    "STATS_LOAD_CAP",
    "ExperienceBankError",
    "Experience",
    "ApproachRank",
    "bank_path",
    "make_abstract",
    "classify_issue",
    "list_issue_types",
    "record",
    "load",
    "seed_priors",
    "aggregate",
    "recommend",
    "format_recommend_block",
    "stats",
    "record_from_repair",
    "harvest_from_implement_results",
    "main",
]
