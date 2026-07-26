---
name: durable-operator-board
description: Audit and safely operate crash-resumable NEXUS tasks.
---

# Durable operator board

## When to use

Use this skill to inspect task checkpoints, replay handoffs, export evidence, or
resume a task after the required human approval.

## Procedure

1. List the task and read its current checkpoint.
2. Replay the journal before considering a rerun.
3. Export the evidence pack when a review or audit trail is required.
4. Confirm every review and human-approval gate.
5. Resume or cancel only when the operator explicitly requests that action.

## Success

- Task status and next action are evidence-backed.
- Completed work is not repeated.
- Failed or waiting gates remain fail-closed.
