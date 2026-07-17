# Bubbles DNA ↔ NEXUS DNA ↔ SARSI ↔ S04

You asked whether SARSI felt like the Bubbles network where every agent had DNA it **had** to have. **Yes — same design instinct, different layer.**

---

## 1. Bubbles network (structural DNA)

**Where:** `Downloads/bubbles_core.py` — class `UniversalBubble`  
**Also:** many `*Bubble.py` specialists, `bubbles_overseer.py`, runtime under  
`Desktop/Projects/research/.bubbles/{nexus,kairos}/`

### What every bubble *had* to have

```text
UniversalBubble(object_id, SystemContext)
  ├── object_id          # identity (required non-empty str)
  ├── context            # SystemContext (required)
  │     ├── event_dispatcher
  │     ├── resource_manager
  │     └── chat_box
  ├── event_queue
  ├── handle_event / process_single_event
  ├── autonomous_step
  ├── start/stop_autonomous_loop
  └── register_bubble on init
```

**Meaning:** You did not invent a free-floating agent. You **subclassed DNA**. No `object_id` / no `SystemContext` → constructor **raises**. That is fail-closed structure.

Specialists (RAG, PPO, LangGraph, QFD, …) only added domain behavior **on top of** that genome.

---

## 2. NEXUS AGENT DNA (prompt / attention DNA)

**Where:**

| Artifact | Path |
|----------|------|
| Source of truth | `Desktop/Projects/research/AGENT_DNA.md` |
| Injector | `.cleanup-archive-…/scripts/nexus_dna_patch.py` |
| Boot patch | `Desktop/Projects/research/patch_dna_into_runpy.py` |
| Master index | `~/nexus_index.json` (D*=1) |

### What every agent *had* to have

From `AGENT_DNA.md`:

> This is D*=0 of every agent's context window.  
> It is the FIRST thing injected, the LAST thing peeled.  
> Every agent inherits this. **No exceptions.**

Mandatory behavior:

1. Read `~/nexus_index.json` first  
2. Follow index cascade (system → research graph → branch → file)  
3. Never navigate blind  
4. Write outputs where cascade can reindex  

**Mechanism:** wrap every dispatch/prompt with:

```xml
<NEXUS_DNA>
…text from AGENT_DNA.md…
</NEXUS_DNA>
```

Boot order you defined:

1. NEXUS DNA  
2. Spectral Memory (lessons / bans)  
3. Graph RAG  
4. Exec context  
5. Cascade rebuild  
6. D* scorecard  

That is **soft structural law in the prompt**, tuned for attention lifetime (D*).

---

## 3. SARSI (contract DNA — paper)

**Paper:** [arXiv:2607.12254](https://arxiv.org/abs/2607.12254)

Every agent **must** carry:

| Field | Role |
|-------|------|
| Goal contract | safety / mission / owner / task / improve |
| Scope | what it may touch |
| Tool registry + tests | validated tools only |
| Benchmarks | held-out accept |
| Autonomy / Auto-Index | mode ≠ permissions |
| Self-model | evidence-linked identity/capabilities |
| External governance | agent proposes; outside accepts |

**Same instinct as Bubbles:** no naked agents.  
**Different layer:** signed/versioned contracts + promote gates, not only base class or prompt preamble.

---

## 4. Side-by-side

| | Bubbles | NEXUS DNA | SARSI | S04 (this plan) |
|--|---------|-----------|-------|-----------------|
| Layer | Runtime class | Prompt D*=0 | Spec / governance | Idea implement unit |
| Enforcement | Constructor raise | Inject every prompt | Design Accept() | Soft inject + CONTRACT.json |
| Identity | `object_id` | Agent in multi-agent system | Agent profile + lineage | `idea_id` + mission |
| Shared world | `SystemContext` | `nexus_index.json` cascade | External governance plane | Repo + alive cycle |
| Scope | Bubble role + event types | Navigate only via index | Scope contract | `allowed_prefixes` |
| Evolution | New Bubble subclasses | Patch DNA file | Evidence-gated improve | Ledger (S03) + contracts |

---

## 5. How you “did it” (memory aid)

1. **Bubbles:** abstract base class + SystemContext registration → network of specialist bubbles.  
2. **Research NEXUS:** single markdown DNA file + monkey-patch so **every** agent prompt starts with navigation law.  
3. **nexus-core today:** skillpack manifests, alive config, critique packs — **partial** DNA, not yet mandatory per idea.  
4. **S04:** bring back “every implement unit has DNA” as a **scope contract**, without rebuilding Bubbles or claiming full SARSI.

---

## 6. What *not* to revive blindly

- Full Bubbles event bus inside nexus-core (you already have lab bus + MCP)  
- D* graph rebuild on every alive cycle (heavy; lessons = S07 later)  
- DNA that is 200 lines of prose (attention dies — keep S04 DNA block short)

---

## 7. Practical rule for S04

> **If it can call Grok to edit the product, it must carry a scope contract**  
> the way every Bubble had to carry `object_id` + `SystemContext`,  
> and every research agent had to carry `<NEXUS_DNA>`.

That is the SARSI-in-your-Bubbles-network feeling — correctly remembered.
