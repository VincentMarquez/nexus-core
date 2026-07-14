# Architecture

## Problem

Multi-agent research systems fail in predictable ways:

1. **Infra death** — process killed mid-task → work lost  
2. **False validation** — “agent replied” ≠ “success criteria met”  
3. **Context thrash** — agents open deep files without a map  
4. **Memory silos** — chat, tasks, and code graph never share a retrieval API  
5. **Unattended spend** — autonomous loops burn tokens forever  

## Solution spine

| Pillar | Module | Job |
|--------|--------|-----|
| Cascade | `nexus.cascade` | Shallow index first (long-lived in context), then branch, then file |
| Pipeline | `nexus.steps` | Fixed 10-step policy with capabilities + checkpoints |
| Agents | `nexus.agents` | Multi-vendor panel, health, fallback table |
| Engine | `nexus.engine` | Durable checkpoints, resume, wraps step execution |
| Judge | `nexus.judge` | Rubric vs success_criteria + artifact evidence |
| Memory | `nexus.memory` | Namespaced hybrid retrieval (RRF) |
| Trust | `nexus.trust` | Provenance + verdict log |

## Data flow

```
Task created
   → engine loads/creates checkpoint
   → for step in policy:
        resolve agent (health + fallback)
        cascade.context_for(step)   # shallow map into prompt
        memory.search(ns, query)    # fail-open
        runner.execute(step)        # pluggable body
        structural pre-gate
        judge.score(...)            # may pass / revise / fail
        trust.record_verdict(...)
        engine.checkpoint()
   → human approval step (interruptible)
   → deliver
```

## Engine contract

The durable engine **must not** reimplement step business logic.

```text
engine.run(task) →
  for step in policy:
      output = runner.execute_step(task, step, context)
      verdict = judge.evaluate(...)
      save_checkpoint(task_id, step, output, verdict)
```

That separation is what makes LangGraph/SqliteSaver (or any checkpointer) a **wrapper**, not a rewrite.

## Autonomy

| Mode | Flag | Behavior |
|------|------|----------|
| Reactive (default) | `autonomy=False` | Only user-submitted tasks run |
| Autonomous | `autonomy=True` | Optional goal loops may create tasks |

Default **OFF**. Unattended generators are the classic token sink.

## Namespaces

Memory and provenance use `proj/<id>`:

- `proj/demo` — examples  
- `proj/lab` — generic research  
- Sensitive tenants use **separate** namespaces and never share FTS results across ns  

## What production systems add

This kit is intentionally small. A full lab may add:

- real LLM bridges + circuit breakers  
- UI (task cards, approval panel)  
- MCP tool surface  
- graphify-backed impact maps  
- eval scoreboard  

Those are **integrations**. The laws above stay the same.
