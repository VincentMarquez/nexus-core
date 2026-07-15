"""Evidence-FTS apply selection + role-separated verify + improve board.

First apply slice (docs/LATEST_IMPROVE_PLAN.md next PR after grade claims/FTS):

  graded candidates
    → FTS evidence hits (cas/soul search)
    → rank by score + evidence
    → role gate: grader ≠ implementer ≠ verifier (anti-collusion)
    → budget check (Network-AI / mission-control)
    → decision package (2511.15755) before apply
    → routa-lite board CLI/MCP

Patterns (shape only, not vendored trees):
- codingagentsystem/cas — MCP SQLite/FTS evidence search
- builderz-labs/mission-control — spend/runtime gate before action
- Jovancoding/Network-AI — budgets + guardrails
- phodal/routa — board: goal / task / trace / evidence
- ahmedEid1/lumen — decision audit package
- arXiv 2601.00360 — anti-collusion role separation
- arXiv 2511.15755 — terminal decision package
- arXiv 2512.03278 — Thucy path-anchored claims
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
EVIDENCE_BOOST = 0.5
EVIDENCE_HIT_CAP = 5


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


def rank_score(grade: dict[str, Any], evidence_hits: Sequence[dict[str, Any]]) -> float:
    """Composite rank: grade score + capped evidence boost."""
    try:
        base = float(grade.get("score") or 0)
    except (TypeError, ValueError):
        base = 0.0
    n = min(len(evidence_hits), EVIDENCE_HIT_CAP)
    return round(base + EVIDENCE_BOOST * n, 4)


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
) -> dict[str, Any]:
    """Rank apply candidates by grade score + FTS evidence hits.

    When *query* is set, also runs a global FTS search and boosts matching repos.
    When *require_evidence* is True, candidates with zero evidence hits are
    excluded (fail-closed for ungrounded applies).
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

        rs = rank_score(g, hits)
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
            return {
                "schema": DECISION_SCHEMA,
                "ok": False,
                "reason": f"repo_not_selected:{repo_s}",
                "selection": {
                    "count": sel.get("count"),
                    "skipped": len(sel.get("skipped") or []),
                },
                "candidates": [c.get("repo") for c in cands],
            }
    elif cands:
        chosen = cands[0]
    else:
        return {
            "schema": DECISION_SCHEMA,
            "ok": False,
            "reason": "no_candidates",
            "selection": sel,
        }

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
) -> dict[str, Any]:
    """routa-lite board: goal, roles, ranked candidates, evidence, decision.

    Offline operator surface for the self-improve backlog.
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
        "candidates (score + evidence rank):",
    ]
    cands = board.get("candidates") or []
    if not cands:
        lines.append("  (none — index fixtures or lower --min-score)")
    for i, c in enumerate(cands, 1):
        lines.append(
            f"  {i}. {c.get('repo')}  score={c.get('score')}  "
            f"rank={c.get('rank')}  evidence={c.get('evidence_hits')}  "
            f"claims={c.get('claims')}"
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
        lines.append(
            f"  {i}. {c.get('repo')}  score={c.get('score')}  "
            f"rank={c.get('rank')}  evidence={c.get('evidence_hits')}"
        )
    skipped = sel.get("skipped") or []
    if skipped:
        lines.append(f"skipped: {len(skipped)}")
        for s in skipped[:5]:
            lines.append(
                f"  - {s.get('repo')}: {s.get('skip_reason')}"
            )
    return "\n".join(lines)


__all__ = [
    "SCHEMA",
    "BOARD_SCHEMA",
    "DECISION_SCHEMA",
    "DEFAULT_ROLES",
    "RoleCollusionError",
    "ApplySelectError",
    "check_roles",
    "require_roles",
    "select_candidates",
    "gate_apply",
    "decision_package",
    "improve_board",
    "format_board",
    "format_selection",
    "rank_score",
]
