"""Opt-in local recovery helpers (network / WiFi). Never reboots unless explicitly allowed.

  nexus recovery status
  nexus recovery network
  nexus recovery wifi
  nexus recovery wifi --allow-reconnect
  nexus recovery reboot --allow-reboot   # dangerous; double gate

Design:
  - Default is **diagnose only** (safe).
  - Soft WiFi reconnect requires --allow-reconnect and allowlisted tools (nmcli).
  - Reboot requires --allow-reboot AND env NEXUS_ALLOW_REBOOT=1.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import heartbeat as hb


@dataclass
class RecoveryResult:
    action: str
    ok: bool
    steps: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "ok": self.ok,
            "steps": self.steps,
            "message": self.message,
        }


def _run(cmd: list[str], *, timeout: float = 60) -> dict[str, Any]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "ok": p.returncode == 0,
            "returncode": p.returncode,
            "stdout": (p.stdout or "")[-2000:],
            "stderr": (p.stderr or "")[-1000:],
        }
    except FileNotFoundError:
        return {"cmd": cmd, "ok": False, "error": f"not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "ok": False, "error": f"timeout after {timeout}s"}


def status() -> dict[str, Any]:
    net = hb.probe_network()
    tools = {
        "nmcli": bool(shutil.which("nmcli")),
        "ip": bool(shutil.which("ip")),
        "ping": bool(shutil.which("ping")),
        "systemctl": bool(shutil.which("systemctl")),
    }
    last = hb.read_local_state()
    return {
        "network": net,
        "tools": tools,
        "last_heartbeat": last,
        "allow_reboot_env": os.environ.get("NEXUS_ALLOW_REBOOT") == "1",
        "hint": {
            "diagnose": "nexus recovery network",
            "wifi": "nexus recovery wifi --allow-reconnect",
            "reboot": "NEXUS_ALLOW_REBOOT=1 nexus recovery reboot --allow-reboot",
        },
    }


def network_diagnose() -> RecoveryResult:
    steps: list[dict[str, Any]] = []
    net = hb.probe_network()
    steps.append({"step": "probe", **net})

    if shutil.which("ip"):
        steps.append({"step": "ip_route", **_run(["ip", "route"])})
        steps.append({"step": "ip_link", **_run(["ip", "-br", "link"])})
    if shutil.which("nmcli"):
        steps.append({"step": "nmcli_dev", **_run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev"])})
        steps.append({"step": "nmcli_wifi", **_run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"])})
    if shutil.which("ping"):
        steps.append({"step": "ping_cf", **_run(["ping", "-c", "2", "-W", "2", "1.1.1.1"], timeout=15)})

    ok = bool(net.get("online"))
    msg = "network looks up" if ok else "network looks down — try: nexus recovery wifi --allow-reconnect"
    return RecoveryResult(action="network", ok=ok, steps=steps, message=msg)


def wifi_recover(
    *,
    allow_reconnect: bool = False,
    connection: Optional[str] = None,
    notify: bool = True,
) -> RecoveryResult:
    """Attempt soft WiFi recovery via NetworkManager (opt-in)."""
    steps: list[dict[str, Any]] = []
    diag = network_diagnose()
    steps.extend(diag.steps)

    if diag.ok:
        return RecoveryResult(
            action="wifi",
            ok=True,
            steps=steps,
            message="already online — no reconnect needed",
        )

    if not allow_reconnect:
        return RecoveryResult(
            action="wifi",
            ok=False,
            steps=steps,
            message="offline; re-run with --allow-reconnect to try nmcli reconnect (opt-in)",
        )

    if not shutil.which("nmcli"):
        return RecoveryResult(
            action="wifi",
            ok=False,
            steps=steps,
            message="nmcli not found — install NetworkManager or reconnect WiFi manually",
        )

    # Soft cycle: networking off/on is aggressive; prefer re-activate connection
    if connection:
        r = _run(["nmcli", "connection", "up", connection], timeout=45)
        steps.append({"step": "nmcli_up_named", **r})
    else:
        # bring up first available wifi device
        dev = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "dev"], timeout=15)
        steps.append({"step": "list_dev", **dev})
        wifi_dev = None
        for line in (dev.get("stdout") or "").splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "wifi":
                wifi_dev = parts[0]
                break
        if wifi_dev:
            r = _run(["nmcli", "device", "connect", wifi_dev], timeout=60)
            steps.append({"step": "nmcli_device_connect", "device": wifi_dev, **r})
        else:
            r = _run(["nmcli", "networking", "on"], timeout=30)
            steps.append({"step": "nmcli_networking_on", **r})
            time.sleep(2)
            r2 = _run(["nmcli", "radio", "wifi", "on"], timeout=30)
            steps.append({"step": "nmcli_radio_on", **r2})

    time.sleep(3)
    net2 = hb.probe_network()
    steps.append({"step": "probe_after", **net2})
    ok = bool(net2.get("online"))

    if not ok and notify:
        _maybe_webhook(
            "NEXUS recovery: WiFi still down after reconnect attempt on "
            f"{net2.get('host')}"
        )

    # If we're back online, send a heartbeat if configured
    if ok:
        try:
            hb.beat_once()
            steps.append({"step": "heartbeat_after_recover", "ok": True})
        except Exception as e:
            steps.append({"step": "heartbeat_after_recover", "ok": False, "error": str(e)})

    return RecoveryResult(
        action="wifi",
        ok=ok,
        steps=steps,
        message="wifi recover succeeded" if ok else "wifi recover failed — still offline",
    )


def reboot_machine(*, allow_reboot: bool = False) -> RecoveryResult:
    """Last-resort reboot. Double gate: flag + env NEXUS_ALLOW_REBOOT=1."""
    steps: list[dict[str, Any]] = []
    if not allow_reboot:
        return RecoveryResult(
            action="reboot",
            ok=False,
            steps=steps,
            message="refused: pass --allow-reboot (and set NEXUS_ALLOW_REBOOT=1)",
        )
    if os.environ.get("NEXUS_ALLOW_REBOOT") != "1":
        return RecoveryResult(
            action="reboot",
            ok=False,
            steps=steps,
            message="refused: set env NEXUS_ALLOW_REBOOT=1 in addition to --allow-reboot",
        )
    if not shutil.which("systemctl") and not shutil.which("reboot"):
        return RecoveryResult(
            action="reboot",
            ok=False,
            steps=steps,
            message="no systemctl/reboot binary found",
        )

    # Log intent to disk before reboot
    log = Path(os.getcwd()).resolve() / ".nexus_state" / "recovery_reboot.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.time(), "action": "reboot", "host": os.uname().nodename}
    log.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    steps.append({"step": "logged", "path": str(log)})

    if shutil.which("systemctl"):
        cmd = ["systemctl", "reboot"]
    else:
        cmd = ["reboot"]
    # Do not actually wait — process will die
    try:
        subprocess.Popen(cmd)  # noqa: S603 — intentional, double-gated
        steps.append({"step": "issued", "cmd": cmd, "ok": True})
        return RecoveryResult(
            action="reboot",
            ok=True,
            steps=steps,
            message="reboot issued",
        )
    except Exception as e:
        steps.append({"step": "issued", "ok": False, "error": str(e)})
        return RecoveryResult(action="reboot", ok=False, steps=steps, message=str(e))


def _maybe_webhook(text: str) -> None:
    cfg = hb.load_config()
    url = cfg.notify_webhook or os.environ.get("NEXUS_HEARTBEAT_WEBHOOK") or ""
    if not url:
        return
    try:
        # Discord-compatible {content}, Slack text, or plain JSON
        body = json.dumps({"content": text, "text": text}).encode()
        import urllib.request

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "nexus-recovery"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def auto_recover(
    *,
    allow_reconnect: bool = False,
    allow_reboot: bool = False,
) -> RecoveryResult:
    """Diagnose → optional wifi → never reboot unless both gates set."""
    steps: list[dict[str, Any]] = []
    d = network_diagnose()
    steps.extend(d.steps)
    if d.ok:
        return RecoveryResult(action="auto", ok=True, steps=steps, message="healthy")

    w = wifi_recover(allow_reconnect=allow_reconnect)
    steps.extend(w.steps)
    if w.ok:
        return RecoveryResult(action="auto", ok=True, steps=steps, message="recovered via wifi")

    if allow_reboot and os.environ.get("NEXUS_ALLOW_REBOOT") == "1":
        r = reboot_machine(allow_reboot=True)
        steps.extend(r.steps)
        return RecoveryResult(action="auto", ok=r.ok, steps=steps, message=r.message)

    return RecoveryResult(
        action="auto",
        ok=False,
        steps=steps,
        message="still down; cloud dead-man should notify if heartbeats stop",
    )
