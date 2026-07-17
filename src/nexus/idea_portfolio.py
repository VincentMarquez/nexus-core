"""Build an implement portfolio: ≥1 arXiv + ≥1 GitHub idea, max N, plus cross-pattern novels.

Used by REAL alive self-improve so implement is never "random best mine only".
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir:
        return Path(workdir).resolve()
    import os

    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def _tokens(text: str) -> set[str]:
    stop = {
        "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "is",
        "are", "be", "as", "by", "from", "this", "that", "multi", "agent", "agents",
        "llm", "based", "using", "via", "into", "our", "we", "you", "it", "its",
    }
    words = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    return {w for w in words if w not in stop}


def collect_arxiv_ideas(root: Path, *, limit: int = 30) -> list[dict[str, Any]]:
    """Load ranked paper grades / PAPER_IMPROVE into idea dicts."""
    root = _root(root)
    ideas: list[dict[str, Any]] = []
    grades_dir = root / ".nexus_state" / "arxiv_improve"
    grade_files = sorted(
        grades_dir.glob("paper_grades-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    grades: list[dict[str, Any]] = []
    if grade_files:
        try:
            blob = json.loads(grade_files[0].read_text(encoding="utf-8"))
            grades = list(blob.get("grades") or [])
        except Exception:
            grades = []
    # Fallback: parse PAPER_IMPROVE markdown table lightly
    if not grades:
        pm = grades_dir / "PAPER_IMPROVE.md"
        if pm.is_file():
            for line in pm.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.search(
                    r"\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|.*?arxiv\.org/abs/([^)\s]+)",
                    line,
                )
                if m:
                    grades.append(
                        {
                            "repo_or_paper_id": f"arxiv:{m.group(3)}",
                            "score": float(m.group(2)),
                            "summary": line[:200],
                            "pattern": "from PAPER_IMPROVE table",
                        }
                    )

    for g in grades:
        pid = str(g.get("repo_or_paper_id") or g.get("repo") or "").strip()
        if not pid:
            continue
        ideas.append(
            {
                "source": "arxiv",
                "id": pid,
                "title": str(g.get("title") or pid)[:200],
                "score": float(g.get("score") or 0),
                "summary": str(g.get("summary") or g.get("pattern") or "")[:400],
                "pattern": str(g.get("pattern") or "")[:200],
                "concrete": str(g.get("summary") or g.get("claims") or "")[:400],
                "effort": g.get("effort"),
                "url": (
                    f"https://arxiv.org/abs/{pid.split(':', 1)[-1]}"
                    if "arxiv" in pid or re.match(r"\d{4}\.\d+", pid)
                    else ""
                ),
            }
        )
    ideas.sort(key=lambda x: -float(x.get("score") or 0))
    return ideas[: max(1, limit)]


def collect_github_ideas(root: Path, *, limit: int = 30, min_score: float = 0.0) -> list[dict[str, Any]]:
    """Load scored mined repos + high-star review into idea dicts."""
    root = _root(root)
    ideas: list[dict[str, Any]] = []
    seen: set[str] = set()

    # From repo_mine SQLite
    try:
        from . import repo_mine as rm

        conn = rm.connect(root)
        rows = rm.list_entries(conn, min_score=min_score, limit=max(limit * 2, 20))
        conn.close()
        for r in rows:
            repo = str(r.get("repo") or r.get("full_name") or "").strip()
            if not repo or repo in seen:
                continue
            seen.add(repo)
            ideas.append(
                {
                    "source": "github",
                    "id": repo,
                    "title": repo,
                    "score": float(r.get("score") or r.get("stars") or 0),
                    "stars": int(r.get("stars") or 0),
                    "summary": str(
                        r.get("summary") or r.get("description") or r.get("idea") or ""
                    )[:400],
                    "pattern": str(r.get("idea") or r.get("skill") or "")[:200],
                    "concrete": (
                        f"Port pattern from {repo}: "
                        f"{r.get('summary') or r.get('description') or 'architecture pattern'}"
                    )[:400],
                    "url": str(r.get("html_url") or f"https://github.com/{repo}"),
                    "local_path": r.get("local_path"),
                }
            )
    except Exception:
        pass

    # High-star markdown / JSON from this cycle
    for path in (
        root / ".nexus_state" / "repo_mine" / "GITHUB_HIGHSTAR.md",
        root / "docs" / "LATEST_GITHUB_REVIEW.md",
    ):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
            r"\*\*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\*\*.*?★\s*(\d+)",
            text,
        ):
            repo, stars = m.group(1), int(m.group(2))
            if repo in seen:
                continue
            seen.add(repo)
            # grab following description line if any
            ideas.append(
                {
                    "source": "github",
                    "id": repo,
                    "title": repo,
                    "score": float(stars),
                    "stars": stars,
                    "summary": f"High-star (≥5k catalog) repo ★{stars}",
                    "pattern": "high_star_catalog",
                    "concrete": f"Study and port one durable pattern from {repo} (★{stars})",
                    "url": f"https://github.com/{repo}",
                }
            )

    ideas.sort(key=lambda x: (-float(x.get("score") or 0), -int(x.get("stars") or 0)))
    return ideas[: max(1, limit)]


def cross_pattern_novel_ideas(
    arxiv: list[dict[str, Any]],
    github: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Spot shared themes across papers + repos → novel synthesis ideas.

    Heuristic: overlapping content tokens between an arXiv idea and a GitHub idea
    produce a hybrid implementable idea (not pure copy of either).
    """
    novels: list[dict[str, Any]] = []
    for a in arxiv[:15]:
        at = _tokens(
            f"{a.get('title')} {a.get('summary')} {a.get('pattern')} {a.get('concrete')}"
        )
        if len(at) < 3:
            continue
        for g in github[:15]:
            gt = _tokens(
                f"{g.get('title')} {g.get('summary')} {g.get('pattern')} {g.get('concrete')}"
            )
            if len(gt) < 3:
                continue
            # Domain seeds: force useful multi-agent / SWE overlaps even if sparse
            domain = {
                "consensus", "orchestr", "communic", "review", "tool", "plan",
                "bench", "durable", "protocol", "coord", "agent", "workflow",
                "memory", "judge", "test", "code", "harness", "pipeline",
            }
            # prefix match soft tokens
            soft_a = {t for t in at if any(t.startswith(d[:4]) or d.startswith(t[:4]) for d in domain)}
            soft_g = {t for t in gt if any(t.startswith(d[:4]) or d.startswith(t[:4]) for d in domain)}
            overlap = (at & gt) | (soft_a & soft_g)
            if len(overlap) < 1 and not (soft_a and soft_g):
                continue
            if len(overlap) < 1:
                # weak link: one shared domain family
                overlap = set(list(soft_a)[:2] + list(soft_g)[:2])
            union = at | gt
            jaccard = len(at & gt) / max(1, len(union))
            # allow weak-to-moderate coupling; skip near-duplicates
            if jaccard > 0.9:
                continue
            theme = ", ".join(sorted(overlap)[:8]) or "multi-agent coordination"
            novels.append(
                {
                    "source": "cross_pattern",
                    "id": f"novel:{a.get('id')}+{g.get('id')}",
                    "title": f"Cross-pattern: {theme[:80]}",
                    "score": float(a.get("score") or 0) * 0.5
                    + float(g.get("score") or 0) * 0.001
                    + len(overlap)
                    + (2.0 if jaccard >= 0.05 else 0.5),
                    "summary": (
                        f"Shared themes [{theme}] across paper {a.get('id')} "
                        f"and repo {g.get('id')}"
                    ),
                    "pattern": theme,
                    "concrete": (
                        f"Novel hybrid: apply arXiv idea «{(a.get('concrete') or a.get('summary') or '')[:120]}» "
                        f"using structure/pattern from GitHub «{g.get('id')}» "
                        f"«{(g.get('concrete') or g.get('summary') or '')[:120]}». "
                        f"Implement one small module + tests in nexus-core."
                    ),
                    "arxiv_id": a.get("id"),
                    "github_id": g.get("id"),
                    "overlap_tokens": sorted(overlap)[:12],
                    "url": a.get("url") or g.get("url") or "",
                }
            )
    # de-dupe by id
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for n in sorted(novels, key=lambda x: -float(x.get("score") or 0)):
        if n["id"] in seen:
            continue
        seen.add(n["id"])
        out.append(n)
        if len(out) >= limit:
            break
    return out


