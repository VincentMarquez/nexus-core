# SWE-bench Pro — multi-AI campaign (Claude · ChatGPT · Grok · Gemini · local)

**Target benchmark:** [SWE-bench Pro](https://labs.scale.com/leaderboard/swe_bench_pro_public) (Scale / industry “hard” SWE bar after Verified contamination).  
**Not** a homemade fixture suite. Official Docker eval is the only score that counts.

## Honest ceiling

| Reality | Note |
|---------|------|
| Top public scores on **Pro** are often **~20–50%+** depending on agent scaffold and date | Far below Verified “70%+” marketing |
| **100% on Pro is not currently realistic** for any public stack | Treat 100% as *aspiration*, score as **resolve rate on official harness** |
| Ensemble + multi-review can **raise** pass rate vs single model | Does not guarantee gold |

Your goal should be: **maximize official Pro resolve rate** with a human-like group review process, then publish the harness number.

---

## Who does what (your requested cast)

| Agent | Bus / CLI slot | Job on SWE-Pro |
|-------|----------------|----------------|
| **Claude** | `claude` | Plan, structure approach, **line-by-line review** pass 1 |
| **Grok** | `grok` | **Implement** patches, iterate on failing tests |
| **ChatGPT (Codex)** | `gpt` | Adversary / hard challenge, **review pass 2**, catch overfit |
| **Gemini** | `gemini` | **Web + arXiv** research (related bugs, papers, API docs) |
| **Local LLM** (Gemma NVFP / Ollama light) | `local` or Grok model `gemma4` | **Local files**, search repo, logs, prior patches under `.nexus_state` |
| **Official SWE-bench / Pro harness** | Docker | **Only** FAIL→PASS grader that counts |

### Group review (like a human PR group)

For every candidate patch:

1. **Grok** posts patch + summary  
2. **Claude** reviews line-by-line (correctness, edge cases, style)  
3. **Codex/ChatGPT** adversarial review (security, missed tests, “looks green but wrong”)  
4. **Gemini** searches web/arXiv for known pitfalls on that library/issue class  
5. **Local** greps the workspace for related fixes, prior failures, flaky tests  
6. **Grok** revises until **all reviewers** approve *or* tests prove pass  
7. **Harness** runs official Pro evaluation — not “we think it’s good”

Nexus tools for handoff: `send_to_workspace` / `read_workspace_chat` with distinct `agent` ids.

---

## Architecture

```text
                    ┌─ Claude  (plan + review L1)
Issue / Pro task ───┼─ Grok    (implement)
                    ├─ Codex   (adversary + review L2)
                    ├─ Gemini  (arXiv + web)
                    └─ Local   (files / logs / prior runs)
                              │
                              ▼
                     predictions.jsonl (patches)
                              │
                              ▼
              Official SWE-bench Pro Docker harness
                              │
                              ▼
                     resolve %  (leaderboard number)
```

Nexus **orchestrates** agents (bus + `run_task` + workspace).  
It does **not** replace the Pro harness.

---

## Install official eval (once)

```bash
# SWE-bench harness (Pro dataset per Scale / SWE-bench docs)
git clone https://github.com/SWE-bench/SWE-bench.git ~/SWE-bench
cd ~/SWE-bench && python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Agent scaffold often used on leaderboards
# git clone https://github.com/SWE-agent/mini-swe-agent.git ~/mini-swe-agent
```

Follow current Scale / SWE-bench docs for **SWE-bench Pro** dataset name and `run_evaluation` flags (they evolve).  
Always score with **their** Docker eval, not local guesses.

---

## Memory rules on Spark (GB10)

| Load | Approx |
|------|--------|
| NVFP4 Gemma | ~80–90 GiB |
| Multi-vendor CLIs (Claude/Codex/Grok/Gemini) | light (API/CLI) |
| Heavy Ollama + NVFP together | **Avoid** |

**Recommended for full multi-AI Pro campaign:**

1. Keep **NVFP** for local file agent *or* stop it and use **e2b-fast** for bus `local`.  
2. Always run **Claude + Codex + Grok + Gemini** as CLI bridges (not full model weights on GPU).  
3. Run **Docker Pro eval** when not mid heavy local inference.

---

## Start the multi-AI stack

```bash
cd ~/nexus-core

# Campaign script: roles + workspace brief + durable multi-vendor run
PYTHONPATH=src python3 scripts/swe_pro_multi_ai.py --once

# Or full-time multi-vendor (existing)
PYTHONPATH=src python3 scripts/multi_vendor_live.py --once
# PYTHONPATH=src python3 scripts/multi_vendor_live.py --watch --interval 600

# Gemini-oriented research for a topic (arXiv)
nexus research "SWE-bench Pro agent scaffolds test-time compute" --max 10 --no-brief
# or with brief if an LLM is free
```

Skill for reviewers: [`skillpacks/swe-pro-group-review/`](../skillpacks/swe-pro-group-review/).

---

## Path toward “as high as possible” on Pro

1. **Official harness only** for the score.  
2. **Ensemble implement:** Codex primary; Claude/Grok propose alternate patches on hard fails.  
3. **Group review gate** before accepting a prediction.  
4. **Gemini** feeds related papers/issues into workspace before implement.  
5. **Local** maintains a failure bank under `.nexus_state/swe_pro/` (what failed, why).  
6. **Best-of-N** only if allowed by the leaderboard rules you care about (some ban it).  
7. **Human** still merges / spot-checks — Pro is hard and noisy.

---

## Related

- [PLATFORMS.md](PLATFORMS.md) — mesh of CLIs  
- [LOCAL_LLM_TOOL_CALLING.md](LOCAL_LLM_TOOL_CALLING.md) — local tool cheat sheet  
- [ALIVE.md](ALIVE.md) — self-improve under a goal  
- `scripts/multi_vendor_live.py` — Claude + GPT + Grok + local durable runs  
- `scripts/swe_pro_multi_ai.py` — Pro-oriented campaign + Gemini research role  
