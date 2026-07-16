# Latest improve plan (from full self-improve cycle)

_Generated 2026-07-16 · Grok 4.5 hard-apply session_

Model: `grok-4.5` · mine sources: `.nexus_state/repo_mine/IMPROVE_OURS.md` (score ≥ 10) · arXiv: `improve-rx-4e382a3fbf` (+ priors)

---

## Goal

Self-improve **nexus-core** from mined multi-agent repos + arXiv durable-workflow / communication papers. Prefer small, tested pattern ports (no vendored trees). Keep `pytest` green.

## Evidence used

| Source | Top signals |
|--------|-------------|
| labsai/EDDI (17) | config-driven routing, middleware hygiene |
| wshobson/agents (16) | Markdown SoT → multi-harness skillpacks |
| MattMagg/MisterSmith (16) | supervised runtime + hard caps |
| mission-control / routa / cas / soul (15) | ops board, FTS, immutable ledger |
| Intelligent-Internet/zenith (14) | principled stop, verify-before-done |
| escapeboy/agent-fleet-o (13) | fleet DAG + HITL dual-control |
| arXiv multi-stage **2604.03350**, AOAD-MAT **2510.13343**, PROV **2508.02866**, checkpoint **2310.12670**, decision package **2511.15755**, anti-collusion **2601.00360** | ordered stages, provenance, dual-control |

## Already landed (prior cycles)

P0–P3 durability, task operator surface, improve_apply FSM, ops store, DAG, consensus, context_pack, vault/gaps, skillpacks, tool catalog, mcp_eval + Grok judge (offline default), worktree apply + promote, FTS select + roles + board, preference rank, grade_ledger, work_ledger dual-control, improve_spine dual-write, spine board rank + method on evidence_refs, MisterSmith/solace patterns.

## First apply slice (this session)

Close open items from last cycle:

1. **decision_package `use_spine` CLI flag** — `nexus improve decide --no-spine|--no-preference|--run-id` parity with select/board; decision package selection cites spine.
2. **spine method on board text lines** — `format_board` / `format_selection` show `method=…` for durable grades.
3. **pattern catalog** — `zenith-principled-stop-ops` + `agent-fleet-ops` (pattern only).
4. **optional nightly live judge** — `make eval-live-judge` (opt-in `NEXUS_LIVE_GROK_JUDGE=1`; not default CI).

### Success criteria

- [x] `decision_package(use_spine=True)` emits `spine:method:` refs; `use_spine=False` does not
- [x] Board text includes `method=grok:…` when on spine
- [x] `list_patterns()` includes zenith + agent-fleet; sandbox apply validates
- [x] `make eval-live-judge` documented; offline unit tests skip live path
- [x] `PYTHONPATH=src python3 -m pytest -q` green

### Non-goals

- No vendored monorepos / Laravel / Rust crates
- No force-push; no auto-promote without flags
- No live Grok in default CI

## P0 backlog (next sessions)

| ID | Item | Notes |
|----|------|-------|
| P0.1 | alive auto `record_from_ranked` preference | when board ranks ≥2 |
| P0.2 | spine method on MCP `apply_select` status text | operator parity |
| P0.3 | more sample pack scenarios | privilege + promote edge cases |
| P0.4 | plan-reuse cache (arXiv 2512.21309) | reuse prior apply plan digests |

## Commands

```bash
nexus improve board --run-id <id>
nexus improve decide --repo wshobson/agents --run-id <id>
nexus improve decide --no-spine   # fixture-only rank
nexus improve apply --list-patterns
make eval-samples
# optional nightly:
NEXUS_LIVE_GROK_JUDGE=1 make eval-live-judge
PYTHONPATH=src python3 -m pytest -q
```
