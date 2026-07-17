"""Hermetic tests for post-implement critique panel (no live bus/Grok)."""

from __future__ import annotations

from pathlib import Path

from nexus import critique_panel as cp


def test_list_slice_files_detects_new_and_modified():
    before = ""
    after = " M src/nexus/foo.py\n?? tests/test_foo.py\n"
    files = cp.list_slice_files(Path("."), before_status=before, after_status=after)
    assert "src/nexus/foo.py" in files
    assert "tests/test_foo.py" in files


def test_list_slice_files_ignores_preexisting_dirty():
    """Strict delta: paths dirty both before and after are not the slice."""
    before = (
        " M src/nexus/old_wip.py\n"
        " M docs/ALIVE_IMPROVEMENTS.md\n"
        "?? Makefile\n"
    )
    after = (
        " M src/nexus/old_wip.py\n"
        " M docs/ALIVE_IMPROVEMENTS.md\n"
        "?? Makefile\n"
        "?? src/nexus/new_idea.py\n"
        " M tests/test_new_idea.py\n"
    )
    files = cp.list_slice_files(Path("."), before_status=before, after_status=after)
    assert "src/nexus/new_idea.py" in files
    assert "tests/test_new_idea.py" in files
    assert "src/nexus/old_wip.py" not in files
    assert "docs/ALIVE_IMPROVEMENTS.md" not in files
    assert "Makefile" not in files


def test_expand_snapshot_scope_does_not_pull_whole_tree(tmp_path: Path):
    """Without baseline, scope is slice only; with baseline, synthesis delta only."""
    root = tmp_path
    # No git needed for expand when baseline is synthetic via monkeypatch
    slice_files = ["src/nexus/mod.py"]
    scope = cp.expand_snapshot_scope(root, slice_files)
    assert scope == ["src/nexus/mod.py"]

    # Simulate post-Grok baseline + synthesis adding one file
    baseline = "?? src/nexus/mod.py\n"
    # invent a fake porcelain for "now" by writing a file and patching git status
    # expand uses git_status_porcelain — stub it
    original = cp.git_status_porcelain
    try:
        cp.git_status_porcelain = lambda r: (  # type: ignore[assignment]
            "?? src/nexus/mod.py\n"
            "?? src/nexus/syn_only.py\n"
            " M docs/UNRELATED_WIP.md\n"
        )
        scope2 = cp.expand_snapshot_scope(
            root, slice_files, baseline_status=baseline
        )
    finally:
        cp.git_status_porcelain = original  # type: ignore[assignment]
    assert "src/nexus/mod.py" in scope2
    assert "src/nexus/syn_only.py" in scope2
    # pre-existing dirty not in baseline must not appear (UNRELATED was never in baseline
    # and is in "now" — it is a synthesis-delta path under strict delta!)
    # Actually: after-before = {syn_only, UNRELATED} - UNRELATED is newly dirty vs baseline
    # so it IS synthesis delta. That's correct if it truly became dirty after baseline.
    # Pre-existing WIP would be in baseline too — test that:
    baseline_with_wip = "?? src/nexus/mod.py\n M docs/UNRELATED_WIP.md\n"
    try:
        cp.git_status_porcelain = lambda r: (  # type: ignore[assignment]
            "?? src/nexus/mod.py\n"
            "?? src/nexus/syn_only.py\n"
            " M docs/UNRELATED_WIP.md\n"
        )
        scope3 = cp.expand_snapshot_scope(
            root, slice_files, baseline_status=baseline_with_wip
        )
    finally:
        cp.git_status_porcelain = original  # type: ignore[assignment]
    assert "src/nexus/syn_only.py" in scope3
    assert "docs/UNRELATED_WIP.md" not in scope3


