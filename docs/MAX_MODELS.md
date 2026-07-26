# Recorded max-tier model configuration

This page preserves one operator's July 2026 configuration for SWE-Pro and hard coding work. Model identifiers and accepted effort/service-tier values change across CLIs and providers; set each variable to a value supported by your installed tool. These values are examples, not product requirements.

| Agent | Slot | Model / tier | Effort |
|-------|------|--------------|--------|
| **Claude** | `claude` (plan + review L1) | `fable` | `max` |
| **ChatGPT / Codex** | `gpt` (adversary + review L2) | `gpt-5.6-sol` | `ultra` reasoning · service tier **`fast`** |
| **Grok** | `grok` (implementer) | `grok-4.5` | reasoning **`high`** (CLI max; maps from max/ultra) · more turns |
| **Gemini** | `gemini` (research) | CLI default | **Recorded note:** the July 2026 operator environment hit `IneligibleTierError` / Antigravity migration. Verify the installed CLI rather than assuming that state persists. |
| **Local** | `local` | Ollama / NVFP via separate config | light tests only |

## Apply from a clone

```bash
export NEXUS_PROJECT_ROOT="${NEXUS_PROJECT_ROOT:-$PWD}"

# Set only identifiers/flags supported by your installed providers.
export NEXUS_CODEX_MODEL="<supported-codex-model>"
export NEXUS_CLAUDE_MODEL="<supported-claude-model>"
export NEXUS_GROK_MODEL="<supported-grok-model>"

# Load neutral timeout/turn defaults plus any local overrides you added.
set -a && source "$NEXUS_PROJECT_ROOT/config/max_models.env" && set +a

# Start the bus with your configured values.
cd "$NEXUS_PROJECT_ROOT"
set -a && source config/max_models.env && set +a
nexus start -y

# or campaigns (auto-load config/max_models.env)
PYTHONPATH=src python3 scripts/swe_pro_multi_ai.py --once
PYTHONPATH=src python3 scripts/multi_vendor_live.py --once
```

## Env vars

| Variable | Recorded example |
|----------|---------|
| `NEXUS_CLAUDE_MODEL` | `fable` |
| `NEXUS_CLAUDE_EFFORT` | `max` |
| `NEXUS_CODEX_MODEL` | `gpt-5.6-sol` |
| `NEXUS_CODEX_REASONING` | `ultra` |
| `NEXUS_CODEX_SERVICE_TIER` | `fast` |
| `NEXUS_GROK_MODEL` | `grok-4.5` |
| `NEXUS_GROK_REASONING_EFFORT` | `high` (max allowed by Grok CLI) |
| `NEXUS_GROK_BRIDGE_TURNS` | `12` |
| `NEXUS_GEMINI_MODEL` | (unset = CLI default) |
| `NEXUS_CLI_TIMEOUT_S` | `600` |

Also mirrored in:

- `~/.claude/settings.json` → the operator's Claude model and effort
- `~/.codex/config.toml` → the operator's Codex model, reasoning, and service tier
- `bridge/bridges/stdin_to_grok.py` → `--reasoning-effort` from env

## Role reminder

| Role | Who |
|------|-----|
| Implementer | **Configured Grok model** |
| Adversary / review L2 | **Configured Codex model** |
| Plan / review L1 | **Configured Claude model** |
| Research | **Gemini** |
