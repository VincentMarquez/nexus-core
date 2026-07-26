# Getting started

The source checkout is currently the canonical installation. Start with the
offline demo, then opt into the bus, live model clients, or repository
execution as needed.

## Requirements

- Python 3.10+
- Git
- a POSIX shell
- Node.js 18+ only for the event bus and dashboard

Ollama, model-provider CLIs, GitHub authentication, and API keys are optional.

## Install and run the offline demo

```bash
git clone https://github.com/VincentMarquez/nexus-core.git
cd nexus-core
make install
source .venv/bin/activate
make demo-all-quick
nexus task list
```

`make install` creates `.venv` and installs the source tree in editable mode.
`make demo-all-quick` runs the unit suite, crash/resume proof, rubric-judge
example, engine smoke cases, platform discovery, and resilience dry-run. It
does not require live model providers.

Quick mode skips the optional GitHub-auth check and scoreboard. It does not run
the real self-improvement loop or capability factory and does not measure live
model quality.

See [the demo guide](DEMO.md) for each check.

## Short proofs

```bash
make demo          # simulated crash → resume → expected artifact
make demo-judge    # artifact presence is not sufficient for success
make smoke         # engine smoke scenarios
```

Inspect the resulting durable task:

```bash
nexus task list
nexus task replay <task_id>
nexus task verify <task_id>
nexus task evidence <task_id> --out evidence.json
```

Details: [Crash → resume](cookbook/01_crash_resume.md) and
[Task operator](cookbook/12_task_operator.md).

## Start the local bus and dashboard

From the repository root:

```bash
./run --no-pull
```

This creates or reuses `.venv`, installs the package, starts the Node.js bus and
dashboard, detects Ollama and supported model CLIs, and supplies mock bridges
for unavailable agent slots. `--no-pull` prevents an automatic Ollama model
download.

The browser opens the local dashboard unless disabled:

```bash
./run --no-pull --no-open
```

Useful controls:

```bash
./run --no-cli       # disable installed model CLIs; use mock bridges
./run --no-pull      # do not download an Ollama model
./run --no-smoke     # skip the first agent ping
./run --model <ollama-model>
nexus status
nexus stop
```

Real providers must be installed and authenticated separately. Exact model
identifiers depend on the selected client or provider. See
[Model platforms](PLATFORMS.md) and [Local LLM tool calling](LOCAL_LLM_TOOL_CALLING.md).

## Run a repository job

```bash
source .venv/bin/activate
nexus do owner/repo --goal "run the checks and repair the failures"
```

The job clones into `.nexus_workspaces/`, detects the project layout, may
install dependencies, runs discovered checks, and can ask configured agents for
repair suggestions.

> **Security:** installers, build hooks, Make targets, and tests can execute
> repository-controlled code. The executable-name allowlist is not a sandbox.
> Use trusted commits or an isolated, credential-free environment.

Resume a saved job with the job ID printed by the first run:

```bash
nexus do owner/repo --resume <job_id>
```

See [Repository repair](cookbook/06_github_do.md) before running third-party
code.

## Workspace MCP and the HTTP demo API

Local stdio:

```bash
export NEXUS_PROJECT_ROOT="$PWD"
nexus mcp
```

Local HTTP tools demo:

```bash
export NEXUS_PROJECT_ROOT="$PWD"
nexus mcp --http --host 127.0.0.1 --port 8765
```

This HTTP mode is a minimal JSON tools/demo API, not the full remote
MCP-over-SSE or Streamable HTTP transport described in the connector patterns.
It has no built-in application authentication. Keep it on localhost and do not
expose it directly to the public internet.

Direct file tools enforce the project root, but the full tool catalog may
include write and operational tools.

See [MCP setup](MCP_SETUP.md), [Connectors](CONNECTORS.md), and
[security and trust boundaries](SECURITY.md).

## Where to go next

- [Architecture](ARCHITECTURE.md)
- [10-step pipeline](PIPELINE.md)
- [Cookbooks](cookbooks.md)
- [Demo guide](DEMO.md)
- [Model platforms](PLATFORMS.md)
- [Security and trust boundaries](SECURITY.md)
