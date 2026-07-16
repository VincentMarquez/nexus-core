# Max-tier models for multi-vendor NEXUS

Pins every bus agent to the **highest** model / effort settings for SWE-Pro and hard coding work.

| Agent | Slot | Model / tier | Effort |
|-------|------|--------------|--------|
| **Claude** | `claude` (plan + review L1) | `fable` | `max` |
| **ChatGPT / Codex** | `gpt` (adversary + review L2) | `gpt-5.6-sol` | `ultra` reasoning · service tier **`fast`** |
| **Grok** | `grok` (implementer) | `grok-4.5` | reasoning **`max`** · more turns |
| **Gemini** | `gemini` (research) | CLI default (set `NEXUS_GEMINI_MODEL` to pin) | — |
| **Local** | `local` | Ollama / NVFP via separate config | light tests only |

## Apply on this machine

```bash
# one-shot for current shell
set -a && source ~/nexus-core/config/max_models.env && set +a

# start bus with max pins
cd ~/nexus-core
set -a && source config/max_models.env && set +a
nexus start -y

# or campaigns (auto-load config/max_models.env)
PYTHONPATH=src python3 scripts/swe_pro_multi_ai.py --once
PYTHONPATH=src python3 scripts/multi_vendor_live.py --once
```

## Env vars

| Variable | Default |
|----------|---------|
| `NEXUS_CLAUDE_MODEL` | `fable` |
| `NEXUS_CLAUDE_EFFORT` | `max` |
| `NEXUS_CODEX_MODEL` | `gpt-5.6-sol` |
| `NEXUS_CODEX_REASONING` | `ultra` |
| `NEXUS_CODEX_SERVICE_TIER` | `fast` |
| `NEXUS_GROK_MODEL` | `grok-4.5` |
| `NEXUS_GROK_REASONING_EFFORT` | `max` |
| `NEXUS_GROK_BRIDGE_TURNS` | `12` |
| `NEXUS_GEMINI_MODEL` | (unset = CLI default) |
| `NEXUS_CLI_TIMEOUT_S` | `600` |

Also mirrored in:

- `~/.claude/settings.json` → `model=fable`, `effort=max`
- `~/.codex/config.toml` → `gpt-5.6-sol` + `ultra` + `service_tier=fast`
- `bridge/bridges/stdin_to_grok.py` → `--reasoning-effort` from env

## Role reminder

| Role | Who |
|------|-----|
| Implementer | **Grok 4.5 max** |
| Adversary / review L2 | **Codex gpt-5.6-sol ultra+fast** |
| Plan / review L1 | **Claude Fable max** |
| Research | **Gemini** |
