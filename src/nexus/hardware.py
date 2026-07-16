"""Detect local hardware and available AI runtimes (no cloud keys)."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, asdict, field
from typing import Any, Optional


def _run(cmd: list[str], timeout: float = 8.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def _mem_gb() -> dict[str, float]:
    out = {"total": 0.0, "available": 0.0}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            kv = {}
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    kv[k.strip()] = v.strip()
        def kb(name: str) -> float:
            raw = kv.get(name, "0").split()[0]
            return float(raw) / (1024 * 1024)
        out["total"] = kb("MemTotal")
        out["available"] = kb("MemAvailable") if "MemAvailable" in kv else kb("MemFree")
    except Exception:
        pass
    return out


def _gpu_info() -> list[dict[str, Any]]:
    gpus: list[dict[str, Any]] = []
    if shutil.which("nvidia-smi"):
        rc, text = _run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ]
        )
        if rc == 0:
            for line in text.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    def num(x: str) -> float:
                        try:
                            return float(x.replace("[N/A]", "0") or 0)
                        except ValueError:
                            return 0.0

                    gpus.append(
                        {
                            "name": parts[0],
                            "vram_total_mb": num(parts[1]),
                            "vram_free_mb": num(parts[2]),
                            "backend": "cuda",
                        }
                    )
    # unified-memory style (no discrete VRAM report)
    if not gpus and platform.machine().startswith(("aarch64", "arm64")):
        mem = _mem_gb()
        gpus.append(
            {
                "name": "unified-memory (possible iGPU/SoC)",
                "vram_total_mb": mem["total"] * 1024,
                "vram_free_mb": mem["available"] * 1024,
                "backend": "unified",
            }
        )
    return gpus


def _ollama_models(host: str = "http://127.0.0.1:11434") -> list[str]:
    import urllib.request

    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode())
        return [m.get("name", "") for m in data.get("models") or [] if m.get("name")]
    except Exception:
        # CLI fallback
        if not shutil.which("ollama"):
            return []
        rc, text = _run(["ollama", "list"])
        if rc != 0:
            return []
        names = []
        for i, line in enumerate(text.splitlines()):
            if i == 0 and line.lower().startswith("name"):
                continue
            parts = line.split()
            if parts:
                names.append(parts[0])
        return names


def _cli_tools() -> dict[str, bool]:
    return {
        "node": bool(shutil.which("node")),
        "ollama": bool(shutil.which("ollama")),
        "claude": bool(shutil.which("claude")),
        "codex": bool(shutil.which("codex")),
        "gemini": bool(shutil.which("gemini")),
        "grok": bool(shutil.which("grok")),
    }


@dataclass
class HardwareProfile:
    cpu_count: int
    arch: str
    system: str
    mem_total_gb: float
    mem_available_gb: float
    gpus: list[dict[str, Any]] = field(default_factory=list)
    tools: dict[str, bool] = field(default_factory=dict)
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_models: list[str] = field(default_factory=list)
    recommended_model: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def recommend_ollama_model(models: list[str], mem_available_gb: float) -> Optional[str]:
    """Pick a safe default model for this box (prefer smaller on tight RAM)."""
    if not models:
        if mem_available_gb >= 24:
            return "gemma2:9b"
        return "gemma2:2b"

    preferred_order = [
        "gemma4:e4b",
        "gemma:7b",
        "gemma2:9b",
        "gemma2:2b",
        "llama3.2:3b",
        "llama3.2",
        "phi3:mini",
        "qwen2.5:3b",
        "qwen2.5:7b",
    ]
    # heavy tags — only if lots of free RAM
    heavy = ("26b", "32b", "70b", "72b", "405b", "27b", "34b")
    allow_heavy = mem_available_gb >= 48

    def score(name: str) -> tuple:
        n = name.lower()
        if "embed" in n:
            return (500, n)
        if any(h in n for h in heavy) and not allow_heavy:
            return (400, n)
        if any(h in n for h in heavy):
            return (80, n)  # usable but not default
        for i, pref in enumerate(preferred_order):
            if n == pref or n == pref.split(":")[0]:
                return (i, n)
            # tag family match e.g. gemma4:e4b vs preferred gemma4:e4b
            if pref in n or n.startswith(pref):
                return (i, n)
        # smaller-looking tags first among unknowns
        if any(x in n for x in ("1b", "2b", "3b", "4b", "7b", "8b", "9b")):
            return (30, n)
        return (60, n)

    candidates = sorted(models, key=score)
    for m in candidates:
        if "embed" in m.lower():
            continue
        if any(h in m.lower() for h in heavy) and not allow_heavy:
            continue
        return m
    for m in models:
        if "embed" not in m.lower():
            return m
    return models[0] if models else None


def detect(ollama_host: str = "http://127.0.0.1:11434") -> HardwareProfile:
    mem = _mem_gb()
    tools = _cli_tools()
    models = _ollama_models(ollama_host) if tools.get("ollama") else []
    # if ollama binary exists but API down, still try list via CLI in _ollama_models
    rec = recommend_ollama_model(models, mem["available"])
    notes: list[str] = []
    if not tools.get("node"):
        notes.append("Node.js missing — event bus/dashboard need node >= 18")
    if not tools.get("ollama"):
        notes.append("Ollama not found — install from https://ollama.com for local LLMs")
    elif not models:
        notes.append("Ollama installed but no models yet — ./run will auto-pull a small default")
    if mem["available"] < 8:
        notes.append("Low free RAM — prefer tiny models")
    if any(g.get("backend") == "unified" for g in _gpu_info()):
        notes.append("Unified memory: avoid loading huge models alongside other heavy services")

    return HardwareProfile(
        cpu_count=os.cpu_count() or 1,
        arch=platform.machine(),
        system=platform.system(),
        mem_total_gb=round(mem["total"], 1),
        mem_available_gb=round(mem["available"], 1),
        gpus=_gpu_info(),
        tools=tools,
        ollama_host=ollama_host,
        ollama_models=models,
        recommended_model=rec,
        notes=notes,
    )
