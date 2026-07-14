# How NEXUS Core compares

Friendly, factual positioning — not a dunk on other projects.

| Concern | DIY scripts | Multi-agent chat frameworks | Workflow engines (e.g. LangGraph-style graphs) | **NEXUS Core** |
|---------|-------------|-----------------------------|-----------------------------------------------|----------------|
| Crash mid-task | Usually lost | Often lost | Checkpoints if you wire them | **Checkpoints by default** |
| “Did it work?” | Eyeball / print | Often “model replied” | Your nodes decide | **Rubric judge + evidence** |
| Multi-CLI / local LLM | Custom glue | Vendor SDKs | Custom | **Bus + file-drop bridges** |
| Autonomy loops | Easy to leave on | Common | Your choice | **Default OFF** |
| Scope | Ad hoc | Conversation-centric | Graph-centric | **10-step research/dev pipeline** |
| Weight | Tiny | Medium–heavy | Medium | **Small core + optional bus** |

## When to use NEXUS Core

- You want a **named pipeline** (plan → challenge → implement → test → approve)  
- You care about **resume** and **success criteria**  
- You want **local models / CLIs** without baking keys into the app  

## When something else may fit better

- Pure chat UX product → agent chat frameworks  
- Highly custom graph control flow → LangGraph (you can still wrap NEXUS-style judges/checkpoints)  
- Single LLM call apps → don’t need a 10-step engine  

## Coexistence

NEXUS Core is complementary: use it as the **task OS** (durability + policy + judge) and plug model providers through the bus or your own runners.

### GLM-5.2 / colibrì

| Layer | Project |
|-------|---------|
| Orchestration, resume, judge, dashboard | **NEXUS Core** (this repo) |
| MoE inference, CUDA/disk, CACHE_ROUTE | **colibrì** + your model snap |
| Lab numbers on GB10 | [glm52-gb10-colibri](https://github.com/VincentMarquez/glm52-gb10-colibri) |

See [GLM52.md](GLM52.md).
