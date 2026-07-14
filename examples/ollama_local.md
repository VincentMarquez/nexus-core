# Hook a local LLM (Ollama)

Connect **Ollama** to the event bus, then optionally to the Python engine.

## Prerequisites

1. [Ollama](https://ollama.com) installed  
2. A model pulled, e.g.:

```bash
ollama serve          # if not already running
ollama pull gemma2    # or llama3.2, qwen2.5, …
```

3. This repo checked out; Node 18+ for the bus.

**Hardware note:** on unified-memory boxes (e.g. GB10), prefer **small** always-on models. Very large models can starve the rest of the stack.

---

## Terminal layout

```text
[1] bridge bus          npm start
[2] ollama bridge       ./bridges/ollama-http.sh local gemma2
[3] optional mock       ./bridges/mock-bridge.sh claude
[4] client / engine     curl or python examples
```

---

## 1. Start the bus

```bash
cd bridge
export NEXUS_AGENTS=claude,local,gpt
export NEXUS_BRIDGE_DIR="${TMPDIR:-/tmp}/nexus-bridges"
npm start
# listening on http://127.0.0.1:3099
```

---

## 2. Start the Ollama bridge

```bash
cd bridge
export NEXUS_BRIDGE_DIR="${TMPDIR:-/tmp}/nexus-bridges"   # same as bus
chmod +x bridges/ollama-http.sh
./bridges/ollama-http.sh local gemma2
```

Env overrides:

| Env | Default | Meaning |
|-----|---------|---------|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama HTTP API |
| `OLLAMA_MODEL` | `gemma2` | model name |
| `NEXUS_BRIDGE_DIR` | `$TMPDIR/nexus-bridges` | shared with bus |

---

## 3. Smoke test

```bash
curl -s http://127.0.0.1:3099/api/status | jq .
curl -s -X POST http://127.0.0.1:3099/api/message \
  -H 'content-type: application/json' \
  -d '{"agent":"local","prompt":"Reply with one short sentence about checkpoints."}'
```

Or:

```bash
python examples/call_bus.py --agent local --prompt "Say hi from local LLM"
```

---

## 4. Drive the Python engine through the bus

Keep operator as mock; route other roles to bus slots (`local` / `claude`):

```bash
# optional: also run a mock "claude" if you have no cloud CLI
./bridges/mock-bridge.sh claude

python examples/run_with_bus.py --task-id ollama-demo
```

`run_with_bus.py` uses `AgentPanel.from_bus(...)`:

- If `local` is online → used for roles mapped to `local`  
- If a slot is offline and fallback is on → **MockAgent** so demos still complete  

Role map (default):

| Pipeline role | Bus agent |
|---------------|-----------|
| planner, implementer, reviewer | `claude` (mock or real CLI) |
| adversary, tester, logger | `local` (Ollama) |

Override:

```bash
python examples/run_with_bus.py \
  --base http://127.0.0.1:3099 \
  --map planner=local,implementer=local,tester=local
```

---

## 5. Real cloud CLI (optional, still no keys in git)

```bash
# only if `claude` is installed and logged in on YOUR machine
./bridges/cli-bridge.sh claude claude --print
```

Never commit API keys. Prefer CLI login or shell env private to your session.

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| `agent offline: local` | Is `ollama-http.sh` running? Same `NEXUS_BRIDGE_DIR`? |
| cannot reach Ollama | `curl $OLLAMA_HOST/api/tags` |
| model not found | `ollama pull <model>` |
| bus connection refused | `npm start` in `bridge/` |
| slow answers | lower `num_predict` in `ollama-http.sh` or use a smaller model |

---

## Notes

- Ollama defaults to localhost  
- Prefer not exposing the bus port without authentication  
