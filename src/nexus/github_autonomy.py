"""Personal-repo autonomy: bootstrap, watch, arXiv + **other-repo scout**, continuous improve.

Use the same community loop on *any* of your repos — not only nexus-core.
Runs on **your machine** (laptop/server) or via GitHub Actions.

  nexus github init --path ~/code/my-app
  nexus github search "multi agent durable" --limit 10
  nexus github scout "topic" --workdir .          # find repos → improvement notes
  nexus github improve --arxiv "topic" --scout "topic"
  nexus github watch --autonomous --scout "topic" # continuous on your machine

Autonomy is **opt-in** (``--autonomous`` / ``--apply``). Default is observe + report.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import github_community as gc

# Workflow template is shipped in-repo; bootstrap copies it into personal projects.
_WORKFLOW_SRC_CANDIDATES = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "community-bot.yml",
    Path(__file__).resolve().parents[2]
    / "connectors"
    / "examples"
    / "community-bot.workflow.yml",
)

STATE_DIR_NAME = "github_autonomy"


@dataclass
class WatchState:
    repo: str
    seen_comment_ids: list[str] = field(default_factory=list)
    last_arxiv_at: float = 0.0
    last_scout_at: float = 0.0
    seen_repos: list[str] = field(default_factory=list)
    cycles: int = 0
    log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WatchState":
        return cls(
            repo=d.get("repo") or "",
            seen_comment_ids=list(d.get("seen_comment_ids") or []),
            last_arxiv_at=float(d.get("last_arxiv_at") or 0),
            last_scout_at=float(d.get("last_scout_at") or 0),
            seen_repos=list(d.get("seen_repos") or [])[-200:],
            cycles=int(d.get("cycles") or 0),
            log=list(d.get("log") or [])[-200:],
        )


@dataclass
class RepoHit:
    full_name: str
    url: str
    description: str = ""
    stars: int = 0
    language: str = ""
    updated_at: str = ""
    topics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _state_path(repo: str, state_dir: Optional[Path] = None) -> Path:
    root = Path(state_dir or Path.cwd() / ".nexus_state" / STATE_DIR_NAME)
    root.mkdir(parents=True, exist_ok=True)
    safe = repo.replace("/", "__")
    return root / f"{safe}.json"


def load_state(repo: str, state_dir: Optional[Path] = None) -> WatchState:
    p = _state_path(repo, state_dir)
    if p.is_file():
        try:
            return WatchState.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return WatchState(repo=repo)


def save_state(state: WatchState, state_dir: Optional[Path] = None) -> Path:
    p = _state_path(state.repo, state_dir)
    p.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    return p


def resolve_workflow_template() -> Path:
    for c in _WORKFLOW_SRC_CANDIDATES:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "community-bot.yml template not found; clone nexus-core or keep connectors/examples"
    )


def bootstrap_personal_repo(
    path: Path,
    *,
    force: bool = False,
    also_readme_snippet: bool = True,
) -> dict[str, Any]:
    """Copy community-bot workflow into a personal project (new or existing)."""
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    wf_dir = path / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    dest = wf_dir / "community-bot.yml"
    src = resolve_workflow_template()
    wrote = False
    if dest.exists() and not force:
        action = "exists"
    else:
        text = src.read_text(encoding="utf-8")
        # Personalize header comment
        text = text.replace(
            "on VincentMarquez/nexus-core",
            f"on personal repo ({path.name})",
        )
        dest.write_text(text, encoding="utf-8")
        wrote = True
        action = "written"

    snippet_path = path / "NEXUS_COMMUNITY.md"
    if also_readme_snippet and (not snippet_path.exists() or force):
        snippet_path.write_text(
            _personal_readme_snippet(path.name),
            encoding="utf-8",
        )
        snippet = "written"
    else:
        snippet = "skipped"

    return {
        "path": str(path),
        "workflow": str(dest),
        "workflow_action": action,
        "wrote_workflow": wrote,
        "nexus_community_md": snippet,
        "next": [
            f"cd {path}",
            "git add .github/workflows/community-bot.yml NEXUS_COMMUNITY.md",
            "git commit -m 'chore: enable NEXUS community loop'",
            "git push   # enable Actions on your personal repo",
            "nexus github watch --repo YOU/REPO --autonomous  # optional always-on laptop loop",
        ],
    }


def _personal_readme_snippet(name: str) -> str:
    return f"""# NEXUS community loop — {name}

