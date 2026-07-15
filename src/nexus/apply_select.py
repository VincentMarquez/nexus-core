"""Evidence-FTS apply selection + role-separated verify + improve board.

First apply slice (docs/LATEST_IMPROVE_PLAN.md next PR after grade claims/FTS):

  graded candidates
    → FTS evidence hits (cas/soul search)
    → rank by score + evidence + preference_boost (offline pairs)
    → role gate: grader ≠ implementer ≠ verifier (anti-collusion)
    → budget check (Network-AI / mission-control)
    → decision package (2511.15755) before apply
    → routa-lite board CLI/MCP
    → board signal → PrincipledStop gaps (sync_signal_to_stop)

Patterns (shape only, not vendored trees):
- codingagentsystem/cas — MCP SQLite/FTS evidence search
- builderz-labs/mission-control — spend/runtime gate before action
- Jovancoding/Network-AI — budgets + guardrails
- phodal/routa — board: goal / task / trace / evidence
- ahmedEid1/lumen — decision audit package
- arXiv 2601.00360 — anti-collusion role separation
- arXiv 2511.15755 — terminal decision package
- arXiv 2512.03278 — Thucy path-anchored claims
- arXiv 2602.04518 — preference-pair rank bias (offline)
- Intelligent-Internet/zenith — independent verify before promote/apply

Does not call the network; fixtures + offline digests only for unit paths.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from .claim_verify import verify_or_report
from .durability.budgets import BudgetExhausted, RunBudget
from .durability.verify_promote import IndependentVerify, VerifyResult
from .evidence_fts import index_workspace, search_evidence
from .grade_artifact import list_graded_candidates, load_grade, validate_grade
from .load_mine_eval import load_fixture_file as load_fixture_grades

SCHEMA = "nexus.apply_select/v1"
BOARD_SCHEMA = "nexus.improve_board/v1"
DECISION_SCHEMA = "nexus.decision_package/v1"

DEFAULT_ROLES = {
    "grader": "grok:grade",
    "implementer": "worker:apply",
    "verifier": "judge:verify",
}

# Weighting for rank score = grade_score + evidence_boost * hit_count (capped)
# + optional preference_boost from offline better>worse pairs (arXiv 2602.04518)
EVIDENCE_BOOST = 0.5
EVIDENCE_HIT_CAP = 5

# Board / supervisor signals (zenith adaptive stop + MAEBE thrash telemetry)
SIGNAL_CONTINUE = "continue"
SIGNAL_REPLAN = "replan"
SIGNAL_STOP = "stop"
BOARD_SIGNALS = frozenset({SIGNAL_CONTINUE, SIGNAL_REPLAN, SIGNAL_STOP})

# Below this confidence, prefer replan over hard apply (0–1 scale)
LOW_CONFIDENCE = 0.35


class RoleCollusionError(PermissionError):
    """Raised when grader / implementer / verifier roles are not independent."""

    def __init__(self, message: str, *, roles: Optional[dict[str, str]] = None) -> None:
        super().__init__(message)
        self.roles = dict(roles or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "RoleCollusionError",
            "message": str(self),
            "roles": self.roles,
        }


class ApplySelectError(ValueError):
    """Selection or decision-package construction failed."""


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def _norm_agent(name: str) -> str:
    return str(name or "").strip().lower()


def check_roles(
    *,
    grader: str,
    implementer: str,
    verifier: str,
    require_distinct: bool = True,
) -> dict[str, Any]:
    """Anti-collusion gate: grader ≠ implementer ≠ verifier when required.

    Returns a structured result; does not raise (use require_roles to raise).
    """
    roles = {
        "grader": str(grader or "").strip(),
        "implementer": str(implementer or "").strip(),
        "verifier": str(verifier or "").strip(),
    }
    missing = [k for k, v in roles.items() if not v]
    if missing:
        return {
            "ok": False,
            "reason": f"missing_roles:{','.join(missing)}",
            "roles": roles,
            "distinct": False,
            "collisions": [],
        }

    g, i, v = (
        _norm_agent(roles["grader"]),
        _norm_agent(roles["implementer"]),
        _norm_agent(roles["verifier"]),
    )
    collisions: list[str] = []
    if g == i:
        collisions.append("grader==implementer")
    if g == v:
        collisions.append("grader==verifier")
    if i == v:
        collisions.append("implementer==verifier")

    distinct = not collisions
    if require_distinct and collisions:
        return {
            "ok": False,
            "reason": "role_collusion:" + ",".join(collisions),
            "roles": roles,
            "distinct": False,
            "collisions": collisions,
        }
    return {
        "ok": True,
        "reason": "roles_ok" if distinct else "roles_overlap_allowed",
        "roles": roles,
        "distinct": distinct,
        "collisions": collisions,
    }


def require_roles(
    *,
    grader: str,
    implementer: str,
    verifier: str,
    require_distinct: bool = True,
) -> dict[str, Any]:
    """Like check_roles but raises RoleCollusionError on failure."""
    res = check_roles(
        grader=grader,
        implementer=implementer,
        verifier=verifier,
        require_distinct=require_distinct,
    )
    if not res.get("ok"):
        raise RoleCollusionError(
            res.get("reason") or "role_check_failed",
            roles=res.get("roles") or {},
        )
    return res


def _fixture_grades(
    workdir: Path,
    *,
    fixture: Optional[Path | str] = None,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Load grades from claims fixture or default mine_eval fixtures."""
    root = workdir
    paths: list[Path] = []
    if fixture is not None:
        paths.append(Path(fixture))
    else:
        preferred = root / "fixtures" / "mine_eval" / "grades_with_claims.json"
        sample = root / "tests" / "fixtures" / "mine_eval_sample.json"
        if preferred.is_file():
            paths.append(preferred)
        if sample.is_file():
            paths.append(sample)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in paths:
        if not p.is_file():
            continue
        try:
            rows = load_fixture_grades(p)
        except Exception:
            # fallback: raw JSON list/object
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(raw, dict) and isinstance(raw.get("grades"), list):
                rows = list(raw["grades"])
            elif isinstance(raw, list):
                rows = raw
            elif isinstance(raw, dict):
                rows = [raw]
            else:
                continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            repo = str(item.get("repo") or "").strip()
            if not repo or repo in seen:
                continue
            try:
                g = validate_grade(
                    item,
                    require_path=True,
                    require_claims=bool(item.get("claims")),
                    check_ranges=True,
                )
            except Exception:
                # soft: keep raw if score present
                try:
                    score = float(item.get("score") or 0)
                except (TypeError, ValueError):
                    continue
                if score < min_score:
                    continue
                g = dict(item)
                g["score"] = score
            if float(g.get("score") or 0) < min_score:
                continue
            seen.add(repo)
            g.setdefault("source", str(p))
            out.append(g)
    return out


