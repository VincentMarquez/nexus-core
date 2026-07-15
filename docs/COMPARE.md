# How NEXUS Core compares

Honest positioning. NEXUS is **not** “an AI that does anything.”  
It is a **specialized multi-agent orchestration engine** for **reliable, long-running software tasks** — especially fixing and validating repositories.

**Elevator pitch:** durable multi-agent work on real codebases. Resume after crashes. Finish only when a rubric judge confirms success.

---

## Two pillars

1. **Reliability & verifiability** — durable checkpoints, rubric judge, adversarial pipeline  
2. **Practical software workflows** — GitHub-native jobs, local models/CLIs, observable bus  

---

## vs DIY scripts, chat agents, graph runners

| Concern | DIY scripts | Multi-agent chat (CrewAI / AutoGen-style) | Graph engines (LangGraph-style) | **NEXUS Core** |
|---------|-------------|-------------------------------|----------------------------------|----------------|
| Crash mid-task | Usually lost | Often lost | Checkpoints if you wire them | **Checkpoints by default** |
| “Did it work?” | Eyeball / print | Often “model replied” | Your nodes decide | **Rubric judge + evidence** |
| Multi-CLI / local LLM | Custom glue | Vendor SDKs | Custom | **Bus + file-drop bridges** |
| Autonomy loops | Easy to leave on | Common | Your choice | **Default OFF** |
| Repo-native job | Ad hoc | Conversation-centric | Graph-centric | **`nexus do owner/repo`** |
| Weight | Tiny | Medium–heavy | Medium | **Small core + optional bus** |
| LLM required? | No | Usually yes | Usually yes | **Heuristic-only mode exists** |

### LangGraph

- **Great at:** custom control flow, production graphs, tight integration with LangChain ecosystem.  
- **NEXUS bet:** opinionated **10-step software pipeline** + first-class **resume** + **rubric success** without building that policy yourself.  
- **Coexist:** use LangGraph for app-specific graphs; call NEXUS-style judges/checkpoints, or run NEXUS as the “task OS” around graph workers.

### CrewAI / AutoGen / similar

- **Great at:** role play, multi-agent conversation, rapid demos.  
- **NEXUS bet:** less “chat room,” more **job runner** — install/test/fix loops, kill-safe state, dashboard, GitHub URL entry.  
- **Coexist:** agents from those frameworks can sit behind the bus if you bridge them.

### Cursor (and other AI editors)

| Aspect | **Cursor** | **nexus-core** |
|--------|------------|----------------|
| What it is | AI-powered code **editor** | Multi-agent **execution / orchestration** engine |
| Main strength | Fast inline edit, Composer, chat | Long, reliable, **verifiable** workflows |
| Crash recovery | Editor state | First-class **checkpoint / resume** |
| Verification | You + model judgment | **Rubric judge + tests + meta-review** |
| Scope | One codebase in the IDE | Whole repos **autonomously** (e.g. `nexus do`) |
| Best at | Daily coding assistance | Autonomous repair, test, validation loops |

They are **complementary**, not competitors:

- **Cursor** helps *you* write and edit code.  
- **nexus-core** *runs agents* that must finish work on repositories over time.

---

## Unique (or unusually strong) features

| Feature | What it does | How distinctive |
|---------|--------------|-----------------|
| Durable execution | Resume after process death | Strong differentiator vs most agent demos |
| Rubric judge | Explicit criteria, not presence | One of the strongest product points |
| Adversarial pipeline | Challenge step before implement | Less common as a default |
| Hybrid / LLM-optional | Heuristics without a model | Rare in agent frameworks |
| Workspace MCP | Jail for external AI apps | Emerging; carefully scoped here |
| GitHub-native jobs | URL → clone → fix → report | Very practical |
| Event bus + dashboard | Live multi-agent visibility | Most systems are black boxes |

---

## What NEXUS is not (yet)

- **Not** a general research AGI or paper-reading platform (no built-in arXiv pipeline today).  
- **Not** a replacement for o1-style single-model reasoning — it **structures** models (or heuristics) in a process.  
- **Not** a full IDE.  
- **Not** claiming unbounded “does anything” autonomy.

---

## When to use NEXUS

- Overnight / long multi-step software jobs that **must survive crashes**  
- You need **success criteria**, not vibes  
- You want **GitHub URL → working checks** with a fix loop  
- Local Ollama / paid CLIs without baking secrets into the app  

## When something else may fit better

- Pure chat product UX → CrewAI / AutoGen / custom chat  
- Highly custom enterprise graphs → LangGraph  
- Single LLM call or IDE autocomplete → don’t need a 10-step engine  
- Interactive pair-programming in the editor → Cursor  

---

## GLM-5.2 / colibrì

| Layer | Project |
|-------|---------|
| Orchestration, resume, judge, dashboard, `nexus do` | **NEXUS Core** (this repo) |
| MoE inference, CUDA/disk, CACHE_ROUTE | **colibrì** + model snap |
| Lab numbers on GB10 | [glm52-gb10-colibri](https://github.com/VincentMarquez/glm52-gb10-colibri) |

See [GLM52.md](GLM52.md).
