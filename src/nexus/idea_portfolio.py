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


# ── S03 implement ledger + portfolio cooldown ──────────────────────────────

LEDGER_NAME = "implement_ledger.jsonl"
_BOOTSTRAP_MARK = ".implement_ledger_bootstrapped"


def _ledger_path(root: Path) -> Path:
    d = _root(root) / ".nexus_state"
    d.mkdir(parents=True, exist_ok=True)
    return d / LEDGER_NAME


def append_implement_ledger(
    root: Path | str,
    *,
    idea_id: str,
    source: str = "",
    ok: bool = True,
    cycle_id: str = "",
    seed: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append one implement outcome row (append-only JSONL)."""
    root_p = _root(root)
    iid = str(idea_id or "").strip()
    if not iid:
        return {"ok": False, "error": "idea_id required"}
    row: dict[str, Any] = {
        "ts": time.time(),
        "id": iid,
        "source": str(source or ""),
        "seed": str(seed or ""),
        "ok": bool(ok),
        "cycle_id": str(cycle_id or ""),
    }
    if extra:
        row["extra"] = extra
    path = _ledger_path(root_p)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return {"ok": True, "path": str(path), "row": row}


def load_implement_ledger(root: Path | str, *, limit: int = 500) -> list[dict[str, Any]]:
    path = _ledger_path(_root(root))
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    for line in lines[-max(1, int(limit)) :]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def cooled_keys(
    root: Path | str,
    *,
    cooldown_days: float = 7.0,
    only_ok: bool = True,
) -> set[str]:
    """Return idea ids (and seeds) that should be soft-demoted.

    Failed implements do not cool when ``only_ok`` is True.
    """
    window_s = max(0.0, float(cooldown_days or 0.0)) * 86400.0
    if window_s <= 0:
        return set()
    now = time.time()
    out: set[str] = set()
    for row in load_implement_ledger(root, limit=2000):
        if only_ok and not row.get("ok"):
            continue
        ts = float(row.get("ts") or 0.0)
        if ts <= 0 or (now - ts) > window_s:
            continue
        iid = str(row.get("id") or "").strip()
        if iid:
            out.add(iid)
        seed = str(row.get("seed") or "").strip()
        if seed:
            out.add(seed)
    return out


def _item_is_cooled(item: dict[str, Any], cooled: set[str]) -> bool:
    if not cooled:
        return False
    iid = str(item.get("id") or "")
    if iid and iid in cooled:
        return True
    for key in ("github_id", "seed", "repo"):
        v = str(item.get(key) or "")
        if v and v in cooled:
            return True
    # novels often encode github as ...+owner/repo
    if iid.startswith("novel:") and "+" in iid:
        tail = iid.rsplit("+", 1)[-1]
        if tail in cooled:
            return True
    return False


def order_with_cooldown(
    items: list[dict[str, Any]],
    cooled_ids: set[str] | list[str] | None,
) -> list[dict[str, Any]]:
    """Stable reorder: non-cooled (hot) first, cooled last. Fail-open if all cool."""
    cooled = set(cooled_ids or [])
    if not cooled or not items:
        return list(items)
    hot = [it for it in items if not _item_is_cooled(it, cooled)]
    cold = [it for it in items if _item_is_cooled(it, cooled)]
    return hot + cold


def bootstrap_ledger_from_alive_state(root: Path | str) -> int:
    """Seed ledger once from latest alive_state implement results if ledger empty.

    Returns number of rows written (0 if already bootstrapped / ledger non-empty).
    """
    root_p = _root(root)
    state_dir = root_p / ".nexus_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    mark = state_dir / _BOOTSTRAP_MARK
    ledger = _ledger_path(root_p)
    if mark.is_file():
        return 0
    if ledger.is_file() and ledger.stat().st_size > 0:
        mark.write_text("skip-nonempty\n", encoding="utf-8")
        return 0
    alive = state_dir / "alive_state.json"
    if not alive.is_file():
        mark.write_text("skip-no-alive\n", encoding="utf-8")
        return 0
    try:
        blob = json.loads(alive.read_text(encoding="utf-8"))
    except Exception:
        mark.write_text("skip-bad-alive\n", encoding="utf-8")
        return 0
    written = 0
    for step in blob.get("steps") or []:
        if not isinstance(step, dict) or step.get("step") != "implement":
            continue
        for r in step.get("results") or []:
            if not isinstance(r, dict):
                continue
            iid = str(r.get("id") or "").strip()
            if not iid:
                continue
            src = str(r.get("source") or "")
            seed = ""
            if src == "github":
                seed = iid
            elif src == "cross_pattern" and "+" in iid:
                seed = iid.rsplit("+", 1)[-1]
            append_implement_ledger(
                root_p,
                idea_id=iid,
                source=src,
                ok=bool(r.get("ok")),
                cycle_id="bootstrap:alive_state",
                seed=seed,
                extra={"bootstrap": True},
            )
            written += 1
    mark.write_text(f"n={written}\n", encoding="utf-8")
    return written


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
    cooled_ids: set[str] | list[str] | None = None,
    capability: list[dict[str, Any]] | None = None,
    max_capability: int = 2,
) -> list[dict[str, Any]]:
    """Ensure ≥min_arxiv + ≥min_github, fill with novels then remaining best, cap max_ideas.

    Diversity (anti-monoculture):
      - at most ``max_per_arxiv_seed`` ideas (incl. cross_pattern) share one paper seed
      - try to include at least ``min_distinct_arxiv`` different papers when pool allows

    Cooldown (S03): soft-demote ids/seeds in ``cooled_ids`` (hot first). Fail-open if
    only cooled candidates remain (marks ``cooldown_reuse``).

    Capability (factory): optional capability ideas slotted after required quotas.
    """
    max_ideas = max(2, min(int(max_ideas), 10))  # hard ceiling 10
    min_arxiv = max(1, int(min_arxiv))
    min_github = max(1, int(min_github))
    max_per_seed = max(1, int(max_per_arxiv_seed))
    min_distinct = max(1, int(min_distinct_arxiv))
    max_cap = max(0, int(max_capability))
    cooled = set(cooled_ids or [])
    if min_arxiv + min_github > max_ideas:
        min_arxiv = 1
        min_github = 1

    arxiv = order_with_cooldown(list(arxiv), cooled)
    github = order_with_cooldown(list(github), cooled)
    novels = order_with_cooldown(list(novels), cooled)
    caps = order_with_cooldown(list(capability or []), cooled)

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
            if _item_is_cooled(it, cooled):
                row["cooldown_reuse"] = True
            portfolio.append(row)
            got += 1
        return got

    # Required quotas first (single arxiv + github seed ok) — hot preferred
    take(arxiv, min_arxiv, "required_arxiv", enforce_seed=True)
    take(github, min_github, "required_github", enforce_seed=False)

    # Capability ideas (skill/tool factory) — bounded slot
    if caps and max_cap > 0:
        take(caps, max_cap, "capability", enforce_seed=False)

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
        list(arxiv) + list(github) + list(caps),
        key=lambda x: -float(x.get("score") or 0),
    )
    # Prefer hot fills before cooled
    rest = order_with_cooldown(rest, cooled)
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
    cooldown_days: float = 7.0,
    cooldown_disable: bool = False,
) -> dict[str, Any]:
    """Full collect → cross-pattern → select → write."""
    root = _root(root)
    # Bootstrap ledger once if empty (S03)
    try:
        bootstrap_ledger_from_alive_state(root)
    except Exception:
        pass
    arxiv = collect_arxiv_ideas(root, limit=30)
    github = collect_github_ideas(root, limit=30, min_score=min_github_score)
    novels = cross_pattern_novel_ideas(arxiv, github, limit=8)
    cooled: set[str] = set()
    if not cooldown_disable and float(cooldown_days or 0) > 0:
        try:
            cooled = cooled_keys(root, cooldown_days=float(cooldown_days))
        except Exception:
            cooled = set()
    caps: list[dict[str, Any]] = []
    try:
        from . import capability_factory as cf

        caps = cf.collect_capability_ideas(root, limit=4)
    except Exception:
        caps = []
    portfolio = select_portfolio(
        arxiv,
        github,
        novels,
        min_arxiv=min_arxiv,
        min_github=min_github,
        max_ideas=max_ideas,
        cooled_ids=cooled,
        capability=caps,
        max_capability=2,
    )
    meta = {
        "min_arxiv": min_arxiv,
        "min_github": min_github,
        "max_ideas": max_ideas,
        "arxiv_pool": len(arxiv),
        "github_pool": len(github),
        "novel_pool": len(novels),
        "cooled": len(cooled),
        "capability_pool": len(caps),
        "arxiv_selected": sum(1 for p in portfolio if p.get("source") == "arxiv"),
        "github_selected": sum(1 for p in portfolio if p.get("source") == "github"),
        "cross_selected": sum(1 for p in portfolio if p.get("source") == "cross_pattern"),
        "capability_selected": sum(
            1 for p in portfolio if str(p.get("source") or "").startswith("capability")
        ),
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
    panel_critique: bool = False,
    scope_contract_enable: bool = False,
    accept_predicate_enable: bool = True,
    cycle_id: str = "",
) -> dict[str, Any]:
    """Implement each selected idea (worker per idea). Returns per-idea results.

    ``panel_critique`` is accepted for API compatibility (panel wiring is opt-in
    elsewhere). ``scope_contract_enable`` injects S04 DNA into the idea goal.
    """
    from . import grok_worker as gw
    from . import repo_mine as rm

    del panel_critique  # reserved — critique_panel is invoked by callers/alive
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
            "contract_injected": False,
        }
        if scope_contract_enable:
            try:
                from . import scope_contract as sc

                contract = sc.default_contract(idea if isinstance(idea, dict) else {})
                goal = sc.prepend_dna_to_goal(goal, contract)
                entry["contract_injected"] = True
                entry["scope_contract_id"] = contract.get("idea_id")
            except Exception as e:
                entry["contract_injected"] = False
                entry["contract_error"] = str(e)[:200]
        try:
            w = (worker or "auto").strip().lower()
            # Wave D: capability ideas use factory fill/activate (not product hard-improve)
            if apply and str(idea.get("source") or "").startswith("capability"):
                try:
                    from . import capability_factory as cfact

                    cres = cfact.implement_capability_idea(
                        root,
                        idea if isinstance(idea, dict) else {},
                        use_grok_fill=True,
                        auto_activate_skill=True,
                        auto_activate_tool=True,
                    )
                    entry["worker"] = "capability_factory"
                    entry["ok"] = bool(cres.get("ok"))
                    entry["result"] = cres
                    entry["capability"] = {
                        "kind": cres.get("kind"),
                        "activate": cres.get("activate"),
                        "fill": (cres.get("fill") or {}).get("filled_by"),
                    }
                except Exception as e:
                    entry["worker"] = "capability_factory"
                    entry["ok"] = False
                    entry["error"] = str(e)[:400]
                    entry["result"] = {}
            elif apply and w in ("auto", "grok") and gw.grok_available():
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
                # Keep enough of the goal for DNA assertions (S04)
                entry["result"] = {"plan": goal[:4000]}
        except Exception as e:
            entry["ok"] = False
            entry["error"] = str(e)[:500]

        # Soft accept predicate (S05) — advisory only
        if accept_predicate_enable:
            try:
                from . import accept_predicate as ap

                acc = ap.evaluate_accept(root, entry, idea=idea, soft=True)
                entry["accept_predicate"] = acc
            except Exception:
                pass

        # S03 ledger: record successful (and failed) implements for cooldown
        try:
            src = str(idea.get("source") or entry.get("source") or "")
            seed = ""
            if src == "github":
                seed = str(idea.get("id") or "")
            elif src == "cross_pattern":
                seed = str(idea.get("github_id") or "")
                if not seed:
                    iid = str(idea.get("id") or "")
                    if "+" in iid:
                        seed = iid.rsplit("+", 1)[-1]
            append_implement_ledger(
                root,
                idea_id=str(idea.get("id") or entry.get("id") or ""),
                source=src,
                ok=bool(entry.get("ok")),
                cycle_id=cycle_id,
                seed=seed,
            )
        except Exception:
            pass

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
