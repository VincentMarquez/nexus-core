"""Bounded multi-source context pack — P1.4 formal stage.

Context engineering for multi-agent runs (arXiv 2508.08322 shape):
assemble **goal + grade + research notes + repo digests + journal + memory**
into a single hard-budgeted pack *before* apply / step prompts.

Why this exists:
- improve_apply already has a ``context_packed`` phase, but only echoed grade fields
- agents need research + mined-repo digests in-prompt without dumping whole trees
- operators need a portable ``nexus.context_pack/v1`` document to inspect/export

Patterns (shape only, no tree vendor):
- arXiv 2508.08322 — context engineering for multi-agent LLM assistants
- Denis2054/Context-Engineering-for-Multi-Agent-Systems — sectioned context
- phodal/routa — evidence/context board export
- Intelligent-Internet/zenith — gap/context before replan
- wshobson/agents — single-source digests as building blocks
- mission-control — operator inspect + export

Schema: ``nexus.context_pack/v1``
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .persist import atomic_write_json

SCHEMA = "nexus.context_pack/v1"

# Per-section character budgets (priority order for total-budget trim).
DEFAULT_SECTION_BUDGETS: dict[str, int] = {
    "goal": 800,
    "constraints": 600,
    "grade": 1200,
    "preference": 900,
    "research": 3000,
    "repo_digest": 3000,
    "journal": 1500,
    "memory": 1000,
    "prior": 1500,
    "notes": 800,
}

# Drop order when total exceeds budget (lowest priority first).
# Preference sits after grade so offline value-system bias (2602.04518) stays
# visible when research/repo digests get trimmed.
SECTION_PRIORITY: tuple[str, ...] = (
    "goal",
    "constraints",
    "grade",
    "preference",
    "research",
    "repo_digest",
    "journal",
    "prior",
    "memory",
    "notes",
)

DEFAULT_TOTAL_CHARS = 10_000  # ~2.5k tokens rough; keep prompts bounded
ELLIPSIS = "\n…[truncated]"


class ContextPackError(ValueError):
    """Invalid pack construction or missing required fields."""


# ---------------------------------------------------------------------------
# Truncation helpers
# ---------------------------------------------------------------------------


def truncate_chars(text: str, max_chars: int, *, ellipsis: str = ELLIPSIS) -> str:
    """Hard-cap *text* to *max_chars*, appending an ellipsis marker when cut."""
    if max_chars <= 0:
        return ""
    raw = str(text or "")
    if len(raw) <= max_chars:
        return raw
    # Keep room for ellipsis when possible
    keep = max(0, max_chars - len(ellipsis))
    if keep <= 0:
        return ellipsis[:max_chars]
    return raw[:keep] + ellipsis


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Offline, deterministic."""
    return max(0, (len(text) + 3) // 4)


# ---------------------------------------------------------------------------
# Section model
# ---------------------------------------------------------------------------


@dataclass
class ContextSection:
    """One named slice of a context pack."""

    name: str
    content: str
    max_chars: int = 0
    source: str = ""
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content,
            "chars": len(self.content),
            "max_chars": self.max_chars,
            "source": self.source,
            "truncated": self.truncated,
            "est_tokens": estimate_tokens(self.content),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextSection":
        return cls(
            name=str(data.get("name") or ""),
            content=str(data.get("content") or ""),
            max_chars=int(data.get("max_chars") or 0),
            source=str(data.get("source") or ""),
            truncated=bool(data.get("truncated")),
        )


def make_section(
    name: str,
    content: str,
    *,
    max_chars: Optional[int] = None,
    source: str = "",
    budgets: Optional[dict[str, int]] = None,
) -> ContextSection:
    """Build a section, applying the per-section budget."""
    budgets = budgets or DEFAULT_SECTION_BUDGETS
    cap = int(max_chars if max_chars is not None else budgets.get(name, 1000))
    raw = str(content or "").strip()
    truncated = len(raw) > cap
    body = truncate_chars(raw, cap) if truncated else raw
    return ContextSection(
        name=name,
        content=body,
        max_chars=cap,
        source=source,
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Source loaders (research notes + repo digests)
# ---------------------------------------------------------------------------


def _state_root(workdir: Path | str) -> Path:
    return Path(workdir).resolve() / ".nexus_state"


def latest_research_notes(
    workdir: Path | str,
    *,
    limit: int = 1,
    max_chars_each: int = 2500,
) -> list[dict[str, Any]]:
    """Load newest arXiv improve notes under ``.nexus_state/arxiv_improve/``."""
    root = _state_root(workdir) / "arxiv_improve"
    if not root.is_dir():
        return []
    files = sorted(
        root.glob("improve-rx-*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for path in files[: max(0, limit)]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body = truncate_chars(text, max_chars_each)
        out.append(
            {
                "path": str(path.relative_to(Path(workdir).resolve()))
                if path.is_relative_to(Path(workdir).resolve())
                else str(path),
                "name": path.name,
                "chars": len(body),
                "truncated": len(text) > max_chars_each,
                "excerpt": body,
            }
        )
    return out


# USE_LATEST: ## [owner/name](url) — score 16.0
_REPO_HEADER_USE = re.compile(
    r"^##\s+\[([^\]]+)\]\([^\)]*\)\s*[—\-]\s*score\s*([0-9.]+)",
    re.IGNORECASE,
)
# IMPROVE_OURS: ## owner/name (score 16.0)
_REPO_HEADER_OURS = re.compile(
    r"^##\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\s*\(\s*score\s*([0-9.]+)\s*\)",
    re.IGNORECASE,
)
# Generic: ## owner/name … score 16
_REPO_HEADER_LOOSE = re.compile(
    r"^##\s+\[?([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\]?.*?\bscore\s*[=:]?\s*([0-9.]+)",
    re.IGNORECASE,
)


def _parse_repo_header(first_line: str) -> Optional[tuple[str, float]]:
    """Return (repo, score) from a ## header line, or None if not a repo entry."""
    first = first_line.strip()
    for rx in (_REPO_HEADER_USE, _REPO_HEADER_OURS, _REPO_HEADER_LOOSE):
        m = rx.match(first)
        if m:
            repo = m.group(1).strip()
            try:
                score = float(m.group(2))
            except ValueError:
                score = 0.0
            return repo, score
    # Bare ## owner/name without score
    m2 = re.match(r"^##\s+\[?([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\]?", first)
    if m2:
        return m2.group(1).strip(), 0.0
    return None


def parse_improve_digest(
    text: str,
    *,
    min_score: float = 0.0,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Parse IMPROVE_OURS / USE_LATEST style markdown into repo entries."""
    raw = str(text or "")
    if not raw.strip():
        return []
    # Split on ## headers that look like repo entries
    parts = re.split(r"(?=^##\s+)", raw, flags=re.MULTILINE)
    entries: list[dict[str, Any]] = []
    for part in parts:
        part = part.strip()
        if not part.startswith("##"):
            continue
        first = part.splitlines()[0]
        low = first.lower()
        # Skip non-repo section headers
        if any(
            k in low
            for k in (
                "combined",
                "commands",
                "how to use",
                "status snapshot",
                "first apply",
                "next open",
                "non-goals",
                "improve *our*",
                "sources ",
            )
        ):
            continue
        parsed = _parse_repo_header(first)
        if not parsed:
            continue
        repo, score = parsed
        if score < min_score:
            continue
        # Pull first summary bullet if present
        summary = ""
        for line in part.splitlines()[1:]:
            s = line.strip()
            if s.startswith("- summary:") or s.startswith("- idea="):
                summary = s.lstrip("- ").strip()
                break
            if (
                s.startswith("- ")
                and "local" not in s.lower()
                and "url:" not in s.lower()
                and "clone" not in s.lower()
            ):
                if len(s) > 20:
                    summary = s.lstrip("- ").strip()
                    break
        entries.append(
            {
                "repo": repo,
                "score": score,
                "summary": summary[:500],
                "excerpt": truncate_chars(part, 600),
            }
        )
        if len(entries) >= limit:
            break
    # Prefer higher scores when mixed
    entries.sort(key=lambda e: (-float(e.get("score") or 0), e.get("repo") or ""))
    return entries[:limit]


def load_repo_digests(
    workdir: Path | str,
    *,
    min_score: float = 10.0,
    limit: int = 8,
    max_chars_total: int = 3000,
) -> list[dict[str, Any]]:
    """Load mined-repo digests from IMPROVE_OURS.md or USE_LATEST.md."""
    root = _state_root(workdir) / "repo_mine"
    candidates = [
        root / "IMPROVE_OURS.md",
        root / "USE_LATEST.md",
    ]
    text = ""
    source = ""
    for path in candidates:
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                source = path.name
                break
            except OSError:
                continue
    if not text:
        return []
    entries = parse_improve_digest(text, min_score=min_score, limit=limit)
    # Bound total excerpt size
    used = 0
    out: list[dict[str, Any]] = []
    for e in entries:
        excerpt = str(e.get("excerpt") or "")
        if used + len(excerpt) > max_chars_total and out:
            break
        e = dict(e)
        e["source"] = source
        out.append(e)
        used += len(excerpt)
    return out


# ---------------------------------------------------------------------------
# Pack builder
# ---------------------------------------------------------------------------


@dataclass
class ContextPack:
    """Assembled, budgeted multi-source context pack."""

    sections: list[ContextSection] = field(default_factory=list)
    total_budget: int = DEFAULT_TOTAL_CHARS
    meta: dict[str, Any] = field(default_factory=dict)
    schema: str = SCHEMA
    ts: float = field(default_factory=time.time)

    # -- metrics ------------------------------------------------------------

    @property
    def total_chars(self) -> int:
        return sum(len(s.content) for s in self.sections if s.content)

    @property
    def est_tokens(self) -> int:
        return estimate_tokens("".join(s.content for s in self.sections))

    def section(self, name: str) -> Optional[ContextSection]:
        for s in self.sections:
            if s.name == name:
                return s
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ts": self.ts,
            "total_budget": self.total_budget,
            "total_chars": self.total_chars,
            "est_tokens": self.est_tokens,
            "n_sections": len(self.sections),
            "sections": [s.to_dict() for s in self.sections],
            "meta": dict(self.meta),
            "truncated_sections": [s.name for s in self.sections if s.truncated],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextPack":
        secs = [
            ContextSection.from_dict(s)
            for s in (data.get("sections") or [])
            if isinstance(s, dict)
        ]
        return cls(
            sections=secs,
            total_budget=int(data.get("total_budget") or DEFAULT_TOTAL_CHARS),
            meta=dict(data.get("meta") or {}),
            schema=str(data.get("schema") or SCHEMA),
            ts=float(data.get("ts") or time.time()),
        )

    def prompt_block(self, *, heading: str = "# CONTEXT PACK (bounded)") -> str:
        """Render markdown suitable for agent prompt injection."""
        if not self.sections:
            return ""
        lines = [heading]
        for s in self.sections:
            if not s.content.strip():
                continue
            flag = " [truncated]" if s.truncated else ""
            lines.append(f"## {s.name}{flag}")
            if s.source:
                lines.append(f"_source: {s.source}_")
            lines.append(s.content.rstrip())
            lines.append("")
        lines.append(
            f"_pack: chars={self.total_chars}/{self.total_budget} "
            f"~tokens={self.est_tokens} schema={self.schema}_"
        )
        return "\n".join(lines).rstrip() + "\n"

    def summary_lines(self) -> list[str]:
        """Operator-facing short summary lines."""
        lines = [
            f"schema={self.schema}  chars={self.total_chars}/{self.total_budget}  "
            f"~tokens={self.est_tokens}  sections={len(self.sections)}"
        ]
        for s in self.sections:
            flag = "*" if s.truncated else " "
            lines.append(
                f"  {flag}{s.name:<14} chars={len(s.content):<5} "
                f"src={s.source or '-'}"
            )
        return lines


def _enforce_total_budget(
    sections: list[ContextSection],
    total_budget: int,
) -> list[ContextSection]:
    """Trim lowest-priority section tails until under total_budget."""
    if total_budget <= 0:
        return [ContextSection(name=s.name, content="", max_chars=0, source=s.source) for s in sections]
    # Work on a copy ordered by SECTION_PRIORITY
    by_name = {s.name: s for s in sections}
    order = [n for n in SECTION_PRIORITY if n in by_name]
    # Append unknown names last
    for s in sections:
        if s.name not in order:
            order.append(s.name)

    def total() -> int:
        return sum(len(by_name[n].content) for n in order if n in by_name)

    # Drop from the end of priority (notes/memory first) by shrinking content
    drop_order = list(reversed(order))
    while total() > total_budget and drop_order:
        name = drop_order[0]
        sec = by_name[name]
        over = total() - total_budget
        if over <= 0:
            break
        new_len = max(0, len(sec.content) - over)
        if new_len == 0:
            by_name[name] = ContextSection(
                name=sec.name,
                content="",
                max_chars=sec.max_chars,
                source=sec.source,
                truncated=True,
            )
            drop_order.pop(0)
            continue
        body = truncate_chars(sec.content, new_len)
        by_name[name] = ContextSection(
            name=sec.name,
            content=body,
            max_chars=sec.max_chars,
            source=sec.source,
            truncated=True,
        )
    return [by_name[n] for n in order if n in by_name and by_name[n].content]


def load_preference_section(
    workdir: Path | str,
    *,
    grade: Optional[dict[str, Any]] = None,
    limit: int = 8,
    require_pairs: bool = True,
) -> Optional[dict[str, Any]]:
    """Load offline preference brief (arXiv 2602.04518) for context packs.

    Returns ``None`` when *require_pairs* and the store is empty (saves budget).
    Includes optional focus boost for the grade's repo when present.
    """
    try:
        from .preference_pairs import (
            format_brief,
            preference_boost,
            preference_brief,
        )
    except Exception:
        return None
    brief = preference_brief(workdir, limit=limit)
    n_pairs = int(brief.get("n_pairs") or 0)
    if require_pairs and n_pairs <= 0:
        return None
    focus_repo = ""
    if grade and isinstance(grade, dict):
        focus_repo = str(grade.get("repo") or "").strip()
    focus_boost: Optional[float] = None
    if focus_repo:
        try:
            focus_boost = float(preference_boost(focus_repo, workdir))
        except Exception:
            focus_boost = None
    text = format_brief(brief)
    if focus_repo and focus_boost is not None:
        text = (
            text.rstrip()
            + f"\nfocus: {focus_repo}  preference_boost={focus_boost:+.2f}\n"
        )
    return {
        "brief": brief,
        "text": text,
        "n_pairs": n_pairs,
        "focus_repo": focus_repo or None,
        "focus_boost": focus_boost,
        "source": "preference_pairs",
    }


def build_context_pack(
    *,
    workdir: Path | str | None = None,
    objective: str = "",
    success_criteria: Optional[Iterable[str]] = None,
    constraints: Optional[Iterable[str]] = None,
    grade: Optional[dict[str, Any]] = None,
    journal_block: str = "",
    memory_hits: Optional[list[Any]] = None,
    prior: Optional[dict[str, Any]] = None,
    notes: str = "",
    include_research: bool = True,
    include_repo_digests: bool = True,
    include_preference: bool = True,
    research_limit: int = 1,
    repo_limit: int = 6,
    preference_limit: int = 8,
    min_score: float = 10.0,
    total_budget: int = DEFAULT_TOTAL_CHARS,
    section_budgets: Optional[dict[str, int]] = None,
    meta: Optional[dict[str, Any]] = None,
) -> ContextPack:
    """Assemble a hard-budgeted multi-source context pack.

    All sources are optional; empty sections are omitted. Research notes,
    repo digests, and offline preference briefs are read from ``workdir``
    when present (``include_preference`` defaults on; skips when store empty).
    """
    budgets = dict(DEFAULT_SECTION_BUDGETS)
    if section_budgets:
        budgets.update(section_budgets)
    wd = Path(workdir).resolve() if workdir else None
    sections: list[ContextSection] = []
    pref_meta: Optional[dict[str, Any]] = None

    # goal
    crit = list(success_criteria or [])
    goal_parts = []
    if objective:
        goal_parts.append(f"objective: {objective}")
    if crit:
        goal_parts.append("success_criteria:")
        for c in crit[:12]:
            goal_parts.append(f"  - {c}")
    if goal_parts:
        sections.append(
            make_section("goal", "\n".join(goal_parts), source="task", budgets=budgets)
        )

    # constraints / non-goals
    cons = list(constraints or [])
    if cons:
        body = "\n".join(f"- {c}" for c in cons[:20])
        sections.append(
            make_section("constraints", body, source="task", budgets=budgets)
        )

    # grade (mine eval / arxiv grade fixture)
    if grade:
        g_lines = [
            f"repo: {grade.get('repo') or '-'}",
            f"arxiv_id: {grade.get('arxiv_id') or '-'}",
            f"score: {grade.get('score')}  idea={grade.get('idea')}  skill={grade.get('skill')}",
            f"method: {grade.get('method') or '-'}",
            f"pattern: {grade.get('pattern') or '-'}",
        ]
        if grade.get("notes"):
            g_lines.append(f"notes: {str(grade.get('notes'))[:800]}")
        sections.append(
            make_section(
                "grade",
                "\n".join(g_lines),
                source="grade",
                budgets=budgets,
            )
        )

    # offline preference brief (arXiv 2602.04518 value systems)
    if include_preference and wd is not None:
        pref_meta = load_preference_section(
            wd,
            grade=grade,
            limit=preference_limit,
            require_pairs=True,
        )
        if pref_meta and pref_meta.get("text"):
            sections.append(
                make_section(
                    "preference",
                    str(pref_meta["text"]),
                    source="preference_pairs",
                    budgets=budgets,
                )
            )

    # research notes
    if include_research and wd is not None:
        notes_list = latest_research_notes(
            wd,
            limit=research_limit,
            max_chars_each=budgets.get("research", 3000),
        )
        if notes_list:
            chunks = []
            for n in notes_list:
                chunks.append(f"### {n.get('name')}\n{n.get('excerpt', '')}")
            sections.append(
                make_section(
                    "research",
                    "\n\n".join(chunks),
                    source="arxiv_improve",
                    budgets=budgets,
                )
            )

    # repo digests
    if include_repo_digests and wd is not None:
        digests = load_repo_digests(
            wd,
            min_score=min_score,
            limit=repo_limit,
            max_chars_total=budgets.get("repo_digest", 3000),
        )
        if digests:
            chunks = []
            for d in digests:
                head = f"### {d.get('repo')} (score={d.get('score')})"
                summary = d.get("summary") or ""
                body = summary or d.get("excerpt") or ""
                chunks.append(f"{head}\n{body}")
            src = digests[0].get("source") or "repo_mine"
            sections.append(
                make_section(
                    "repo_digest",
                    "\n\n".join(chunks),
                    source=str(src),
                    budgets=budgets,
                )
            )

    # journal
    if journal_block and str(journal_block).strip():
        sections.append(
            make_section(
                "journal",
                str(journal_block),
                source="task_journal",
                budgets=budgets,
            )
        )

    # memory hits
    if memory_hits:
        m_lines = []
        for i, hit in enumerate(memory_hits[:8]):
            if isinstance(hit, dict):
                txt = hit.get("text") or hit.get("content") or hit.get("value") or str(hit)
            else:
                txt = str(hit)
            m_lines.append(f"- [{i}] {truncate_chars(txt, 200)}")
        if m_lines:
            sections.append(
                make_section(
                    "memory",
                    "\n".join(m_lines),
                    source="memory",
                    budgets=budgets,
                )
            )

    # prior step outputs
    if prior:
        p_lines = []
        for k, v in list(prior.items())[:12]:
            p_lines.append(f"### step {k}\n{truncate_chars(str(v), 300)}")
        if p_lines:
            sections.append(
                make_section(
                    "prior",
                    "\n".join(p_lines),
                    source="task_outputs",
                    budgets=budgets,
                )
            )

    # free-form notes
    if notes and str(notes).strip():
        sections.append(
            make_section("notes", str(notes), source="caller", budgets=budgets)
        )

    # Enforce total budget
    sections = _enforce_total_budget(sections, total_budget)

    pack_meta = dict(meta or {})
    if wd is not None:
        pack_meta.setdefault("workdir", str(wd))
    pack_meta.setdefault("include_research", include_research)
    pack_meta.setdefault("include_repo_digests", include_repo_digests)
    pack_meta.setdefault("include_preference", include_preference)
    if pref_meta:
        pack_meta["preference_n_pairs"] = pref_meta.get("n_pairs")
        if pref_meta.get("focus_repo"):
            pack_meta["preference_focus"] = pref_meta.get("focus_repo")
            pack_meta["preference_focus_boost"] = pref_meta.get("focus_boost")

    return ContextPack(
        sections=sections,
        total_budget=total_budget,
        meta=pack_meta,
        ts=time.time(),
    )


def save_pack(path: Path | str, pack: ContextPack) -> Path:
    """Atomic write of pack JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, pack.to_dict())
    return p


def load_pack(path: Path | str) -> ContextPack:
    """Load pack JSON from disk."""
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ContextPackError("pack root must be an object")
    return ContextPack.from_dict(data)


def pack_from_grade(
    workdir: Path | str,
    grade: dict[str, Any],
    *,
    total_budget: int = DEFAULT_TOTAL_CHARS,
    notes: str = "",
    include_preference: bool = True,
) -> ContextPack:
    """Convenience: pack for improve-apply context_packed phase."""
    return build_context_pack(
        workdir=workdir,
        objective=str(grade.get("pattern") or grade.get("notes") or "improve-apply"),
        grade=grade,
        notes=notes or str(grade.get("notes") or ""),
        include_research=True,
        include_repo_digests=True,
        include_preference=include_preference,
        total_budget=total_budget,
        meta={
            "source": "improve_apply",
            "repo": grade.get("repo"),
            "arxiv_id": grade.get("arxiv_id"),
            "score": grade.get("score"),
        },
    )
