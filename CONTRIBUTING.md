# Contributing to NEXUS Core

Thanks for helping. Small, tested changes that protect the design principles in the README are the best contributions.

## Dev setup

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
make install
make test
make smoke
```

## Before you open a PR

1. `make test` and `make smoke` pass  
2. New behavior has a test or an eval case when practical  
3. Docs updated if you change a public API or CLI  
4. No secrets, tokens, or machine-specific absolute paths  

## Good first issues

Look for labels:

- `good first issue` — small docs/tests/examples  
- `help wanted` — slightly larger, still scoped  

## Design principles (don’t break these)

- Engine wraps step runners; doesn’t reimplement step bodies  
- Presence ≠ success (judge scores criteria + evidence)  
- Autonomy defaults **off**  
- Memory fail-open; offline agents are not treated as healthy  
- Cascade / shallow index before deep navigation  

## PR style

- One concern per PR when possible  
- Clear description: problem → approach → how tested  
- Keep the public tone professional (this is a community project)

## Questions

Open a GitHub Discussion or Issue. Be kind; assume good intent.