def test_snapshot_restore_roundtrip(tmp_path: Path):
    root = tmp_path
    (root / "src").mkdir()
    f = root / "src" / "a.py"
    f.write_text("v1\n", encoding="utf-8")
    snap = cp.snapshot_paths(root, ["src/a.py", "src/b.py"])
    assert snap["src/a.py"] == "v1\n"
    assert snap["src/b.py"] is None
    f.write_text("v2\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("new\n", encoding="utf-8")
    restored = cp.restore_snapshot(root, snap)
    assert f.read_text(encoding="utf-8") == "v1\n"
    assert not (root / "src" / "b.py").exists()
    assert "src/a.py" in restored


def test_write_review_pack_layout(tmp_path: Path):
    root = tmp_path
    idea = {
        "id": "arxiv:2606.26649v1",
        "source": "arxiv",
        "title": "Policy as Code",
        "concrete": "Cedar gate",
        "url": "https://arxiv.org/abs/2606.26649",
    }
    pack = cp.write_review_pack(
        root,
        idea,
        cycle_id="cyc1",
        slice_files=["src/nexus/cedar_policy.py"],
        diff_text="diff --git a/src/nexus/cedar_policy.py",
        grok_result={"ok": True, "model": "grok-4.5"},
    )
    assert (pack / "MANIFEST.md").is_file()
    assert (pack / "DIFF.patch").is_file()
    assert (pack / "CONTEXT.md").is_file()
    assert (pack / "critiques").is_dir()
    assert (pack / "synthesis").is_dir()


def test_panel_and_synthesis_ok_with_mocks(tmp_path: Path):
    root = tmp_path
    (root / "src" / "nexus").mkdir(parents=True)
    (root / "tests").mkdir()
    target = root / "src" / "nexus" / "mod.py"
    target.write_text("x = 1\n", encoding="utf-8")
    (root / "tests" / "test_mod.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )

    def message_fn(agent: str, prompt: str) -> str:
        return (
            f"# Critique from {agent}\n\n## Summary\nok\n\n"
            f"### F1 — niggle\n- severity: nit\n- file: src/nexus/mod.py\n"
            f"- problem: name\n- suggestion: If you rename x it would be clearer\n"
        )

    def grok_fn(root_arg, goal: str):
        # synthesis "accepts" by appending a comment
        p = Path(root_arg) / "src" / "nexus" / "mod.py"
        p.write_text(p.read_text(encoding="utf-8") + "# improved\n", encoding="utf-8")
        return {"ok": True, "text": "applied", "model": "mock"}

    def pytest_fn(root_arg, files):
        return {"ok": True, "mode": "mock", "output": "passed"}

    idea = {"id": "demo:1", "source": "arxiv", "title": "T", "concrete": "c"}
    before = ""
    after = "?? src/nexus/mod.py\n?? tests/test_mod.py\n"
    out = cp.run_slice_critique_panel(
        root,
        idea,
        before_status=before,
        after_status=after,
        grok_result={"ok": True},
        cycle_id="testcycle",
        dry_run=False,
        message_fn=message_fn,
        grok_fn=grok_fn,
        pytest_fn=pytest_fn,
        panel_timeout_s=5,
    )
    assert out["status"] == "synthesis_ok"
    assert out["ok"] is True
    assert "improved" in target.read_text(encoding="utf-8")
    # critiques written
    cdir = root / ".nexus_state" / "critiques" / "testcycle" / "demo:1" / "critiques"
    assert (cdir / "claude" / "critique.md").is_file()
    assert (cdir / "gpt" / "critique.md").is_file()
    assert (cdir / "antigravity" / "critique.md").is_file()


def test_synthesis_reverts_after_two_reds(tmp_path: Path):
    root = tmp_path
    (root / "src" / "nexus").mkdir(parents=True)
    target = root / "src" / "nexus" / "mod.py"
    target.write_text("GOOD\n", encoding="utf-8")

    def message_fn(agent: str, prompt: str) -> str:
        return f"# Critique {agent}\n\n### F1\n- severity: major\n- file: src/nexus/mod.py\n- problem: x\n- suggestion: fix\n"

    calls = {"n": 0}

    def grok_fn(root_arg, goal: str):
        calls["n"] += 1
        p = Path(root_arg) / "src" / "nexus" / "mod.py"
        p.write_text(f"BAD{calls['n']}\n", encoding="utf-8")
        return {"ok": True, "text": "broke it", "model": "mock"}

    def pytest_fn(root_arg, files):
        return {"ok": False, "mode": "mock", "output": "FAILED"}

    idea = {"id": "demo:2", "source": "github", "title": "T", "concrete": "c"}
    out = cp.run_slice_critique_panel(
        root,
        idea,
        before_status="",
        after_status="?? src/nexus/mod.py\n",
        cycle_id="revcycle",
        dry_run=False,
        message_fn=message_fn,
        grok_fn=grok_fn,
        pytest_fn=pytest_fn,
        max_fails=2,
    )
    assert out["status"] == "synthesis_reverted"
    assert out["ok"] is False
    # original Grok implement content restored
    assert target.read_text(encoding="utf-8") == "GOOD\n"
    assert calls["n"] == 2
    assert (
        root
        / ".nexus_state"
        / "critiques"
        / "revcycle"
        / "demo:2"
        / "synthesis"
        / "REVERTED.md"
    ).is_file()


def test_panel_runs_critics_in_parallel(tmp_path: Path):
    """All three critics should be invoked without waiting sequentially."""
    import threading
    import time as _time

    root = tmp_path
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("1\n", encoding="utf-8")
    started: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(3, timeout=5)

    def message_fn(agent: str, prompt: str) -> str:
        with lock:
            started.append(agent)
        # All three must reach the barrier ≈ at once if parallel
        barrier.wait()
        return f"# Critique {agent}\nok"

    idea = {"id": "par:1", "source": "arxiv", "title": "t", "concrete": "c"}
    t0 = _time.time()
    res = cp.collect_panel_critiques(
        root,
        idea,
        pack_dir=cp.write_review_pack(
            root,
            idea,
            cycle_id="parcyc",
            slice_files=["src/a.py"],
            diff_text="diff",
        ),
        slice_files=["src/a.py"],
        diff_text="diff",
        message_fn=message_fn,
        timeout_s=30,
        parallel=True,
    )
    elapsed = _time.time() - t0
    assert res["parallel"] is True
    assert res["ok"] is True
    assert set(res["critics"]) == {"claude", "gpt", "antigravity"}
    assert all(res["critics"][a]["ok"] for a in ("claude", "gpt", "antigravity"))
    # Sequential would take ~3 * barrier delay; parallel finishes near one wait
    assert elapsed < 4.0
    assert set(started) == {"claude", "gpt", "antigravity"}


def test_dry_run_critiques_only(tmp_path: Path):
    root = tmp_path
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("1\n", encoding="utf-8")

    def message_fn(agent: str, prompt: str) -> str:
        return f"# Critique {agent}\nsummary"

    idea = {"id": "dry:1", "source": "arxiv", "title": "t", "concrete": "c"}
    out = cp.run_slice_critique_panel(
        root,
        idea,
        before_status="",
        after_status=" M src/a.py\n",
        cycle_id="dryc",
        dry_run=True,
        message_fn=message_fn,
        pytest_fn=lambda *a, **k: {"ok": False},  # must not matter
    )
    assert out["status"] == "dry_critiques_only"
    assert out["ok"] is True
    assert (root / "src" / "a.py").read_text(encoding="utf-8") == "1\n"
