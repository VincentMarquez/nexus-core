# Resilience: power, WiFi, and cloud pokes

## Short answers

| Event | What NEXUS does | What it does **not** do |
|-------|------------------|-------------------------|
| Process crash | Durable jobs **resume** from `.nexus_state/` | — |
| WiFi drops | Local LLM/tools can continue; cloud features pause | Auto-fix WiFi unless you opt in |
| Power loss | State on disk usually survives | Nothing runs while the machine is off |
| Host unreachable | **Cloud dead-man** can poke you | Local agent cannot phone home without power/network |

## Architecture

```text
  your PC (must be powered)
       │  every 5 min
       ▼
  nexus heartbeat once  ──ping──►  Healthchecks.io (cloud)
                                       │
                         missed 2–3 beats
                                       ▼
                              email / SMS / phone app
                                       +
                         GitHub Actions deadman.yml
                                       ▼
                              issue + Discord/Slack webhook
                              (“host heartbeat DOWN”)
```

**Rule:** the notifier must live **off** the dead machine.

## Setup (15 minutes)

### 1. Healthchecks.io (or any ping URL)

1. Create a check (period 5 min, grace 10 min).  
2. Copy the **ping URL** (`https://hc-ping.com/<uuid>`).  
3. On the lab machine:

```bash
cd ~/nexus-core
export NEXUS_HEARTBEAT_URL='https://hc-ping.com/YOUR-UUID'
nexus heartbeat init --url "$NEXUS_HEARTBEAT_URL"
nexus heartbeat once
nexus heartbeat install-cron   # copy crontab line
crontab -e                     # paste
```

Optional Discord/Slack when *local* WiFi recovery fails (needs some network):

```bash
export NEXUS_HEARTBEAT_WEBHOOK='https://discord.com/api/webhooks/…'
nexus heartbeat init --url "$NEXUS_HEARTBEAT_URL" --webhook "$NEXUS_HEARTBEAT_WEBHOOK"
```

### 2. GitHub Actions companion

Repo secrets:

| Secret | Purpose |
|--------|---------|
| `HEALTHCHECK_STATUS_URL` | Healthchecks API status for the check |
| `HEALTHCHECK_API_KEY` | Optional API key header |
| `NOTIFY_WEBHOOK` | Optional Discord/Slack webhook |

Workflow: [`deadman.yml` on GitHub](https://github.com/VincentMarquez/nexus-core/blob/main/.github/workflows/deadman.yml)  
Runs every 15 minutes; if status is `down`, opens/comments a GitHub issue and fires the webhook.

### 3. Local recovery (opt-in)

```bash
nexus recovery status
nexus recovery network                 # diagnose only
nexus recovery wifi                    # diagnose; tells you if offline
nexus recovery wifi --allow-reconnect  # nmcli reconnect (opt-in)
```

**Reboot (dangerous, double gate):**

```bash
NEXUS_ALLOW_REBOOT=1 nexus recovery reboot --allow-reboot
```

Neither reboot nor reconnect runs unless you pass the flags. Default is diagnose-only.

## After the machine is back

```bash
nexus start -y
nexus heartbeat once
nexus recovery network
# resume durable jobs if needed
nexus do owner/repo --resume <job-id>
```

## CLI cheatsheet

| Command | Role |
|---------|------|
| `nexus heartbeat init --url …` | Save ping config |
| `nexus heartbeat once` | Single ping (cron) |
| `nexus heartbeat watch` | Foreground loop |
| `nexus heartbeat status` | Last beat + network probe |
| `nexus heartbeat install-cron` | Print crontab + instructions |
| `nexus recovery network` | Diagnose connectivity |
| `nexus recovery wifi --allow-reconnect` | Soft WiFi fix |
| `nexus recovery reboot --allow-reboot` | Reboot (env gate required) |

## Design principles

1. **Cloud pokes ≠ local agents** — separation of failure domains.  
2. **Autonomy opt-in** — reconnect/reboot never default.  
3. **Resume over hope** — durable engine still the answer for process death.  
4. **Allowlisted recovery** — `nmcli` / `systemctl reboot` only, no free-form shell from an LLM.
