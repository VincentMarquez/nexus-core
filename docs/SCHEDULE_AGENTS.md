# Schedule ChatGPT / Claude / Grok on NEXUS + auto-mine for *your* code

Yes: you can **schedule** work so cloud agents (ChatGPT, Claude) and local jobs keep using NEXUS — and scored external repos feed **improvements to your project**.

## The chase (what you wanted)

```text
1. Discover other repos (search)
2. Score them (Ollama or heuristic)     idea + skill
3. USE them (clone + prove locally)     not follow/star
4. Improve OURS (plan + optional apply)
5. Optional: ChatGPT/Claude on a schedule hit the same tools via MCP
```

```bash
# Score → use → write plan to improve *this* repo
nexus github mine run -q "multi agent durable" -n 8 --improve
# Actually port patterns (opt-in durable job):
nexus github mine improve-ours --apply --repo VincentMarquez/nexus-core
```

## Schedule on this machine

```bash
nexus schedule --query "multi agent durable" --mcp-http
# paste into: crontab -e
```

Typical lines:

| When | Job |
|------|-----|
| every 5 min | `nexus heartbeat once` (cloud poke if host dies) |
| 09:00 & 21:00 | `nexus github mine run …` (discover + grade + use) |
| 09:30 & 21:30 | `nexus github mine improve-ours` (refresh IMPROVE_OURS.md) |
| @reboot | `nexus mcp --http` (for ChatGPT remote connector) |

**`--apply` is never on cron by default** — only plan files. You run apply when you want code changes.

## ChatGPT on a schedule using NEXUS

ChatGPT cannot natively “cron” itself easily; two patterns work:

### A. Always-on MCP + you (or Zapier) open a scheduled chat

1. On the lab machine:

```bash
nexus platforms connect --force
nexus mcp --http --host 127.0.0.1 --port 8765
# tunnel:
cloudflared tunnel --url http://127.0.0.1:8765
```

2. ChatGPT → **Settings → Connectors → Custom MCP** → paste `https://….trycloudflare.com`.  
3. Enable connector in a chat.  
4. Schedule a reminder (phone/calendar/Zapier) that opens ChatGPT with a prompt like:

> Using nexus-workspace tools: run list_platforms, run_project_checks,  
> github_scout for "multi agent", and send_to_workspace a summary as agent chatgpt_web.

### B. Machine cron does the heavy lifting; ChatGPT only reviews

Cron runs `mine` + `improve-ours` and writes:

- `.nexus_state/repo_mine/USE_LATEST.md`  
- `.nexus_state/repo_mine/IMPROVE_OURS.md`  

You (or a scheduled ChatGPT/Claude session with MCP) only **read those files** and approve/apply:

```bash
nexus github mine improve-ours --apply --repo YOU/REPO
```

## Claude on a schedule

1. `nexus platforms connect` → Claude Desktop / `claude-desktop.nexus.json`  
2. Or Claude Code CLI with MCP.  
3. Same cron files as above; Claude can be pointed at `IMPROVE_OURS.md`.  
4. Bus path: `nexus start -y` so agent `claude` is on the event bus for long jobs.

## Grok CLI

Already first-class: `nexus platforms connect` + local model + MCP tools.  
Schedule: same cron; interactive Grok when you want to drive tools by hand.

## End-to-end daily loop

```text
cron: mine run
   → high-score repos cloned under .nexus_workspaces/scout_repos/
   → IMPROVE_OURS.md updated
cron: heartbeat
   → Healthchecks knows the host is alive
you / ChatGPT / Claude (MCP):
   → read IMPROVE_OURS.md
   → optional: improve-ours --apply
   → make demo-all-quick
```

That **is** the chase: **score other repos → use them to improve ours**, with cloud AIs optional co-pilots on the same NEXUS tool surface.