def _arxiv_seed(item: dict[str, Any]) -> str:
    """Canonical paper id for diversity caps (strip novel:/version)."""
    aid = str(item.get("arxiv_id") or item.get("id") or "")
    if aid.startswith("novel:"):
        # novel:arxiv:2401.07324v3+owner/repo
        body = aid[6:]
        if body.startswith("arxiv:"):
            body = body[6:]
        aid = body.split("+", 1)[0]
    if aid.startswith("arxiv:"):
        aid = aid[6:]
    # strip version vN
    if "v" in aid:
        base, _, rest = aid.rpartition("v")
        if rest.isdigit() and base:
            aid = base
    return aid.strip()


def select_portfolio(
    arxiv: list[dict[str, Any]],
    github: list[dict[str, Any]],
    novels: list[dict[str, Any]],
    *,
    min_arxiv: int = 1,
    min_github: int = 1,
    max_ideas: int = 10,
    max_per_arxiv_seed: int = 2,
    min_distinct_arxiv: int = 3,
) -> list[dict[str, Any]]:
    """Ensure ≥min_arxiv + ≥min_github, fill with novels then remaining best, cap max_ideas.

    Diversity (anti-monoculture):
      - at most ``max_per_arxiv_seed`` ideas (incl. cross_pattern) share one paper seed
      - try to include at least ``min_distinct_arxiv`` different papers when pool allows
    """
    max_ideas = max(2, min(int(max_ideas), 10))  # hard ceiling 10
    min_arxiv = max(1, int(min_arxiv))
    min_github = max(1, int(min_github))
    max_per_seed = max(1, int(max_per_arxiv_seed))
    min_distinct = max(1, int(min_distinct_arxiv))
    if min_arxiv + min_github > max_ideas:
        min_arxiv = 1
        min_github = 1

    portfolio: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    seed_counts: dict[str, int] = {}

    def can_take(it: dict[str, Any], *, enforce_seed: bool) -> bool:
        iid = str(it.get("id") or "")
        if not iid or iid in used_ids:
            return False
        if not enforce_seed:
            return True
        seed = _arxiv_seed(it)
        if not seed:
            return True
        return seed_counts.get(seed, 0) < max_per_seed

    def take(
        items: list[dict[str, Any]],
        n: int,
        source_tag: str,
        *,
        enforce_seed: bool = True,
    ) -> int:
        got = 0
        for it in items:
            if len(portfolio) >= max_ideas or got >= n:
                break
            if not can_take(it, enforce_seed=enforce_seed):
                continue
            iid = str(it.get("id") or "")
            used_ids.add(iid)
            seed = _arxiv_seed(it)
            if seed and enforce_seed:
                seed_counts[seed] = seed_counts.get(seed, 0) + 1
            row = dict(it)
            row["selected_as"] = source_tag
            portfolio.append(row)
            got += 1
        return got

    # Required quotas first (single arxiv + github seed ok)
    take(arxiv, min_arxiv, "required_arxiv", enforce_seed=True)
    take(github, min_github, "required_github", enforce_seed=False)

    # Pull additional distinct arXiv papers before flooding with same-seed crosses
    distinct_now = len({_arxiv_seed(p) for p in portfolio if _arxiv_seed(p)})
    need_distinct = max(0, min_distinct - distinct_now)
    if need_distinct > 0:
        # skip already-used seeds
        extra_arxiv = [
            a
            for a in arxiv
            if _arxiv_seed(a) and seed_counts.get(_arxiv_seed(a), 0) == 0
        ]
        take(extra_arxiv, need_distinct, "diversity_arxiv", enforce_seed=True)

    # Cross-patterns with seed cap (stops 7× same paper remixes)
    take(novels, max_ideas - len(portfolio), "cross_pattern", enforce_seed=True)

    # Fill remainder (still enforce seed cap — no flood of same-paper remixes)
    rest = sorted(
        list(arxiv) + list(github),
        key=lambda x: -float(x.get("score") or 0),
    )
    take(rest, max_ideas - len(portfolio), "fill", enforce_seed=True)
    # Last resort: more github-only / arxiv-only items without cross_pattern flood
    if len(portfolio) < max_ideas:
        take(github + arxiv, max_ideas - len(portfolio), "fill_sources", enforce_seed=True)

    for i, p in enumerate(portfolio, 1):
        p["rank"] = i

    return portfolio


