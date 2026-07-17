"""Trace-derived failure pattern mining (Socratic-SWE shape).

Paper: *Socratic-SWE: Self-Evolving Coding Agents via Trace-Derived Agent Skills*
https://arxiv.org/abs/2606.07412v1

Socratic-SWE mines historical agent trajectories for recurring failure modes and
turns them into reusable agent skills. This module is a small, offline-first
port of that *shape* for NEXUS:

  decision_ledger + ops_store failure rows
            │
            ▼
     classify text → pattern ids
            │
            ▼
     aggregate (count ≥ min_count)
            │
            ▼
     skill hints for replan / context packs

Sources (read-only):

- ``.nexus_state/ledger/decisions.sqlite`` — agent decisions whose action/claim
  looks like a failure (reject, fail, veto, error, …)
- ``.nexus_state/ops/ops.sqlite`` — jobs with ``status=failed`` (and optional
  ``meta.error`` / title / goal text)

No network; no secrets; pattern only — not a vendored upstream tree.
Schema: ``nexus.failure_patterns/v1``
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

SCHEMA = "nexus.failure_patterns/v1"
ARXIV_ID = "2606.07412v1"
ARXIV_URL = "https://arxiv.org/abs/2606.07412v1"
SOURCE_TITLE = "Socratic-SWE: Self-Evolving Coding Agents via Trace-Derived Agent Skills"

DEFAULT_MIN_COUNT = 2
DEFAULT_TRACE_LIMIT = 500
DEFAULT_EXAMPLE_LIMIT = 3

# Actions that mark a decision as a failure-ish outcome (substring match, lower).
# Note: "deny" is NOT a substring of "denied" — keep both forms.
_FAILURE_ACTION_NEEDLES = (
    "fail",
    "reject",
    "veto",
    "error",
    "denied",
    "deny",
    "abort",
    "block",
    "timeout",
    "crash",
    "refuse",
    "revert",
)

# Grade keys that, when false, mark a decision as failed.
_GRADE_FALSE_KEYS = ("ok", "passed", "success", "green", "verified")


class FailurePatternError(RuntimeError):
    """Invalid failure-pattern analysis input or operation."""


# ---------------------------------------------------------------------------
# Pattern catalog (heuristic rules — extend, do not hard-code agent policy)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternRule:
    """One recurring failure mode + remediation skill hint."""

    id: str
    label: str
    regexes: tuple[str, ...]
    skill_hint: str
    priority: int = 100  # lower = preferred when multiple match same span

    def compiled(self) -> tuple[re.Pattern[str], ...]:
        return tuple(re.compile(r, re.I | re.M) for r in self.regexes)


# Ordered catalog. First match still records *all* matching patterns so
# multi-label traces are allowed; priority only affects sort of singles.
PATTERN_CATALOG: tuple[PatternRule, ...] = (
    PatternRule(
        id="missing_dependency_check",
        label="missing dependency check",
        regexes=(
            r"ModuleNotFoundError",
            r"ImportError",
            r"No module named\s+['\"]?[\w.]+",
            r"package\s+['\"]?[\w.-]+['\"]?\s+not found",
            r"Could not find a version that satisfies",
            r"pip install",
            r"cannot import name",
            r"missing dependency",
            r"required package",
        ),
        skill_hint=(
            "Before coding, verify imports/deps exist (or add an install/check step); "
            "fail closed on ModuleNotFoundError rather than guessing APIs."
        ),
        priority=10,
    ),
    PatternRule(
        id="incorrect_api_usage",
        label="incorrect API usage",
        regexes=(
            r"unexpected keyword argument",
            r"got an unexpected keyword",
            r"takes \d+ positional argument",
            r"missing \d+ required positional",
            r"TypeError:.*argument",
            r"AttributeError:.*object has no attribute",
            r"incorrect API",
            r"wrong signature",
            r"not callable",
        ),
        skill_hint=(
            "Check function/method signatures against source or stubs before calling; "
            "prefer thin typed adapters over free-form kwargs."
        ),
        priority=20,
    ),
    PatternRule(
        id="file_or_path_missing",
        label="file or path missing",
        regexes=(
            r"FileNotFoundError",
            r"No such file or directory",
            r"ENOENT",
            r"path does not exist",
            r"not a (?:file|directory)",
            r"cannot open ['\"]",
        ),
        skill_hint=(
            "Resolve paths under the workdir jail first; assert Path.exists() before "
            "read/write and surface missing paths as structured tool errors."
        ),
        priority=30,
    ),
    PatternRule(
        id="permission_or_auth",
        label="permission or auth failure",
        regexes=(
            r"PermissionError",
            r"Permission denied",
            r"EACCES",
            r"401\b",
            r"403\b",
            r"Unauthorized",
            r"authentication failed",
            r"not authorized",
            r"access denied",
        ),
        skill_hint=(
            "Check privilege/auth gates before privileged ops; surface 401/403 as "
            "operator-visible blocks rather than retrying blindly."
        ),
        priority=40,
    ),
    PatternRule(
        id="test_assertion_failure",
        label="test assertion failure",
        regexes=(
            r"AssertionError",
            r"FAILED\s+[\w./:-]+",
            r"\d+ failed(?!, 0 failed)",
            r"[1-9]\d* failed",
            r"pytest\.raises",
            r"assert .+ ==",
            r"test failed",
            r"tests? failed",
        ),
        skill_hint=(
            "Read the failing assertion and expected vs actual; fix the minimal "
            "unit under test before expanding scope or adding new features."
        ),
        priority=50,
    ),
    PatternRule(
        id="timeout_or_hang",
        label="timeout or hang",
        regexes=(
            r"TimeoutError",
            r"timed?\s*out",
            r"deadline exceeded",
            r"Read timed out",
            r"context deadline",
            r"hung",
        ),
        skill_hint=(
            "Set explicit timeouts on subprocess/network tools; prefer fail-fast "
            "with partial logs over unbounded waits."
        ),
        priority=60,
    ),
    PatternRule(
        id="syntax_or_parse_error",
        label="syntax or parse error",
        regexes=(
            r"SyntaxError",
            r"IndentationError",
            r"JSONDecodeError",
            r"Expecting value:",
            r"invalid syntax",
            r"yaml\.scanner",
            r"parse error",
        ),
        skill_hint=(
            "Validate generated code/JSON/YAML with a parser before promotion; "
            "keep patches small enough to re-parse quickly."
        ),
        priority=70,
    ),
    PatternRule(
        id="network_or_connectivity",
        label="network or connectivity",
        regexes=(
            r"ConnectionError",
            r"ConnectionRefused",
            r"Connection reset",
            r"Name or service not known",
            r"Temporary failure in name resolution",
            r"Network is unreachable",
            r"Max retries exceeded",
            r"URLError",
        ),
        skill_hint=(
            "Prefer offline fixtures in unit tests; for live calls, probe once, "
            "then degrade to cache/heuristic rather than thrashing retries."
        ),
        priority=80,
    ),
    PatternRule(
        id="budget_or_rate_limit",
        label="budget or rate limit",
        regexes=(
            r"rate limit",
            r"429\b",
            r"quota exceeded",
            r"budget exceeded",
            r"token limit",
            r"max_tokens",
            r"spend cap",
        ),
        skill_hint=(
            "Respect spend/rate caps; shrink context and batch work before retrying; "
            "record spend so operators see the ceiling."
        ),
        priority=90,
    ),
    PatternRule(
        id="policy_or_gate_denied",
        label="policy or gate denied",
        regexes=(
            r"policy denied",
            r"cedar",
            r"gate denied",
            r"forbid-",
            r"promote denied",
            r"not approved",
            r"quality.?gate",
            r"mission_gate",
            r"veto",
        ),
        skill_hint=(
            "Satisfy gate preconditions (review approved, domain ready, evidence) "
            "before promote/complete; do not force-bypass without operator force."
        ),
        priority=25,
    ),
    PatternRule(
        id="generic_runtime_error",
        label="generic runtime error",
        regexes=(
            r"RuntimeError",
            r"ValueError",
            r"KeyError",
            r"IndexError",
            r"Exception:",
            r"Traceback \(most recent call last\)",
            r"\berror\b",
            r"\bfailed\b",
        ),
        skill_hint=(
            "Capture structured error fields (type, message, tool) into the ledger; "
            "replan from the concrete exception rather than free-form retry."
        ),
        priority=900,  # catch-all — lowest priority
    ),
)

_COMPILED: list[tuple[PatternRule, tuple[re.Pattern[str], ...]]] | None = None


def _catalog_compiled() -> list[tuple[PatternRule, tuple[re.Pattern[str], ...]]]:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = [(r, r.compiled()) for r in PATTERN_CATALOG]
    return _COMPILED


def list_pattern_ids() -> list[str]:
    return [r.id for r in PATTERN_CATALOG]


def pattern_rule(pattern_id: str) -> Optional[PatternRule]:
    for r in PATTERN_CATALOG:
        if r.id == pattern_id:
            return r
    return None


# ---------------------------------------------------------------------------
# Trace records
# ---------------------------------------------------------------------------


@dataclass
class FailureTrace:
    """One failure-ish event from ledger or ops."""

    source: str  # decision_ledger | ops_store
    ref_id: str
    text: str
    pattern_ids: list[str] = field(default_factory=list)
    agent: str = ""
    action: str = ""
    run_id: str = ""
    job_id: str = ""
    status: str = ""
    created_at: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # keep examples compact in reports
        if len(d.get("text") or "") > 400:
            d["text"] = (d["text"][:397] + "...")
        return d


@dataclass
class PatternHit:
    """Aggregated recurring pattern."""

    id: str
    label: str
    count: int
    skill_hint: str
    sources: dict[str, int] = field(default_factory=dict)
    example_refs: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    priority: int = 100

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_text(text: str) -> list[str]:
    """Return all matching pattern ids for *text* (may be multi-label).

    Catch-all ``generic_runtime_error`` is only kept when no more specific
    pattern matched.
    """
    if not text or not str(text).strip():
        return []
    blob = str(text)
    hits: list[tuple[int, str]] = []
    for rule, cre in _catalog_compiled():
        if any(p.search(blob) for p in cre):
            hits.append((rule.priority, rule.id))
    if not hits:
        return []
    # Drop catch-all if anything more specific hit.
    specific = [pid for pri, pid in hits if pid != "generic_runtime_error"]
    if specific:
        # stable unique by first appearance order in catalog priority sort
        ordered = sorted(specific, key=lambda pid: next(
            (r.priority for r in PATTERN_CATALOG if r.id == pid), 999
        ))
        seen: set[str] = set()
        out: list[str] = []
        for pid in ordered:
            if pid not in seen:
                seen.add(pid)
                out.append(pid)
        return out
    return ["generic_runtime_error"]


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def _json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return str(obj)


def _decision_is_failure(row: dict[str, Any]) -> bool:
    action = str(row.get("action") or "").strip().lower()
    if any(n in action for n in _FAILURE_ACTION_NEEDLES):
        return True
    grade = row.get("grade") or {}
    if isinstance(grade, dict):
        for k in _GRADE_FALSE_KEYS:
            if k in grade and grade[k] is False:
                return True
        # explicit error field
        if grade.get("error") or grade.get("errors"):
            return True
    claim = str(row.get("claim") or "")
    # Only treat claim text as failure when it clearly signals one — avoid
    # scanning every successful claim for the word "error" in normal prose.
    if claim and classify_text(claim) and any(
        n in claim.lower()
        for n in ("fail", "error", "exception", "traceback", "denied", "rejected")
    ):
        return True
    return False


def _decision_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("action", "claim", "agent"):
        if row.get(key):
            parts.append(str(row[key]))
    grade = row.get("grade")
    if isinstance(grade, dict) and grade:
        # Prefer explicit error-ish fields first
        for k in ("error", "errors", "message", "detail", "reason", "summary"):
            if grade.get(k):
                parts.append(str(grade[k]))
        parts.append(_json_dumps(grade))
    refs = row.get("evidence_refs")
    if refs:
        parts.append(_json_dumps(refs))
    return "\n".join(parts)


def _job_text(job: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("status", "title", "goal", "kind"):
        if job.get(key):
            parts.append(str(job[key]))
    meta = job.get("meta") or {}
    if isinstance(meta, dict) and meta:
        for k in (
            "error",
            "errors",
            "message",
            "detail",
            "reason",
            "summary",
            "stderr",
            "stdout",
            "traceback",
            "log",
        ):
            if meta.get(k):
                parts.append(str(meta[k]))
        parts.append(_json_dumps(meta))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Collect
# ---------------------------------------------------------------------------


def collect_decision_traces(
    workdir: Optional[Path | str] = None,
    *,
    limit: int = DEFAULT_TRACE_LIMIT,
    run_id: Optional[str] = None,
    ledger: Any = None,
) -> list[FailureTrace]:
    """Load failure-ish decisions from the decision ledger."""
    from .decision_ledger import DecisionLedger

    own = ledger is None
    led = ledger if ledger is not None else DecisionLedger.open(workdir)
    try:
        # Pull a larger window then filter; tail is newest-first.
        pull = max(1, min(int(limit) * 4, 5000))
        rows = led.tail(limit=pull, run_id=run_id)
        out: list[FailureTrace] = []
        for row in rows:
            if not _decision_is_failure(row):
                continue
            text = _decision_text(row)
            pids = classify_text(text)
            if not pids:
                # Still count as generic if action says failure.
                pids = ["generic_runtime_error"]
            out.append(
                FailureTrace(
                    source="decision_ledger",
                    ref_id=str(row.get("id") or ""),
                    text=text,
                    pattern_ids=pids,
                    agent=str(row.get("agent") or ""),
                    action=str(row.get("action") or ""),
                    run_id=str(row.get("run_id") or ""),
                    created_at=float(row.get("created_at") or 0),
                    meta={
                        "content_hash": row.get("content_hash"),
                        "grade": row.get("grade") or {},
                    },
                )
            )
            if len(out) >= int(limit):
                break
        return out
    finally:
        if own:
            try:
                led.close()
            except Exception:
                pass


def collect_ops_traces(
    workdir: Optional[Path | str] = None,
    *,
    limit: int = DEFAULT_TRACE_LIMIT,
    store: Any = None,
) -> list[FailureTrace]:
    """Load failed jobs from ops_store."""
    from .ops_store import OpsStore

    own = store is None
    ops = store if store is not None else OpsStore.open(workdir)
    try:
        jobs = ops.list_jobs(status="failed", limit=max(1, min(int(limit), 1000)))
        out: list[FailureTrace] = []
        for job in jobs:
            text = _job_text(job)
            pids = classify_text(text)
            if not pids:
                pids = ["generic_runtime_error"]
            out.append(
                FailureTrace(
                    source="ops_store",
                    ref_id=str(job.get("id") or ""),
                    text=text,
                    pattern_ids=pids,
                    job_id=str(job.get("id") or ""),
                    status=str(job.get("status") or ""),
                    action=str(job.get("kind") or ""),
                    agent=str((job.get("meta") or {}).get("agent") or job.get("kind") or ""),
                    created_at=float(job.get("updated_at") or job.get("created_at") or 0),
                    meta={"kind": job.get("kind"), "title": job.get("title")},
                )
            )
            if len(out) >= int(limit):
                break
        return out
    finally:
        if own:
            try:
                ops.close()
            except Exception:
                pass


def collect_traces(
    workdir: Optional[Path | str] = None,
    *,
    limit: int = DEFAULT_TRACE_LIMIT,
    run_id: Optional[str] = None,
    include_ledger: bool = True,
    include_ops: bool = True,
    ledger: Any = None,
    store: Any = None,
) -> list[FailureTrace]:
    """Union of decision + ops failure traces (newest sources first per source)."""
    traces: list[FailureTrace] = []
    if include_ledger:
        traces.extend(
            collect_decision_traces(
                workdir, limit=limit, run_id=run_id, ledger=ledger
            )
        )
    if include_ops:
        traces.extend(collect_ops_traces(workdir, limit=limit, store=store))
    return traces


# ---------------------------------------------------------------------------
# Aggregate / analyze
# ---------------------------------------------------------------------------


def _aggregate(
    traces: Sequence[FailureTrace],
    *,
    min_count: int = DEFAULT_MIN_COUNT,
    example_limit: int = DEFAULT_EXAMPLE_LIMIT,
) -> list[PatternHit]:
    buckets: dict[str, dict[str, Any]] = {}
    for tr in traces:
        for pid in tr.pattern_ids or []:
            b = buckets.setdefault(
                pid,
                {
                    "count": 0,
                    "sources": {},
                    "example_refs": [],
                    "examples": [],
                    "agents": set(),
                },
            )
            b["count"] += 1
            b["sources"][tr.source] = int(b["sources"].get(tr.source, 0)) + 1
            if tr.agent:
                b["agents"].add(tr.agent)
            if len(b["example_refs"]) < int(example_limit):
                ref = f"{tr.source}:{tr.ref_id}"
                if ref not in b["example_refs"]:
                    b["example_refs"].append(ref)
                    snippet = (tr.text or "").replace("\n", " ").strip()
                    if len(snippet) > 160:
                        snippet = snippet[:157] + "..."
                    b["examples"].append(snippet)

    hits: list[PatternHit] = []
    for pid, b in buckets.items():
        if int(b["count"]) < int(min_count):
            continue
        rule = pattern_rule(pid)
        hits.append(
            PatternHit(
                id=pid,
                label=(rule.label if rule else pid),
                count=int(b["count"]),
                skill_hint=(rule.skill_hint if rule else ""),
                sources=dict(b["sources"]),
                example_refs=list(b["example_refs"]),
                examples=list(b["examples"]),
                agents=sorted(b["agents"]),
                priority=(rule.priority if rule else 999),
            )
        )
    hits.sort(key=lambda h: (-h.count, h.priority, h.id))
    return hits


def analyze_failure_patterns(
    workdir: Optional[Path | str] = None,
    *,
    min_count: int = DEFAULT_MIN_COUNT,
    limit: int = DEFAULT_TRACE_LIMIT,
    run_id: Optional[str] = None,
    include_ledger: bool = True,
    include_ops: bool = True,
    example_limit: int = DEFAULT_EXAMPLE_LIMIT,
    traces: Optional[Sequence[FailureTrace]] = None,
    ledger: Any = None,
    store: Any = None,
) -> dict[str, Any]:
    """Mine recurring failure patterns from historical traces.

    Returns a JSON-serialisable report with schema ``nexus.failure_patterns/v1``.
    Patterns with ``count < min_count`` are omitted from ``patterns`` but
    still counted in ``singleton_count`` for transparency.
    """
    root = _root(workdir)
    if traces is None:
        traces = collect_traces(
            root,
            limit=limit,
            run_id=run_id,
            include_ledger=include_ledger,
            include_ops=include_ops,
            ledger=ledger,
            store=store,
        )
    else:
        traces = list(traces)

    all_hits = _aggregate(traces, min_count=1, example_limit=example_limit)
    recurring = [h for h in all_hits if h.count >= int(min_count)]
    singletons = [h for h in all_hits if h.count < int(min_count)]

    by_source: dict[str, int] = {}
    for tr in traces:
        by_source[tr.source] = by_source.get(tr.source, 0) + 1

    skills = skill_hints_from_hits(recurring)

    return {
        "schema": SCHEMA,
        "ok": True,
        "arxiv_id": ARXIV_ID,
        "arxiv_url": ARXIV_URL,
        "title": SOURCE_TITLE,
        "workdir": str(root),
        "ts": time.time(),
        "min_count": int(min_count),
        "n_traces": len(traces),
        "by_source": by_source,
        "n_patterns": len(recurring),
        "singleton_count": len(singletons),
        "patterns": [h.to_dict() for h in recurring],
        "skills": skills,
        "catalog_size": len(PATTERN_CATALOG),
        "run_id": run_id or "",
    }


def skill_hints_from_hits(
    hits: Sequence[PatternHit] | Sequence[dict[str, Any]],
    *,
    max_skills: int = 8,
) -> list[dict[str, Any]]:
    """Turn recurring pattern hits into Socratic-style skill briefs."""
    out: list[dict[str, Any]] = []
    for h in hits:
        if isinstance(h, PatternHit):
            d = h.to_dict()
        else:
            d = dict(h)
        pid = str(d.get("id") or "")
        if not pid:
            continue
        out.append(
            {
                "skill_id": f"trace-skill:{pid}",
                "pattern_id": pid,
                "label": d.get("label") or pid,
                "when_to_use": (
                    f"Recurring failure '{d.get('label') or pid}' seen "
                    f"{int(d.get('count') or 0)} time(s) in historical traces."
                ),
                "instruction": d.get("skill_hint") or "",
                "evidence_count": int(d.get("count") or 0),
                "sources": d.get("sources") or {},
            }
        )
        if len(out) >= int(max_skills):
            break
    return out


def skill_brief(report: dict[str, Any], *, max_skills: int = 5) -> str:
    """Human-readable skill brief for context packs / replan prompts."""
    skills = list(report.get("skills") or [])[: int(max_skills)]
    if not skills:
        return (
            f"(no recurring failure skills; traces={report.get('n_traces', 0)} "
            f"min_count={report.get('min_count', DEFAULT_MIN_COUNT)})"
        )
    lines = [
        f"Trace-derived agent skills ({ARXIV_ID}, n_traces={report.get('n_traces', 0)}):"
    ]
    for i, s in enumerate(skills, 1):
        lines.append(
            f"{i}. [{s.get('pattern_id')}] {s.get('label')} "
            f"(n={s.get('evidence_count')}): {s.get('instruction')}"
        )
    return "\n".join(lines)


def format_report(report: dict[str, Any]) -> str:
    """Operator-facing multi-line summary."""
    lines = [
        f"failure_patterns schema={report.get('schema')} arxiv={report.get('arxiv_id')}",
        f"workdir={report.get('workdir')}",
        f"traces={report.get('n_traces')} recurring_patterns={report.get('n_patterns')} "
        f"singletons={report.get('singleton_count')} min_count={report.get('min_count')}",
        f"by_source={report.get('by_source')}",
    ]
    patterns = report.get("patterns") or []
    if not patterns:
        lines.append("(no recurring patterns at this min_count)")
    else:
        lines.append("patterns:")
        for p in patterns:
            lines.append(
                f"  - {p.get('id')}: count={p.get('count')} "
                f"sources={p.get('sources')} agents={p.get('agents')}"
            )
            hint = (p.get("skill_hint") or "")[:120]
            if hint:
                lines.append(f"      skill: {hint}")
            for ex in (p.get("examples") or [])[:2]:
                lines.append(f"      e.g. {ex}")
    skills = report.get("skills") or []
    if skills:
        lines.append("skills:")
        for s in skills[:8]:
            lines.append(
                f"  - {s.get('skill_id')}: {s.get('instruction')[:100]}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience: analyze raw free-form logs (external feedback)
# ---------------------------------------------------------------------------


def classify_log_lines(
    lines: Iterable[str],
    *,
    min_count: int = 1,
) -> dict[str, Any]:
    """Classify free-form log lines without a ledger (unit/offline helper)."""
    traces: list[FailureTrace] = []
    for i, line in enumerate(lines):
        text = str(line or "").strip()
        if not text:
            continue
        pids = classify_text(text)
        if not pids:
            continue
        traces.append(
            FailureTrace(
                source="external_log",
                ref_id=f"line-{i}",
                text=text,
                pattern_ids=pids,
            )
        )
    return analyze_failure_patterns(
        workdir=".",
        min_count=min_count,
        traces=traces,
        include_ledger=False,
        include_ops=False,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m nexus.failure_patterns",
        description=(
            "Analyze decision_ledger + ops_store failure traces for recurring "
            f"patterns (Socratic-SWE {ARXIV_ID})."
        ),
    )
    p.add_argument("--path", default=".", help="project workdir")
    p.add_argument(
        "--min-count",
        type=int,
        default=DEFAULT_MIN_COUNT,
        dest="min_count",
        help=f"min occurrences to count as recurring (default {DEFAULT_MIN_COUNT})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_TRACE_LIMIT,
        help="max traces per source",
    )
    p.add_argument("--run-id", default=None, dest="run_id")
    p.add_argument(
        "--no-ledger",
        action="store_true",
        dest="no_ledger",
        help="skip decision_ledger source",
    )
    p.add_argument(
        "--no-ops",
        action="store_true",
        dest="no_ops",
        help="skip ops_store source",
    )
    p.add_argument(
        "--skills-only",
        action="store_true",
        dest="skills_only",
        help="print skill brief only",
    )
    p.add_argument(
        "--catalog",
        action="store_true",
        help="list pattern catalog ids and exit",
    )
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--classify",
        default=None,
        help="classify a single text string (no DB) and print pattern ids",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.catalog:
        rows = [
            {"id": r.id, "label": r.label, "priority": r.priority, "skill_hint": r.skill_hint}
            for r in PATTERN_CATALOG
        ]
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in PATTERN_CATALOG:
                print(f"{r.id:28} prio={r.priority:<4} {r.label}")
        return 0

    if args.classify is not None:
        pids = classify_text(args.classify)
        if args.json:
            print(json.dumps({"text": args.classify, "pattern_ids": pids}, indent=2))
        else:
            print(",".join(pids) if pids else "(no match)")
        return 0

    report = analyze_failure_patterns(
        args.path,
        min_count=int(args.min_count),
        limit=int(args.limit),
        run_id=args.run_id,
        include_ledger=not bool(args.no_ledger),
        include_ops=not bool(args.no_ops),
    )
    if args.skills_only:
        print(skill_brief(report))
        return 0
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_report(report))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return _cli(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "SCHEMA",
    "ARXIV_ID",
    "ARXIV_URL",
    "SOURCE_TITLE",
    "DEFAULT_MIN_COUNT",
    "PATTERN_CATALOG",
    "FailurePatternError",
    "PatternRule",
    "FailureTrace",
    "PatternHit",
    "list_pattern_ids",
    "pattern_rule",
    "classify_text",
    "collect_decision_traces",
    "collect_ops_traces",
    "collect_traces",
    "analyze_failure_patterns",
    "skill_hints_from_hits",
    "skill_brief",
    "format_report",
    "classify_log_lines",
    "main",
]
