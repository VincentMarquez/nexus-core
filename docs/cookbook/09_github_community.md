# 09 — GitHub community inbox, auto-reply, test loop, personal repos

**Goal:** Triage issues and trusted pull requests from one desk, share test
results, and optionally feed research into a local improvement loop.

## Automatic loop (GitHub Actions)

On **VincentMarquez/nexus-core** (or any repo after `init`):

1. Issue or PR opens → greeting
2. Issues and same-repository trusted PR branches can run baseline checks
3. Results are posted without merging

Fork pull-request code is not executed by the bundled write-capable workflow.
Testing untrusted forks requires a separate read-only, secret-free job.

Opt out once: comment `/skip-loop`.

## Brand-new personal repo

```bash
mkdir -p ~/code/my-app && cd ~/code/my-app
git init
# … add your code …
nexus github init --path .
# Review .github/workflows/community-bot.yml and NEXUS_COMMUNITY.md first.
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
nexus github scout "multi agent durable" --workdir . --connect
nexus github connect owner/repo
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
source .venv/bin/activate

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

## Safety

Repository proof and test paths can run installers, build hooks, and tests from
the selected checkout. The command allowlist is not a sandbox, and subprocesses
inherit the environment and may reach CLI credential stores.

Use the local loop only with a trusted checkout or in an isolated,
credential-free environment. Do not execute untrusted pull-request code in a
job with write-capable tokens or secrets. See
[the full community guide](../GITHUB_COMMUNITY.md#safety) and
[security boundaries](../SECURITY.md).

## Full doc

[docs/GITHUB_COMMUNITY.md](../GITHUB_COMMUNITY.md)
