# Latest improve plan (manual fix-all)

## Goal

Close the gap between **what Grok found** and **what still looked “failed”**: docs, demos, DAG steps, skill packs, community security, metrics.

## First apply slice

1. Restore `SELF_IMPROVE_CYCLE.md` + this plan  
2. Cookbook `12_task_operator.md`  
3. `examples/demo_hitl_resume.py`  
4. Alive/publish: write evidence pack when tasks exist  
5. `StepDef.depends_on` + topological run order  
6. `skillpacks/` layout + one example pack  
7. Community draft security gate  
8. `nexus.metrics` optional OTel/Prometheus  

## Tests

```bash
PYTHONPATH=src python3 -m pytest -q
python3 examples/demo_hitl_resume.py
```

## Do not

- Vendor full upstream trees  
- Force-push  
- Commit secrets / `.nexus_state` ledgers with keys  
