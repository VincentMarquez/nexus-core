"""GitHub community one-stop shop: inbox, drafts, and auto-replies.

Works two ways:

1. **Local CLI** (maintainer machine) — `nexus github inbox|reply|draft|auto`
   uses the authenticated `gh` CLI (same token scopes as your laptop).

2. **GitHub Actions** — `.github/workflows/community-bot.yml` posts a first
   reply on new issues / PRs automatically (GITHUB_TOKEN).

Marker ``<!-- nexus-community-bot -->`` prevents double-replies.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

BOT_MARKER = "<!-- nexus-community-bot -->"
DEFAULT_REPO = "VincentMarquez/nexus-core"

DOCS_HOME = "https://vincentmarquez.github.io/nexus-core/"
GETTING_STARTED = f"{DOCS_HOME}getting-started/"
COOKBOOKS = f"{DOCS_HOME}cookbooks/"
COMPARE = f"{DOCS_HOME}COMPARE/"
CONTRIBUTING = "https://github.com/VincentMarquez/nexus-core/blob/main/CONTRIBUTING.md"


@dataclass
class ThreadItem:
    """One issue or pull request that may need a reply."""

    number: int
    title: str
    url: str
    kind: str  # "issue" | "pr"
    author: str
    body: str = ""
    labels: list[str] = field(default_factory=list)
    state: str = "open"
    comments: int = 0
    updated_at: str = ""
    already_bot_replied: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"#{self.number}"


class GhError(RuntimeError):
    pass


def gh_available() -> bool:
    return shutil.which("gh") is not None


def _run_gh(
    args: list[str],
    *,
    timeout: float = 60,
    input_text: Optional[str] = None,
) -> str:
    if not gh_available():
        raise GhError(
            "`gh` CLI not found. Install: https://cli.github.com/\n"
            "Then: gh auth login"
        )
    try:
        p = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )
    except subprocess.TimeoutExpired as e:
        raise GhError(f"gh timed out: {' '.join(args)}") from e
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip()
        raise GhError(f"gh {' '.join(args)} failed: {err}")
    return p.stdout


def resolve_repo(repo: Optional[str] = None) -> str:
    """Prefer explicit repo, else env, else `gh` default, else project default."""
    if repo and repo.strip():
        return repo.strip()
    env = os.environ.get("NEXUS_GITHUB_REPO", "").strip()
    if env:
        return env
    if gh_available():
        try:
            out = _run_gh(
                ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                timeout=20,
            ).strip()
            if out:
                return out
        except GhError:
            pass
    return DEFAULT_REPO


def _has_bot_marker(text: str) -> bool:
    return BOT_MARKER in (text or "")


def _comment_count(value: Any) -> int:
    """gh JSON may return an int or a list of comment objects."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return len(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def list_inbox(
    repo: Optional[str] = None,
    *,
    limit: int = 30,
    include_bot_replied: bool = False,
    deep: bool = False,
) -> list[ThreadItem]:
    """Open issues + PRs, newest activity first. Flags prior bot replies.

    By default only scans the issue/PR body for the bot marker (fast).
    Pass ``deep=True`` to also scan comments (slower; used by auto-reply).
    """
    repo = resolve_repo(repo)
    raw = _run_gh(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,url,author,body,labels,comments,updatedAt,state",
        ]
    )
    issues = json.loads(raw or "[]")

    raw_pr = _run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,url,author,body,labels,comments,updatedAt,state",
        ]
    )
    prs = json.loads(raw_pr or "[]")

    items: list[ThreadItem] = []
    for it in issues:
        author = it.get("author") or {}
        login = author.get("login", "") if isinstance(author, dict) else str(author)
        labels = [
            (lb.get("name") if isinstance(lb, dict) else str(lb))
            for lb in (it.get("labels") or [])
        ]
        body = it.get("body") or ""
        n = int(it["number"])
        bot = _has_bot_marker(body)
        if deep and not bot:
            bot = _thread_has_bot_comment(repo, n)
        items.append(
            ThreadItem(
                number=n,
                title=it.get("title") or "",
                url=it.get("url") or "",
                kind="issue",
                author=login,
                body=body,
                labels=[x for x in labels if x],
                state=it.get("state") or "open",
                comments=_comment_count(it.get("comments")),
                updated_at=it.get("updatedAt") or "",
                already_bot_replied=bot,
                raw=it,
            )
        )

    for it in prs:
        author = it.get("author") or {}
        login = author.get("login", "") if isinstance(author, dict) else str(author)
        labels = [
            (lb.get("name") if isinstance(lb, dict) else str(lb))
            for lb in (it.get("labels") or [])
        ]
        body = it.get("body") or ""
        n = int(it["number"])
        bot = _has_bot_marker(body)
        if deep and not bot:
            bot = _thread_has_bot_comment(repo, n)
        items.append(
            ThreadItem(
                number=n,
                title=it.get("title") or "",
                url=it.get("url") or "",
                kind="pr",
                author=login,
                body=body,
                labels=[x for x in labels if x],
                state=it.get("state") or "open",
                comments=_comment_count(it.get("comments")),
                updated_at=it.get("updatedAt") or "",
                already_bot_replied=bot,
                raw=it,
            )
        )

    items.sort(key=lambda x: x.updated_at, reverse=True)
    if not include_bot_replied:
        items = [x for x in items if not x.already_bot_replied]
    return items


