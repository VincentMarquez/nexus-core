# Skill packs (multi-harness layout)

Inspired by multi-harness agent marketplaces (e.g. one Markdown source → many tools).  
**Port patterns, not whole trees.** Each pack is a small, versioned folder.

## Layout

```text
skillpacks/
  <pack-id>/
    SKILL.md          # human + agent instructions (source of truth)
    manifest.json     # id, version, tags, entrypoints
    hooks/            # optional shell/python hooks
    tests/            # optional pack-local checks
```

## Packs

| Pack | Purpose |
|------|---------|
| [`durable-operator/`](durable-operator/) | Operator audit + HITL resume |
| [`gemma-local-tools/`](gemma-local-tools/) | **Small/local LLM cheat sheet** — how Gemma (or any small model) uses Grok’s full tool belt + coding skills |

## Small models + full tools

Local models inside Grok CLI get the **same hands** (shell, files, MCP) as cloud Grok. They need a **cheat sheet** so they actually call tools:

```bash
# Install for Grok CLI
mkdir -p ~/.grok/skills
cp -a skillpacks/gemma-local-tools ~/.grok/skills/gemma-local-agent

# Session prompt on /model gemma4:
#   Follow gemma-local-agent. Use tools; don't only describe them.
```

Full write-up: [docs/LOCAL_LLM_TOOL_CALLING.md](../docs/LOCAL_LLM_TOOL_CALLING.md).

## Use with NEXUS

```bash
# Read pack into context (agent / human)
less skillpacks/durable-operator/SKILL.md
less skillpacks/gemma-local-tools/SKILL.md

# Run related product demos
python3 examples/demo_hitl_resume.py
nexus task list
```

Packs are **docs + hooks**, not a second plugin runtime. Wire them into Cursor/Claude/Grok via copy-paste, skill install, or MCP file tools.
