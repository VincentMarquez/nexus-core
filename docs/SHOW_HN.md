# Show HN draft (copy/paste when ready)

**Title options** (pick one):

1. `Show HN: Many LLMs talk together on hard problems (durable multi-agent panel)`  
2. `Show HN: nexus-core – Claude/Codex/Gemini/Grok/local reason as a team`  
3. `Show HN: Multi-LLM debate + resume after kill -9 + rubric judge`

---

**Body:**

Hi HN —

**nexus-core** is a multi-agent **orchestration engine** where **several LLMs talk and reason together** on hard work — not a single-chat wrapper and not “an AI that does anything.”

**Pain:** one model overconfidently “finishes”; multi-agent demos die mid-run; validators only check that *someone replied*.

**Bet:**

1. **Heterogeneous panel** — Claude / Codex / Gemini / Grok / Ollama / GLM on one bus, role-mapped  
2. **Adversary + meta-review** — models challenge each other before you ship  
3. **Durable execution** — checkpoint after each step; resume after `kill -9`  
4. **Rubric judge** — success = explicit criteria + artifacts, not vibes  
5. **Real jobs** — `nexus do` (GitHub), `nexus research` (arXiv), `nexus procure`  
6. **Autonomy default off** — no unattended token burn  

**Complementary to Cursor:** Cursor helps *you* edit. NEXUS runs a **panel** overnight on whole repos.

**60-second proof:**

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core && ./run && make demo
```

Crash → resume → completed. Judge vs presence:

```bash
make demo-judge
```

GitHub job:

```bash
./run owner/repo --goal "make tests pass"
```

MIT. Happy to take critique on the judge design and the `nexus do` allowlist.
