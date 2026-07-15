# Architecture figures

Publication-style diagrams for talks, papers, and the README.

| Figure | File | Description |
|--------|------|-------------|
| **LLMs reason together (hero)** | [assets/arch-llms-reason-together.svg](assets/arch-llms-reason-together.svg) | Many models talk via bus — dialogue, challenge, meta-review, judge |
| **CLI + resume + judge** | [assets/arch-cli-judge-resume.svg](assets/arch-cli-judge-resume.svg) | Terminal CLIs, crash→resume, presence vs rubric judge |
| System overview | [assets/arch-overview.svg](assets/arch-overview.svg) | Surface → engine → panel/judge/memory → bus → backends |
| Multi-agent panel | [assets/arch-multi-agent.svg](assets/arch-multi-agent.svg) | ChatGPT, Codex, Claude, Grok, Gemini, local LLM → NEXUS roles |
| MCP mesh | [assets/arch-mcp-mesh.svg](assets/arch-mcp-mesh.svg) | AI apps + phone MCP → tunnel → machine |
| GLM-5.2 path | [assets/arch-glm-pipeline.svg](assets/arch-glm-pipeline.svg) | Cloud/small agents + colibrì GLM-5.2 |
| 10-step pipeline | [assets/arch-pipeline-10.svg](assets/arch-pipeline-10.svg) | Adversarial step flow |
| Crash → resume | [assets/demo-flow.svg](assets/demo-flow.svg) | Kill mid-task recovery |
| Demo animation | [assets/demo.gif](assets/demo.gif) | Short loop for social |

## Suggested paper caption style

> **Figure 1.** Heterogeneous LLMs (Claude, Codex/GPT, Gemini, Grok, local, GLM) attach through a shared event bus. They plan, challenge, implement, test, and meta-review together; durable checkpoints survive process death; a rubric judge scores success criteria against artifacts — not model self-report.

## Reuse

SVGs are plain vector graphics (MIT with the repo). Recolor freely for slides.
