# S13 — Tool factory (callables agents invoke)

| Field | Value |
|-------|--------|
| Status | **done** Wave A/C builtins (2026-07-17) — MCP wire later |
| Phase | P4 — Capability factory |
| Risk | Medium–high (code that agents can call) |
| Depends on | S12 design, S05/S06, `tool_catalog`, MCP TOOLS, privilege tags |
| Primary targets | candidate tool modules, MCP registration path, catalog export |

## Problem

Self-improve can invent better procedures (skills) but still only has the **same fixed tool belt**. Agents cannot grow new hands—only new advice. Novel improvements often need a **new callable** (search lessons, classify scope, run a structured review, validate a pack).

## Goal

When evidence shows a **capability gap**, the system can:

1. Propose a **tool candidate** (name, privilege, schema, tests, handler stub)  
2. Implement it under quarantine  
3. Verify (unit tests + catalog validate)  
4. Accept (soft)  
5. Activate into the live tool surface agents already use (MCP / CLI / multi_llm registry)  

Examples:

| Tool | Privilege | Why |
|------|-----------|-----|
| `nexus_skill_search` | read | Find activated skills for a goal |
| `nexus_lesson_query` | read | Programmatic S07 access |
| `nexus_scope_check` | read | Contract path classify for editors |
| `nexus_code_review` | read | Structured review of a file list |
| `nexus_pack_validate` | read | Skillpack structure + tests |
| `nexus_candidate_propose` | write | Scaffold skill/tool candidate only under factory dir |

## Non-goals

- Default-on network/shell tools with admin privilege  
- Auto-register untested handlers into MCP  
- Letting the model invent privilege elevation  
- Replacing the whole MCP server each cycle  

## Design

### Candidate shape

```text
.nexus_state/capability_factory/candidates/tools/<name>-<hash>/
  TOOL.md              # purpose, args, privilege, safety
  handler.py           # or patch plan into src/nexus/
  test_handler.py
  openapi_fragment.json
  EVIDENCE.md
  STATUS.json
```

### Privilege rules (hard)

| Rule | |
|------|--|
| Default privilege | `read` |
| `write` / `ops` / `admin` | Never auto-activate; owner flag required |
| Path jail | Handlers may only touch allowlisted roots unless privilege raised |
| Creation ≠ activation | STATUS `activated` only after Accept + register step |

### Pipeline

1. **Propose** from skill gap (“skill X needs tool Y”) or repeated manual steps  
2. **Scaffold** handler + tests + TOOL.md under candidates/  
3. **Implement** in quarantine worktree (S06 patterns)  
4. **Verify** `pytest` on candidate + `tool_catalog.validate` shape  
5. **Accept** soft predicate (tests green, privilege sane, no path escape)  
6. **Activate** (separate, flag-gated):
   - merge handler into `src/nexus/` or bridges  
   - register in MCP `TOOLS[]` / CLI  
   - export catalog  
7. **Observe** call counts + errors → lessons  

### Integration with multi_llm / MCP

Today many surfaces use **mock** registries. Activation path should prefer:

1. Real **read-only** local tools first (status, scope_check, lesson_query)  
2. Then write tools behind `scope_contract` + owner policy  

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `tool_factory_enable` | `false` | Master opt-in |
| `tool_factory_auto_activate_read` | `false` | Even read tools need explicit activate in v1 |
| `tool_factory_allow_write_activate` | `false` | Hard stop on write/ops activation |

### Acceptance criteria (when implementing)

- [ ] Propose cannot register into live MCP  
- [ ] Privilege default read; tests for elevation refusal  
- [ ] Path jail on candidate handlers  
- [ ] Catalog validate on activate  
- [ ] Linked skill candidate can declare `required_tools: [...]`  

## Relation to skills (S12)

| If… | Then… |
|-----|--------|
| Skill needs a missing callable | Open S13 tool candidate; skill stays draft until tool accepted or skill rewritten without it |
| Tool is useless alone | Open S12 skill that teaches when/how to call it |
