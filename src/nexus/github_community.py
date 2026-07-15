"""GitHub community one-stop shop: inbox, drafts, auto-replies, and test loop.

Works two ways:

1. **Local CLI** (maintainer machine) — `nexus github inbox|reply|draft|auto|loop`
   uses the authenticated `gh` CLI (same token scopes as your laptop).

2. **GitHub Actions** — `.github/workflows/community-bot.yml`
   - first reply on new issues / PRs
   - **response loop**: human reply or new PR commits → run tests → post results → wait for next reply

Markers:

- ``<!-- nexus-community-bot -->`` first / triage replies
- ``<!-- nexus-community-loop sha=… -->`` test-result posts (dedupe per commit)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

BOT_MARKER = "<!-- nexus-community-bot -->"
LOOP_MARKER = "<!-- nexus-community-loop -->"
LOOP_SHA_RE = re.compile(r"<!--\s*nexus-community-loop\s+sha=([0-9a-fA-F]+)\s*-->")
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


# --- response loop: pick up reply → run tests → share results --------------------


@dataclass
class CheckResult:
    name: str
    cmd: list[str]
    ok: bool
    returncode: int
    duration_s: float
    stdout: str = ""
    stderr: str = ""


@dataclass
class LoopReport:
    """Aggregate of community-loop checks (not a pytest test case)."""

    sha: str
    workdir: str
    checks: list[CheckResult] = field(default_factory=list)
    triggered_by: str = ""
    kind: str = "issue"
    number: int = 0

    @property
    def ok(self) -> bool:
        """Overall green if required suite checks pass (install is informational)."""
        required = [c for c in self.checks if c.name != "install"]
        if not required:
            return bool(self.checks) and all(c.ok for c in self.checks)
        return all(c.ok for c in required)


def git_head_sha(workdir: Path) -> str:
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _tail(text: str, n: int = 2500) -> str:
    text = text or ""
    if len(text) <= n:
        return text
    return "…\n" + text[-n:]


def run_project_checks(
    workdir: Path,
    *,
    timeout_each: float = 300,
) -> list[CheckResult]:
    """Install-light test suite for the community loop.

    Prefer repo-local pytest + smoke evals; never runs arbitrary shell from issues.
    """
    workdir = Path(workdir).resolve()
    results: list[CheckResult] = []
    py = sys.executable or "python3"

    # Ensure package importable in this tree when possible (best-effort).
    # Use the *current* interpreter so local venvs work (PEP 668 safe).
    has_project = (workdir / "pyproject.toml").is_file() or (workdir / "setup.py").is_file()
    install_cmd = [py, "-m", "pip", "install", "-e", ".[dev]", "-q"] if has_project else []

    if install_cmd:
        t0 = time.time()
        try:
            p = subprocess.run(
                install_cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout_each,
            )
            # Soft-fail install if the suite is still runnable (e.g. already installed)
            ok_install = p.returncode == 0
            results.append(
                CheckResult(
                    name="install",
                    cmd=install_cmd,
                    ok=ok_install,
                    returncode=p.returncode,
                    duration_s=time.time() - t0,
                    stdout=_tail(p.stdout or "", 1200),
                    stderr=_tail(p.stderr or "", 1200),
                )
            )
            if not ok_install:
                # Continue to pytest — package may already be on PYTHONPATH
                pass
        except subprocess.TimeoutExpired:
            results.append(
                CheckResult(
                    name="install",
                    cmd=install_cmd,
                    ok=False,
                    returncode=-1,
                    duration_s=timeout_each,
                    stderr=f"timeout after {timeout_each}s",
                )
            )
            # still try tests

    candidates: list[tuple[str, list[str]]] = [
        ("pytest", [py, "-m", "pytest", "-q", "--tb=line"]),
    ]
    smoke = workdir / "evals" / "smoke.py"
    if smoke.is_file():
        candidates.append(("smoke", [py, "evals/smoke.py"]))

    for name, cmd in candidates:
        t0 = time.time()
        try:
            p = subprocess.run(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout_each,
            )
            results.append(
                CheckResult(
                    name=name,
                    cmd=cmd,
                    ok=p.returncode == 0,
                    returncode=p.returncode,
                    duration_s=time.time() - t0,
                    stdout=_tail(p.stdout or ""),
                    stderr=_tail(p.stderr or ""),
                )
            )
        except subprocess.TimeoutExpired:
            results.append(
                CheckResult(
                    name=name,
                    cmd=cmd,
                    ok=False,
                    returncode=-1,
                    duration_s=timeout_each,
                    stderr=f"timeout after {timeout_each}s",
                )
            )
        except FileNotFoundError as e:
            results.append(
                CheckResult(
                    name=name,
                    cmd=cmd,
                    ok=False,
                    returncode=127,
                    duration_s=time.time() - t0,
                    stderr=str(e),
                )
            )
    return results


def format_loop_report(report: LoopReport) -> str:
    status = "✅ **PASS**" if report.ok else "❌ **FAIL**"
    who = f"@{report.triggered_by}" if report.triggered_by else "someone"
    lines = [
        f"### Community loop — test results {status}",
        "",
        f"Picked up a response from {who} on **#{report.number}** ({report.kind}).",
        f"Ran checks on `{report.sha[:12] if report.sha != 'unknown' else 'unknown'}` "
        f"(`{report.workdir}`).",
        "",
        "| Check | Result | Time |",
        "|-------|--------|------|",
    ]
    for c in report.checks:
        icon = "✅" if c.ok else "❌"
        lines.append(
            f"| `{c.name}` | {icon} exit {c.returncode} | {c.duration_s:.1f}s |"
        )
    lines.append("")
    for c in report.checks:
        if c.ok and c.name == "install":
            continue
        block = (c.stdout or c.stderr or "").strip()
        if not block and c.ok:
            continue
        lines.append(f"<details><summary><code>{c.name}</code> output</summary>")
        lines.append("")
        lines.append("```text")
        lines.append(block or "(no output)")
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.append("---")
    lines.append(
        "**Loop:** reply again (or push commits on a PR) and this will run again → "
        "tests → share results. "
        "Commands: `nexus github loop <n>` · `nexus github inbox`"
    )
    lines.append("")
    lines.append(f"{LOOP_MARKER}")
    lines.append(f"<!-- nexus-community-loop sha={report.sha} -->")
    return "\n".join(lines)


def _comment_bodies(repo: str, number: int) -> list[str]:
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
        return []
    # gh --jq may print one body per line; multi-line bodies are awkward.
    # Prefer JSON array when possible.
    try:
        raw_json = _run_gh(
            ["api", f"repos/{repo}/issues/{number}/comments"],
            timeout=30,
        )
        data = json.loads(raw_json or "[]")
        return [str(c.get("body") or "") for c in data]
    except Exception:
        return [raw] if raw else []


def last_loop_sha(repo: str, number: int) -> Optional[str]:
    for body in reversed(_comment_bodies(repo, number)):
        m = LOOP_SHA_RE.search(body or "")
        if m:
            return m.group(1)
        if LOOP_MARKER in (body or ""):
            return "unknown"
    return None


def is_bot_comment_body(body: str) -> bool:
    b = body or ""
    return BOT_MARKER in b or LOOP_MARKER in b or "nexus-community-loop sha=" in b


def comment_requests_skip(body: str) -> bool:
    """Human can opt out of the auto loop for one comment."""
    low = (body or "").lower()
    return any(
        t in low
        for t in ("/skip-loop", "/noloop", "[skip loop]", "<!-- skip-loop -->")
    )


def event_wants_first_reply(event: dict[str, Any], event_name: str) -> bool:
    action = event.get("action") or ""
    if event_name == "issues" and action in {"opened", "reopened"}:
        return True
    if event_name == "pull_request" and action in {"opened", "reopened"}:
        return True
    if event_name == "issue_comment" and action == "created":
        comment = event.get("comment") or {}
        cbody = (comment.get("body") or "").lower()
        if is_bot_comment_body(comment.get("body") or ""):
            return False
        return any(
            t in cbody
            for t in ("@nexus", "/nexus", "nexus-bot", "nexus bot", "/triage")
        )
    return False


def event_wants_loop(event: dict[str, Any], event_name: str) -> bool:
    """Human response or new PR commits → run tests."""
    action = event.get("action") or ""
    if event_name == "issue_comment" and action == "created":
        comment = event.get("comment") or {}
        body = comment.get("body") or ""
        if is_bot_comment_body(body):
            return False
        if comment_requests_skip(body):
            return False
        # Any human comment on the thread restarts the loop
        return True
    if event_name == "pull_request" and action in {
        "opened",
        "reopened",
        "synchronize",
        "ready_for_review",
    }:
        return True
    if event_name == "issues" and action in {"opened", "reopened"}:
        # Baseline checks on the default branch when a thread starts
        return True
    return False


def number_from_event(event: dict[str, Any]) -> tuple[int, str, str]:
    """Return (number, kind, triggered_by_login)."""
    if event.get("pull_request"):
        pr = event["pull_request"]
        login = (pr.get("user") or {}).get("login", "")
        if event.get("comment"):
            login = (event["comment"].get("user") or {}).get("login", login)
        return int(pr["number"]), "pr", login
    if event.get("issue"):
        issue = event["issue"]
        kind = "pr" if issue.get("pull_request") else "issue"
        login = (issue.get("user") or {}).get("login", "")
        if event.get("comment"):
            login = (event["comment"].get("user") or {}).get("login", login)
        return int(issue["number"]), kind, login
    raise ValueError("event has no issue/pull_request")


def run_and_post_loop(
    repo: Optional[str],
    number: int,
    *,
    workdir: Optional[Path] = None,
    kind: str = "issue",
    triggered_by: str = "",
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Run project checks and post a loop results comment."""
    repo = resolve_repo(repo)
    root = Path(workdir or os.environ.get("GITHUB_WORKSPACE") or Path.cwd()).resolve()
    sha = git_head_sha(root)
    if not force:
        prev = last_loop_sha(repo, number)
        if prev and prev == sha and sha != "unknown":
            return {
                "skipped": True,
                "reason": "same_sha_already_posted",
                "number": number,
                "sha": sha,
            }

    checks = run_project_checks(root)
    report = LoopReport(
        sha=sha,
        workdir=str(root),
        checks=checks,
        triggered_by=triggered_by,
        kind=kind,
        number=number,
    )
    body = format_loop_report(report)
    res = post_comment(repo, number, body, dry_run=dry_run)
    res.update(
        {
            "loop": True,
            "ok_checks": report.ok,
            "sha": sha,
            "number": number,
            "kind": kind,
            "checks": [
                {"name": c.name, "ok": c.ok, "returncode": c.returncode}
                for c in checks
            ],
        }
    )
    return res


