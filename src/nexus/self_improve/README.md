# `nexus.self_improve` package

Clean import surface for the product self-improve spine.

```python
from nexus.self_improve import (
    cycle_once,          # alive DRY/REAL cycle
    run_canonical,       # research → engine+judge
    build_portfolio,     # idea selection
    implement_portfolio,
    write_implement_summary,
)
```

Implementation still lives in the sibling modules (`alive.py`, `unified_pipeline.py`,
`idea_portfolio.py`, …) so CLI/MCP imports stay stable. This package is the **facade**,
not a second copy of the logic.

Human map: [`docs/self-improve/`](../../../docs/self-improve/README.md)
