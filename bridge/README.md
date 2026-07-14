# Event bus and agent bridges

HTTP bus + file-drop workers for multi-CLI / local-LLM agents.

Design notes: [docs/BRIDGES_AND_BUS.md](../docs/BRIDGES_AND_BUS.md)

## Quick start

```bash
cd bridge
npm start                 # bus on :3099  → dashboard at /dashboard

# another terminal
./bridges/mock-bridge.sh claude

# another terminal
curl -s http://127.0.0.1:3099/api/status | jq .
curl -s -X POST http://127.0.0.1:3099/api/message \
  -H 'content-type: application/json' \
  -d '{"agent":"claude","prompt":"ping"}' | jq .
```

## Local LLM (Ollama)

```bash
# ollama serve && ollama pull gemma2
./bridges/ollama-http.sh local gemma2
```

Guide: [examples/ollama_local.md](../examples/ollama_local.md)

## GLM-5.2 (colibrì)

```bash
# terminal: coli serve  (COLI_MODEL=…, OpenAI-compatible :8000/v1)
export COLI_OPENAI_BASE=http://127.0.0.1:8000/v1
export COLI_OPENAI_MODEL=glm-5.2-colibri
./bridges/colibri-glm.sh glm52
```

Guide: [docs/GLM52.md](../docs/GLM52.md) · [examples/glm52_nexus.md](../examples/glm52_nexus.md)

## Real CLI agents

```bash
# example: Claude Code CLI already installed and authenticated
./bridges/cli-bridge.sh claude claude --print
```

Credentials stay in your local CLI session or shell environment.

## Python

```bash
python ../examples/call_bus.py --agent local
python ../examples/run_with_bus.py   # durable engine via bus
```

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `NEXUS_BUS_PORT` | `3099` | HTTP port |
| `NEXUS_BRIDGE_DIR` | `$TMPDIR/nexus-bridges` | prompt/response/status files |
| `NEXUS_AGENTS` | `claude,gpt,gemini,local` | known agent slots |
| `NEXUS_STATE_DIR` | `../.nexus_state` | task JSON for dashboard |
