# 06 — Paste a GitHub URL, let NEXUS do the rest

**Goal:** Point NEXUS at any public GitHub repo. It clones, installs, runs checks, and tries to fix failures.

## One liner

```bash
./run https://github.com/owner/repo
# or after install:
nexus do owner/repo
nexus do https://github.com/owner/repo --goal "make the tests pass"
```

## What it does

1. Starts the NEXUS stack (bus + agents) if it isn’t up  
2. `git clone --depth 1` into `.nexus_workspaces/owner__repo`  
3. Detects Python / Node / Go / Rust layouts  
4. Installs dependencies (pip / npm / yarn / pnpm / go / cargo / make)  
5. Runs tests / lint / build when it can discover them  
6. **Fix loop** (up to 3 rounds): agents (or heuristics) propose file writes + safe commands  
7. Writes `NEXUS_REPORT.md` in the workdir  

## Resume after crash

```bash
nexus do owner/repo --resume gh-owner-repo-abc12345
```

Job state lives under `.nexus_state/github_jobs/`.

## Safety

- Only **allowlisted** tools run (`pip`, `npm`, `pytest`, `go`, `cargo`, `make`, …)  
- Agent file writes are **jailed** under the workdir  
- No `sudo`, no `curl | sh`  
- Docker Compose is detected but **not** auto-started  

## Heuristic-only (no LLM)

```bash
nexus do owner/repo --heuristic-only --no-start
```

## Tip

Install Ollama and/or Claude/Codex/Gemini CLIs first so fix rounds can use real agents:

```bash
./run   # wires agents automatically
nexus do psf/requests --goal "install and run a quick import check"
```
