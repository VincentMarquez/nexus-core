# 05 — GLM-5.2 (colibrì) as a NEXUS agent

**Goal:** Attach a heavy local MoE behind the bus as agent `glm52`.

Full guide: [docs/GLM52.md](../docs/GLM52.md)

```bash
# Terminal 1 — your colibrì install + model
export COLI_MODEL=/path/to/glm52-colibri-int4
coli serve --host 127.0.0.1 --port 8000

# Terminal 2
nexus start -y --no-open

# Terminal 3
export COLI_OPENAI_BASE=http://127.0.0.1:8000/v1
export COLI_OPENAI_MODEL=glm-5.2-colibri   # match serve
./bridge/bridges/colibri-glm.sh glm52

# Terminal 4
python examples/call_bus.py --agent glm52 --prompt "Say GLM_OK"
python examples/run_with_bus.py --task-id glm-mix \
  --map planner=glm52,implementer=glm52,tester=local,logger=local
```

Lab measurements: https://github.com/VincentMarquez/glm52-gb10-colibri  
Upstream: https://github.com/JustVugg/colibri  
