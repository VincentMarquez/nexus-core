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
| wshobson/agents | 15 | Multi-harness skillpacks (P2.1 done) |
| builderz-labs/mission-control | 15 | Ops/CLI/MCP parity, OpenAPI tool catalog (P2.2 done) |
| **IBM/AssetOpsBench** | 15 | **Domain MCP eval smoke — scenario→trajectory→scorer (P2.3)** |
| phodal/routa | 15 | Board/evidence export |
| labsai/EDDI | 15 | Production config signals |
| ahmedEid1/lumen | 15 | Phase guards + honest grades |
| Intelligent-Internet/zenith | 14 | Principled stop + independent verify |
| MattMagg/MisterSmith | 15 | Supervision / durability OS |
| gossipcat-ai/gossipcat-ai | 15 | Consensus grading (P1.3 done) |
| (+ more in IMPROVE_OURS) | | |

### arXiv (latest `improve-rx-b6536eed67` + prior)

| Id | Idea for NEXUS |
|----|----------------|
| 2203.08975 | Multi-agent communication survey → tool surface health smoke |
| 2508.08322 | Context engineering packs (landed P1.4) |
| 2510.13343 | Ordered action decisions / next_agent (landed) |
| 2512.03278 | Evidence-linked claims (grade + audit) |
| 2511.15755 | Deterministic multi-agent decision audit |
| 2302.10809 | Causal explain (landed operator board) |
| 2502.07165 | Principle-based multi-agent prompting |

## 3. Prior slices already landed

P0 durability · P1 operator board (handoff, veto, replay, explain, cost, prov, graph, evidence, DAG, consensus, context pack, vault, gap seed) · improve_apply FSM · grade_artifact · ops_store · **P2.1 skillpacks** · **P2.2 tool_catalog**.

## 4. Open backlog (priority)

| Pri | Item | Source | Status |
|-----|------|--------|--------|
| P2.1 | Skillpack generate/validate/drift + privilege filter | wshobson/agents | **done** |
| P2.2 | OpenAPI-ish tool catalog export for MCP | mission-control | **done** |
| **P2.3** | **Domain MCP eval smoke (AssetOpsBench shape)** | IBM/AssetOpsBench | **this session** |
| P3 | Optional engine review→promote hook | zenith / cycgraph | **this session (opt-in)** |

## 5. First apply slice (this session) — P2.3 + P3

### P2.3 — Domain MCP eval smoke

**AssetOpsBench-shaped offline suite: scenarios → MCP `call_tool` trajectories → code-based scorers → pass-rate report.**

#### Scope

1. `src/nexus/mcp_eval.py`
   - Built-in domain scenarios (workspace, status, vault, catalog, grade, skill, ops, context, gap)
   - Scorers: `tool_ok`, `is_error`, `contains`, `contains_all`, `json_keys`, `json_path_eq`, `no_secret_leak`
   - `evaluate` / `export_report` / `run_and_export` (`nexus.mcp_eval/v1`)
2. CLI: `nexus eval list|smoke|run`
3. MCP tool: `mcp_eval` (`action=list|run|smoke`)
4. Privilege tag in tool catalog
5. Tests: `tests/test_mcp_eval.py`

### P3 — Review → promote (opt-in)

1. `src/nexus/engine.py` — `_maybe_promote_after_review` when `meta.promote_on_review`
2. Journal `promote` / `promote_denied`; optional taint promote via `meta.promote_keys`
3. Fail-closed when `meta.promote_require` and verify denies
4. Tests in `tests/test_engine.py`

### Non-goals

- Do not vendor AssetOpsBench monorepo / IoT fixtures / LLM-as-judge
- Do not force promote on every review (opt-in only)
- No secrets in eval reports

### Acceptance criteria

- [x] Built-in suite passes offline against live MCP tools
- [x] Path jail scenario expects error
- [x] Catalog validate scenario requires `ok: true`
- [x] Vault status never secret-leaks
- [x] CLI + MCP parity (`list` / `smoke`)
- [x] Export writes `report.json` + `trajectories.jsonl` + `summary.md`
- [x] Opt-in promote records journal event; require path fail-closes
- [x] `PYTHONPATH=src python3 -m pytest -q` green

## 6. Commands

```bash
nexus eval list --json
nexus eval smoke --domain catalog,status --max-privilege read
nexus eval smoke --path . --json
PYTHONPATH=src python3 -m pytest -q tests/test_mcp_eval.py tests/test_engine.py
```
