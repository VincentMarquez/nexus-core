# Small / local LLMs + full Grok tool belt

**Problem:** A small local model (e.g. Gemma 4 NVFP4 or Ollama) can sit *inside* a compatible Grok CLI session and access registered host tools, but only when the client supports tool calls and the model emits valid requests. Weaker models often **talk about** tools instead of **calling** them.

**Pattern:** Keep tools on the **host** (Grok CLI). Give the small model a **cheat sheet skill** that teaches *when* and *how* to call them, plus which coding skills to load for big work.

## Architecture (simple)

```text
User
  → Grok CLI  (hands: shell, edit, MCP, skills)
       → local model gemma4 / nexus-local  (brain: next action)
       → OR cloud Grok
```

| Piece | Who owns it |
|-------|-------------|
| Shell, file edit, search | Grok host tools |
| Nexus workspace / GitHub helpers | `nexus-workspace` MCP |
| Science kernel, etc. | Other MCP servers in `~/.grok/config.toml` |
| “How to use all of that” | Skill pack **gemma-local-tools** |

The model never embeds tools. **MCP and skills attach to the Grok session**, so switching models keeps the registered host surface; successful calls still depend on client and model support.

## Cheat sheet skill pack

| Path | Role |
|------|------|
| [gemma-local-tools/SKILL.md](https://github.com/VincentMarquez/nexus-core/blob/main/skillpacks/gemma-local-tools/SKILL.md) | Operator-specific example for discovering and using enabled tools |
| [gemma-local-tools/manifest.json](https://github.com/VincentMarquez/nexus-core/blob/main/skillpacks/gemma-local-tools/manifest.json) | Version / tags |

Install for Grok CLI (user machine):

```bash
mkdir -p ~/.grok/skills
cp -a skillpacks/gemma-local-tools ~/.grok/skills/gemma-local-agent
# or symlink:
# ln -sfn "$(pwd)/skillpacks/gemma-local-tools" ~/.grok/skills/gemma-local-agent
```

In a Grok session on the local model:

```text
Follow the gemma-local-agent / gemma-local-tools skill.
Use tools; do not only describe them.
```

Or rely on skill auto-discovery when the description matches.

## What the cheat sheet covers

1. **Built-in tools** — shell, files, web  
2. **Nexus MCP** — workspace chat, project jail, ops, improve, scout, …  
3. **GitHub** — `gh` + `github_*` MCP tools  
4. **Science MCP** — if configured  
5. **Coding skills** — `implement`, `review`, `code-review`, `check-work`, `design`, `execute-plan`, `pr-babysit`  
6. **Office / meta** — docx, pptx, xlsx, imagine, help, create-skill  
7. **Style rules for small models** — short plan → call tool → use result  

## Spark / NVFP4 notes

- Primary local brain: vLLM NVFP4 Gemma (`gemma4` in Grok config) — see [PLATFORMS.md](PLATFORMS.md).  
- In the recorded Spark setup, NVFP used approximately 80–90 GiB of unified memory; measure your own deployment before co-loading another large model.
- Tools still come from Grok, not from the vLLM container.

## Related

- [PLATFORMS.md](PLATFORMS.md) — multi-platform mesh + local models  
- [MCP_SETUP.md](MCP_SETUP.md) — workspace MCP  
- [design/nexus-orchestration-mcp-server.md](design/nexus-orchestration-mcp-server.md) — implemented `run_task` / `get_task_status` and planned higher-level interfaces
- Bus tool loop for Ollama without Grok: `bridge/bridges/ollama_tools.py`

## Why this helps small models

| Without cheat sheet | With cheat sheet |
|---------------------|------------------|
| “You could run pytest…” | Calls shell `pytest` |
| Invents file contents | `read_project_file` / file tools |
| Forgets GitHub | `gh auth status` / `github_community_status` |
| No path for “build a feature” | Load **`implement`** skill |

This is **prompting + packaging**, not a new runtime. The upgrade is making the small model a first-class *user* of the same host tools cloud Grok already has.
