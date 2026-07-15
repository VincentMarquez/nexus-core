# Latest improve plan (from full self-improve cycle)

**Grok 4.5 hard-apply — 2026-07-15**  
Model: `grok-4.5` · sources: 20 mined repos (IMPROVE_OURS) + 20 arXiv notes

---

## First apply slice (this session) — landed

### Preference rank bias + board-sync CI + mission-control spend pattern

| Pass criterion | Status |
|----------------|--------|
| `preference_boost` applied inside `select_candidates` rank | ✅ `rank_score(..., preference_delta=)` + `use_preference` |
| Candidate rows expose `preference_boost` | ✅ board / select format show `pref=` |
| Offline better>worse pairs bias ranking (arXiv **2602.04518**) | ✅ `preference_pairs.preference_boost` |
| CI/Makefile `board --sync-gaps` smoke | ✅ `smoke_board_sync` + `make board-sync-gaps` |
| Pattern catalog: mission-control spend skill | ✅ `mission-control-spend-ops` |
| pytest green | ✅ full suite |

**Modules:** `src/nexus/apply_select.py`, `src/nexus/worktree_apply.py`, `src/nexus/preference_pairs.py`  
**Tests:** `tests/test_apply_select.py`, `tests/test_worktree_apply.py`  
**Ops:** `Makefile` (`board-sync-gaps`, `test-quality`), `.github/workflows/ci.yml`

**Patterns (shape only, not vendored trees):**  
builderz-labs/mission-control (spend/ops), codingagentsystem/cas (FTS board), wshobson/agents (skill SoT), Intelligent-Internet/zenith (stop/replan), arXiv **2602.04518** preference pairs, **2511.15755** decision package, **2601.00360** anti-collusion.

### Prior slices still green

- Board signal → PrincipledStop gaps + preference pair store
- Decision package → worktree_apply + alive self_approve
- Grade claims + MCP FTS evidence
- Worktree apply + promote-to-main
- Durable MCP context, skillpacks, tool catalog, mcp_eval, ops, consensus, DAG

---

## First apply slice — scope (this session)

**Goal:** Close prior open items: *preference_boost in select rank · CI board --sync-gaps · mission-control spend pattern*.

### Do

1. **Preference rank** — `select_candidates` adds offline pair boost to composite rank (default on; `use_preference=False` to disable).
2. **Board sync smoke** — pure `smoke_board_sync()` + Makefile/CI quality gate (no live Grok).
3. **Pattern catalog** — `mission-control-spend-ops` skillpack (ops list/spend/status commands).

### Explicit non-goals

- No live preference IRL training loop
- No vendored upstream trees
- No force-push / auto-promote without flags
- No live Grok judge in unit tests

---

## Next open (P1+)

| Item | Notes |
|------|--------|
| Preference brief inject into context_pack | small |
| Wire `use_preference` CLI flag on `improve select\|board` | operator control |
| Live Grok judge gated integration (optional CI secret) | offline fallback already |
| Alive cycle: auto `record_from_ranked` when board continues | optional |

---

## Evidence sources (this cycle)

- `.nexus_state/repo_mine/IMPROVE_OURS.md` — top: labsai/EDDI 17, wshobson/agents 16, MisterSmith 16, mission-control 15, cas 15, …
- `.nexus_state/arxiv_improve/improve-rx-1bccfca000.md` — communication survey **2203.08975**, context **2508.08322**, Thucy **2512.03278**, AOAD-MAT **2510.13343**, principles **2502.07165**
- Prior plan open items from hard-apply board→gaps + preferences cycle

---

## Commands

```bash
# preference-biased select
nexus improve prefer record --better wshobson/agents --worse openai/swarm
nexus improve select --fixture fixtures/mine_eval/grades_with_claims.json
# board + gap sync smoke
make board-sync-gaps
# third pattern
nexus improve apply --mode sandbox --pattern mission-control-spend-ops \
  --fixture tests/fixtures/mine_eval_sample.json --no-require-decision
PYTHONPATH=src python3 -m pytest -q
make test-quality
```
