# Quick start: GLM-5.2 + NEXUS

Full guide: [docs/GLM52.md](../docs/GLM52.md)

## Minimal path (two processes)

**Terminal 1 — colibrì API** (your install + model path):

```bash
export COLI_MODEL=/path/to/glm52-colibri-int4
coli serve --host 127.0.0.1 --port 8000
```

**Terminal 2 — NEXUS stack**

```bash
cd nexus-core
make install
nexus start -y --no-open
```

**Terminal 3 — GLM bridge**

```bash
export NEXUS_BRIDGE_DIR=/tmp/nexus-core-bridges   # must match nexus start
export COLI_OPENAI_BASE=http://127.0.0.1:8000/v1
export COLI_OPENAI_MODEL=glm-5.2-colibri         # match serve id
./bridge/bridges/colibri-glm.sh glm52
```

**Terminal 4 — call**

```bash
python examples/call_bus.py --agent glm52 --prompt "Say GLM_OK"
```

**Engine with mixed brains**

```bash
python examples/run_with_bus.py --task-id glm-mix \
  --map planner=glm52,implementer=glm52,tester=local,reviewer=glm52,logger=local,adversary=local
```

## Lab measurements (separate repo)

Decode tok/s tiers, CACHE_ROUTE, GB10 notes:  
https://github.com/VincentMarquez/glm52-gb10-colibri
