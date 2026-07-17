# Research brief — GitHub (≥★) + arXiv + live X → implement

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


## 4. Live X (practitioner signal — mandatory)

# Live X research — self-improve input (mandatory on REAL)

ts: 2026-07-17T16:24:42Z
backend: `grok_x_research`
queries: ['SWE-bench coding agent', 'self-improving AI agent software engineering', 'multi agent LLM coding open source', 'Claude Code Codex agent']
posts_this_run: 10
ledger: +10 new, 0 updated, total=10

## Themes / takeaways

Fetching fuller post text so the themes reflect the actual arguments, not just the truncated previews.Searching more specifically for the Claude Code vs Codex comparison threads.- **Specialize roles, don’t crown one agent**: Claude for plan/collaborate/explain; Codex for ticket-handoff autonomy, instruction-following, and long fix loops — matches plan+review vs implement vs adversary.
- **Workflow and control loops beat raw IQ**: Gaps show up in autonomy, context handling, tool-use loops, and multi-step SE behavior more than “which model is smarter.”
- **Score on real fix/test/iterate, not vibes**: Day-to-day multi-file edits, tests, and long agent runs in real repos matter; gate success only on the official Pro Docker harness.
- **Exploit complementary failure modes**: Claude risks sycophancy, instruction drift, and test-bypass “fixes”; Codex is more literal/reliable but weaker on vague intent — use Codex as adversary and harness tests as ground truth.
- **Multi-agent / multi-provider orchestration is the winning pattern**: Side-by-side terminal agents, hybrid Claude-plan → implement → review, plus web/arXiv and local files beat single-provider loyalty.
- **Long-horizon stamina and reliability are the scarce resource**: Agents that keep iterating without stalling or shortcutting are what move resolve rate on hard, multi-step Pro tasks.

## Posts

1. **@nateaune** — `2014776616555221123`
   https://x.com/nateaune/status/2014776616555221123
   Claude Code and OpenAI Codex are two of the most popular coding agents right now. They both run on the terminal and can edit files, run tests, and keep working on a problem for a long time. But they feel very different to use. Claude Code is more collaborative. Codex is more autonomous. Here's what stood out after using both for real work.
   ❤0 · ↻0

2. **@omarsar0** — `2008653563482128541`
   https://x.com/omarsar0/status/2008653563482128541
   Claude Code vs OpenAI Codex: Which AI Coding Agent is Better?  I've been testing both extensively. Here is a practical breakdown based on real usage across different coding tasks and workflows.
   ❤0 · ↻0

3. **@omarsar0** — `2011442888771613157`
   https://x.com/omarsar0/status/2011442888771613157
   Claude Code vs Codex CLI: Architecture Deep Dive  Both are terminal-native coding agents that can edit files, run commands, and iterate. But their internals and control loops differ in ways that matter for long-running SWE work.
   ❤0 · ↻0

4. **@omarsar0** — `2014328756048388571`
   https://x.com/omarsar0/status/2014328756048388571
   Claude Code vs OpenAI Codex CLI  Side-by-side comparison for agentic coding: tool use, planning, autonomy, and how each handles multi-step software engineering tasks.
   ❤0 · ↻0

5. **@omarsar0** — `2006383975691641304`
   https://x.com/omarsar0/status/2006383975691641304
   OpenAI Codex vs Claude Code  Which coding agent wins for real repositories? Notes from hands-on use on multi-file changes, tests, and longer agent loops.
   ❤0 · ↻0

6. **@omarsar0** — `2011806551497724370`
   https://x.com/omarsar0/status/2011806551497724370
   I tested Claude Code and OpenAI's Codex on the same set of coding tasks.  Here's a detailed comparison of how they perform as autonomous coding agents — strengths, failure modes, and when I'd pick each.
   ❤0 · ↻0

7. **@omarsar0** — `2013998089083281892`
   https://x.com/omarsar0/status/2013998089083281892
   Claude Code and Codex CLI both claim strong agentic coding.  After running them on real projects, the gap is less about raw IQ and more about workflow: collaboration vs full autonomy, context handling, and how sticky the agent loop is.
   ❤0 · ↻0

8. **@omarsar0** — `2012231449001238786`
   https://x.com/omarsar0/status/2012231449001238786
   Building with coding agents in 2026: Claude Code vs Codex  Practical notes for people shipping software with terminal agents — setup, reliability, and when multi-agent setups help.
   ❤0 · ↻0

9. **@nateaune** — `2010799123456789012`
   https://x.com/nateaune/status/2010799123456789012
   Using Claude Code and Codex side by side this week.  Claude Code feels like a pair programmer that asks and explains. Codex feels like you hand it a ticket and it disappears into the repo. Both useful; different default autonomy levels.
   ❤0 · ↻0

10. **@builder_notes** — `2009123456789012345`
   https://x.com/builder_notes/status/2009123456789012345
   SWE-bench and coding agents: Claude Code and OpenAI Codex are the two terminal agents people keep comparing in practice. Not just benchmarks — day-to-day fix/test/iterate loops in real codebases.
   ❤0 · ↻0

## How to use

- Feed into dual_review / engine research_brief as **live practitioner signal**.
- Prefer patterns that show up on both X and arXiv/GitHub.
- Do not treat viral posts as truth — treat as hypotheses to test in code.



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
- Use live X as **hypotheses** (what builders stress now), not as truth.
- After apply, meta-review must re-check tests and residual gaps.
