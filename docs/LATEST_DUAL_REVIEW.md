# Research brief — GitHub (≥★) + arXiv → implement

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
- local clone: `.nexus_workspaces/scout_repos/wshobson__agents`
- url: https://github.com/wshobson/agents

Port **patterns**, not the whole tree. Prefer tests + small modules.

## builderz-labs/mission-control (score 15.0)
- idea=7.0 skill=8.0
- A self-hosted SQLite-backed AI agent control plane with task governance, spend tracking, Docker/CLI/MCP/TUI surfaces, and strong quality gates—useful operational scaffolding to reuse when building multi-agent systems, though alpha and somewhat overlapping with existing observability tools.
- local clone: `.nexus_workspaces/scout_repos/builderz-labs__mission-control`
- url: https://github.com/builderz-labs/mission-control

Port **patterns**, not the whole tree. Prefer tests + small modules.

## SolaceLabs/solace-agent-mesh (score 15.0)
- idea=7.0 skill=8.0
- Event-driven multi-agent framework on Solace messaging and Google ADK is strong for enterprise agent meshes, with solid packaging, CVE-aware pins, and broad tests, but Solace coupling limits reuse outside that stack.
- local clone: `.nexus_workspaces/scout_repos/SolaceLabs__solace-agent-mesh`
- url: https://github.com/SolaceLabs/solace-agent-mesh

Port **patterns**, not the whole tree. Prefer tests + small modules.

## Combined engineering goal

```
Improve this repository by adopting useful patterns from these local clones (do not follow or star anyone; do not vendor entire upstream trees). Keep tests green; small scoped changes only. Sources:
- From wshobson/agents (.nexus_workspaces/scout_repos/wshobson__agents): A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/commands, with multi-harness adapters, validation, and tests so teams can reuse production agentic building blocks across Claude Code, Codex, Cursor, OpenCode, Gemini, and Copilot.
- From builderz-labs/mission-control (.nexus_workspaces/scout_repos/builderz-labs__mission-control): A self-hosted SQLite-backed AI agent control plane with task governance, spend tracking, Docker/CLI/MCP/TUI surfaces, and strong quality gates—useful operational scaffolding to reuse when building multi-agent systems, though alpha and somewhat overlapping with existing observability tools.
- From SolaceLabs/solace-agent-mesh (.nexus_workspaces/scout_repos/SolaceLabs__solace-agent-mesh): Event-driven multi-agent framework on Solace messaging and Google ADK is strong for enterprise agent meshes, with solid packaging, CVE-aware pins, and broad tests, but Solace coupling limits reuse outside that stack.
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

Source note: `.nexus_state/arxiv_improve/improve-rx-8ef609d240.md`  
Papers read: 20/20  

| rank | score | effort | paper | target | concrete change |
|---|---|---|---|---|---|
| 1 | 8.0 | 6 | [SWE-Adept: An LLM-Based Agentic Framework for Deep Codebase ](https://arxiv.org/abs/2603.01327v2) | orchestrator | Implement a structured, multi-step planning phase in the orchestrator that explicitly sepa |
| 2 | 8.0 | 6 | [SWE-Exp: Experience-Driven Software Issue Resolution](https://arxiv.org/abs/2507.23361v2) | context_store, decision_ledger, cross_ru | Implement a structured 'Experience Bank' module to store abstracted successful/failed repa |
| 3 | 8.0 | 6 | [Are "Solved Issues" in SWE-bench Really Solved Correctly? An](https://arxiv.org/abs/2503.15223v2) | claim_verify | Integrate a differential testing module (like PatchDiff) into the `claim_verify` step to c |
| 4 | 8.0 | 6 | [SWE-Edit: Rethinking Code Editing for Efficient SWE-Agent](https://arxiv.org/abs/2604.26102v2) | context_store, multi_llm_agent, critique | Implement a dedicated 'Viewer' module that pre-processes and extracts only the most releva |
| 5 | 8.0 | 5 | [SWE-Bench++: A Framework for the Scalable Generation of Soft](https://arxiv.org/abs/2512.17419v1) | mine_eval_slice | Integrate a multi-language PR sourcing mechanism into the data ingestion pipeline, expandi |


## 4. Historical X input — quarantined

The July 17 model-mediated search output was not directly verified through
the official X API. Its post IDs, URLs, text, engagement data, and derived
themes were removed from this public brief and cannot be used as release
evidence or satisfy the research/publish gate.

Future model/web-search discoveries remain local under
`.nexus_state/x_research/` as unverified hypotheses. Only directly verified
official-API results are gate-eligible.



## Available skills (S12 factory + skillpacks)

Prefer these playbooks when implementing:

- `code-review-portfolio-slice` (skillpacks/activated) — `skillpacks/code-review-portfolio-slice`
- `durable-operator` (skillpacks/activated) — `skillpacks/durable-operator`
- `gemma-local-tools` (skillpacks/activated) — `skillpacks/gemma-local-tools`
- `swe-bar` (skillpacks/activated) — `skillpacks/swe-bar`
- `swe-pro-group-review` (skillpacks/activated) — `skillpacks/swe-pro-group-review`
- `code-review-portfolio-slice` (candidate/activated) — `.nexus_state/capability_factory/candidates/skills/code-review-portfolio-slice-9cc0a4b9`
## 5. Implementer charter

- Port **patterns** only (no whole-tree vendor).
- Prefer tests + small modules; keep pytest green.
- Prefer high-star + high paper-score items first.
- Use only directly verified X evidence in release-gated decisions.
- After apply, meta-review must re-check tests and residual gaps.
