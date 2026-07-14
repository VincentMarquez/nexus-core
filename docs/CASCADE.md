# Cascade navigation (D* style)

## Idea

Context is finite. Deep file paths die mid-generation.  
A **shallow master index** survives longer and should be read **first**.

Conceptual layers:

| Depth | Content | Survival in context |
|-------|---------|---------------------|
| D*≈1 | System index (projects, where things live) | longest |
| D*≈2–3 | Branch / package map | medium |
| D*≈4–5 | Concrete files / blobs | shortest |

## Law

```text
Never navigate blind.
Read the cascade from the top before opening deep files.
```

## In this kit

```python
from nexus.cascade import CascadeIndex

idx = CascadeIndex.demo()
print(idx.overview())           # D*1
print(idx.branch("engine"))     # deeper
ctx = idx.prompt_block()        # inject into agent context
```

Production systems often auto-rebuild indexes when agents write new files under `scripts/output/` (or equivalent).
