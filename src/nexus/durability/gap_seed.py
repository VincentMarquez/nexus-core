"""Auto-seed the principled-stop gap board from improve plans (P1.5).

Supervised *alive* loops only stop for ``gaps_closed`` when gaps are
registered. This module parses open backlog items from plan docs so the
board is not empty after a fresh checkout / plan refresh.

Primary sources (first hit wins per gap id; later sources fill missing):

1. ``docs/LATEST_IMPROVE_PLAN.md`` — status table + **Next open** section
2. ``docs/ALIVE_IMPROVEMENTS.md`` — latest ``next open:`` trail
3. ``.nexus_state/repo_mine/IMPROVE_OURS.md`` — optional ``## Backlog`` ids

Does not vendor zenith/mission-control; pattern only (gap board + backlog).

Schema: ``nexus.gap_seed/v1``
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from .stop import GapItem, PrincipledStop

SCHEMA = "nexus.gap_seed/v1"

# Status table: | id | description | status |
_TABLE_ROW = re.compile(
    r"^\|\s*\**([A-Za-z][A-Za-z0-9._+-]*)\**\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|?\s*$"
)
# Numbered next-open: 1. **P1.5** description  OR  1. description
_NEXT_NUM = re.compile(
    r"^\s*(?:\d+[\.\)]\s+|\-\s+(?:\*\*)?)(?:\*\*)?([A-Za-z][A-Za-z0-9._+-]*)?(?:\*\*)?\s*(.*)$"
)
# Inline trail only at line start / bullet (not mid-prose like "inline `next open:` trails")
_INLINE_NEXT = re.compile(
    r"(?i)^(?:[-*]\s+)?(?:\*\*)?next\s+open(?:\*\*)?\s*:\s*(.+)$"
)
# Bare backlog ids in backticks or bold: `P1.5` **P0.4**
_BARE_ID = re.compile(r"(?:`|\*\*)([A-Za-z][A-Za-z0-9._+-]*)(?:`|\*\*)")


def _normalize_id(raw: str) -> str:
    gid = (raw or "").strip().strip("*`").strip()
    # P1.5+ → P1.5 (plus means "and beyond", still one trackable gap family)
    if gid.endswith("+") and len(gid) > 1:
        gid = gid[:-1]
    return gid


def _clean_text(raw: str) -> str:
    """Strip light markdown noise from table cells / bullets."""
    s = (raw or "").strip()
    s = s.replace("**", "").replace("__", "")
    s = s.strip("`").strip()
    # drop trailing parenthetical code refs noise is ok to keep; just normalize space
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_done_status(status: str) -> bool:
    s = (status or "").strip().lower()
    if not s:
        return False
    if "open" in s and "done" not in s:
        return False
    return any(
        k in s
        for k in (
            "done",
            "landed",
            "complete",
            "closed",
            "shipped",
            "✓",
            "✔",
            "[x]",
        )
    )


def _is_open_status(status: str) -> bool:
    s = (status or "").strip().lower()
    if not s:
        return True
    if _is_done_status(s):
        return False
    return any(k in s for k in ("open", "todo", "pending", "later", "next", "wip", "partial"))


def parse_status_table_gaps(text: str, *, source: str = "") -> list[dict[str, Any]]:
    """Parse markdown status table rows into gap dicts (open + done)."""
    out: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        m = _TABLE_ROW.match(line.strip())
        if not m:
            continue
        gid = _normalize_id(m.group(1))
        # skip header-ish ids
        if gid.lower() in {"tier", "item", "id", "status", "pri", "priority", "---"}:
            continue
        if set(gid) <= {"-"}:
            continue
        desc = _clean_text(m.group(2))
        status = _clean_text(m.group(3))
        # Skip pure separator rows
        if set(desc.replace(" ", "")) <= {"-"}:
            continue
        open_ = _is_open_status(status)
        if not open_ and not _is_done_status(status):
            # Unknown status — treat as open only if not clearly done
            open_ = True
        out.append(
            {
                "id": gid,
                "description": desc,
                "open": open_,
                "status": status,
                "source": source or "status_table",
            }
        )
    return out


def parse_next_open_gaps(text: str, *, source: str = "") -> list[dict[str, Any]]:
    """Parse 'Next open' numbered/bullet lists and inline 'next open:' trails."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    lines = str(text or "").splitlines()
    in_next = False
    for line in lines:
        stripped = line.strip()
        low = stripped.lower()
        if re.match(r"^#{1,3}\s+next\s+open", low) or low.startswith("## next open"):
            in_next = True
            continue
        if in_next and stripped.startswith("#"):
            in_next = False
        # Inline trail (anywhere, e.g. ALIVE log)
        im = _INLINE_NEXT.search(stripped)
        if im:
            chunk = im.group(1)
            # split on · | ; or ,
            parts = re.split(r"\s*[·|;,]\s*", chunk)
            for i, part in enumerate(parts):
                part = part.strip().strip("-").strip()
                if not part:
                    continue
                # leading **P1.5** or bare P1.5
                m = re.match(
                    r"^(?:\*\*)?([A-Za-z][A-Za-z0-9._+-]*)(?:\*\*)?\s+(.*)$",
                    part,
                )
                if m and re.match(r"^[A-Za-z]+\d", m.group(1)):
                    gid = _normalize_id(m.group(1))
                    desc = _clean_text(m.group(2))
                else:
                    # id-only token
                    m2 = re.match(r"^(?:\*\*)?([A-Za-z][A-Za-z0-9._+-]*)(?:\*\*)?$", part)
                    if m2 and re.match(r"^[A-Za-z]+\d", m2.group(1)):
                        gid = _normalize_id(m2.group(1))
                        desc = ""
                    else:
                        gid = f"open-{len(seen) + 1}"
                        desc = _clean_text(part)
                if gid in seen:
                    continue
                seen.add(gid)
                out.append(
                    {
                        "id": gid,
                        "description": desc,
                        "open": True,
                        "status": "open",
                        "source": source or "next_open_inline",
                    }
                )
            continue
        if not in_next:
            continue
        if not stripped or stripped.startswith("```"):
            continue
        # Numbered / bullet under Next open
        m = re.match(
            r"^(?:\d+[\.\)]\s+|[-*]\s+)(?:\*\*)?([A-Za-z][A-Za-z0-9._+-]*)?(?:\*\*)?\s*(.*)$",
            stripped,
        )
        if not m:
            continue
        raw_id, rest = m.group(1), _clean_text(m.group(2) or "")
        if raw_id and re.match(r"^[A-Za-z]+\d", raw_id):
            gid = _normalize_id(raw_id)
            desc = rest
        else:
            # whole line after bullet is description
            full = _clean_text(f"{raw_id or ''} {rest}")
            gid = f"open-{len(seen) + 1}"
            desc = full
        if not desc and not raw_id:
            continue
        if gid in seen:
            continue
        seen.add(gid)
        out.append(
            {
                "id": gid,
                "description": desc,
                "open": True,
                "status": "open",
                "source": source or "next_open",
            }
        )
    return out


