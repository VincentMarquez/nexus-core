# Short social post (draft)

Use with the demo video: [docs/assets/nexus-demo-reel.mp4](../assets/nexus-demo-reel.mp4)

---

### Post (single)

NEXUS Core runs an unattended multi-LLM self-improve loop:

• Research (GitHub + arXiv) → portfolio of ideas  
• Grok implements → multi-model critique panel → synthesis  
• Capability factory mints skills/tools from cycle lessons  
• Fail-closed publish when the judge or inputs fail  

Example cycle: ~2h54m alone · 10/10 ideas · tests green · publish gated by design  

```bash
git clone https://github.com/VincentMarquez/nexus-core.git
cd nexus-core && make install && make start && make demo-all-quick
```

https://github.com/VincentMarquez/nexus-core

---

### Thread (optional, 6 posts)

**1.** Unattended multi-LLM self-improve: product changes + skills from failures + fail-closed publish.  
[video] https://github.com/VincentMarquez/nexus-core  

**2.** Loop: research → portfolio → implement → Claude/GPT/Antigravity panel → Grok synthesis → tests → S08 publish gate.  

**3.** Capability factory: lessons (e.g. engine fail-open) → propose skill → fill SKILL.md → soft accept → activate into skillpacks/. Creation ≠ activation.  

**4.** Example numbers: ~2h54m wall clock · 10/10 ideas · multi-LLM panel · tests green · publish blocked when engine judge fails (intentional).  

**5.** Try it:

```bash
git clone https://github.com/VincentMarquez/nexus-core.git
cd nexus-core
make install && make start && make demo-all-quick
```

**6.** Architecture: Phase A governed self-edit spine + Phase B skills/tools factory (MCP + multi_llm --real). Stars and issues welcome.
