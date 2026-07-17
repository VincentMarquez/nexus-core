#!/usr/bin/env python3
"""Generate docs/assets/last-real-badge.svg + docs/hype/LAST_REAL.md from the latest summary.

Usage (repo root)::

    python3 scripts/last_real_badge.py
    # optional wall-clock override:
    python3 scripts/last_real_badge.py --runtime "~2h54m"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_summary(text: str) -> dict[str, str]:
    out = {
        "health": "n/a",
        "ideas": "n/a",
        "tests": "n/a",
        "pushed": "n/a",
        "ts": "n/a",
    }
    m = re.search(r"overall_health:\s*([0-9.]+)%", text, re.I)
    if m:
        out["health"] = f"{m.group(1)}%"
    m = re.search(r"Implement success\s*\|\s*\*?\*?([0-9]+/[0-9]+)", text)
    if m:
        out["ideas"] = m.group(1)
    m = re.search(r"Final tests green\s*\|\s*\*?\*?(True|False)", text, re.I)
    if m:
        out["tests"] = "green" if m.group(1).lower() == "true" else "red"
    m = re.search(r"Publish pushed\s*\|\s*\*?\*?(True|False)", text, re.I)
    if m:
        out["pushed"] = "yes" if m.group(1).lower() == "true" else "gated"
    m = re.search(r"ts:\s*([0-9T:\-Z]+)", text)
    if m:
        out["ts"] = m.group(1)[:10]
    return out


def write_badge(path: Path, ideas: str, tests: str, runtime: str, pushed: str) -> None:
    w = 640
    left = 88
    msg = f"{ideas} · {tests} · {runtime} · pub {pushed}"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="28" role="img" aria-label="last REAL {msg}">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <rect width="{left}" height="28" fill="#555"/>
  <rect x="{left}" width="{w - left}" height="28" fill="#0e7a4a"/>
  <rect width="{w}" height="28" fill="url(#s)"/>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="12">
    <text x="{left // 2}" y="18">last REAL</text>
    <text x="{left + (w - left) / 2}" y="18">{msg}</text>
  </g>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--runtime",
        default="~2h54m",
        help="wall-clock string for the badge (default from last known REAL)",
    )
    ap.add_argument(
        "--summary",
        default="",
        help="path to LATEST_IMPLEMENT_SUMMARY.md (default docs/...)",
    )
    args = ap.parse_args(argv)
    root = _root()
    summary_path = Path(args.summary) if args.summary else root / "docs" / "LATEST_IMPLEMENT_SUMMARY.md"
    if not summary_path.is_file():
        # fallback state file
        alt = root / ".nexus_state" / "LAST_IMPLEMENT_SUMMARY.md"
        if alt.is_file():
            summary_path = alt
        else:
            print(f"error: summary not found: {summary_path}", file=sys.stderr)
            return 1
    text = summary_path.read_text(encoding="utf-8", errors="replace")
    meta = parse_summary(text)
    badge = root / "docs" / "assets" / "last-real-badge.svg"
    badge.parent.mkdir(parents=True, exist_ok=True)
    write_badge(badge, meta["ideas"], meta["tests"], args.runtime, meta["pushed"])
    hype = root / "docs" / "hype"
    hype.mkdir(parents=True, exist_ok=True)
    (hype / "LAST_REAL.md").write_text(
        f"""# Last REAL (generated)

![Last REAL](../assets/last-real-badge.svg)

Regenerate::

```bash
python3 scripts/last_real_badge.py --runtime "{args.runtime}"
```

| Field | Value |
|-------|-------|
| Timestamp | `{meta["ts"]}` |
| Ideas landed | **{meta["ideas"]}** |
| Final tests | **{meta["tests"]}** |
| Wall clock | **{args.runtime}** |
| Publish | **{meta["pushed"]}** |
| Health | **{meta["health"]}** |

Full write-up: [`docs/LATEST_IMPLEMENT_SUMMARY.md`](../LATEST_IMPLEMENT_SUMMARY.md)
""",
        encoding="utf-8",
    )
    print(f"wrote {badge}")
    print(f"wrote {hype / 'LAST_REAL.md'}")
    print(
        f"last REAL · {meta['ideas']} · tests {meta['tests']} · "
        f"{args.runtime} · publish {meta['pushed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
