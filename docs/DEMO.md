# Demo guide

How to **run** and **show** NEXUS Core in under a few minutes.

## One command (full showcase)

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
make install
make demo-all
```

Or quick (skips scoreboard / optional gh):

```bash
make demo-all-quick
# same as: bash scripts/demo_showcase.sh --quick
```

### What `demo-all` proves

| # | Segment | Pass criteria |
|---|---------|----------------|
| 0 | Unit tests | pytest green |
| 1 | Crash → resume | Kill after step 3, resume to 10/10 + `DEMO_OK` artifact |
| 2 | Judge vs presence | Demo script exits 0; evidence required for success |
| 3 | Smoke evals | full_complete, kill_resume, autonomy_block, human_gate |
| 4 | Platforms mesh | `nexus platforms status` |
| 5 | Resilience | `nexus recovery network` + heartbeat dry-run |
| 6 | GitHub CLI | optional if `gh` logged in |
| 7 | Scoreboard | optional snapshot |

No API keys required for the core path.

## Classic short demos

```bash
make demo          # crash mid-task → resume (scripts/demo.sh)
make demo-judge    # presence ≠ success
make smoke         # evals/smoke.py
```

## Screen recording script (Show HN / X)

1. Terminal font large; theme dark.  
2. Run `make demo-all-quick` (or full).  
3. Narrate:  
   - “Agent jobs die at step 5 — we checkpoint after every step.”  
   - “Kill the process… resume… 10/10 and DEMO_OK on disk.”  
   - “Judge rejects vibes without artifacts.”  
4. Optional cut to browser: https://vincentmarquez.github.io/nexus-core/  
5. Optional: open an issue on the repo → community bot first reply (if Actions enabled).

## GitHub Actions

CI already runs **pytest + smoke** on every push (that is the automated demo gate).

```text
.github/workflows/ci.yml  →  pytest -q  +  python evals/smoke.py
```

`make demo-all` is the **human-facing** showcase (same proofs + more narrative).

## After the demo

```bash
./run                 # bus + dashboard + local LLM/agents
nexus platforms connect --force
# heartbeat (cloud poke when host dies):
# export NEXUS_HEARTBEAT_URL=https://hc-ping.com/UUID
# nexus heartbeat init --url "$NEXUS_HEARTBEAT_URL" && nexus heartbeat install-cron
```

Pitch line:

> Multi-agent tasks that **resume after a crash**, with a **judge that checks real success criteria** — not “the model said OK.”
