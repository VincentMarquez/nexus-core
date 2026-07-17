"""comm_bench — unified overhead benchmark for agent communication patterns.

Implements the concrete recommendation from arXiv:2602.03128
("Understanding Multi-Agent LLM Frameworks: A Unified Benchmark and
Experimental Analysis"), ranked #1 by paper_improve: measure the overhead
of the communication/scoring patterns this codebase actually uses, on
unified dimensions — latency, tokens, success rate — and emit a
comparable table.

Patterns benchmarked here:
  * heuristic     — offline term-overlap paper scoring (no model)
  * ollama_llm    — local model read+score via /api/generate

Output: .nexus_state/bench/comm_bench-<ts>.{json,md}
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import paper_improve as pi


def _p50(vals: list[float]) -> float:
    return round(statistics.median(vals), 1) if vals else 0.0


def bench_pattern(
    name: str,
    calls: list[Callable[[], dict[str, Any]]],
) -> dict[str, Any]:
    """Run callables for one pattern; collect unified metrics.

    Each callable returns a dict; keys used if present:
      ok (bool), tokens_in (int), tokens_out (int), score (float)
    """
    lat: list[float] = []
    oks = 0
    tin = tout = 0
    scores: list[float] = []
    for fn in calls:
        t0 = time.time()
        try:
            res = fn() or {}
            ok = bool(res.get("ok", True))
        except Exception:
            res, ok = {}, False
        lat.append((time.time() - t0) * 1000.0)
        oks += 1 if ok else 0
        tin += int(res.get("tokens_in", 0) or 0)
        tout += int(res.get("tokens_out", 0) or 0)
        if res.get("score") is not None:
            scores.append(float(res["score"]))
    n = max(1, len(calls))
    return {
        "pattern": name,
        "calls": len(calls),
        "ok_rate": round(oks / n, 3),
        "p50_ms": _p50(lat),
        "total_ms": round(sum(lat), 1),
        "tokens_in": tin,
        "tokens_out": tout,
        "mean_score": round(statistics.mean(scores), 2) if scores else None,
        "scored_ge6": sum(1 for s in scores if s >= 6.0),
    }


def _paper_calls(
    root: Path,
    papers: list[dict[str, Any]],
    capsule: str,
    *,
    use_llm: bool,
    model: Optional[str] = None,
) -> list[Callable[[], dict[str, Any]]]:
    def make(p: dict[str, Any]) -> Callable[[], dict[str, Any]]:
        def call() -> dict[str, Any]:
            sc = (
                pi.score_paper_llm(p, capsule, model=model)
                if use_llm
                else pi.score_paper_heuristic(p, capsule)
            )
            ok = not str(sc.get("rationale", "")).startswith("llm unavailable")
            return {"ok": ok, "score": sc.get("applicability", 0.0)}

        return call

    return [make(p) for p in papers]


def run_comm_bench(
    workdir: Optional[Path | str] = None,
    *,
    limit: int = 10,
    model: Optional[str] = None,
    include_llm: bool = True,
) -> dict[str, Any]:
    """Benchmark scoring/communication patterns on cached papers; write report."""
    root = Path(workdir or ".").resolve()
    note = pi.latest_note(root)
    if note is None:
        return {"ok": False, "error": "no arxiv note found"}
    metas = pi.parse_note_papers(note)[: max(1, limit)]
    papers = []
    for m in metas:
        p = pi.fetch_abstract(root, m["id"], delay=0)  # cache hit path
        p.setdefault("title", m["title"])
        papers.append(p)
    capsule = pi.repo_capsule(root)

    rows = [bench_pattern("heuristic", _paper_calls(root, papers, capsule, use_llm=False))]
    if include_llm:
        rows.append(
            bench_pattern(
                "ollama_llm",
                _paper_calls(root, papers, capsule, use_llm=True, model=model),
            )
        )

    out_dir = root / ".nexus_state" / "bench"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    jpath = out_dir / f"comm_bench-{ts}.json"
    jpath.write_text(
        json.dumps({"schema": "nexus.comm_bench/v1", "paper": "2602.03128v1",
                    "rows": rows}, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# comm_bench — unified communication/scoring overhead (arXiv:2602.03128)",
        "",
        "| pattern | calls | ok_rate | p50 ms | total ms | mean score | applicable(>=6) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['pattern']} | {r['calls']} | {r['ok_rate']} | {r['p50_ms']} | "
            f"{r['total_ms']} | {r['mean_score']} | {r['scored_ge6']} |"
        )
    mpath = out_dir / f"comm_bench-{ts}.md"
    mpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "rows": rows, "json": str(jpath), "md": str(mpath)}
