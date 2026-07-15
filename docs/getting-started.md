# Getting started

## Install

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# after publish: pip install nexus-multi-agent
```

## One-command stack

```bash
nexus doctor              # hardware + tools
nexus start -y            # bus, dashboard, Ollama if present
nexus status
nexus stop
```

CLI agents (Claude/Codex/Gemini) only when you opt in:

```bash
nexus start -y --with-cli
```

## Demos

```bash
nexus demo                # crash → resume
python examples/demo_judge_vs_presence.py
python evals/smoke.py
```

## Workspace MCP

```bash
export NEXUS_PROJECT_ROOT=$PWD
nexus mcp --http --port 8765
# curl http://127.0.0.1:8765/health
```

Stdio (Claude Desktop): `nexus mcp` with `NEXUS_PROJECT_ROOT` set.

## Next

- [Cookbooks](cookbooks.md)  
- [Connectors](CONNECTORS.md)  
- [GLM-5.2](GLM52.md)  
