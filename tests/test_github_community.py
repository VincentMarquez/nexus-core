import json
from pathlib import Path

import pytest

from nexus.github_community import (
    BOT_MARKER,
    ThreadItem,
    draft_from_github_event,
    format_inbox_table,
    heuristic_draft,
    post_comment,
    _has_bot_marker,
)


def test_bot_marker():
    assert _has_bot_marker(f"hi\n{BOT_MARKER}\n")
    assert not _has_bot_marker("normal comment")


def test_heuristic_issue_bug():
    item = ThreadItem(
        number=1,
        title="Bug: demo fails",
        url="https://github.com/x/y/issues/1",
        kind="issue",
        author="alice",
        body="it crashed",
        labels=["bug"],
    )
    text = heuristic_draft(item)
    assert "alice" in text
    assert "traceback" in text.lower() or "error" in text.lower()
    assert BOT_MARKER not in text  # marker added at post time


def test_heuristic_pr():
    item = ThreadItem(
        number=2,
        title="Add feature X",
        url="https://github.com/x/y/pull/2",
        kind="pr",
        author="bob",
        body="please review",
    )
    text = heuristic_draft(item)
    assert "bob" in text
    assert "make test" in text
    assert "presence" in text.lower() or "resume" in text.lower()


def test_format_inbox_empty():
    assert "empty" in format_inbox_table([]).lower()


def test_format_inbox_rows():
    items = [
        ThreadItem(
            number=3,
            title="Hello world issue title here",
            url="u",
            kind="issue",
            author="carol",
            comments=2,
        )
    ]
    table = format_inbox_table(items)
    assert "#3" in table.replace(" ", "") or "3" in table
    assert "carol" in table
    assert "issue" in table


def test_draft_from_issue_opened_event(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issues")
    event = {
        "action": "opened",
        "issue": {
            "number": 9,
            "title": "Feature request: dark mode",
            "html_url": "https://example.com/9",
            "user": {"login": "dana"},
            "body": "please add dark mode",
            "labels": [{"name": "enhancement"}],
        },
    }
    number, kind, body = draft_from_github_event(event)
    assert number == 9
    assert kind == "issue"
    assert "dana" in body
    assert "idea" in body.lower() or "feature" in body.lower() or "Thanks" in body


def test_draft_from_pr_event(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    event = {
        "action": "opened",
        "pull_request": {
            "number": 4,
            "title": "Fix typos",
            "html_url": "https://example.com/4",
            "user": {"login": "erin"},
            "body": "typo fixes",
            "labels": [],
        },
    }
    number, kind, body = draft_from_github_event(event)
    assert number == 4 and kind == "pr"
    assert "erin" in body
    assert "checklist" in body.lower() or "make test" in body


def test_issue_comment_skips_without_mention(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    event = {
        "action": "created",
        "issue": {
            "number": 5,
            "title": "Q",
            "html_url": "u",
            "user": {"login": "f"},
            "body": "b",
            "labels": [],
        },
        "comment": {"body": "just chatting"},
    }
    with pytest.raises(ValueError, match="does not request"):
        draft_from_github_event(event)


def test_issue_comment_with_mention(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    event = {
        "action": "created",
        "issue": {
            "number": 5,
            "title": "Q",
            "html_url": "u",
            "user": {"login": "f"},
            "body": "b",
            "labels": [],
        },
        "comment": {"body": "hey /nexus please triage"},
    }
    number, kind, body = draft_from_github_event(event)
    assert number == 5
    assert "Thanks" in body or "thanks" in body.lower()


def test_post_comment_dry_run(monkeypatch):
    # no gh needed
    res = post_comment("owner/repo", 1, "Hello from test", dry_run=True)
    assert res["dry_run"] is True
    assert BOT_MARKER in res["body"]
    assert res["number"] == 1


def test_handle_event_file_dry(tmp_path, monkeypatch):
    from nexus.github_community import handle_event_file

    monkeypatch.setenv("GITHUB_EVENT_NAME", "issues")
    monkeypatch.setenv("GITHUB_REPOSITORY", "VincentMarquez/nexus-core")
    event = {
        "action": "opened",
        "issue": {
            "number": 99,
            "title": "Hello",
            "html_url": "u",
            "user": {"login": "g"},
            "body": "body",
            "labels": [],
        },
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")

    # force skip comment scan / use dry_run so no network
    monkeypatch.setattr(
        "nexus.github_community._thread_has_bot_comment",
        lambda repo, n: False,
    )
    res = handle_event_file(path, repo="VincentMarquez/nexus-core", dry_run=True)
    assert res.get("dry_run") is True
    assert res.get("number") == 99
