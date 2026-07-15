"""arXiv search + fetch (public API, no API key).

https://info.arxiv.org/help/api/user-manual.html
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
USER_AGENT = "nexus-core/0.5 (research; +https://github.com/VincentMarquez/nexus-core)"


@dataclass
class Paper:
    arxiv_id: str
    title: str
    summary: str
    authors: list[str] = field(default_factory=list)
    published: str = ""
    updated: str = ""
    categories: list[str] = field(default_factory=list)
    pdf_url: str = ""
    abs_url: str = ""
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def short(self) -> str:
        authors = ", ".join(self.authors[:4])
        if len(self.authors) > 4:
            authors += " et al."
        return (
            f"**{self.arxiv_id}** — {self.title}\n"
            f"  {authors}\n"
            f"  {self.abs_url}\n"
            f"  {self.summary[:280].strip()}…"
        )


def _http_get(url: str, timeout: float = 45.0, retries: int = 3) -> bytes:
    """GET with polite retries (arXiv rate-limits aggressively)."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # URLError, HTTPError, TimeoutError
            last_err = e
            # exponential backoff: 1s, 2s, 4s — respect 429
            wait = 1.0 * (2**attempt)
            if "429" in str(e) or "rate" in str(e).lower():
                wait = max(wait, 3.0 + attempt * 2)
            time.sleep(wait)
    raise RuntimeError(f"arXiv request failed after {retries} tries: {last_err}")

def normalize_arxiv_id(raw: str) -> str:
    s = (raw or "").strip()
    s = s.replace("https://arxiv.org/abs/", "").replace("http://arxiv.org/abs/", "")
    s = s.replace("https://arxiv.org/pdf/", "").replace("http://arxiv.org/pdf/", "")
    s = s.replace(".pdf", "")
    # old style arXiv:hep-th/9901001
    s = s.replace("arXiv:", "").replace("arxiv:", "")
    return s.strip()


def search(
    query: str,
    *,
    max_results: int = 8,
    sort_by: str = "relevance",
    sort_order: str = "descending",
    start: int = 0,
) -> list[Paper]:
    """Search arXiv. Query uses arXiv query syntax, e.g. 'all:transformer attention'."""
    q = (query or "").strip()
    if not q:
        return []
    # if looks like bare terms, wrap as all:
    if not re.search(r"(all|ti|au|abs|cat):", q):
        q = "all:" + q
    params = {
        "search_query": q,
        "start": str(start),
        "max_results": str(max(1, min(max_results, 50))),
        "sortBy": sort_by,  # relevance | lastUpdatedDate | submittedDate
        "sortOrder": sort_order,
    }
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    # be polite
    time.sleep(0.35)
    data = _http_get(url)
    return _parse_feed(data)


def get_paper(arxiv_id: str) -> Optional[Paper]:
    aid = normalize_arxiv_id(arxiv_id)
    if not aid:
        return None
    params = {
        "id_list": aid,
        "max_results": "1",
    }
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    time.sleep(0.35)
    papers = _parse_feed(_http_get(url))
    return papers[0] if papers else None


def _parse_feed(data: bytes) -> list[Paper]:
    root = ET.fromstring(data)
    out: list[Paper] = []
    for entry in root.findall(f"{ATOM}entry"):
        id_url = (entry.findtext(f"{ATOM}id") or "").strip()
        # http://arxiv.org/abs/2301.00001v1
        m = re.search(r"arxiv\.org/abs/([^/\s]+)", id_url)
        aid = m.group(1) if m else id_url.rsplit("/", 1)[-1]
        title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
        summary = " ".join((entry.findtext(f"{ATOM}summary") or "").split())
        authors = [
            (a.findtext(f"{ATOM}name") or "").strip()
            for a in entry.findall(f"{ATOM}author")
            if (a.findtext(f"{ATOM}name") or "").strip()
        ]
        published = (entry.findtext(f"{ATOM}published") or "")[:10]
        updated = (entry.findtext(f"{ATOM}updated") or "")[:10]
        cats = []
        for c in entry.findall(f"{ATOM}category"):
            term = c.attrib.get("term")
            if term:
                cats.append(term)
        pdf_url = ""
        abs_url = f"https://arxiv.org/abs/{aid}"
        for link in entry.findall(f"{ATOM}link"):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href") or ""
            if link.attrib.get("rel") == "alternate":
                abs_url = link.attrib.get("href") or abs_url
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{aid}.pdf"
        comment = entry.findtext(f"{ARXIV}comment") or ""
        out.append(
            Paper(
                arxiv_id=aid,
                title=title,
                summary=summary,
                authors=authors,
                published=published,
                updated=updated,
                categories=cats,
                pdf_url=pdf_url,
                abs_url=abs_url,
                comment=comment.strip(),
            )
        )
    return out


def download_pdf(paper: Paper, dest_dir: Path) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", paper.arxiv_id)
    path = dest_dir / f"{safe}.pdf"
    if path.exists() and path.stat().st_size > 1000:
        return path
    time.sleep(0.5)
    data = _http_get(paper.pdf_url, timeout=120)
    path.write_bytes(data)
    return path


def save_paper_json(paper: Paper, dest_dir: Path) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", paper.arxiv_id)
    path = dest_dir / f"{safe}.json"
    path.write_text(json.dumps(paper.to_dict(), indent=2), encoding="utf-8")
    return path


def save_abstract_md(paper: Paper, dest_dir: Path) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", paper.arxiv_id)
    path = dest_dir / f"{safe}.md"
    body = (
        f"# {paper.title}\n\n"
        f"- **arXiv:** [{paper.arxiv_id}]({paper.abs_url})\n"
        f"- **PDF:** {paper.pdf_url}\n"
        f"- **Authors:** {', '.join(paper.authors)}\n"
        f"- **Published:** {paper.published}\n"
        f"- **Categories:** {', '.join(paper.categories)}\n\n"
        f"## Abstract\n\n{paper.summary}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path
