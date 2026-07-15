"""Discover → grade → **use** other GitHub repos (not follow/star).

Like yumiaura/followme's discovery pipeline, but the goal is to **mine useful
codebases for your project**: clone, prove, score, keep winners under
``.nexus_workspaces/scout_repos/``, write improvement notes.

  nexus github mine fetch -n 8 --query "multi agent durable"
  nexus github mine evaluate --limit 8
  nexus github mine use --min-score 12
  nexus github mine run --query "…"          # full pipeline once
  nexus github mine list

Scoring: idea (novelty) + skill (engineering) in [1,10] each → sum [2,20].
No GitHub follow/star API calls — ever.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from . import github_autonomy as ga
from . import github_community as gc

DB_NAME = "repo_mine.sqlite"
SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  repo TEXT PRIMARY KEY,
  profile TEXT,
  clone_url TEXT,
  html_url TEXT,
  language TEXT,
  stars INTEGER DEFAULT 0,
  description TEXT,
  created_at TEXT,
  updated_at TEXT,
  idea REAL,
  skill REAL,
  summary TEXT,
  used INTEGER DEFAULT 0,
  local_path TEXT,
  prove_ok INTEGER,
  prove_json TEXT
);
"""


def _db_path(workdir: Path) -> Path:
    d = Path(workdir).resolve() / ".nexus_state"
    d.mkdir(parents=True, exist_ok=True)
    return d / DB_NAME


