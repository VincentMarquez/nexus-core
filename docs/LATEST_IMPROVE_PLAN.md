# Latest improve plan (from full self-improve cycle)

**Grok 4.5 hard-apply — 2026-07-15**  
Model: `grok-4.5` · sources: 10+ mined repos (IMPROVE_OURS) + 20 arXiv notes

---

## Landed this session (First apply slice)

### Wire decision_package → worktree_apply + alive self_approve + board stop/replan

| Pass criterion | Status |
|----------------|--------|
| `decision_for_grade` builds terminal package from loaded grade (claims/path evidence) | ✅ `apply_select.decision_for_grade` |
| `run_apply` records decision + fail-closes on deny when `require_decision` (default) | ✅ `worktree_apply.run_apply` |
| Role collusion blocks apply (anti-collusion **2601.00360**) | ✅ ledger agent `decide` + tests |
| Board signal ∈ {continue, replan, stop} (zenith / MAEBE) | ✅ `board_signal` + `improve_board.signal` |
| Alive self_approve consults board before hard apply | ✅ `_self_approve_decision_gate` |
| pytest green | ✅ full suite |

**Modules:** `src/nexus/apply_select.py`, `src/nexus/worktree_apply.py`, `src/nexus/alive.py`, `src/nexus/cli.py`  
**Tests:** `tests/test_apply_select.py`, `tests/test_worktree_apply.py`, `tests/test_usage_alive.py`

**Patterns (shape only, not vendored trees):**  
wshobson/agents, cas/forge worktree, mission-control/Network-AI budgets, routa board, zenith stop/replan, arXiv **2511.15755** decision package, **2601.00360** anti-collusion, **2506.03053** MAEBE thrash signals, **2512.03278** Thucy claims.

### Prior slices still green

- Grade claims + MCP FTS evidence (`grade_artifact`, `evidence_fts`)
- Apply select + role gate + decision package (`apply_select`)
- Worktree apply + promote-to-main (`worktree_apply`)
- Durable MCP context loop (`context_store`)
- Skillpacks / tool catalog / mcp_eval / ops_store / consensus / DAG

---

## First apply slice (this session) — scope

**Goal:** Close the open item from the prior cycle: *wire decision_package into worktree_apply / alive self_approve · board stop/replan signals*.

### Do

1. **Decision gate on apply** — after claim_verify, before plan_apply, build `nexus.decision_package/v1` and refuse apply on deny / stop / replan when `require_decision=True` (default).
2. **Board signals** — `continue` | `replan` | `stop` from decision + roles + principled stop + low confidence.
3. **Alive self_approve** — run improve board + decision gate; skip apply with auditable `skip_reason` when not `continue`.
4. **CLI** — `nexus improve apply --no-require-decision` / role flags; board shows SIGNAL line.

### Explicit non-goals

- No preference-pair rubric learning (P2.3 next)
- No vendored upstream trees
- No force-push / auto-promote without flags

---

## Next open (P1+)

| Item | Notes |
|------|--------|
| Preference-pair rubric learning | arXiv **2602.04518** — store better/worse apply pairs offline |
| Wire board signal into PrincipledStop gap board auto | replan → register gap; stop → stop.watch exit |
| More pattern catalog entries beyond markdown-skill-sot | cas FTS pack, mission-control spend skill |
| Live Grok judge gated integration (optional CI secret) | already offline fallback |

---

## Evidence sources (this cycle)

- `.nexus_state/repo_mine/IMPROVE_OURS.md` — top: wshobson/agents 16, mission-control / cas / lumen / MisterSmith / EDDI / …
- `.nexus_state/arxiv_improve/improve-rx-27056d5405.md` — communication survey, multi-LLM tools, context engineering, AOAD-MAT, Thucy, over-privileged tools, preference IRL, adversarial hierarchy, principles

---

## Commands

```bash
# board with stop/replan signal
nexus improve board --fixture fixtures/mine_eval/grades_with_claims.json
# decision package
nexus improve decide --repo wshobson/agents
# worktree apply (decision required by default)
nexus improve apply --mode sandbox --fixture tests/fixtures/mine_eval_sample.json
PYTHONPATH=src python3 -m pytest -q
```