def parse_plan_gaps(text: str, *, source: str = "") -> list[dict[str, Any]]:
    """Combine status-table + next-open parsers; first id wins."""
    by_id: dict[str, dict[str, Any]] = {}
    for g in parse_status_table_gaps(text, source=source):
        by_id.setdefault(g["id"], g)
    for g in parse_next_open_gaps(text, source=source):
        by_id.setdefault(g["id"], g)
    return list(by_id.values())


def default_plan_paths(workdir: Path | str) -> list[Path]:
    root = Path(workdir)
    return [
        root / "docs" / "LATEST_IMPROVE_PLAN.md",
        root / "docs" / "ALIVE_IMPROVEMENTS.md",
        root / ".nexus_state" / "repo_mine" / "IMPROVE_OURS.md",
    ]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _last_inline_next_open(text: str, *, source: str = "") -> list[dict[str, Any]]:
    """Only the most recent ``next open:`` trail (ALIVE log is append-only)."""
    last_chunk = ""
    for line in str(text or "").splitlines():
        im = _INLINE_NEXT.search(line.strip())
        if im:
            last_chunk = im.group(0)
    if not last_chunk:
        return []
    return parse_next_open_gaps(last_chunk, source=source or "next_open_latest")


def collect_plan_gaps(
    workdir: Path | str,
    *,
    paths: Optional[list[Path]] = None,
) -> list[dict[str, Any]]:
    """Load and merge gaps from plan files under *workdir*.

    Prefer ``LATEST_IMPROVE_PLAN.md`` (status + next open). For the append-only
    ALIVE log, only the *latest* ``next open:`` trail is considered so historical
    P0.x items do not reappear as open gaps.
    """
    root = Path(workdir)
    by_id: dict[str, dict[str, Any]] = {}

    def _add(items: list[dict[str, Any]], *, prefer_new_open: bool = False) -> None:
        for g in items:
            gid = str(g.get("id") or "").strip()
            if not gid:
                continue
            if gid not in by_id:
                by_id[gid] = g
                continue
            # plan status "done" wins over later open noise
            if by_id[gid].get("open") is False:
                continue
            if prefer_new_open and g.get("open") is False:
                by_id[gid] = g

    if paths is not None:
        for p in paths:
            if not p.is_file():
                continue
            text = _read_text(p)
            rel = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
            _add(parse_plan_gaps(text, source=rel))
        return list(by_id.values())

    plan = root / "docs" / "LATEST_IMPROVE_PLAN.md"
    if plan.is_file():
        _add(parse_plan_gaps(_read_text(plan), source="docs/LATEST_IMPROVE_PLAN.md"))

    alive_log = root / "docs" / "ALIVE_IMPROVEMENTS.md"
    if alive_log.is_file():
        # latest trail only — fill ids not already decided by the plan
        _add(
            _last_inline_next_open(
                _read_text(alive_log),
                source="docs/ALIVE_IMPROVEMENTS.md#latest",
            )
        )

    ours = root / ".nexus_state" / "repo_mine" / "IMPROVE_OURS.md"
    if ours.is_file():
        _add(parse_plan_gaps(_read_text(ours), source=".nexus_state/repo_mine/IMPROVE_OURS.md"))

    return list(by_id.values())


