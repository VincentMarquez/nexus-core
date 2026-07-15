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
| wshobson/agents | 16 | Single Markdown skill → multi-harness generate/validate/drift (P2.1) |
| builderz-labs/mission-control | 15 | Ops/CLI/MCP parity, **openapi.json tool catalog (P2.2)** |
| IBM/AssetOpsBench | 15 | Domain MCP + eval/smoke harness shape |
| phodal/routa | 15 | Board/evidence export |
| labsai/EDDI | 15 | Config-driven production signals |
| automagik-dev/forge | 15 | HITL + worktree isolation |
| ahmedEid1/lumen | 15 | Phase guards + honest grades |
| MattMagg/MisterSmith | 15 | Supervision / durability OS |
| Network-AI | 14 | Dual packaging / catalog export hygiene |
| (+ more in IMPROVE_OURS) | | |

### arXiv (latest `improve-rx-36f52aff73` + prior)

| Id | Idea for NEXUS |
|----|----------------|
| 2508.08322 | Context engineering packs (landed P1.4) |
| 2510.13343 | Ordered action decisions / next_agent (landed) |
| 2512.03278 | Evidence-linked claims (grade + audit) |
| 2606.20023 | Over-privileged tools → privilege ladder on packs **and tools** |
| 2203.08975 | Multi-agent communication survey |
| 2511.15755 | Deterministic multi-agent decision audit |
| 2302.10809 | Causal explain (landed operator board) |

## 3. Prior slices already landed

P0 durability · P1 operator board (handoff, veto, replay, explain, cost, prov, graph, evidence, DAG, consensus, context pack, vault, gap seed) · improve_apply FSM · grade_artifact · ops_store · **P2.1 skillpacks**.

## 4. Open backlog (priority)

| Pri | Item | Source | Status |
|-----|------|--------|--------|
| P2.1 | Skillpack generate/validate/drift + privilege filter | wshobson/agents, 2606.20023 | **done** |
| **P2.2** | **Lightweight OpenAPI-ish tool catalog export for MCP** | mission-control | **this session** |
| P2.3 | Domain MCP eval smoke (AssetOpsBench shape) | IBM/AssetOpsBench | open (partial: catalog validate smoke) |
| P3 | Optional engine review→promote hook | zenith / cycgraph | open |

## 5. First apply slice (this session) — P2.2

**Export MCP `TOOLS[]` as a privilege-tagged catalog + OpenAPI 3.1 document (mission-control-shaped).**

### Scope

1. `src/nexus/tool_catalog.py`
   - `build_entries` / `build_catalog` (`nexus.tool_catalog/v1`)
   - `build_openapi` (OpenAPI 3.1, `POST /tools/{name}`)
   - `validate_tools` (unique names, required⊆properties, path parity)
   - `export_catalog` → `.nexus_state/tool_catalog/`
   - privilege ladder + `--max-privilege` filter
2. CLI: `nexus tools list|validate|catalog|openapi|export`
3. MCP tool: `tool_catalog` (`action=list|validate|export|openapi|catalog`)
4. HTTP: `GET /openapi.json` + `GET /catalog.json`
5. Tests: `tests/test_tool_catalog.py`

### Non-goals

- Do not vendor mission-control monorepo or full REST product API
- Do not implement auth / multi-tenant OpenAPI servers
- No secrets in catalog artifacts

### Acceptance criteria

- [x] Live `mcp_server.TOOLS` validates clean
- [x] Every tool gets an OpenAPI path + privilege tag
- [x] least-privilege filter drops write/ops when max=read
- [x] MCP + CLI + HTTP parity
- [x] export writes `catalog.json` + `openapi.json` + `summary.md`
- [x] `PYTHONPATH=src python3 -m pytest -q` green

## 6. Commands

```bash
nexus tools list --max-privilege write
nexus tools validate --json
nexus tools export
nexus tools openapi --out .nexus_state/tool_catalog/openapi.json
PYTHONPATH=src python3 -m pytest -q tests/test_tool_catalog.py
```
