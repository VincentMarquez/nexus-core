"""Tests for mission-control quality gate + completion receipts + spend caps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import mission_gate as mg
from nexus.ops_store import OpsStore


# ── receipts (stdlib HMAC shape of mission-control receipt-signing) ─────────


def test_canonicalize_sorted_and_stable():
    a = mg.canonicalize({"b": 1, "a": {"z": 2, "y": 3}})
    b = mg.canonicalize({"a": {"y": 3, "z": 2}, "b": 1})
    assert a == b
    assert '"a"' in a
    # keys ordered: a before b
    assert a.index('"a"') < a.index('"b"')


def test_sign_and_verify_receipt_roundtrip():
    payload = {"job_id": "j1", "status": "completed", "tokens": 42}
    secret = "test-secret-not-for-prod"
    receipt = mg.sign_receipt(payload, secret=secret)
    assert receipt["alg"] == "HMAC-SHA256"
    assert len(receipt["payload_hash"]) == 64
    assert len(receipt["signature"]) == 64
    assert mg.verify_receipt(payload, receipt, secret=secret) is True
    # tamper
    bad = dict(payload, tokens=99)
    assert mg.verify_receipt(bad, receipt, secret=secret) is False
    assert mg.verify_receipt(payload, receipt, secret="wrong") is False


def test_sign_requires_secret():
    with pytest.raises(mg.MissionGateError) as ei:
        mg.sign_receipt({"x": 1}, secret="")
    assert ei.value.code == "secret_required"


# ── enable + quality review ─────────────────────────────────────────────────


def test_enable_gate_and_record_review(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        out = gate.enable_gate(
            "job-q1",
            title="quality task",
            goal="ship with review",
            max_tokens=500,
        )
        assert out["schema"] == mg.SCHEMA
        assert out["policy"]["enabled"] is True
        assert out["policy"]["require_review"] is True
        assert out["policy"]["max_tokens"] == 500

        rev = gate.record_review(
            "job-q1",
            reviewer="aegis",
            status="approved",
            notes="LGTM",
        )
        assert rev["status"] == "approved"
        assert rev["reviewer"] == "aegis"
        latest = gate.latest_review("job-q1")
        assert latest is not None
        assert latest["id"] == rev["id"]
        assert latest["notes"] == "LGTM"


def test_review_rejects_unknown_job(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        with pytest.raises(mg.MissionGateError) as ei:
            gate.record_review("missing", status="approved")
        assert ei.value.code == "job_not_found"


def test_review_invalid_status(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        gate.enable_gate("job-bad")
        with pytest.raises(mg.MissionGateError) as ei:
            gate.record_review("job-bad", status="lgtm-maybe")
        assert ei.value.code == "invalid_review_status"


def test_rejected_review_blocks_board(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        gate.enable_gate("job-r", status="running")
        gate.record_review("job-r", status="rejected", notes="needs tests")
        job = gate.store.get("job-r")
        assert job is not None
        assert job["status"] == "blocked"


# ── complete gate ───────────────────────────────────────────────────────────


def test_complete_requires_approved_review(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        gate.enable_gate("job-c1", require_review=True)
        chk = gate.check_complete("job-c1")
        assert chk["ok"] is False
        assert "missing_quality_review" in chk["reasons"]

        with pytest.raises(mg.MissionGateError) as ei:
            gate.complete("job-c1")
        assert ei.value.code == "missing_quality_review"

        gate.record_review("job-c1", status="needs_work")
        chk2 = gate.check_complete("job-c1")
        assert chk2["ok"] is False
        assert any("review_not_approved" in r for r in chk2["reasons"])

        gate.record_review("job-c1", status="approved", notes="ok now")
        out = gate.complete("job-c1")
        assert out["ok"] is True
        assert out["job"]["status"] == "completed"
        assert out["receipt"] is not None
        assert out["receipt"]["receipt"]["payload_hash"]


def test_complete_force_skips_review(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        gate.enable_gate("job-force", require_review=True)
        out = gate.complete("job-force", force=True)
        assert out["ok"] is True
        assert out["forced"] is True
        assert out["job"]["status"] == "completed"


def test_completion_receipt_verifies(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        gate.enable_gate("job-rcpt", require_review=True)
        gate.record_review("job-rcpt", status="approved")
        out = gate.complete("job-rcpt", notes="done")
        rid = out["receipt"]["id"]
        v = gate.verify_stored_receipt(rid)
        assert v["ok"] is True
        v2 = gate.verify_stored_receipt(job_id="job-rcpt")
        assert v2["ok"] is True
        latest = gate.latest_receipt("job-rcpt")
        assert latest is not None
        assert latest["id"] == rid
        # payload integrity via public helpers
        assert mg.verify_receipt(
            latest["payload"],
            {
                "payload_hash": latest["payload_hash"],
                "signature": latest["signature"],
            },
            secret=gate.get_or_create_secret(),
        )


# ── spend hard-cap ──────────────────────────────────────────────────────────


def test_spend_cap_blocks_over_budget(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        gate.enable_gate("job-cap", max_tokens=100, require_review=False)
        ok = gate.gated_record_spend("job-cap", 60, source="agent:a", label="step1")
        assert ok["ok"] is True
        assert ok["spend"]["job"]["tokens"] == 60

        with pytest.raises(mg.MissionGateError) as ei:
            gate.gated_record_spend("job-cap", 50, source="agent:a")
        assert ei.value.code == "spend_cap_exceeded"

        # force override
        forced = gate.gated_record_spend(
            "job-cap", 50, source="agent:a", force=True
        )
        assert forced["ok"] is True
        assert forced["spend"]["job"]["tokens"] == 110


def test_complete_blocked_when_over_cap(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        gate.enable_gate(
            "job-over",
            max_tokens=10,
            require_review=True,
        )
        gate.store.record_spend("job-over", 20, source="runaway")
        gate.record_review("job-over", status="approved")
        chk = gate.check_complete("job-over")
        assert chk["ok"] is False
        assert "spend_cap_exceeded" in chk["reasons"]


def test_set_spend_cap(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        gate.store.ensure_job("job-sc", kind="task", status="running")
        out = gate.set_spend_cap("job-sc", 250)
        assert out["max_tokens"] == 250
        pol = gate._policy(gate.store.get("job-sc") or {})
        assert pol["max_tokens"] == 250


# ── summary + functional helpers ────────────────────────────────────────────


def test_summary_and_helpers(tmp_path: Path):
    en = mg.enable_mission_gate(tmp_path, "job-h", max_tokens=99)
    assert en["job_id"] == "job-h"
    with mg.MissionGate.open(tmp_path) as gate:
        gate.record_review("job-h", status="approved")
    out = mg.complete_with_gate(tmp_path, "job-h")
    assert out["ok"] is True
    with mg.MissionGate.open(tmp_path) as gate:
        s = gate.summary("job-h")
        assert s["job"]["status"] == "completed"
        assert s["latest_review"]["status"] == "approved"
        assert s["latest_receipt"] is not None
        board = gate.summary()
        assert board["n_reviews"] >= 1
        assert board["n_receipts"] >= 1


# ── module CLI ──────────────────────────────────────────────────────────────


def test_module_cli_lifecycle(tmp_path: Path, capsys):
    def run(argv: list[str]) -> tuple[int, str]:
        capsys.readouterr()  # clear
        rc = mg.main(argv)
        return rc, capsys.readouterr().out

    rc, _ = run(
        [
            "--workdir",
            str(tmp_path),
            "enable",
            "cli-job",
            "--max-tokens",
            "200",
            "--title",
            "cli",
        ]
    )
    assert rc == 0
    rc, _ = run(
        [
            "--workdir",
            str(tmp_path),
            "review",
            "cli-job",
            "--status",
            "approved",
            "--notes",
            "ship it",
        ]
    )
    assert rc == 0
    rc, out = run(["--workdir", str(tmp_path), "check", "cli-job", "--json"])
    assert rc == 0
    check = json.loads(out)
    assert check["ok"] is True
    rc, _ = run(
        ["--workdir", str(tmp_path), "spend", "cli-job", "40", "--source", "cli"]
    )
    assert rc == 0
    rc, out = run(["--workdir", str(tmp_path), "complete", "cli-job", "--json"])
    assert rc == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["job"]["status"] == "completed"
    assert payload.get("receipt") is not None
    rc, out = run(["--workdir", str(tmp_path), "verify", "cli-job", "--json"])
    assert rc == 0
    assert json.loads(out)["ok"] is True


def test_module_cli_check_fails_without_review(tmp_path: Path):
    with mg.MissionGate.open(tmp_path) as gate:
        gate.enable_gate("no-rev", require_review=True)
    rc = mg.main(["--workdir", str(tmp_path), "check", "no-rev"])
    assert rc == 2


def test_ops_store_still_independent(tmp_path: Path):
    """Mission gate tables must not break plain OpsStore open/use."""
    with OpsStore.open(tmp_path) as store:
        store.upsert_job("plain", kind="task", status="inbox", title="plain")
        store.record_spend("plain", 5, source="x")
        store.set_status("plain", "completed")
        assert store.get("plain")["status"] == "completed"
    # gate can open same db and add tables
    with mg.MissionGate.open(tmp_path) as gate:
        assert gate.store.get("plain")["tokens"] == 5
        gate.enable_gate("plain2")
        assert gate.store.get("plain2") is not None