def connect(workdir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(workdir)))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def known_repos(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT repo FROM entries")}


def insert_hit(conn: sqlite3.Connection, hit: ga.RepoHit) -> bool:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    owner = hit.full_name.split("/")[0] if "/" in hit.full_name else ""
    try:
        conn.execute(
            """
            INSERT INTO entries(repo, profile, clone_url, html_url, language, stars,
                                description, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                hit.full_name,
                owner,
                f"https://github.com/{hit.full_name}.git",
                hit.url,
                hit.language,
                hit.stars,
                hit.description,
                now,
                now,
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def unevaluated(conn: sqlite3.Connection, limit: Optional[int] = None) -> list[sqlite3.Row]:
    q = "SELECT * FROM entries WHERE idea IS NULL ORDER BY created_at DESC"
    if limit:
        q += f" LIMIT {int(limit)}"
    return list(conn.execute(q))


def save_eval(
    conn: sqlite3.Connection,
    repo: str,
    idea: float,
    skill: float,
    summary: str,
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn.execute(
        """
        UPDATE entries SET idea=?, skill=?, summary=?, updated_at=? WHERE repo=?
        """,
        (float(idea), float(skill), summary[:2000], now, repo),
    )
    conn.commit()


def mark_used(
    conn: sqlite3.Connection,
    repo: str,
    *,
    local_path: str,
    prove_ok: Optional[bool],
    prove_json: str,
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn.execute(
        """
        UPDATE entries SET used=1, local_path=?, prove_ok=?, prove_json=?, updated_at=?
        WHERE repo=?
        """,
        (
            local_path,
            1 if prove_ok else 0 if prove_ok is not None else None,
            prove_json[:8000],
            now,
            repo,
        ),
    )
    conn.commit()


def list_entries(
    conn: sqlite3.Connection,
    *,
    min_score: float = 0.0,
    only_used: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = """
    SELECT repo, profile, stars, language, idea, skill,
           COALESCE(idea,0)+COALESCE(skill,0) AS score,
           summary, used, local_path, html_url, description
    FROM entries
    WHERE 1=1
    """
    if only_used:
        q += " AND used=1"
    q += " ORDER BY score DESC, stars DESC LIMIT ?"
    rows = conn.execute(q, (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        score = float(d.get("score") or 0)
        if score < min_score and (d.get("idea") is not None):
            continue
        out.append(d)
    return out


# --- evaluate: Grok (hard grade) → Ollama (light) → heuristic -----------------


def _digest_repo(path: Path, *, max_files: int = 16, max_chars: int = 12000) -> str:
    chunks: list[str] = []
    total = 0
    prefer = (
        "README.md",
        "readme.md",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "Makefile",
    )
    files: list[Path] = []
    for name in prefer:
        p = path / name
        if p.is_file():
            files.append(p)
    # sample source
    for ext in (".py", ".ts", ".go", ".rs", ".md"):
        for p in sorted(path.rglob(f"*{ext}"))[:40]:
            if any(part.startswith(".") for part in p.parts):
                continue
            if p not in files:
                files.append(p)
            if len(files) >= max_files:
                break
        if len(files) >= max_files:
            break
    for p in files[:max_files]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:2500]
        except Exception:
            continue
        rel = str(p.relative_to(path))
        block = f"## {rel}\n{text}\n"
        if total + len(block) > max_chars:
            break
        chunks.append(block)
        total += len(block)
    return "\n".join(chunks) if chunks else "(empty digest)"


def heuristic_grade(hit_desc: str, digest: str, stars: int, language: str) -> dict[str, Any]:
    """Deterministic grade when Ollama is off — still useful for ranking."""
    d = (digest + "\n" + (hit_desc or "")).lower()
    idea = 5.0
    skill = 5.0
    # novelty signals
    for kw, bump in (
        ("multi-agent", 1.2),
        ("agent", 0.6),
        ("orchestrat", 0.8),
        ("ollama", 0.5),
        ("llm", 0.5),
        ("durable", 0.8),
        ("checkpoint", 0.7),
        ("resume", 0.5),
        ("mcp", 0.7),
        ("rag", 0.4),
        ("novel", 0.3),
    ):
        if kw in d:
            idea = min(10.0, idea + bump)
    # engineering signals
    for kw, bump in (
        ("test", 0.5),
        ("pytest", 0.8),
        ("ci", 0.4),
        ("github/workflows", 0.6),
        ("type", 0.2),
        ("license", 0.3),
        ("dockerfile", 0.4),
        ("pyproject", 0.4),
        ("readme", 0.3),
    ):
        if kw in d:
            skill = min(10.0, skill + bump)
    # small focused projects often more portable
    if stars < 50:
        idea = min(10.0, idea + 0.3)
    elif stars > 5000:
        skill = min(10.0, skill + 0.5)
        idea = max(1.0, idea - 0.3)
    if language and language.lower() == "python":
        skill = min(10.0, skill + 0.2)
    summary = (hit_desc or digest[:200].replace("\n", " ")).strip()[:240]
    return {
        "idea": round(idea, 2),
        "skill": round(skill, 2),
        "description": summary or "no description",
        "method": "heuristic",
    }


def ollama_grade(
    digest: str,
    full_name: str,
    *,
    host: str = "http://127.0.0.1:11434",
    model: str = "gemma2",
) -> Optional[dict[str, Any]]:
    """Ask Ollama for idea/skill/description JSON. Returns None if unavailable."""
    prompt = (
        "You grade open-source repos for reuse in another engineering project.\n"
        "Reply with ONLY JSON: "
        '{"idea": <1-10 novelty>, "skill": <1-10 engineering quality>, '
        '"description": "<one English sentence>"}\n'
        f"Repo: {full_name}\n\nCODE/README DIGEST:\n{digest[:14000]}\n"
    )
    url = host.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 256},
        "format": "json",
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            body = json.loads(r.read().decode())
        text = (body.get("response") or "").strip()
        obj = json.loads(text) if text.startswith("{") else None
        if not obj:
            m = re.search(r"\{.*\}", text, re.S)
            obj = json.loads(m.group(0)) if m else None
        if not isinstance(obj, dict):
            return None
        idea = float(obj.get("idea") or 5)
        skill = float(obj.get("skill") or 5)
        idea = max(1.0, min(10.0, idea))
        skill = max(1.0, min(10.0, skill))
        return {
            "idea": round(idea, 2),
            "skill": round(skill, 2),
            "description": str(obj.get("description") or "")[:400],
            "method": f"ollama:{model}",
        }
    except Exception:
        return None


# --- pipeline steps -----------------------------------------------------------


def step_fetch(
    workdir: Path,
    *,
    query: str,
    count: int = 8,
    language: Optional[str] = "Python",
    max_stars: Optional[int] = 500,
) -> dict[str, Any]:
    """Pull N new repos from GitHub search into SQLite (no follow/star)."""
    conn = connect(workdir)
    skip = known_repos(conn)
    q = query.strip()
    if language:
        q = f"{q} language:{language}"
    if max_stars is not None:
        q = f"{q} stars:<={int(max_stars)}"
    # over-fetch then filter known
    hits = ga.search_github_repos(q, limit=min(50, max(count * 3, count)), language=None)
    inserted = 0
    new_names: list[str] = []
    for h in hits:
        if h.full_name in skip:
            continue
        if insert_hit(conn, h):
            inserted += 1
            new_names.append(h.full_name)
            skip.add(h.full_name)
        if inserted >= count:
            break
    conn.close()
    return {
        "step": "fetch",
        "query": q,
        "inserted": inserted,
        "repos": new_names,
        "db": str(_db_path(workdir)),
    }


def grade_repo(
    digest: str,
    full_name: str,
    *,
    hit_desc: str = "",
    stars: int = 0,
    language: str = "",
    grader: str = "auto",
    use_ollama: bool = True,
    ollama_host: str = "http://127.0.0.1:11434",
    ollama_model: Optional[str] = None,
) -> dict[str, Any]:
    """Grade one repo. Default: **Grok hard grade** → Ollama light → heuristic.

    ``grader``: auto | grok | ollama | heuristic
    """
    g = (grader or "auto").strip().lower()
    model = ollama_model or os.environ.get("OLLAMA_MODEL") or "gemma2"
    host = os.environ.get("OLLAMA_HOST") or ollama_host
    grade: Optional[dict[str, Any]] = None

    # Hard work: Grok scores for reuse quality
    if g in ("auto", "grok"):
        try:
            from . import grok_worker as gw

            grade = gw.grok_grade(digest, full_name)
        except Exception:
            grade = None

    # Light work: local LLM (Ollama) fallback or when grader=ollama
    if not grade and use_ollama and g in ("auto", "ollama", "grok"):
        grade = ollama_grade(digest, full_name, host=host, model=model)

    if not grade:
        grade = heuristic_grade(hit_desc, digest, stars, language)
    return grade


def step_evaluate(
    workdir: Path,
    *,
    limit: Optional[int] = 10,
    use_ollama: bool = True,
    ollama_host: str = "http://127.0.0.1:11434",
    ollama_model: Optional[str] = None,
    keep_clone: bool = True,
    grader: str = "auto",
) -> dict[str, Any]:
    """Clone each unevaluated repo, grade, store scores.

    Default cascade (``grader=auto``): **Grok** grades → local Ollama light → heuristic.
    """
    conn = connect(workdir)
    pending = unevaluated(conn, limit=limit)
    results: list[dict[str, Any]] = []
    clone_root = Path(workdir).resolve() / ".nexus_workspaces" / "mine_eval"
    g = (grader or "auto").strip().lower()
    if g in ("heuristic", "none"):
        g = "heuristic"
        use_ollama = False

    for row in pending:
        repo = row["repo"]
        entry: dict[str, Any] = {"repo": repo}
        try:
            conn_res = ga.connect_repo(repo, clone_root=clone_root, pull=True)
            entry["connect"] = conn_res.get("action")
            if not conn_res.get("ok"):
                entry["error"] = "clone_failed"
                results.append(entry)
                continue
            path = Path(conn_res["path"])
            digest = _digest_repo(path)
            grade = grade_repo(
                digest,
                repo,
                hit_desc=row["description"] or "",
                stars=int(row["stars"] or 0),
                language=row["language"] or "",
                grader=g,
                use_ollama=use_ollama,
                ollama_host=ollama_host,
                ollama_model=ollama_model,
            )
            save_eval(conn, repo, grade["idea"], grade["skill"], grade["description"])
            entry.update(grade)
            entry["score"] = round(grade["idea"] + grade["skill"], 2)
            entry["path"] = str(path)
            if not keep_clone:
                pass
            results.append(entry)
            print(
                f"  graded {repo}: idea={grade['idea']} skill={grade['skill']} "
                f"sum={entry['score']} [{grade['method']}]"
            )
        except Exception as e:
            entry["error"] = str(e)
            results.append(entry)
    conn.close()
    return {
        "step": "evaluate",
        "grader": g,
        "evaluated": len([r for r in results if "idea" in r]),
        "results": results,
        "db": str(_db_path(workdir)),
    }


def step_use(
    workdir: Path,
    *,
    min_score: float = 12.0,
    limit: int = 5,
    prove: bool = True,
    structure_only: bool = False,
    write_notes: bool = True,
) -> dict[str, Any]:
    """Keep high-scoring repos: connect+prove into scout_repos + USE notes for your project.

    Does **not** follow or star anyone on GitHub.
    """
    conn = connect(workdir)
    rows = list_entries(conn, min_score=0.0, limit=100)
    # filter scored above threshold, prefer unused first
    candidates = []
    for r in rows:
        if r.get("idea") is None:
            continue
        score = float(r.get("score") or 0)
        if score >= min_score:
            candidates.append(r)
    candidates.sort(key=lambda x: (0 if not x.get("used") else 1, -float(x.get("score") or 0)))
    candidates = candidates[:limit]

    used: list[dict[str, Any]] = []
    notes_bits: list[str] = [
        "# Repo mine — USE (not follow)",
        "",
        f"Min score (idea+skill): **{min_score}**",
        f"Workdir: `{workdir}`",
        "",
        "These repos were **cloned/proven for reuse** in your project. "
        "No GitHub follow or star was performed.",
        "",
    ]

    for r in candidates:
        repo = r["repo"]
        print(f"  use {repo} score={r.get('score')}")
        proof = ga.connect_and_prove(
            repo,
            workdir=Path(workdir),
            pull=True,
            prove=prove,
            run_checks=prove and not structure_only,
        )
        conn_ok = bool((proof.get("connect") or {}).get("ok"))
        path = (proof.get("connect") or {}).get("path") or ""
        pev = proof.get("prove") or {}
        prove_ok = None
        if pev:
            checks = pev.get("checks") or []
            if checks:
                prove_ok = all(c.get("ok") for c in checks)
            else:
                prove_ok = bool(pev.get("ok"))
        mark_used(
            conn,
            repo,
            local_path=path,
            prove_ok=prove_ok,
            prove_json=json.dumps(proof, default=str)[:8000],
        )
        item = {
            "repo": repo,
            "score": r.get("score"),
            "idea": r.get("idea"),
            "skill": r.get("skill"),
            "summary": r.get("summary") or r.get("description"),
            "path": path,
            "connected": conn_ok,
            "prove_ok": prove_ok,
            "html_url": r.get("html_url"),
        }
        used.append(item)
        notes_bits += [
            f"## [{repo}]({r.get('html_url')}) — score {r.get('score')}",
            "",
            f"- idea={r.get('idea')} skill={r.get('skill')}",
            f"- summary: {item['summary']}",
            f"- local: `{path}`",
            f"- prove_ok: {prove_ok}",
            "",
            "### How to use in *your* code",
            "1. Browse the local clone (patterns, tests, CLI shape).",
            "2. Port only what your tests need — do not vendor wholesale.",
            "3. `nexus do . -g \"adopt idea from " + repo + "\"` or hand-patch.",
            "4. `nexus github loop` / `make demo-all` for evidence.",
            "",
        ]

    notes_path = None
    if write_notes and used:
        nd = Path(workdir).resolve() / ".nexus_state" / "repo_mine"
        nd.mkdir(parents=True, exist_ok=True)
        notes_path = nd / f"use-{time.strftime('%Y%m%d-%H%M%S')}.md"
        notes_path.write_text("\n".join(notes_bits), encoding="utf-8")
        latest = nd / "USE_LATEST.md"
        latest.write_text("\n".join(notes_bits), encoding="utf-8")

    conn.close()
    return {
        "step": "use",
        "min_score": min_score,
        "used": len(used),
        "repos": used,
        "notes": str(notes_path) if notes_path else None,
        "policy": "no_follow_no_star",
    }


def step_improve_ours(
    workdir: Path,
    *,
    min_score: float = 12.0,
    limit: int = 3,
    apply: bool = False,
    our_repo: Optional[str] = None,
    dry_run: bool = False,
    worker: str = "auto",
) -> dict[str, Any]:
    """Turn scored/used external repos into a plan (and optional hard apply) for *this* project.

    This is the chase: discover → score → use clones → **improve our code**.

    ``worker``: auto | grok | bus
      - **grok** (default under auto when CLI present): hard agentic improve
      - **bus**: durable GithubJobRunner + local panel (light agents on bus)
    """
    workdir = Path(workdir).resolve()
    conn = connect(workdir)
    rows = list_entries(conn, min_score=min_score, limit=50)
    # prefer used + high score
    rows.sort(
        key=lambda r: (
            0 if r.get("used") else 1,
            -float(r.get("score") or 0),
        )
    )
    picks = [r for r in rows if r.get("idea") is not None][:limit]
    conn.close()

    if not picks:
        return {
            "step": "improve_ours",
            "ok": False,
            "error": "no scored repos — run: nexus github mine run -q \"…\" first",
        }

    lines = [
        "# Improve *our* project from mined repos",
        "",
        f"Target workdir: `{workdir}`",
        f"Sources (score ≥ {min_score}):",
        "",
    ]
    goals: list[str] = []
    for r in picks:
        path = r.get("local_path") or ""
        lines += [
            f"## {r.get('repo')} (score {r.get('score')})",
            f"- idea={r.get('idea')} skill={r.get('skill')}",
            f"- {r.get('summary') or r.get('description') or ''}",
            f"- local clone: `{path}`",
            f"- url: {r.get('html_url')}",
            "",
            "Port **patterns**, not the whole tree. Prefer tests + small modules.",
            "",
        ]
        goals.append(
            f"From {r.get('repo')} ({path}): {r.get('summary') or r.get('description') or 'patterns'}"
        )

    goal = (
        "Improve this repository by adopting useful patterns from these local clones "
        "(do not follow or star anyone; do not vendor entire upstream trees). "
        "Keep tests green; small scoped changes only. Sources:\n- "
        + "\n- ".join(goals)
    )
    lines += [
        "## Combined engineering goal",
        "",
        "```",
        goal,
        "```",
        "",
        "## Commands",
        "",
        "```bash",
        "# plan only (this file)",
        "nexus github mine improve-ours --min-score " + str(min_score),
        "# hard apply with Grok (default worker=auto)",
        "nexus github mine improve-ours --apply --worker grok",
        "make demo-all-quick",
        "```",
        "",
    ]

    out_dir = workdir / ".nexus_state" / "repo_mine"
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "IMPROVE_OURS.md"
    if not dry_run:
        plan_path.write_text("\n".join(lines), encoding="utf-8")

    apply_result = None
    w = (worker or "auto").strip().lower()
    if apply and not dry_run:
        use_grok = w in ("auto", "grok")
        if use_grok:
            try:
                from . import grok_worker as gw

                if gw.grok_available():
                    print(f"  hard improve via Grok (worker={w})…")
                    gr = gw.grok_hard_improve(workdir, goal, max_turns=12)
                    apply_result = {
                        "via": "grok",
                        "ok": bool(gr.get("ok")),
                        "model": gr.get("model"),
                        "returncode": gr.get("returncode"),
                        "summary": (gr.get("text") or "")[:1500],
                        "error": gr.get("error"),
                    }
                    if gr.get("ok"):
                        # still write plan path into result
                        apply_result["plan"] = str(plan_path)
            except Exception as e:
                apply_result = {"via": "grok", "ok": False, "error": str(e)}

        # Bus / durable job if Grok skipped, failed, or worker=bus
        need_bus = w == "bus" or (
            w == "auto" and (not apply_result or not apply_result.get("ok"))
        )
        if need_bus and w != "grok":
            from .github_job import GithubJobRunner, ensure_panel_for_job

            target = our_repo or os.environ.get("NEXUS_GITHUB_REPO") or ""
            if not target:
                try:
                    raw = gc._run_gh(
                        ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                        timeout=20,
                    )
                    target = raw.strip()
                except Exception:
                    target = ""
            if not target:
                apply_result = apply_result or {
                    "error": "set --repo owner/name or NEXUS_GITHUB_REPO for --apply",
                }
            else:
                panel = None
                try:
                    panel = ensure_panel_for_job()
                except Exception:
                    panel = None
                try:
                    print(f"  hard improve via bus job (repo={target})…")
                    jr = GithubJobRunner(panel=panel)
                    job = jr.run(target, goal=goal, max_fix_rounds=2)
                    bus_res = {
                        "via": "bus",
                        "status": getattr(job, "status", None),
                        "job_id": getattr(job, "job_id", None),
                        "repo": target,
                    }
                    if apply_result and not apply_result.get("ok"):
                        apply_result = {"grok_attempt": apply_result, **bus_res}
                    else:
                        apply_result = bus_res
                except Exception as e:
                    apply_result = {
                        "via": "bus",
                        "error": str(e),
                        "repo": target,
                        "grok_attempt": apply_result,
                    }
        elif w == "grok" and not apply_result:
            apply_result = {"via": "grok", "ok": False, "error": "grok CLI not available"}

    return {
        "step": "improve_ours",
        "ok": True,
        "worker": w,
        "sources": [
            {
                "repo": r.get("repo"),
                "score": r.get("score"),
                "path": r.get("local_path"),
            }
            for r in picks
        ],
        "plan": str(plan_path),
        "goal_preview": goal[:500],
        "apply": apply_result,
        "chase": "score → use clones → improve our code",
    }


def run_pipeline(
    workdir: Path,
    *,
    query: str,
    fetch_count: int = 8,
    language: Optional[str] = "Python",
    max_stars: Optional[int] = 500,
    eval_limit: int = 8,
    min_score: float = 12.0,
    use_limit: int = 5,
    use_ollama: bool = True,
    prove: bool = True,
    improve: bool = False,
    apply_improve: bool = False,
    our_repo: Optional[str] = None,
    grader: str = "auto",
    worker: str = "auto",
) -> dict[str, Any]:
    """fetch → evaluate → use → optional improve-ours (mine for code, never follow/star).

    Grading hard work defaults to **Grok**; local Ollama is light fallback.
    """
    print(f"=== NEXUS repo mine (use, don't follow) ===")
    print(f"  query: {query!r}  grader={grader}  worker={worker}")
    f = step_fetch(
        workdir,
        query=query,
        count=fetch_count,
        language=language,
        max_stars=max_stars,
    )
    print(f"  fetch: +{f['inserted']} repos")
    e = step_evaluate(
        workdir,
        limit=eval_limit,
        use_ollama=use_ollama,
        grader=grader,
    )
    print(f"  evaluate: {e['evaluated']} graded (grader={e.get('grader')})")
    u = step_use(
        workdir,
        min_score=min_score,
        limit=use_limit,
        prove=prove,
    )
    print(f"  use: {u['used']} kept for your project")
    if u.get("notes"):
        print(f"  notes: {u['notes']}")
    imp = None
    if improve or apply_improve:
        imp = step_improve_ours(
            workdir,
            min_score=min_score,
            limit=min(use_limit, 3),
            apply=apply_improve,
            our_repo=our_repo,
            worker=worker,
        )
        print(f"  improve_ours: plan={imp.get('plan')} apply={imp.get('apply')}")
    return {"fetch": f, "evaluate": e, "use": u, "improve_ours": imp}
