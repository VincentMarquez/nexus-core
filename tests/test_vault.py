"""Tests for P1.5 env-backed secrets vault (presence + redaction)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import vault as vmod
from nexus.vault import REDACTED, Vault


def test_present_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value-12345")
    v = Vault(workdir=tmp_path)
    assert v.present("OPENAI_API_KEY") is True
    assert v.source_of("OPENAI_API_KEY") == "env"
    assert v.get("OPENAI_API_KEY") == "sk-test-secret-value-12345"
    st = v.status(keys=["OPENAI_API_KEY", "ANTHROPIC_API_KEY"])
    assert st["present"]["OPENAI_API_KEY"] is True
    assert st["present"]["ANTHROPIC_API_KEY"] is False
    # status never embeds the raw value
    blob = json.dumps(st)
    assert "sk-test-secret-value-12345" not in blob


def test_nexus_prefix_alias(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("NEXUS_GITHUB_TOKEN", "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    v = Vault(workdir=tmp_path)
    assert v.present("GITHUB_TOKEN") is True
    assert v.source_of("GITHUB_TOKEN") == "nexus_env"


def test_file_vault_gitignored_path(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # clear env so file is used
    for k in list(vmod.DEFAULT_KNOWN_KEYS):
        monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv(f"NEXUS_{k}", raising=False)
    state = tmp_path / ".nexus_state"
    state.mkdir()
    secret = "file-secret-value-zzzzzzzz"
    (state / "vault.local.json").write_text(
        json.dumps({"CUSTOM_API_KEY": secret}),
        encoding="utf-8",
    )
    v = Vault(workdir=tmp_path)
    v.register("CUSTOM_API_KEY")
    assert v.present("CUSTOM_API_KEY") is True
    assert v.source_of("CUSTOM_API_KEY") == "file"
    assert v.require("CUSTOM_API_KEY") == secret


def test_require_missing(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MISSING_KEY_XYZ", raising=False)
    v = Vault(workdir=tmp_path)
    with pytest.raises(KeyError):
        v.require("MISSING_KEY_XYZ")


def test_redact_values_and_key_patterns(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    secret = "sk-super-secret-token-abcdef"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    v = Vault(workdir=tmp_path)
    text = f"calling with {secret} and OPENAI_API_KEY={secret} ok"
    red = v.redact(text)
    assert secret not in red
    assert REDACTED in red
    assert "OPENAI_API_KEY=" in red


def test_mask_mapping(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mask-me-please-now")
    v = Vault(workdir=tmp_path)
    masked = v.mask_mapping(
        {
            "OPENAI_API_KEY": "sk-mask-me-please-now",
            "note": "hello sk-mask-me-please-now world",
            "nested": {"token": "should-mask-by-key-name"},
            "safe": 42,
        }
    )
    assert masked["OPENAI_API_KEY"] == REDACTED
    assert "sk-mask-me-please-now" not in masked["note"]
    assert masked["nested"]["token"] == REDACTED
    assert masked["safe"] == 42


def test_module_helpers(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key-12345678")
    st = vmod.status(tmp_path)
    assert st["schema"] == "nexus.vault/v1"
    assert st["present"].get("XAI_API_KEY") is True
    assert vmod.present("XAI_API_KEY", tmp_path)
    assert "xai-test-key-12345678" not in vmod.redact(
        "leak xai-test-key-12345678 here", tmp_path
    )
