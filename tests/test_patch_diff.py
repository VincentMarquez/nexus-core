"""Tests for structural PatchDiff preflight (arXiv 2503.15223)."""

from __future__ import annotations

import pytest

from nexus.patch_diff import (
    CHECK_CATALOG,
    PatchDiffError,
    catalog_self_check,
    compare_patches,
    diff_from_grade,
    extract_patch_payload,
    is_test_path,
    list_checks,
    parse_file_list,
    parse_unified_diff,
    patch_diff_or_report,
    validate_check_ids,
)


CANDIDATE_DIFF = """\
diff --git a/src/nexus/foo.py b/src/nexus/foo.py
--- a/src/nexus/foo.py
+++ b/src/nexus/foo.py
@@ -1,3 +1,4 @@
 def foo():
-    return 1
+    return 2
+    # fix
"""

GOLD_SAME = CANDIDATE_DIFF

GOLD_OTHER_FILE = """\
diff --git a/src/nexus/bar.py b/src/nexus/bar.py
--- a/src/nexus/bar.py
+++ b/src/nexus/bar.py
@@ -1,2 +1,2 @@
 def bar():
-    return 0
+    return 1
"""

TEST_ONLY_DIFF = """\
diff --git a/tests/test_foo.py b/tests/test_foo.py
--- a/tests/test_foo.py
+++ b/tests/test_foo.py
@@ -1,2 +1,3 @@
 def test_foo():
-    assert True
+    assert True
+    assert 1 == 1
"""

DIVERGENT_SAME_FILE = """\
diff --git a/src/nexus/foo.py b/src/nexus/foo.py
--- a/src/nexus/foo.py
+++ b/src/nexus/foo.py
@@ -1,3 +1,3 @@
 def foo():
-    return 1
+    return 99
"""

BARE_MULTIFILE = """\
--- src/a.py
+++ src/a.py
@@ -1,1 +1,1 @@
-old_a
+new_a
--- src/b.py
+++ src/b.py
@@ -1,1 +1,1 @@
-old_b
+new_b
"""

BARE_WITH_TIMESTAMP = """\
--- a/src/nexus/foo.py\t2026-01-01 00:00:00
+++ b/src/nexus/foo.py\t2026-01-01 00:00:01
@@ -1,1 +1,1 @@
-x
+y
"""


def test_is_test_path_heuristics():
    assert is_test_path("tests/test_foo.py")
    assert is_test_path("src/pkg/test_bar.py")
    assert is_test_path("app/foo.spec.ts")
    assert is_test_path("pkg/__tests__/x.js")
    assert is_test_path("pkg/foo_test.go")
    assert is_test_path("pkg/foo_test.py")
    assert is_test_path("pkg/FooTest.java")
    assert not is_test_path("src/nexus/foo.py")
    assert not is_test_path("src/nexus/claim_verify.py")
    # Do not over-match production modules named spec/fixtures/testing.
    assert not is_test_path("src/spec/engine.py")
    assert not is_test_path("src/nexus/fixtures/loader.py")
    assert not is_test_path("src/testing/util.py")


def test_parse_unified_diff_files_and_counts():
    view = parse_unified_diff(CANDIDATE_DIFF)
    assert not view.empty
    assert "src/nexus/foo.py" in view.paths
    assert view.production_paths == {"src/nexus/foo.py"}
    assert view.test_paths == set()
    fc = view.files["src/nexus/foo.py"]
    assert fc.added_lines >= 1
    assert fc.removed_lines >= 1
    assert fc.hunk_count >= 1
    assert fc.content_fingerprint


def test_parse_bare_header_no_git_prefix():
    """diff -u style without diff --git / optional a/b prefix."""
    view = parse_unified_diff(BARE_WITH_TIMESTAMP)
    assert not view.empty
    assert "src/nexus/foo.py" in view.paths
    assert view.files["src/nexus/foo.py"].added_lines >= 1


def test_parse_multifile_bare_headers():
    view = parse_unified_diff(BARE_MULTIFILE)
    assert view.paths == {"src/a.py", "src/b.py"}
    assert view.files["src/a.py"].content_fingerprint
    assert view.files["src/b.py"].content_fingerprint


def test_parse_empty():
    view = parse_unified_diff("   \n")
    assert view.empty
    assert view.paths == set()


def test_parse_file_list():
    view = parse_file_list(["src/a.py", "tests/test_a.py", ""])
    assert view.paths == {"src/a.py", "tests/test_a.py"}
    assert view.test_paths == {"tests/test_a.py"}
    assert view.production_paths == {"src/a.py"}


def test_catalog_marketplace_shape():
    """wshobson-style single-source check marketplace."""
    assert len(CHECK_CATALOG) >= 5
    listed = list_checks()
    assert {r["check_id"] for r in listed} == set(CHECK_CATALOG)
    gate = catalog_self_check()
    assert gate["ok"] is True
    assert gate["count"] == len(CHECK_CATALOG)
    assert validate_check_ids(["empty_patch", "test_only"]) == []
    assert validate_check_ids(["nope_check"]) == ["nope_check"]
    assert "reference_unparseable" in CHECK_CATALOG


def test_compare_identical_to_reference():
    report = compare_patches(CANDIDATE_DIFF, GOLD_SAME)
    assert report["schema"] == "nexus.patch_diff/v1"
    assert report["ok"] is True
    assert report["verdict"] == "equivalent"
    assert report["overlap_jaccard"] == 1.0


