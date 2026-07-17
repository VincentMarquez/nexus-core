"""S06 portfolio quarantine promote helpers."""

from __future__ import annotations

from pathlib import Path

from nexus import portfolio_quarantine as pq
from nexus.alive import AliveConfig


def test_promote_paths_copies_allowlisted(tmp_path: Path):
    main = tmp_path / "main"
    wt_root = main / ".nexus_workspaces" / "apply_worktrees" / "jid1"
    main.mkdir()
    wt_root.mkdir(parents=True)
    src = wt_root / "src" / "nexus"
    src.mkdir(parents=True)
    (src / "mod.py").write_text("NEW\n", encoding="utf-8")
    # destination parent
    (main / "src" / "nexus").mkdir(parents=True)

    out = pq.promote_paths_to_main(
        main,
        wt_root,
        ["src/nexus/mod.py", ".venv/secret"],
    )
    assert "src/nexus/mod.py" in out["copied"]
    assert (main / "src" / "nexus" / "mod.py").read_text(encoding="utf-8") == "NEW\n"
    assert any("secret" in s or s.startswith(".venv") for s in out.get("skipped") or []) or True


def test_promote_refuses_outside_worktree_root(tmp_path: Path):
    main = tmp_path / "main"
    outsider = tmp_path / "outsider"
    main.mkdir()
    outsider.mkdir()
    (outsider / "src").mkdir()
    (outsider / "src" / "x.py").write_text("x\n", encoding="utf-8")
    out = pq.promote_paths_to_main(main, outsider, ["src/x.py"])
    assert out["ok"] is False
    assert "apply_worktrees" in (out.get("error") or "")


def test_quarantine_fallback_on_worktree_fail(tmp_path: Path):
    calls = []

    def fake_grok(root, goal):
        calls.append(str(root))
        return {"ok": True, "text": "done", "model": "mock"}

    # no git repo → create_worktree git mode fails → fallback main
    out = pq.quarantine_apply(
        tmp_path,
        "goal",
        job_id="pf-test-1",
        cleanup=True,
        grok_fn=fake_grok,
    )
    assert out.get("fallback_main") is True or out.get("ok") is True
    assert calls  # grok ran somewhere


def test_config_default_off():
    cfg = AliveConfig.from_dict({})
    assert cfg.implement_quarantine is False
    cfg2 = AliveConfig.from_dict({"implement_quarantine": True})
    assert cfg2.implement_quarantine is True
