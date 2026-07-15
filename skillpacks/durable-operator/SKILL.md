# Skill: Durable operator board

## When to use

- Inspect crash-safe multi-agent tasks  
- Export evidence for CI / boards  
- Human-approve a waiting task  

## Commands

```bash
nexus task list
nexus task replay <id>
nexus task evidence <id> --out evidence.json
nexus task resume <id> --approve
python3 examples/demo_hitl_resume.py
```

## Rules

1. Prefer journal + checkpoint over re-running agents.  
2. Never force-push; never commit secrets.  
3. Fail-closed on review veto / human reject.  
4. Keep pytest green after changes.  

## Success

- Task replay shows handoffs and decisions  
- Evidence pack includes timeline + gates  
- HITL resume completes without data loss  
