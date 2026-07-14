# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | yes |
| < 0.2   | best effort |

## Reporting a vulnerability

Please **do not** open a public issue for security-sensitive reports.

Prefer:

1. GitHub **Security Advisories** on this repository, or  
2. A private report to the maintainer via GitHub.

Include: impact, reproduction steps, and affected versions if known.

## Scope notes

- The reference event bus is intended for **local / trusted networks**.  
- Do not expose it to the public internet without authentication and TLS.  
- Agent bridges execute local CLIs; treat bridge hosts as trusted compute.  
