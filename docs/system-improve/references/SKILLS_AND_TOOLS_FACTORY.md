# Skills + tools as self-improve products

**Thesis:** When self-improvement works, the system must not only patch `src/`.  
It must also **mint better skills** (how agents work) and **better tools** (what agents can call) — quarantined, tested, activated — so capability **compounds**.

SARSI names this (skill learning, candidate tools/skills, creation ≠ activation) but underweights it.  
Nexus already has the sockets: `skillpacks/`, `marketplace`, MCP `TOOLS[]`, `tool_catalog`, lessons (S07), accept (S05), quarantine (S06).

---

## Two capital types

| Capital | Artifact | Who consumes it | Example |
|---------|----------|-----------------|--------|
| **Skill** | `skillpacks/<id>/SKILL.md` + `manifest.json` (+ tests) | Humans + any harness (Grok/Claude/local) as *procedure* | “How to review a portfolio slice”, “how to open a SWE-Pro instance” |
| **Tool** | Callable capability: MCP tool, CLI subcommand, marketplace entry, safe local registry handler | Agents at runtime via tool call | `nexus_scope_classify`, `nexus_lesson_search`, `code_review_pack` |

```text
                    evidence (REAL cycle)
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
     SKILL CANDIDATE              TOOL CANDIDATE
     (Markdown playbook)          (callable function)
              │                         │
              └──────────┬──────────────┘
                         ▼
              quarantine + tests + Accept
                         │
                    activation
              (owner / soft auto low-risk)
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
         skill catalog          tool catalog
         (skillpacks/)          (MCP TOOLS / CLI)
```

Skills without tools = advice.  
Tools without skills = buttons nobody uses well.  
**Both** are required for a self-improving coding OS.

---

## What “new skill” means (examples)

| Novel skill | Born from | Pack does |
|-------------|-----------|-----------|
| `code-review-portfolio-slice` | Panel critiques | Structured review checklist for S01 files only |
| `swe-pro-minimal-repro` | Harness fails | Isolate failing test → minimal patch loop |
| `scope-respecting-edit` | S04 violations | Enforce allowed_prefixes ritual before edit |
| `accept-then-document` | S05 rejects | When accept fails, write residual + lesson |
| `novel-cross-pattern-hygiene` | Portfolio thrash | When to skip cooled GitHub seeds |

**Skill ≠ one-off patch.** Skill is reusable across ideas and seats.

---

## What “new tool” means (examples)

| Novel tool | Privilege | Does |
|------------|-----------|------|
| `nexus_skill_search` | read | Search activated skillpacks by tag/goal |
| `nexus_lesson_query` | read | Query S07 lessons programmatically |
| `nexus_scope_check` | read | Classify paths vs active contract |
| `nexus_accept_eval` | read | Run soft accept on a pack of files |
| `nexus_review_diff` | read | Structured code review of a path list |
| `nexus_pack_validate` | read | Validate skillpack layout / tests |
| `nexus_candidate_propose` | write (gated) | Write a *candidate* skill/tool stub under quarantine dir |

**Tool ≠ vendoring a whole framework.** Tool is a **small, tested, privilege-tagged** callable registered where agents already look (MCP / tool_catalog / multi_llm registry).

Privilege ladder (existing catalog idea):

`read` → `write` → `ops` → `admin`

New tools default to **read** until Accept + owner policy raise them.

---

## Lifecycle (same for skills and tools)

```text
1. PROPOSE   — from evidence (lessons, accept fails, panel F-findings, SWE logs, novel portfolio)
2. SCAFFOLD  — create candidate under quarantine path (NOT live catalog)
3. IMPLEMENT — Grok (or human) fills SKILL.md / tool handler + tests
4. VERIFY    — pack tests / unit tests / soft accept / optional smoke
5. ACCEPT    — S05-style predicate on the *candidate* (not worker ok alone)
6. ACTIVATE  — copy/register into live skillpacks or MCP TOOLS (creation ≠ activation)
7. OBSERVE   — usage + failures → lessons → next propose
8. RETIRE    — version bump or demote if accept_rate collapses
```

Quarantine roots (proposed):

```text
.nexus_state/capability_factory/
  candidates/
    skills/<id>-<hash>/
    tools/<id>-<hash>/
  ledger.jsonl          # propose/accept/activate events
```

Live destinations:

```text
skillpacks/<id>/                 # activated skills
src/nexus/... or MCP TOOLS[]     # activated tools (code)
.nexus_state/tool_catalog/       # export after activate
```

---

## SARSI alignment

| SARSI | Here |
|-------|------|
| Skill learning (moderate risk) | Skill candidates |
| Tool candidates | Tool candidates |
| Creation ≠ activation | quarantine → Accept → activate |
| Independent evidence | pack tests + soft accept + panel optional |
| Meta-improvement | meta-skill: “how we invent skills/tools” (later) |

---

## Non-goals (v1 factory)

- Auto-raising privilege to admin  
- Unbounded tool generation calling the network  
- Replacing human review for write/ops tools  
- Training weights to “learn skills”  
- Marketplace of untrusted third-party packs without validate  

---

## Success metrics

| Metric | Meaning |
|--------|---------|
| Candidates proposed / cycle | Factory is alive |
| Accept rate on candidates | Quality not spam |
| Activated skills used in later REAL prompts | Transfer |
| New tools called by multi_llm / MCP | Tools are real |
| SWE-Pro / self-check residual ↓ after activation | North star |

---

## Relation to finished spine (S01–S11)

S01–S11 made **governed code self-edit** safe.  
S12–S13 make **capability capital** grow: skills agents follow + tools agents call.
