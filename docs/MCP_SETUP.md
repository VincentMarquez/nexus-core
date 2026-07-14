# MCP setup recipes (generic)

Step-by-step for connecting **your** AI subscriptions to a **NEXUS-style** machine.  
Replace every `<placeholder>` with your values. Nothing here is a live secret.

---

## A. ChatGPT → Workspace MCP (remote)

1. Deploy or run an MCP SSE server on your machine (project-scoped tools).  
2. Expose it with HTTPS (tunnel or reverse proxy), e.g.  
   `https://<your-tunnel-host>/mcp`  
3. In ChatGPT: **Settings → Connectors / Apps → Add custom MCP**.  
4. Paste the URL. Name it something like `nexus-workspace`.  
5. In a new chat, **enable** the connector (tools must appear).  
6. Test: list files in the project root; send a workspace ping with  
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
nexus start -y                 # Ollama + bus + dashboard
nexus start -y --with-cli      # also Claude/Codex/Gemini CLIs if installed
```

Subscriptions authenticate via **CLI login**, not via this git repo.

---

## G. Shared rules for all connectors

| Rule | Detail |
|------|--------|
| Project jail | Tools only under `NEXUS_PROJECT_ROOT` |
| No fake tools | If connector isn’t attached, say so |
| Agent labels | Distinct id per AI product |
| Logs | JSONL with timestamps; no secrets |
| Rotate | Tunnel auth / tokens outside git |

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Tools missing in chat | Connector not enabled for that conversation |
| 401 / 403 from URL | Tunnel auth or expired token |
| Works on LAN, fails on phone app | Need public HTTPS tunnel or VPN into tailnet |
| Shell tools hang | Exec daemon not running / queue path wrong |
| Two agents look like one | Forgot distinct `agent:` labels |