def _candidate_query(grade: dict[str, Any]) -> str:
    """Build an FTS query from grade fields + first claim."""
    parts: list[str] = []
    for key in ("repo", "pattern", "summary"):
        val = str(grade.get(key) or "").strip()
        if val:
            parts.append(val)
    claims = grade.get("claims") or []
    if isinstance(claims, list):
        for c in claims[:2]:
            if isinstance(c, dict):
                st = str(c.get("statement") or "").strip()
                if st:
                    parts.append(st)
                    break
    # Prefer distinctive tokens: repo slug + key phrases
    repo = str(grade.get("repo") or "")
    slug = repo.split("/")[-1] if repo else ""
    if slug and slug not in " ".join(parts):
        parts.insert(0, slug)
    return " ".join(parts)[:240] or "multi agent"


def _evidence_for_grade(
    grade: dict[str, Any],
    *,
    workdir: Path,
    k: int = 5,
    query_override: Optional[str] = None,
) -> list[dict[str, Any]]:
    q = (query_override or _candidate_query(grade)).strip()
    if not q:
        return []
    try:
        res = search_evidence(q, workdir=workdir, k=k, auto_index=False)
    except Exception:
        return []
    hits = list(res.get("hits") or [])
    # Prefer hits that mention this repo
    repo = str(grade.get("repo") or "").lower()
    slug = repo.split("/")[-1] if repo else ""
    ranked: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for h in hits:
        blob = json.dumps(h, default=str).lower()
        if (repo and repo in blob) or (slug and slug in blob):
            ranked.append(h)
        else:
            rest.append(h)
    return (ranked + rest)[:k]


def rank_score(
    grade: dict[str, Any],
    evidence_hits: Sequence[dict[str, Any]],
    *,
    preference_delta: float = 0.0,
) -> float:
    """Composite rank: grade score + capped evidence boost + preference delta.

    *preference_delta* is typically ``preference_boost(repo)`` from offline
    better>worse pairs (arXiv 2602.04518), clamped in that helper to ±1.5.
    """
    try:
        base = float(grade.get("score") or 0)
    except (TypeError, ValueError):
        base = 0.0
    n = min(len(evidence_hits), EVIDENCE_HIT_CAP)
    try:
        pref = float(preference_delta or 0.0)
    except (TypeError, ValueError):
        pref = 0.0
    return round(base + EVIDENCE_BOOST * n + pref, 4)


def select_candidates(
    workdir: Optional[Path | str] = None,
    *,
    query: str = "",
    min_score: float = 10.0,
    limit: int = 5,
    fixture: Optional[Path | str] = None,
    require_evidence: bool = True,
    auto_index: bool = True,
    k_evidence: int = 5,
    use_preference: bool = True,
) -> dict[str, Any]:
    """Rank apply candidates by grade score + FTS evidence hits + preference.

    When *query* is set, also runs a global FTS search and boosts matching repos.
    When *require_evidence* is True, candidates with zero evidence hits are
    excluded (fail-closed for ungrounded applies).
    When *use_preference* is True (default), offline preference pairs bias rank
    via ``preference_boost`` (wins−losses, capped).
    """
    root = _root(workdir)
    index_report: Optional[dict[str, Any]] = None
    if auto_index:
        try:
            index_report = index_workspace(root)
        except Exception as e:
            index_report = {"ok": False, "error": str(e)}

    # Gather candidates: fixtures first (tests), then digests
    grades = _fixture_grades(root, fixture=fixture, min_score=min_score)
    seen = {str(g.get("repo") or "") for g in grades}
    try:
        for g in list_graded_candidates(root, min_score=min_score, limit=max(limit * 3, 20)):
            repo = str(g.get("repo") or "")
            if repo and repo not in seen:
                seen.add(repo)
                grades.append(g)
    except Exception:
        pass

    # Global query → boost matching repos
    global_hits: list[dict[str, Any]] = []
    repo_from_query: set[str] = set()
    if query.strip():
        try:
            gres = search_evidence(query, workdir=root, k=max(k_evidence, limit * 2), auto_index=False)
            global_hits = list(gres.get("hits") or [])
            for h in global_hits:
                r = str(h.get("repo") or "").strip()
                if r:
                    repo_from_query.add(r)
        except Exception:
            pass

    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for g in grades:
        repo = str(g.get("repo") or "")
        hits = _evidence_for_grade(g, workdir=root, k=k_evidence)
        # If global query set, also count global hits for this repo
        if repo_from_query and repo in repo_from_query:
            extra = [h for h in global_hits if str(h.get("repo") or "") == repo]
            # merge by id
            seen_ids = {str(h.get("id") or id(h)) for h in hits}
            for h in extra:
                hid = str(h.get("id") or id(h))
                if hid not in seen_ids:
                    hits.append(h)
                    seen_ids.add(hid)
        # claim-level evidence from grade itself counts when FTS empty
        claim_paths = []
        for c in g.get("claims") or []:
            if isinstance(c, dict) and c.get("path"):
                claim_paths.append(str(c["path"]))
        if not hits and claim_paths:
            # synthetic evidence from Thucy claims (offline, no FTS needed)
            hits = [
                {
                    "id": f"claim:{repo}:{i}",
                    "kind": "claim",
                    "repo": repo,
                    "path": p,
                    "statement": (g.get("claims") or [{}])[i].get("statement", "")
                    if isinstance((g.get("claims") or [None])[i], dict)
                    else "",
                    "source": "grade.claims",
                }
                for i, p in enumerate(claim_paths[:k_evidence])
            ]

        pref_delta = 0.0
        if use_preference and repo:
            try:
                from .preference_pairs import preference_boost

                pref_delta = float(preference_boost(repo, root))
            except Exception:
                pref_delta = 0.0

        rs = rank_score(g, hits, preference_delta=pref_delta)
        # boost if global query matched
        if query.strip() and repo in repo_from_query:
            rs = round(rs + 1.0, 4)

        claim_check = verify_or_report(g)
        row = {
            "repo": repo,
            "score": float(g.get("score") or 0),
            "idea": g.get("idea"),
            "skill": g.get("skill"),
            "method": g.get("method"),
            "path": g.get("path"),
            "pattern": g.get("pattern") or "",
            "rank": rs,
            "preference_boost": round(pref_delta, 4),
            "evidence_hits": len(hits),
            "evidence": [
                {
                    "id": h.get("id"),
                    "kind": h.get("kind"),
                    "path": h.get("path"),
                    "statement": (h.get("statement") or h.get("text") or "")[:200],
                    "arxiv_id": h.get("arxiv_id"),
                    "repo": h.get("repo"),
                }
                for h in hits[:k_evidence]
            ],
            "claim_ok": bool(claim_check.get("ok")),
            "claims": len(g.get("claims") or []),
            "source": g.get("source") or "",
        }
        if require_evidence and not hits:
            skipped.append({**row, "skip_reason": "no_evidence"})
            continue
        if not claim_check.get("ok") and require_evidence:
            skipped.append(
                {
                    **row,
                    "skip_reason": "claim_verify_failed",
                    "claim_reasons": claim_check.get("reasons"),
                }
            )
            continue
        candidates.append(row)

    candidates.sort(key=lambda c: (-float(c.get("rank") or 0), c.get("repo") or ""))
    selected = candidates[: max(1, int(limit))]

    return {
        "schema": SCHEMA,
        "ok": True,
        "workdir": str(root),
        "query": query,
        "min_score": min_score,
        "require_evidence": require_evidence,
        "use_preference": bool(use_preference),
        "count": len(selected),
        "total_considered": len(grades),
        "candidates": selected,
        "skipped": skipped[:20],
        "global_hits": len(global_hits),
        "index": {
            "ok": bool((index_report or {}).get("ok", index_report is None)),
            "docs": (index_report or {}).get("docs"),
            "grades_indexed": (index_report or {}).get("grades_indexed"),
        }
        if index_report is not None
        else None,
        "ts": time.time(),
    }


