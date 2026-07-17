# Dual review — GitHub (≥★) + arXiv → implement brief

Goal: Maximize official SWE-bench Pro resolve rate with multi-AI group review: Claude plan+review, Grok implement, Codex adversary, Gemini arXiv/web, local files. Score only via official Pro Docker harness. Aspiration toward highest SWE coding; 100% Pro not currently realistic for any public stack.
Pipeline: goal → plan → challenge → implement → test → review → log → meta_review → approval → deliver
github_min_stars: 5000

## 1. GitHub high-star review

# GitHub high-star review (≥5000★)

query_requested: `multi agent durable resume checkpoint`
query_used: `multi agent durable resume checkpoint`
fallback_used: False
found: 0



## 2. Improve-ours plan (from mined/scored repos)

# Improve *our* project from mined repos

Target workdir: `/path/to/nexus-core`
Sources (score ≥ 10.0):

## wshobson/agents (score 16.0)
- idea=8.0 skill=8.0
- A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/commands, with multi-harness adapters, validation, and tests so teams can reuse production agentic building blocks across Claude Code, Codex, Cursor, OpenCode, Gemini, and Copilot.
- local clone: `/path/to/nexus-core/.nexus_workspaces/scout_repos/wshobson__agents`
- url: https://github.com/wshobson/agents

Port **patterns**, not the whole tree. Prefer tests + small modules.

## builderz-labs/mission-control (score 15.0)
- idea=7.0 skill=8.0
- A self-hosted SQLite-backed AI agent control plane with task governance, spend tracking, Docker/CLI/MCP/TUI surfaces, and strong quality gates—useful operational scaffolding to reuse when building multi-agent systems, though alpha and somewhat overlapping with existing observability tools.
- local clone: `/path/to/nexus-core/.nexus_workspaces/scout_repos/builderz-labs__mission-control`
- url: https://github.com/builderz-labs/mission-control

Port **patterns**, not the whole tree. Prefer tests + small modules.

## SolaceLabs/solace-agent-mesh (score 15.0)
- idea=7.0 skill=8.0
- Event-driven multi-agent framework on Solace messaging and Google ADK is strong for enterprise agent meshes, with solid packaging, CVE-aware pins, and broad tests, but Solace coupling limits reuse outside that stack.
- local clone: `/path/to/nexus-core/.nexus_workspaces/scout_repos/SolaceLabs__solace-agent-mesh`
- url: https://github.com/SolaceLabs/solace-agent-mesh

Port **patterns**, not the whole tree. Prefer tests + small modules.

## Combined engineering goal

```
Improve this repository by adopting useful patterns from these local clones (do not follow or star anyone; do not vendor entire upstream trees). Keep tests green; small scoped changes only. Sources:
- From wshobson/agents (/path/to/nexus-core/.nexus_workspaces/scout_repos/wshobson__agents): A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/commands, with multi-harness adapters, validation, and tests so teams can reuse production agentic building blocks across Claude Code, Codex, Cursor, OpenCode, Gemini, and Copilot.
- From builderz-labs/mission-control (/path/to/nexus-core/.nexus_workspaces/scout_repos/builderz-labs__mission-control): A self-hosted SQLite-backed AI agent control plane with task governance, spend tracking, Docker/CLI/MCP/TUI surfaces, and strong quality gates—useful operational scaffolding to reuse when building multi-agent systems, though alpha and somewhat overlapping with existing observability tools.
- From SolaceLabs/solace-agent-mesh (/path/to/nexus-core/.nexus_workspaces/scout_repos/SolaceLabs__solace-agent-mesh): Event-driven multi-agent framework on Solace messaging and Google ADK is strong for enterprise agent meshes, with solid packaging, CVE-aware pins, and broad tests, but Solace coupling limits reuse outside that stack.
```

## Commands

```bash
# plan only (this file)
nexus github mine improve-ours --min-score 10.0
# hard apply with Grok (default worker=auto)
nexus github mine improve-ours --apply --worker grok
make demo-all-quick
```


## 3. arXiv paper ranking

# PAPER_IMPROVE — ranked applicability to nexus-core

Source note: `/path/to/nexus-core/.nexus_state/arxiv_improve/improve-rx-b8a6e0d93c.md`  
Papers read: 20/20  

| rank | score | effort | paper | target | concrete change |
|---|---|---|---|---|---|
| 1 | 8.0 | 6 | [Autoformalization of Agent Instructions into Policy-as-Code](https://arxiv.org/abs/2606.26649v1) | consensus, circuits, control_plane_plann | Implement a Cedar Policy Language validation step within the consensus module before promo |
| 2 | 8.0 | 6 | [FutureWeaver: Planning Test-Time Compute for Multi-Agent Sys](https://arxiv.org/abs/2512.11213v2) | orchestrator, control_plane_planner, dec | Implement a budget-aware resource allocation module within the orchestrator that tracks an |
| 3 | 8.0 | 6 | [Tree Search for Language Model Agents](https://arxiv.org/abs/2407.01476v4) | orchestrator, control_plane_planner | Implement a search-based planning module (e.g., A* or Beam Search) within the `orchestrato |
| 4 | 8.0 | 6 | [General Agent Evaluation](https://arxiv.org/abs/2602.22953v2) | multi_llm_agent | Implement a standardized, unifying protocol layer for agent interactions, abstracting away |
| 5 | 8.0 | 5 | [SWE-Replay: Efficient Test-Time Scaling for Software Enginee](https://arxiv.org/abs/2601.22129v2) | orchestrator, grok_worker | Implement a mechanism in the orchestrator to cache and selectively replay intermediate sta |


## 4. Implementer charter

- Port **patterns** only (no whole-tree vendor).
- Prefer tests + small modules; keep pytest green.
- Prefer high-star + high paper-score items first.
- After apply, meta-review must re-check tests and residual gaps.
