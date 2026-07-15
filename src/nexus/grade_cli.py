"""``nexus-eval`` entrypoint — AssetOpsBench-shaped grade ledger CLI.

Thin wrapper around ``nexus grade …`` for the First apply slice::

  nexus-eval list
  nexus-eval top --n 10
  nexus-eval weak --max-score 14
  nexus-eval export --format md
  nexus-eval ingest [--fixture PATH]
"""

from __future__ import annotations

import sys
from typing import Optional


def main(argv: Optional[list[str]] = None) -> int:
    """Dispatch to ``nexus grade`` with the same argv shape as the plan."""
    from .cli import main as nexus_main

    raw = list(sys.argv[1:] if argv is None else argv)
    # Default subcommand: list
    if not raw or raw[0] in ("-h", "--help"):
        if raw and raw[0] in ("-h", "--help"):
            return nexus_main(["grade", "--help"])
        return nexus_main(["grade", "list", "--help"])
    # Already prefixed
    if raw[0] == "grade":
        return nexus_main(raw)
    return nexus_main(["grade", *raw])


if __name__ == "__main__":
    raise SystemExit(main())