def handle_loop_event_file(
    event_path: Path,
    *,
    repo: Optional[str] = None,
    workdir: Optional[Path] = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    event_name = (os.environ.get("GITHUB_EVENT_NAME") or "").strip()
    if not event_wants_loop(event, event_name):
        return {"skipped": True, "reason": "event_not_for_loop", "event": event_name}
    number, kind, who = number_from_event(event)
    repo = resolve_repo(repo or os.environ.get("GITHUB_REPOSITORY"))
    return run_and_post_loop(
        repo,
        number,
        workdir=workdir,
        kind=kind,
        triggered_by=who,
        dry_run=dry_run,
        force=force,
    )


def handle_event_file(
    event_path: Path,
    *,
    repo: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """First-reply entry used by GitHub Actions."""
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    event_name = (os.environ.get("GITHUB_EVENT_NAME") or "").strip()
    if not event_wants_first_reply(event, event_name):
        return {"skipped": True, "reason": "event_not_for_first_reply", "event": event_name}
    number, kind, body = draft_from_github_event(event)
    repo = resolve_repo(repo or os.environ.get("GITHUB_REPOSITORY"))
    # Avoid double-post if we already replied
    if _thread_has_bot_comment(repo, number):
        return {"skipped": True, "reason": "already_replied", "number": number}
    return post_comment(repo, number, body, dry_run=dry_run) | {
        "kind": kind,
        "number": number,
        "first_reply": True,
    }


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
        "When you reply, the **loop** runs tests and posts results. "
        "Inbox: `nexus github inbox` · `nexus github loop <n>` · `nexus github reply <n>`._"
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


# Security / safety tokens — block auto-replies that would exfiltrate or self-harm ops
_SECURITY_DENY_PATTERNS = (
    "curl http",
    "curl https",
    "wget ",
    "rm -rf /",
    "DROP TABLE",
    "api_key=",
    "API_KEY=",
    "BEGIN RSA PRIVATE",
    "xai-",
    "sk-ant-",
    "ghp_",
    "password:",
    "sudo rm",
    "mkfs.",
    "base64 -d | bash",
    "| bash",
    "| sh",
)


def security_gate(
    text: str,
    *,
    extra_deny: Optional[list[str]] = None,
) -> tuple[bool, str]:
    """Return (ok, reason). Fail closed on dangerous reply content.

    Used before posting community drafts (agent security / workflow papers).
    """
    body = text or ""
    low = body.lower()
    for p in _SECURITY_DENY_PATTERNS:
        if p.lower() in low:
            return False, f"blocked pattern: {p!r}"
    for p in extra_deny or []:
        if p and p.lower() in low:
            return False, f"blocked extra deny: {p!r}"
    # huge dump risk
    if len(body) > 12_000:
        return False, "reply too long (>12000 chars)"
    return True, "ok"


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
            ok, reason = security_gate(text)
            if ok:
                return text
            # fall through to heuristic if LLM draft is unsafe
            _ = reason
    text = heuristic_draft(item, repo=repo)
    ok, reason = security_gate(text)
    if not ok:
        # last resort: minimal safe reply
        return (
            f"Thanks for opening this — a maintainer will review.\n\n"
            f"(auto-draft suppressed: {reason})\n\n{BOT_MARKER}\n"
        )
    return text


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
        ok, reason = security_gate(body)
        if not ok:
            results.append({
                "number": item.number,
                "kind": item.kind,
                "title": item.title,
                "skipped": True,
                "reason": reason,
            })
            continue
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


def main_argv(argv: Optional[list[str]] = None) -> int:
    """Actions entry: python -m nexus.github_community --event PATH [--loop]"""
    import argparse

    ap = argparse.ArgumentParser(prog="nexus.github_community")
    ap.add_argument("--event", type=Path, help="GitHub event JSON path")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--workdir", type=Path, default=None)
    ap.add_argument(
        "--loop",
        action="store_true",
        help="response loop: run tests and post results",
    )
    ap.add_argument("--force", action="store_true", help="post even if same sha")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--number",
        type=int,
        default=None,
        help="with --loop, run against this issue/PR without an event file",
    )
    args = ap.parse_args(argv)

    try:
        if args.loop and args.number is not None:
            res = run_and_post_loop(
                args.repo,
                int(args.number),
                workdir=args.workdir,
                dry_run=args.dry_run,
                force=args.force,
            )
        elif args.loop and args.event:
            res = handle_loop_event_file(
                args.event,
                repo=args.repo,
                workdir=args.workdir,
                dry_run=args.dry_run,
                force=args.force,
            )
        elif args.event:
            res = handle_event_file(args.event, repo=args.repo, dry_run=args.dry_run)
        else:
            ap.error("--event is required (or --loop --number N)")
            return 2
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
