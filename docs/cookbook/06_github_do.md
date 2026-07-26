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
6. **Fix loop** (up to 3 rounds): agents (or heuristics) propose project-scoped file writes and allowlisted commands
7. Writes `NEXUS_REPORT.md` in the workdir  

## Resume after crash

```bash
nexus do owner/repo --resume gh-owner-repo-abc12345
```

Job state lives under `.nexus_state/github_jobs/`.

## Safety

`nexus do` is not a security sandbox.

- Installers, build hooks, Make targets, interpreters, and test runners execute
  repository-controlled code. An allowlisted executable such as `pip`, `npm`,
  `make`, or `pytest` can still run arbitrary project code.
- Direct agent file writes are restricted to the selected work directory, but
  operating-system processes launched by the repository are not isolated by
  that path check.
- The command filter blocks some obvious operations such as `sudo` and
  `curl | sh`; it is a guardrail, not an execution boundary.
- Docker Compose is detected but is not auto-started.

Use a trusted commit or run the target in an isolated, credential-free
container or virtual machine with restricted network and filesystem access.
Use `--structure-only` in GitHub scout/connect flows when you only need layout
inspection without dependency installation or tests.

See [security and trust boundaries](../SECURITY.md).

## Heuristic-only (no LLM)

```bash
nexus do owner/repo --heuristic-only --no-start
```

## Tip

For a **trusted** repository, install and authenticate Ollama and/or supported
model CLIs before the run so fix rounds can use real agents:

```bash
./run   # wires agents automatically
nexus do psf/requests --goal "install and run a quick import check"
```

Do not expose authenticated provider or GitHub CLIs to an untrusted checkout.
Repository subprocesses inherit environment variables and may be able to reach
credential stores owned by the host account.
