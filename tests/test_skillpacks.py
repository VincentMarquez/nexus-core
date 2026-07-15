"""Tests for multi-harness skillpack list/validate/generate/drift (P2.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import skillpacks as sp
from nexus import mcp_server
from nexus.cli import main as cli_main


def _write_pack(
    root: Path,
    pack_id: str = "demo-pack",
    *,
    privilege: str = "read",
    harnesses: list[str] | None = None,
    skill_extra: str = "",
    bad_manifest: bool = False,
) -> Path:
    d = root / "skillpacks" / pack_id
    d.mkdir(parents=True, exist_ok=True)
    man = {
        "id": pack_id,
        "version": "0.1.0",
        "name": "Demo pack",
        "tags": ["test", privilege],
        "privilege": privilege,
        "entrypoints": {"skill": "SKILL.md"},
        "harnesses": harnesses or ["grok", "local"],
    }
    if bad_manifest:
        (d / "manifest.json").write_text("{not json", encoding="utf-8")
    else:
        (d / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    skill = f"""# Skill: Demo pack

## When to use

- Unit tests for skillpack generator

## Commands

```bash
nexus skillpacks list
nexus skillpacks validate
```

## Rules

1. Keep tests green.
2. Never vendor whole trees.

## Success

- validate ok
- generate writes harness stubs
{skill_extra}
"""
    (d / "SKILL.md").write_text(skill, encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# Core library
# ---------------------------------------------------------------------------


def test_list_and_validate_ok(tmp_path: Path):
    _write_pack(tmp_path)
    rows = sp.list_packs(tmp_path, validate=True)
    assert len(rows) == 1
    assert rows[0].id == "demo-pack"
    assert rows[0].privilege == "read"
    assert rows[0].valid is True
    rep = sp.validate_all(tmp_path)
    assert rep["ok"] is True
    assert rep["errors"] == 0


def test_validate_missing_skill(tmp_path: Path):
    d = tmp_path / "skillpacks" / "broken"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(
        json.dumps({"id": "broken", "version": "0.0.1", "name": "Broken"}),
        encoding="utf-8",
    )
    rep = sp.validate_pack(d)
    assert rep.ok is False
    assert any("SKILL.md" in f.message for f in rep.findings)


def test_validate_bad_privilege(tmp_path: Path):
    d = _write_pack(tmp_path)
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    man["privilege"] = "root"
    (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    rep = sp.validate_pack(d)
    assert rep.ok is False
    assert any("privilege" in f.message for f in rep.findings)


def test_least_privilege_filter(tmp_path: Path):
    _write_pack(tmp_path, "read-pack", privilege="read")
    _write_pack(tmp_path, "ops-pack", privilege="ops")
    _write_pack(tmp_path, "admin-pack", privilege="admin")
    rows = sp.list_packs(tmp_path, max_privilege="write")
    ids = {r.id for r in rows}
    assert "read-pack" in ids
    assert "ops-pack" not in ids
    assert "admin-pack" not in ids


def test_generate_and_drift(tmp_path: Path):
    _write_pack(tmp_path, harnesses=["grok", "cursor", "local"])
    out = tmp_path / "out"
    gen = sp.generate_all(tmp_path, out_root=out)
    assert gen["ok"] is True
    assert gen["count"] == 1
    written = gen["generated"][0]["written"]
    assert any(p.startswith("grok/") for p in written)
    assert any(p.startswith("cursor/") for p in written)
    # SKILL body present in generated
    skill_out = out / "grok" / "skills" / "demo-pack" / "SKILL.md"
    assert skill_out.is_file()
    body = skill_out.read_text(encoding="utf-8")
    assert "When to use" in body
    # meta has privilege
    meta = json.loads(
        (out / "grok" / "skills" / "demo-pack" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert meta["privilege"] == "read"
    assert meta["pack_id"] == "demo-pack"

    drift = sp.drift_check(tmp_path, out_root=out)
    assert drift["ok"] is True
    assert drift["errors"] == 0

    # Corrupt generated → drift warning
    skill_out.write_text("# totally different\n", encoding="utf-8")
    drift2 = sp.drift_check(tmp_path, out_root=out)
    assert any("drifts" in f["message"] for f in drift2["findings"])


def test_generate_refuses_invalid(tmp_path: Path):
    d = tmp_path / "skillpacks" / "bad"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(
        json.dumps({"id": "bad", "version": "", "name": ""}),
        encoding="utf-8",
    )
    (d / "SKILL.md").write_text("x", encoding="utf-8")
    with pytest.raises(sp.SkillpackError):
        sp.generate_pack(d, out_root=tmp_path / "out")


def test_drift_missing_artifacts(tmp_path: Path):
    _write_pack(tmp_path)
    drift = sp.drift_check(tmp_path, out_root=tmp_path / "empty-out")
    assert drift["ok"] is False
    assert drift["errors"] >= 1


def test_cursor_mdc_frontmatter(tmp_path: Path):
    _write_pack(tmp_path, harnesses=["cursor"])
    out = tmp_path / "out"
    sp.generate_pack(
        tmp_path / "skillpacks" / "demo-pack",
        out_root=out,
        harnesses=["cursor"],
    )
    mdc = (out / "cursor" / "rules" / "demo-pack.mdc").read_text(encoding="utf-8")
    assert mdc.startswith("---")
    assert "nexus_pack: demo-pack" in mdc
    assert "privilege: read" in mdc


# ---------------------------------------------------------------------------
# Real repo pack (durable-operator)
# ---------------------------------------------------------------------------


def test_repo_durable_operator_validates():
    root = Path(__file__).resolve().parents[1]
    packs = sp.list_packs(root)
    ids = {p.id for p in packs}
    assert "durable-operator" in ids
    rep = sp.validate_all(root)
    assert rep["ok"] is True
    # privilege ops declared
    op = next(p for p in packs if p.id == "durable-operator")
    assert op.privilege == "ops"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_list_validate_generate(tmp_path: Path, capsys):
    _write_pack(tmp_path)
    assert cli_main(["skillpacks", "list", "--path", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "demo-pack" in out

    assert cli_main(["skillpacks", "validate", "--path", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True

    out_dir = tmp_path / "gen"
    rc = cli_main(
        [
            "skillpacks",
            "generate",
            "--path",
            str(tmp_path),
            "--out",
            str(out_dir),
            "--json",
        ]
    )
    assert rc == 0
    gen = json.loads(capsys.readouterr().out)
    assert gen["ok"] is True
    assert (out_dir / "local" / "demo-pack" / "SKILL.md").is_file()

    assert (
        cli_main(
            [
                "skillpacks",
                "drift",
                "--path",
                str(tmp_path),
                "--out",
                str(out_dir),
                "--json",
            ]
        )
        == 0
    )


def test_cli_max_privilege(tmp_path: Path, capsys):
    _write_pack(tmp_path, "ops-only", privilege="ops")
    assert (
        cli_main(
            [
                "skillpacks",
                "list",
                "--path",
                str(tmp_path),
                "--max-privilege",
                "read",
                "--json",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["packs"] == []


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------


def test_mcp_skillpacks_tool(tmp_path: Path, monkeypatch):
    _write_pack(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    # list
    r = mcp_server.call_tool("skillpacks", {"action": "list"})
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["count"] == 1
    assert body["packs"][0]["id"] == "demo-pack"

    # validate
    r = mcp_server.call_tool("skillpacks", {"action": "validate"})
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["ok"] is True

    # generate
    r = mcp_server.call_tool(
        "skillpacks", {"action": "generate", "pack": "demo-pack", "harness": "local"}
    )
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    assert body["ok"] is True

    # drift
    r = mcp_server.call_tool("skillpacks", {"action": "drift"})
    assert r.get("isError") is False
    body = json.loads(r["content"][0]["text"])
    # local only generated; other harnesses may be missing → errors possible
    assert "findings" in body


def test_mcp_tool_registered():
    names = {t["name"] for t in mcp_server.TOOLS}
    assert "skillpacks" in names
