# Latest improve plan (from full self-improve cycle)

_Generated 2026-07-15 · Grok 4.5 hard-apply · 10+ repos + 20 arXiv_

Model: `grok-4.5` · sources: `.nexus_state/repo_mine/IMPROVE_OURS.md` + arXiv `rx-ae18c1bce0` / prior notes

---

## Goal

Self-improve nexus-core from mined multi-agent repos + arXiv, with **small, tested** slices. Prefer patterns (not vendored trees) from `.nexus_workspaces/scout_repos/`.

## Evidence already landed (prior cycles)

P0 durability (atomic persist, budgets, taint, state slice, eval memory, principled stop, independent verify) · P1 ops plane / DAG / consensus / context pack / vault+gaps · P2 skillpacks / tool catalog / MCP eval packs · P3 review→promote + improve_apply / alive promote gate · sample fixtures + Ollama judge.

## First apply slice (this session) — P2.7 + P3.3 + CI

Close the open items from the previous hard-apply cycle:

1. **Grok LLM-as-judge adapter** (same `set_llm_judge` hook as Ollama)
2. **Auto-wire `promote_on_done` when self_approve lands real apply**
3. **CI sample-pack smoke** (`--install-samples --tag sample --no-builtin`)

### P2.7 — Grok judge adapter

| API | Behavior |
|-----|----------|
| `make_grok_judge(model=, timeout=)` | Grok CLI, tools off, JSON schema ok/score/reason |
| Offline | heuristic keyword fallback (CI-safe) |
| Env | `NEXUS_MCP_EVAL_LLM_JUDGE=grok\|auto\|ollama\|1` |
| `auto` | prefer Grok if CLI on PATH, else Ollama |
| CLI | `nexus eval smoke --llm-judge` |

Patterns: multi-LLM tool agents (arXiv **2401.07324**); AssetOpsBench judge scorer; wshobson/mission-control adapter surface.

### P3.3 — alive promote when self_approve applies

| Rule | Effect |
|------|--------|
| `cfg.promote_on_done` | always run IndependentVerify gate (existing) |
| auto | if `self_approve` + `apply` + tests green **and** `self_approve_apply` step ok → run promote even when knob is false |
| report | auto steps tagged `auto=true`, `auto_reason=self_approve_apply` |

Patterns: zenith independent validation; cycgraph promote; lumen decision audit.

### CI — sample pack smoke

| Surface | Command |
|---------|---------|
| `.github/workflows/ci.yml` | `nexus eval smoke --install-samples --tag sample --no-builtin --no-export` |
| `make eval-samples` | same offline path locally |

## Success criteria

- [x] `make_grok_judge` falls back offline without network / without CLI
- [x] `NEXUS_MCP_EVAL_LLM_JUDGE=grok|auto|ollama` selects the right adapter
- [x] self_approve apply landing auto-triggers promote gate
- [x] CI runs sample pack smoke offline
- [x] `pytest` green

## Non-goals

- No vendored AssetOpsBench industrial IoT trees
- No force-push / secrets in packs or reports
- No always-on promote for planning-only cycles

## Next open

- Optional live Grok judge integration test (gated, not default CI)
- Wire full-cycle demo script flag for `--llm-judge auto`
- Expand sample packs with a consensus/context scenario

## Commands

```bash
# sample packs offline (CI)
make eval-samples
# or:
nexus eval smoke --install-samples --tag sample --no-builtin --no-export

# optional LLM judge (Grok preferred under auto; falls back offline)
NEXUS_MCP_EVAL_LLM_JUDGE=auto nexus eval smoke --llm-judge --no-export
NEXUS_MCP_EVAL_LLM_JUDGE=grok nexus eval smoke --llm-judge --no-export

# alive: self_approve apply auto-runs promote; or set promote_on_done true
# .nexus_state/alive.json → self_approve/apply/promote_on_done

PYTHONPATH=src python3 -m pytest -q
```
