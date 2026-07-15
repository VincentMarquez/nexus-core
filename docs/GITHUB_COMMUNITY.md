# GitHub community one-stop shop

Reply to **issues**, **pull requests**, and **@-mentions** from one place — automatically on GitHub, and interactively from your laptop.

This is the same idea as an always-on assistant desk: new threads get a first reply, and maintainers clear the rest from a single inbox.

## Two layers

| Layer | What it does | Where |
|-------|----------------|-------|
| **GitHub Actions bot** | First reply when an issue/PR opens (or when someone says `@nexus` / `/triage`) | `.github/workflows/community-bot.yml` |
| **Local CLI** | Inbox, drafts, post, bulk auto-reply using your `gh` login | `nexus github …` |

Both use the same drafts and the marker `<!-- nexus-community-bot -->` so threads are never double-spammed.

## Enable on this repo (already wired)

1. Push the workflow file (on `main` it runs for this repository).  
2. **Settings → Actions → General → Workflow permissions**  
   - Allow **Read and write** permissions for `GITHUB_TOKEN`  
   - (or leave default if the workflow’s `permissions:` block is enough)  
3. Open a test issue → the bot should comment within a minute.  

No extra secrets are required for the default **heuristic** replies (docs links + triage checklists).

Optional later:

| Secret / setup | Purpose |
|----------------|---------|
| Personal `gh auth login` on your machine | Local `nexus github inbox/reply/auto` |
| NEXUS bus + agents running | `nexus github reply N --llm` for model-assisted drafts |

## Local one-stop shop

```bash
# one-time
gh auth login          # scopes: repo
cd nexus-core && make install

nexus github status
nexus github inbox                 # open issues/PRs needing a first bot reply
nexus github inbox --all           # include already-answered
nexus github draft 12              # print draft, do not post
nexus github reply 12              # post auto-draft
nexus github reply 12 --body "Thanks — fixed in main."
nexus github auto --dry-run        # preview bulk first-replies
nexus github auto                  # post bulk first-replies
```

Target another repo:

```bash
nexus github inbox --repo owner/other
# or
export NEXUS_GITHUB_REPO=owner/other
```

### Repair jobs (unchanged)

Repo clone → install → test → fix remains:

```bash
nexus do owner/repo
nexus github do owner/repo     # same
```

## Trigger rules (Actions)

| Event | When the bot speaks |
|-------|---------------------|
| `issues` opened / reopened | Always (first reply) |
| `pull_request` opened / reopened | Always (PR checklist) |
| `issue_comment` created | Only if body contains `@nexus`, `/nexus`, `/triage`, or `nexus-bot` |
| Manual **workflow_dispatch** | Optional issue/PR number |

Bot-authored senders are ignored to avoid loops.

## Draft flavors

Heuristic (default, no LLM):

- **Bug** issues → ask for OS, command, traceback, `make demo`  
- **Feature** issues → point at durability / judge / job priorities  
- **PRs** → test/docs checklist + design laws  
- **Generic** → docs + discussions  

LLM (optional): `--llm` uses the NEXUS bus panel when the stack is up; falls back to heuristic if not.

## Security notes

- Default Actions replies use **`GITHUB_TOKEN` only** (repo-scoped, short-lived).  
- Local CLI uses **your** `gh` credentials — treat it like posting as yourself.  
- Prefer `--dry-run` before bulk `auto`.  
- Never put API keys in issue bodies or bot templates.  
- Autonomy stays **opt-in**: the bot greets and triages; it does not merge PRs or push code.

## README blurb

See the **GitHub community** section in the root `README.md`.

## Cookbook

[09 — Community inbox & auto-reply](../cookbook/09_github_community.md)
