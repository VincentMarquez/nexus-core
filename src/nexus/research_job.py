"""Research job: arXiv search → fetch → optional agent brief → report."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import arxiv_client


@dataclass
class ResearchJob:
    job_id: str
    query: str
    status: str = "pending"
    work_dir: str = ""
    papers: list[dict[str, Any]] = field(default_factory=list)
    brief: str = ""
    report_path: str = ""
    log: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchJobRunner:
    def __init__(
        self,
        *,
        workspace_root: Optional[Path] = None,
        state_dir: Optional[Path] = None,
        panel: Any = None,
    ):
        root = Path(__file__).resolve().parents[2]
        self.workspace_root = Path(workspace_root or root / ".nexus_workspaces" / "research")
        self.state_dir = Path(state_dir or root / ".nexus_state" / "research_jobs")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.panel = panel

    def _path(self, job_id: str) -> Path:
        return self.state_dir / f"{job_id}.json"

    def save(self, job: ResearchJob) -> None:
        self._path(job.job_id).write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")

    def run(
        self,
        query: str,
        *,
        max_results: int = 8,
        download_pdf: bool = False,
        with_brief: bool = True,
        job_id: Optional[str] = None,
    ) -> ResearchJob:
        jid = job_id or f"rx-{uuid.uuid4().hex[:10]}"
        work = self.workspace_root / jid
        work.mkdir(parents=True, exist_ok=True)
        job = ResearchJob(job_id=jid, query=query, status="running", work_dir=str(work))
        self.save(job)
        print(f"=== NEXUS research: {query!r} ===")
        print(f"  job: {jid}")
        print(f"  dir: {work}")

        try:
            papers = arxiv_client.search(query, max_results=max_results)
        except Exception as e:
            job.status = "failed"
            job.log.append({"event": "search_failed", "error": str(e)})
            self.save(job)
            print(f"  search failed: {e}")
            return job

        job.papers = [p.to_dict() for p in papers]
        job.log.append({"event": "found", "n": len(papers)})
        self.save(job)
        print(f"  found {len(papers)} papers")

        for p in papers:
            arxiv_client.save_abstract_md(p, work / "abstracts")
            arxiv_client.save_paper_json(p, work / "meta")
            print(f"  · {p.arxiv_id}: {p.title[:70]}")
            if download_pdf:
                try:
                    path = arxiv_client.download_pdf(p, work / "pdfs")
                    print(f"    pdf → {path.name}")
                except Exception as e:
                    print(f"    pdf failed: {e}")

        if with_brief:
            job.brief = self._brief(query, papers)
            (work / "BRIEF.md").write_text(job.brief, encoding="utf-8")

        report = self._report(job, papers)
        rpath = work / "NEXUS_RESEARCH_REPORT.md"
        rpath.write_text(report, encoding="utf-8")
        job.report_path = str(rpath)
        job.status = "completed"
        self.save(job)
        print(f"=== done: {job.status} ===")
        print(f"  report: {rpath}")
        return job

    def _brief(self, query: str, papers: list[arxiv_client.Paper]) -> str:
        # Prefer agent when panel online; else structured heuristic brief
        catalog = "\n\n".join(
            f"### {p.arxiv_id}: {p.title}\nAuthors: {', '.join(p.authors[:6])}\n"
            f"Cats: {', '.join(p.categories)}\nAbstract: {p.summary[:800]}"
            for p in papers
        )
        if self.panel is not None:
            try:
                from .steps import StepDef

                step = StepDef(
                    2,
                    "plan",
                    "Synthesize research brief from arXiv results",
                    "planner",
                    output_keys=("approach", "risks", "estimated_steps"),
                )
                prompt = (
                    f"You are a research analyst. Query: {query}\n\n"
                    f"Papers:\n{catalog[:12000]}\n\n"
                    f"Write a concise research brief as JSON keys approach (thematic synthesis), "
                    f"risks (gaps/limitations), estimated_steps (reading plan as number or short list string)."
                )
                agent = self.panel.resolve(step)
                out = self.panel.run(
                    agent,
                    prompt,
                    step=step,
                    task={"objective": query, "success_criteria": ["useful brief"]},
                )
                approach = out.get("approach") or out.get("_raw") or ""
                risks = out.get("risks") or ""
                steps = out.get("estimated_steps") or ""
                return (
                    f"# Research brief — {query}\n\n"
                    f"## Synthesis\n{approach}\n\n"
                    f"## Gaps / caveats\n{risks}\n\n"
                    f"## Reading plan\n{steps}\n"
                )
            except Exception as e:
                pass

        # Heuristic brief
        lines = [
            f"# Research brief — {query}",
            "",
            f"Found **{len(papers)}** arXiv hits (heuristic summary; no LLM).",
            "",
            "## Top papers",
        ]
        for i, p in enumerate(papers, 1):
            lines.append(f"{i}. **[{p.arxiv_id}]({p.abs_url})** — {p.title}")
            lines.append(f"   - {', '.join(p.authors[:3])}")
            lines.append(f"   - {p.summary[:220]}…")
            lines.append("")
        lines.append("## Next")
        lines.append("- Skim abstracts in `abstracts/`")
        lines.append("- `nexus arxiv get <id> --pdf` for full PDFs")
        lines.append("- Feed promising PDFs into your domain agents / notes")
        return "\n".join(lines)

    def _report(self, job: ResearchJob, papers: list[arxiv_client.Paper]) -> str:
        parts = [
            f"# NEXUS research report",
            "",
            f"- **Job:** `{job.job_id}`",
            f"- **Query:** {job.query}",
            f"- **Status:** {job.status}",
            f"- **Workdir:** `{job.work_dir}`",
            f"- **Hits:** {len(papers)}",
            "",
            "## Papers",
            "",
        ]
        for p in papers:
            parts.append(f"### [{p.arxiv_id}]({p.abs_url}) — {p.title}")
            parts.append(f"- Authors: {', '.join(p.authors)}")
            parts.append(f"- Published: {p.published} · Categories: {', '.join(p.categories)}")
            parts.append(f"- PDF: {p.pdf_url}")
            parts.append("")
            parts.append(p.summary)
            parts.append("")
        if job.brief:
            parts.append("## Brief")
            parts.append("")
            parts.append(job.brief)
        return "\n".join(parts)