def gate_apply(
    candidate: dict[str, Any],
    *,
    grader: str = DEFAULT_ROLES["grader"],
    implementer: str = DEFAULT_ROLES["implementer"],
    verifier: str = DEFAULT_ROLES["verifier"],
    require_distinct_roles: bool = True,
    min_verify_score: Optional[float] = None,
    budget: Optional[RunBudget] = None,
    budget_tokens: int = 0,
    budget_steps: int = 1,
) -> dict[str, Any]:
    """Role + independent-verify + budget gate before apply.

    Returns decision package fragment with ok True/False.
    """
    role_res = check_roles(
        grader=grader,
        implementer=implementer,
        verifier=verifier,
        require_distinct=require_distinct_roles,
    )
    if not role_res.get("ok"):
        return {
            "schema": DECISION_SCHEMA,
            "ok": False,
            "reason": role_res.get("reason"),
            "roles": role_res.get("roles"),
            "collisions": role_res.get("collisions"),
            "candidate": {"repo": candidate.get("repo"), "score": candidate.get("score")},
        }

    # Independent verify: verifier must pass with candidate score + evidence paths
    score = candidate.get("score")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    evidence_paths = [
        str(e.get("path") or e.get("statement") or "")
        for e in (candidate.get("evidence") or [])
        if e
    ]
    # also accept claim paths
    if not evidence_paths and candidate.get("path"):
        evidence_paths = [str(candidate["path"])]

    iv = IndependentVerify(
        min_score=float(min_verify_score) if min_verify_score is not None else 0.0,
        require_pass=False,  # offline path: score + cross-agent is enough
        require_cross_agent=require_distinct_roles,
        require_evidence=True,
        fail_closed=True,
    )
    # IndependentVerify compares implementer vs verifier (not grader)
    vres: VerifyResult = iv.evaluate(
        implementer=implementer,
        verifier=verifier,
        score=score_f if score_f is not None else 0.0,
        decision="pass" if (score_f is not None and score_f >= float(iv.min_score)) else "revise",
        evidence=evidence_paths,
    )
    if not vres.ok:
        return {
            "schema": DECISION_SCHEMA,
            "ok": False,
            "reason": f"verify_failed:{vres.reason}",
            "roles": role_res["roles"],
            "verify": vres.to_dict(),
            "candidate": {"repo": candidate.get("repo"), "score": candidate.get("score")},
        }

    # Budget gate
    budget_snap: Optional[dict[str, Any]] = None
    if budget is not None:
        try:
            budget.consume(
                steps=int(budget_steps or 0),
                tokens=int(budget_tokens or 0),
                check=True,
            )
            budget_snap = budget.snapshot()
            if budget.soft_stop:
                return {
                    "schema": DECISION_SCHEMA,
                    "ok": False,
                    "reason": f"budget_soft_stop:{budget.soft_reason}",
                    "roles": role_res["roles"],
                    "verify": vres.to_dict(),
                    "budget": budget_snap,
                    "candidate": {
                        "repo": candidate.get("repo"),
                        "score": candidate.get("score"),
                    },
                }
        except BudgetExhausted as e:
            return {
                "schema": DECISION_SCHEMA,
                "ok": False,
                "reason": f"budget_exhausted:{e.kind}",
                "roles": role_res["roles"],
                "verify": vres.to_dict(),
                "budget": e.to_dict(),
                "candidate": {
                    "repo": candidate.get("repo"),
                    "score": candidate.get("score"),
                },
            }

    # confidence: normalize score 0–20 → 0–1 (mine scores often 0–20 scale)
    conf = 0.0
    if score_f is not None:
        conf = max(0.0, min(1.0, score_f / 20.0))
    # bump confidence with evidence density
    conf = min(1.0, conf + 0.05 * min(int(candidate.get("evidence_hits") or 0), 4))

    return {
        "schema": DECISION_SCHEMA,
        "ok": True,
        "reason": "apply_allowed",
        "roles": role_res["roles"],
        "role_check": role_res,
        "verify": vres.to_dict(),
        "budget": budget_snap,
        "confidence": round(conf, 4),
        "candidate": {
            "repo": candidate.get("repo"),
            "score": candidate.get("score"),
            "idea": candidate.get("idea"),
            "skill": candidate.get("skill"),
            "path": candidate.get("path"),
            "pattern": candidate.get("pattern"),
            "rank": candidate.get("rank"),
            "evidence_hits": candidate.get("evidence_hits"),
        },
        "evidence_refs": evidence_paths[:10],
        "claims_summary": [
            e.get("statement")
            for e in (candidate.get("evidence") or [])[:5]
            if e.get("statement")
        ],
        "ts": time.time(),
    }


