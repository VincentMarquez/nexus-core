# Task evidence packs

NEXUS can export one portable JSON document for a durable task:

```bash
nexus task evidence <task_id> --out evidence.json
```

The export uses schema `nexus.evidence/v1` and combines recorded state rather
than rerunning agents.

## Main fields

| Field | Contents |
|---|---|
| `task` | Objective, status, step, criteria, constraints, agents, and budgets |
| `norms` | Parsed `require:*`, `deny:*`, token, and wall-time constraints |
| `gates` | Integrity, budget, timeline, terminal, completion, veto, approval, and norm checks |
| `gate_failures` / `ready` | Failed readiness checks and the combined result |
| `story` / `explain` | Human-readable decision chain, handoffs, vetoes, failures, and judge rationale |
| `cost` | Recorded token and score rollups |
| `verify` | Checkpoint-to-journal consistency checks |
| `timeline` | Normalized event sequence |
| `provenance` | Agents, activities, entities, and their relationships |
| `graph` | Agent handoff/call graph |

`ready=true` means the evidence pack's configured gates passed. It is not a
security attestation and does not prove that model output is factually correct.

Additional output modes:

```bash
nexus task evidence <task_id>
nexus task evidence <task_id> --json
nexus task evidence <task_id> --compact
```

See [Crash → resume](../cookbook/01_crash_resume.md#evidence-pack-norms-p6)
and [Task operator](../cookbook/12_task_operator.md) for the related inspection
commands.

## Included examples

- [`hitl-demo-3a6a46ef.json`](hitl-demo-3a6a46ef.json) — completed HITL run
  with a passing integrity/timeline gate.
- [`gap-demo.json`](gap-demo.json) — completed checkpoint whose missing journal
  keeps `ready=false`.

These are historical examples, not current-branch test results.

## Privacy

Machine-local task dumps under `.nexus_state/` are not committed by default.
They may contain prompts, outputs, source excerpts, local paths, stdout/stderr,
tool arguments, and operator feedback. Treat them as sensitive runtime data.

Before publishing an evidence pack:

1. inspect every field;
2. redact private paths, source, credentials, and personal data;
3. confirm that linked artifacts are intended to be public; and
4. label the run date and environment so it is not mistaken for current status.
