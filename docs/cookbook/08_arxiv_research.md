# 08 — arXiv research jobs

**Goal:** Search arXiv, save abstracts, write a research brief/report.

## One-liners

```bash
nexus arxiv search "multi agent durable execution"
nexus arxiv get 1706.03762
nexus arxiv get 1706.03762 --pdf

nexus research "retrieval augmented generation evaluation"
nexus research "cat:cs.AI multi agent" --max 10 --pdf --heuristic-only
```

## What you get

Under `.nexus_workspaces/research/<job-id>/`:

- `abstracts/*.md` — title, authors, abstract  
- `meta/*.json` — structured metadata  
- `BRIEF.md` — agent or heuristic synthesis  
- `NEXUS_RESEARCH_REPORT.md` — full job report  
- `pdfs/` — if `--pdf`  

## Agent persona

See [Research agent persona](../agents/RESEARCH_ARXIV.md).

## Combine with GitHub jobs

```bash
nexus research "repository repair agents" --max 5
nexus do owner/repo --goal "implement the approach from the top paper, with tests"
```
