# Repo mine — use other codebases (don’t follow people)

ML architecture (alive + mine + budget): ![arch-alive-self-improve.svg](assets/arch-alive-self-improve.svg)

Inspired by tools like [yumiaura/followme](https://github.com/yumiaura/followme), but with a different endgame:

| followme | NEXUS `github mine` |
|----------|---------------------|
| fetch → evaluate → **follow** → **star** | fetch → evaluate → **connect/prove** → **use notes** |
| grows your social graph | grows **your local library of proven repos** |
| needs `user:follow` token | only needs `gh` search/clone (public) |

## Pipeline

```text
GitHub Search
    → SQLite (.nexus_state/repo_mine.sqlite)
    → shallow clone + **Grok grade** (hard) → local Ollama (light) → heuristic
    → keep score ≥ threshold
    → clone/pull into .nexus_workspaces/scout_repos/
    → optional install/test prove
    → USE_LATEST.md  (how to port into *your* project)
    → improve-ours: **Grok hard apply** (opt-in) or bus job
```

**Never** calls GitHub follow or star APIs.

## Who does the work?

| Role | Engine | Notes |
|------|--------|--------|
| **Hard grading** | Grok CLI (`grok_worker.grok_grade`) | idea/skill/description for reuse |
| **Light fallback** | Local Ollama | if Grok offline/budget or `--grader ollama` |
| **Offline** | Heuristic keywords | `--heuristic-only` / `--grader heuristic` |
| **Hard improve** | Grok CLI (`grok_hard_improve`) | `--apply` with `--worker auto\|grok` |
| **Bus apply** | Local panel job | `--worker bus` |

```bash
# Prefer Grok for grade + hard work; keep Ollama for light turns
export NEXUS_GROK_MODEL=grok-4.5   # optional pin
nexus github mine evaluate -l 5 --grader auto
nexus github mine improve-ours --apply --worker grok
```

## Commands

```bash
# Full pipeline once (Grok grades by default)
nexus github mine run -q "multi agent durable" -n 8 --min-score 12

# Step by step
nexus github mine fetch -n 10 -q "orchestrat LLM" --language Python --max-stars 500
nexus github mine evaluate -l 10                 # Grok → Ollama → heuristic
nexus github mine evaluate -l 10 --grader grok
nexus github mine evaluate -l 10 --heuristic-only
nexus github mine use --min-score 12 --limit 5   # keep winners for your code
nexus github mine list
nexus github mine list --used
```

## Scoring

- `idea` 1–10 novelty  
- `skill` 1–10 engineering  
- **score** = idea + skill (threshold default **12**, range 2–20)  

Grok (then Ollama) grades for **reuse**, not social popularity.

## After mine — improve **our** code

```bash
ls .nexus_workspaces/scout_repos/
less .nexus_state/repo_mine/USE_LATEST.md

# Plan from top scores (always safe)
nexus github mine improve-ours --min-score 12
less .nexus_state/repo_mine/IMPROVE_OURS.md

# Port patterns into THIS project (opt-in; Grok hard worker by default)
nexus github mine improve-ours --apply --worker grok
# or durable bus job with local agents:
nexus github mine improve-ours --apply --worker bus --repo VincentMarquez/nexus-core
make demo-all-quick
```

Full pipeline with plan step:

```bash
nexus github mine run -q "multi agent" --improve
nexus github mine run -q "multi agent" --improve --apply --worker grok
```

## vs `github scout`

| | `scout` | `mine` |
|--|---------|--------|
| State | latest notes JSON | durable SQLite of many runs |
| Grade | informal | idea+skill scores |
| Goal | one-shot related digests | continuous library of **useable** clones |
