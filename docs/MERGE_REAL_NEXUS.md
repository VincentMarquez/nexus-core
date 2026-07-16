# Merge GitHub nexus-core with your real (lab) NEXUS

You have **two layers**. They are meant to work together, not replace each other.

| Layer | Path | Role |
|-------|------|------|
| **Product / OSS** | `~/nexus-core` → github.com/VincentMarquez/nexus-core | Durable engine, mine, alive, community bot, demos, CLI `nexus` |
| **Staging (safe)** | `~/nexus-core-staging` | Clean `origin/main` worktree — **test GitHub code here first** |
| **Lab / research** | `~/Desktop/research` (`run.py`, bridges, EEG, agents…) | Your full autonomous research machine |

## Safe pull of “best GitHub code” without breaking lab

**Never** copy GitHub over `Desktop/research` while ops services are running. Use:

```bash
# 1) Isolated eval (does NOT touch lab or rewrite product until green)
bash ~/nexus-core/scripts/safe_product_eval.sh --compare

# 2) Only if tests passed, fast-forward product tree to GitHub main
bash ~/nexus-core/scripts/safe_product_eval.sh --promote

# 3) Use product from lab WITHOUT merging lab code:
export PYTHONPATH=~/nexus-core/src
# or: pip install -e ~/nexus-core
nexus doctor
nexus task list
```

**What “best parts” means in practice**

| Use from product | Leave in lab |
|------------------|--------------|
| `nexus.engine`, `agents`, `persist`, `task` CLI | `run.py`, EEG, research bridges |
| multi-vendor live, alive/mine | domain experiments |
| fixtures + tests (CI green) | systemd ops units |

Staging worktree: `git worktree add ~/nexus-core-staging origin/main`

## Recommended merge model

```text
┌─────────────────────────────────────┐
│  Lab NEXUS  (Desktop/research)      │
│  run.py · bus · CLIs · Ollama       │  ← boots infrastructure you already use
└─────────────────┬───────────────────┘
                  │  same machine, same Ollama, same gh
                  ▼
┌─────────────────────────────────────┐
│  Product CLI  (nexus-core)          │
│  nexus alive / mine / demo / usage  │  ← self-improve + GitHub product loop
│  NEXUS_PROJECT_ROOT=…               │
└─────────────────────────────────────┘
```

**Do not** copy the whole research tree into GitHub. Instead:

1. Keep **lab** as the big workspace.  
2. Install **product** CLI from `nexus-core` (editable).  
3. Point product jobs at the tree you want improved:

| Goal | `NEXUS_PROJECT_ROOT` / `--path` |
|------|----------------------------------|
| Improve the open-source product | `~/nexus-core` (default) |
| Improve the lab research tree | `~/Desktop/research` |
| Improve another personal repo | path after `github init` |

## One-time integrate (this machine)

```bash
# 1) Product package (editable)
cd ~/nexus-core
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# 2) Put `nexus` on PATH (optional)
mkdir -p ~/.local/bin
ln -sfn ~/nexus-core/.venv/bin/nexus ~/.local/bin/nexus
# ensure ~/.local/bin is on PATH

# 3) Link lab → product helpers
bash ~/nexus-core/scripts/integrate_research.sh

# 4) Same Ollama / gh you already use
export OLLAMA_HOST=http://127.0.0.1:11434
export OLLAMA_MODEL=gemma4:26b   # or whatever you run
```

## Real self-improvement run (product tree)

```bash
cd ~/nexus-core
source .venv/bin/activate

# budget so it can't run away
nexus usage set --daily 500000 --monthly 8000000

# goal
nexus alive init \
  --goal "improve multi-agent durability, demos, and mine→apply path" \
  -q "multi agent durable orchestration" \
  --repo VincentMarquez/nexus-core

# REAL cycle (not dry-run): mine + score + USE + IMPROVE_OURS plan
# apply/self_approve stay OFF until you like the plan
nexus alive once

# inspect
less .nexus_state/repo_mine/IMPROVE_OURS.md
ls .nexus_workspaces/scout_repos/
nexus usage status

# when you want code changes:
nexus github mine improve-ours --apply --repo VincentMarquez/nexus-core
# then push from nexus-core if you accept the diff
```

## Real run targeting the **lab** tree

```bash
cd ~/nexus-core && source .venv/bin/activate
export NEXUS_PROJECT_ROOT=/path/to/home/Desktop/research

nexus alive init --path "$NEXUS_PROJECT_ROOT" \
  --goal "harden research stack: durability, dispatch, local LLM tools" \
  -q "multi agent research orchestration" \
  --repo VincentMarquez/nexus-core

nexus alive once --path "$NEXUS_PROJECT_ROOT"
# plans/clones land under Desktop/research/.nexus_state/ and .nexus_workspaces/
```

Lab still boots with `python3 run.py`. Product CLI is the **self-improve / GitHub product** control plane.

## Continuous “alive”

```bash
# foreground
nexus alive watch --interval 3600

# or cron
nexus schedule --mcp-http
crontab -e   # paste
```

## Safety

| Default | Meaning |
|---------|---------|
| `apply=false` | Plans only |
| `self_approve=false` | No auto `nexus do` |
| Token budget on | Throttle via `nexus usage set` |

Turn on self-approve only when you trust the loop:

```bash
nexus alive init --apply --self-approve --repo YOU/REPO
```
