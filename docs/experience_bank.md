# Experience Bank (SWE-Exp)

Offline-first store for abstracted repair patterns shaped after
[SWE-Exp](https://arxiv.org/abs/2507.23361v2)
(*Experience-Driven Software Issue Resolution*).

Schema: `nexus.experience_bank/v1`  
Module: `src/nexus/experience_bank.py`  
Store: `.nexus_state/experience_bank.jsonl` (append-only via `persist`)

## Core loop

```
issue text / type → classify → record(success|failure|prior) → recommend
```

Brief form used in prompts:

> If issue type `X`, try approach first: `Y`

Failure-dominant buckets render as **AVOID** instead of try-first.

## API (selected)

| Function | Role |
|----------|------|
| `record` / `record_from_repair` | Append one experience (fail-closed on empty approach / bad outcome) |
| `load` | Read rows; skips corrupt/unknown-outcome lines; newest window when capped |
| `recommend` | Laplace-smoothed ranks; **per-type** catalog priors when no success yet |
| `format_recommend_block` | Markdown brief for context packs / dual-review |
| `harvest_from_implement_results` | Ingest implement results with **abstracted** approaches |
| `seed_priors` | Persist `DEFAULT_PRIORS` once (idempotent, single-process) |
| `stats` | Operator snapshot (`n`, `n_total`, `truncated`) |

## Cold start

Catalog priors are merged **in memory per issue type** when that type has no
success evidence — a partially filled bank still answers every catalog type.
`seed_priors()` writes them to disk once if you want durable priors.

## Harvest rules

- Prefer structured `approach` / `repair_approach` / `pattern` / `summary`.
- Success without approach → constant
  `"Implement landed via standard tests/verify path"` (repo id in `repo`/`meta`).
- Failure without approach → **skipped** (no per-rid singleton pollution).
- `ok` must be a clear boolean / 0 / 1 / `"true"` / `"false"` (else skip).

## CLI

```bash
PYTHONPATH=src python3 -m nexus.experience_bank --path . seed
PYTHONPATH=src python3 -m nexus.experience_bank --path . recommend \
  --issue-text "ModuleNotFoundError: No module named 'x'"
PYTHONPATH=src python3 -m nexus.experience_bank --path . --json stats
```

## Non-goals (current)

- No vendored SWE-Exp / SWE-bench trees.
- Confidence / timestamp are metadata-only (not scored in v1).
- Orchestrator auto-harvest + prompt injection remain opt-in (flag-gated next).
