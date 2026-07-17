"""Tests for Thucy-style claim verification (P0.4 / arXiv 2512.03278)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.claim_verify import (
    ClaimVerifyError,
    missing_fields,
    verify_claim,
    verify_or_report,
)


def _good(**overrides):
    base = {
        "repo": "wshobson/agents",
        "score": 16.0,
        "idea": 8.0,
        "skill": 8.0,
        "path": ".nexus_workspaces/mine_eval/wshobson__agents",
        "method": "grok:grok-4.5",
    }
    base.update(overrides)
    return base


def test_verify_passes_complete_grade():
    out = verify_claim(_good())
    assert out["ok"] is True
    assert out["score"] == 16.0
    assert out["idea"] == 8.0
    assert out["skill"] == 8.0
    assert "wshobson" in out["path"]


def test_missing_path_fails():
    with pytest.raises(ClaimVerifyError, match="path"):
        verify_claim(_good(path=""))
    with pytest.raises(ClaimVerifyError, match="missing"):
        g = _good()
        del g["path"]
        verify_claim(g)


def test_missing_score_fails():
    g = _good()
    del g["score"]
    with pytest.raises(ClaimVerifyError, match="score"):
        verify_claim(g)
    assert "score" in missing_fields(g)


def test_non_numeric_score_fails():
    with pytest.raises(ClaimVerifyError, match="score"):
        verify_claim(_good(score="high"))


def test_missing_idea_or_skill_fails():
    for key in ("idea", "skill"):
        g = _good()
        del g[key]
        with pytest.raises(ClaimVerifyError):
            verify_claim(g)


def test_verify_or_report_soft():
    bad = verify_or_report({"repo": "x"})
    assert bad["ok"] is False
    assert bad["missing"]
    good = verify_or_report(_good())
    assert good["ok"] is True


def test_require_path_exists(tmp_path: Path):
    evidence = tmp_path / "evidence" / "repo"
    evidence.mkdir(parents=True)
    rel = "evidence/repo"
    out = verify_claim(
        _good(path=rel),
        workdir=tmp_path,
        require_path_exists=True,
    )
    assert out["ok"] is True
    assert Path(out["resolved_path"]).is_dir()

    with pytest.raises(ClaimVerifyError, match="does not exist"):
        verify_claim(
            _good(path="missing/path"),
            workdir=tmp_path,
            require_path_exists=True,
        )


def test_min_score_gate():
    with pytest.raises(ClaimVerifyError, match="min_score"):
        verify_claim(_good(score=5.0), min_score=10.0)


# ── PatchDiff integration (arXiv 2503.15223) ───────────────────────────────

_PROD_PATCH = """\
diff --git a/src/nexus/foo.py b/src/nexus/foo.py
--- a/src/nexus/foo.py
+++ b/src/nexus/foo.py
@@ -1,2 +1,2 @@
 def foo():
-    return 1
+    return 2
"""

_TEST_ONLY_PATCH = """\
diff --git a/tests/test_foo.py b/tests/test_foo.py
--- a/tests/test_foo.py
+++ b/tests/test_foo.py
@@ -1,2 +1,3 @@
 def test_foo():
     assert True