def _thread_has_bot_comment(repo: str, number: int) -> bool:
    """Scan recent comments for the bot marker (best-effort)."""
    try:
        raw = _run_gh(
            [
                "api",
                f"repos/{repo}/issues/{number}/comments",
                "--jq",
                ".[].body",
            ],
            timeout=30,
        )
    except GhError:
        return False
    return BOT_MARKER in (raw or "")


def fetch_thread(repo: Optional[str], number: int) -> ThreadItem:
    repo = resolve_repo(repo)
    # Issues API covers both issues and PRs for metadata/comments
    raw = _run_gh(
        [
            "api",
            f"repos/{repo}/issues/{number}",
            "--jq",
            "{number,title,html_url,user,body,labels,comments,updated_at,state,pull_request}",
        ]
    )
    data = json.loads(raw)
    author = data.get("user") or {}
    login = author.get("login", "") if isinstance(author, dict) else str(author)
    labels = [
        (lb.get("name") if isinstance(lb, dict) else str(lb))
        for lb in (data.get("labels") or [])
    ]
    kind = "pr" if data.get("pull_request") else "issue"
    body = data.get("body") or ""
    bot = _has_bot_marker(body) or _thread_has_bot_comment(repo, number)
    return ThreadItem(
        number=int(data["number"]),
        title=data.get("title") or "",
        url=data.get("html_url") or "",
        kind=kind,
        author=login,
        body=body,
        labels=[x for x in labels if x],
        state=data.get("state") or "open",
        comments=int(data.get("comments") or 0),
        updated_at=data.get("updated_at") or "",
        already_bot_replied=bot,
        raw=data,
    )


