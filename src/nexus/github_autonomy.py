"""Personal-repo autonomy: bootstrap community bot, continuous watch, arXiv improve.

Use the same community loop on *any* of your repos — not only nexus-core.

  nexus github init --path ~/code/my-app     # drop workflow into a new/existing repo
  nexus github watch --autonomous           # keep polling: inbox → tests → post
  nexus github improve --arxiv "topic"      # pull papers → notes → optional fix job

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
            cycles=int(d.get("cycles") or 0),
            log=list(d.get("log") or [])[-200:],
        )


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


def watch_once(
    repo: Optional[str] = None,
    *,
    workdir: Optional[Path] = None,
    autonomous: bool = False,
    dry_run: bool = False,
    arxiv_query: Optional[str] = None,
    arxiv_every_s: float = 86400,
    apply_improve: bool = False,
    state_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """One watch cycle: new human comments → test loop; optional arXiv improve."""
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
            )
            state.last_arxiv_at = now
            actions.append({"type": "arxiv_improve", **imp})
        except Exception as e:
            actions.append({"type": "arxiv_error", "error": str(e)})

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
        "actions": actions,
    }


def watch_forever(
    repo: Optional[str] = None,
    *,
    interval_s: float = 120,
    max_cycles: int = 0,
    **kwargs: Any,
) -> int:
    """Block and run watch_once forever (or max_cycles). Ctrl-C to stop."""
    repo = gc.resolve_repo(repo)
    print(f"=== NEXUS github watch ===")
    print(f"  repo:        {repo}")
    print(f"  interval:    {interval_s}s")
    print(f"  autonomous:  {kwargs.get('autonomous', False)}")
    print(f"  arxiv:       {kwargs.get('arxiv_query') or '(off)'}")
    print("  Ctrl-C to stop")
    n = 0
    try:
        while True:
            n += 1
            print(f"\n--- cycle {n} @ {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
            res = watch_once(repo, **kwargs)
            acts = res.get("actions") or []
            if not acts:
                print("  (no new human activity)")
            else:
                for a in acts:
                    print(f"  {a.get('type')}: {json.dumps({k: a.get(k) for k in a if k != 'body'}, default=str)[:200]}")
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
) -> dict[str, Any]:
    """Search arXiv → write improvement notes → optional nexus do repair job.

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
        "dry_run": dry_run,
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
