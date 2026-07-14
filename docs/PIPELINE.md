# 10-step pipeline

Default adversarial workflow for non-trivial work.

## Steps

| # | `name` | Typical agent role | Checkpoint | Notes |
|---|--------|--------------------|------------|-------|
| 1 | `goal` | operator | | Sets `objective`, `constraints`, `success_criteria` |
| 2 | `plan` | planner | | Approach, risks, files |
| 3 | `challenge` | adversary | optional | Attacks plan; can force replan |
| 4 | `implement` | implementer | | Produces artifacts |
| 5 | `test` | tester | optional | Runs checks; evidence for judge |
| 6 | `review` | reviewer | | Findings + severity |
| 7 | `log` | logger | | State snapshot |
| 8 | `meta_review` | multi | | Panel review |
| 9 | `approval` | operator | **human** | Approve / reject / feedback |
| 10 | `deliver` | implementer | | Final report path |

## Capabilities

Agents declare capability sets, e.g. `can_plan`, `can_execute`, `can_review`.  
Steps require a capability; unhealthy agents fall back via a table.

## Validation layers

1. **Structural pre-gate** — shape of output dict, required keys  
2. **Rubric judge** — scores against `success_criteria` using evidence  
3. **Human approval** — final gate for risky work  

Presence of an agent reply is **never** enough for step 5/6 success.

## Customization

```python
from nexus.steps import StepPolicy, StepDef

policy = StepPolicy.default()
# or build your own list of StepDef(...)
```
