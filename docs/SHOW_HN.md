# Show HN draft (copy/paste when ready)

**Title options** (pick one):

1. `Show HN: Durable multi-agent jobs for real repos (resume + rubric judge)`  
2. `Show HN: nexus-core – agents that finish software work after kill -9`  
3. `Show HN: Paste a GitHub URL; agents fix/test with verifiable success`

---

**Body:**

Hi HN —

**nexus-core** is a specialized multi-agent **orchestration engine** for long-running software tasks — not a chat toy and not “an AI that does anything.”

**Pain:** agent workflows die mid-run and lose progress; “validators” often only check that a model replied, not that the work met the goal.

**Bet:**

1. **Durable execution** — checkpoint after each step; resume after `kill -9`  
2. **Rubric judge** — success = explicit criteria + artifacts, not vibes  
3. **Adversarial pipeline** — plan is challenged before implement  
4. **GitHub-native jobs** — `nexus do owner/repo --goal "fix failing tests"`  
5. **Hybrid** — Ollama/CLIs when present; heuristic-only when not  
6. **Autonomy default off** — no unattended token burn  

**Complementary to Cursor:** Cursor helps *you* edit. NEXUS *runs* overnight/repair loops on whole repos.

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
