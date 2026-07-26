# Security policy

## Supported versions

Security fixes target the current default branch and the latest tagged release.
Older tags receive fixes on a best-effort basis.

| Version | Support |
|---|---|
| Current default branch | Active development |
| Latest tagged release | Supported |
| Older releases | Best effort |

## Reporting a vulnerability

Do not open a public issue for a security-sensitive report.

Prefer:

1. GitHub Security Advisories for this repository; or
2. a private report to the maintainer through GitHub.

Include the impact, affected versions or commits, reproduction steps, and any
suggested mitigation. Do not include live credentials or private user data.

## Operational security

NEXUS coordinates tools and can execute project workflows. It is not a security
sandbox.

Before running third-party code or enabling remote, autonomous, or
write-capable operations, read
[Security and trust boundaries](docs/SECURITY.md). In particular:

- repository installers, build hooks, and tests can execute project code;
- untrusted pull-request code must not run with write credentials or secrets;
- the built-in HTTP tools API is an unauthenticated local demo, not a remote
  production MCP endpoint;
- `.nexus_state/` is gitignored but may contain sensitive runtime data; and
- autonomous apply, activation, commit, and push paths require a clean,
  dedicated branch plus human review of their configuration and diff.
