"""S07 — Cross-run lessons (AutoResearchClaw / MetaClaw-shaped).

After a REAL cycle, harvest short structured lessons from failures/warnings.
Next dual_review injects top lessons so the pipeline does not re-learn the same
mistakes in free text only.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional, Sequence

SCHEMA = "nexus.cross_run_lessons/v1"
DEFAULT_MAX_AGE_DAYS = 30.0
DEFAULT_INJECT_LIMIT = 12


def _root(workdir: Path | str | None = None) -> Path:
    if workdir:
        return Path(workdir).resolve()
    import os

    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def lessons_path(root: Path | str | None = None) -> Path:
    d = _root(root) / ".nexus_state"
    d.mkdir(parents=True, exist_ok=True)
    return d / "cross_run_lessons.jsonl"


def append_lesson(
    root: Path | str | None,
    *,
    code: str,
    text: str,
    severity: str = "med",
    cycle_id: str = "",
    source: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> Path:
    path = lessons_path(root)
    row: dict[str, Any] = {
        "schema": SCHEMA,
        "ts": time.time(),
        "code": str(code or "generic")[:80],
        "text": str(text or "")[:500],
        "severity": str(severity or "med")[:20],
        "cycle_id": str(cycle_id or "")[:80],
        "source": str(source or "")[:80],
    }
    if extra:
        row["extra"] = extra
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return path


def load_lessons(
    root: Path | str | None = None,
    *,
    limit: int = 50,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    now: Optional[float] = None,
) -> list[dict[str, Any]]:
    path = lessons_path(root)
    if not path.is_file():
        return []
    now_t = float(now if now is not None else time.time())
    window = float(max_age_days) * 86400.0
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines[-max(200, limit * 4) :]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not row.get("text"):
            continue
        try:
            ts = float(row.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if max_age_days > 0 and now_t - ts > window:
            continue
        rows.append(row)
    # prefer newest, de-dupe by code+text prefix
    rows.sort(key=lambda r: float(r.get("ts") or 0), reverse=True)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        key = f"{r.get('code')}|{str(r.get('text'))[:80]}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def format_lessons_block(
    lessons: Sequence[dict[str, Any]],
    *,
    limit: int = DEFAULT_INJECT_LIMIT,
) -> str:
    if not lessons:
        return ""
    lines = [
        "## Cross-run lessons (S07 — avoid repeating)",
        "",
        "These are durable lessons from prior REAL cycles. Treat as constraints:",
        "",
    ]
    for i, les in enumerate(list(lessons)[: max(1, limit)], 1):
        sev = les.get("severity") or "med"
        code = les.get("code") or "generic"
        text = (les.get("text") or "").replace("\n", " ")[:240]
        lines.append(f"{i}. **[{sev}]** `{code}` — {text}")
    lines.append("")
    return "\n".join(lines)


def harvest_lessons_from_report(
    root: Path | str | None,
    report: dict[str, Any],
    *,
    cycle_id: str = "",
) -> dict[str, Any]:
    """Scan cycle report steps/results; append lessons. Fail-open."""
    written = 0
    codes: list[str] = []
    try:
        steps = list(report.get("steps") or [])
    except Exception:
        return {"ok": False, "written": 0, "error": "bad report"}

    def _add(code: str, text: str, severity: str = "med", source: str = "") -> None:
        nonlocal written
        try:
            append_lesson(
                root,
                code=code,
                text=text,
                severity=severity,
                cycle_id=cycle_id or str(report.get("ts") or ""),
                source=source,
            )
            written += 1
            codes.append(code)
        except Exception:
            pass

    for step in steps:
        if not isinstance(step, dict):
            continue
        name = str(step.get("step") or "")

        if name == "x_live_input" and step.get("ok") is False:
            _add(
                "x_research_failed",
                f"Live X research failed: {step.get('error') or 'unknown'}",
                "med",
                name,
            )
        if name == "canonical_engine" and (
            step.get("ok") is False or step.get("error")
        ):
            _add(
                "engine_failed_open",
                "Canonical engine failed or errored; implement may have continued fail-open.",
                "high",
                name,
            )
        if name == "publish_github" and step.get("skipped"):
            _add(
                "publish_skipped",
                str(step.get("skipped"))[:240],
                "low",
                name,
            )
        if name == "implement" and isinstance(step.get("results"), list):
            for r in step["results"]:
                if not isinstance(r, dict):
                    continue
                rid = r.get("id") or "?"
                if not r.get("ok"):
                    _add(
                        "implement_failed",
                        f"Idea {rid} implement ok=false: {str(r.get('error') or '')[:160]}",
                        "high",
                        "implement",
                    )
                panel = r.get("panel_critique") if isinstance(r.get("panel_critique"), dict) else {}
                if panel.get("status") == "panel_round1_failed":
                    _add(
                        "panel_timeout_or_offline",
                        f"Panel failed for {rid}; synthesis skipped. Prefer longer timeouts / quorum.",
                        "med",
                        "panel",
                    )
                if panel.get("status") == "synthesis_reverted":
                    _add(
                        "synthesis_reverted",
                        f"Synthesis reverted for {rid}; kept Grok implement only.",
                        "med",
                        "panel",
                    )
                if r.get("cooldown_reuse"):
                    _add(
                        "cooldown_reuse",
                        f"Portfolio reused cooled idea {rid} — pool may be thin.",
                        "low",
                        "portfolio",
                    )
                ap = r.get("accept_predicate") if isinstance(r.get("accept_predicate"), dict) else {}
                if ap and ap.get("accept") is False:
                    reasons = ",".join(ap.get("reasons") or [])[:160]
                    _add(
                        "accept_rejected",
                        f"Accept predicate rejected {rid}: {reasons}",
                        "high",
                        "accept",
                    )

        # also nested results under applied blob
        if name == "implement" and isinstance(step.get("results"), list):
            pass

    # portfolio thrash heuristic: many wshobson-like repeats in ids (from results)
    return {"ok": True, "written": written, "codes": codes[:40]}


def inject_into_dual_brief(body: str, lessons_block: str) -> str:
    """Insert lessons section after title block if not already present."""
    if not lessons_block or "Cross-run lessons (S07" in body:
        return body
    # place after first heading block
    lines = body.splitlines()
    if not lines:
        return lessons_block + "\n" + body
    # insert after goal/pipeline header (~ first blank after line 5)
    insert_at = 1
    for i, ln in enumerate(lines[:30]):
        if ln.startswith("## 1."):
            insert_at = i
            break
    else:
        insert_at = min(8, len(lines))
    return "\n".join(lines[:insert_at] + ["", lessons_block.rstrip(), ""] + lines[insert_at:])
