# Schedule local NEXUS jobs and optional remote reviews

NEXUS can print cron entries for local heartbeat, repository-mining, and Alive
jobs. Remote AI applications require their own scheduler and a compatible,
authenticated remote MCP deployment.

## Print the local schedule

```bash
nexus schedule --query "multi agent durable"
```

The command only prints lines; it does not install them. Review the output, then
paste selected entries into `crontab -e`.

Typical entries:

| When | Job |
|---|---|
| Every 5 minutes | `nexus heartbeat once` |
| Twice daily | Heuristic repository discovery and grading |
| Twice daily | Refresh the local improvement plan |
| Every 6 hours | One Alive cycle using the current `alive.json` |

Review [Alive](ALIVE.md) before scheduling it. Even with implementation and push
flags disabled, a real cycle can use network services and update local candidate
state and planning/evidence documents.

`--mcp-http` can add an `@reboot` entry for the built-in local HTTP tools demo:

```bash
nexus schedule --mcp-http
```

That demo API is unauthenticated and is not a full remote MCP transport. Keep it
on localhost. Do not tunnel it to the internet or use it as a web-app connector.

## Repository research loop

Run these interactively before scheduling them:

```bash
nexus github mine run -q "multi agent durable" -n 8 --improve
nexus github mine improve-ours --repo YOU/REPO
```

Repository clone/proof paths can execute project-controlled installers and
tests. The generated schedule uses heuristic-only mining, but operators should
still review its current commands and use isolated, credential-free execution
for untrusted repositories.

Code application remains a separate explicit action:

```bash
nexus github mine improve-ours --apply --repo YOU/REPO
```

Do not place `--apply`, self-approval, or push commands on a schedule until the
target, branch protection, token budget, credentials, and recovery plan have
been reviewed.

## Remote AI clients

For ChatGPT, Claude, Grok, or another web client:

1. deploy a compatible remote MCP server separately;
2. protect it with authentication, TLS, least-privilege tools, and host/network
   isolation;
3. connect the client using its supported connector flow; and
4. use that product's supported task/reminder scheduler if unattended reviews
   are required.

The built-in `nexus mcp` command supports local stdio MCP. The
`nexus mcp --http` mode is only a local JSON tools demo and is not a substitute
for the remote server in this pattern.

See [MCP setup](MCP_SETUP.md), [Connectors](CONNECTORS.md), and
[Security and trust boundaries](SECURITY.md).

## Review workflow

A safer division of responsibility is:

```text
local cron
  → heartbeat
  → heuristic discovery / candidate state
  → planning artifacts

operator or authenticated remote reviewer
  → inspect artifacts
  → approve a clean, dedicated branch
  → run apply manually
  → verify tests and diff
```

Runtime files under `.nexus_state/` may contain prompts, outputs, paths, logs,
and operator feedback. Inspect and redact them before sharing.
