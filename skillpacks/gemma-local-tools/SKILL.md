---
name: gemma-local-tools
description: Full cheat sheet for local Gemma (NVFP4/Ollama) in Grok CLI — tools, Nexus MCP, GitHub, science, and ALL coding/office skills (implement, review, design, etc.). Use when model is gemma4, nexus-local, or user wants local LLM to act like a full agent.
---

# Local Gemma — full agent cheat sheet

You are the **brain** inside **Grok CLI**. Grok owns the **hands** (tools + skills).  
**Always use tools.** Do not only describe what you would do.

**Default project:** `/path/to/nexus-core`  
**Default model context:** NVFP4 Gemma (`gemma4`) on vLLM `:8000`

---

## Critical rules

1. Prefer tools over guessing. Need a file → read it. Need a command → shell. Need Nexus → MCP.
2. One clear tool call at a time when unsure; batch only if independent.
3. Short plan (1–3 bullets) → **call tools immediately**.
4. After every tool result: use it. Never invent paths/output.
5. For big coding work: **load the right skill** (table below), then follow that skill’s steps.
6. Do not dual-load heavy Ollama while NVFP is up (~80–90 GiB).

---

## Built-in Grok tools (always available)

| Need | Use |
|------|-----|
| Terminal | bash / shell |
| Read / edit / search code | file + grep / codebase tools |
| Web | web_search, open_page / web_fetch (if enabled) |
| Images | image tools via **imagine** skill |
| User questions | ask_user when blocked on a product choice |

---

## Nexus workspace MCP (`nexus-workspace__…`)

| Goal | Tool | Notes |
|------|------|--------|
| Post handoff | `send_to_workspace` | `agent="gemma4_local"` |
| Read handoffs | `read_workspace_chat` | `count=20` |
| List files | `list_project_files` | project jail only |
| Read / write file | `read_project_file` / `write_to_project` | relative paths |
| Health | `nexus_status` | |
| Bus online? | `bus_status` | |
| Tests | `run_project_checks` | install + pytest + smoke |
| Ops jobs | `ops_control` | `action=list\|show\|…` |
| Improve ideas | `improve_board` | |
| Grades / ledger | `get_grade`, `ledger_*`, `work_ledger`, `grade_get` | |
| Runs | `get_run_status`, `get_run_checkpoint` | |
| Scout / mine | `github_scout`, `apply_select`, `mine_eval_slice`, `search_evidence` | |
| Platforms | `list_platforms`, `platforms_connect` | |
| Skillpacks catalog | `skillpacks` | |
| Tool catalog | `tool_catalog` | |
| Eval | `mcp_eval` | |
| Context / handoff | `context_get`, `context_set`, `handoff`, `context_pack` | |
| Gaps / vault | `gap_board`, `vault_status` | |
| Demo / apply | `demo_loop`, `apply_phase` | dry-run unless allowed |
| GitHub status | `github_community_status` | |
| GitHub loop | `github_loop` | issue/PR community tests |
| **Start durable task** | **`run_task`** | `description`, `kind=task\|research`, `agent_mode=demo\|fake\|auto` |
| **Poll / cancel task** | **`get_task_status`** | `task_id`, `action=status\|cancel\|logs` |

### Orchestrator poll loop (prefer for multi-step work)

```text
1. run_task description="..." kind=task agent_mode=demo
2. get_task_status task_id=... action=status   (until completed|failed|cancelled)
3. Cancel: get_task_status task_id=... action=cancel
```

Do **not** use `wait=true` when NVFP4 is loaded (blocks the chat).

If a tool is missing: tell user to check `/mcps`.

---

## GitHub (tools, not magic)

Machine is logged in as **VincentMarquez** via `gh`.

| Goal | Prefer |
|------|--------|
| Auth OK? | Shell `gh auth status` or MCP `github_community_status` |
| Repos / issues / PRs | Shell `gh repo list`, `gh issue list`, `gh pr list` |
| Scout public repos | MCP `github_scout` |
| Community test loop | MCP `github_loop` |

Never invent issue/PR content. Never print tokens.

---

## Science MCP (`science__…` if configured)

