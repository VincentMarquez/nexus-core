# Developer path: Grok Build as the coding agent for NEXUS

This is the **developer path** for improving `nexus-core` itself: use **Grok Build** (xAI’s coding agent TUI + headless harness) as the primary implementer, while NEXUS remains the **orchestration / durability / multi-vendor bus**.

You already have Grok Build installed on this machine (`grok` → Grok Build TUI). NEXUS already drives it headlessly via `nexus.grok_worker`.

---

## What Grok Build is

| Piece | Role |
|-------|------|
| **TUI** | Interactive coding agent in the terminal (read/edit/run/search) |
| **Headless** | `grok -p "…"` for scripts, CI, and NEXUS workers |
| **Agent mode (ACP)** | `grok agent stdio` for IDE / custom clients |
| **Tools** | Shell, file edit, grep, web, subagents, MCP servers |
| **Config** | `~/.grok/config.toml` + project MCP (e.g. `nexus-workspace`) |

Local docs: `~/.grok/docs/user-guide/` (headless, agents, MCP, permissions, sessions).

**Complexity:** medium — treat it as a **reference harness** + production CLI, not something to re-implement from scratch.

---

## How NEXUS and Grok Build fit together

```text
┌──────────────────────────────────────────────────────────┐
│  YOU (developer)                                         │
│  • Interactive:  grok   (TUI in nexus-core)              │
│  • Scripted:     nexus alive / multi_vendor / mine       │
└────────────────────────────┬─────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
   Grok Build TUI      grok -p headless     Claude / Codex
   (deep coding)       (grade + hard apply) (bus bridges)
         │                   │                   │
         └───────────────────┼───────────────────┘
                             ▼
                    NEXUS hub (nexus-core)
                    · DurableEngine + task journal
                    · Multi-vendor AgentPanel + fallbacks
                    · MCP tools (nexus-workspace)
                    · Mine / alive / publish (tests green)
```

| Concern | Owner |
|---------|--------|
| Agentic edit loop, TUI, tool UX | **Grok Build** |
| Checkpoints, multi-agent roles, evidence, GitHub publish | **NEXUS** |
| Hard grade + hard self-improve apply | NEXUS → `grok_worker` → Grok Build headless |
| Plan / implement / challenge with several vendors | NEXUS bus (Claude / GPT / Grok) |

**Do not** replace NEXUS with Grok Build alone. Use Grok Build as the **best coding agent**, NEXUS as the **durable orchestration layer**.

---

## Use case for `nexus-core`

### 1) Day-to-day coding (interactive)

```bash
cd ~/nexus-core
# MCP tools for project jail + checks (if platforms connect was run)
nexus platforms connect --path .
grok
# in TUI: work on engine, tests, docs; MCP: nexus-workspace
```

### 2) Headless hard work (what alive/mine already do)

```bash
# Grade a digest (JSON schema, no tools)
# see nexus.grok_worker.grok_grade

# Hard improve with tools + always-approve
export NEXUS_GROK_MODEL=grok-4.5
grok -p "Implement X; keep pytest green" -m grok-4.5 \
  --max-turns 32 --always-approve --cwd ~/nexus-core
```

NEXUS wrappers:

| Function | File |
|----------|------|
| `grok_grade` | `src/nexus/grok_worker.py` |
| `grok_hard_improve` | same |
| Bus slot `grok` | `bridge/bridges/stdin_to_grok.py` + `cli.py` |
| Self-improve | `scripts/full_self_improve_cycle.py` |
| Multi-vendor | `scripts/multi_vendor_live.py` |

### 3) Reference patterns to study (not wholesale fork)

Study Grok Build’s *ideas* and map them into NEXUS:

| Grok Build concept | NEXUS analogue | Opportunity |
|--------------------|----------------|-------------|
| Agent turns / max-turns | step loop + budgets | Align `max_turns` with step timeouts |
| Permissions / always-approve | trust + human gate | Keep HITL for production; YOLO only in sandbox |
| Subagents | multi-role panel | Already multi-vendor; avoid nested explosion |
| Sessions / resume | DurableEngine journal | Prefer NEXUS resume over only Grok session |
| MCP servers | `nexus.mcp_server` | Keep one tool surface for all vendors |
| Worktrees | `worktree_apply` | Safe apply isolation |
| Headless JSON / schema | `grok_grade` json-schema | Structured outputs for mine/alive |
| Plan mode | step `plan` + IMPROVE_OURS | Keep plans in repo docs |

### 4) Safe experiment (don’t break lab NEXUS)

```bash
# Product staging only — never overwrite lab workspace
bash ~/nexus-core/scripts/safe_product_eval.sh --compare

# Interactive Grok Build only in product tree
cd ~/nexus-core-staging   # or ~/nexus-core
grok -p "Read src/nexus/engine.py and propose one small durability test"
```

Lab (`$NEXUS_LAB_ROOT`) stays your live ops workspace; product is the coding target.

---

## Recommended workflow (developer path)

1. **Open product tree**  
   `cd ~/nexus-core && grok`  
2. **Small PR-sized change** with Grok Build (tests green).  
3. **Orchestration / multi-agent** via NEXUS bus when you need Claude + Codex + Grok together.  
4. **Self-improve** only with budget + staging eval first.  
5. **Publish** only allowlisted paths when pytest is green.

```bash
# Example: one headless improve slice under NEXUS control
export NEXUS_GROK_MODEL=grok-4.5
export NEXUS_PROJECT_ROOT=~/nexus-core
PYTHONPATH=src python3 -c "
from pathlib import Path
from nexus.grok_worker import grok_hard_improve
r = grok_hard_improve(Path('.'), 'Add one test for agent fallback; keep pytest green', max_turns=16)
print(r.get('ok'), r.get('returncode'), (r.get('text') or '')[:500])
"
```

---

## What *not* to do

| Avoid | Why |
|-------|-----|
| Vendor entire Grok Build into the repo | Binary + marketplace already on machine; license/update burden |
| Run unbounded `grok -p` in loops overnight | Token burn (you already saw this) |
| Replace DurableEngine with only Grok sessions | Lose multi-vendor audit + crash resume |
| Point Grok Build at lab `lab workspace` while ops units run | Risk of accidental edits to live workspace |

---

## Complexity and next steps

| Step | Effort | Outcome |
|------|--------|---------|
| Use TUI daily on `nexus-core` | Low | Faster coding |
| Keep `grok_worker` as headless API | Done | Mine/alive/multi-vendor |
| Map Grok permissions ↔ NEXUS trust/HITL | Medium | Safer prod |
| Optional: ACP client for dashboard | Medium | Stream Grok thoughts into NEXUS UI |
| Study Grok Build open sources if/when published as a repo | Medium | Pattern theft without fork |

---

## Quick links

| Resource | Location |
|----------|----------|
| Grok Build CLI | `grok` / `~/.grok/bin/grok` |
| User guide | `~/.grok/docs/user-guide/` |
| NEXUS Grok worker | `src/nexus/grok_worker.py` |
| Platforms / MCP | `docs/PLATFORMS.md` |
| Safe GitHub eval | `scripts/safe_product_eval.sh` |
| Multi-vendor live | `scripts/multi_vendor_live.py` |
| Merge with lab | `docs/MERGE_REAL_NEXUS.md` |

**Bottom line:** Grok Build is the **coding agent harness**; NEXUS is the **durable multi-agent product**. Build Nexus *with* Grok Build, and orchestrate Grok *inside* Nexus — that is the developer path.