def post_comment(
    repo: Optional[str],
    number: int,
    body: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Post a comment on an issue or PR. Appends bot marker if missing."""
    repo = resolve_repo(repo)
    text = body.rstrip()
    if BOT_MARKER not in text:
        text = f"{text}\n\n{BOT_MARKER}\n"
    if dry_run:
        return {"dry_run": True, "repo": repo, "number": number, "body": text}
    # gh issue comment works for PRs too
    out = _run_gh(
        ["issue", "comment", str(number), "--repo", repo, "--body", text],
        timeout=45,
    )
    return {"ok": True, "repo": repo, "number": number, "stdout": out.strip()}


def heuristic_draft(item: ThreadItem, *, repo: Optional[str] = None) -> str:
    """Deterministic first reply — no LLM required."""
    repo = resolve_repo(repo)
    who = f"@{item.author}" if item.author else "there"
    labels = {lb.lower() for lb in item.labels}
    body_l = (item.body or "").lower()
    title_l = (item.title or "").lower()

    if item.kind == "pr":
        return _draft_pr(who, item, labels)

    # Issue flavors
    if "bug" in labels or "bug report" in title_l or "bug" in body_l[:200]:
        return _draft_bug(who, item)
    if "enhancement" in labels or "feature" in labels or "feature" in title_l:
        return _draft_feature(who, item)
    if "good first issue" in labels or "help wanted" in labels:
        return _draft_good_first(who, item)
    return _draft_generic_issue(who, item)


def _footer() -> str:
    return (
        "\n\n---\n"
        f"**Docs:** [{DOCS_HOME}]({DOCS_HOME}) · "
        f"[Getting started]({GETTING_STARTED}) · "
        f"[Cookbooks]({COOKBOOKS}) · "
        f"[Compare]({COMPARE})\n"
        f"**Contribute:** [{CONTRIBUTING}]({CONTRIBUTING})\n"
        "\n"
        "_Auto-reply from the NEXUS community bot. "
        "Maintainers can follow up from the same inbox: "
        "`nexus github inbox` · `nexus github reply <n>`._"
    )


def _draft_pr(who: str, item: ThreadItem, labels: set[str]) -> str:
    return (
        f"Thanks for the PR, {who} — appreciated.\n\n"
        f"**{item.title}**\n\n"
        "Quick checklist before review:\n"
        "- [ ] `make test` and `make smoke` pass locally\n"
        "- [ ] One concern per PR when practical\n"
        "- [ ] Docs updated if CLI / public API changed\n"
        "- [ ] No secrets or machine-specific paths\n\n"
        "Design laws we protect: **presence ≠ success**, "
        "**resume over hope**, **autonomy opt-in**.\n"
        f"{_footer()}"
    )


def _draft_bug(who: str, item: ThreadItem) -> str:
    return (
        f"Thanks for the report, {who}.\n\n"
        f"**{item.title}**\n\n"
        "To dig in quickly it helps to have:\n"
        "1. OS / Python version (`python --version`)\n"
        "2. Exact command you ran (`./run`, `nexus do …`, …)\n"
        "3. Full error / traceback (or link)\n"
        "4. Whether `make demo` works on a clean clone\n\n"
        f"Useful docs: [Getting started]({GETTING_STARTED}) · "
        f"[GitHub jobs cookbook]({DOCS_HOME}cookbook/06_github_do/)\n"
        f"{_footer()}"
    )


def _draft_feature(who: str, item: ThreadItem) -> str:
    return (
        f"Thanks for the idea, {who}.\n\n"
        f"**{item.title}**\n\n"
        "We prioritize features that strengthen:\n"
        "- durable multi-agent runs (crash → resume)\n"
        "- rubric judging (evidence, not vibes)\n"
        "- practical jobs (`nexus do` / research / procure)\n\n"
        "A short “problem → proposed API → how we’d test it” note speeds review.\n"
        f"{_footer()}"
    )


def _draft_good_first(who: str, item: ThreadItem) -> str:
    return (
        f"Thanks for picking this up, {who}!\n\n"
        f"**{item.title}**\n\n"
        "This is labeled for newer contributors. Suggested path:\n"
        "1. Read [CONTRIBUTING](" + CONTRIBUTING + ")\n"
        "2. `make install && make test`\n"
        "3. Open a draft PR early if you want feedback\n"
        f"{_footer()}"
    )


def _draft_generic_issue(who: str, item: ThreadItem) -> str:
    return (
        f"Thanks for opening this, {who}.\n\n"
        f"**{item.title}**\n\n"
        "A maintainer (or the community bot follow-up) will triage shortly. "
        "Meanwhile:\n"
        f"- [Getting started]({GETTING_STARTED})\n"
        f"- [Cookbooks]({COOKBOOKS})\n"
        f"- [Discussions](https://github.com/{DEFAULT_REPO}/discussions) for open-ended Qs\n"
        f"{_footer()}"
    )


def llm_draft(
    item: ThreadItem,
    *,
    repo: Optional[str] = None,
    panel: Any = None,
) -> Optional[str]:
    """Optional LLM draft via NEXUS bus panel when available.

    Returns None if no panel / call fails — caller should fall back to heuristic.
    """
    if panel is None:
        return None
    repo = resolve_repo(repo)
    prompt = (
        "You are the NEXUS Core maintainer assistant. Draft a short, friendly GitHub "
        f"{'PR' if item.kind == 'pr' else 'issue'} first reply (markdown).\n"
        "Rules: be helpful, link docs when relevant, never invent features, "
        "never claim you merged or fixed code, keep under 180 words, no secrets.\n"
        f"Repo: {repo}\n"
        f"#{item.number} ({item.kind}) by @{item.author}\n"
        f"Title: {item.title}\n"
        f"Labels: {', '.join(item.labels) or '(none)'}\n"
        f"Body:\n{(item.body or '')[:2500]}\n"
    )
    try:
        # Panel APIs vary; support common call shapes
        if hasattr(panel, "ask"):
            text = panel.ask(prompt)
        elif hasattr(panel, "complete"):
            text = panel.complete(prompt)
        elif callable(panel):
            text = panel(prompt)
        else:
            return None
        if not text or not str(text).strip():
            return None
        out = str(text).strip()
        # strip accidental code fences around the whole message
        out = re.sub(r"^```(?:markdown|md)?\n", "", out)
        out = re.sub(r"\n```$", "", out)
        return out + _footer()
    except Exception:
        return None


def draft_reply(
    item: ThreadItem,
    *,
    repo: Optional[str] = None,
    panel: Any = None,
    prefer_llm: bool = False,
) -> str:
    if prefer_llm:
        text = llm_draft(item, repo=repo, panel=panel)
        if text:
            return text
    return heuristic_draft(item, repo=repo)


def auto_reply_open(
    repo: Optional[str] = None,
    *,
    limit: int = 20,
    dry_run: bool = False,
    prefer_llm: bool = False,
    panel: Any = None,
) -> list[dict[str, Any]]:
    """Post first replies on open threads that have no bot marker yet."""
    repo = resolve_repo(repo)
    results: list[dict[str, Any]] = []
    for item in list_inbox(repo, limit=limit, include_bot_replied=False, deep=True):
        if _thread_has_bot_comment(repo, item.number):
            continue
        body = draft_reply(item, repo=repo, panel=panel, prefer_llm=prefer_llm)
        res = post_comment(repo, item.number, body, dry_run=dry_run)
        res["kind"] = item.kind
        res["title"] = item.title
        results.append(res)
    return results


def format_inbox_table(items: list[ThreadItem]) -> str:
    if not items:
        return "(inbox empty — nothing open needs a first bot reply)"
    lines = [
        f"{'KIND':<6} {'#':<6} {'BOT':<4} {'AUTH':<16} {'CMTS':<5} TITLE",
        "-" * 72,
    ]
    for it in items:
        bot = "yes" if it.already_bot_replied else "no"
        lines.append(
            f"{it.kind:<6} {it.number:<6} {bot:<4} {(it.author or '?')[:16]:<16} "
            f"{it.comments:<5} {it.title[:48]}"
        )
    return "\n".join(lines)


def draft_from_github_event(event: dict[str, Any]) -> tuple[int, str, str]:
    """Build (number, kind, body) from a GitHub Actions event payload."""
    name = (os.environ.get("GITHUB_EVENT_NAME") or "").strip()
    action = event.get("action") or ""

    if "pull_request" in event and event.get("pull_request"):
        pr = event["pull_request"]
        item = ThreadItem(
            number=int(pr["number"]),
            title=pr.get("title") or "",
            url=pr.get("html_url") or "",
            kind="pr",
            author=(pr.get("user") or {}).get("login", ""),
            body=pr.get("body") or "",
            labels=[
                (lb.get("name") if isinstance(lb, dict) else str(lb))
                for lb in (pr.get("labels") or [])
            ],
        )
        return item.number, "pr", heuristic_draft(item)

    if "issue" in event and event.get("issue"):
        issue = event["issue"]
        # ignore PR-linked issue objects on pull_request events handled above
        if issue.get("pull_request") and name.startswith("pull_request"):
            pass
        item = ThreadItem(
            number=int(issue["number"]),
            title=issue.get("title") or "",
            url=issue.get("html_url") or "",
            kind="pr" if issue.get("pull_request") else "issue",
            author=(issue.get("user") or {}).get("login", ""),
            body=issue.get("body") or "",
            labels=[
                (lb.get("name") if isinstance(lb, dict) else str(lb))
                for lb in (issue.get("labels") or [])
            ],
        )
        # Skip if comment event and not an @-mention / slash command
        if name == "issue_comment":
            comment = event.get("comment") or {}
            cbody = (comment.get("body") or "").lower()
            if not any(
                t in cbody
                for t in ("@nexus", "/nexus", "nexus-bot", "nexus bot", "/triage")
            ):
                raise ValueError("comment does not request bot; skip")
            if _has_bot_marker(comment.get("body") or ""):
                raise ValueError("already a bot comment; skip")
        if action in {"opened", "reopened"} or name == "issue_comment":
            return item.number, item.kind, heuristic_draft(item)

    raise ValueError(f"unsupported event action={action!r} name={name!r}")


def handle_event_file(
    event_path: Path,
    *,
    repo: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Entry used by GitHub Actions."""
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    number, kind, body = draft_from_github_event(event)
    repo = resolve_repo(repo or os.environ.get("GITHUB_REPOSITORY"))
    # Avoid double-post if we already replied
    if _thread_has_bot_comment(repo, number):
        return {"skipped": True, "reason": "already_replied", "number": number}
    return post_comment(repo, number, body, dry_run=dry_run) | {
        "kind": kind,
        "number": number,
    }


def main_argv(argv: Optional[list[str]] = None) -> int:
    """Minimal CLI for Actions: python -m nexus.github_community --event $PATH"""
    import argparse

    ap = argparse.ArgumentParser(prog="nexus.github_community")
    ap.add_argument("--event", type=Path, help="GitHub event JSON path")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not args.event:
        ap.error("--event is required for module entry")
    try:
        res = handle_event_file(args.event, repo=args.repo, dry_run=args.dry_run)
    except ValueError as e:
        print(f"skip: {e}")
        return 0
    except GhError as e:
        print(f"error: {e}")
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_argv())
