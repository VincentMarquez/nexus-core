# Latest arXiv improve notes (from alive cycle)

# arXiv improve — multi agent orchestration

Repo: `VincentMarquez/nexus-core`  
Research job: `rx-ad22656322`  
Status: `completed`

## Papers

1. **A Survey of Multi-Agent Deep Reinforcement Learning with Communication** — `2203.08975v2`  
   https://arxiv.org/abs/2203.08975v2
2. **A Methodology to Engineer and Validate Dynamic Multi-level Multi-agent Based Simulations** — `1311.5108v1`  
   https://arxiv.org/abs/1311.5108v1
3. **AOAD-MAT: Transformer-based multi-agent deep reinforcement learning model considering agents' order of action decisions** — `2510.13343v1`  
   https://arxiv.org/abs/2510.13343v1
4. **From Model-Based Screening to Data-Driven Surrogates: A Multi-Stage Workflow for Exploring Stochastic Agent-Based Models** — `2604.03350v1`  
   https://arxiv.org/abs/2604.03350v1

## Brief

# Research brief — multi agent orchestration

Found **4** arXiv hits (heuristic summary; no LLM).

## Top papers
1. **[2203.08975v2](https://arxiv.org/abs/2203.08975v2)** — A Survey of Multi-Agent Deep Reinforcement Learning with Communication
   - Changxi Zhu, Mehdi Dastani, Shihan Wang
   - Communication is an effective mechanism for coordinating the behaviors of multiple agents, broadening their views of the environment, and to support their collaborations. In the field of multi-agent deep reinforcement le…

2. **[1311.5108v1](https://arxiv.org/abs/1311.5108v1)** — A Methodology to Engineer and Validate Dynamic Multi-level Multi-agent Based Simulations
   - Jean-Baptiste Soyez, Gildas Morvan, Daniel Dupont
   - This article proposes a methodology to model and simulate complex systems, based on IRM4MLS, a generic agent-based meta-model able to deal with multi-level systems. This methodology permits the engineering of dynamic mul…

3. **[2510.13343v1](https://arxiv.org/abs/2510.13343v1)** — AOAD-MAT: Transformer-based multi-agent deep reinforcement learning model considering agents' order of action decisions
   - Shota Takayama, Katsuhide Fujita
   - Multi-agent reinforcement learning focuses on training the behaviors of multiple learning agents that coexist in a shared environment. Recently, MARL models, such as the Multi-Agent Transformer (MAT) and ACtion dEpendent…

4. **[2604.03350v1](https://arxiv.org/abs/2604.03350v1)** — From Model-Based Screening to Data-Driven Surrogates: A Multi-Stage Workflow for Exploring Stochastic Agent-Based Models
   - Paul Saves, Matthieu Mastio, Nicolas Verstaevel
   - Systematic exploration of Agent-Based Models (ABMs) is challenged by the curse of dimensionality and their inherent stochasticity. We present a multi-stage pipeline integrating the systematic design of experiments with m…

## Next
- Skim abstracts in `abstracts/`
- `nexus arxiv get <id> --pdf` for full PDFs
- Feed promising PDFs into your domain agents / notes

## Suggested next engineering goals

1. Map paper ideas to failing tests or missing features in this repo.
2. Open a scoped issue / PR with evidence (tests).
3. Re-run `nexus github loop <n>` after each change.

```bash
nexus research "multi agent orchestration" --max 4
nexus do VincentMarquez/nexus-core -g "apply insights from arXiv: multi agent orchestration; keep tests green"
nexus github loop <n> --force
```