+    assert 1 == 1
"""


def test_claim_without_patch_has_no_patch_diff():
    out = verify_claim(_good())
    assert out["ok"] is True
    assert "patch_diff" not in out


def test_claim_attaches_soft_patch_diff_test_only():
    """Soft mode: claim still ok, but patch_diff report flags test-only."""
    out = verify_claim(_good(patch=_TEST_ONLY_PATCH))
    assert out["ok"] is True
    pd = out["patch_diff"]
    assert pd["schema"] == "nexus.patch_diff/v1"
    assert pd["ok"] is False
    assert "test_only" in pd["flags"]
    assert pd["verdict"] == "suspicious"


def test_claim_hard_patch_diff_refuses_test_only():
    with pytest.raises(ClaimVerifyError, match="patch_diff failed"):
        verify_claim(
            _good(patch=_TEST_ONLY_PATCH),
            require_patch_diff_ok=True,
        )


def test_claim_hard_patch_diff_accepts_production():
    out = verify_claim(
        _good(patch=_PROD_PATCH, gold_patch=_PROD_PATCH),
        require_patch_diff_ok=True,
    )
    assert out["ok"] is True
    assert out["patch_diff"]["verdict"] == "equivalent"
    assert out["patch_diff"]["ok"] is True


def test_claim_can_disable_patch_diff():
    out = verify_claim(_good(patch=_TEST_ONLY_PATCH), run_patch_diff=False)
    assert "patch_diff" not in out


def test_verify_or_report_hard_patch_diff():
    soft = verify_or_report(_good(patch=_TEST_ONLY_PATCH))
    assert soft["ok"] is True
    assert soft["patch_diff"]["ok"] is False

    hard = verify_or_report(
        _good(patch=_TEST_ONLY_PATCH),
        require_patch_diff_ok=True,
    )
    assert hard["ok"] is False
    assert any("patch_diff" in r for r in hard["reasons"])


def test_verify_or_report_unknown_patch_diff_checks_soft():
    """Soft mode must not raise PatchDiffError for bad check ids."""
    soft = verify_or_report(
        _good(patch=_PROD_PATCH),
        patch_diff_checks=["typo_not_a_check"],
    )
    assert soft["ok"] is True
    assert soft["patch_diff"]["ok"] is False
    assert soft["patch_diff"]["verdict"] == "skip"
    assert "error" in soft["patch_diff"].get("flags", [])


def test_verify_or_report_unknown_patch_diff_checks_hard():
    hard = verify_or_report(
        _good(patch=_PROD_PATCH),
        patch_diff_checks=["typo_not_a_check"],
        require_patch_diff_ok=True,
    )
    assert hard["ok"] is False
    assert any("patch_diff" in r for r in hard["reasons"])


def test_claim_generic_files_key_no_patch_diff():
    """Pre-existing grades with dict files= must not grow a bogus report."""
    out = verify_claim(
        _good(files=[{"path": "src/a.py", "status": "M"}])
    )
    assert out["ok"] is True
    assert "patch_diff" not in out


def test_claim_hard_min_overlap_refuses_disjoint_gold():
    other = """\
diff --git a/src/nexus/bar.py b/src/nexus/bar.py
--- a/src/nexus/bar.py
+++ b/src/nexus/bar.py
@@ -1,1 +1,1 @@
-a
+b
"""
    with pytest.raises(ClaimVerifyError, match="patch_diff failed"):
        verify_claim(
            _good(patch=_PROD_PATCH, gold_patch=other),
            require_patch_diff_ok=True,
            patch_diff_min_overlap=0.9,
        )


def test_claim_fail_verdicts_divergent():
    """Opt-in: refuse content-divergent candidates when gold is trusted."""
    divergent = """\
diff --git a/src/nexus/foo.py b/src/nexus/foo.py
--- a/src/nexus/foo.py
+++ b/src/nexus/foo.py
@@ -1,2 +1,2 @@
 def foo():
-    return 1
+    return 99
"""
    # Default hard mode still accepts divergent (warn, ok=True on report).
    ok = verify_claim(
        _good(patch=_PROD_PATCH, gold_patch=divergent),
        require_patch_diff_ok=True,
    )
    assert ok["patch_diff"]["verdict"] == "divergent"

    with pytest.raises(ClaimVerifyError, match="patch_diff failed"):
        verify_claim(
            _good(patch=_PROD_PATCH, gold_patch=divergent),
            require_patch_diff_ok=True,
            patch_diff_fail_verdicts=("divergent",),
        )


def test_claim_hard_without_patch_still_passes():
    """require_patch_diff_ok only gates present reports (documented)."""
    out = verify_claim(_good(), require_patch_diff_ok=True)
    assert out["ok"] is True
    assert "patch_diff" not in out