def candidate_from_grade(grade: dict[str, Any]) -> dict[str, Any]:
    """Build a gate_apply candidate row from a raw grade artifact.

    Used by worktree_apply / alive self_approve when a grade is already loaded
    (skips FTS select but still produces Thucy claim evidence refs).
    """
    if not isinstance(grade, dict):
        raise ApplySelectError("grade must be a dict")
    repo = str(grade.get("repo") or "").strip()
    if not repo:
        raise ApplySelectError("grade.repo required")
    try:
        score = float(grade.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    evidence: list[dict[str, Any]] = []
    claims = grade.get("claims") or []
    if isinstance(claims, list):
        for i, c in enumerate(claims):
            if not isinstance(c, dict):
                continue
            path = str(c.get("path") or grade.get("path") or "").strip()
            statement = str(c.get("statement") or "").strip()
            if not path and not statement:
                continue
            evidence.append(
                {
                    "id": f"claim:{repo}:{i}",
                    "kind": "claim",
                    "repo": repo,
                    "path": path or str(grade.get("path") or ""),
                    "statement": statement,
                    "source": "grade.claims",
                }
            )
    if not evidence and grade.get("path"):
        evidence.append(
            {
                "id": f"path:{repo}",
                "kind": "path",
                "repo": repo,
                "path": str(grade.get("path")),
                "statement": str(grade.get("summary") or grade.get("pattern") or "")[
                    :200
                ],
                "source": "grade.path",
            }
        )
    hits = len(evidence)
    row = {
        "repo": repo,
        "score": score,
        "idea": grade.get("idea"),
        "skill": grade.get("skill"),
        "method": grade.get("method"),
        "path": grade.get("path"),
        "pattern": grade.get("pattern") or "",
        "rank": rank_score({"score": score}, evidence),
        "evidence_hits": hits,
        "evidence": evidence,
        "claims": len(claims) if isinstance(claims, list) else 0,
        "claim_ok": bool(evidence),
        "source": grade.get("source") or "",
    }
    return row


def decision_for_grade(
    grade: dict[str, Any],
    *,
    grader: str = DEFAULT_ROLES["grader"],
    implementer: str = DEFAULT_ROLES["implementer"],
    verifier: str = DEFAULT_ROLES["verifier"],
    require_distinct_roles: bool = True,
    min_verify_score: Optional[float] = None,
    budget: Optional[RunBudget] = None,
    max_steps: Optional[int] = None,
    max_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """Terminal decision package from an already-loaded grade (no FTS select).

    Wire point for worktree_apply before plan_apply and alive self_approve.
    """
    cand = candidate_from_grade(grade)
    if budget is None and (max_steps is not None or max_tokens is not None):
        budget = RunBudget(max_steps=max_steps, max_tokens=max_tokens, hard=True)
    gate = gate_apply(
        cand,
        grader=grader,
        implementer=implementer,
        verifier=verifier,
        require_distinct_roles=require_distinct_roles,
        min_verify_score=min_verify_score,
        budget=budget,
        budget_steps=1,
    )
    gate["goal"] = (
        f"apply pattern from {cand.get('repo')} "
        f"(score={cand.get('score')}, evidence={cand.get('evidence_hits')})"
    )
    gate["action_order"] = [
        {"agent": grader, "action": "grade"},
        {"agent": implementer, "action": "apply"},
        {"agent": verifier, "action": "verify"},
    ]
    gate["candidate"] = {
        **(gate.get("candidate") or {}),
        "rank": cand.get("rank"),
        "evidence_hits": cand.get("evidence_hits"),
        "pattern": cand.get("pattern"),
        "path": cand.get("path"),
    }
    return gate


# Gap ids written onto PrincipledStop when board signals replan/stop
BOARD_GAP_REPLAN = "board-replan"
BOARD_GAP_STOP = "board-stop"
BOARD_SIGNAL_GAPS = frozenset({BOARD_GAP_REPLAN, BOARD_GAP_STOP})


def _slug_gap_suffix(reason: str, *, max_len: int = 40) -> str:
    """Stable short id fragment from a signal reason (path-safe)."""
    import re

    s = re.sub(r"[^A-Za-z0-9._+-]+", "-", str(reason or "").strip().lower())
    s = s.strip("-")[:max_len].strip("-")
    return s or "unknown"


def sync_signal_to_stop(
    stopper: Any,
    signal: Optional[dict[str, Any] | str] = None,
    *,
    reason: str = "",
    detail: str = "",
    hints: Optional[Sequence[str]] = None,
    abort_on_hard_stop: bool = True,
    close_on_continue: bool = True,
) -> dict[str, Any]:
    """Wire improve board signal into a PrincipledStop gap board.

    zenith / MAEBE pattern:
      - ``replan`` → register ``board-replan`` (+ optional reason-specific id)
      - ``stop`` → register ``board-stop``; hard stops may ``abort()`` so watch exits
      - ``continue`` → close board signal gaps (progress cleared the thrash)

    Does not mutate stop when *signal* is empty/unknown. Returns a small audit
    dict suitable for alive report steps.
    """
    if signal is None:
        return {"ok": False, "skipped": "no_signal", "actions": []}

    if isinstance(signal, str):
        sig_name = signal.strip().lower()
        sig_reason = reason or sig_name
        sig_detail = detail
        sig_hints = list(hints or [])
        # reconstruct minimal blob for hard-stop heuristics
        signal = {
            "signal": sig_name,
            "reason": sig_reason,
            "detail": sig_detail,
            "hints": sig_hints,
        }
    else:
        sig_name = str(signal.get("signal") or "").strip().lower()
        sig_reason = str(reason or signal.get("reason") or sig_name)
        sig_detail = str(detail or signal.get("detail") or "")
        sig_hints = list(hints if hints is not None else (signal.get("hints") or []))

    if sig_name not in BOARD_SIGNALS:
        return {
            "ok": False,
            "skipped": f"unknown_signal:{sig_name or 'empty'}",
            "actions": [],
        }

    if stopper is None or not hasattr(stopper, "register_gap"):
        return {"ok": False, "skipped": "no_stopper", "actions": []}

    actions: list[dict[str, Any]] = []
    evidence = sig_detail or sig_reason
    if sig_hints:
        evidence = (evidence + " | hints: " + "; ".join(str(h) for h in sig_hints[:4])).strip(
            " |"
        )

    if sig_name == SIGNAL_REPLAN:
        g = stopper.register_gap(
            BOARD_GAP_REPLAN,
            f"board replan: {sig_reason}",
            evidence=evidence or f"signal=replan reason={sig_reason}",
        )
        actions.append({"action": "register", "gap_id": g.id, "signal": SIGNAL_REPLAN})
        # Secondary reason-scoped gap so operators can close specific thrash causes
        suffix = _slug_gap_suffix(sig_reason)
        if suffix and suffix not in {"replan", "board-replan", BOARD_GAP_REPLAN}:
            rid = f"{BOARD_GAP_REPLAN}:{suffix}"
            g2 = stopper.register_gap(
                rid,
                f"board replan detail: {sig_reason}",
                evidence=evidence,
            )
            actions.append({"action": "register", "gap_id": g2.id, "signal": SIGNAL_REPLAN})
        # Clear stop gap if we only need replan (not a hard stop)
        if close_on_continue and BOARD_GAP_STOP in getattr(stopper, "gaps", {}):
            try:
                stopper.close_gap(BOARD_GAP_STOP, evidence="signal=replan (not stop)")
                actions.append({"action": "close", "gap_id": BOARD_GAP_STOP})
            except KeyError:
                pass

    elif sig_name == SIGNAL_STOP:
        g = stopper.register_gap(
            BOARD_GAP_STOP,
            f"board stop: {sig_reason}",
            evidence=evidence or f"signal=stop reason={sig_reason}",
        )
        actions.append({"action": "register", "gap_id": g.id, "signal": SIGNAL_STOP})
        suffix = _slug_gap_suffix(sig_reason)
        if suffix and suffix not in {"stop", "board-stop", BOARD_GAP_STOP}:
            rid = f"{BOARD_GAP_STOP}:{suffix}"
            g2 = stopper.register_gap(
                rid,
                f"board stop detail: {sig_reason}",
                evidence=evidence,
            )
            actions.append({"action": "register", "gap_id": g2.id, "signal": SIGNAL_STOP})

        # Hard stops (collusion / budget / principled) abort so watch() exits
        hard = any(
            k in sig_reason.lower()
            for k in (
                "collusion",
                "budget",
                "principled_stop",
                "role_collusion",
                "abort",
            )
        )
        if abort_on_hard_stop and hard and hasattr(stopper, "abort"):
            # only abort once
            if not bool(getattr(stopper, "aborted", False)):
                stopper.abort(f"board_signal:{sig_reason}")
                actions.append(
                    {
                        "action": "abort",
                        "reason": f"board_signal:{sig_reason}",
                        "signal": SIGNAL_STOP,
                    }
                )

    elif sig_name == SIGNAL_CONTINUE:
        if close_on_continue:
            for gid in list(BOARD_SIGNAL_GAPS):
                gaps = getattr(stopper, "gaps", {}) or {}
                item = gaps.get(gid)
                if item is not None and getattr(item, "open", False):
                    stopper.close_gap(
                        gid,
                        evidence=evidence or f"signal=continue reason={sig_reason}",
                    )
                    actions.append({"action": "close", "gap_id": gid, "signal": SIGNAL_CONTINUE})
            # close reason-scoped board-* children that are still open
            for gid, item in list((getattr(stopper, "gaps", {}) or {}).items()):
                if not getattr(item, "open", False):
                    continue
                if gid.startswith(BOARD_GAP_REPLAN + ":") or gid.startswith(
                    BOARD_GAP_STOP + ":"
                ):
                    stopper.close_gap(
                        gid,
                        evidence=evidence or "signal=continue",
                    )
                    actions.append(
                        {"action": "close", "gap_id": gid, "signal": SIGNAL_CONTINUE}
                    )

    counts = stopper.gap_counts() if hasattr(stopper, "gap_counts") else {}
    return {
        "ok": True,
        "signal": sig_name,
        "reason": sig_reason,
        "actions": actions,
        "gaps": counts,
        "aborted": bool(getattr(stopper, "aborted", False)),
    }


def board_signal(
    *,
    decision: Optional[dict[str, Any]] = None,
    roles_ok: bool = True,
    candidates: Optional[Sequence[dict[str, Any]]] = None,
    skipped: Optional[Sequence[dict[str, Any]]] = None,
    stop_decision: Optional[dict[str, Any]] = None,
    low_confidence: float = LOW_CONFIDENCE,
) -> dict[str, Any]:
    """Derive continue | replan | stop for the improve board / alive loop.

    Priority (fail-closed for safety signals first):
      1. PrincipledStop hard stop → stop
      2. Role collusion / budget hard deny → stop
      3. No candidates / verify soft fail / low confidence → replan
      4. Decision allow → continue

    Patterns: zenith adaptive stop/replan; MAEBE thrash telemetry;
    arXiv 2511.15755 decision package before act.
    """
    cands = list(candidates or [])
    skipped_n = len(list(skipped or []))
    dec = decision or {}
    hints: list[str] = []

    # 1) Explicit principled stop from alive/zenith board
    if isinstance(stop_decision, dict) and stop_decision.get("stop"):
        reason = str(stop_decision.get("reason") or "principled_stop")
        return {
            "signal": SIGNAL_STOP,
            "reason": f"principled_stop:{reason}",
            "detail": str(stop_decision.get("detail") or ""),
            "hints": ["close remaining gaps or raise stop_max_cycles"],
            "decision_ok": bool(dec.get("ok")),
        }

    # 2) Role collusion / budget — hard stop (do not thrash apply)
    if not roles_ok:
        return {
            "signal": SIGNAL_STOP,
            "reason": "role_collusion",
            "detail": "grader/implementer/verifier must be distinct",
            "hints": [
                "set distinct --grader / --implementer / --verifier",
                "anti-collusion arXiv 2601.00360",
            ],
            "decision_ok": False,
        }

    reason = str(dec.get("reason") or "")
    if dec and not dec.get("ok"):
        if "collusion" in reason:
            return {
                "signal": SIGNAL_STOP,
                "reason": reason,
                "detail": "role separation failed",
                "hints": ["split grader ≠ implementer ≠ verifier"],
                "decision_ok": False,
            }
        if "budget" in reason:
            return {
                "signal": SIGNAL_STOP,
                "reason": reason,
                "detail": "run budget exhausted or soft-stop",
                "hints": ["raise max_steps/max_tokens or wait for budget reset"],
                "decision_ok": False,
            }
        # Soft denies → replan
        if "verify_failed" in reason or "no_candidates" in reason or "repo_not" in reason:
            hints.append("re-index evidence FTS / lower --min-score / pick another repo")
            return {
                "signal": SIGNAL_REPLAN,
                "reason": reason or "decision_denied",
                "detail": "decision package denied — replan before apply",
                "hints": hints,
                "decision_ok": False,
            }
        return {
            "signal": SIGNAL_REPLAN,
            "reason": reason or "decision_denied",
            "detail": "apply not allowed; replan backlog",
            "hints": ["inspect decision.reason and evidence_refs"],
            "decision_ok": False,
        }

    # 3) Empty board → replan (not stop — operator can lower bar)
    if not cands:
        return {
            "signal": SIGNAL_REPLAN,
            "reason": "no_candidates",
            "detail": f"no ranked candidates (skipped={skipped_n})",
            "hints": [
                "index fixtures (make mcp-smoke)",
                "lower --min-score",
                "add claims to grade digests",
            ],
            "decision_ok": False,
        }

    # 4) Low confidence allow → replan rather than hard apply
    conf = dec.get("confidence")
    try:
        conf_f = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf_f = None
    if conf_f is not None and conf_f < float(low_confidence):
        return {
            "signal": SIGNAL_REPLAN,
            "reason": f"low_confidence:{conf_f}",
            "detail": f"confidence {conf_f} < {low_confidence}",
            "hints": ["gather more evidence hits", "prefer higher-score candidate"],
            "decision_ok": bool(dec.get("ok")),
            "confidence": conf_f,
        }

    # 5) Decision allow → continue
    if dec.get("ok"):
        return {
            "signal": SIGNAL_CONTINUE,
            "reason": str(dec.get("reason") or "apply_allowed"),
            "detail": (
                f"apply { (dec.get('candidate') or {}).get('repo') } "
                f"confidence={dec.get('confidence')}"
            ),
            "hints": [],
            "decision_ok": True,
            "confidence": dec.get("confidence"),
        }

    # No decision yet but candidates exist → continue toward decide
    return {
        "signal": SIGNAL_CONTINUE,
        "reason": "candidates_ready",
        "detail": f"{len(cands)} candidate(s); run decide before apply",
        "hints": ["nexus improve decide --repo <top>"],
        "decision_ok": False,
    }


def decision_package(
    workdir: Optional[Path | str] = None,
    *,
    repo: Optional[str] = None,
    query: str = "",
    min_score: float = 10.0,
    fixture: Optional[Path | str] = None,
    grader: str = DEFAULT_ROLES["grader"],
    implementer: str = DEFAULT_ROLES["implementer"],
    verifier: str = DEFAULT_ROLES["verifier"],
    require_distinct_roles: bool = True,
    require_evidence: bool = True,
    max_steps: Optional[int] = None,
    max_tokens: Optional[int] = None,
    auto_index: bool = True,
) -> dict[str, Any]:
    """Build a terminal decision package for the top (or named) candidate.

    Combines select_candidates + gate_apply into one auditable artifact
    (2511.15755 decision package shape).
    """
    root = _root(workdir)
    sel = select_candidates(
        root,
        query=query or (repo or ""),
        min_score=min_score,
        limit=10,
        fixture=fixture,
        require_evidence=require_evidence,
        auto_index=auto_index,
    )
    cands = list(sel.get("candidates") or [])
    chosen: Optional[dict[str, Any]] = None
    if repo:
        repo_s = str(repo).strip()
        for c in cands:
            if c.get("repo") == repo_s or str(c.get("repo") or "").endswith(
                "/" + repo_s.split("/")[-1]
            ):
                chosen = c
                break
        if chosen is None:
            # try skipped for better error
            pkg = {
                "schema": DECISION_SCHEMA,
                "ok": False,
                "reason": f"repo_not_selected:{repo_s}",
                "selection": {
                    "count": sel.get("count"),
                    "skipped": len(sel.get("skipped") or []),
                },
                "candidates": [c.get("repo") for c in cands],
            }
            pkg["signal"] = board_signal(
                decision=pkg,
                roles_ok=True,
                candidates=cands,
                skipped=sel.get("skipped") or [],
            )
            return pkg
    elif cands:
        chosen = cands[0]
    else:
        pkg = {
            "schema": DECISION_SCHEMA,
            "ok": False,
            "reason": "no_candidates",
            "selection": sel,
        }
        pkg["signal"] = board_signal(
            decision=pkg,
            roles_ok=True,
            candidates=[],
            skipped=sel.get("skipped") or [],
        )
        return pkg

    budget = None
    if max_steps is not None or max_tokens is not None:
        budget = RunBudget(max_steps=max_steps, max_tokens=max_tokens, hard=True)

    gate = gate_apply(
        chosen,
        grader=grader,
        implementer=implementer,
        verifier=verifier,
        require_distinct_roles=require_distinct_roles,
        budget=budget,
        budget_steps=1,
    )
    gate["selection"] = {
        "query": sel.get("query"),
        "count": sel.get("count"),
        "rank": chosen.get("rank"),
        "index": sel.get("index"),
    }
    gate["goal"] = (
        f"apply pattern from {chosen.get('repo')} "
        f"(score={chosen.get('score')}, evidence={chosen.get('evidence_hits')})"
    )
    gate["action_order"] = [
        {"agent": grader, "action": "grade"},
        {"agent": implementer, "action": "apply"},
        {"agent": verifier, "action": "verify"},
    ]
    role_ok = True
    if require_distinct_roles:
        role_ok = bool(
            check_roles(
                grader=grader,
                implementer=implementer,
                verifier=verifier,
                require_distinct=True,
            ).get("ok")
        )
    gate["signal"] = board_signal(
        decision=gate,
        roles_ok=role_ok,
        candidates=cands,
        skipped=sel.get("skipped") or [],
    )
    return gate


def improve_board(
    workdir: Optional[Path | str] = None,
    *,
    query: str = "",
    min_score: float = 10.0,
    limit: int = 5,
    fixture: Optional[Path | str] = None,
    grader: str = DEFAULT_ROLES["grader"],
    implementer: str = DEFAULT_ROLES["implementer"],
    verifier: str = DEFAULT_ROLES["verifier"],
    goal: str = "self-improve nexus-core from mined repos + arXiv",
    auto_index: bool = True,
    stop_decision: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """routa-lite board: goal, roles, ranked candidates, evidence, decision, signal.

    Offline operator surface for the self-improve backlog. Includes zenith-style
    ``signal`` ∈ {continue, replan, stop} for alive / supervisor loops.
    """
    root = _root(workdir)
    sel = select_candidates(
        root,
        query=query,
        min_score=min_score,
        limit=limit,
        fixture=fixture,
        require_evidence=True,
        auto_index=auto_index,
    )
    top = (sel.get("candidates") or [None])[0]
    decision = None
    if top:
        decision = gate_apply(
            top,
            grader=grader,
            implementer=implementer,
            verifier=verifier,
            require_distinct_roles=True,
        )

    # Recent ledger traces (optional)
    traces: list[dict[str, Any]] = []
    try:
        from .decision_ledger import DecisionLedger

        with DecisionLedger.open(root) as led:
            for r in led.tail(limit=8):
                traces.append(
                    {
                        "agent": r.get("agent"),
                        "action": r.get("action"),
                        "run_id": r.get("run_id"),
                        "claim": (r.get("claim") or "")[:120],
                        "ts": r.get("ts"),
                    }
                )
    except Exception:
        pass

    role_res = check_roles(
        grader=grader,
        implementer=implementer,
        verifier=verifier,
        require_distinct=True,
    )

    signal = board_signal(
        decision=decision,
        roles_ok=bool(role_res.get("ok")),
        candidates=sel.get("candidates") or [],
        skipped=sel.get("skipped") or [],
        stop_decision=stop_decision,
    )

    return {
        "schema": BOARD_SCHEMA,
        "ok": True,
        "goal": goal,
        "roles": role_res.get("roles"),
        "roles_ok": bool(role_res.get("ok")),
        "role_reason": role_res.get("reason"),
        "candidates": sel.get("candidates") or [],
        "skipped": sel.get("skipped") or [],
        "decision": decision,
        "signal": signal.get("signal"),
        "signal_reason": signal.get("reason"),
        "signal_detail": signal.get("detail"),
        "replan_hints": list(signal.get("hints") or []),
        "signal_meta": signal,
        "traces": traces,
        "selection": {
            "query": sel.get("query"),
            "count": sel.get("count"),
            "total_considered": sel.get("total_considered"),
            "index": sel.get("index"),
        },
        "workdir": str(root),
        "ts": time.time(),
    }


def format_board(board: dict[str, Any]) -> str:
    """Human-readable routa-lite improve board."""
    lines = [
        "=== NEXUS improve board (routa-lite) ===",
        f"goal: {board.get('goal')}",
        f"roles: grader={ (board.get('roles') or {}).get('grader') }  "
        f"implementer={ (board.get('roles') or {}).get('implementer') }  "
        f"verifier={ (board.get('roles') or {}).get('verifier') }  "
        f"[{'OK' if board.get('roles_ok') else 'COLLISION'}]",
        "",
        "candidates (score + evidence + preference rank):",
    ]
    cands = board.get("candidates") or []
    if not cands:
        lines.append("  (none — index fixtures or lower --min-score)")
    for i, c in enumerate(cands, 1):
        pref = c.get("preference_boost")
        pref_s = f"  pref={pref:+.2f}" if pref not in (None, 0, 0.0) else ""
        lines.append(
            f"  {i}. {c.get('repo')}  score={c.get('score')}  "
            f"rank={c.get('rank')}  evidence={c.get('evidence_hits')}  "
            f"claims={c.get('claims')}{pref_s}"
        )
        for e in (c.get("evidence") or [])[:2]:
            st = (e.get("statement") or "")[:70]
            if st:
                lines.append(f"      · {st}")
    dec = board.get("decision") or {}
    lines.append("")
    if dec:
        status = "ALLOW" if dec.get("ok") else "DENY"
        lines.append(
            f"decision: {status}  reason={dec.get('reason')}  "
            f"confidence={dec.get('confidence', '—')}"
        )
        if dec.get("evidence_refs"):
            lines.append("evidence_refs:")
            for ref in dec["evidence_refs"][:5]:
                lines.append(f"  - {ref}")
    sig = board.get("signal") or (board.get("signal_meta") or {}).get("signal")
    if sig:
        lines.append(
            f"signal:   {str(sig).upper()}  "
            f"reason={board.get('signal_reason') or (board.get('signal_meta') or {}).get('reason')}"
        )
        for h in (board.get("replan_hints") or [])[:3]:
            lines.append(f"  hint: {h}")
    traces = board.get("traces") or []
    if traces:
        lines.append("")
        lines.append("recent traces:")
        for t in traces[:5]:
            lines.append(
                f"  {t.get('agent')}/{t.get('action')}  "
                f"{(t.get('claim') or '')[:50]}"
            )
    lines.append(f"workdir: {board.get('workdir')}")
    return "\n".join(lines)


def format_selection(sel: dict[str, Any]) -> str:
    """Human-readable selection report."""
    lines = [
        "=== NEXUS apply select (evidence-FTS) ===",
        f"query: {sel.get('query') or '(none)'}",
        f"considered: {sel.get('total_considered')}  "
        f"selected: {sel.get('count')}  "
        f"require_evidence: {sel.get('require_evidence')}",
    ]
    for i, c in enumerate(sel.get("candidates") or [], 1):
        pref = c.get("preference_boost")
        pref_s = f"  pref={pref:+.2f}" if pref not in (None, 0, 0.0) else ""
        lines.append(
            f"  {i}. {c.get('repo')}  score={c.get('score')}  "
            f"rank={c.get('rank')}  evidence={c.get('evidence_hits')}{pref_s}"
        )
    skipped = sel.get("skipped") or []
    if skipped:
        lines.append(f"skipped: {len(skipped)}")
        for s in skipped[:5]:
            lines.append(
                f"  - {s.get('repo')}: {s.get('skip_reason')}"
            )
    return "\n".join(lines)


def smoke_board_sync(
    workdir: Optional[Path | str] = None,
    *,
    fixture: Optional[Path | str] = None,
    sync_gaps: bool = True,
    abort_on_hard_stop: bool = True,
) -> dict[str, Any]:
    """Offline CI smoke: build improve board and optionally sync signal→gaps.

    Fail-closed: returns ``ok=False`` when board construction fails or signal
    is missing. Does not call the network.
    """
    from .durability.stop import PrincipledStop

    root = _root(workdir)
    fx = fixture
    if fx is None:
        preferred = root / "fixtures" / "mine_eval" / "grades_with_claims.json"
        sample = root / "tests" / "fixtures" / "mine_eval_sample.json"
        if preferred.is_file():
            fx = preferred
        elif sample.is_file():
            fx = sample

    try:
        board = improve_board(
            root,
            fixture=fx,
            auto_index=True,
            goal="smoke board --sync-gaps",
        )
    except Exception as e:
        return {
            "schema": BOARD_SCHEMA,
            "ok": False,
            "error": f"board_failed:{e}",
            "workdir": str(root),
        }

    signal = str(board.get("signal") or "")
    if signal not in BOARD_SIGNALS:
        return {
            "schema": BOARD_SCHEMA,
            "ok": False,
            "error": f"missing_or_invalid_signal:{signal!r}",
            "board": {
                "signal": board.get("signal"),
                "signal_reason": board.get("signal_reason"),
                "count": len(board.get("candidates") or []),
            },
            "workdir": str(root),
        }

    sync_report: Optional[dict[str, Any]] = None
    if sync_gaps:
        stop = PrincipledStop()
        try:
            sync_report = sync_signal_to_stop(
                stop,
                {
                    "signal": signal,
                    "reason": board.get("signal_reason"),
                    "detail": board.get("signal_detail"),
                    "hints": list(board.get("replan_hints") or []),
                },
                abort_on_hard_stop=abort_on_hard_stop,
                close_on_continue=True,
            )
            # Surface open gaps for operator / CI log
            if sync_report is not None and hasattr(stop, "gaps"):
                sync_report = {
                    **sync_report,
                    "open_gaps": [
                        gid
                        for gid, g in (stop.gaps or {}).items()
                        if getattr(g, "open", False)
                    ],
                    "aborted": bool(getattr(stop, "aborted", False)),
                }
        except Exception as e:
            return {
                "schema": BOARD_SCHEMA,
                "ok": False,
                "error": f"sync_failed:{e}",
                "signal": signal,
                "workdir": str(root),
            }

    cands = board.get("candidates") or []
    top = cands[0] if cands else None
    return {
        "schema": BOARD_SCHEMA,
        "ok": True,
        "signal": signal,
        "signal_reason": board.get("signal_reason"),
        "candidates": len(cands),
        "top_repo": (top or {}).get("repo"),
        "top_rank": (top or {}).get("rank"),
        "top_preference_boost": (top or {}).get("preference_boost"),
        "decision_ok": bool((board.get("decision") or {}).get("ok")),
        "roles_ok": bool(board.get("roles_ok")),
        "sync": sync_report,
        "workdir": str(root),
        "ts": time.time(),
    }


__all__ = [
    "SCHEMA",
    "BOARD_SCHEMA",
    "DECISION_SCHEMA",
    "DEFAULT_ROLES",
    "SIGNAL_CONTINUE",
    "SIGNAL_REPLAN",
    "SIGNAL_STOP",
    "BOARD_SIGNALS",
    "BOARD_GAP_REPLAN",
    "BOARD_GAP_STOP",
    "BOARD_SIGNAL_GAPS",
    "LOW_CONFIDENCE",
    "RoleCollusionError",
    "ApplySelectError",
    "check_roles",
    "require_roles",
    "select_candidates",
    "gate_apply",
    "candidate_from_grade",
    "decision_for_grade",
    "decision_package",
    "board_signal",
    "sync_signal_to_stop",
    "improve_board",
    "format_board",
    "format_selection",
    "rank_score",
    "smoke_board_sync",
]
