# 03 — Local LLM via Ollama

**Goal:** Auto-detect hardware, start bus + dashboard, answer as agent `local`.

```bash
# Install Ollama from https://ollama.com if needed
make install
nexus start -y
# browser opens dashboard (or open the printed URL)

python examples/call_bus.py --agent local --prompt "Reply in one short sentence."
nexus stop
```

Force a model:

```bash
nexus start -y --model gemma4:e4b --no-open
```

Enable paid CLIs only when you want them:

```bash
nexus start -y --with-cli
```
