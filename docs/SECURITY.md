# Security and trust boundaries

NEXUS coordinates tools and can execute project workflows. It is not a security
sandbox. This page describes the operational boundaries to review before
running third-party code or enabling remote, autonomous, or write-capable
operations.

For private vulnerability reports, supported versions, and disclosure
instructions, use the repository-level
[security policy](https://github.com/VincentMarquez/nexus-core/security/policy).

## Repository execution

`nexus do`, repository proof jobs, and community test loops may run package
installers, build hooks, Make targets, and tests from the selected checkout.
The command-name allowlist rejects some obvious commands, but an allowed
interpreter, package manager, build tool, or test runner can still execute
repository-controlled code.

Use trusted commits or run target repositories in an isolated, credential-free
container or virtual machine. Restrict filesystem access, network access, and
environment variables at the operating-system boundary. Child processes inherit
the environment and may also reach credential stores used by authenticated
provider and GitHub CLIs.

## GitHub Actions and untrusted pull requests

Never check out and execute untrusted pull-request code in the same job that has
a write-capable GitHub token or other secrets. Split the workflow into:

1. an untrusted test job with read-only permissions and no secrets; and
2. a trusted reporting or publishing job that consumes only validated
   artifacts.

The bundled write-capable community workflow excludes fork PR heads and runs PR
checks only for same-repository branches, which must be treated as trusted. Add
a separate read-only, secret-free workflow when untrusted fork testing is
required. Review the generated workflow before enabling it in another
repository.

## MCP and remote access

The built-in `nexus mcp --http` tools API is a local demo API, not the full
remote MCP transport described in the connector patterns. It has no built-in
application authentication. Keep it bound to localhost and do not expose it
directly to the public internet.

Direct file tools enforce `NEXUS_PROJECT_ROOT`, but that path check is not a
complete capability sandbox. The wider MCP catalog can include write and
operational tools, and catalog privilege labels are descriptive metadata rather
than call-time authorization.

## Runtime state

`.nexus_state/` is gitignored but not encrypted. Depending on the workflow, it
may contain prompts, model outputs, source excerpts, task history, local paths,
stdout/stderr, tool arguments, usage data, and operator feedback.

Treat it as sensitive local data:

- do not use it as a secret store;
- inspect it before sharing logs or evidence packs;
- remove or redact confidential material before publication; and
- protect the host account and filesystem that contain it.

## Providers and credentials

Provider authentication belongs in each provider's supported CLI, secret
manager, or environment configuration. Never commit API keys, OAuth tokens,
cookies, tunnel URLs, personal hostnames, or credential-bearing config files.

## Autonomous writes and publishing

Apply, activation, self-approval, commit, and push paths are advanced
operations. When enabling them:

- use a clean, dedicated branch or worktree;
- protect the default branch;
- inspect the effective configuration and staged diff;
- keep unrelated changes out of the working tree; and
- use least-privilege credentials.

A “no force-push” rule and an allowlist reduce risk; they do not make an
autonomous publish path safe by themselves.

## Safer starting points

- `make demo-all-quick` exercises local orchestration without live model keys.
- `nexus github watch --once` observes without `--autonomous`.
- `nexus github scout "topic" --structure-only` avoids dependency installation
  and test execution in discovered repositories.
- `nexus mcp` uses local stdio; remote HTTP access requires an external
  authentication boundary.

Related guides:

- [Getting started](getting-started.md)
- [Repository execution](cookbook/06_github_do.md#safety)
- [GitHub community workflows](GITHUB_COMMUNITY.md#safety)
- [MCP setup](MCP_SETUP.md)
- [Connectors](CONNECTORS.md)
- [Alive and publishing](ALIVE.md)
