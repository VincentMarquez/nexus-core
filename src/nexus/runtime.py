"""Process supervision for bus, bridges, ollama — local only."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class RuntimeManager:
    def __init__(self, state_dir: Optional[Path] = None):
        self.root = repo_root()
        self.state_dir = Path(state_dir or self.root / ".nexus_state")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.pid_dir = self.state_dir / "pids"
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = self.state_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.bridge_dir = Path(os.environ.get("NEXUS_BRIDGE_DIR") or "/tmp/nexus-core-bridges")
        self.bridge_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.state_dir / "runtime.json"
        env_port = os.environ.get("NEXUS_BUS_PORT")
        if env_port:
            self.bus_port = int(env_port)
        elif self.meta_path.exists():
            try:
                self.bus_port = int(json.loads(self.meta_path.read_text()).get("bus_port") or 0)
            except Exception:
                self.bus_port = 0
        else:
            self.bus_port = 0  # auto

    def _pid_file(self, name: str) -> Path:
        return self.pid_dir / f"{name}.pid"

    def _write_pid(self, name: str, pid: int) -> None:
        self._pid_file(name).write_text(str(pid), encoding="utf-8")

    def _read_pid(self, name: str) -> Optional[int]:
        p = self._pid_file(name)
        if not p.exists():
            return None
        try:
            return int(p.read_text().strip())
        except ValueError:
            return None

    def is_running(self, name: str) -> bool:
        pid = self._read_pid(name)
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def stop(self, name: str) -> bool:
        pid = self._read_pid(name)
        if not pid:
            return False
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        # wait briefly
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except OSError:
                break
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            self._pid_file(name).unlink()
        except OSError:
            pass
        return True

    def stop_all(self) -> list[str]:
        stopped = []
        for p in self.pid_dir.glob("*.pid"):
            name = p.stem
            if self.stop(name):
                stopped.append(name)
        return stopped

    def status(self) -> dict[str, Any]:
        procs = {}
        for p in self.pid_dir.glob("*.pid"):
            name = p.stem
            procs[name] = {"pid": self._read_pid(name), "running": self.is_running(name)}
        return {
            "bus_port": self.bus_port,
            "bridge_dir": str(self.bridge_dir),
            "state_dir": str(self.state_dir),
            "dashboard": f"http://127.0.0.1:{self.bus_port}/dashboard",
            "processes": procs,
            "bus_up": self.bus_healthy(),
        }

    def bus_healthy(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.bus_port}/health", timeout=2
            ) as r:
                return r.status == 200
        except Exception:
            return False

    def start_process(
        self,
        name: str,
        cmd: list[str],
        *,
        cwd: Optional[Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> int:
        if self.is_running(name):
            return self._read_pid(name) or 0
        log = open(self.log_dir / f"{name}.log", "ab")
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd or self.root),
            env=full_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._write_pid(name, proc.pid)
        return proc.pid

    def ensure_ollama_serve(self) -> bool:
        # API already up?
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2):
                return True
        except Exception:
            pass
        if not shutil_which("ollama"):
            return False
        self.start_process("ollama-serve", ["ollama", "serve"])
        for _ in range(30):
            try:
                with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1):
                    return True
            except Exception:
                time.sleep(0.3)
        return False

    def pull_model(self, model: str) -> bool:
        if not shutil_which("ollama"):
            return False
        # run foreground pull so user sees progress in log; don't hang forever for huge models
        log_path = self.log_dir / "ollama-pull.log"
        with open(log_path, "ab") as log:
            p = subprocess.run(
                ["ollama", "pull", model],
                cwd=str(self.root),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=3600,
            )
        return p.returncode == 0

    def pick_port(self, preferred: int = 3099) -> int:
        """Prefer 3099; if taken by something else, bind an ephemeral free port."""
        import socket

        if self.bus_port and self.bus_port > 0:
            return self.bus_port

        def free(port: int) -> bool:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False
            finally:
                s.close()

        # If 3099 free, use it. If something answers our /health shape, reuse.
        if free(preferred):
            return preferred
        if self._health_on(preferred):
            return preferred
        for p in range(3109, 3200):
            if free(p):
                return p
        # last resort ephemeral
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def _health_on(self, port: int) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                data = r.read().decode()
                return '"ok"' in data or '"ok": true' in data.replace(" ", "")
        except Exception:
            return False

    def _save_meta(self) -> None:
        self.meta_path.write_text(
            json.dumps(
                {
                    "bus_port": self.bus_port,
                    "bridge_dir": str(self.bridge_dir),
                    "state_dir": str(self.state_dir),
                    "dashboard": f"http://127.0.0.1:{self.bus_port}/dashboard",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def start_bus(self, agents: list[str]) -> int:
        self.bus_port = self.pick_port(3099)
        env = {
            "NEXUS_BUS_PORT": str(self.bus_port),
            "NEXUS_BRIDGE_DIR": str(self.bridge_dir),
            "NEXUS_STATE_DIR": str(self.state_dir),
            "NEXUS_AGENTS": ",".join(agents),
            # Product default: 6 minutes per real-CLI turn (was 2m → mass 504s)
            "NEXUS_MSG_TIMEOUT_MS": os.environ.get("NEXUS_MSG_TIMEOUT_MS") or "360000",
        }
        pid = self.start_process(
            "bus",
            ["node", "server.js"],
            cwd=self.root / "bridge",
            env=env,
        )
        self._save_meta()
        return pid

    def start_ollama_bridge(self, agent: str, model: str) -> int:
        script = self.root / "bridge" / "bridges" / "ollama-http.sh"
        env = {
            "NEXUS_BRIDGE_DIR": str(self.bridge_dir),
            "OLLAMA_HOST": "http://127.0.0.1:11434",
            "OLLAMA_MODEL": model,
        }
        return self.start_process(
            f"bridge-{agent}",
            ["bash", str(script), agent, model],
            cwd=self.root / "bridge",
            env=env,
        )

    def start_mock_bridge(self, agent: str) -> int:
        script = self.root / "bridge" / "bridges" / "mock-bridge.sh"
        env = {"NEXUS_BRIDGE_DIR": str(self.bridge_dir)}
        return self.start_process(
            f"bridge-{agent}",
            ["bash", str(script), agent],
            cwd=self.root / "bridge",
            env=env,
        )

    def start_cli_bridge(self, agent: str, cli_cmd: list[str]) -> int:
        script = self.root / "bridge" / "bridges" / "cli-bridge.sh"
        env = {
            "NEXUS_BRIDGE_DIR": str(self.bridge_dir),
            # Real CLIs need several minutes; short timeouts → 504 → failed tasks
            "NEXUS_CLI_TIMEOUT_S": os.environ.get("NEXUS_CLI_TIMEOUT_S") or "600",
            # auto: Codex gets prompt as last arg; others use stdin
            "NEXUS_CLI_PROMPT_MODE": os.environ.get("NEXUS_CLI_PROMPT_MODE") or "auto",
        }
        # Forward max-model pins into the bridge process environment
        for key in (
            "NEXUS_CLAUDE_MODEL",
            "NEXUS_CLAUDE_EFFORT",
            "NEXUS_CODEX_MODEL",
            "NEXUS_CODEX_REASONING",
            "NEXUS_CODEX_SERVICE_TIER",
            "NEXUS_GROK_MODEL",
            "NEXUS_GROK_REASONING_EFFORT",
            "NEXUS_GROK_BRIDGE_TURNS",
            "NEXUS_GEMINI_MODEL",
            "NEXUS_MSG_TIMEOUT_MS",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "XAI_API_KEY",
            "GEMINI_API_KEY",
            "HOME",
            "PATH",
        ):
            if key in os.environ:
                env[key] = os.environ[key]
        return self.start_process(
            f"bridge-{agent}",
            ["bash", str(script), agent, *cli_cmd],
            cwd=self.root / "bridge",
            env=env,
        )

    def wait_bus(self, timeout_s: float = 15.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.bus_healthy():
                return True
            time.sleep(0.2)
        return False

    def open_dashboard(self) -> None:
        url = f"http://127.0.0.1:{self.bus_port}/dashboard"
        # best-effort browser open
        for cmd in (
            ["xdg-open", url],
            ["gio", "open", url],
            ["open", url],  # macOS
        ):
            try:
                if shutil_which(cmd[0]):
                    subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
            except Exception:
                continue
        # write URL for user
        (self.state_dir / "dashboard.url").write_text(url + "\n", encoding="utf-8")


def shutil_which(cmd: str) -> Optional[str]:
    import shutil

    return shutil.which(cmd)
