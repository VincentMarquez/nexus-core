# Self-improve flow

## DRY (`run self-improve`)

```text
budget → dry_run step → exit
```

No mine, no engine, no apply, no executive review.

## REAL (`run self-improve real`)

```text
1. Budget gate
2. GitHub ≥5K★ research INPUT (required)
3. arXiv research INPUT + paper rank
4. Dual brief
5. Canonical engine + ConsensusJudge
     goal → plan → challenge → implement → test
     → review → log → meta_review → approval → deliver
6. idea_portfolio  (≥1 arXiv + ≥1 GitHub, max 10, cross-pattern novels)
7. self_check → fix_loop until green (max fix_max_attempts)
8. implement_portfolio (worker per idea)
9. post_implement fix_loop if tests go red
10. meta_review + optional publish_github
11. EXECUTIVE REVIEW → docs/LATEST_IMPLEMENT_SUMMARY.md
```

## Judge verdicts

| Decision | Score | Effect |
|----------|-------|--------|
| pass | ≥ 0.7 | continue |
| revise | ≥ 0.45 | continue (noted) |
| fail | &lt; 0.45 | hard-stop on implement/test steps |

Review veto strings: `reject`, `veto`, `fail`, `deny`, `blocked`.

## Idea quotas (REAL)

| Rule | Default |
|------|---------|
| Min arXiv ideas | 1 |
| Min GitHub ideas | 1 |
| Max ideas / cycle | 10 |
| Cross-pattern scan | on |

Config: `.nexus_state/alive.json`  
keys: `implement_min_arxiv`, `implement_min_github`, `implement_max_ideas`, `cross_pattern_scan`, `fix_max_attempts`, `github_min_stars`.

## Lab vs product

| Command | What runs |
|---------|-----------|
| `run self-improve` / REAL | product `nexus alive once` |
| `run review pipeline` | product `unified_pipeline` (engine+judge, no alive push) |
| `mine github …` | product research input only |
| TOOL_CALL / Grok MCP | product MCP tools (`canonical_pipeline`, `github_mine`, …) |
