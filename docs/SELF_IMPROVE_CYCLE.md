# Self-improve cycle — Grok 4.5

_Generated 2026-07-15 · hard-apply worker_

Model: `grok-4.5` · repos≈20 · arXiv≈20

---

## Reasoning plan (this cycle)

1. **Read evidence** — `IMPROVE_OURS.md` top clones + latest arXiv notes (`rx-ae18c1bce0` and priors).
2. **Inventory landed work** — P0 durability through P3 promote gates, sample packs, Ollama judge.
3. **Pick First apply slice** — close open items only; small, tested, no tree vendoring.
4. **Apply** — Grok judge adapter + self_approve→promote auto-wire + CI sample smoke.
5. **Prove** — `pytest` green; offline sample pack run; docs updated.

## First apply slice

See `docs/LATEST_IMPROVE_PLAN.md` § First apply slice (P2.7 + P3.3 + CI).

## Sources (patterns only)

| Source | Pattern ported |
|--------|----------------|
| IBM/AssetOpsBench | scenario packs + judge scorer shape |
| builderz-labs/mission-control | CLI/MCP/CI parity |
| Intelligent-Internet/zenith | independent verify before promote |
| wmcmahan/cycgraph (prior) | promote gate discipline |
| arXiv 2401.07324 | multi-LLM tool agents (Grok + Ollama judges) |
| arXiv 2511.15755 | deterministic multi-agent tool audit |
| arXiv 2508.08322 | bounded context (already landed) |

## Non-goals

- Do not force-push; do not commit secrets; do not vendor whole upstream trees.
- Prefer offline-safe defaults (heuristic fallback for LLM judges).
