# Architecture figures

Publication-style diagrams for talks, papers, and the README.

| Figure | File | Description |
|--------|------|-------------|
| System overview | [assets/arch-overview.svg](assets/arch-overview.svg) | Surface → engine → panel/judge/memory → bus → backends |
| Multi-agent panel | [assets/arch-multi-agent.svg](assets/arch-multi-agent.svg) | ChatGPT, Codex, Claude, Grok, Gemini, local LLM → NEXUS roles |
| MCP mesh | [assets/arch-mcp-mesh.svg](assets/arch-mcp-mesh.svg) | AI apps + phone MCP → tunnel → machine |
| GLM-5.2 path | [assets/arch-glm-pipeline.svg](assets/arch-glm-pipeline.svg) | Cloud/small agents + colibrì GLM-5.2 |
| 10-step pipeline | [assets/arch-pipeline-10.svg](assets/arch-pipeline-10.svg) | Adversarial step flow |
| Crash → resume | [assets/demo-flow.svg](assets/demo-flow.svg) | Kill mid-task recovery |
| Demo animation | [assets/demo.gif](assets/demo.gif) | Short loop for social |

## Suggested paper caption style

> **Figure 1.** NEXUS Core multi-agent architecture. Heterogeneous vendors (cloud CLI subscriptions and local models) attach through an event bus and optional MCP connectors. A durable 10-step pipeline checkpoints after each step; a rubric judge scores success criteria against artifact evidence.

## Reuse

SVGs are plain vector graphics (MIT with the repo). Recolor freely for slides.
