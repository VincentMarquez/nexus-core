# Tracker (single source of truth)

**Update this file when status changes.**  
Statuses: `done` · `in_progress` · `ready` · `blocked` · `later` · `wontfix`

## Phase A — Governed self-edit spine

| ID | Status |
|----|--------|
| S01–S11 | **done** |

## Phase B — Capability factory

| ID | Status | Notes |
|----|--------|-------|
| S12 | **done** | harvest → fill → soft-accept; golden skill activated |
| S13 | **done** | builtins + first-class MCP `nexus_*` tools + multi_llm `--real` registry |
| Wave D | **done** | portfolio `capability:skill\|tool` select + implement via factory |
| Wave E | **done** | auto-activate soft-accepted skills (`skill_factory_auto_activate`, default on) + retire |

## Closed-loop factory (complete)

| Item | Status |
|------|--------|
| Grok/heuristic fill skill candidates | **done** (`fill_skill_candidate`) |
| Harvest accept path | **done** (fill+accept default; activate opt-in) |
| First-class MCP tool names | **done** (`nexus_lesson_query` … `nexus_code_review`) |
| multi_llm `--real` registry | **done** (`REAL_LOCAL_TOOLS` + `build_local_registry`) |
| skill ↔ tool spawn | **done** (`_spawn_required_tools` on propose+fill) |
| Portfolio capability ideas | **done** (`collect_capability_ideas` / `implement_capability_idea`) |
| Auto-activate + retire | **done** (CLI/MCP/alive; auto-activate default on) |

## Now

- **REAL run:** **operator-owned** — run the self-improved REAL in this workspace yourself  
- **Do not assume a live REAL process** unless you started one  
- **workspace:** `.nexus/workspace/chat.jsonl`  
- **summary on end:** `docs/LATEST_IMPLEMENT_SUMMARY.md`  

## Config flags (factory)

| Flag | Default | Meaning |
|------|---------|---------|
| `skill_factory_enable` | `true` | harvest after REAL |
| `skill_factory_auto_activate` | `true` | Wave E: activate accepted skill candidates into `skillpacks/` |

## Recently completed

- Full S01–S13 + Waves D–E closed-loop factory  
- First-class MCP builtins + multi_llm real registry  
- Portfolio capability idea implement path  
- CLI: `fill-skill`, `harvest`, `auto-activate`, `retire-skill`  
