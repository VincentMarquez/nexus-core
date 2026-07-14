# How to wire a multi-agent bus + CLI bridges

This document describes the **pattern** used in a full NEXUS-style lab.  
The public kit includes **stubs only** under [`bridge/`](../bridge/) — no API keys, no personal paths, no real vendor SDKs.

The Python durable engine (`nexus.engine`) does **not** require this stack. Bridges are how you connect **real** CLI agents when you outgrow mock agents.

---

## Big picture

```
┌─────────────────────┐     HTTP JSON      ┌──────────────────────┐
│  UI / orchestrator  │ ─────────────────► │  Event bus (Node)    │
│  (React, run.py,    │ ◄───────────────── │  server.js :PORT     │
│   CLI client)       │   SSE / poll       │                      │
└─────────────────────┘                    └──────────┬───────────┘
                                                      │
                         writes prompt file           │ status + response files
                         /tmp/<agent>-prompt.json     │
                                                      ▼
                                           ┌──────────────────────┐
                                           │  Bridge worker (bash)│
                                           │  loops: wait prompt  │
                                           │  → call local CLI    │
                                           │  → write response    │
                                           └──────────┬───────────┘
                                                      │
                                                      ▼
                                           claude / codex / gemini / …
                                           (auth is YOUR local CLI login)
```

**Key idea:** the bus never embeds your API keys.  
Each **bridge process** runs next to a CLI that is already logged in (`claude`, `codex`, etc.), or reads keys only from **your** environment (`ANTHROPIC_API_KEY`, …) that you never commit.

---

## Components

| Piece | Job | Public stub |
|-------|-----|-------------|
| **Event bus** | HTTP API: submit work, poll status, list agents online | `bridge/server.js` |
| **Bridge worker** | Watch prompt file → invoke CLI → write response | `bridge/bridges/*.sh` |
| **Orchestrator** | 10-step policy; picks agents; checkpoints | Python `nexus.engine` |
| **Dashboard (optional)** | Show tasks / agents | *not shipped* — any UI that hits the bus |

---

## File-drop protocol (simple, robust)

Many CLI tools are easiest to drive from a **sidecar process**, not from in-process SDKs.

For each agent name (e.g. `claude`, `gpt`):

| File | Writer | Meaning |
|------|--------|---------|
| `/tmp/<agent>-bridge-prompt.json` | bus | `{ "id", "prompt", "ts" }` |
| `/tmp/<agent>-bridge-response.json` | bridge | `{ "id", "text", "ts" }` |
| `/tmp/<agent>-bridge-status.json` | bridge | `{ "status": "online"\|"offline"\|"busy", "ts" }` |

### Bridge loop (pseudocode)

```text
loop forever:
  if prompt file exists:
    set status = busy
    read prompt JSON
    run:  $LLM_CLI << prompt   # e.g. claude --print
    write response JSON
    delete prompt file
    set status = online
  sleep 0.5s
```

### Bus side

```text
when orchestrator needs agent A:
  write prompt file for A
  poll until response file appears (timeout)
  return text to engine
```

**Why files?** CLI sessions often live in a terminal; a bash loop can call them without the Node process holding secrets.

---

## HTTP surface (minimal contract)

Implement at least:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | liveness |
| `GET` | `/api/status` | which agents are online (read status files) |
| `POST` | `/api/message` | `{ "agent", "prompt" }` → wait → `{ "text" }` |
| `GET` | `/api/events` | optional SSE stream of task updates |

Env vars (examples — **never commit values**):

```bash
export NEXUS_BUS_PORT=3099
export ANTHROPIC_API_KEY=...    # only if a bridge uses the API directly
export OPENAI_API_KEY=...
# Prefer CLI login over keys when possible
```

Use a `.env` file locally and add `.env` to `.gitignore` (already ignored in this repo).

---

## Circuit breakers

If an agent fails repeatedly:

1. Mark it **OPEN** in a small health table  
2. Route to **fallback** agent (see Python `FALLBACK_TABLE` in `nexus.steps`)  
3. After cooldown, try **HALF_OPEN** with one probe  

Do **not** default missing health to “online” — offline agents must not poison validation.

---

## Wiring to the Python engine

```text
MockAgent.run()     →   offline demo (default in this repo)
HttpAgent.run()     →   POST /api/message  (your bus)
```

Pattern for a real adapter (sketch):

```python
import urllib.request, json

def call_bus(agent: str, prompt: str, base="http://127.0.0.1:3099") -> str:
    req = urllib.request.Request(
        f"{base}/api/message",
        data=json.dumps({"agent": agent, "prompt": prompt}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["text"]
```

Keep keys **out** of Python if the bridge owns auth.

---

## Security checklist (public repos)

| Do | Don’t |
|----|--------|
| Document env var **names** | Commit `.env` or real keys |
| Use `/tmp` or configurable `BRIDGE_DIR` | Hardcode `/home/you/...` |
| Singleton lock per bridge | Run two bridges on the same files |
| Timeouts on CLI calls | Hang forever on a stuck model |
| Fail open on memory search | Fail open on **auth** (never) |

---

## How to run the stubs in this repo

```bash
# terminal 1 — bus
cd bridge
npm start
# or: node server.js

# terminal 2 — mock bridge (no real LLM)
./bridges/mock-bridge.sh claude

# terminal 3 — smoke request
curl -s http://127.0.0.1:3099/health
curl -s http://127.0.0.1:3099/api/status
curl -s -X POST http://127.0.0.1:3099/api/message \
  -H 'content-type: application/json' \
  -d '{"agent":"claude","prompt":"Say hello from the stub bridge"}'
```

### Local LLM (Ollama)

```bash
./bridges/ollama-http.sh local gemma2
# details: examples/ollama_local.md
```

### Python engine on the bus

```bash
python examples/run_with_bus.py --task-id bus-demo
# uses nexus.bus_client.BusClient + AgentPanel.from_bus
```

Replace `mock-bridge.sh` with a real CLI bridge once you have `claude` / `codex` installed locally.

---

## What we intentionally omit

- Real Anthropic/OpenAI/xAI HTTP clients with baked-in keys  
- Personal project directories, Gmail, medical tools  
- Production systemd units and dashboards  

Those stay in a **private** lab. This doc + `bridge/` stubs are the **how-to**.
