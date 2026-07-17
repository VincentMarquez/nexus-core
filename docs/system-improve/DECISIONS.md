# Decisions log

Record non-obvious choices so chat history is not the only memory.

Format:

```markdown
## D-YYYYMMDD-N — short title
- **Status:** accepted | superseded | rejected
- **Context:** …
- **Decision:** …
- **Why:** …
- **Consequences:** …
```

---

## D-20260717-1 — Offline plan folder separate from runtime self-improve

- **Status:** accepted
- **Context:** Need trackable system improvement without mixing into alive REAL / LATEST_* noise.
- **Decision:** Create `docs/system-improve/` as human+LLM offline control surface; keep `docs/self-improve/` as product map.
- **Why:** Runtime artifacts thrash every cycle; plans must be stable and reviewable.
- **Consequences:** Two folders to know; README cross-links reduce confusion.

## D-20260717-2 — Two main fixes first (slice + publish)

- **Status:** accepted (implemented on disk)
- **Context:** Dirty-tree critique and unscoped publish were the highest product-correctness bugs.
- **Decision:** Land S01 + S02 before portfolio/engine policy work.
- **Why:** Wrong unit of work poisons every other quality signal.
- **Consequences:** Next alive process behaves correctly; mid-run process may still be old code.

## D-20260717-3 — Next step is implement ledger, not full SARSI

- **Status:** accepted
- **Context:** SARSI landscape is inspiring; full foundry is out of scope.
- **Decision:** S03 portfolio cooldown via implement ledger before SARSI-shaped contracts/foundry.
- **Why:** Immediate thrash (`wshobson` every run) is cheap to fix and high value.
- **Consequences:** Defer S04–S06 until thrash stops.

## D-20260717-4 — Soft gates before hard fail-closed

- **Status:** accepted
- **Context:** Engine/X fail-open debates.
- **Decision:** When we touch gates (S05/S08), default soft (demote / block push / warn) with explicit hard flag later.
- **Why:** Avoid breaking long REAL cycles on flaky external inputs.
- **Consequences:** Honesty improves before strictness.

## D-20260717-5 — Stop mid-run REAL to land S03/S10

- **Status:** accepted
- **Context:** Live process held old imports; panel timeouts at 360s; wshobson re-selected.
- **Decision:** Operator stop of `alive once` (~15:07 UTC) then land S03+S10 on clean tree.
- **Why:** Continuing thrash delayed cooldown fix; next cycle should pick new ideas.
- **Consequences:** Incomplete portfolio for that run (ideas 1–2 done-ish, #3 mid); no END summary for that process.

## D-20260717-6 — Cooldown is demote-not-delete

- **Status:** accepted
- **Context:** S03 fail-open requirement.
- **Decision:** Cooled ids go to end of selection lists (`order_with_cooldown`); if only cooled github remains, still select with `cooldown_reuse=true`.
- **Why:** Never empty required_github quota.
- **Consequences:** True block requires future hard flag (not default).

## D-20260717-7 — S04 is Bubbles/DNA discipline, not Bubbles rewrite

- **Status:** accepted
- **Context:** Operator recalled Bubbles “every agent had DNA”; SARSI felt similar.
- **Decision:** Document lineage (UniversalBubble + AGENT_DNA.md + SARSI) in `references/BUBBLES_DNA_AND_SARSI.md`; implement S04 as short scope-contract DNA per idea, soft inject first.
- **Why:** Same product law (no naked agents) without reintroducing full Bubbles event runtime.
- **Consequences:** S04 v1 = CONTRACT.json + prompt DNA block; hard path enforce later.

## D-20260717-8 — S04 default OFF after GPT review

- **Status:** accepted
- **Context:** GPT request-changes vs Grok approve-with-nits; PRINCIPLES §3.
- **Decision:** `scope_contract_enable` defaults **false**; when true, advisory only; same contract for implement + critics + synthesis; never filter panel files; no publish change.
- **Why:** Avoid silent behavior change on next REAL restart.
- **Consequences:** Operator must set `"scope_contract_enable": true` in alive.json to use DNA.

## D-20260717-9 — Self-improve must mint skills AND tools

- **Status:** accepted
- **Context:** SARSI underweights skill/tool generation; operator wants novel skills (e.g. code review) and better *callables* agents can invoke, not only src patches.
- **Decision:** Phase B = S12 skill factory + S13 tool factory; shared quarantine/Accept/activation; skills = procedures in skillpacks; tools = privilege-tagged MCP/CLI handlers; creation ≠ activation; default flags off for generate/activate.
- **Why:** Capability compounds only if next runs inherit playbooks *and* hands.
- **Consequences:** Implement in waves (order doc); first skill golden path `code-review-portfolio-slice`; first tools wrap existing read modules (lessons, scope, skill search).
