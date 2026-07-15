from pathlib import Path

import pytest

from nexus.github_job import (
    parse_github_ref,
    detect_project,
    _cmd_allowed,
    GithubJobRunner,
)


def test_parse_url_and_slug():
    r = parse_github_ref("https://github.com/psf/requests")
    assert r.owner == "psf" and r.repo == "requests"
    r2 = parse_github_ref("psf/requests")
    assert r2.clone_url.endswith("requests.git")
    r3 = parse_github_ref("git@github.com:psf/requests.git")
    assert r3.slug == "psf/requests"


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_github_ref("not a repo")


def test_cmd_allowlist():
    assert _cmd_allowed(["python3", "-m", "pytest", "-q"])
    assert _cmd_allowed(["npm", "install"])
    assert not _cmd_allowed(["rm", "-rf", "/tmp/x"])
    assert not _cmd_allowed(["curl", "http://evil"])


def test_detect_nexus_self():
    p = detect_project(Path(__file__).resolve().parents[1])
    assert "python" in p.languages
    assert p.install_cmds
    assert p.check_cmds


def test_runner_create_and_detect(tmp_path, monkeypatch):
    # Use a local path as "clone" by faking work_dir with a mini project
    mini = tmp_path / "owner__toy"
    mini.mkdir()
    (mini / "pyproject.toml").write_text(
        '[project]\nname="toy"\nversion="0.0.1"\n', encoding="utf-8"
    )
    (mini / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (mini / "test_toy.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    (mini / "README.md").write_text("# Toy\n\nRun tests.\n", encoding="utf-8")

    runner = GithubJobRunner(
        workspace_root=tmp_path,
        state_dir=tmp_path / "jobs",
        panel=None,
    )
    job = runner.create("owner/toy", goal="make tests pass")
    # point at mini without git clone
    job.work_dir = str(mini)
    runner.save(job)

    # skip clone by marking as existing non-git dir with files
    assert runner.phase_clone(job) is True
    prof = runner.phase_detect(job)
    assert "python" in prof.languages
    assert any("pip" in c for c in prof.install_cmds) or any(
        "requirements" in " ".join(c) for c in prof.install_cmds
    )
