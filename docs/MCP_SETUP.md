# MCP setup recipes (generic)

Step-by-step for connecting **your** AI subscriptions to a **NEXUS-style** machine.  
Replace every `<placeholder>` with your values. Nothing here is a live secret.

Transport note: `nexus mcp` implements local stdio MCP. `nexus mcp --http`
starts a minimal unauthenticated JSON tools API for local demos; it is not the
full remote MCP-over-SSE or Streamable HTTP server assumed in sections A, B,
and D. Use a separately deployed, compatible remote MCP server for web-app
connectors.

---

## A. ChatGPT → Workspace MCP (remote)

1. Deploy a web-client-compatible remote MCP server with project-scoped tools.
   Do not substitute the built-in HTTP demo API.
2. Put authentication and TLS in front of it with a private tunnel or reverse
   proxy.
3. Expose the authenticated endpoint with HTTPS, e.g.
   `https://<your-tunnel-host>/mcp`
4. In ChatGPT: **Settings → Connectors / Apps → Add custom MCP**.
5. Paste the URL. Name it something like `nexus-workspace`.
6. In a new chat, **enable** the connector (tools must appear).
7. Test: list files in the project root; send a workspace ping with
   `agent: "chatgpt_web"`.

---

## B. Grok → Workspace MCP (remote)

1. Same MCP URL as ChatGPT (one server, many clients).  
2. Grok → **Connectors → New → Custom**.  
3. Paste URL, save.  
4. Enable connector in the conversation.  
5. When posting to a shared workspace, force  
   `agent: "grok_web"` so logs don’t look like another product.

---

## C. Claude Desktop → Machine MCP (stdio)

1. Install Node 18+ on the machine.  
2. Run / install your `machine-mcp.js` (stdio).  
3. Point Claude Desktop config at the command (see example JSON in `connectors/examples/`).  
4. Restart Claude Desktop; confirm tools list.  
5. Prefer **queued shell** (daemon) over raw unbounded `child_process` for safety.

---

## D. Claude / others → remote Workspace MCP

If the product supports custom HTTPS MCP connectors, reuse the same  
`https://<your-tunnel-host>/mcp` URL as ChatGPT/Grok.

---

## E. Phone memory MCP

1. Run a small MCP server on the phone (or paired device).  
2. Publish it only on a **private network or auth tunnel**.  
3. On the lab machine:

```bash
export PHONE_MCP_URL="https://<your-phone-tunnel>/mcp"
```

4. Clients treat it as **best-effort**: offline → empty results.  
5. Do not block durable tasks on phone availability.

---

## F. Local LLM + CLI (this repo — no MCP required)

```bash
make install
source .venv/bin/activate
nexus start -y                 # Ollama + bus + dashboard
nexus start -y --with-cli      # also Claude/Codex/Gemini CLIs if installed
```

Subscriptions authenticate via **CLI login**, not via this git repo.

---

## G. Shared rules for all connectors

| Rule | Detail |
|------|--------|
| Project root | Direct file tools reject paths outside `NEXUS_PROJECT_ROOT`; this is not a complete capability sandbox |
| No fake tools | If connector isn’t attached, say so |
| Agent labels | Distinct id per AI product |
| Logs | JSONL may contain prompts, outputs, paths, and tool arguments; inspect and redact before sharing |
| Rotate | Tunnel auth / tokens outside git |

The wider MCP catalog may include write and operational tools. Catalog
privilege labels describe tools but do not enforce authorization at call time.
Restrict the enabled catalog, operating-system permissions, network access, and
available credentials. See [security and trust boundaries](SECURITY.md).

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Tools missing in chat | Connector not enabled for that conversation |
| 401 / 403 from URL | Tunnel auth or expired token |
| Works on LAN, fails on phone app | Need public HTTPS tunnel or VPN into tailnet |
| Shell tools hang | Exec daemon not running / queue path wrong |
| Two agents look like one | Forgot distinct `agent:` labels |
