# 09 — GitHub community inbox, auto-reply, and test loop

**Goal:** Answer anyone on issues/PRs from one desk, and on every response **run tests and share results** automatically.

## Automatic loop (GitHub Actions)

On **VincentMarquez/nexus-core**, `.github/workflows/community-bot.yml`:

1. Issue/PR opens → greeting + baseline checks posted  
2. Someone comments → bot runs install/pytest/smoke → posts PASS/FAIL  
3. They reply again (or push PR commits) → loop repeats  

Opt out once: comment `/skip-loop`.

## Local one-stop shop

```bash
gh auth login
make install

nexus github status
nexus github inbox
nexus github draft 1
nexus github reply 1 --dry-run
nexus github loop 1 --dry-run    # run checks, do not post
nexus github loop 1              # post results on #1
```

## Custom body + loop

```bash
nexus github reply 3 --body "Thanks — trying a fix now."
# after you push / they reply, Actions (or local loop) posts test evidence
nexus github loop 3 --force
```

## Markers

- `<!-- nexus-community-bot -->` — greeting / triage  
- `<!-- nexus-community-loop sha=… -->` — test result (dedupe per commit)

## Full doc

[docs/GITHUB_COMMUNITY.md](../docs/GITHUB_COMMUNITY.md)
