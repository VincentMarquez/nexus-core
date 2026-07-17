"""Tests for SWE-Exp Experience Bank (arxiv:2507.23361v2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import experience_bank as eb


def test_classify_issue_types():
    assert eb.classify_issue("ModuleNotFoundError: No module named 'x'") == "missing_dependency"
    assert eb.classify_issue("AssertionError: 1 == 2") == "test_assertion_failure"
    assert eb.classify_issue("unexpected keyword argument 'foo'") == "incorrect_api_usage"
    assert eb.classify_issue("") == "generic_repair"
    assert "missing_dependency" in eb.list_issue_types()
    # First-match priority: ImportError wins over a later AssertionError signal.
    assert (
        eb.classify_issue("FAILED tests/x.py ImportError: no module\nAssertionError")
        == "missing_dependency"
    )


def test_make_abstract_success_and_failure():
    ok = eb.make_abstract("test_assertion_failure", "fix minimal unit.")
    assert "try approach first" in ok
    assert "test_assertion_failure" in ok
    # Approaches ending in "first" must not produce "first first".
    ok_first = eb.make_abstract("generic_repair", "try imports first")
    assert not ok_first.endswith("first first")
    assert ok_first.endswith("try imports first")
    bad = eb.make_abstract(
        "test_assertion_failure", "ignore failing tests", outcome=eb.OUTCOME_FAILURE
    )
    assert "avoid approach" in bad


def test_record_load_roundtrip(tmp_path: Path):
    row = eb.record(
        tmp_path,
        issue_type="missing_dependency",
        approach="Add missing package to pyproject and reinstall",
        outcome="success",
        source="test",
        evidence="ModuleNotFoundError: foo",
        repo="example/repo",
    )
    assert row["schema"] == eb.SCHEMA
    assert row["id"].startswith("exp-")
    assert "try approach" in row["abstract"]
    assert eb.bank_path(tmp_path).is_file()

    rows = eb.load(tmp_path, limit=10)
    assert len(rows) == 1
    assert rows[0]["approach"].startswith("Add missing package")

    fails = eb.load(tmp_path, outcome="failure")
    assert fails == []


def test_record_classifies_from_issue_text(tmp_path: Path):
    row = eb.record(
        tmp_path,
        approach="Parse JSON before writing",
        outcome="success",
        issue_text="JSONDecodeError: Expecting value",
        source="test",
    )
    assert row["issue_type"] == "syntax_or_parse_error"


def test_record_rejects_empty_approach(tmp_path: Path):
    with pytest.raises(eb.ExperienceBankError):
        eb.record(tmp_path, approach="  ", outcome="success")


def test_record_rejects_bad_outcome(tmp_path: Path):
    with pytest.raises(eb.ExperienceBankError):
        eb.record(tmp_path, approach="x", outcome="maybe")


def test_recommend_prefers_success_over_failure(tmp_path: Path):
    # Real evidence only — no prior merge for this ranking assertion.
    eb.record(
        tmp_path,
        issue_type="test_assertion_failure",
        approach="Delete the failing test",
        outcome="failure",
        source="t",
    )
    eb.record(
        tmp_path,
        issue_type="test_assertion_failure",
        approach="Delete the failing test",
        outcome="failure",
        source="t",
    )
    eb.record(
        tmp_path,
        issue_type="test_assertion_failure",
        approach="Fix expected vs actual in the unit under test",
        outcome="success",
        source="t",
    )
    ranks = eb.recommend(
        tmp_path,
        issue_type="test_assertion_failure",
        limit=5,
        include_priors_seed=False,
    )
    assert ranks
    assert ranks[0]["approach"].startswith("Fix expected vs actual")
    assert ranks[0]["successes"] >= 1
    # limit=5 + two distinct approaches → failed approach is present and lower.
    by_ap = {r["approach"]: r for r in ranks}
    assert "Delete the failing test" in by_ap
    assert by_ap["Delete the failing test"]["score"] < ranks[0]["score"]


def test_recommend_cold_start_from_priors(tmp_path: Path):
    ranks = eb.recommend(
        tmp_path,
        issue_text="ModuleNotFoundError: No module named 'requests'",
        limit=3,
    )
    assert ranks
    assert ranks[0]["issue_type"] == "missing_dependency"
    assert ranks[0]["score"] > 0
    # disk still empty (cold-start is in-memory)
    assert eb.load(tmp_path) == []


def test_recommend_prior_survives_unrelated_rows(tmp_path: Path):
    """F1: non-empty bank must still surface catalog priors for unseen types."""
    eb.record(
        tmp_path,
        issue_type="timeout_or_hang",
        approach="retry blindly",
        outcome="success",
        source="t",
    )
    ranks = eb.recommend(tmp_path, issue_type="missing_dependency", limit=3)
    assert ranks, "expected catalog prior for missing_dependency on non-empty bank"
    assert ranks[0]["issue_type"] == "missing_dependency"
    assert ranks[0]["priors"] >= 1 or ranks[0]["score"] > 0


def test_recommend_prior_competes_with_failure_only(tmp_path: Path):
    """Failure-only bank for a type should still surface positive prior."""
    eb.record(
        tmp_path,
        issue_type="syntax_or_parse_error",
        approach="Just retry blindly",
        outcome="failure",
        source="t",
    )
    ranks = eb.recommend(
        tmp_path, issue_type="syntax_or_parse_error", limit=5, include_priors_seed=True
    )
    assert ranks
    # Prior catalog approach should outrank pure failure (score 0.556 > 0.333).
    top = ranks[0]
    assert top["failures"] == 0 or top["priors"] >= 1 or top["score"] >= 0.5


def test_load_skips_unknown_outcome_rows(tmp_path: Path):
    """F2: unknown stored outcomes must not raise on filtered load."""
    eb.record(
        tmp_path,
        issue_type="generic_repair",
        approach="good",
        outcome="failure",
        source="t",
    )
    path = eb.bank_path(tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "approach": "foreign-weird",
                    "outcome": "weird",
                    "issue_type": "generic_repair",
                }
            )
            + "\n"
        )
    fails = eb.load(tmp_path, outcome="failure")
    assert len(fails) == 1
    assert fails[0]["approach"] == "good"
    # Unfiltered load also keeps the foreign row (approach present) without raising.
    all_rows = eb.load(tmp_path, limit=10)
    assert any(r.get("approach") == "foreign-weird" for r in all_rows)


def test_load_reverse_false_keeps_newest_window(tmp_path: Path):
    """F3: reverse=False + limit keeps newest N (not oldest N)."""
    for i in range(6):
        eb.record(
            tmp_path,
            issue_type="generic_repair",
            approach=f"a{i}",
            outcome="success" if i == 5 else "failure",
            source="t",
        )
    rows = eb.load(tmp_path, limit=5, reverse=False)
    approaches = [r["approach"] for r in rows]
    assert "a5" in approaches, "newest success must survive truncation"
    assert "a0" not in approaches, "oldest row should be dropped under limit=5"
    assert approaches == sorted(approaches) or approaches[-1] == "a5"
    # Chronological among kept window: oldest-of-window first.
    assert approaches[0] == "a1"
    assert approaches[-1] == "a5"


def test_stats_reports_truncation_fields(tmp_path: Path):
    eb.record(tmp_path, issue_type="generic_repair", approach="x", outcome="success")
    st = eb.stats(tmp_path)
    assert st["n"] == 1
    assert st["n_total"] == 1
    assert st["truncated"] is False


def test_harvest_uses_abstracted_default_approach(tmp_path: Path):
    """F4: missing approach → constant abstraction, not per-rid unique strings."""
    out = eb.harvest_from_implement_results(
        tmp_path,
        [
            {"id": "r1", "ok": True},
            {"id": "r2", "ok": True},
            {"id": "r3", "ok": True},
            {"id": "r4", "ok": False, "error": "AssertionError"},  # no approach → skip
            {"id": "r5", "ok": "false"},  # string false → failure; no approach → skip
            {"id": "r6", "ok": "true", "approach": "Custom structured fix"},
        ],
        run_id="run-h",
    )
    assert out["written"] == 4  # r1,r2,r3 abstracted + r6 structured
    assert out["skipped"] >= 2
    rows = eb.load(tmp_path, limit=20, reverse=False)
    approaches = [r["approach"] for r in rows]
    # Three repos share one bucket string; rid lives in repo field.
    assert approaches.count(eb.HARVEST_DEFAULT_SUCCESS_APPROACH) == 3
    assert not any("Landed implement for r" in a for a in approaches)
    repos = {r["repo"] for r in rows}
    assert "r1" in repos and "r2" in repos and "r3" in repos


def test_aggregate_failure_only_uses_avoid_abstract():
    ranks = eb.aggregate(
        [
            {
                "issue_type": "generic_repair",
                "approach": "delete tests",
                "outcome": "failure",
                # foreign row with no stored abstract
            }
        ]
    )
    assert ranks
    assert "avoid approach" in ranks[0].abstract
    assert ranks[0].failures == 1


def test_format_recommend_block_marks_avoid():
    ranks = [
        {
            "issue_type": "generic_repair",
            "approach": "delete tests",
            "score": 0.33,
            "successes": 0,
            "failures": 3,
            "abstract": "If issue type `generic_repair`, try approach first: delete tests",
        }
    ]
    block = eb.format_recommend_block(ranks, issue_type="generic_repair")
    assert "[AVOID]" in block
    assert "avoid approach" in block


def test_seed_priors_idempotent(tmp_path: Path):
    a = eb.seed_priors(tmp_path)
    assert a["seeded"] == len(eb.DEFAULT_PRIORS)
    b = eb.seed_priors(tmp_path)
    assert b["skipped"] is True
    assert b["seeded"] == 0
    st = eb.stats(tmp_path)
    assert st["n"] == len(eb.DEFAULT_PRIORS)
    assert st["by_outcome"].get("prior") == len(eb.DEFAULT_PRIORS)


def test_format_recommend_block():
    ranks = [
        {
            "issue_type": "missing_dependency",
            "approach": "check imports first",
            "score": 0.75,
            "successes": 2,
            "failures": 0,
            "abstract": "If issue type `missing_dependency`, try approach: check imports first",
        }
    ]
    block = eb.format_recommend_block(ranks, issue_type="missing_dependency")
    assert "Experience Bank" in block
    assert "missing_dependency" in block
    assert "try approach" in block
    assert "[TRY]" in block


def test_record_from_repair_and_harvest(tmp_path: Path):
    eb.record_from_repair(
        tmp_path,
        ok=True,
        issue_text="TimeoutError: hung",
        approach="Set explicit subprocess timeout",
        source="repair",
    )
    rows = eb.load(tmp_path)
    assert rows[0]["outcome"] == "success"
    assert rows[0]["issue_type"] == "timeout_or_hang"

    out = eb.harvest_from_implement_results(
        tmp_path,
        [
            {
                "id": "arxiv:2507.23361v2",
                "ok": True,
                "approach": "Land Experience Bank module + tests",
                "pattern": "experience-bank",
            },
            {
                "id": "other/idea",
                "ok": False,
                "error": "AssertionError: expected green",
                # no structured approach → skipped (not fabricated)
            },
            {
                "id": "other/fail",
                "ok": False,
                "approach": "Ignore the assertion",
                "error": "AssertionError: expected green",
            },
        ],
        run_id="run-1",
    )
    assert out["written"] == 2  # structured success + structured failure
    assert out["skipped"] >= 1
    all_rows = eb.load(tmp_path, limit=20)
    assert any(r.get("repo") == "arxiv:2507.23361v2" for r in all_rows)


def test_cli_record_recommend_stats(tmp_path: Path, capsys):
    rc = eb.main(
        [
            "--path",
            str(tmp_path),
            "record",
            "--issue-type",
            "incorrect_api_usage",
            "--approach",
            "Read the real signature before calling",
            "--outcome",
            "success",
        ]
    )
    assert rc == 0
    capsys.readouterr()  # drop human-readable record output
    rc2 = eb.main(
        [
            "--path",
            str(tmp_path),
            "--json",
            "recommend",
            "--issue-type",
            "incorrect_api_usage",
            "--limit",
            "3",
        ]
    )
    assert rc2 == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["issue_type"] == "incorrect_api_usage"
    assert data["recommendations"]

    rc3 = eb.main(["--path", str(tmp_path), "--json", "stats"])
    assert rc3 == 0
    st = json.loads(capsys.readouterr().out)
    assert st["n"] >= 1
    assert st["schema"] == eb.SCHEMA
    assert "truncated" in st


def test_cli_types():
    rc = eb.main(["types"])
    assert rc == 0
