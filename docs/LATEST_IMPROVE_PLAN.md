# Latest improve plan (from full self-improve cycle)

_Generated 2026-07-15 · Grok 4.5 hard-apply · 10+ repos + 20 arXiv_

Model: `grok-4.5` · sources: `.nexus_state/repo_mine/IMPROVE_OURS.md` + arXiv `rx-3c113dc2aa` / prior notes

---

## Goal

Self-improve nexus-core from mined multi-agent repos + arXiv, with **small, tested** slices. Prefer patterns (not vendored trees) from `.nexus_workspaces/scout_repos/`.

## Evidence already landed (prior cycles)

P0 durability (atomic persist, budgets, taint, state slice, eval memory, principled stop, independent verify) · P1 ops plane / DAG / consensus / context pack / vault+gaps · P2 skillpacks / tool catalog / MCP eval · P3 review→promote + improve_apply promote gate.

## First apply slice (this session) — P2.6 + P2.5 + P3.2

Close the open items from the previous hard-apply cycle:

1. **Sample scenario pack fixtures** (in-repo, AssetOpsBench shape)
2. **Wire `promote_on_done` from alive cycle**
3. **Optional real LLM judge adapter** (Ollama, offline fallback)

### P2.6 — sample packs under `fixtures/mcp_eval/packs/`

`.nexus_state/` is gitignored, so samples **ship** under committed fixtures and install on demand:

| Path | Role |
|------|------|
| `fixtures/mcp_eval/packs/operator_smoke.json` | read-only operator surface |
| `fixtures/mcp_eval/packs/privilege_safety.json` | path jail + vault no-leak + catalog validate |
| `src/nexus/mcp_eval.py` | `bundled_packs_dir`, `list_bundled_packs`, `ensure_sample_packs` |
| CLI | `nexus eval packs --install-samples` · `nexus eval smoke --install-samples` |

Patterns: IBM/AssetOpsBench `scenarios/*.json`; mission-control CLI/export parity.

### P2.5 — Ollama LLM-as-judge adapter

| API | Behavior |
|-----|----------|
| `make_ollama_judge(host=, model=)` | HTTP `/api/generate` JSON ok/score/reason |
| Offline | heuristic keyword fallback (CI-safe) |
| Env | `NEXUS_MCP_EVAL_LLM_JUDGE=1` + optional `NEXUS_OLLAMA_*` |
| CLI | `nexus eval smoke --llm-judge` |

Patterns: AssetOpsBench judge scorer; small multi-LLM tool agents (arXiv 2401.07324).

### P3.2 — alive `promote_on_done`

| Knob | Default | Effect |
|------|---------|--------|
| `AliveConfig.promote_on_done` | `false` | After self_check, run dry `ImproveApplyRun` with IndependentVerify |
| `AliveConfig.promote_require` | `false` | Fail-closed (block cycle) when verify denies |

Patterns: zenith independent validation; cycgraph promote gate; lumen decision audit path.

## Success criteria

- [x] Sample packs load as `nexus.scenario_pack/v1` and install into `.nexus_state/mcp_eval/packs/`
- [x] `nexus eval packs --install-samples` reports installed/skipped
- [x] Ollama judge adapter falls back offline without network
- [x] Alive config round-trips promote knobs; green checks → promote ok
- [x] `pytest` green

## Non-goals

- No vendored AssetOpsBench industrial IoT trees
- No force-push / secrets in packs or reports
- No full multi-grader panel (consensus already exists)

## Next open

- Wire `promote_on_done=true` in full-cycle alive demos when self_approve lands real apply
- Optional Grok (not only Ollama) judge adapter behind same `set_llm_judge` hook
- Scenario pack CI job: `eval smoke --install-samples --tag sample --no-builtin`

## Commands

```bash
# install samples + discover
nexus eval packs --install-samples
nexus eval smoke --install-samples --tag sample --no-builtin --no-export

# optional LLM judge (Ollama; falls back offline)
NEXUS_MCP_EVAL_LLM_JUDGE=1 nexus eval smoke --llm-judge --no-export

# alive promote wire (opt-in)
# set promote_on_done / promote_require in .nexus_state/alive.json

PYTHONPATH=src python3 -m pytest -q
```