def write_portfolio(
    root: Path,
    portfolio: list[dict[str, Any]],
    *,
    novels: Optional[list[dict[str, Any]]] = None,
    meta: Optional[dict[str, Any]] = None,
) -> Path:
    root = _root(root)
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    state = root / ".nexus_state"
    state.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Idea portfolio — implement ≥1 arXiv + ≥1 GitHub (max 10)",
        "",
        f"ts: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"count: {len(portfolio)}",
        f"meta: {json.dumps(meta or {}, default=str)[:500]}",
        "",
        "## Selected for implement",
        "",
    ]
    for p in portfolio:
        lines += [
            f"### {p.get('rank')}. [{p.get('source')}] {p.get('id')}",
            f"- selected_as: `{p.get('selected_as')}`",
            f"- score: {p.get('score')}  stars: {p.get('stars', '—')}",
            f"- title: {p.get('title')}",
            f"- concrete: {p.get('concrete') or p.get('summary')}",
            f"- url: {p.get('url') or '—'}",
            "",
        ]
    if novels:
        lines += ["## Cross-pattern novel candidates (spotted across papers + code)", ""]
        for n in novels[:8]:
            lines.append(
                f"- **{n.get('id')}**: {n.get('concrete') or n.get('summary')} "
                f"(overlap: {', '.join((n.get('overlap_tokens') or [])[:6])})"
            )
        lines.append("")

    lines += [
        "## Policy",
        "",
        "- REAL self-improve must implement **at least 1 arXiv** and **1 GitHub** idea.",
        "- Cap **10** ideas per cycle.",
        "- Prefer small modules + tests; fix_loop until green after each apply batch.",
        "",
    ]
    text = "\n".join(lines) + "\n"
    dest = docs / "LATEST_IDEA_PORTFOLIO.md"
    dest.write_text(text, encoding="utf-8")
    (state / "IDEA_PORTFOLIO.json").write_text(
        json.dumps(
            {"ts": time.time(), "portfolio": portfolio, "novels": novels or [], "meta": meta or {}},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (state / "IDEA_PORTFOLIO.md").write_text(text, encoding="utf-8")
    return dest


def build_portfolio(
    root: Path,
    *,
    min_arxiv: int = 1,
    min_github: int = 1,
    max_ideas: int = 10,
    min_github_score: float = 0.0,
) -> dict[str, Any]:
    """Full collect → cross-pattern → select → write."""
    root = _root(root)
    arxiv = collect_arxiv_ideas(root, limit=30)
    github = collect_github_ideas(root, limit=30, min_score=min_github_score)
    novels = cross_pattern_novel_ideas(arxiv, github, limit=8)
    portfolio = select_portfolio(
        arxiv,
        github,
        novels,
        min_arxiv=min_arxiv,
        min_github=min_github,
        max_ideas=max_ideas,
    )
    meta = {
        "min_arxiv": min_arxiv,
        "min_github": min_github,
        "max_ideas": max_ideas,
        "arxiv_pool": len(arxiv),
        "github_pool": len(github),
        "novel_pool": len(novels),
        "arxiv_selected": sum(1 for p in portfolio if p.get("source") == "arxiv"),
        "github_selected": sum(1 for p in portfolio if p.get("source") == "github"),
        "cross_selected": sum(1 for p in portfolio if p.get("source") == "cross_pattern"),
    }
    path = write_portfolio(root, portfolio, novels=novels, meta=meta)
    ok = (
        meta["arxiv_selected"] >= min_arxiv
        and meta["github_selected"] >= min_github
        and len(portfolio) <= max_ideas
    )
    return {
        "ok": ok,
        "path": str(path),
        "portfolio": portfolio,
        "novels": novels,
        "meta": meta,
        "error": None
        if ok
        else (
            f"quota unmet: need ≥{min_arxiv} arxiv + ≥{min_github} github "
            f"(got {meta['arxiv_selected']}/{meta['github_selected']}); "
            f"pools arxiv={meta['arxiv_pool']} github={meta['github_pool']}"
        ),
    }


def implement_portfolio(
    root: Path,
    portfolio: list[dict[str, Any]],
    *,
    worker: str = "auto",
    our_repo: str = "",
    apply: bool = True,
) -> dict[str, Any]:
    """Implement each selected idea (worker per idea). Returns per-idea results."""
    from . import grok_worker as gw
    from . import repo_mine as rm

    root = _root(root)
    results: list[dict[str, Any]] = []
    for idea in portfolio:
        goal = (
            f"IMPLEMENT idea from portfolio [{idea.get('source')}] {idea.get('id')}.\n"
            f"Title: {idea.get('title')}\n"
            f"Concrete change: {idea.get('concrete') or idea.get('summary')}\n"
            f"URL: {idea.get('url')}\n"
            "Rules: small scoped change in this repo only; add/adjust tests; "
            "do not vendor whole upstream; do not force-push; finish with pytest green if possible."
        )
        entry: dict[str, Any] = {
            "id": idea.get("id"),
            "source": idea.get("source"),
            "selected_as": idea.get("selected_as"),
        }
        try:
            w = (worker or "auto").strip().lower()
            if apply and w in ("auto", "grok") and gw.grok_available():
                res = gw.grok_hard_improve(root, goal)
                entry["worker"] = "grok"
                entry["ok"] = bool(res.get("ok", True)) if isinstance(res, dict) else True
                entry["result"] = {
                    k: res.get(k)
                    for k in ("ok", "text", "error", "model", "exit_code")
                    if isinstance(res, dict)
                }
            elif apply:
                # Batch remaining github ideas via improve_ours once as fallback
                applied = rm.step_improve_ours(
                    root,
                    min_score=0,
                    limit=1,
                    apply=True,
                    our_repo=our_repo or None,
                    worker=worker,
                )
                entry["worker"] = "improve_ours"
                entry["ok"] = bool(applied.get("ok", True)) if isinstance(applied, dict) else False
                entry["result"] = applied if isinstance(applied, dict) else {}
            else:
                entry["worker"] = "plan_only"
                entry["ok"] = True
                entry["result"] = {"plan": goal[:500]}
        except Exception as e:
            entry["ok"] = False
            entry["error"] = str(e)[:500]
        results.append(entry)
    ok_n = sum(1 for r in results if r.get("ok"))
    return {
        "ok": ok_n >= min(2, len(results)) if results else False,
        "implemented": ok_n,
        "total": len(results),
        "results": results,
        "arxiv_done": sum(
            1 for r in results if r.get("source") == "arxiv" and r.get("ok")
        ),
        "github_done": sum(
            1 for r in results if r.get("source") == "github" and r.get("ok")
        ),
        "cross_done": sum(
            1 for r in results if r.get("source") == "cross_pattern" and r.get("ok")
        ),
    }
