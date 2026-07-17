# Skill: Engine Fail Aware Brief

## When to use

Continue carefully when canonical engine fails open

## Steps

1. Confirm unit of work (strict file delta / scope contract if present).
2. Read EVIDENCE.md and any linked lessons.
3. Execute the procedure below without expanding scope.
4. Run pack tests / py_compile on touched files.
5. Record residuals if incomplete.

## Procedure

1. **Orient** — List in-scope files; refuse forbidden prefixes (`.venv/`, `.env`, `.nexus_state/` secrets).
2. **Diagnose** — Map symptoms to one root cause; prefer existing modules over new ones.
3. **Act** — Make the smallest change that satisfies Success.
4. **Verify** — Run focused tests; do not claim ok if compile/tests fail.
5. **Leave trail** — Update docs only if behavior changed; link cycle evidence.

## Tools (optional)

- `nexus_scope_check` — classify paths
- `nexus_lesson_query` — prior failures
- `nexus_code_review` — static review checklist
- `nexus_skill_search` — find related packs

## Rules

1. Prefer small, tested changes.
2. Do not force-push; do not commit secrets.
3. Creation of candidates is not activation.
4. Honor portfolio cooldown and scope DNA when present.

## Success

- Procedure steps completed or residual noted
- Layout tests pass for this pack
- No forbidden-path edits

## Evidence seed

# Evidence — engine-fail-aware-brief

lesson:engine_failed_open n≈1 sample=Canonical engine failed or errored; implement may have continued fail-open.

