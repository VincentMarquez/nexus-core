#!/usr/bin/env python3
"""Call the stub event bus (no API keys). Start bridge/server.js + a mock bridge first."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--base",
        default=None,
        help="bus base URL (default: http://127.0.0.1:$NEXUS_BUS_PORT or :3099)",
    )
    ap.add_argument("--agent", default="claude")
    ap.add_argument("--prompt", default="Hello from nexus-core")
    args = ap.parse_args()
    if not args.base:
        import os

        port = os.environ.get("NEXUS_BUS_PORT", "3099")
        # prefer last_start.json if present
        try:
            from pathlib import Path
            import json as _json

            snap = Path(".nexus_state/last_start.json")
            if snap.exists():
                port = str(_json.loads(snap.read_text()).get("runtime", {}).get("bus_port") or port)
        except Exception:
            pass
        args.base = f"http://127.0.0.1:{port}"

    for path in ("/health", "/api/status"):
        try:
            with urllib.request.urlopen(args.base + path, timeout=5) as r:
                print(path, r.status, r.read().decode()[:300])
        except urllib.error.URLError as e:
            print(f"Bus not reachable at {args.base} ({e})")
            print("Start:  cd bridge && npm start")
            print("Then:   ./bridges/mock-bridge.sh claude")
            return 1

    req = urllib.request.Request(
        args.base + "/api/message",
        data=json.dumps({"agent": args.agent, "prompt": args.prompt}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        print(json.dumps(json.loads(r.read()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
