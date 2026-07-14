#!/usr/bin/env python3
"""Call the stub event bus (no API keys). Start bridge/server.js + a mock bridge first."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3099")
    ap.add_argument("--agent", default="claude")
    ap.add_argument("--prompt", default="Hello from nexus-core")
    args = ap.parse_args()

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
