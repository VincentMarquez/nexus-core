# Latest improve plan (from full self-improve cycle)

**Grok 4.5 hard-apply — 2026-07-15**  
Model: `grok-4.5` · sources: 20 mined repos (IMPROVE_OURS) + 20 arXiv notes

---

## Landed this session (First apply slice)

### Board signal → PrincipledStop gaps + preference pairs + pattern catalog

| Pass criterion | Status |
|----------------|--------|
| `sync_signal_to_stop` maps replan→`board-replan`, stop→`board-stop` | ✅ `apply_select.sync_signal_to_stop` |
| Hard stop (collusion/budget/principled) can abort stop board for watch exit | ✅ `abort_on_hard_stop` |
| Continue closes board signal gaps | ✅ `close_on_continue` |
| Alive self_approve gate syncs gaps + optional preference pair | ✅ `_self_approve_decision_gate` |
| Principled stop re-syncs board signal each cycle | ✅ `_record_principled_stop` |
| Offline preference pairs (arXiv **2602.04518**) | ✅ `preference_pairs.py` + `nexus improve prefer` |
| Second worktree pattern: `cas-evidence-board-ops` | ✅ `worktree_apply.PATTERN_CATALOG` |
| CLI `board --sync-gaps` / `--record-pref` | ✅ `cli.py` |
| pytest green | ✅ full suite |

**Modules:** `src/nexus/apply_select.py`, `src/nexus/alive.py`, `src/nexus/preference_pairs.py`, `src/nexus/worktree_apply.py`, `src/nexus/cli.py`  
**Tests:** `tests/test_apply_select.py`, `tests/test_preference_pairs.py`, `tests/test_usage_alive.py`, `tests/test_worktree_apply.py`

**Patterns (shape only, not vendored trees):**  
Intelligent-Internet/zenith (stop/replan/gap), codingagentsystem/cas (FTS evidence skill), mission-control/routa (board), wshobson/agents (skill SoT), arXiv **2602.04518** preference pairs, **2601.00360** anti-collusion, **2511.15755** decision package, **2506.03053** MAEBE thrash.

### Prior slices still green

- Decision package → worktree_apply + alive self_approve + board signals
- Grade claims + MCP FTS evidence
- Worktree apply + promote-to-main
- Durable MCP context loop, skillpacks, tool catalog, mcp_eval, ops, consensus, DAG

---

## First apply slice (this session) — scope

**Goal:** Close prior open items: *wire board signal into PrincipledStop gap board · preference-pair store · more pattern catalog*.

### Do

1. **Board → gap board** — replan registers `board-replan`; stop registers `board-stop` (hard stops abort); continue closes board gaps.
2. **Alive wire** — self_approve decision gate + principled stop cycle both sync signals; knobs `sync_board_gaps` / `abort_on_board_stop` / `record_preferences`.
3. **Preference pairs** — offline JSONL better>worse pairs + boost/brief for later ranking bias.
4. **Pattern catalog** — `cas-evidence-board-ops` skillpack (evidence board operator docs).

### Explicit non-goals

- No live preference IRL training loop
- No vendored upstream trees
- No force-push / auto-promote without flags

---

## Next open (P1+)

| Item | Notes |
|------|--------|
| Use `preference_boost` inside `select_candidates` rank | small rank delta from offline pairs |
| CI job for `board --sync-gaps` smoke | operator gate regression |
| Live Grok judge gated integration (optional CI secret) | already offline fallback |
| More pattern catalog (mission-control spend skill) | optional |

---

## Evidence sources (this cycle)

- `.nexus_state/repo_mine/IMPROVE_OURS.md` — top: wshobson/agents, mission-control, cas, lumen, zenith, forge, …
- `.nexus_state/arxiv_improve/improve-rx-a7bfdd595a.md` — communication survey, context **2508.08322**, Thucy **2512.03278**, preference IRL **2602.04518**, decision package **2511.15755**, anti-collusion **2601.00360**, MAEBE **2506.03053**

---

## Commands

```bash
# board + sync signal onto gap board
nexus improve board --fixture fixtures/mine_eval/grades_with_claims.json --sync-gaps
# preference pairs
nexus improve prefer record --better wshobson/agents --worse openai/swarm
nexus improve prefer list
# second pattern
nexus improve apply --mode sandbox --pattern cas-evidence-board-ops \
  --fixture tests/fixtures/mine_eval_sample.json --no-require-decision
PYTHONPATH=src python3 -m pytest -q
```
