"""Self-improve facade — single import path for the unified cycle.

Product source of truth. Lab UI only *calls* into this stack via
``nexus alive`` CLI / product MCP (canonical_pipeline, github_mine).

See: docs/self-improve/README.md
"""

from __future__ import annotations

from nexus.alive import (
    AliveConfig,
    cycle_once,
    load_config,
    save_config,
    write_implement_summary,
)
from nexus.idea_portfolio import (
    build_portfolio,
    collect_arxiv_ideas,
    collect_github_ideas,
    cross_pattern_novel_ideas,
    implement_portfolio,
)
from nexus.unified_pipeline import (
    CANONICAL_FLOW,
    format_pipeline_summary,
    run_canonical,
)

__all__ = [
    "AliveConfig",
    "CANONICAL_FLOW",
    "build_portfolio",
    "collect_arxiv_ideas",
    "collect_github_ideas",
    "cross_pattern_novel_ideas",
    "cycle_once",
    "format_pipeline_summary",
    "implement_portfolio",
    "load_config",
    "run_canonical",
    "save_config",
    "write_implement_summary",
]
