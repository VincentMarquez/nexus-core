# Show HN draft

**Title**

Show HN: NEXUS – multi-LLM self-improve that mints skills from its own failures

**Text**

NEXUS Core is an open multi-agent stack where heterogeneous LLMs (Claude, GPT/Codex, Grok, Gemini, Ollama, …) share a bus, keep durable checkpoints, and treat success as rubric + tests—not “the model said OK.”

Self-improve path:

1. **Portfolio cycle** — arXiv + GitHub ideas (max 10); Grok implements; multi-LLM panel critiques; Grok synthesizes ACCEPT/SKIP/DEFER into product code.  
2. **Capability factory** — harvests lessons → skill/tool candidates → fill → soft accept → activate into skillpacks/ (creation ≠ activation).  
3. **MCP + multi_llm --real** — first-class read tools for lessons, scope, skill search, pack validate, code review.  
4. **Fail-closed publish** — can block push when engine/X health fails even if local tests are green.

Example unattended run: ~2h54m, 10/10 ideas, tests green, publish gated by design.

```bash
git clone https://github.com/VincentMarquez/nexus-core.git
cd nexus-core
make install && make start && make demo-all-quick
```

Not a SWE-bench leaderboard claim—the product is the **governed loop**.
