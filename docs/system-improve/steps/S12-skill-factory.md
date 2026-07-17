# S12 — Skill factory (procedures agents follow)

| Field | Value |
|-------|--------|
| Status | **done** Wave A/B (2026-07-17) — Wave D/E later |
| Phase | P4 — Capability factory |
| Risk | Medium (opt-in; quarantine first) |
| Depends on | S05 accept, S06 quarantine, S07 lessons, skillpacks layout |
| Primary targets | `skillpacks/`, `.nexus_state/capability_factory/`, `marketplace` validate |

## Problem

Self-improve mostly emits **code diffs**. Reusable know-how stays trapped in chat, one-off modules, or S07 lesson one-liners. Agents re-discover “how to review code” every cycle.

## Goal

When improvement works (or when a novel need is detected), the system can **propose → scaffold → verify → activate** a new **skillpack**:

- e.g. **code review skill**, SWE-Pro repro skill, scope-respecting edit skill  
- **Novel** procedures, not only copies of existing packs  
- Portable Markdown + manifest + optional tests (wshobson-shaped, already in-repo)

## Non-goals

- Auto-activate high-privilege skills without Accept  
- Skill spam without ledger/cooldown (mirror S03)  
- Full tool implementation (that’s **S13**)  

## Design

### Candidate shape

```text
.nexus_state/capability_factory/candidates/skills/<id>-<short_hash>/
  SKILL.md
  manifest.json
  tests/           # optional pack-local
  EVIDENCE.md      # cycle ids, lessons, panel refs
  STATUS.json      # proposed | verified | accepted | rejected | activated
```

### Propose triggers

| Source | Example skill |
|--------|----------------|
| S07 lessons (repeated code) | `panel-timeout-resilience` |
| S05 accept rejects | `py-compile-before-claim-ok` |
| Panel major findings | `code-review-slice` |
| Portfolio novel ideas | hybrid “research → checklist” skills |
| Operator / dual_review brief | explicit “we need a review skill” |

### Pipeline (per candidate)

1. **Propose** — write STATUS proposed + EVIDENCE (no live skillpacks write yet)  
2. **Scaffold** — template SKILL.md + manifest from trusted schema  
3. **Fill** — Grok (quarantine) expands skill from evidence; scope contract `allowed_prefixes: ["skillpacks/", ".nexus_state/capability_factory/"]`  
4. **Verify** — structure validate (marketplace-style) + optional tests  
5. **Accept** — soft accept_predicate on pack (S05 shaped)  
6. **Activate** — copy to `skillpacks/<id>/` only if accept + flag  
7. **Ledger** — append factory ledger; cooldown on skill id  

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `skill_factory_enable` | `false` | Master opt-in |
| `skill_factory_auto_activate` | `false` | Even if accept, require owner or second gate |
| `skill_factory_max_per_cycle` | `2` | Cap spam |

### Acceptance criteria (when implementing)

- [ ] Propose never writes under live `skillpacks/`  
- [ ] Activate is explicit step; creation ≠ activation  
- [ ] Unit tests: scaffold, validate, refuse path escape  
- [ ] Cooldown: same skill id not re-proposed every cycle  
- [ ] At least one golden path: lesson → candidate → verify dry  

## Relation to tools (S13)

Skills may **reference** tools by name (`use nexus_scope_check`).  
If a skill needs a missing tool, factory emits a **tool candidate** (S13) linked by id.
