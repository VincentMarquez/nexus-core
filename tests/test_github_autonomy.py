
from pathlib import Path

from nexus.github_autonomy import bootstrap_personal_repo, improve_from_arxiv, WatchState, load_state, save_state


def test_bootstrap_writes_workflow(tmp_path):
    res = bootstrap_personal_repo(tmp_path / "app", force=True)
    wf = Path(res["workflow"])
    assert wf.is_file()
    text = wf.read_text(encoding="utf-8")
    assert "Community bot" in text or "community" in text.lower()
    assert (tmp_path / "app" / "NEXUS_COMMUNITY.md").is_file()
    assert res["wrote_workflow"] is True


def test_bootstrap_no_overwrite(tmp_path):
    root = tmp_path / "app2"
    bootstrap_personal_repo(root, force=True)
    res = bootstrap_personal_repo(root, force=False)
    assert res["workflow_action"] == "exists"


def test_watch_state_roundtrip(tmp_path):
    st = WatchState(repo="a/b", seen_comment_ids=["1", "2"], cycles=3)
    p = save_state(st, state_dir=tmp_path)
    assert p.is_file()
    st2 = load_state("a/b", state_dir=tmp_path)
    assert st2.cycles == 3
    assert st2.seen_comment_ids == ["1", "2"]


def test_safe_slug():
    from nexus.github_autonomy import _safe_slug
    assert _safe_slug("a/b") == "a__b"


def test_prove_structure_only(tmp_path):
    from nexus.github_autonomy import prove_connected_repo
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n', encoding="utf-8")
    (tmp_path / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    ev = prove_connected_repo(tmp_path, run_checks=False)
    assert ev["ok"] is True
    assert "python" in ev["languages"]
    assert ev["has_tests"] is True
    assert ev["proved"] == "structure_only"
