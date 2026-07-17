"""paper_improve — read arXiv papers and rank them for codebase applicability.

Closes the gap where the alive arxiv step only produced reading lists:
this module *reads* each paper (title + full abstract), scores how much it
could improve the current code (local ollama LLM; offline heuristic
fallback), and emits grades in the same shape as ``mine_eval`` repo grades
(``repo_or_paper_id: "arxiv:<id>"``) plus a ranked PAPER_IMPROVE.md plan
with a concrete suggested change per paper.

Env:
  NEXUS_PAPER_IMPROVE=1        enable inside alive cycle (default off)
  NEXUS_PAPER_IMPROVE_MODEL    ollama model (default gemma4:e4b)
  NEXUS_OLLAMA_HOST            default http://localhost:11434
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from . import arxiv_client
from . import usage as usage_mod

_ID_RE = re.compile(r"arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)")
_TITLE_RE = re.compile(r"^\s*\d+\.\s+\*\*(.+?)\*\*\s+[—-]+\s+`([^`]+)`", re.M)


def _root(workdir: Optional[Path | str]) -> Path:
    return Path(workdir or ".").resolve()


def latest_note(root: Path) -> Optional[Path]:
    d = root / ".nexus_state" / "arxiv_improve"
    if not d.is_dir():
        return None
    notes = sorted(d.glob("improve-rx-*.md"), key=lambda p: p.stat().st_mtime)
    return notes[-1] if notes else None


def parse_note_papers(note_path: Path) -> list[dict[str, str]]:
    """Extract (id, title) pairs from an improve-rx note. Order preserved."""
    text = note_path.read_text(encoding="utf-8", errors="replace")
    papers: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _TITLE_RE.finditer(text):
        title, pid = m.group(1).strip(), m.group(2).strip()
        if pid not in seen:
            seen.add(pid)
            papers.append({"id": pid, "title": title})
    if not papers:  # fall back to bare links
        for m in _ID_RE.finditer(text):
            pid = m.group(1)
            if pid not in seen:
                seen.add(pid)
                papers.append({"id": pid, "title": pid})
    return papers


def _from_research_md(root: Path, pid: str) -> Optional[dict[str, Any]]:
    """Reuse abstracts already written by ResearchJobRunner (avoid re-hitting arXiv)."""
    research = root / ".nexus_workspaces" / "research"
    if not research.is_dir():
        return None
    # Prefer newest research job that has this abstract
    candidates = sorted(
        research.glob(f"rx-*/abstracts/{pid.replace('/', '_')}.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        candidates = sorted(
            research.glob(f"rx-*/abstracts/{pid}.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    if not candidates:
        return None
    text = candidates[0].read_text(encoding="utf-8", errors="replace")
    title_m = re.search(r"^#\s+(.+)$", text, re.M)
    authors_m = re.search(r"\*\*Authors:\*\*\s*(.+)$", text, re.M)
    abs_m = re.search(r"## Abstract\s*\n+(.+)", text, re.S)
    abstract = (abs_m.group(1).strip() if abs_m else "")
    return {
        "arxiv_id": pid,
        "id": pid,
        "title": title_m.group(1).strip() if title_m else pid,
        "summary": abstract,
        "abstract": abstract,
        "authors": authors_m.group(1).strip() if authors_m else "",
        "abs_url": f"https://arxiv.org/abs/{pid}",
        "pdf_url": f"https://arxiv.org/pdf/{pid}",
        "seeded_from": str(candidates[0]),
    }


def fetch_abstract(root: Path, pid: str, *, delay: float = 1.2) -> dict[str, Any]:
    """Fetch (and cache) one paper's metadata + abstract. Never raises."""
    cache = root / ".nexus_state" / "arxiv_improve" / "abstracts"
    cache.mkdir(parents=True, exist_ok=True)
    cpath = cache / f"{pid.replace('/', '_')}.json"
    if cpath.is_file():
        try:
            return json.loads(cpath.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Prefer local research-job abstracts — arXiv API often hangs mid-cycle.
    local = _from_research_md(root, pid)
    if local and (local.get("summary") or local.get("abstract")):
        try:
            cpath.write_text(json.dumps(local, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return local
    try:
        time.sleep(max(0.0, delay))  # be polite; arXiv 429s eager clients
        p = arxiv_client.get_paper(pid)
        if p is None:
            return {"id": pid, "error": "not found"}
        d = p.to_dict()
        d.setdefault("id", pid)
        cpath.write_text(json.dumps(d), encoding="utf-8")
        return d
    except Exception as e:  # network down, 429, parse error
        return {"id": pid, "error": str(e)[:200]}


def repo_capsule(root: Path, *, max_chars: int = 1400) -> str:
    """Short factual description of this codebase for applicability scoring."""
    bits: list[str] = [
        "nexus-core: a self-improving multi-agent LLM workspace.",
        "Goal: maximize official SWE-bench Pro resolve rate via multi-AI group review.",
        "Pipeline (alive cycle): mine GitHub repos -> arxiv research -> self_check "
        "(install/pytest/smoke) -> decision gate -> worker apply (grok CLI) -> "
        "promote verify -> publish to GitHub, all under a token budget.",
    ]
    src = root / "src" / "nexus"
    if src.is_dir():
        mods = sorted(p.stem for p in src.glob("*.py"))[:60]
        bits.append("Modules: " + ", ".join(mods))
    out = "\n".join(bits)
    return out[:max_chars]


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

_STOP = set(
    "a an the of for and or to in on with via is are we our this that using "
    "based new novel paper propose proposed show shows results method methods "
    "model models approach study large language".split()
)


def _terms(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", (text or "").lower())
        if w not in _STOP
    }


def score_paper_heuristic(paper: dict[str, Any], capsule: str) -> dict[str, Any]:
    """Deterministic offline fallback: term overlap between abstract and repo."""
    text = f"{paper.get('title','')} {paper.get('summary') or paper.get('abstract') or ''}"
    overlap = _terms(text) & _terms(capsule)
    score = round(min(10.0, len(overlap) * 0.9), 1)
    return {
        "applicability": score,
        "effort": 5,
        "target_area": "unknown",
        "concrete_change": "",
        "rationale": "heuristic term overlap: " + ", ".join(sorted(overlap)[:8]),
        "method": "heuristic",
    }


def score_paper_llm(
    paper: dict[str, Any],
    capsule: str,
    *,
    model: Optional[str] = None,
    host: Optional[str] = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Score one paper with a local ollama model. Falls back to heuristic."""
    model = model or os.environ.get("NEXUS_PAPER_IMPROVE_MODEL") or "gemma4:e4b"
    host = (host or os.environ.get("NEXUS_OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    abstract = (paper.get("summary") or paper.get("abstract") or "")[:2200]
    if not abstract:
        return score_paper_heuristic(paper, capsule)
    prompt = (
        "You review research papers for one specific codebase.\n\nCODEBASE:\n"
        + capsule
        + "\n\nPAPER TITLE: "
        + str(paper.get("title", ""))
        + "\nPAPER ABSTRACT:\n"
        + abstract
        + "\n\nAnswer with ONLY a JSON object, no prose, keys: "
        '{"applicability": 0-10 (how much a concrete idea from this paper could '
        "improve THIS codebase now), \"effort\": 1-10 (implementation effort), "
        '"target_area": "<module or subsystem>", '
        '"concrete_change": "<one specific, small change to make>", '
        '"rationale": "<one sentence>"}'
    )
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 220},
            "format": "json",
        }
    ).encode()
    try:
        req = urllib.request.Request(
            host + "/api/generate", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
        raw = payload.get("response") or "{}"
        data = json.loads(raw)
        out = {
            "applicability": float(data.get("applicability", 0) or 0),
            "effort": int(float(data.get("effort", 5) or 5)),
            "target_area": str(data.get("target_area", ""))[:120],
            "concrete_change": str(data.get("concrete_change", ""))[:400],
            "rationale": str(data.get("rationale", ""))[:300],
            "method": f"ollama:{model}",
        }
        out["applicability"] = max(0.0, min(10.0, out["applicability"]))
        return out
    except Exception as e:
        fb = score_paper_heuristic(paper, capsule)
        fb["rationale"] = f"llm unavailable ({str(e)[:80]}); " + fb["rationale"]
        return fb


def to_grade(paper: dict[str, Any], sc: dict[str, Any]) -> dict[str, Any]:
    """mine_eval-compatible grade for a paper."""
    pid = str(paper.get("id", ""))
    return {
        "repo_or_paper_id": f"arxiv:{pid}",
        "repo": f"arxiv:{pid}",
        "title": paper.get("title", pid),
        "score": round(float(sc.get("applicability", 0.0)), 1),
        "idea": round(float(sc.get("applicability", 0.0)), 1),
        "skill": max(0, 10 - int(sc.get("effort", 5))),
        "effort": int(sc.get("effort", 5)),
        "method": sc.get("method", "heuristic"),
        "pattern": sc.get("target_area", ""),
        "summary": sc.get("concrete_change", ""),
        "claims": [
            {
                "statement": sc.get("rationale", ""),
                "path": f"https://arxiv.org/abs/{pid}",
                "quote": "",
            }
        ],
    }


def step_paper_improve(
    workdir: Optional[Path | str] = None,
    *,
    note: Optional[Path | str] = None,
    use_llm: bool = True,
    limit: int = 20,
    top: int = 5,
    min_score: float = 6.0,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Read papers from the latest arxiv note, score, rank, and write a plan."""
    root = _root(workdir)
    note_path = Path(note) if note else latest_note(root)
    if note_path is None or not Path(note_path).is_file():
        return {"step": "paper_improve", "ok": False, "error": "no arxiv note found"}
    papers = parse_note_papers(Path(note_path))[: max(1, limit)]
    if not papers:
        return {"step": "paper_improve", "ok": False, "error": "no papers in note"}

    capsule = repo_capsule(root)
    grades: list[dict[str, Any]] = []
    read = 0
    for meta in papers:
        p = fetch_abstract(root, meta["id"])
        p.setdefault("title", meta["title"])
        if not p.get("error"):
            read += 1
        sc = (
            score_paper_llm(p, capsule, model=model)
            if use_llm
            else score_paper_heuristic(p, capsule)
        )
        grades.append(to_grade(p, sc))

    grades.sort(key=lambda g: float(g.get("score", 0)), reverse=True)
    out_dir = root / ".nexus_state" / "arxiv_improve"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    gpath = out_dir / f"paper_grades-{ts}.json"
    gpath.write_text(
        json.dumps({"schema": "nexus.paper_grades/v1", "grades": grades}, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# PAPER_IMPROVE — ranked applicability to nexus-core",
        "",
        f"Source note: `{note_path}`  ",
        f"Papers read: {read}/{len(papers)}  ",
        "",
        "| rank | score | effort | paper | target | concrete change |",
        "|---|---|---|---|---|---|",
    ]
    for i, g in enumerate(grades[: max(1, top)], 1):
        lines.append(
            f"| {i} | {g['score']} | {g.get('effort','?')} | "
            f"[{str(g.get('title',''))[:60]}](https://arxiv.org/abs/{str(g['repo_or_paper_id']).split(':',1)[-1]}) | "
            f"{str(g.get('pattern',''))[:40]} | {str(g.get('summary',''))[:90]} |"
        )
    mpath = out_dir / "PAPER_IMPROVE.md"
    mpath.write_text("\n".join(lines) + "\n", encoding="utf-8")

    try:
        usage_mod.record(
            250 * len(grades),
            source="paper_improve",
            label=f"read+score {len(grades)}",
            workdir=root,
            enforce=False,
        )
    except Exception:
        pass

    applicable = [g for g in grades if float(g.get("score", 0)) >= min_score]
    return {
        "step": "paper_improve",
        "ok": True,
        "papers": len(papers),
        "read": read,
        "applicable": len(applicable),
        "top": grades[0] if grades else None,
        "grades_path": str(gpath),
        "plan": str(mpath),
    }
