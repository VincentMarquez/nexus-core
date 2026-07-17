# Landscape (inspiration map)

Short reference for offline review. Not an implementation plan.

| System | Closest match to Nexus | Steal this | Not this |
|--------|------------------------|------------|----------|
| **AutoResearchClaw** ([repo](https://github.com/aiming-lab/AutoResearchClaw), [paper](https://arxiv.org/abs/2605.20025)) | Research + multi-agent + cross-run evolution | Failure → lesson → next-run injection | Full paper factory as product |
| **Darwin Gödel Machine** ([repo](https://github.com/jennyzzt/dgm), [paper](https://arxiv.org/abs/2505.22954)) | Self-edit coding agent + archive | Accept descendant only if eval improves | Drop research / lab |
| **SICA** ([paper](https://arxiv.org/abs/2504.15228)) | Self-edit + multi-criteria select | Cost/speed/bench in Accept() | Harness-only worldview |
| **EvoScientist** ([repo](https://github.com/EvoScientist/EvoScientist), [paper](https://arxiv.org/abs/2603.08127)) | Research + MCP + failed directions | Don’t re-explore dead ideas | Knowledge-only evolution |
| **CORAL** ([paper](https://arxiv.org/abs/2604.01658)) | Long-running multi-agent ops | Separate evaluator, isolation, resources | Optimization-problem only |
| **AgentOS** ([repo](https://github.com/iii-experimental/agentos)) | Bus + workers + MCP | Narrow seats, platform shape | Pre-1.0 as copy-paste |
| **Gas Town** ([repo](https://github.com/gastownhall/gastown)) | Live multi-model workspace | Worktrees, handoffs, merge discipline | No autonomous self-redesign |
| **GitHub Agentic Workflows** ([repo](https://github.com/github/gh-aw)) | Safe repo automation | Read vs write split, PR gates | No research portfolio |
| **Co-Scientist / AlphaEvolve** (DeepMind blogs) | Debate-rank / fitness mutation | Objective fitness before keep | Specialized discovery only |
| **SARSI** ([paper](https://arxiv.org/abs/2607.12254)) | Full governed RSI *design* | Contracts, Accept, external governance, foundry ideas | Treat as shipped code (it isn’t) |

## Nexus position (one line)

**Union of research intake + multi-LLM workspace + self-edit + publish**, currently weak on **cross-run memory** and **evidence-gated accept**.
