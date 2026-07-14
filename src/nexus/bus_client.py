"""HTTP client for the NEXUS-style event bus (bridge/server.js).

No API keys here — the bus talks to CLI/local bridges that own auth.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

from .circuits import CircuitBreaker


@dataclass
class BusClient:
    """Thin client for the public bridge stub (or any compatible bus)."""

    base_url: str = "http://127.0.0.1:3099"
    timeout_s: float = 300.0
    circuits: CircuitBreaker = field(default_factory=CircuitBreaker)

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
        try:
            h = self.health()
            return bool(h.get("ok"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return False

    def agent_online(self, agent: str) -> bool:
        try:
            st = self.status()
            for row in st.get("agents") or []:
                if row.get("agent") == agent:
                    return row.get("status") in {"online", "busy"}
            return False
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return False

    def message(
        self,
        agent: str,
        prompt: str,
        *,
        timeout_ms: Optional[int] = None,
    ) -> str:
        """POST /api/message → response text (circuit-aware)."""
        if not self.circuits.can_execute(agent):
            raise RuntimeError(f"circuit OPEN for agent {agent}")
        body: dict[str, Any] = {"agent": agent, "prompt": prompt}
        if timeout_ms is not None:
            body["timeout_ms"] = timeout_ms
        try:
            out = self._post(
                "/api/message",
                body,
                timeout=(timeout_ms or int(self.timeout_s * 1000)) / 1000.0 + 5,
            )
            if isinstance(out, dict) and "text" in out:
                self.circuits.record_success(agent)
                return str(out["text"])
            if isinstance(out, dict) and "error" in out:
                raise RuntimeError(out["error"])
            raise RuntimeError(f"unexpected bus response: {out!r}")
        except Exception as e:
            self.circuits.record_failure(agent, str(e))
            raise

    def list_tasks(self) -> list[dict[str, Any]]:
        try:
            out = self._get("/api/tasks", timeout=5)
            return list(out.get("tasks") or [])
        except Exception:
            return []
