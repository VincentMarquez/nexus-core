"""Live X (Twitter) research input for self-improve — mandatory on REAL.

Same shape as arXiv/GitHub research:
  search → ledger (dedupe) → LATEST_X_REVIEW.md → dual_review / engine brief

Backends (first success wins):
  1. **Grok CLI** with web/X research (default — preferred for this product)
  2. Official X API v2 only if ``NEXUS_X_PREFER_API=1`` + bearer token
  3. Explicit failure marker (still records the mandatory phase)

  from nexus.x_research import step_x_review
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional, Sequence

FIELDS = (
    "post_id",
    "author",
    "text",
    "created_at",
    "url",
    "query",
    "first_seen",
    "last_seen",
    "likes",
    "reposts",
    "source",
    "times_seen",
)


def _root(workdir: Optional[Path | str] = None) -> Path:
    return Path(workdir or os.environ.get("NEXUS_PROJECT_ROOT") or os.getcwd()).resolve()


def docs_csv_path(workdir: Optional[Path | str] = None) -> Path:
    return _root(workdir) / "docs" / "X_LEDGER.csv"


def state_csv_path(workdir: Optional[Path | str] = None) -> Path:
    d = _root(workdir) / ".nexus_state"
    d.mkdir(parents=True, exist_ok=True)
    return d / "x_ledger.csv"


def latest_review_path(workdir: Optional[Path | str] = None) -> Path:
    return _root(workdir) / "docs" / "LATEST_X_REVIEW.md"


def _bearer() -> str:
    for k in (
        "X_BEARER_TOKEN",
        "TWITTER_BEARER_TOKEN",
        "TWITTER_BEARER",
        "X_API_BEARER",
    ):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


def _canon_id(pid: str) -> str:
    s = (pid or "").strip()
    if s.startswith("http") and "/status/" in s:
        s = s.rstrip("/").rsplit("/", 1)[-1]
    return s


def _stable_id_from_text(text: str, author: str = "") -> str:
    h = hashlib.sha256(f"{author}\n{text}".encode("utf-8", errors="replace")).hexdigest()
    return "x" + h[:16]


def load_rows(workdir: Optional[Path | str] = None) -> list[dict[str, str]]:
    for path in (docs_csv_path(workdir), state_csv_path(workdir)):
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", newline="") as f:
                rows = []
                for r in csv.DictReader(f):
                    if not r.get("post_id"):
                        continue
                    rows.append({k: (r.get(k) or "") for k in FIELDS})
                if rows:
                    return rows
        except Exception:
            continue
    return []


def seen_ids(workdir: Optional[Path | str] = None) -> set[str]:
    return {_canon_id(r["post_id"]) for r in load_rows(workdir)}


def save_rows(rows: Sequence[dict[str, str]], workdir: Optional[Path | str] = None) -> list[Path]:
    root = _root(workdir)
    ordered = sorted(rows, key=lambda r: (r.get("first_seen") or "", r.get("post_id") or ""))
    written: list[Path] = []
    for path in (docs_csv_path(root), state_csv_path(root)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for r in ordered:
                w.writerow({k: r.get(k) or "" for k in FIELDS})
        written.append(path)
    return written


def record_posts(
    posts: Sequence[dict[str, Any]],
    *,
    query: str,
    workdir: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Merge posts into ledger; return counts."""
    root = _root(workdir)
    rows = load_rows(root)
    by_id = {_canon_id(r["post_id"]): r for r in rows}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    added = 0
    updated = 0
    for p in posts:
        pid = _canon_id(str(p.get("post_id") or p.get("id") or ""))
        text = str(p.get("text") or "").strip()
        if not pid and text:
            pid = _stable_id_from_text(text, str(p.get("author") or ""))
        if not pid:
            continue
        if pid in by_id:
            r = by_id[pid]
            r["last_seen"] = now
            r["times_seen"] = str(int(r.get("times_seen") or "1") + 1)
            if query and query not in (r.get("query") or ""):
                r["query"] = ((r.get("query") or "") + " | " + query).strip(" |")
            updated += 1
        else:
            by_id[pid] = {
                "post_id": pid,
                "author": str(p.get("author") or p.get("username") or "")[:80],
                "text": text[:2000],
                "created_at": str(p.get("created_at") or "")[:40],
                "url": str(p.get("url") or "")[:300],
                "query": query[:200],
                "first_seen": now,
                "last_seen": now,
                "likes": str(p.get("likes") or p.get("like_count") or ""),
                "reposts": str(p.get("reposts") or p.get("repost_count") or ""),
                "source": str(p.get("source") or "x")[:40],
                "times_seen": "1",
            }
            added += 1
    save_rows(list(by_id.values()), root)
    return {"added": added, "updated": updated, "total": len(by_id)}


