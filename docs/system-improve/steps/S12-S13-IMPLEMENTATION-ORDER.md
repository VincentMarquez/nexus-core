# P4 implementation order (skills + tools)

Do **not** implement everything at once. Same discipline as S01–S11.

## Wave A — Observe & scaffold (safest)

1. Factory ledger + dirs under `.nexus_state/capability_factory/`  
2. CLI/API: `propose_skill`, `propose_tool` (write candidates only)  
3. Templates for SKILL.md / TOOL.md / manifest  
4. Unit tests: path jail, no live skillpacks/MCP writes  

## Wave B — Skill factory (S12)

1. Harvest proposers from S07 lessons + S05 rejects  
2. Grok fill candidate skill in quarantine  
3. Validate pack structure  
4. Soft accept on pack  
5. Manual/flag activate → `skillpacks/<id>/`  

**First golden skill to mint:** `code-review-portfolio-slice`  
(structured review of S01 file list — maps to your “review code” example)

## Wave C — Tool factory read-only (S13)

1. Scaffold read tools that wrap existing modules:
   - `nexus_lesson_query` → cross_run_lessons  
   - `nexus_scope_check` → scope_contract.classify_paths  
   - `nexus_skill_search` → scan skillpacks  
2. Tests + catalog entries  
3. Flag-gated activate into MCP/CLI  
4. multi_llm opt-in real registry for these names only  

## Wave D — Novel generation

1. Portfolio idea type `capability:skill` / `capability:tool`  
2. Panel critiques skill/tool candidates (not only product src)  
3. Skill may spawn tool candidate; tool may spawn skill  
4. Cooldown + max per cycle  

## Wave E — Meta (later)

1. Meta-skill: how the factory itself proposes better  
2. Auto-activate only for read + high accept_rate  
3. Retire unused / failing tools  

## Definition of done for P4 v1

- [ ] At least one **new skill** activated from evidence (not hand-waved)  
- [ ] At least one **new read tool** callable by agent/MCP after activate  
- [ ] Creation never equals activation  
- [ ] Flags default off for generate/activate  
- [ ] Docs in system-improve + skillpacks README pointer  