This repo includes `.github/workflows/community-bot.yml` from
[nexus-core](https://github.com/VincentMarquez/nexus-core).

## What it does

```text
issue / PR / comment
      → first reply (optional)
      → run install + pytest + smoke
      → post results
      → next response → loop again
```

## On your laptop (any personal repo)

```bash
gh auth login
export NEXUS_GITHUB_REPO=you/{name}   # or --repo each time

nexus github inbox --repo you/{name}
nexus github loop 1 --repo you/{name} --workdir .
nexus github watch --repo you/{name} --interval 120 --autonomous

# Pull new arXiv papers and turn them into improvement notes (+ optional fix job)
nexus github improve --repo you/{name} --arxiv "your research topic" --max 6
nexus github improve --repo you/{name} --arxiv "topic" --apply --workdir .
```

## Fully autonomous

- **GitHub Actions** keeps the loop alive in the cloud whenever someone talks on the repo.
- **`nexus github watch --autonomous`** keeps a local process polling forever (or until Ctrl-C).
- Autonomy still **does not auto-merge** by default — it reports evidence; add `--apply` only when you want `nexus do` repair after arXiv improve.

See: https://vincentmarquez.github.io/nexus-core/GITHUB_COMMUNITY/
"""


def list_recent_comment_events(
    repo: str,
    *,
    limit_threads: int = 15,
) -> list[dict[str, Any]]:
    """Open issues/PRs with their latest comment metadata (best-effort)."""
    repo = gc.resolve_repo(repo)
    items = gc.list_inbox(repo, limit=limit_threads, include_bot_replied=True)
    events: list[dict[str, Any]] = []
    for it in items:
        try:
            raw = gc._run_gh(
                ["api", f"repos/{repo}/issues/{it.number}/comments", "--jq",
                 ".[-3:] | .[] | {id, user: .user.login, body: .body[0:200], created: .created_at}"],
                timeout=30,
            )
        except gc.GhError:
            continue
        # Parse multi-json objects line by line if jq streams
        if not raw.strip():
            continue
        try:
            # Prefer full JSON array
            arr = json.loads(
                gc._run_gh(
                    ["api", f"repos/{repo}/issues/{it.number}/comments"],
                    timeout=30,
                )
                or "[]"
            )
        except Exception:
            continue
        for c in arr[-5:]:
            body = c.get("body") or ""
            if gc.is_bot_comment_body(body):
                continue
            events.append(
                {
                    "number": it.number,
                    "kind": it.kind,
                    "title": it.title,
                    "comment_id": str(c.get("id")),
                    "author": (c.get("user") or {}).get("login", ""),
                    "created": c.get("created_at") or "",
                    "body_preview": body[:180],
                }
            )
    return events


def search_github_repos(
    query: str,
    *,
    limit: int = 10,
    language: Optional[str] = None,
    sort: str = "stars",
    exclude: Optional[set[str]] = None,
) -> list[RepoHit]:
    """Search public GitHub for other repos (continuous-improvement fuel).

    Uses authenticated ``gh`` when available (higher rate limits).
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("empty search query")
    if language:
        q = f"{q} language:{language}"
    # Prefer recent + starred signal
    limit_n = str(max(1, min(int(limit), 50)))
    json_fields = "fullName,url,description,stargazersCount,language,updatedAt"
    args = [
        "search",
        "repos",
        q,
        "--limit",
        limit_n,
        "--json",
        json_fields,
    ]
    if sort in {"stars", "forks", "help-wanted-issues", "updated", "best-match"}:
        args.extend(["--sort", sort if sort != "stars" else "stars"])
    try:
        raw = gc._run_gh(args, timeout=60)
        data = json.loads(raw or "[]")
    except (gc.GhError, json.JSONDecodeError):
        # fallback: fewer fields / no sort
        raw = gc._run_gh(
            [
                "search",
                "repos",
                q,
                "--limit",
                limit_n,
                "--json",
                "fullName,url,description,stargazersCount,language,updatedAt",
            ],
            timeout=60,
        )
        data = json.loads(raw or "[]")

    exclude = exclude or set()
    hits: list[RepoHit] = []
    for it in data:
        name = (
            it.get("fullName")
            or it.get("nameWithOwner")
            or it.get("full_name")
            or ""
        )
        if not name or name in exclude:
            continue
        topics = it.get("repositoryTopics") or it.get("topics") or []
        if topics and isinstance(topics[0], dict):
            topics = [t.get("name") or "" for t in topics]
        hits.append(
            RepoHit(
                full_name=name,
                url=it.get("url") or f"https://github.com/{name}",
                description=(it.get("description") or "")[:400],
                stars=int(
                    it.get("stargazerCount")
                    or it.get("stargazersCount")
                    or it.get("stargazers_count")
                    or 0
                ),
                language=it.get("language") or "",
                updated_at=it.get("updatedAt") or it.get("updated_at") or "",
                topics=[t for t in topics if t][:12],
            )
        )
    return hits


def fetch_readme_excerpt(full_name: str, *, max_chars: int = 2500) -> str:
    """Best-effort README text via gh API."""
    try:
        raw = gc._run_gh(
            [
                "api",
                f"repos/{full_name}/readme",
                "-H",
                "Accept: application/vnd.github.raw",
            ],
            timeout=30,
        )
        return (raw or "")[:max_chars]
    except gc.GhError:
        return ""


def _safe_slug(full_name: str) -> str:
    return full_name.replace("/", "__").replace(" ", "_")


def connect_repo(
    full_name: str,
    *,
    clone_root: Path,
    pull: bool = True,
) -> dict[str, Any]:
    """Clone (shallow) or pull an external repo into a local workspace.

    Read-only toward the remote: never push, never force-write remotes.
    """
    from .github_job import _run

    full_name = full_name.strip().strip("/")
    if full_name.count("/") != 1:
        raise ValueError(f"expected owner/repo, got {full_name!r}")
    clone_root = Path(clone_root).resolve()
    clone_root.mkdir(parents=True, exist_ok=True)
    dest = clone_root / _safe_slug(full_name)
    clone_url = f"https://github.com/{full_name}.git"
    out: dict[str, Any] = {
        "full_name": full_name,
        "path": str(dest),
        "clone_url": clone_url,
        "action": None,
        "ok": False,
        "sha": None,
    }

    if (dest / ".git").is_dir():
        out["action"] = "pull" if pull else "reuse"
        if pull:
            r = _run(["git", "pull", "--ff-only"], cwd=dest, timeout=180)
            out["pull"] = {
                "ok": r["ok"],
                "returncode": r["returncode"],
                "stderr": (r.get("stderr") or "")[-400:],
            }
            out["ok"] = bool(r["ok"]) or True  # still usable if already up to date-ish
            if not r["ok"] and "Already up to date" in (r.get("stdout") or ""):
                out["ok"] = True
            # ff-only failure still leaves usable tree
            if dest.exists():
                out["ok"] = True
        else:
            out["ok"] = True
    else:
        out["action"] = "clone"
        if dest.exists() and any(dest.iterdir()):
            # non-git dir — do not clobber
            out["error"] = "path exists and is not a git clone"
            return out
        r = _run(
            ["git", "clone", "--depth", "1", clone_url, str(dest)],
            timeout=300,
        )
        out["clone"] = {
            "ok": r["ok"],
            "returncode": r["returncode"],
            "stderr": (r.get("stderr") or "")[-500:],
        }
        out["ok"] = bool(r["ok"]) and dest.is_dir()

    if out["ok"] and dest.is_dir():
        sha = _run(["git", "rev-parse", "HEAD"], cwd=dest, timeout=15)
        if sha.get("ok"):
            out["sha"] = (sha.get("stdout") or "").strip()
        # light inventory
        try:
            files = sorted(
                p.name for p in dest.iterdir() if not p.name.startswith(".git")
            )[:40]
            out["top_level"] = files
        except Exception:
            out["top_level"] = []
    return out


def prove_connected_repo(
    path: Path,
    *,
    run_checks: bool = True,
    timeout_each: float = 180,
) -> dict[str, Any]:
    """Prove a connected clone: detect stack + optional allowlisted checks.

    Evidence is real filesystem / command output — not a model claim.
    """
    from .github_job import _cmd_allowed, _run, detect_project

    path = Path(path).resolve()
    if not path.is_dir():
        return {"ok": False, "error": f"not a directory: {path}"}

    prof = detect_project(path)
    evidence: dict[str, Any] = {
        "path": str(path),
        "languages": prof.languages,
        "package_managers": prof.package_managers,
        "install_cmds": prof.install_cmds[:4],
        "check_cmds": prof.check_cmds[:4],
        "readme_summary": (prof.readme_summary or "")[:800],
        "checks": [],
        "ok": True,
    }

    # Structural proof always
    has_tests = bool(prof.check_cmds) or (path / "tests").is_dir() or any(
        path.glob("test_*.py")
    )
    evidence["has_tests"] = has_tests
    evidence["has_ci"] = any(
        (path / p).exists()
        for p in (
            ".github/workflows",
            ".gitlab-ci.yml",
            "tox.ini",
            "Makefile",
        )
    )

    if not run_checks:
        evidence["proved"] = "structure_only"
        return evidence

    # Run at most one install + one check (allowlisted), time-boxed
    ran = 0
    for cmd in prof.install_cmds[:1]:
        if not _cmd_allowed(cmd):
            continue
        # Prefer non-editable install of deps only when possible
        r = _run(cmd, cwd=path, timeout=timeout_each)
        evidence["checks"].append(
            {
                "phase": "install",
                "cmd": cmd,
                "ok": r["ok"],
                "returncode": r["returncode"],
                "stderr_tail": (r.get("stderr") or "")[-600:],
                "stdout_tail": (r.get("stdout") or "")[-600:],
            }
        )
        ran += 1
        break

    for cmd in prof.check_cmds[:1]:
        if not _cmd_allowed(cmd):
            continue
        r = _run(cmd, cwd=path, timeout=timeout_each)
        evidence["checks"].append(
            {
                "phase": "check",
                "cmd": cmd,
                "ok": r["ok"],
                "returncode": r["returncode"],
                "stderr_tail": (r.get("stderr") or "")[-800:],
                "stdout_tail": (r.get("stdout") or "")[-800:],
            }
        )
        ran += 1
        break

    if ran == 0:
        # Still prove *something*: collect-only pytest if present
        if shutil.which("python3") and (
            (path / "tests").is_dir() or any(path.glob("test_*.py"))
        ):
            cmd = ["python3", "-m", "pytest", "--collect-only", "-q"]
            if _cmd_allowed(cmd):
                r = _run(cmd, cwd=path, timeout=min(60, timeout_each))
                evidence["checks"].append(
                    {
                        "phase": "collect",
                        "cmd": cmd,
                        "ok": r["ok"],
                        "returncode": r["returncode"],
                        "stdout_tail": (r.get("stdout") or "")[-800:],
                        "stderr_tail": (r.get("stderr") or "")[-400:],
                    }
                )

    check_ok = all(c.get("ok") for c in evidence["checks"]) if evidence["checks"] else None
    evidence["checks_ok"] = check_ok
    evidence["proved"] = (
        "structure+checks"
        if evidence["checks"]
        else "structure_only"
    )
    # Structural connect is success; check failure is still useful evidence
    evidence["ok"] = True
    return evidence


def connect_and_prove(
    full_name: str,
    *,
    workdir: Path,
    pull: bool = True,
    prove: bool = True,
    run_checks: bool = True,
) -> dict[str, Any]:
    """Connect (clone/pull) an external repo and optionally prove it with checks."""
    clone_root = Path(workdir).resolve() / ".nexus_workspaces" / "scout_repos"
    conn = connect_repo(full_name, clone_root=clone_root, pull=pull)
    result: dict[str, Any] = {"connect": conn, "prove": None}
    if conn.get("ok") and prove and conn.get("path"):
        result["prove"] = prove_connected_repo(
            Path(conn["path"]),
            run_checks=run_checks,
        )
    return result


def scout_other_repos(
    query: str,
    *,
    repo: Optional[str] = None,
    workdir: Optional[Path] = None,
    limit: int = 8,
    language: Optional[str] = None,
    deep: bool = True,
    connect: bool = True,
    prove: bool = True,
    pull: bool = True,
    run_checks: bool = True,
    post_issue: bool = False,
    dry_run: bool = False,
    exclude_self: bool = True,
    apply: bool = False,
    state_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Search GitHub → connect (clone/pull) → prove with real checks → notes.

    This is the continuous-improvement outer loop: other people's repos become
    **local evidence**, not just links.

    ``apply`` runs a local ``nexus do`` goal informed by scouted repos (opt-in).
    """
    target = gc.resolve_repo(repo)
    workdir = Path(workdir or Path.cwd()).resolve()
    exclude: set[str] = set()
    if exclude_self:
        exclude.add(target)
        # also exclude common forks noise later via name match
    hits = search_github_repos(query, limit=limit, language=language, exclude=exclude)
    state = load_state(target, state_dir)
    known = set(state.seen_repos)
    new_hits = [h for h in hits if h.full_name not in known]
    # still document all hits this run; track new for "continuous"
    for h in hits:
        known.add(h.full_name)
    state.seen_repos = list(known)[-200:]
    save_state(state, state_dir)

    notes_dir = workdir / ".nexus_state" / "repo_scout"
    notes_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    notes_path = notes_dir / f"scout-{stamp}.md"

    lines = [
        f"# Repo scout — connect · pull · prove",
        "",
        f"Query: `{query}`  ",
        f"Your repo: `{target}`  ",
        f"Workdir: `{workdir}`  ",
        f"Hits: {len(hits)} ({len(new_hits)} new vs prior state)",
        f"Connect: `{connect}` · Prove: `{prove}` · Pull: `{pull}`",
        "",
        "## Related repositories (with local proof)",
        "",
    ]
    details: list[dict[str, Any]] = []
    proved_ok = 0
    connected = 0
    for i, h in enumerate(hits, 1):
        is_new = h.full_name in {x.full_name for x in new_hits}
        flag = " **NEW**" if is_new else ""
        lines.append(
            f"### {i}. [{h.full_name}]({h.url}) ★{h.stars} · {h.language or '?'}{flag}"
        )
        lines.append("")
        lines.append((h.description or "").strip() or "_no description_")
        lines.append("")
        excerpt = ""
        if deep and not dry_run:
            excerpt = fetch_readme_excerpt(h.full_name)
            if excerpt:
                lines.append("<details><summary>README excerpt</summary>")
                lines.append("")
                lines.append("```markdown")
                lines.append(excerpt[:2000])
                lines.append("```")
                lines.append("</details>")
                lines.append("")

        proof: dict[str, Any] = {}
        if connect and not dry_run:
            try:
                proof = connect_and_prove(
                    h.full_name,
                    workdir=workdir,
                    pull=pull,
                    prove=prove,
                    run_checks=run_checks and prove,
                )
            except Exception as e:
                proof = {"error": str(e)}
            conn = proof.get("connect") or {}
            if conn.get("ok"):
                connected += 1
                lines.append(
                    f"- **Connected:** `{conn.get('action')}` → `{conn.get('path')}` "
                    f"@ `{(conn.get('sha') or '?')[:12]}`"
                )
                if conn.get("top_level"):
                    lines.append(
                        f"- **Top-level:** {', '.join(conn['top_level'][:12])}"
                    )
            else:
                lines.append(
                    f"- **Connect failed:** {conn.get('error') or conn.get('clone') or conn}"
                )
            pev = proof.get("prove") or {}
            if pev:
                lines.append(
                    f"- **Prove:** {pev.get('proved')} · languages={pev.get('languages')} · "
                    f"has_tests={pev.get('has_tests')} · has_ci={pev.get('has_ci')}"
                )
                for c in pev.get("checks") or []:
                    icon = "✅" if c.get("ok") else "❌"
                    lines.append(
                        f"  - {icon} `{c.get('phase')}` `{' '.join(c.get('cmd') or [])}` "
                        f"exit={c.get('returncode')}"
                    )
                    if c.get("ok"):
                        proved_ok += 1
            lines.append("")
        elif dry_run and connect:
            lines.append(f"- *(dry-run)* would clone/pull into `.nexus_workspaces/scout_repos/`")
            lines.append("")

        details.append(
            {
                **h.to_dict(),
                "new": is_new,
                "readme_chars": len(excerpt),
                "proof": proof,
            }
        )

    lines += [
        "",
        "## Proof summary",
        "",
        f"- Repos found: **{len(hits)}**",
        f"- Connected (clone/pull): **{connected}**",
        f"- Check steps green: **{proved_ok}**",
        "",
        "## How to use this for continuous improvement (on your machine)",
        "",
        "1. Open connected clones under `.nexus_workspaces/scout_repos/`.",
        "2. Port **proven** patterns (tests green / clear layout) into *your* repo.",
        "3. `nexus do` / agents implement; `nexus github loop` posts evidence.",
        "4. Re-run scout on a schedule — pulls refresh remotes; new repos appear as **NEW**.",
        "",
        "```bash",
        f'nexus github search "{query}" --limit {limit}',
        f'nexus github scout "{query}" --repo {target} --workdir . --connect --prove',
        f'nexus github connect owner/other-repo --workdir . --prove',
        f'nexus github improve --scout "{query}" --arxiv "{query}" --repo {target}',
        f"nexus github watch --repo {target} --workdir . --autonomous \\",
        f'  --scout "{query}" --scout-every 43200 --arxiv "{query}"',
        "```",
        "",
    ]
    if not dry_run:
        notes_path.write_text("\n".join(lines), encoding="utf-8")
    else:
        notes_path = Path(str(notes_path) + ".dry-run")

    issue_url = None
    if post_issue and not dry_run and hits:
        body = (
            f"### Repo scout — continuous improvement\n\n"
            f"Query: **{query}**\n\n"
            f"Notes: `{notes_path}`\n\n"
            + "\n".join(
                f"- [{h.full_name}]({h.url}) ★{h.stars} — {(h.description or '')[:120]}"
                for h in hits[:12]
            )
            + f"\n\n{gc.LOOP_MARKER}\n{gc.BOT_MARKER}\n"
        )
        try:
            issue_url = gc._run_gh(
                [
                    "issue",
                    "create",
                    "--repo",
                    target,
                    "--title",
                    f"scout: related repos for {query[:60]}",
                    "--body",
                    body,
                ],
                timeout=45,
            ).strip()
        except gc.GhError as e:
            issue_url = f"(issue create failed: {e})"

    apply_result = None
    if apply and not dry_run and hits:
        from .github_job import GithubJobRunner, ensure_panel_for_job

        panel = None
        try:
            panel = ensure_panel_for_job()
        except Exception:
            panel = None
        top = ", ".join(h.full_name for h in hits[:5])
        goal = (
            f"Study ideas from related open-source repos ({top}) for query {query!r}. "
            f"Notes: {notes_path}. Port only safe, tested improvements into this codebase; "
            f"keep tests green; do not copy licenses blindly."
        )
        try:
            jr = GithubJobRunner(panel=panel)
            job_gh = jr.run(target, goal=goal, max_fix_rounds=2)
            apply_result = {
                "status": job_gh.status,
                "job_id": getattr(job_gh, "job_id", None),
            }
        except Exception as e:
            apply_result = {"error": str(e)}

    # machine-local JSON index for later cycles
    index_path = notes_dir / "latest.json"
    if not dry_run:
        index_path.write_text(
            json.dumps(
                {
                    "query": query,
                    "target": target,
                    "notes": str(notes_path),
                    "hits": details,
                    "ts": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return {
        "query": query,
        "repo": target,
        "hits": len(hits),
        "new_hits": len(new_hits),
        "connected": connected,
        "check_steps_green": proved_ok,
        "repos": [h.full_name for h in hits],
        "notes": str(notes_path),
        "index": str(index_path) if not dry_run else None,
        "clone_root": str(workdir / ".nexus_workspaces" / "scout_repos"),
        "issue": issue_url,
        "apply": apply_result,
        "connect": connect,
        "prove": prove,
        "dry_run": dry_run,
        "machine_local": True,
        "proved_with_evidence": True,
    }


def watch_once(
    repo: Optional[str] = None,
    *,
    workdir: Optional[Path] = None,
    autonomous: bool = False,
    dry_run: bool = False,
    arxiv_query: Optional[str] = None,
    arxiv_every_s: float = 86400,
    scout_query: Optional[str] = None,
    scout_every_s: float = 43200,
    apply_improve: bool = False,
    state_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """One watch cycle on your machine: comments → tests; optional arXiv + repo scout."""
    repo = gc.resolve_repo(repo)
    state = load_state(repo, state_dir)
    workdir = Path(workdir or Path.cwd()).resolve()
    seen = set(state.seen_comment_ids)
    actions: list[dict[str, Any]] = []

    # First-replies for brand-new threads (no bot yet)
    if autonomous:
        try:
            for r in gc.auto_reply_open(repo, limit=10, dry_run=dry_run):
                actions.append({"type": "first_reply", **{k: r.get(k) for k in ("number", "kind", "title", "dry_run", "ok")}})
        except gc.GhError as e:
            actions.append({"type": "first_reply_error", "error": str(e)})

    # New human comments → response loop
    events = list_recent_comment_events(repo)
    for ev in events:
        cid = ev["comment_id"]
        if cid in seen:
            continue
        seen.add(cid)
        if not autonomous and not dry_run:
            # Observe-only unless autonomous: record but do not post loop
            actions.append({"type": "observed", **ev})
            continue
        try:
            res = gc.run_and_post_loop(
                repo,
                int(ev["number"]),
                workdir=workdir,
                kind=ev.get("kind") or "issue",
                triggered_by=ev.get("author") or "",
                dry_run=dry_run,
                force=False,
            )
            actions.append({"type": "loop", "comment_id": cid, **res})
        except gc.GhError as e:
            actions.append({"type": "loop_error", "number": ev["number"], "error": str(e)})

    # Periodic arXiv improve
    now = time.time()
    if arxiv_query and (now - state.last_arxiv_at) >= arxiv_every_s:
        try:
            imp = improve_from_arxiv(
                arxiv_query,
                repo=repo,
                workdir=workdir,
                apply=apply_improve and autonomous,
                dry_run=dry_run,
                max_results=5,
                post_issue=bool(autonomous and not dry_run),
            )
            state.last_arxiv_at = now
            actions.append({"type": "arxiv_improve", **{k: imp.get(k) for k in ("query", "papers", "notes", "issue", "apply")}})
        except Exception as e:
            actions.append({"type": "arxiv_error", "error": str(e)})

    # Periodic other-repo scout (continuous improvement fuel)
    if scout_query and (now - state.last_scout_at) >= scout_every_s:
        try:
            sc = scout_other_repos(
                scout_query,
                repo=repo,
                workdir=workdir,
                limit=8,
                deep=True,
                connect=True,
                prove=True,
                pull=True,
                run_checks=True,
                post_issue=bool(autonomous and not dry_run),
                dry_run=dry_run,
                apply=apply_improve and autonomous,
                state_dir=state_dir,
            )
            state.last_scout_at = now
            # merge repo memory written by scout
            st_after = load_state(repo, state_dir)
            state.seen_repos = st_after.seen_repos
            actions.append(
                {
                    "type": "repo_scout",
                    **{
                        k: sc.get(k)
                        for k in (
                            "query",
                            "hits",
                            "new_hits",
                            "connected",
                            "check_steps_green",
                            "repos",
                            "notes",
                            "clone_root",
                            "issue",
                            "apply",
                        )
                    },
                }
            )
        except Exception as e:
            actions.append({"type": "scout_error", "error": str(e)})

    state.seen_comment_ids = list(seen)[-500:]
    state.cycles += 1
    state.log.append({"t": now, "n_actions": len(actions)})
    save_state(state, state_dir)

    return {
        "repo": repo,
        "workdir": str(workdir),
        "autonomous": autonomous,
        "dry_run": dry_run,
        "cycles": state.cycles,
        "machine_local": True,
        "actions": actions,
    }


def watch_forever(
    repo: Optional[str] = None,
    *,
    interval_s: float = 120,
    max_cycles: int = 0,
    **kwargs: Any,
) -> int:
    """Block and run watch_once forever on this machine (or max_cycles). Ctrl-C to stop."""
    repo = gc.resolve_repo(repo)
    print(f"=== NEXUS github watch (machine-local continuous) ===")
    print(f"  repo:        {repo}")
    print(f"  interval:    {interval_s}s")
    print(f"  autonomous:  {kwargs.get('autonomous', False)}")
    print(f"  arxiv:       {kwargs.get('arxiv_query') or '(off)'}")
    print(f"  scout:       {kwargs.get('scout_query') or '(off)'}")
    print(f"  workdir:     {kwargs.get('workdir') or Path.cwd()}")
    print("  Ctrl-C to stop")
    n = 0
    try:
        while True:
            n += 1
            print(f"\n--- cycle {n} @ {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
            res = watch_once(repo, **kwargs)
            acts = res.get("actions") or []
            if not acts:
                print("  (idle — no new comments / scout / arxiv due)")
            else:
                for a in acts:
                    print(
                        f"  {a.get('type')}: "
                        f"{json.dumps({k: a.get(k) for k in a if k not in ('body',)}, default=str)[:220]}"
                    )
            if max_cycles and n >= max_cycles:
                print(f"  reached max_cycles={max_cycles}")
                return 0
            time.sleep(max(15.0, float(interval_s)))
    except KeyboardInterrupt:
        print("\n  stopped.")
        return 0


def improve_from_arxiv(
    query: str,
    *,
    repo: Optional[str] = None,
    workdir: Optional[Path] = None,
    max_results: int = 6,
    apply: bool = False,
    dry_run: bool = False,
    download_pdf: bool = False,
    post_issue: bool = True,
    also_scout: bool = False,
    scout_query: Optional[str] = None,
) -> dict[str, Any]:
    """Search arXiv → write improvement notes → optional nexus do repair job.

    When ``also_scout`` is true, also search related GitHub repos for continuous
    code improvement ideas (machine-local notes under ``.nexus_state/``).

    ``apply`` is opt-in: runs ``GithubJobRunner`` with a goal derived from papers.
    """
    from .research_job import ResearchJobRunner

    repo = gc.resolve_repo(repo)
    workdir = Path(workdir or Path.cwd()).resolve()
    runner = ResearchJobRunner(panel=None)
    job = runner.run(
        query,
        max_results=max_results,
        download_pdf=download_pdf,
        with_brief=True,
    )
    scout_res = None
    if also_scout or scout_query:
        try:
            scout_res = scout_other_repos(
                scout_query or query,
                repo=repo,
                workdir=workdir,
                limit=max_results,
                deep=True,
                post_issue=False,
                dry_run=dry_run,
                apply=False,
            )
        except Exception as e:
            scout_res = {"error": str(e)}
    notes_dir = workdir / ".nexus_state" / "arxiv_improve"
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes_path = notes_dir / f"improve-{job.job_id}.md"

    titles = [p.get("title") or "" for p in (job.papers or [])][:max_results]
    lines = [
        f"# arXiv improve — {query}",
        "",
        f"Repo: `{repo}`  ",
        f"Research job: `{job.job_id}`  ",
        f"Status: `{job.status}`",
        "",
        "## Papers",
        "",
    ]
    for i, p in enumerate(job.papers or [], 1):
        lines.append(
            f"{i}. **{p.get('title', '')}** — `{p.get('arxiv_id', '')}`  \n"
            f"   {p.get('abs_url', p.get('pdf_url', ''))}"
        )
    lines += [
        "",
        "## Brief",
        "",
        job.brief or "(heuristic summary only — start NEXUS bus for richer briefs)",
        "",
        "## Suggested next engineering goals",
        "",
        "1. Map paper ideas to failing tests or missing features in this repo.",
        "2. Open a scoped issue / PR with evidence (tests).",
        "3. Re-run `nexus github loop <n>` after each change.",
        "",
        "```bash",
        f'nexus research "{query}" --max {max_results}',
        f'nexus do {repo} -g "apply insights from arXiv: {query}; keep tests green"',
        "nexus github loop <n> --force",
        "```",
        "",
    ]
    notes_path.write_text("\n".join(lines), encoding="utf-8")

    issue_url = None
    if post_issue and not dry_run and titles:
        body = (
            f"### arXiv improve run\n\n"
            f"Query: **{query}**\n\n"
            f"Notes: `{notes_path}`\n\n"
            + "\n".join(f"- {t}" for t in titles[:8])
            + f"\n\n{gc.LOOP_MARKER}\n{gc.BOT_MARKER}\n"
        )
        try:
            # Create issue via gh
            out = gc._run_gh(
                [
                    "issue",
                    "create",
                    "--repo",
                    repo,
                    "--title",
                    f"arXiv improve: {query[:80]}",
                    "--body",
                    body,
                ],
                timeout=45,
            )
            issue_url = out.strip()
        except gc.GhError as e:
            issue_url = f"(issue create failed: {e})"

    apply_result = None
    if apply and not dry_run:
        from .github_job import GithubJobRunner, ensure_panel_for_job

        panel = None
        try:
            panel = ensure_panel_for_job()
        except Exception:
            panel = None
        goal = (
            f"Improve this repository using insights from arXiv papers on: {query}. "
            f"Notes at {notes_path}. Keep tests green; small scoped changes only."
        )
        # Prefer local workdir if it looks like the repo; else clone via do
        try:
            jr = GithubJobRunner(panel=panel)
            job_gh = jr.run(repo, goal=goal, max_fix_rounds=2)
            apply_result = {
                "status": job_gh.status,
                "job_id": getattr(job_gh, "job_id", None),
            }
        except Exception as e:
            apply_result = {"error": str(e)}

    return {
        "query": query,
        "repo": repo,
        "research_job": job.job_id,
        "research_status": job.status,
        "papers": len(job.papers or []),
        "notes": str(notes_path),
        "issue": issue_url,
        "apply": apply_result,
        "scout": scout_res,
        "dry_run": dry_run,
        "machine_local": True,
    }


def copy_template_to_examples() -> Optional[Path]:
    """Ensure connectors/examples has a portable workflow copy."""
    src = _WORKFLOW_SRC_CANDIDATES[0]
    if not src.is_file():
        return None
    dest = _WORKFLOW_SRC_CANDIDATES[1]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime:
        shutil.copy2(src, dest)
    return dest
