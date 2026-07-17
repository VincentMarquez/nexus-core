"""arXiv paper ledger — skip papers already seen; AI-readable CSV.

Primary store (stdlib, Excel-friendly)::

  docs/ARXIV_LEDGER.csv          # committed, Grok/local LLM can read
  .nexus_state/arxiv_ledger.csv  # runtime mirror

Columns: arxiv_id, title, first_seen, last_seen, query, notes_path, times_seen

  from nexus.arxiv_ledger import seen_ids, filter_new, record_papers
"""

from __future__ import annotations

import csv
import os
import time
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import arxiv_client

# stable field order for Excel / Grok
FIELDS = (
    "arxiv_id",
    "title",
    "first_seen",
    "last_seen",
    "query",
    "notes_path",
    "times_seen",
    "abs_url",
)


def _root(workdir: Optional[Path] = None) -> Path:
    return Path(workdir or os.environ.get("NEXUS_PROJECT_ROOT") or os.getcwd()).resolve()


def docs_csv_path(workdir: Optional[Path] = None) -> Path:
    return _root(workdir) / "docs" / "ARXIV_LEDGER.csv"


def state_csv_path(workdir: Optional[Path] = None) -> Path:
    d = _root(workdir) / ".nexus_state"
    d.mkdir(parents=True, exist_ok=True)
    return d / "arxiv_ledger.csv"


def _canon_id(aid: str) -> str:
    """Normalize id; strip version suffix for dedup (2203.08975v2 → 2203.08975)."""
    s = arxiv_client.normalize_arxiv_id(aid)
    # drop trailing vN
    if "v" in s:
        base, _, rest = s.rpartition("v")
        if rest.isdigit() and base:
            return base
    return s


def load_rows(workdir: Optional[Path] = None) -> list[dict[str, str]]:
    """Load ledger rows (docs first, else state mirror)."""
    for path in (docs_csv_path(workdir), state_csv_path(workdir)):
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = []
                for r in reader:
                    if not r.get("arxiv_id"):
                        continue
                    rows.append({k: (r.get(k) or "") for k in FIELDS})
                if rows:
                    return rows
        except Exception:
            continue
    return []


def seen_ids(workdir: Optional[Path] = None) -> set[str]:
    """Canonical arXiv ids already in the ledger."""
    out: set[str] = set()
    for r in load_rows(workdir):
        out.add(_canon_id(r["arxiv_id"]))
    return out


def save_rows(rows: Sequence[dict[str, str]], workdir: Optional[Path] = None) -> list[Path]:
    """Write both docs (AI-readable) and state mirror CSVs."""
    root = _root(workdir)
    # stable sort by first_seen then id
    ordered = sorted(
        rows,
        key=lambda r: (r.get("first_seen") or "", r.get("arxiv_id") or ""),
    )
    written: list[Path] = []
    for path in (docs_csv_path(root), state_csv_path(root)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(FIELDS), extrasaction="ignore")
            w.writeheader()
            for r in ordered:
                w.writerow({k: r.get(k, "") for k in FIELDS})
        written.append(path)
    # short markdown cheat-sheet for agents that prefer md
    md = root / "docs" / "ARXIV_LEDGER.md"
    lines = [
        "# arXiv ledger (seen papers)",
        "",
        "Machine-readable twin: [`ARXIV_LEDGER.csv`](ARXIV_LEDGER.csv) "
        "(open in Excel / LibreOffice). Cycles **skip** ids already listed.",
        "",
        f"_Rows: {len(ordered)}_",
        "",
        "| arxiv_id | title | times | last_seen | query |",
        "|----------|-------|------:|-----------|-------|",
    ]
    for r in ordered[-50:]:  # last 50 for brevity
        title = (r.get("title") or "").replace("|", "/")[:70]
        lines.append(
            f"| {r.get('arxiv_id','')} | {title} | {r.get('times_seen','1')} | "
            f"{r.get('last_seen','')} | {(r.get('query') or '')[:40]} |"
        )
    lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")
    written.append(md)
    return written