def seed_gap_board(
    stopper: PrincipledStop,
    workdir: Path | str,
    *,
    paths: Optional[list[Path]] = None,
    reopen_closed: bool = False,
    close_done: bool = True,
) -> dict[str, Any]:
    """Upsert plan gaps onto *stopper*.

    - New open plan gaps are registered.
    - Already-closed board gaps stay closed unless *reopen_closed*.
    - Plan rows marked done can close matching open board gaps when *close_done*.

    Returns a ``nexus.gap_seed/v1`` summary (no secrets).
    """
    items = collect_plan_gaps(workdir, paths=paths)
    registered: list[str] = []
    closed: list[str] = []
    skipped: list[str] = []
    for g in items:
        gid = str(g.get("id") or "").strip()
        if not gid:
            continue
        desc = str(g.get("description") or "")
        want_open = bool(g.get("open", True))
        existing = stopper.gaps.get(gid)
        if existing is not None and not existing.open and not reopen_closed:
            # preserve operator progress
            if not want_open and close_done:
                skipped.append(gid)
                continue
            skipped.append(gid)
            continue
        if want_open:
            stopper.register_gap(gid, desc, evidence=f"seed:{g.get('source') or 'plan'}")
            registered.append(gid)
        else:
            if existing is None:
                # record as closed for audit trail
                stopper.register_gap(gid, desc, evidence=f"seed-done:{g.get('source') or 'plan'}")
                stopper.close_gap(gid, evidence=f"plan status: {g.get('status') or 'done'}")
                closed.append(gid)
            elif existing.open and close_done:
                stopper.close_gap(gid, evidence=f"plan status: {g.get('status') or 'done'}")
                closed.append(gid)
            else:
                skipped.append(gid)
    counts = stopper.gap_counts()
    return {
        "schema": SCHEMA,
        "n_plan": len(items),
        "registered": registered,
        "closed": closed,
        "skipped": skipped,
        "board": counts,
        "gaps": [g.to_dict() for g in stopper.gaps.values()],
    }


def board_snapshot(stopper: PrincipledStop) -> dict[str, Any]:
    """Operator-facing board view."""
    counts = stopper.gap_counts()
    return {
        "schema": SCHEMA,
        "counts": counts,
        "open": [g.to_dict() for g in stopper.open_gaps()],
        "closed": [g.to_dict() for g in stopper.closed_gaps()],
        "cycle": stopper.cycle,
        "no_progress_streak": stopper.no_progress_streak,
        "policy": stopper.policy.to_dict(),
    }
