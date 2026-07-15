#!/usr/bin/env python3
"""Tool-augmented Ollama turn for the NEXUS bus bridge.

Gives the *local* LLM the same Workspace MCP tools (project jail) that Grok CLI /
Cursor get via MCP — so agents on the bus are not second-class.

Protocol (model output):
  TOOL_CALL {"name": "...", "arguments": {...}}
  or plain final text when done.

Env:
  NEXUS_PROJECT_ROOT  project jail (required for tools)
  NEXUS_OLLAMA_TOOLS=0  disable tool loop (generate only)
  NEXUS_TOOL_ROUNDS    max tool rounds (default 4)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

# Allow `python -m nexus...` imports when PYTHONPATH includes src/
_SRC = Path(__file__).resolve().parents[2] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


TOOL_CALL_RE = re.compile(
    r"TOOL_CALL\s*(\{.*?\})\s*(?:$|\n)",
    re.S | re.I,
)


def _ollama_generate(host: str, model: str, prompt: str, *, num_predict: int = 768) -> str:
    url = host.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": num_predict},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        body = json.loads(r.read().decode())
    return (body.get("response") or "").strip()


def _tool_catalog() -> str:
    try:
        from nexus.mcp_server import TOOLS

        lines = []
        for t in TOOLS:
            lines.append(f"- {t['name']}: {t.get('description', '')[:160]}")
        return "\n".join(lines)
    except Exception as e:
        return f"(tools unavailable: {e})"


def _run_tool(name: str, arguments: dict[str, Any]) -> str:
    try:
        from nexus.mcp_server import call_tool

        res = call_tool(name, arguments)
        parts = res.get("content") or []
        texts = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                texts.append(str(p.get("text") or ""))
            else:
                texts.append(str(p))
        out = "\n".join(texts) if texts else json.dumps(res)[:4000]
        if res.get("isError"):
            return f"ERROR: {out}"
        return out[:12000]
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def _system_preamble(agent: str) -> str:
    return (
        f"You are NEXUS bus agent `{agent}` (local LLM). "
        "You share the same project tools as Grok CLI / Cursor via Workspace MCP.\n"
        "When you need a tool, output exactly one line:\n"
        'TOOL_CALL {"name": "tool_name", "arguments": {...}}\n'
        "Otherwise answer with final plain text only (no TOOL_CALL).\n"
        "Prefer evidence (run_project_checks, read files) over speculation.\n"
        f"Available tools:\n{_tool_catalog()}\n"
    )


def handle_turn(
    user_prompt: str,
    *,
    host: str,
    model: str,
    agent: str,
) -> str:
    tools_on = os.environ.get("NEXUS_OLLAMA_TOOLS", "1").strip() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if not tools_on:
        return _ollama_generate(host, model, user_prompt) or f"[ollama:{agent}] empty"

    max_rounds = int(os.environ.get("NEXUS_TOOL_ROUNDS") or 4)
    # Ensure project root for mcp jail
    if not os.environ.get("NEXUS_PROJECT_ROOT"):
        # bridge lives in repo/bridge/bridges → parents[2] = repo root
        os.environ["NEXUS_PROJECT_ROOT"] = str(Path(__file__).resolve().parents[2])

    history = _system_preamble(agent) + "\n\nUser task:\n" + user_prompt
    last_text = ""
    for rnd in range(max_rounds):
        last_text = _ollama_generate(host, model, history, num_predict=768)
        if not last_text:
            return f"[ollama:{agent}] empty response"
        m = TOOL_CALL_RE.search(last_text)
        if not m:
            # strip accidental fences
            return last_text
        try:
            call = json.loads(m.group(1))
        except json.JSONDecodeError:
            return last_text
        name = str(call.get("name") or "")
        arguments = call.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        result = _run_tool(name, arguments)
        history += (
            f"\n\nAssistant:\n{last_text}\n\n"
            f"Tool result ({name}):\n{result}\n\n"
            "Continue. Emit another TOOL_CALL or final answer.\n"
        )
    return last_text or f"[ollama:{agent}] tool rounds exhausted"


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 5:
        print(
            "usage: ollama_tools.py PROMPT_JSON RESPONSE_JSON HOST MODEL AGENT",
            file=sys.stderr,
        )
        return 2
    prompt_path, response_path, host, model, agent = argv[:5]
    data = json.load(open(prompt_path, encoding="utf-8"))
    req_id = data.get("id", "")
    user_in = data.get("prompt", "")
    try:
        text = handle_turn(user_in, host=host, model=model, agent=agent)
    except Exception as e:
        text = f"[ollama:{agent}] error: {e}"
    json.dump(
        {"id": req_id, "text": text, "ts": time.time(), "tools": True},
        open(response_path, "w", encoding="utf-8"),
    )
    print(f"[ollama-tools:{agent}] answered id={req_id} chars={len(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
