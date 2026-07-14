# Video scripts (for 10k-path distribution)

Record with OBS, Loom, or phone-on-monitor. 1080p, large font terminal.

---

## Video A — Product demo (MUST, 45–60s)

**Title:** `NEXUS Core: multi-agent tasks that resume after a crash`  
**Upload:** YouTube (unlisted or public) + link in README  
**Goal:** strangers clone and star  

### Shot list

| Time | Screen | Say (approx) |
|------|--------|----------------|
| 0–5s | README one-liner | “Multi-agent jobs die mid-run. Here’s a fix.” |
| 5–15s | Terminal: `make demo` | “We run three steps and checkpoint.” |
| 15–25s | Highlight step 3/10 running | “Simulate a crash.” |
| 25–40s | Resume → 10/10 completed | “Resume from disk. Task finishes.” |
| 40–50s | `make demo-judge` | “Judges check real success criteria, not presence.” |
| 50–60s | GitHub URL | “MIT — github.com/VincentMarquez/nexus-core” |

### Terminal prep

```bash
cd ~/nexus-core
# big font, dark theme, clear history noise
clear
make install
make demo
make demo-judge
```

### Do / don’t

- Do: full-screen terminal, no password prompts  
- Don’t: show `.env`, API keys, personal home paths if avoidable  

---

## Video B — Lab setup story (OPTIONAL, 2–3 min)

**Title:** `Why I built NEXUS — multi-agent lab → open source core`  
**Goal:** authority + narrative (not install path)

### Shot list

| Time | Show | Say |
|------|------|-----|
| 0–20s | Architecture diagram (docs) | “I run multi-agent research workflows daily.” |
| 20–50s | Dashboard (synthetic tasks only) | “Tasks, agents, status — the ops surface.” |
| 50–90s | Bus + bridges concept | “CLI agents and local models over a bus.” |
| 90–120s | Cut to `make demo` | “The open-source core is the portable spine.” |
| 120–150s | Link nexus-core | “Start here if you want to run it yourself.” |

### Hard rules for Video B

- No medical/personal research content  
- No API keys or private chat logs  
- Blur emails / account names  
- End on the **public** repo  

---

## Where to post

1. YouTube → embed/link in README  
2. Show HN (`docs/SHOW_HN.md`) with Video A  
3. X/LinkedIn: 15s cut of crash→resume + link  
4. Optional: Discord/Reddit help-style post (one link, no spam)  