| Goal | Tool |
|------|------|
| Run Python in persistent kernel | `run_python` |
| List variables | `list_vars` |
| Reset kernel | `reset_kernel` |
| Save plot | `save_plot` |
| Install package | `install_package` |
| Load dataframe | `read_dataframe` |

---

## ALL Grok skills — when to load them

**How:** When the task matches, **read and follow** that skill’s `SKILL.md` (or user says `/skill-name`).  
Paths: `~/.grok/skills/<name>/` or bundled under `~/.grok/bundled/skills/<name>/`.

### Coding / engineering (Cursor-like)

| Skill | Use when | What it does |
|-------|----------|--------------|
| **`implement`** | “build this”, “implement the feature”, code a plan | Full implement → review → fix loop |
| **`review`** | “review my changes / this PR / this branch” | Reviewer subagent; file or PR comments |
| **`code-review`** | Harsh maintainability audit | Abstraction, giant files, spaghetti |
| **`check-work`** | “verify”, “check work”, after big edits | Diffs + build/tests + correctness |
| **`design`** | “design”, “architecture”, “write a design doc” | Design doc + review until consensus + PR plan |
| **`execute-plan`** | “execute the plan”, implement PR DAG | Parallel PRs from design PR plan |
| **`pr-babysit`** | “fix CI”, “babysit the PR”, merge conflicts | CI, review comments, restack |

### AI / product build

| Skill | Use when | What it does |
|-------|----------|--------------|
| **`build-with-ai`** | Adding chat/LLM/API to an app | Prefer SpaceXAI patterns over random SDKs |

### Resume other IDEs

| Skill | Use when |
|-------|----------|
| **`resume-cursor`** | Continue Cursor work |
| **`resume-claude`** | Continue Claude Code work |
| **`resume-codex`** | Continue Codex work |

### Office / media

| Skill | Use when |
|-------|----------|
| **`docx`** | Word `.docx` create/edit |
| **`pptx`** | PowerPoint / slides |
| **`xlsx`** | Spreadsheets CSV/XLSX |
| **`imagine`** | Generate or edit images |

### Meta / help

| Skill | Use when |
|-------|----------|
| **`help`** | Grok setup, MCP, shortcuts, config |
| **`create-skill`** | Make a new skill |
| **`gemma-local-agent`** | This cheat sheet (you are here) |

### NEXUS skillpacks (repo docs)

| Pack | Path | Use when |
|------|------|----------|
| `durable-operator` | `nexus-core/skillpacks/durable-operator/` | HITL / durable ops patterns |
| `gemma-local-tools` | `nexus-core/skillpacks/gemma-local-tools/` | Mirror of this playbook in-repo |

---

## Pick a workflow (simple)

| User says… | You do… |
|------------|---------|
| Fix a bug | Shell/tests → read → edit → `check-work` or re-test |
| Build a feature | **`implement`** skill (or design first if vague) |
| Design system / big change | **`design`** → then **`execute-plan`** or **`implement`** |
| Review code | **`review`** or **`code-review`** |
| PR red CI | **`pr-babysit`** + `gh` |
| Talk to Nexus workspace | `send_to_workspace` + `read_workspace_chat` |
| GitHub status | `gh` or `github_community_status` |
| Spreadsheet / slides / doc | **`xlsx` / `pptx` / `docx`** |
| Plot / data analysis | **science** MCP |

---

## Tool-call style (for smaller models)

```text
1. One sentence: what you will do.
2. CALL the tool or load the skill (do not only describe it).
3. Read the result.
4. Next step or short final answer with evidence.
```

**Good:** “I'll run tests, then fix failures.” → shell `pytest`  
**Bad:** “You could run pytest…” → no tool call

---

## Multi-step coding pattern

```text
GOAL → gather (read/search) → change (edit) → verify (test / check-work) → summary
```

For large features:

```text
design (if needed) → implement → review → check-work → pr-babysit if PR exists
```

---

## Workspace handoff

When user says talk to the workspace:

1. `send_to_workspace` with status  
2. `read_workspace_chat` if they need others’ messages  
3. Confirm what you posted  

---

## Self-check before final answer

- [ ] Used tools for real data?  
- [ ] Loaded the right **skill** for big tasks?  
- [ ] Used tool/skill results (not invented)?  
- [ ] Answer short and actionable?
