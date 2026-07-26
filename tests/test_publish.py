import subprocess
from pathlib import Path

from nexus import publish as pub


def test_allowed_paths():
    assert pub._allowed("src/nexus/alive.py", pub.DEFAULT_ALLOW)
    assert pub._allowed("docs/ALIVE.md", pub.DEFAULT_ALLOW)
    assert not pub._allowed(".nexus_state/usage/ledger.jsonl", pub.DEFAULT_ALLOW)
    assert not pub._allowed(".venv/lib/foo", pub.DEFAULT_ALLOW)
    assert not pub._allowed("secrets.db", pub.DEFAULT_ALLOW)


def test_write_improvements_log(tmp_path):
    log = pub.write_improvements_log(
        tmp_path,
        {"goal": "g", "steps": [{"step": "mine", "fetch": 1, "evaluated": 1, "used": 1}]},
    )
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    assert "Alive improvement log" in text
    assert "mine:" in text


def test_cycle_scoped_publish_fails_closed_without_baseline(tmp_path):
    (tmp_path / ".git").mkdir()
    result = pub.commit_and_maybe_push(
        tmp_path,
        "test",
        baseline_status=None,
        require_cycle_scope=True,
    )
    assert result["ok"] is False
    assert "baseline missing" in result["error"]


def test_cycle_scoped_publish_excludes_preexisting_staged_file(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "-q")
    git("config", "user.email", "nexus-tests@example.invalid")
    git("config", "user.name", "NEXUS tests")

    private = tmp_path / "private.txt"
    private.write_text("pre-existing staged content\n", encoding="utf-8")
    git("add", "private.txt")
    baseline, ok = pub.status_porcelain_checked(tmp_path)
    assert ok is True

    cycle_file = tmp_path / "docs" / "cycle.md"
    cycle_file.parent.mkdir()
    cycle_file.write_text("cycle output\n", encoding="utf-8")

    result = pub.commit_and_maybe_push(
        tmp_path,
        "cycle output",
        baseline_status=baseline,
        require_cycle_scope=True,
    )

    assert result["ok"] is True
    assert result["staged"] == ["docs/cycle.md"]
    committed = git("show", "--name-only", "--format=").stdout.splitlines()
    assert committed == ["docs/cycle.md"]
    assert "?? private.txt" in git("status", "--porcelain").stdout
