# Demo guide

How to **run** and **show** NEXUS Core in under a few minutes.

## One command (offline showcase)

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
make install
make demo-all
```

Or quick (skips the scoreboard and optional GitHub-auth status check):

```bash
make demo-all-quick
# same as: bash scripts/demo_showcase.sh --quick
```

### What the showcase proves

| # | Segment | Pass criteria |
|---|---------|----------------|
| 0 | Unit tests | pytest green |
| 1 | Crash → resume | Kill after step 3, resume to 10/10 + `DEMO_OK` artifact |
| 2 | Judge vs presence | Demo script exits 0; evidence required for success |
| 3 | Smoke evals | full_complete, kill_resume, autonomy_block, human_gate |
| 4 | Platform discovery | `nexus platforms status` reports what is available |
| 5 | Resilience | `nexus recovery network` + heartbeat dry-run |
| 6 | GitHub CLI | optional if `gh` logged in |
| 7 | Scoreboard | optional snapshot |

No API keys are required. The showcase uses deterministic local fixtures,
mock-style demo agents, and offline checks. It proves orchestration, checkpoint
recovery, judging, gates, and evidence handling. It does **not** evaluate a live
model/provider, run the real self-improvement loop, or exercise the capability
factory.

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
4. Optional cut to the local dashboard after `./run --no-pull`.
5. Optional: show `nexus task evidence <task_id>` for the audit export.

## GitHub Actions

CI already runs **pytest + smoke** on every push (that is the automated demo gate).

```text
.github/workflows/ci.yml  →  pytest -q  +  python evals/smoke.py
```

`make demo-all` is the **human-facing** showcase (same proofs + more narrative).

## After the demo

```bash
./run --no-pull       # bus + dashboard; prevents an automatic model download
nexus platforms status
nexus doctor
```

`./run` requires Node.js 18+. Installed providers must be authenticated
separately; missing model clients are represented by mock bridges.

Before executing a third-party repository with `nexus do`, read the
[repository safety notes](cookbook/06_github_do.md#safety). Before connecting
remote clients, read the transport and authentication notes in
[MCP setup](MCP_SETUP.md).

Pitch line:

> Multi-agent tasks that **resume after a crash**, with a **judge that checks real success criteria** — not “the model said OK.”
