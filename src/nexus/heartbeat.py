"""Machine heartbeat + cloud dead-man support.

Local host pings an external URL (Healthchecks.io / custom) on a schedule.
If the machine loses power or WiFi, pings stop and the *cloud* monitor notifies you.

  nexus heartbeat once
  nexus heartbeat watch --interval 300
  nexus heartbeat status
  nexus heartbeat install-cron

Config (first match wins):
  env NEXUS_HEARTBEAT_URL
  env HEALTHCHECK_URL / HEALTHCHECKS_PING_URL
  file .nexus_state/heartbeat.json  → {"ping_url": "https://…", "host_id": "lab"}
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


CONFIG_NAME = "heartbeat.json"
STATE_NAME = "last_heartbeat.json"


@dataclass
class HeartbeatConfig:
    ping_url: str = ""
    status_url: str = ""  # optional Healthchecks status endpoint for Actions
    host_id: str = ""
    notify_webhook: str = ""  # optional Discord/Slack/generic POST when *local* recovery fails
    interval_s: int = 300
    github_repo: str = ""  # optional owner/repo for Actions companion
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HeartbeatConfig":
        return cls(
            ping_url=str(d.get("ping_url") or ""),
            status_url=str(d.get("status_url") or ""),
            host_id=str(d.get("host_id") or ""),
            notify_webhook=str(d.get("notify_webhook") or ""),
            interval_s=int(d.get("interval_s") or 300),
            github_repo=str(d.get("github_repo") or ""),
            extra={k: v for k, v in d.items() if k not in {
                "ping_url", "status_url", "host_id", "notify_webhook",
                "interval_s", "github_repo",
            }},
        )


def _state_dir(root: Optional[Path] = None) -> Path:
    base = Path(root or os.getcwd()).resolve() / ".nexus_state"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path(root: Optional[Path] = None) -> Path:
    return _state_dir(root) / CONFIG_NAME


def state_path(root: Optional[Path] = None) -> Path:
    return _state_dir(root) / STATE_NAME


def load_config(root: Optional[Path] = None) -> HeartbeatConfig:
    cfg = HeartbeatConfig()
    p = config_path(root)
    if p.is_file():
        try:
            cfg = HeartbeatConfig.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    # env overrides
    url = (
        os.environ.get("NEXUS_HEARTBEAT_URL")
        or os.environ.get("HEALTHCHECK_URL")
        or os.environ.get("HEALTHCHECKS_PING_URL")
        or cfg.ping_url
    )
    cfg.ping_url = (url or "").strip()
    if os.environ.get("NEXUS_HEARTBEAT_STATUS_URL"):
        cfg.status_url = os.environ["NEXUS_HEARTBEAT_STATUS_URL"].strip()
    if os.environ.get("NEXUS_HEARTBEAT_WEBHOOK"):
        cfg.notify_webhook = os.environ["NEXUS_HEARTBEAT_WEBHOOK"].strip()
    if os.environ.get("NEXUS_HOST_ID"):
        cfg.host_id = os.environ["NEXUS_HOST_ID"].strip()
    if not cfg.host_id:
        cfg.host_id = socket.gethostname()
    return cfg


def save_config(cfg: HeartbeatConfig, root: Optional[Path] = None) -> Path:
    p = config_path(root)
    p.write_text(json.dumps(cfg.to_dict(), indent=2) + "\n", encoding="utf-8")
    return p


def probe_network(*, timeout: float = 3.0) -> dict[str, Any]:
    """Best-effort connectivity probes (does not fix anything)."""
    checks: list[dict[str, Any]] = []

    def _http(url: str) -> dict[str, Any]:
        t0 = time.time()
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": "nexus-heartbeat"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                code = getattr(r, "status", 200)
            return {"target": url, "ok": 200 <= int(code) < 500, "ms": int((time.time() - t0) * 1000)}
        except Exception as e:
            return {"target": url, "ok": False, "error": str(e)[:200], "ms": int((time.time() - t0) * 1000)}

    def _dns(host: str) -> dict[str, Any]:
        t0 = time.time()
        try:
            socket.getaddrinfo(host, 443)
            return {"target": f"dns:{host}", "ok": True, "ms": int((time.time() - t0) * 1000)}
        except Exception as e:
            return {"target": f"dns:{host}", "ok": False, "error": str(e)[:200]}

    checks.append(_dns("1.1.1.1"))
    checks.append(_dns("github.com"))
    checks.append(_http("https://1.1.1.1"))
    checks.append(_http("https://api.github.com"))
    online = any(c.get("ok") for c in checks if str(c.get("target", "")).startswith("https"))
    return {
        "online": online,
        "checks": checks,
        "ts": time.time(),
        "host": socket.gethostname(),
    }


def ping_url(url: str, *, timeout: float = 10.0, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """HTTP GET (or POST JSON) to heartbeat / Healthchecks ping URL."""
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "empty ping_url"}
    t0 = time.time()
    try:
        data = None
        headers = {"User-Agent": "nexus-heartbeat/0.8"}
        method = "GET"
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            method = "POST"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = getattr(r, "status", 200)
            _ = r.read()[:500]
        return {
            "ok": 200 <= int(code) < 400,
            "status": int(code),
            "ms": int((time.time() - t0) * 1000),
            "url": url.split("?")[0][:80],
        }
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "status": e.code,
            "error": str(e)[:200],
            "ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "ms": int((time.time() - t0) * 1000)}


def write_local_state(payload: dict[str, Any], root: Optional[Path] = None) -> Path:
    p = state_path(root)
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


def read_local_state(root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    p = state_path(root)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def beat_once(
    root: Optional[Path] = None,
    *,
    dry_run: bool = False,
    force_body: bool = True,
) -> dict[str, Any]:
    """One heartbeat: probe network, ping cloud URL, persist local state."""
    cfg = load_config(root)
    net = probe_network()
    body = {
        "host_id": cfg.host_id,
        "hostname": socket.gethostname(),
        "ts": time.time(),
        "online": net.get("online"),
        "nexus": "heartbeat",
    }
    ping: dict[str, Any]
    if not cfg.ping_url:
        ping = {
            "ok": False,
            "error": "no ping_url configured — set NEXUS_HEARTBEAT_URL or heartbeat.json",
            "skipped": True,
        }
    elif dry_run:
        ping = {"ok": True, "dry_run": True, "url": cfg.ping_url[:80]}
    else:
        # Healthchecks accepts GET; POST body is fine for custom webhooks
        ping = ping_url(cfg.ping_url, body=body if force_body else None)
        # Healthchecks classic UUID URLs prefer GET without body if POST fails
        if not ping.get("ok") and force_body:
            ping = ping_url(cfg.ping_url, body=None)

    state = {
        "ts": time.time(),
        "host_id": cfg.host_id,
        "ping": ping,
        "network": net,
        "ping_url_configured": bool(cfg.ping_url),
    }
    if not dry_run:
        write_local_state(state, root)
    return state


def watch(
    root: Optional[Path] = None,
    *,
    interval_s: Optional[float] = None,
    max_beats: int = 0,
) -> int:
    """Loop forever (or max_beats). Ctrl-C to stop."""
    cfg = load_config(root)
    interval = float(interval_s or cfg.interval_s or 300)
    print(f"=== NEXUS heartbeat watch ===")
    print(f"  host_id:  {cfg.host_id}")
    print(f"  interval: {interval}s")
    print(f"  ping:     {(cfg.ping_url[:60] + '…') if cfg.ping_url else '(not configured)'}")
    print("  Ctrl-C to stop")
    n = 0
    try:
        while True:
            n += 1
            res = beat_once(root)
            ok = (res.get("ping") or {}).get("ok")
            online = (res.get("network") or {}).get("online")
            print(
                f"  beat {n}: ping={'OK' if ok else 'FAIL'} "
                f"net={'up' if online else 'down'} "
                f"ts={time.strftime('%H:%M:%S')}"
            )
            if max_beats and n >= max_beats:
                return 0 if ok else 1
            time.sleep(max(30.0, interval))
    except KeyboardInterrupt:
        print("\n  stopped.")
        return 0


def cron_line(
    *,
    project_root: Optional[Path] = None,
    interval_min: int = 5,
    python: Optional[str] = None,
) -> str:
    """Suggested crontab entry for unattended pings."""
    root = Path(project_root or os.getcwd()).resolve()
    py = python or os.environ.get("NEXUS_PYTHON")
    if not py:
        venv = root / ".venv" / "bin" / "python"
        py = str(venv) if venv.is_file() else "python3"
    # every N minutes
    if interval_min <= 1:
        sched = "* * * * *"
    elif 60 % interval_min == 0 or interval_min < 60:
        sched = f"*/{max(1, interval_min)} * * * *"
    else:
        sched = f"*/5 * * * *"
    return (
        f"{sched} cd {root} && "
        f"NEXUS_PROJECT_ROOT={root} {py} -m nexus.cli heartbeat once "
        f">>{root}/.nexus_state/heartbeat.log 2>&1"
    )


def install_instructions(root: Optional[Path] = None) -> str:
    cfg = load_config(root)
    root = Path(root or os.getcwd()).resolve()
    lines = [
        "# NEXUS heartbeat — cloud dead-man switch",
        "",
        "1) Create a free check at https://healthchecks.io (or any ping URL).",
        "2) Configure ping URL:",
        "",
        f"   export NEXUS_HEARTBEAT_URL='https://hc-ping.com/YOUR-UUID'",
        f"   # or write {config_path(root)}",
        "",
        "3) Cron (machine must be powered on):",
        "",
        f"   crontab -e",
        f"   {cron_line(project_root=root)}",
        "",
        "4) Optional: Discord/Slack webhook when *local* recovery fails (needs network):",
        "   export NEXUS_HEARTBEAT_WEBHOOK='https://…'",
        "",
        "5) GitHub Actions companion: .github/workflows/deadman.yml",
        "   Secret HEALTHCHECK_STATUS_URL = Healthchecks status badge/API URL",
        "   Secret NOTIFY_WEBHOOK = optional Discord/Slack incoming webhook",
        "",
        f"host_id: {cfg.host_id}",
        f"ping configured: {bool(cfg.ping_url)}",
        "",
        "If power or WiFi dies, pings stop → Healthchecks (cloud) emails/texts you.",
        "Local NEXUS cannot notify anyone while the machine is off.",
    ]
    return "\n".join(lines)


def init_config(
    ping_url: str,
    root: Optional[Path] = None,
    *,
    interval_s: int = 300,
    host_id: str = "",
    status_url: str = "",
    notify_webhook: str = "",
) -> Path:
    cfg = load_config(root)
    cfg.ping_url = ping_url.strip()
    cfg.interval_s = interval_s
    if host_id:
        cfg.host_id = host_id
    if status_url:
        cfg.status_url = status_url
    if notify_webhook:
        cfg.notify_webhook = notify_webhook
    return save_config(cfg, root)
