# Show HN draft (copy/paste when ready)

**Title options** (pick one):

1. `Show HN: NEXUS Core – multi-agent tasks that resume after a crash`  
2. `Show HN: Crash-safe multi-agent runner with a real success-criteria judge`  
3. `Show HN: Agent pipelines that don’t lose work when you kill -9`

---

**Body:**

Hi HN —

I open-sourced **NEXUS Core**, a small Python (+ optional Node bus) system for multi-agent research/dev workflows.

**Pain:** multi-agent pipelines die mid-run, and “validators” often only check that *someone replied*, not that the work met the goal.

**What it does:**

1. **Durable 10-step pipeline** — checkpoint after each step; resume after interrupt  
2. **Rubric-style judge** — scores success criteria using artifact evidence  
3. **Cascade index** — shallow map before deep file thrash  
4. **Event bus + bridges** — wire CLI agents and **local LLMs** (Ollama) without baking keys into the repo  
5. **Autonomy default off** — no unattended token burn  

**60-second proof:**

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core && make install && make demo
```

You’ll see: run 3 steps → simulated crash → resume → completed 10/10.

Judge vs presence trap:

```bash
make demo-judge
```

Dashboard (optional):

```bash
make bus
# http://127.0.0.1:3099/dashboard
```

Repo: https://github.com/VincentMarquez/nexus-core  
Demo assets: crash→resume GIF in the README; optional screen recording welcome.

MIT. Feedback welcome — especially on the judge/resume design.

---

Launch discussion: https://github.com/VincentMarquez/nexus-core/discussions/4

## Posting checklist

- [ ] `make release-check` green on a clean clone  
- [ ] Demo GIF or 30s video linked (optional but huge)  
- [ ] You’re available for 2–4 hours after posting to reply  
- [ ] Don’t post the same text to 10 subreddits the same hour (looks like spam)  
