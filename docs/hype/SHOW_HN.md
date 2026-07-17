# Show HN draft

**Title:**

Show HN: NEXUS – multi-LLM self-improve that mints skills from its own failures

**Body:**

NEXUS Core is an open multi-agent stack where heterogeneous LLMs (Claude, GPT/Codex, Grok, Gemini, Ollama, …) share a bus, keep durable checkpoints, and only “succeed” when a rubric judge + tests agree.

What’s new in the self-improve path:

1. **Portfolio REAL cycle** — ≥1 arXiv + ≥1 GitHub idea, max 10; Grok implements; multi-LLM panel critiques; Grok synthesizes ACCEPT/SKIP/DEFER into product code.  
2. **Capability factory** — harvests lessons (e.g. engine fail-open) → propose skill/tool candidates → fill procedure → soft accept → explicit activate into `skillpacks/` (creation ≠ activation).  
3. **MCP + multi_llm --real** — first-class read tools (`nexus_lesson_query`, `nexus_scope_check`, …).  
4. **Fail-closed publish** — bad engine/X health can block push even when local tests are green.

Latest unattended run (my machine): ~2h54m, 10/10 ideas, tests green, publish gated by design.

Demo:

```bash
git clone https://github.com/VincentMarquez/nexus-core.git
cd nexus-core
make install && make start && make demo-all-quick
```

Video + architecture: see README hero.

Not claiming SWE-bench SOTA — the product is the **governed loop**, not a leaderboard number.