def test_compare_test_only_suspicious():
    report = compare_patches(TEST_ONLY_DIFF)
    assert report["ok"] is False
    assert report["verdict"] == "suspicious"
    assert "test_only" in report["flags"]
    assert report["candidate"]["test_file_count"] == 1
    assert report["candidate"]["production_file_count"] == 0


def test_compare_empty_fail():
    report = compare_patches("not a real diff at all")
    # free-form without headers → empty view
    assert report["verdict"] == "empty"
    assert report["ok"] is False
    assert "empty_patch" in report["flags"]


def test_compare_file_set_mismatch():
    """Disjoint gold at default min_overlap=0 is warn; ok stays True."""
    report = compare_patches(CANDIDATE_DIFF, GOLD_OTHER_FILE)
    assert report["overlap_jaccard"] == 0.0
    assert "file_set_mismatch" in report["flags"]
    assert report["verdict"] == "divergent"
    assert report["ok"] is True  # warn-level only when min_overlap unset


def test_compare_min_overlap_breach_fails_ok():
    """Explicit min_overlap breach must flip ok=False (hard-gate teeth)."""
    report = compare_patches(
        CANDIDATE_DIFF,
        GOLD_OTHER_FILE,
        min_overlap=0.9,
    )
    assert report["overlap_jaccard"] == 0.0
    assert report["overlap_breach"] is True
    assert "file_set_mismatch" in report["flags"]
    assert report["verdict"] == "divergent"
    assert report["ok"] is False


def test_compare_content_divergence():
    report = compare_patches(CANDIDATE_DIFF, DIVERGENT_SAME_FILE)
    assert "content_divergence" in report["flags"]
    assert "src/nexus/foo.py" in report["shared_files"]
    assert report["verdict"] == "divergent"
    # warn-level by default — still ok unless fail_verdicts / min_overlap
    assert report["ok"] is True


def test_compare_file_lists_only_not_equivalent():
    """Path-only lists must not claim content equivalence."""
    report = compare_patches(
        None,
        None,
        candidate_files=["src/a.py", "tests/test_a.py"],
        reference_files=["src/a.py", "src/b.py"],
    )
    assert report["candidate"]["file_count"] == 2
    assert "missing_reference_files" in report["flags"]
    assert "src/b.py" in report["only_reference"]
    assert report["verdict"] != "equivalent"


def test_compare_identical_paths_no_body_caps_compatible():
    report = compare_patches(
        None,
        None,
        candidate_files=["src/a.py"],
        reference_files=["src/a.py"],
    )
    assert report["verdict"] == "compatible"
    assert report["ok"] is True
    assert "identical_reference" not in report["flags"]


def test_compare_unparseable_reference():
    report = compare_patches(CANDIDATE_DIFF, "GOLD PATCH CORRUPTED %%%")
    assert "reference_unparseable" in report["flags"]
    assert report["ok"] is False
    assert report["verdict"] == "compatible"  # candidate itself is fine
    # reference checks should not pretend "no reference provided"
    skip_details = [
        f["detail"]
        for f in report["findings"]
        if f.get("skipped") and f["check_id"] == "file_set_mismatch"
    ]
    assert skip_details
    assert "unparseable" in skip_details[0]


def test_unknown_check_raises():
    with pytest.raises(PatchDiffError, match="unknown"):
        compare_patches(CANDIDATE_DIFF, checks=["not_a_real_check"])


def test_subset_checks():
    report = compare_patches(
        TEST_ONLY_DIFF,
        checks=["empty_patch"],  # skip test_only
    )
    assert "test_only" not in report["flags"]
    assert report["ok"] is True  # only empty_patch ran and did not trigger


def test_extract_and_diff_from_grade():
    grade = {
        "score": 16,
        "idea": 8,
        "skill": 8,
        "path": "x",
        "patch": TEST_ONLY_DIFF,
        "gold_patch": CANDIDATE_DIFF,
    }
    payload = extract_patch_payload(grade)
    assert payload["has_payload"] is True
    assert payload["candidate"]
    assert payload["reference"]

    report = diff_from_grade(grade)
    assert report is not None
    assert "test_only" in report["flags"]

    assert diff_from_grade({"score": 1}) is None


def test_extract_ignores_generic_files_and_diff_keys():
    """Generic grade fields must not invent a patch payload."""
    grade = {
        "files": [{"path": "src/a.py", "status": "M"}],
        "diff": "not-a-patch-key-anymore",
        "score": 1,
    }
    payload = extract_patch_payload(grade)
    assert payload["has_payload"] is False
    assert diff_from_grade(grade) is None


def test_extract_skips_non_str_list_items():
    grade = {
        "patch_files": [{"path": "src/a.py"}, "src/b.py", None, ""],
    }
    payload = extract_patch_payload(grade)
    assert payload["has_payload"] is True
    assert payload["candidate_files"] == ["src/b.py"]


def test_extract_explicit_patch_files():
    grade = {"changed_files": ["src/a.py", "tests/test_a.py"]}
    payload = extract_patch_payload(grade)
    assert payload["candidate_files"] == ["src/a.py", "tests/test_a.py"]


def test_patch_diff_or_report_soft_error():
    bad = patch_diff_or_report(CANDIDATE_DIFF, checks=["zzz_bad"])
    assert bad["ok"] is False
    assert bad["verdict"] == "skip"
