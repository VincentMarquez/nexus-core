# 02 — Judge vs “the model said OK”

**Goal:** See why presence checks lie.

```bash
make install
make demo-judge
```

You’ll see:

| Case | Presence | Rubric judge |
|------|----------|--------------|
| Wrong artifact, agent claims pass | PASS | revise/fail |
| File contains `DEMO_OK` | PASS | **PASS** |

Wire this into tasks with real `success_criteria` (file exists, substring present, etc.).
