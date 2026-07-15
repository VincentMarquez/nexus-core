# 11 — Heartbeat, cloud poke, WiFi recovery

**Goal:** Get notified when the lab host loses power/WiFi; optionally soft-recover network when the machine is still up.

## Cloud poke (works even if the PC is off)

```bash
# 1) Create check at https://healthchecks.io
export NEXUS_HEARTBEAT_URL='https://hc-ping.com/YOUR-UUID'

nexus heartbeat init --url "$NEXUS_HEARTBEAT_URL"
nexus heartbeat once
nexus heartbeat install-cron
# paste the printed line into: crontab -e
```

GitHub secrets for `.github/workflows/deadman.yml`:

- `HEALTHCHECK_STATUS_URL`
- `NOTIFY_WEBHOOK` (optional Discord/Slack)

## Local recovery (machine still powered)

```bash
nexus recovery network
nexus recovery wifi --allow-reconnect   # opt-in nmcli
```

## Full docs

[docs/RESILIENCE.md](../docs/RESILIENCE.md)
