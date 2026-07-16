#!/usr/bin/env python3
"""CLI-bridge helper: read prompt from stdin, run headless Grok, print reply.

Used as:  python3 stdin_to_grok.py   (prompt on stdin from cli-bridge.sh)
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    prompt = sys.stdin.read()
    if not prompt.strip():
        print("[grok-bridge] empty prompt", file=sys.stderr)
        return 2
    model = os.environ.get("NEXUS_GROK_MODEL") or "grok-4.5"
    max_turns = os.environ.get("NEXUS_GROK_BRIDGE_TURNS") or "12"
    # max / high / medium / low — pin max for multi-vendor hard work
    effort = (os.environ.get("NEXUS_GROK_REASONING_EFFORT") or "max").strip()
    cmd = [
        "grok",
        "-p",
        prompt,
        "-m",
        model,
        "--max-turns",
        str(max_turns),
        "--output-format",
        "plain",
        "--always-approve",
        "--no-plan",
    ]
    if effort:
        cmd.extend(["--reasoning-effort", effort])
    # Web search on for research-grade reviews unless explicitly disabled
    if os.environ.get("NEXUS_GROK_DISABLE_WEB", "").strip() in ("1", "true", "yes"):
        cmd.append("--disable-web-search")
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("NEXUS_CLI_TIMEOUT_S") or 300),
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        print("[grok-bridge] timeout")
        return 1
    except FileNotFoundError:
        print("[grok-bridge] grok CLI not on PATH")
        return 127
    out = (p.stdout or "").strip() or (p.stderr or "").strip()
    if not out:
        out = f"[grok-bridge] empty (rc={p.returncode})"
    print(out)
    return 0 if p.returncode == 0 and p.stdout else min(p.returncode or 1, 1)


if __name__ == "__main__":
    raise SystemExit(main())