def filter_new(
    papers: Iterable[Any],
    workdir: Optional[Path] = None,
    *,
    known: Optional[set[str]] = None,
) -> tuple[list[Any], list[Any]]:
    """Split papers into (new, already_seen). Accepts Paper or dict."""
    known = known if known is not None else seen_ids(workdir)
    fresh: list[Any] = []
    old: list[Any] = []
    for p in papers:
        if hasattr(p, "arxiv_id"):
            aid = p.arxiv_id
        else:
            aid = (p or {}).get("arxiv_id") or ""
        if _canon_id(aid) in known:
            old.append(p)
        else:
            fresh.append(p)
    return fresh, old


def record_papers(
    papers: Iterable[Any],
    *,
    query: str = "",
    notes_path: str = "",
    workdir: Optional[Path] = None,
) -> dict[str, Any]:
    """Upsert papers into the CSV ledger. Returns counts."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    by_id: dict[str, dict[str, str]] = {}
    for r in load_rows(workdir):
        by_id[_canon_id(r["arxiv_id"])] = dict(r)

    added = 0
    updated = 0
    for p in papers:
        if hasattr(p, "to_dict"):
            d = p.to_dict()
        elif isinstance(p, dict):
            d = p
        else:
            continue
        raw_id = str(d.get("arxiv_id") or "")
        cid = _canon_id(raw_id)
        if not cid:
            continue
        if cid in by_id:
            row = by_id[cid]
            row["last_seen"] = now
            try:
                row["times_seen"] = str(int(row.get("times_seen") or "1") + 1)
            except ValueError:
                row["times_seen"] = "2"
            if query:
                row["query"] = query
            if notes_path:
                row["notes_path"] = notes_path
            if d.get("title"):
                row["title"] = str(d.get("title") or "")[:300]
            updated += 1
        else:
            by_id[cid] = {
                "arxiv_id": cid,
                "title": str(d.get("title") or "")[:300],
                "first_seen": now,
                "last_seen": now,
                "query": query,
                "notes_path": notes_path,
                "times_seen": "1",
                "abs_url": str(d.get("abs_url") or f"https://arxiv.org/abs/{cid}"),
            }
            added += 1

    paths = save_rows(list(by_id.values()), workdir)
    return {
        "added": added,
        "updated": updated,
        "total": len(by_id),
        "paths": [str(p) for p in paths],
    }


def _last_seen_map(workdir: Optional[Path] = None) -> dict[str, str]:
    """canonical_id → last_seen ISO string (empty if unknown)."""
    out: dict[str, str] = {}
    for r in load_rows(workdir):
        cid = _canon_id(r.get("arxiv_id") or "")
        if cid:
            out[cid] = str(r.get("last_seen") or r.get("first_seen") or "")
    return out


def _paper_id(p: Any) -> str:
    if hasattr(p, "arxiv_id"):
        return _canon_id(str(p.arxiv_id))
    if isinstance(p, dict):
        return _canon_id(str(p.get("arxiv_id") or p.get("id") or ""))
    return ""


def search_new(
    query: str,
    *,
    max_results: int = 10,
    workdir: Optional[Path] = None,
    overfetch: int = 5,
    allow_reuse_if_short: bool = True,
    reuse_policy: str = "lru",
) -> dict[str, Any]:
    """Search arXiv, prefer papers not yet in the ledger.

    Over-fetches then filters. If not enough new papers and
    ``allow_reuse_if_short``, pads with already-seen hits.

    ``reuse_policy``:
      - ``lru`` (default): when reusing, pick least-recently-seen first
        so REAL does not always remix the same top API hits
      - ``api``: keep arXiv API order for reused papers
    """
    want = max(1, int(max_results))
    fetch_n = min(50, max(want * overfetch, want))
    known = seen_ids(workdir)
    raw = arxiv_client.search(query, max_results=fetch_n)
    fresh, old = filter_new(raw, workdir, known=known)
    chosen = list(fresh[:want])
    reused: list[Any] = []
    if len(chosen) < want and allow_reuse_if_short:
        need = want - len(chosen)
        if (reuse_policy or "lru").lower() == "lru":
            last_map = _last_seen_map(workdir)
            old_sorted = sorted(
                old,
                key=lambda p: (last_map.get(_paper_id(p) or "", "9999"), _paper_id(p)),
            )
            reused = list(old_sorted[:need])
        else:
            reused = list(old[:need])
        chosen.extend(reused)
    return {
        "query": query,
        "requested": want,
        "fetched": len(raw),
        "new": len(fresh),
        "already_seen": len(old),
        "returned": len(chosen),
        "reused": len(reused),
        "reuse_policy": reuse_policy,
        "papers": chosen,
        "skipped_ids": [
            (p.arxiv_id if hasattr(p, "arxiv_id") else p.get("arxiv_id"))
            for p in old
        ][:30],
        "ledger_size": len(known),
    }


def search_fresh_diverse(
    queries: Sequence[str],
    *,
    max_results: int = 10,
    workdir: Optional[Path] = None,
    overfetch: int = 4,
    reuse_policy: str = "lru",
) -> dict[str, Any]:
    """Run several arXiv queries; prefer **new** papers across all of them.

    Used by REAL alive so one saturated query does not freeze research on a
    single paper seed. Falls back to LRU reuse only after exhausting new hits.
    """
    want = max(1, int(max_results))
    qs = [str(q).strip() for q in (queries or []) if str(q).strip()]
    if not qs:
        qs = ["multi agent LLM orchestration"]

    known = seen_ids(workdir)
    all_raw: list[Any] = []
    fresh_pool: list[Any] = []
    old_pool: list[Any] = []
    seen_ids_cycle: set[str] = set()
    per_query: list[dict[str, Any]] = []

    for q in qs:
        fetch_n = min(50, max(want * overfetch, want))
        try:
            raw = arxiv_client.search(q, max_results=fetch_n)
        except Exception as e:
            per_query.append({"query": q, "error": str(e)[:200]})
            continue
        all_raw.extend(raw)
        fresh, old = filter_new(raw, workdir, known=known)
        n_new = 0
        for p in fresh:
            pid = _paper_id(p)
            if not pid or pid in seen_ids_cycle:
                continue
            seen_ids_cycle.add(pid)
            fresh_pool.append(p)
            n_new += 1
        for p in old:
            pid = _paper_id(p)
            if not pid or pid in seen_ids_cycle:
                continue
            # keep for LRU later; mark so we don't double-count across queries
            old_pool.append(p)
        per_query.append(
            {
                "query": q,
                "fetched": len(raw),
                "new_in_query": n_new,
                "already_seen_in_query": len(old),
            }
        )

    chosen = list(fresh_pool[:want])
    reused: list[Any] = []
    if len(chosen) < want:
        need = want - len(chosen)
        # de-dupe old_pool
        old_dedup: list[Any] = []
        old_seen: set[str] = set(seen_ids_cycle)
        for p in old_pool:
            pid = _paper_id(p)
            if not pid or pid in old_seen:
                continue
            old_seen.add(pid)
            old_dedup.append(p)
        if (reuse_policy or "lru").lower() == "lru":
            last_map = _last_seen_map(workdir)
            old_dedup = sorted(
                old_dedup,
                key=lambda p: (last_map.get(_paper_id(p) or "", "9999"), _paper_id(p)),
            )
        reused = list(old_dedup[:need])
        chosen.extend(reused)

    return {
        "queries": qs,
        "requested": want,
        "fetched": len(all_raw),
        "new": len(fresh_pool),
        "already_seen": max(0, len(all_raw) - len(fresh_pool)),
        "returned": len(chosen),
        "reused": len(reused),
        "reuse_policy": reuse_policy,
        "papers": chosen,
        "per_query": per_query,
        "ledger_size": len(known),
        "mode": "fresh_diverse",
    }
