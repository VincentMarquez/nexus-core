"""Print crontab / launchd snippets so NEXUS + ChatGPT/Claude can run on a schedule.

Does not install system services without the user pasting lines (safe default).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _python(root: Path) -> str:
    v = root / ".venv" / "bin" / "python"
    if v.is_file():
        return str(v)
    return os.environ.get("NEXUS_PYTHON") or "python3"


def install_bundle(
    root: Optional[Path] = None,
    *,
    mine_query: str = "multi agent durable",
    heartbeat: bool = True,
    mine: bool = True,
    mcp_http: bool = False,
) -> str:
    root = Path(root or os.getcwd()).resolve()
    py = _python(root)
    env = f"cd {root} && NEXUS_PROJECT_ROOT={root}"
    lines = [
        "# NEXUS scheduled jobs — paste into: crontab -e",
        "# ChatGPT / Claude use the same machine via MCP (see docs/SCHEDULE_AGENTS.md)",
        "",
    ]
    if heartbeat:
        lines.append(
            f"*/5 * * * * {env} {py} -m nexus.cli heartbeat once "
            f">>{root}/.nexus_state/heartbeat.log 2>&1"
        )
    if mine:
        # twice a day: discover/grade/use; improve plan without --apply by default
        lines.append(
            f"0 9,21 * * * {env} {py} -m nexus.cli github mine run "
            f"-q '{mine_query}' -n 6 --heuristic-only --min-score 12 "
            f">>{root}/.nexus_state/mine.log 2>&1"
        )
        lines.append(
            f"30 9,21 * * * {env} {py} -m nexus.cli github mine improve-ours "
            f"--min-score 12 "
            f">>{root}/.nexus_state/mine_improve.log 2>&1"
        )
    if mcp_http:
        lines.append(
            f"@reboot {env} {py} -m nexus.cli mcp --http --host 127.0.0.1 --port 8765 "
            f">>{root}/.nexus_state/mcp_http.log 2>&1"
        )
        lines.append(
            "# Expose MCP to ChatGPT with a tunnel, e.g.:\n"
            "#   cloudflared tunnel --url http://127.0.0.1:8765\n"
            "# Then paste https://….trycloudflare.com into ChatGPT Connectors."
        )
    lines += [
        "",
        "# Optional always-on community + mine watch (foreground service / tmux):",
        f"# {env} {py} -m nexus.cli github watch --autonomous --workdir {root} \\",
        f"#   --scout '{mine_query}' --scout-every 43200",
        "",
        "# Apply improvements only when you mean it (not on cron by default):",
        f"# {env} {py} -m nexus.cli github mine improve-ours --apply --repo YOU/REPO",
        "",
    ]
    return "\n".join(lines)
