# NEXUS Core cookbooks

Copy-paste recipes. Each is self-contained.

| # | Recipe | What you learn |
|---|--------|----------------|
| 01 | [Crash → resume](01_crash_resume.md) | Durable checkpoints |
| 02 | [Judge vs presence](02_judge_vs_presence.md) | Evidence-based success |
| 03 | [Local LLM (Ollama)](03_local_llm_ollama.md) | Auto local model on the bus |
| 04 | [Workspace MCP](04_workspace_mcp.md) | Tools for AI clients |
| 05 | [GLM-5.2 / colibrì](05_glm52_colibri.md) | Heavy MoE as an agent |

Prereq for most recipes:

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```
