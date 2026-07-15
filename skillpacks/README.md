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

## Example

See [`durable-operator/`](durable-operator/) — operator audit + HITL resume.

## Use with NEXUS

```bash
# Read pack into context (agent / human)
less skillpacks/durable-operator/SKILL.md

# Run related product demos
python3 examples/demo_hitl_resume.py
nexus task list
```

Packs are **docs + hooks**, not a second plugin runtime. Wire them into Cursor/Claude/Grok via copy-paste or MCP file tools.
