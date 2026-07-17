# Idea portfolio — implement ≥1 arXiv + ≥1 GitHub (max 10)

ts: 2026-07-17T05:22:19Z
count: 10
meta: {"min_arxiv": 1, "min_github": 1, "max_ideas": 10, "arxiv_pool": 20, "github_pool": 30, "novel_pool": 8, "arxiv_selected": 2, "github_selected": 2, "cross_selected": 6}

## Selected for implement

### 1. [arxiv] arxiv:2606.26649v1
- selected_as: `required_arxiv`
- score: 8.0  stars: —
- title: Autoformalization of Agent Instructions into Policy-as-Code
- concrete: Implement a Cedar Policy Language validation step within the consensus module before promoting a decision.
- url: https://arxiv.org/abs/2606.26649v1

### 2. [github] wshobson/agents
- selected_as: `required_github`
- score: 16.0  stars: 37933
- title: wshobson/agents
- concrete: Port pattern from wshobson/agents: A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/commands, with multi-harness adapters, validation, and tests so teams can reuse production agentic building blocks across Claude Code, Codex, Cursor, OpenCode, Gemini, and Copilot.
- url: https://github.com/wshobson/agents

### 3. [arxiv] arxiv:2512.11213v2
- selected_as: `diversity_arxiv`
- score: 8.0  stars: —
- title: FutureWeaver: Planning Test-Time Compute for Multi-Agent Systems with Modularized Collaboration
- concrete: Implement a budget-aware resource allocation module within the orchestrator that tracks and limits compute usage across agents.
- url: https://arxiv.org/abs/2512.11213v2

### 4. [cross_pattern] novel:arxiv:2512.11213v2+builderz-labs/mission-control
- selected_as: `cross_pattern`
- score: 9.015  stars: —
- title: Cross-pattern: control, plane, systems
- concrete: Novel hybrid: apply arXiv idea «Implement a budget-aware resource allocation module within the orchestrator that tracks and limits compute usage across » using structure/pattern from GitHub «builderz-labs/mission-control» «Port pattern from builderz-labs/mission-control: A self-hosted SQLite-backed AI agent control plane with task governance». Implement one small module + tests in nexus-core.
- url: https://arxiv.org/abs/2512.11213v2

