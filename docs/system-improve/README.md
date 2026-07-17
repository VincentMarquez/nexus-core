# System improve plan (offline control surface)

**Purpose:** A clean, human-owned plan for improving NEXUS **without breaking the live system** and without losing track of work.

This folder is **not** part of the alive / REAL self-improve loop.  
It is for **you + other LLMs offline review**, then **step-by-step execution**.

| Folder | Role |
|--------|------|
| **`docs/system-improve/`** (this) | Plan · track · review · decide · execute carefully |
| `docs/self-improve/` | How the **running** product spine works |
| `docs/LATEST_*` | **Generated** cycle artifacts (noise for planning) |

---

## Start here (5 minutes)

1. Read **[PRINCIPLES.md](./PRINCIPLES.md)** — non-breaking rules (always).
2. Read **[BASELINE.md](./BASELINE.md)** — clean starting point as of this plan.
3. Open **[TRACKER.md](./TRACKER.md)** — single checklist of status.
4. Open **[ROADMAP.md](./ROADMAP.md)** — phases and order.
5. Before coding a step: open that step under **[steps/](./steps/)** and run **[HOW_TO_EXECUTE.md](./HOW_TO_EXECUTE.md)**.
6. Before accepting a big change: use **[OFFLINE_REVIEW.md](./OFFLINE_REVIEW.md)** with Claude / GPT / another model.

---

## How we work (simple loop)

```text
  TRACKER shows next open step
       │
       ▼
  Offline review (other LLM) of the step file
       │
       ▼
  Implement ONLY that step (small PR / commit)
       │
       ▼
  Tests for that step + smoke that alive still imports
       │
       ▼
  Mark step done in TRACKER + note in DECISIONS if needed
       │
       ▼
  Next step (no batching five half-done ideas)
```

**Default rule:** one open step in progress at a time.

---

## What is already done (do not re-litigate)

| Step | Status | Summary |
|------|--------|---------|
| S01 Critique slice isolation | **Done on disk** | Strict porcelain delta; synthesis-only revert |
| S02 Cycle-scoped publish | **Done on disk** | Baseline porcelain at cycle start; stage only new dirt |

These may not apply until the **next** `alive once` process (already-running cycles keep old imports).

---

## Plan status

| Phase | Scope | Status |
|-------|--------|--------|
| **A** | Governed self-edit spine (S01–S11) | **Complete** |
| **B** | Capability factory — **skills + tools** (S12–S13) | **Designed / ready to build** |

See **[TRACKER.md](./TRACKER.md)**.

### Phase B (why it matters)

Self-improve must mint more than code:

- **Skills** — reusable procedures (e.g. code review, SWE-Pro repro) in `skillpacks/`  
- **Tools** — new callables agents can invoke (MCP/CLI), privilege-tagged  

Order: [steps/S12-S13-IMPLEMENTATION-ORDER.md](./steps/S12-S13-IMPLEMENTATION-ORDER.md)  
Vision: [references/SKILLS_AND_TOOLS_FACTORY.md](./references/SKILLS_AND_TOOLS_FACTORY.md)

Optional later: panel quorum, multi_llm real registry, SWE-Pro held-out Accept, SARSI meta-skill loop.

---

## Files in this folder

| File | What |
|------|------|
| [PRINCIPLES.md](./PRINCIPLES.md) | Safety / non-breaking rules |
| [BASELINE.md](./BASELINE.md) | Starting snapshot (truth at plan birth) |
| [ROADMAP.md](./ROADMAP.md) | Phases P0–P3 |
| [TRACKER.md](./TRACKER.md) | **Living checklist** — update this |
| [HOW_TO_EXECUTE.md](./HOW_TO_EXECUTE.md) | How to land a step safely |
| [OFFLINE_REVIEW.md](./OFFLINE_REVIEW.md) | Prompt + process for other LLMs |
| [DECISIONS.md](./DECISIONS.md) | Decision log (why we chose X) |
| [references/LANDSCAPE.md](./references/LANDSCAPE.md) | AutoResearchClaw, DGM, SARSI, … |
| [references/SARSI_NEXUS.md](./references/SARSI_NEXUS.md) | SARSI → Nexus map (inspiration, not rewrite) |
| [steps/](./steps/) | One markdown file per step |

---

## Explicit non-goals of this folder

- Not auto-executed by `nexus alive`
- Not a second portfolio of 10 ideas per day
- Not SARSI implementation of stages 7–8
- Not rewriting the lab bus mid-flight

We improve **contracts, gates, and memory** first so self-edit becomes safer—not faster thrash.
