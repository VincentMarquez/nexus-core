"""HTTP / file-bridge client for the NEXUS lab event bus.

No API keys here — bridges own auth. Product engine steps call ``message()``
and **must** get a synchronous text reply from a real seat (Claude/GPT/Grok/local).

History:
  An old client POSTed ``{agent, prompt}`` to ``/api/message``, which expects
  ``{text, target}`` and returns only a correlationId (async SSE). That made
  multi-LLM REAL look broken — only Grok hard-worker later in the cycle.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .circuits import CircuitBreaker

# Lab bridge temp files (same as security-lab/bridge/server.js BRIDGE_FILES)
_BRIDGE_FILES: dict[str, dict[str, str]] = {
    "gpt": {
        "prompt": "/tmp/cerf-bridge-prompt.json",
        "response": "/tmp/cerf-bridge-response.json",
        "status": "/tmp/cerf-bridge-status.json",
    },
    "claude": {
        "prompt": "/tmp/claude-bridge-prompt.json",
        "response": "/tmp/claude-bridge-response.json",
        "status": "/tmp/claude-bridge-status.json",
    },
    "gpt2": {
        "prompt": "/tmp/gpt2-bridge-prompt.json",
        "response": "/tmp/gpt2-bridge-response.json",
        "status": "/tmp/gpt2-bridge-status.json",
    },
    "gemini": {
        "prompt": "/tmp/gemini-bridge-prompt.json",
        "response": "/tmp/gemini-bridge-response.json",
        "status": "/tmp/gemini-bridge-status.json",
    },
    "antigravity": {
        "prompt": "/tmp/antigravity-bridge-prompt.json",
        "response": "/tmp/antigravity-bridge-response.json",
        "status": "/tmp/antigravity-bridge-status.json",
    },
}


@dataclass
class BusClient:
    """Thin client for the lab bus + CLI file bridges."""

    base_url: str = "http://127.0.0.1:3099"
    timeout_s: float = 360.0  # match long bridge turns
    circuits: CircuitBreaker = field(default_factory=CircuitBreaker)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:26b"

    def _url(self, path: str) -> str:
        return self.base_url.rstrip("/") + path

    def _get(self, path: str, *, timeout: Optional[float] = None) -> Any:
        req = urllib.request.Request(self._url(path), method="GET")
        with urllib.request.urlopen(req, timeout=timeout or 10) as r:
            return json.loads(r.read().decode())

    def _post(self, path: str, body: dict[str, Any], *, timeout: Optional[float] = None) -> Any:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self._url(path),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as r:
            return json.loads(r.read().decode())

    def health(self) -> dict[str, Any]:
        return self._get("/health", timeout=5)

    def status(self) -> dict[str, Any]:
        return self._get("/api/status", timeout=5)

    def is_reachable(self) -> bool:
        # Prefer /api/status (always present). /health may 404 on older buses.
        try:
            st = self.status()
            if isinstance(st, dict) and (
                "agents" in st or "uptime" in st or st.get("ok") is True
            ):
                return True
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, TypeError):
            pass
        try:
            h = self.health()
            return bool(isinstance(h, dict) and h.get("ok"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return False

    def agent_online(self, agent: str) -> bool:
        """True if lab bus reports the seat online.

        Supports both shapes:
          agents: {"claude": true, "gpt": true, ...}
          agents: [{"agent":"claude","status":"online"}, ...]
        """
        # File-bridge agents: status file fresher than 3 min counts as online
        files = _BRIDGE_FILES.get(agent)
        if files:
            try:
                p = Path(files["status"])
                if p.is_file():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    age = time.time() - float(data.get("timestamp") or 0)
                    st = str(data.get("status") or "")
                    if st in ("online", "processing") and age < 180:
                        return True
            except Exception:
                pass

        if agent in ("local", "kairos"):
            try:
                req = urllib.request.Request(
                    self.ollama_url.rstrip("/") + "/api/tags", method="GET"
                )
                with urllib.request.urlopen(req, timeout=3) as r:
                    return r.status == 200
            except Exception:
                return False

        if agent == "grok":
            import shutil

            return bool(shutil.which("grok"))

        try:
            st = self.status()
            agents = st.get("agents")
            if isinstance(agents, dict):
                v = agents.get(agent)
                if isinstance(v, bool):
                    return v
                if isinstance(v, dict):
                    return str(v.get("status") or "").lower() in {
                        "online",
                        "busy",
                        "processing",
                        "true",
                        "1",
                    }
                return bool(v)
            if isinstance(agents, list):
                for row in agents:
                    if not isinstance(row, dict):
                        continue
                    name = row.get("agent") or row.get("name") or row.get("id")
                    if name == agent:
                        return str(row.get("status") or "").lower() in {
                            "online",
                            "busy",
                            "processing",
                        }
            return False
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, TypeError):
            return False

    def message(
        self,
        agent: str,
        prompt: str,
        *,
        timeout_ms: Optional[int] = None,
    ) -> str:
        """Invoke a lab seat and wait for text (sync).

        Routes:
          claude/gpt/gpt2/gemini/antigravity → file bridges under /tmp
          local/kairos → Ollama
          grok → Grok CLI
        """
        if not self.circuits.can_execute(agent):
            raise RuntimeError(f"circuit OPEN for agent {agent}")
        try:
            from . import usage as usage_mod

            usage_mod.check_budget(
                usage_mod.estimate_tokens(prompt) + 512, raise_on_exceed=True
            )
        except Exception as _budget_err:
            if _budget_err.__class__.__name__ == "BudgetExceeded":
                raise

        timeout_s = (timeout_ms or int(self.timeout_s * 1000)) / 1000.0
        try:
            if agent in _BRIDGE_FILES:
                text = self._message_file_bridge(agent, prompt, timeout_s=timeout_s)
            elif agent in ("local", "kairos"):
                text = self._message_ollama(prompt, timeout_s=min(timeout_s, 180.0))
            elif agent == "grok":
                text = self._message_grok_cli(prompt, timeout_s=timeout_s)
            else:
                # last resort: file bridge if name maps, else ollama
                text = self._message_ollama(prompt, timeout_s=min(timeout_s, 120.0))
            self.circuits.record_success(agent)
            return text
        except Exception as e:
            self.circuits.record_failure(agent, str(e))
            raise

    def _message_file_bridge(self, agent: str, prompt: str, *, timeout_s: float) -> str:
        files = _BRIDGE_FILES[agent]
        prompt_path = Path(files["prompt"])
        response_path = Path(files["response"])
        msg_id = uuid.uuid4().hex[:8]
        payload = {
            "id": msg_id,
            "prompt": prompt,
            "timestamp": int(time.time()),
            "auto_approve": True,
        }
        # clear stale response with same id
        try:
            if response_path.is_file():
                response_path.unlink()
        except OSError:
            pass
        prompt_path.write_text(json.dumps(payload), encoding="utf-8")

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(0.4)
            if not response_path.is_file():
                continue
            try:
                resp = json.loads(response_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if resp.get("id") != msg_id:
                continue
            status = resp.get("status")
            if status == "complete":
                try:
                    response_path.unlink()
                except OSError:
                    pass
                return str(resp.get("response") or resp.get("text") or "")
            if status == "error":
                try:
                    response_path.unlink()
                except OSError:
                    pass
                raise RuntimeError(str(resp.get("error") or "bridge error"))
        raise RuntimeError(f"bridge timeout after {int(timeout_s)}s ({agent})")

    def _message_ollama(self, prompt: str, *, timeout_s: float) -> str:
        body = {
            "model": self.ollama_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.4, "num_predict": 1200},
        }
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self.ollama_url.rstrip("/") + "/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            out = json.loads(r.read().decode())
        msg = out.get("message") or {}
        return str(msg.get("content") or out.get("response") or "")

    def _message_grok_cli(self, prompt: str, *, timeout_s: float) -> str:
        import os
        import subprocess

        # Match lab Grok path: CLI OIDC, no XAI key mix
        env = {k: v for k, v in os.environ.items() if k != "XAI_API_KEY"}
        cmd = [
            "grok",
            "-p",
            prompt,
            "-m",
            "grok-4.5",
            "--output-format",
            "plain",
            "--disable-web-search",
            "--always-approve",
            "--max-turns",
            "8",
        ]
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        if r.returncode != 0 and not (r.stdout or "").strip():
            raise RuntimeError((r.stderr or r.stdout or "grok failed")[:500])
        return (r.stdout or "").strip()

    def list_tasks(self) -> list[dict[str, Any]]:
        try:
            out = self._get("/api/tasks", timeout=5)
            return list(out.get("tasks") or [])
        except Exception:
            return []
