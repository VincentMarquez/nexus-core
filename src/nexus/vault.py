"""Env-backed secrets vault — presence checks + redaction (never commit values).

P1.5 slice: operators need a single place to ask "is the key configured?"
without dumping secrets into logs, MCP responses, or git.

Resolution order for :meth:`Vault.get`:

1. ``os.environ[NAME]``
2. ``os.environ["NEXUS_" + NAME]`` when NAME lacks the prefix
3. Optional local JSON map at ``NEXUS_VAULT_FILE`` or
   ``.nexus_state/vault.local.json`` (``.nexus_state/`` is gitignored)

Values are **never** written by this module. ``status()`` returns only
booleans / metadata. ``redact()`` masks known secret *values* in text.

Patterns (no tree vendor): mission-control env spend keys, lumen ops shell,
Hermes-Studio approvals — env-first secrets with audit-safe presence.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "nexus.vault/v1"

# Common provider / platform keys NEXUS may touch (extend via register / env list).
DEFAULT_KNOWN_KEYS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "GROK_API_KEY",
    "NEXUS_GROK_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "NEXUS_GITHUB_TOKEN",
    "HF_TOKEN",
    "HUGGINGFACE_TOKEN",
    "OLLAMA_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "TOGETHER_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "NEXUS_BUS_TOKEN",
    "NEXUS_MCP_TOKEN",
)

REDACTED = "***REDACTED***"
_MIN_SECRET_LEN = 8  # do not redact very short/ambiguous strings


def _root(workdir: Optional[Path] = None) -> Path:
    return Path(workdir or os.environ.get("NEXUS_PROJECT_ROOT") or os.getcwd()).resolve()


def default_vault_file(workdir: Optional[Path] = None) -> Path:
    env = (os.environ.get("NEXUS_VAULT_FILE") or "").strip()
    if env:
        return Path(env).expanduser()
    return _root(workdir) / ".nexus_state" / "vault.local.json"


@dataclass
class Vault:
    """Read-only secret resolver + redactor."""

    workdir: Optional[Path] = None
    known_keys: list[str] = field(default_factory=lambda: list(DEFAULT_KNOWN_KEYS))
    _file_cache: Optional[dict[str, str]] = field(default=None, repr=False)

    def register(self, *names: str) -> None:
        for n in names:
            key = (n or "").strip()
            if key and key not in self.known_keys:
                self.known_keys.append(key)

    def _load_file(self) -> dict[str, str]:
        if self._file_cache is not None:
            return self._file_cache
        path = default_vault_file(self.workdir)
        data: dict[str, str] = {}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        if v is None:
                            continue
                        s = str(v).strip()
                        if s:
                            data[str(k)] = s
            except Exception:
                data = {}
        self._file_cache = data
        return data

    def reload(self) -> None:
        self._file_cache = None

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        key = (name or "").strip()
        if not key:
            return default
        if key in os.environ and str(os.environ[key]).strip():
            return str(os.environ[key])
        # NEXUS_ prefix alias
        if not key.startswith("NEXUS_"):
            alt = f"NEXUS_{key}"
            if alt in os.environ and str(os.environ[alt]).strip():
                return str(os.environ[alt])
        # bare key without NEXUS_ when looking up NEXUS_* 
        if key.startswith("NEXUS_"):
            bare = key[len("NEXUS_") :]
            if bare in os.environ and str(os.environ[bare]).strip():
                return str(os.environ[bare])
        file_map = self._load_file()
        if key in file_map:
            return file_map[key]
        if not key.startswith("NEXUS_") and f"NEXUS_{key}" in file_map:
            return file_map[f"NEXUS_{key}"]
        return default

    def require(self, name: str) -> str:
        val = self.get(name)
        if val is None or not str(val).strip():
            raise KeyError(f"secret not configured: {name}")
        return str(val)

    def present(self, name: str) -> bool:
        val = self.get(name)
        return bool(val and str(val).strip())

    def source_of(self, name: str) -> str:
        """Where a key would resolve from (env | nexus_env | file | missing)."""
        key = (name or "").strip()
        if not key:
            return "missing"
        if key in os.environ and str(os.environ[key]).strip():
            return "env"
        if not key.startswith("NEXUS_"):
            alt = f"NEXUS_{key}"
            if alt in os.environ and str(os.environ[alt]).strip():
                return "nexus_env"
        if key.startswith("NEXUS_"):
            bare = key[len("NEXUS_") :]
            if bare in os.environ and str(os.environ[bare]).strip():
                return "env"
        file_map = self._load_file()
        if key in file_map or (not key.startswith("NEXUS_") and f"NEXUS_{key}" in file_map):
            return "file"
        return "missing"

    def status(self, keys: Optional[Iterable[str]] = None) -> dict[str, Any]:
        """Presence-only report — never includes secret values."""
        names = list(keys) if keys is not None else list(self.known_keys)
        # also surface any extra keys from vault file names only
        file_map = self._load_file()
        for k in file_map:
            if k not in names:
                names.append(k)
        present: dict[str, bool] = {}
        sources: dict[str, str] = {}
        for n in names:
            present[n] = self.present(n)
            sources[n] = self.source_of(n)
        return {
            "schema": SCHEMA,
            "vault_file": str(default_vault_file(self.workdir)),
            "vault_file_exists": default_vault_file(self.workdir).is_file(),
            "n_known": len(names),
            "n_present": sum(1 for v in present.values() if v),
            "present": present,
            "sources": sources,
        }

    def _secret_values(self) -> list[str]:
        vals: list[str] = []
        seen: set[str] = set()
        for name in self.known_keys:
            v = self.get(name)
            if not v:
                continue
            s = str(v).strip()
            if len(s) < _MIN_SECRET_LEN:
                continue
            if s not in seen:
                seen.add(s)
                vals.append(s)
        # file values even if key not in known list
        for v in self._load_file().values():
            s = str(v).strip()
            if len(s) >= _MIN_SECRET_LEN and s not in seen:
                seen.add(s)
                vals.append(s)
        # longest first so partial overlaps redact fully
        vals.sort(key=len, reverse=True)
        return vals

    def redact(self, text: str) -> str:
        """Replace known secret values in *text* with a redaction marker."""
        raw = str(text or "")
        if not raw:
            return raw
        out = raw
        for val in self._secret_values():
            if val in out:
                out = out.replace(val, REDACTED)
        # also mask common KEY=value patterns for known key names
        for name in self.known_keys:
            out = re.sub(
                rf"({re.escape(name)}\s*[=:]\s*)([^\s,;\"']+)",
                rf"\1{REDACTED}",
                out,
                flags=re.IGNORECASE,
            )
        return out

    def mask_mapping(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Return a shallow copy with secret-bearing values redacted."""
        known_lower = {k.lower() for k in self.known_keys}
        sensitive_names = {
            "token",
            "key",
            "secret",
            "password",
            "passwd",
            "api_key",
            "access_token",
            "refresh_token",
            "authorization",
            "auth",
        }
        out: dict[str, Any] = {}
        for k, v in data.items():
            kl = str(k).lower()
            sensitive = (
                kl in known_lower
                or kl in sensitive_names
                or "secret" in kl
                or "password" in kl
                or kl.endswith("_key")
                or kl.endswith("_token")
                or kl.endswith("token")
                or kl.endswith("secret")
            )
            if sensitive:
                if v is None or v == "":
                    out[k] = v
                elif isinstance(v, Mapping):
                    out[k] = self.mask_mapping(v)
                else:
                    out[k] = REDACTED
            elif isinstance(v, str):
                out[k] = self.redact(v)
            elif isinstance(v, Mapping):
                out[k] = self.mask_mapping(v)
            else:
                out[k] = v
        return out


def get_vault(workdir: Optional[Path] = None) -> Vault:
    return Vault(workdir=workdir)


def status(workdir: Optional[Path] = None) -> dict[str, Any]:
    return get_vault(workdir).status()


def redact(text: str, workdir: Optional[Path] = None) -> str:
    return get_vault(workdir).redact(text)


def present(name: str, workdir: Optional[Path] = None) -> bool:
    return get_vault(workdir).present(name)
