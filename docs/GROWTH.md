# How high-star GitHub repos actually grow

Research summary + a practical plan for NEXUS Core.  
**Stars measure attention, not correctness** — but attention funds contributors and users.

## What the research says

### 1. Growth is uneven: slow / moderate / fast / viral

Empirical work on thousands of GitHub projects (Borges et al., *Journal of Systems and Software*, 2018 — “What’s in a GitHub Star?”) finds:

- Stars often jump **right after public launch**, then stabilize.  
- **Releases accelerate** star growth.  
- **Organization-owned** repos tend to attract more stars than personal ones (on average).  
- Age alone is a weak predictor; **forks and activity** correlate more.  
- Growth patterns cluster into roughly **slow, moderate, fast, and viral**.  

**Implication:** plan for a strong launch window + regular releases, not “wait years for organic discovery.”

### 2. Social promotion is a first-class driver

The same line of research highlights **active promotion on social sites** as a major factor distinguishing high-growth projects from quiet ones.

**Implication:** shipping code without distribution is incomplete. Show HN, X, Reddit (niche, non-spam), blogs, and communities matter as much as features.

### 3. Stars are a noisy popularity proxy

Stars are widely used as a popularity signal, but:

- They are easy to game and easy to misread.  
- High precision as “engineered project” filters at low thresholds, poor recall.  
- Users also care about **docs, quality, and maintenance**.  

**Implication:** chase **users who run the demo and file issues**, not vanity alone. Stars follow usefulness + visibility.

### 4. Practitioner playbooks that repeatedly work

From open-source growth write-ups (e.g. teams that hit ~1k–10k+ stars):

| Lever | Why it works |
|-------|----------------|
| **Clear problem statement** | People star what they can explain in one sentence |
| **60-second demo** (GIF/video) | Multiplies click-through from social posts |
| **Show HN / launch posts** | Single spikes that seed the long tail |
| **Awesome-list PRs** (when relevant) | Evergreen discovery |
| **Respond to every early issue** | Converts traffic into community |
| **Release cadence** | Each release is a reason to reshare |
| **Solve your own pain loudly** | Authentic distribution (blog the war story) |
| **Integrations** | “Works with Ollama / LangGraph / …” rides existing demand |

Counterexamples that **don’t** scale: star-begging, spam, empty READMEs, abandoned issues.

### 5. The 10k pattern (qualitative)

Repos that cross **~10k stars** usually have at least two of:

1. **Category-defining utility** (many people need it weekly)  
2. **Viral distribution moments** (HN front page, influencer boost, big company adoption)  
3. **Time + consistency** (months to years of shipping and showing up)  

Lists and “awesome” resources sometimes hit 10k via **collaborative value** (hundreds of PRs). Tools hit 10k via **default status** in a workflow.

**For NEXUS Core:** the honest path is *category story* (“crash-safe multi-agent runner with a real judge”) × *demo that proves it* × *repeated distribution* — not a single tweet.

---

## NEXUS Core positioning (star-shaped)

**One-liner:**

> Multi-agent tasks that **resume after a crash**, with a **judge that checks real success criteria** — not “the model said OK.”

**Proof assets in this repo:**

| Asset | Command / path |
|-------|----------------|
| Crash → resume demo | `make demo` |
| Judge vs presence | `make demo-judge` |
| Full eval gate | `make smoke` |
| Bus + dashboard | `make bus` → `/dashboard` |
| Local LLM | `examples/ollama_local.md` |
| Launch post draft | `docs/SHOW_HN.md` |

---

## 90-day growth plan (executable)

### Days 1–7 — Foundation
- [x] Product README + badges  
- [x] One-command demo (`make demo`)  
- [x] CI green  
- [x] CONTRIBUTING / CoC / SECURITY  
- [ ] Record 30–45s screen capture of `make demo` → upload as `docs/assets/demo.gif` or YouTube  
- [ ] Pin repo on GitHub profile  

### Days 8–21 — Launch window
- [ ] Post **Show HN** using `docs/SHOW_HN.md` (weekday morning US time often better)  
- [ ] Share on X/LinkedIn with demo clip  
- [ ] One value post each: r/LocalLLaMA, relevant Discord (help-first, link once)  
- [ ] Tag `v0.2.0` GitHub Release with notes from CHANGELOG  

### Days 22–60 — Compounding
- [ ] Blog: “Why agent jobs die at step 5” → link repo  
- [ ] `good first issue` labels; merge doc PRs fast  
- [ ] Docker Compose polish; optional `pip` publish if API stabilizes  
- [ ] Awesome-list PR only where it clearly fits  

### Days 61–90 — Depth
- [ ] Integration people already use (LangGraph checkpointer adapter, etc.)  
- [ ] Public scoreboard of smoke reliability  
- [ ] Talk / short video walkthrough  

**Success metrics (better than raw stars):**

| Metric | Healthy early signal |
|--------|----------------------|
| Unique cloners / visitors (Insights) | Up week over week |
| Issues from people you don’t know | > 0 |
| Demo completions (anecdotal) | Strangers quote the resume story |
| Stars | Lagging indicator |

---

## Ethics

- Don’t buy stars or run bot farms.  
- Don’t spam communities.  
- Do ship value and invite critique.  

Stars earned from a working `make demo` compound; stars from noise don’t.
