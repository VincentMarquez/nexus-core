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
| wshobson/agents | 16 | Single Markdown skill → multi-harness generate/validate/drift |
| builderz-labs/mission-control | 15 | Ops/CLI/MCP parity, packaging hygiene |
| IBM/AssetOpsBench | 15 | Domain MCP + eval harness shape |
| phodal/routa | 15 | Board/evidence export |
| labsai/EDDI | 15 | Config-driven production signals |
| automagik-dev/forge | 15 | HITL + worktree isolation |
| ahmedEid1/lumen | 15 | Phase guards + honest grades |
| MattMagg/MisterSmith | 15 | Supervision / durability OS |
| openai/swarm | 14 | Agent handoff |
| SolaceLabs/solace-agent-mesh | 14 | Event mesh packaging |
| (+ more in IMPROVE_OURS) | | |

### arXiv (latest `improve-rx-406cb98836` + prior)

| Id | Idea for NEXUS |
|----|----------------|
| 2508.08322 | Context engineering packs (landed P1.4) |
| 2510.13343 | Ordered action decisions / next_agent (landed) |
| 2512.03278 | Evidence-linked claims (grade + audit) |
| 2606.20023 | Over-privileged tools → pack `privilege` ladder |
| 2203.08975 | Multi-agent communication survey |
| 2502.07165 | Principle-based multi-agent prompting |
| 2303.16641 | Adversarial hierarchy / zero-trust slices (P11) |

## 3. Prior slices already landed

P0 durability (atomic persist, budgets, taint, state slice, eval memory, stop, verify-promote) · P1 operator board (handoff, veto, replay, explain, cost, prov, graph, evidence, DAG, consensus, context pack, vault, gap seed) · improve_apply FSM · grade_artifact loop · ops_store.

## 4. Open backlog (priority)

| Pri | Item | Source |
|-----|------|--------|
| **P2.1** | **Skillpack generate/validate/drift + privilege filter** | wshobson/agents, 2606.20023 |
| P2.2 | Lightweight OpenAPI-ish tool catalog export for MCP | mission-control |
| P2.3 | Domain MCP eval smoke (AssetOpsBench shape) | IBM/AssetOpsBench |
| P3 | Optional engine review→promote hook | zenith / cycgraph |

## 5. First apply slice (this session) — P2.1

**Implement multi-harness skillpack tooling from a single SKILL.md source.**

### Scope

1. `src/nexus/skillpacks.py`
   - `list_packs` / `validate_pack` / `validate_all`
   - `generate_pack` / `generate_all` → `.nexus_state/generated_skillpacks/`
   - harness adapters: `grok`, `cursor`, `claude`, `codex`, `local`
   - `drift_check` source vs generated
   - `privilege` ladder + `--max-privilege` filter
2. CLI: `nexus skillpacks list|validate|generate|drift`
3. MCP tool: `skillpacks` (`action=list|validate|generate|drift`)
4. Tests: `tests/test_skillpacks.py`
5. Annotate `skillpacks/durable-operator/manifest.json` with `privilege: ops`

### Non-goals

- Do not vendor wshobson monorepo or plugin trees
- Do not implement full Cursor/Claude installers
- No secrets in generated artifacts

### Acceptance criteria

- [x] `nexus skillpacks validate` green on durable-operator
- [x] `generate` + `drift` round-trip
- [x] least-privilege filter drops ops/admin packs when max=read/write
- [x] MCP + CLI parity
- [x] `PYTHONPATH=src python3 -m pytest -q` → 289 passed

## 6. Commands

```bash
nexus skillpacks list
nexus skillpacks validate --json
nexus skillpacks generate
nexus skillpacks drift
PYTHONPATH=src python3 -m pytest -q tests/test_skillpacks.py
```
