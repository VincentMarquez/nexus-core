# Latest improve plan (from full self-improve cycle)

**Source:** Grok 4.5 graded mine + arXiv research (EVIDENCE)  
**Target:** `/path/to/nexus-core`  
**Generated / hard-apply session:** 2026-07-15 (Grok 4.5 CLI worker)

---

## Landed this session — First apply slice **P0.5**

| Item | Module | Status |
|------|--------|--------|
| **P0.1–P0.4 + P0.6** ledger / stages / loader / claim_verify / smoke | prior cycle | **done** |
| **P0.5 Worktree-isolated apply** | `src/nexus/worktree_apply.py` | **done this session** |
| APPLY stage order | `src/nexus/stages.py` `APPLY_STAGES` | **done** |
| CLI | `nexus improve apply` | **done** |
| Tests | `tests/test_worktree_apply.py` | **done** |

### What P0.5 does

1. Claim-verified grade (fixture / IMPROVE_OURS) must pass before apply.
2. Creates an **isolated worktree** under `.nexus_workspaces/apply_worktrees/<job_id>/` (sandbox default; optional `git worktree` when not nested).
3. Applies **one** ported pattern: Markdown skill SoT pack from **wshobson/agents** shape (`skillpacks/markdown-sot-demo/{manifest.json,SKILL.md}`) — **not** a vendored tree.
4. Runs structural `skillpacks.validate` **inside** the worktree.
5. Proves **main is untouched** via path fingerprints; ledgers `plan_apply` + `apply`.
6. Cleanup removes the worktree (unless `--keep`).

### Acceptance

- [x] Stages refuse skip: cannot `plan_apply` / `apply` before `claim_verify`
- [x] Pattern files land only under worktree; main fingerprint stable
- [x] Bad grade (missing score/path) fails before worktree write
- [x] `wshobson/agents` fixture (score 16.0) end-to-end apply green
- [x] Ledger has mine→grade→claim_verify→plan_apply→apply rows
- [x] No whole upstream tree vendored

### Commands

```bash
PYTHONPATH=src python3 -m nexus.cli improve apply \
  --fixture tests/fixtures/mine_eval_sample.json --mode sandbox
PYTHONPATH=src python3 -m nexus.cli improve apply --list-patterns
PYTHONPATH=src python3 -m pytest -q tests/test_worktree_apply.py tests/test_stage_order.py
```

---

## Evidence sources (this cycle)

### Mined repos (IMPROVE_OURS, score ≥ 10)

Top patterns still in scope (port shape only):

| Repo | Score | Pattern |
|------|------:|---------|
| wshobson/agents | 16.0 | Markdown skill SoT + validate/generate |
| MattMagg/MisterSmith | 16.0 | supervised runtime / operator surfaces |
| builderz-labs/mission-control | 15.0 | ops plane, CLI/MCP parity |
| codingagentsystem/cas | 15.0 | worktree-isolated workers |
| automagik-dev/forge | 15.0 | worktree apply + kanban |
| Intelligent-Internet/zenith | 15.0 | principled stop / gap board |
| ahmedEid1/lumen | 15.0 | decision audit / idempotency |
| choihyunsus/soul | 15.0 | immutable ledger |
| IBM/AssetOpsBench | 15.0 | eval CLI / MCP scenarios |
| gossipcat-ai/gossipcat-ai | 14.0 | consensus review |

### arXiv (control-plane steals)

| id | Idea → NEXUS |
|----|----------------|
| **2510.13343** | AOAD-MAT ordered stages (`APPLY_STAGES`) |
| **2512.03278** | Thucy claim-verify before apply |
| **2508.08322** | context / durable agent messages |
| **2310.12670** | fault-tolerant checkpoint isolation |
| **2511.15755** | deterministic audit / replayable apply |
| **2203.08975** | multi-agent communication survey |

---

## Prioritized backlog (remaining)

### Done spine

- P0.1 ledger · P0.2 stages · P0.3 loader · P0.4 claim_verify · **P0.5 worktree apply** · P0.6 smoke
- P1.x ops / DAG / consensus / context_pack / vault (prior sessions)
- P2.x skillpacks / tool catalog / mcp_eval / promote gates (prior sessions)

### Next open (P1-ish, small)

| Item | Notes |
|------|--------|
| **Promote from worktree** | Optional: copy verified pack from worktree → main after independent verify |
| **Git worktree outside repo** | Nested `git worktree add` fails inside checkout; sandbox is default |
| **More pattern catalog entries** | e.g. cas supervisor marker, soul handoff stub (still no tree vendor) |
| **Wire improve apply into alive cycle** | When self_approve lands, run apply stage with budget |

### Explicit non-goals (still)

- No vendoring whole scout_repos trees
- No force-push / no secrets in ledger
- No full TUI / mission-control dashboard clone

---

## Loop mantra

*mine → grade (Grok) → claim-verify → ledger → **worktree apply** → re-grade → demo.*

Every apply writes only inside an isolated worktree until an explicit promote step (future) copies verified artifacts to main.
