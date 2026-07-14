# Memory spine

One retrieval API for chat turns, docs, and graph nodes.

## API

```python
mem.search(query, ns="proj/demo", k=5)
# → [{text, score, source, kind, ns}, ...]
```

## Rankers (RRF fused)

| Ranker | Role |
|--------|------|
| Lexical | BM25-like token overlap (always on) |
| Dense | Optional embedding cosine (fail-open if unavailable) |
| Graph hop | Expand via neighbor links when graph provided |

Reciprocal Rank Fusion (RRF) merges lists with `k0=60`.

## Namespaces

Queries are **hard-filtered** by namespace. A `proj/a` search never returns `proj/b` chunks.

## Fail-open

If dense embedder or graph is down, retrieval degrades to lexical only.  
The task engine must continue.

## What not to store in a public demo

PHI, secrets, personal chat exports, raw credentials.  
Use synthetic chunks only in examples.
