"""Tests for comm_bench (offline, deterministic)."""

from __future__ import annotations

import json
from pathlib import Path

from nexus import comm_bench as cb


def test_bench_pattern_metrics():
    calls = [
        lambda: {"ok": True, "score": 7.0, "tokens_in": 100, "tokens_out": 20},
        lambda: {"ok": True, "score": 3.0, "tokens_in": 80, "tokens_out": 10},
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    ]
    row = cb.bench_pattern("demo", calls)
    assert row["calls"] == 3
    assert row["ok_rate"] == round(2 / 3, 3)
    assert row["tokens_in"] == 180 and row["tokens_out"] == 30
    assert row["mean_score"] == 5.0
    assert row["scored_ge6"] == 1
    assert row["p50_ms"] >= 0.0


def test_run_comm_bench_offline(tmp_path: Path, monkeypatch):
    d = tmp_path / ".nexus_state" / "arxiv_improve"
    d.mkdir(parents=True)
    (d / "improve-rx-t.md").write_text(
        "1. **Relevant Multi-Agent Review for SWE Bench Code Repair** — `2501.11111v1`\n"
        "   https://arxiv.org/abs/2501.11111v1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cb.pi, "fetch_abstract",
        lambda root, pid, delay=0: {
            "id": pid,
            "title": "Relevant Multi-Agent Review for SWE Bench Code Repair",
            "summary": "multi-agent group review pipeline improves swe-bench resolve "
            "rate with budget gating and self-check",
        },
    )
    res = cb.run_comm_bench(tmp_path, include_llm=False)
    assert res["ok"] is True
    assert res["rows"][0]["pattern"] == "heuristic"
    assert res["rows"][0]["calls"] == 1
    data = json.loads(Path(res["json"]).read_text())
    assert data["paper"] == "2602.03128v1"
    assert Path(res["md"]).read_text().count("|") > 10


def test_run_comm_bench_no_note(tmp_path: Path):
    res = cb.run_comm_bench(tmp_path, include_llm=False)
    assert res["ok"] is False
