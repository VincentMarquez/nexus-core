# Getting started

## Start console (website)

Open the public **Start** page (same look as the local JS dashboard):

**https://vincentmarquez.github.io/nexus-core/**

- Copy-ready `./run` command  
- GitHub job builder (`nexus do …`)  
- Detects a **local bus** on this machine and links to the live dashboard  

## Zero config (terminal)

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
./run
```

This creates `.venv`, installs the package, starts the bus + **start console dashboard**, auto-starts Ollama (and pulls a small model if needed), and **enables real CLI agents when they are installed** (claude / codex / gemini). Missing tools get safe **mock** bridges so demos still work.

Requires: **Python 3.10+** and **Node 18+**. Ollama and AI CLIs are optional.

After start, the browser opens `http://127.0.0.1:<port>/dashboard` — agents, tasks, SSE events, and copy-paste job builders.

## Manual install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# after publish: pip install nexus-multi-agent
nexus start          # same automatic behavior
```

## Control flags

```bash
./run --no-cli       # mock agents only (no real CLIs)
./run --no-pull      # don’t pull Ollama models
./run --no-smoke     # skip first agent ping
./run --model gemma2:2b
nexus status
nexus stop
```

## Paste a GitHub repo

```bash
./run https://github.com/owner/repo
nexus do owner/repo --goal "make tests pass"
nexus do owner/repo --resume gh-owner-repo-xxxxxxxx
```

Clones into `.nexus_workspaces/`, installs, runs checks, and tries to fix failures (agents when the stack is up). See [cookbook 06](cookbook/06_github_do.md).

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
