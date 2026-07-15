# 09 — GitHub community inbox, auto-reply, test loop, personal repos

**Goal:** Answer anyone on issues/PRs from one desk; on every response **run tests and share results**; use the **same loop on personal repos**; optionally **keep running autonomously** and **pull arXiv papers to improve code**.

## Automatic loop (GitHub Actions)

On **VincentMarquez/nexus-core** (or any repo after `init`):

1. Issue/PR opens → greeting + baseline checks posted  
2. Someone comments → bot runs install/pytest/smoke → posts PASS/FAIL  
3. They reply again (or push PR commits) → loop repeats  

Opt out once: comment `/skip-loop`.

## Brand-new personal repo

```bash
mkdir -p ~/code/my-app && cd ~/code/my-app
git init
# … add your code …
nexus github init --path .
git add .github NEXUS_COMMUNITY.md
git commit -m "chore: enable NEXUS community loop"
gh repo create my-app --private --source=. --push
# Actions now run the loop on this personal repo
```

## Fully autonomous on your machine (opt-in)

```bash
# Cloud: already on when workflow is pushed
# Laptop/server daemon — posts loop results when people talk:
nexus github watch --repo YOU/my-app --workdir . --autonomous --interval 120
```

Without `--autonomous`, watch only logs activity.

## Search other repos → continuous improvement

```bash
nexus github search "multi agent durable resume" --limit 10
nexus github scout "multi agent durable" --workdir .
# → .nexus_state/repo_scout/scout-*.md + latest.json

nexus github improve --arxiv "durable multi-agent systems" --with-scout --max 6
nexus github improve --scout "your topic" --apply

# Continuous on your machine: community loop + arXiv + other-repo scout
nexus github watch --autonomous --workdir . \
  --arxiv "your topic" --arxiv-every 86400 \
  --scout "your topic" --scout-every 43200
```

## Local one-stop shop

```bash
gh auth login
make install

nexus github status
nexus github inbox
nexus github draft 1
nexus github reply 1 --dry-run
nexus github loop 1 --dry-run
nexus github loop 1
```

## Markers

- `<!-- nexus-community-bot -->` — greeting / triage  
- `<!-- nexus-community-loop sha=… -->` — test result (dedupe per commit)

## Full doc

[docs/GITHUB_COMMUNITY.md](../docs/GITHUB_COMMUNITY.md)
