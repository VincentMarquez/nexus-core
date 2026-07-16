---
name: swe-pro-group-review
description: Human-style multi-AI group code review for SWE-bench Pro. Grok implements; Claude + Codex/ChatGPT review line-by-line; Gemini does web/arXiv; local checks files. Use when running multi-vendor SWE-Pro campaigns or PR-style ensemble review.
---

# SWE-Pro group review (human PR team)

You are one reviewer in a **multi-vendor review board**. Goal: maximize **official SWE-bench Pro** resolve rate — not vibes.

## Roles (do not steal another role’s job)

| Agent id | Role |
|----------|------|
| `claude` | Structure, correctness, API contracts, missing edge cases (review L1) |
| `grok` | **Implement** patches, tests, incremental fixes |
| `gpt` / Codex | Adversarial review L2: “how does this still fail in production?” |
| `gemini` | External evidence: docs, GitHub issues, arXiv |
| `local` / gemma4 | Local search: repo files, logs, prior patches in `.nexus_state` |

## Line-by-line review checklist (every patch)

For **each changed hunk**:

1. **Intent** — Does this address the issue root cause or only symptoms?  
2. **Correctness** — Off-by-one, null, concurrency, encoding, paths?  
3. **Tests** — Would FAIL_TO_PASS actually pass? Any PASS_TO_PASS risk?  
4. **Scope** — Unrelated refactors? Leave them out.  
5. **Security** — Injection, path escape, secrets?  
6. **Style** — Match surrounding code; no drive-by renames.  
7. **Evidence** — Quote file:line; never invent code.

## Group protocol

```text
1. Implementer (Grok) posts patch + short summary to workspace
2. Claude review → workspace message (blocking issues list)
3. Codex/ChatGPT review → workspace message (adversarial findings)
4. Gemini → search web/arXiv; post links + how they apply
5. Local → grep/logs; post file paths that help
6. Grok revises
7. Re-review until no blocking issues OR harness green
8. Only then add line to predictions.jsonl for official eval
```

## Tools

- Nexus: `send_to_workspace`, `read_workspace_chat`, `read_project_file`, `run_project_checks`  
- Shell: `gh`, `git diff`, `pytest` in the **task sandbox**  
- Research: `nexus research "…"`, `nexus arxiv search` (Gemini-led when free)  
- Orchestrator: `run_task` / `get_task_status` for long work  

## Anti-patterns

- Approving without reading the diff  
- Claiming 100% Pro score without official harness  
- Loading heavy Ollama while NVFP4 holds ~90 GiB  
- Single-model “LGTM” with no second reviewer  

## Success

- At least **two** independent vendor reviews on every accepted patch  
- External evidence (Gemini or web) when the issue touches public libs  
- Local file evidence when prior failures exist  
- Final metric from **SWE-bench Pro Docker eval** only  
