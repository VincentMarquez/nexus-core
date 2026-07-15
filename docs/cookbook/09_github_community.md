# 09 — GitHub community inbox & auto-reply

**Goal:** Answer anyone on issues/PRs from one desk — automatically on GitHub, interactively on your machine.

## Automatic (GitHub Actions)

Already in the repo: `.github/workflows/community-bot.yml`.

1. Ensure Actions can write issues/PRs (workflow sets `permissions`).  
2. Open a new issue on `VincentMarquez/nexus-core`.  
3. Within ~1 minute you should see a first-reply comment with docs links.  

Re-trigger on a comment by writing `@nexus` or `/triage`.

## Local one-stop shop

```bash
gh auth login
make install

nexus github status
nexus github inbox
nexus github draft 1
nexus github reply 1 --dry-run
nexus github reply 1
nexus github auto --dry-run
```

## Custom body

```bash
nexus github reply 3 --body "Shipped in v0.7.0 — thanks!"
echo "LGTM after squash" | nexus github reply 4 --stdin
```

## Combined with repair jobs

```bash
# someone filed "tests fail on 3.12"
nexus do VincentMarquez/nexus-core --goal "make CI green on 3.12"
# then report back
nexus github reply 7 --body "Reproduced and fixed on main; please pull and re-run make test."
```

## Marker

Comments include `<!-- nexus-community-bot -->` so auto mode skips threads already handled.

## Full doc

[docs/GITHUB_COMMUNITY.md](../docs/GITHUB_COMMUNITY.md)
