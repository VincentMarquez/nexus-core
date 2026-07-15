# Latest improve plan (from full self-improve cycle)

_Generated 2026-07-15 · Grok 4.5 hard-apply session_

Model: `grok-4.5` · mined repos ≥10 · arXiv improve notes under `.nexus_state/arxiv_improve/`

---

## 1. Goal

Self-improve **nexus-core** from mined multi-agent repos + arXiv papers: small, tested ports of patterns (not vendored trees). Keep `pytest` green.

## 2. Evidence used

### Mined repos (IMPROVE_OURS, score ≥ 10)

| Repo | Score | Pattern to port |
|------|------:|-----------------|
| **IBM/AssetOpsBench** | 15 | **JSON scenario packs + static/judge scorers (P2.4)** |
| Intelligent-Internet/zenith | 13 | Independent verify before close/promote (P3.1) |
| wmcmahan/cycgraph (prior) | — | Promote-gate discipline (already in durability) |
| builderz-labs/mission-control | 15 | CLI/MCP/export parity |
| ahmedEid1/lumen | 15 | Phase guards + honest grades |
| wshobson/agents | 16 | Multi-harness skillpacks (done P2.1) |
| phodal/routa | 15 | Board/evidence export |
| labsai/EDDI | 16 | Production config signals |
| (+ more in IMPROVE_OURS) | | |

### arXiv (latest `improve-rx-0a75f9514d` + prior)

| Id | Idea for NEXUS |
|----|----------------|
| 2203.08975 | Multi-agent communication survey → tool surface health smoke |
| 2511.15755 | Deterministic multi-agent decision audit |
| 2508.08322 | Context engineering packs (landed P1.4) |
| 2510.13343 | Ordered action decisions / next_agent (landed) |
| 2512.03278 | Evidence-linked claims (grade + audit) |
| 2310.12670 | Fault-tolerant checkpointing |
| 2508.02866 | PROV-AGENT provenance (landed operator board) |

## 3. Prior slices already landed

P0 durability · P1 operator board · improve_apply FSM · grade_artifact · ops_store · skillpacks · tool_catalog · **P2.3 domain MCP eval smoke** · **P3 engine review→promote** · context pack · vault · gap seed · consensus · DAG.

## 4. Open backlog (priority)

| Pri | Item | Source | Status |
|-----|------|--------|--------|
| P2.3 | Domain MCP eval smoke | AssetOpsBench | **done** |
| P3 | Engine review→promote hook | zenith / cycgraph | **done** |
| **P2.4** | **JSON scenario packs + pack CLI/MCP** | AssetOpsBench scenarios/*.json | **this session** |
| **P2.5** | **Optional llm_judge scorer (pluggable; offline fallback)** | AssetOpsBench static_json / judge | **this session** |
| **P3.1** | **improve_apply promote gate wiring** | zenith IndependentVerify | **this session** |

## 5. First apply slice (this session) — P2.4 + P2.5 + P3.1

### P2.4 — JSON scenario packs

**Load AssetOpsBench-shaped JSON packs and merge with the built-in suite.**

#### Scope

1. `src/nexus/mcp_eval.py`
   - `nexus.scenario_pack/v1` load/write/merge/discover
   - Alias map for AssetOpsBench fields (`type`→domain, `args`→arguments, `characteristic_form`→expected)
   - `evaluate` / `list_scenarios` / `run_and_export` accept `--pack` / discover
2. CLI: `nexus eval list|smoke|run|packs` with `--pack`, `--no-builtin`, `--discover-packs`
3. MCP tool `mcp_eval`: `pack`, `no_builtin`, `discover_packs`, action `packs`
4. Tests: pack load/merge/discover/CLI

### P2.5 — Optional LLM-as-judge (offline-safe)

1. Scorers: `heuristic_judge`, `llm_judge` (injected callable; fallback to heuristic)
2. Fail-closed only when `expected.require_llm=true` and no judge registered
3. Alias `static_json` → `json_path_eq`

### P3.1 — improve_apply promote gate

1. `ImproveApplyRun._promote_gate()` before `done` when `meta.promote_on_done`
2. Uses `IndependentVerify` (cross-agent by default; degraded same-agent for demos)
3. Fail-closed on `meta.promote_require`; soft-deny still completes
4. Timeline events `promote` / `promote_denied`; `meta.promote` audit blob

### Non-goals

- Do not vendor AssetOpsBench monorepo / IoT fixtures
- Do not call network LLMs in default CI path
- Do not force promote on every improve-apply run (opt-in only)

### Acceptance criteria

- [x] Load pack object / bare array / single scenario JSON
- [x] Pack id overrides builtin when merged
- [x] `nexus eval smoke --pack … --no-builtin` green offline
- [x] `heuristic_judge` / `llm_judge` fallback + require_llm fail-closed
- [x] improve_apply promote pass journals `promote`; require path stays at `audited`
- [x] `PYTHONPATH=src python3 -m pytest -q` green

## 6. Commands

```bash
nexus eval packs --json
nexus eval list --pack path/to/pack.json --no-builtin --json
nexus eval smoke --pack path/to/pack.json --discover-packs --max-privilege read
PYTHONPATH=src python3 -m pytest -q tests/test_mcp_eval.py tests/test_improve_apply.py
```
