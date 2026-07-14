# Roadmap

Ideas for growing NEXUS Core. Order is a suggestion, not a commitment.

## Near term

- [ ] Optional dense embeddings behind the same `memory.search` API  
- [ ] Richer SSE event types from the Python engine (task_started, step_done)  
- [ ] Pluggable checkpointer interface (JSON today; SQLite / LangGraph later)  
- [ ] More smoke tasks in `evals/` (fault injection, offline agent)  

## Medium term

- [ ] Reference Workspace MCP server implementation (SSE) in-repo  
- [ ] Reference Machine MCP (stdio) skeleton with project jail  
- [ ] Expanded dashboard (approve button, live step log)  
- [ ] Routing scores from historical `agent_calls`  
- [ ] Example Docker Compose: bus + ollama + engine  

## Longer term

- [ ] Multi-project / multi-tenant examples  
- [ ] Published benchmarks for resume reliability and judge quality  
- [ ] Language bindings or HTTP-only control plane  

Contributions that match the design principles in the README are especially welcome.