# ── Fetch backends ──────────────────────────────────────────────────────────


def search_x_api(
    query: str,
    *,
    max_results: int = 20,
    bearer: Optional[str] = None,
) -> list[dict[str, Any]]:
    """X API v2 recent search (requires bearer token)."""
    token = (bearer or _bearer()).strip()
    if not token:
        raise RuntimeError("no X bearer token (set X_BEARER_TOKEN or TWITTER_BEARER_TOKEN)")
    max_results = max(10, min(int(max_results), 100))
    q = (query or "").strip()
    if not q:
        return []
    params = urllib.parse.urlencode(
        {
            "query": q + " -is:retweet lang:en",
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id",
            "expansions": "author_id",
            "user.fields": "username",
        }
    )
    url = f"https://api.twitter.com/2/tweets/search/recent?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "nexus-core-x-research/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode())
    users = {
        u["id"]: u.get("username") or u["id"]
        for u in (data.get("includes") or {}).get("users") or []
        if u.get("id")
    }
    out: list[dict[str, Any]] = []
    for t in data.get("data") or []:
        tid = str(t.get("id") or "")
        author = users.get(str(t.get("author_id") or ""), str(t.get("author_id") or ""))
        metrics = t.get("public_metrics") or {}
        out.append(
            {
                "post_id": tid,
                "author": author,
                "text": t.get("text") or "",
                "created_at": t.get("created_at") or "",
                "url": f"https://x.com/{author}/status/{tid}" if author and tid else f"https://x.com/i/status/{tid}",
                "likes": metrics.get("like_count"),
                "reposts": metrics.get("retweet_count"),
                "source": "x_api_v2",
            }
        )
    return out


