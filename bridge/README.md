# Bridge stubs (no secrets)

Minimal **event bus** + **file-drop bridges** so you can see the multi-agent wiring pattern.

- **No API keys** in this tree  
- **No personal paths**  
- Mock bridge returns canned text; swap the shell script for a real CLI when ready  

Full design notes: [docs/BRIDGES_AND_BUS.md](../docs/BRIDGES_AND_BUS.md)

## Quick start

```bash
# from repo root
cd bridge
npm start                 # bus on :3099 (override NEXUS_BUS_PORT)

# another terminal
./bridges/mock-bridge.sh claude

# another terminal
curl -s http://127.0.0.1:3099/api/status | jq .
curl -s -X POST http://127.0.0.1:3099/api/message \
  -H 'content-type: application/json' \
  -d '{"agent":"claude","prompt":"ping"}' | jq .
```

## Local LLM (Ollama — no cloud keys)

```bash
# ollama serve && ollama pull gemma2
./bridges/ollama-http.sh local gemma2
```

Guide: [examples/ollama_local.md](../examples/ollama_local.md)

## Real CLI (example pattern — you provide the CLI)

```bash
# only if `claude` is installed and logged in on YOUR machine
./bridges/cli-bridge.sh claude claude --print
```

Auth stays with the CLI or your local env — never commit keys.

## Python

```bash
python ../examples/call_bus.py --agent local
python ../examples/run_with_bus.py   # durable engine via bus
```