### 5. [cross_pattern] novel:arxiv:2407.01476v4+wshobson/agents
- selected_as: `cross_pattern`
- score: 8.516  stars: —
- title: Cross-pattern: codex, commands, plane, planner
- concrete: Novel hybrid: apply arXiv idea «Implement a search-based planning module (e.g., A* or Beam Search) within the `orchestrator` to guide the `control_plane» using structure/pattern from GitHub «wshobson/agents» «Port pattern from wshobson/agents: A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/comm». Implement one small module + tests in nexus-core.
- url: https://arxiv.org/abs/2407.01476v4

### 6. [cross_pattern] novel:arxiv:2602.22953v2+wshobson/agents
- selected_as: `cross_pattern`
- score: 8.516  stars: —
- title: Cross-pattern: codex, commands, protocol, tool
- concrete: Novel hybrid: apply arXiv idea «Implement a standardized, unifying protocol layer for agent interactions, abstracting away specific tool-calling or CLI » using structure/pattern from GitHub «wshobson/agents» «Port pattern from wshobson/agents: A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/comm». Implement one small module + tests in nexus-core.
- url: https://arxiv.org/abs/2602.22953v2

### 7. [cross_pattern] novel:arxiv:2601.22129v2+wshobson/agents
- selected_as: `cross_pattern`
- score: 8.516  stars: —
- title: Cross-pattern: codex, commands, test, worker
- concrete: Novel hybrid: apply arXiv idea «Implement a mechanism in the orchestrator to cache and selectively replay intermediate states (e.g., directory contents,» using structure/pattern from GitHub «wshobson/agents» «Port pattern from wshobson/agents: A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/comm». Implement one small module + tests in nexus-core.
- url: https://arxiv.org/abs/2601.22129v2

### 8. [cross_pattern] novel:arxiv:2510.21903v2+wshobson/agents
- selected_as: `cross_pattern`
- score: 8.516  stars: —
- title: Cross-pattern: codex, commands, constraints, orchestrator
- concrete: Novel hybrid: apply arXiv idea «Implement a dedicated 'User Intent Model' module that processes interaction history and ambiguous instructions to genera» using structure/pattern from GitHub «wshobson/agents» «Port pattern from wshobson/agents: A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/comm». Implement one small module + tests in nexus-core.
- url: https://arxiv.org/abs/2510.21903v2

### 9. [cross_pattern] novel:arxiv:2606.26649v1+IBM/AssetOpsBench
- selected_as: `cross_pattern`
- score: 8.515  stars: —
- title: Cross-pattern: benchmark, plane, planner, work
- concrete: Novel hybrid: apply arXiv idea «Implement a Cedar Policy Language validation step within the consensus module before promoting a decision.» using structure/pattern from GitHub «IBM/AssetOpsBench» «Port pattern from IBM/AssetOpsBench: IBM’s Industry 4.0 multi-agent benchmark with domain MCP servers (IoT, FMSR, TSFM, ». Implement one small module + tests in nexus-core.
- url: https://arxiv.org/abs/2606.26649v1

### 10. [github] builderz-labs/mission-control
- selected_as: `fill`
- score: 15.0  stars: 5759
- title: builderz-labs/mission-control
- concrete: Port pattern from builderz-labs/mission-control: A self-hosted SQLite-backed AI agent control plane with task governance, spend tracking, Docker/CLI/MCP/TUI surfaces, and strong quality gates—useful operational scaffolding to reuse when building multi-agent systems, though alpha and somewhat overlapping with existing observability tools.
- url: https://github.com/builderz-labs/mission-control

## Cross-pattern novel candidates (spotted across papers + code)

- **novel:arxiv:2512.11213v2+builderz-labs/mission-control**: Novel hybrid: apply arXiv idea «Implement a budget-aware resource allocation module within the orchestrator that tracks and limits compute usage across » using structure/pattern from GitHub «builderz-labs/mission-control» «Port pattern from builderz-labs/mission-control: A self-hosted SQLite-backed AI agent control plane with task governance». Implement one small module + tests in nexus-core. (overlap: control, plane, systems)
- **novel:arxiv:2407.01476v4+wshobson/agents**: Novel hybrid: apply arXiv idea «Implement a search-based planning module (e.g., A* or Beam Search) within the `orchestrator` to guide the `control_plane» using structure/pattern from GitHub «wshobson/agents» «Port pattern from wshobson/agents: A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/comm». Implement one small module + tests in nexus-core. (overlap: codex, commands, plane, planner)
- **novel:arxiv:2602.22953v2+wshobson/agents**: Novel hybrid: apply arXiv idea «Implement a standardized, unifying protocol layer for agent interactions, abstracting away specific tool-calling or CLI » using structure/pattern from GitHub «wshobson/agents» «Port pattern from wshobson/agents: A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/comm». Implement one small module + tests in nexus-core. (overlap: codex, commands, protocol, tool)
- **novel:arxiv:2601.22129v2+wshobson/agents**: Novel hybrid: apply arXiv idea «Implement a mechanism in the orchestrator to cache and selectively replay intermediate states (e.g., directory contents,» using structure/pattern from GitHub «wshobson/agents» «Port pattern from wshobson/agents: A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/comm». Implement one small module + tests in nexus-core. (overlap: codex, commands, test, worker)
- **novel:arxiv:2510.21903v2+wshobson/agents**: Novel hybrid: apply arXiv idea «Implement a dedicated 'User Intent Model' module that processes interaction history and ambiguous instructions to genera» using structure/pattern from GitHub «wshobson/agents» «Port pattern from wshobson/agents: A single-source Markdown marketplace of 94 plugins and hundreds of agents/skills/comm». Implement one small module + tests in nexus-core. (overlap: codex, commands, constraints, orchestrator)
- **novel:arxiv:2606.26649v1+IBM/AssetOpsBench**: Novel hybrid: apply arXiv idea «Implement a Cedar Policy Language validation step within the consensus module before promoting a decision.» using structure/pattern from GitHub «IBM/AssetOpsBench» «Port pattern from IBM/AssetOpsBench: IBM’s Industry 4.0 multi-agent benchmark with domain MCP servers (IoT, FMSR, TSFM, ». Implement one small module + tests in nexus-core. (overlap: benchmark, plane, planner, work)
- **novel:arxiv:2606.26649v1+phodal/routa**: Novel hybrid: apply arXiv idea «Implement a Cedar Policy Language validation step within the consensus module before promoting a decision.» using structure/pattern from GitHub «phodal/routa» «Port pattern from phodal/routa: A polished monorepo multi-agent delivery board (Next.js, Tauri, Rust crates, CLI, MCP/AC». Implement one small module + tests in nexus-core. (overlap: plane, planner, workflow, workspace)
- **novel:arxiv:2606.26649v1+labsai/EDDI**: Novel hybrid: apply arXiv idea «Implement a Cedar Policy Language validation step within the consensus module before promoting a decision.» using structure/pattern from GitHub «labsai/EDDI» «Port pattern from labsai/EDDI: Config-driven multi-agent conversational middleware (Java/Quarkus) with routing, memory, ». Implement one small module + tests in nexus-core. (overlap: memory, orchestration, plane, planner)

## Policy

- REAL self-improve must implement **at least 1 arXiv** and **1 GitHub** idea.
- Cap **10** ideas per cycle.
- Prefer small modules + tests; fix_loop until green after each apply batch.