def search_via_grok(
    query: str,
    *,
    max_results: int = 15,
    timeout_s: float = 180.0,
) -> list[dict[str, Any]]:
    """Use Grok CLI (web enabled) to gather recent X/public discussion as structured posts."""
    from . import grok_worker as gw

    if not gw.grok_available():
        raise RuntimeError("grok CLI not on PATH")

    schema = (
        '{"type":"object","properties":{"posts":{"type":"array","items":{"type":"object",'
        '"properties":{"post_id":{"type":"string"},"author":{"type":"string"},'
        '"text":{"type":"string"},"url":{"type":"string"},"created_at":{"type":"string"},'
        '"likes":{"type":"number"},"reposts":{"type":"number"}},'
        '"required":["text"]}}},"required":["posts"]}'
    )
    prompt = (
        "You are a research scout for a software self-improve system.\n"
        f"Find **live, recent X (Twitter)** posts and public discussion about:\n"
        f"  {query}\n\n"
        "Prefer posts from builders, researchers, agent/SWE-bench practitioners, open-source maintainers.\n"
        "Use web/X search tools if available. Return ONLY JSON matching the schema with up to "
        f"{max_results} posts.\n"
        "Each post needs text; include author handle, url (x.com/...), post_id if known, engagement if known.\n"
        "If you cannot access X live, return the best recent public posts you can find about the topic "
        "and set post_id to empty (we will hash-id them).\n"
    )
    # Enable web search for this research call (default grok_prompt disables it).
    model = gw.default_model()
    effort = gw.default_effort()
    import subprocess
    import shutil

    cmd = [
        "grok",
        "-p",
        prompt,
        "-m",
        model,
        "--reasoning-effort",
        effort,
        "--max-turns",
        "6",
        "--json-schema",
        schema,
        "--always-approve",
        "--no-plan",
    ]
    # Intentionally NOT --disable-web-search
    env = gw._child_env()  # noqa: SLF001 — shared env policy
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"grok X research timeout after {timeout_s}s") from e
    text = (p.stdout or "").strip() or (p.stderr or "").strip()
    from . import usage as usage_mod

    usage_mod.record_text(prompt, text, source=f"grok:{model}", label="x_research", enforce=False)
    obj = gw._parse_json_obj(text) or {}  # noqa: SLF001
    if "structuredOutput" in obj and isinstance(obj["structuredOutput"], dict):
        obj = obj["structuredOutput"]
    posts = obj.get("posts") if isinstance(obj, dict) else None
    if not isinstance(posts, list):
        # try to pull array from text
        m = re.search(r"\[[\s\S]*\]", text)
        if m:
            try:
                posts = json.loads(m.group(0))
            except json.JSONDecodeError:
                posts = []
        else:
            posts = []
    out: list[dict[str, Any]] = []
    for raw in posts[: max_results]:
        if not isinstance(raw, dict):
            continue
        text_p = str(raw.get("text") or "").strip()
        if not text_p:
            continue
        author = str(raw.get("author") or "").lstrip("@")
        pid = str(raw.get("post_id") or raw.get("id") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not pid and url and "/status/" in url:
            pid = url.rstrip("/").rsplit("/", 1)[-1]
        if not pid:
            pid = _stable_id_from_text(text_p, author)
        if not url and author and pid.isdigit():
            url = f"https://x.com/{author}/status/{pid}"
        out.append(
            {
                "post_id": pid,
                "author": author,
                "text": text_p,
                "created_at": str(raw.get("created_at") or ""),
                "url": url,
                "likes": raw.get("likes"),
                "reposts": raw.get("reposts"),
                "source": "grok_x_research",
            }
        )
    if not out:
        raise RuntimeError("grok returned no parseable X posts")
    return out


def fetch_posts(
    query: str,
    *,
    max_results: int = 20,
    prefer_api: bool | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch posts; return (posts, backend_name).

    **Default: Grok tools first** (live X/web research via CLI).  
    Official X API is optional backup only when:
      - ``prefer_api=True``, or
      - env ``NEXUS_X_PREFER_API=1`` and a bearer token is set.
    """
    errors: list[str] = []
    if prefer_api is None:
        prefer_api = (os.environ.get("NEXUS_X_PREFER_API") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "api",
        )

    # 1) Preferred: Grok (student's tutor reads live X/world)
    if not prefer_api:
        try:
            return search_via_grok(query, max_results=max_results), "grok_x_research"
        except Exception as e:
            errors.append(f"grok: {e}")
        # optional API fallback if token present
        if _bearer():
            try:
                return search_x_api(query, max_results=max_results), "x_api_v2"
            except Exception as e:
                errors.append(f"x_api: {e}")
        raise RuntimeError("; ".join(errors) or "no X backend available")

    # 2) Explicit API-first (ops choice)
    if _bearer():
        try:
            return search_x_api(query, max_results=max_results), "x_api_v2"
        except Exception as e:
            errors.append(f"x_api: {e}")
    try:
        return search_via_grok(query, max_results=max_results), "grok_x_research"
    except Exception as e:
        errors.append(f"grok: {e}")
    raise RuntimeError("; ".join(errors) or "no X backend available")


def write_latest_review(
    root: Path,
    *,
    queries: list[str],
    posts: list[dict[str, Any]],
    backend: str,
    ledger: dict[str, Any],
    themes: str = "",
) -> Path:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    state = root / ".nexus_state" / "x_research"
    state.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Live X research — self-improve input (mandatory on REAL)",
        "",
        f"ts: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"backend: `{backend}`",
        f"queries: {queries}",
        f"posts_this_run: {len(posts)}",
        f"ledger: +{ledger.get('added', 0)} new, {ledger.get('updated', 0)} updated, total={ledger.get('total', 0)}",
        "",
        "## Themes / takeaways",
        "",
        themes.strip() or "(ranked from post texts — builders & SWE-agent discourse)",
        "",
        "## Posts",
        "",
    ]
    for i, p in enumerate(posts[:30], 1):
        author = p.get("author") or "?"
        url = p.get("url") or ""
        text = (p.get("text") or "").replace("\n", " ")
        lines.append(f"{i}. **@{author}** — `{p.get('post_id')}`")
        if url:
            lines.append(f"   {url}")
        lines.append(f"   {text[:400]}")
        eng = []
        if p.get("likes") not in (None, ""):
            eng.append(f"❤{p.get('likes')}")
        if p.get("reposts") not in (None, ""):
            eng.append(f"↻{p.get('reposts')}")
        if eng:
            lines.append(f"   {' · '.join(eng)}")
        lines.append("")
    lines += [
        "## How to use",
        "",
        "- Feed into dual_review / engine research_brief as **live practitioner signal**.",
        "- Prefer patterns that show up on both X and arXiv/GitHub.",
        "- Do not treat viral posts as truth — treat as hypotheses to test in code.",
        "",
    ]
    text = "\n".join(lines)
    dest = docs / "LATEST_X_REVIEW.md"
    dest.write_text(text, encoding="utf-8")
    (state / "LATEST_X_REVIEW.md").write_text(text, encoding="utf-8")
    (state / f"batch-{int(time.time())}.json").write_text(
        json.dumps(
            {"queries": queries, "backend": backend, "posts": posts, "ledger": ledger},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return dest


def _themes_via_grok(posts: list[dict[str, Any]], goal: str = "") -> str:
    """Optional short theme summary for the review doc."""
    try:
        from . import grok_worker as gw

        if not gw.grok_available() or not posts:
            return ""
        blob = "\n".join(
            f"- @{p.get('author')}: {(p.get('text') or '')[:200]}" for p in posts[:20]
        )
        prompt = (
            "Summarize 3-6 themes from these X posts for a self-improving coding agent. "
            "Bullet list only. Goal context: "
            f"{(goal or 'improve software engineering agents')[:200]}\n\n{blob}"
        )
        res = gw.grok_prompt(
            prompt,
            max_turns=1,
            tools=False,
            timeout_s=90,
            label="x_themes",
            soft_ok=True,
        )
        return (res.get("text") or "").strip()[:2000]
    except Exception:
        return ""


def step_x_review(
    root: Path | str,
    *,
    queries: Optional[list[str]] = None,
    max_results: int = 20,
    goal: str = "",
    use_grok_themes: bool = True,
) -> dict[str, Any]:
    """Mandatory X research step for alive REAL.

    Raises only on total backend failure when ``require`` is handled by caller.
    """
    root = _root(root)
    qs = [q.strip() for q in (queries or []) if q and str(q).strip()]
    if not qs:
        qs = [
            "SWE-bench coding agent",
            "self-improving AI agent software engineering",
            "multi agent LLM coding",
        ]
    # rotate primary query hourly (same idea as arxiv)
    rot = int(time.time() // 3600) % len(qs)
    primary = qs[rot]
    extras = [q for i, q in enumerate(qs) if i != rot][:3]

    all_posts: list[dict[str, Any]] = []
    backends: list[str] = []
    errors: list[str] = []
    for q in [primary] + extras:
        try:
            posts, backend = fetch_posts(q, max_results=max(10, max_results // max(1, len(extras) + 1)))
            backends.append(backend)
            for p in posts:
                p = dict(p)
                p["_query"] = q
                all_posts.append(p)
        except Exception as e:
            errors.append(f"{q}: {e}")

    # dedupe by post_id
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for p in all_posts:
        pid = _canon_id(str(p.get("post_id") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        uniq.append(p)

    if not uniq:
        # still write a failure review so dual_review shows the mandatory hole
        dest = write_latest_review(
            root,
            queries=qs,
            posts=[],
            backend="none",
            ledger={"added": 0, "updated": 0, "total": len(load_rows(root))},
            themes=f"**FAILED** mandatory X research.\n\nErrors:\n" + "\n".join(f"- {e}" for e in errors),
        )
        return {
            "step": "x_review",
            "ok": False,
            "required_on_real": True,
            "error": "; ".join(errors) or "no posts",
            "path": str(dest),
            "posts": 0,
            "queries": qs,
            "backend": "none",
        }

    # record per-query into ledger
    ledger_total = {"added": 0, "updated": 0, "total": 0}
    by_q: dict[str, list] = {}
    for p in uniq:
        by_q.setdefault(str(p.get("_query") or primary), []).append(p)
    for q, plist in by_q.items():
        lr = record_posts(plist, query=q, workdir=root)
        ledger_total["added"] += int(lr.get("added") or 0)
        ledger_total["updated"] += int(lr.get("updated") or 0)
        ledger_total["total"] = int(lr.get("total") or ledger_total["total"])

    themes = ""
    if use_grok_themes:
        themes = _themes_via_grok(uniq, goal=goal)

    backend = "+".join(sorted(set(backends))) or "unknown"
    dest = write_latest_review(
        root,
        queries=qs,
        posts=uniq,
        backend=backend,
        ledger=ledger_total,
        themes=themes,
    )
    try:
        from . import usage as usage_mod

        usage_mod.record(
            800,
            source="x_research",
            label=(primary[:40] or "x"),
            workdir=root,
            enforce=False,
        )
    except Exception:
        pass

    return {
        "step": "x_review",
        "ok": True,
        "required_on_real": True,
        "path": str(dest),
        "posts": len(uniq),
        "queries": qs,
        "primary_query": primary,
        "backend": backend,
        "ledger": ledger_total,
        "errors": errors or None,
        "note": "mandatory live X input — practitioner signal for portfolio/engine",
    }
