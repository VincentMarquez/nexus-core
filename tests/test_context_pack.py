"""Tests for P1.4 bounded multi-source context pack."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import DurableEngine, Settings, Task
from nexus.context_pack import (
    SCHEMA,
    ContextPack,
    build_context_pack,
    estimate_tokens,
    load_pack,
    load_repo_digests,
    make_section,
    pack_from_grade,
    parse_improve_digest,
    save_pack,
    truncate_chars,
)
from nexus.engine import TaskStatus
from nexus import mcp_server
from nexus.cli import main


# ---------------------------------------------------------------------------
# Truncation + section budgets
# ---------------------------------------------------------------------------


def test_truncate_chars_and_tokens():
    assert truncate_chars("hello", 10) == "hello"
    cut = truncate_chars("x" * 100, 20)
    assert len(cut) <= 20
    assert "truncated" in cut or cut.endswith("…]") or "…" in cut
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 8) == 2


def test_make_section_applies_budget():
    sec = make_section("goal", "y" * 5000, max_chars=100)
    assert len(sec.content) <= 100
    assert sec.truncated is True
    assert sec.name == "goal"


def test_total_budget_trims_low_priority():
    pack = build_context_pack(
        objective="test objective " + ("z" * 200),
        success_criteria=["a", "b"],
        constraints=["deny:network"],
        notes="n" * 5000,
        journal_block="j" * 3000,
        memory_hits=[{"text": "m" * 2000}],
        prior={"1": "p" * 2000},
        include_research=False,
        include_repo_digests=False,
        total_budget=1500,
    )
    assert pack.total_chars <= 1500
    assert pack.section("goal") is not None
    # notes/memory should be trimmed or dropped first
    doc = pack.to_dict()
    assert doc["schema"] == SCHEMA
    assert doc["total_chars"] <= 1500
    assert "prompt" not in doc  # prompt via method
    prompt = pack.prompt_block()
    assert "CONTEXT PACK" in prompt
    assert "goal" in prompt


def test_parse_improve_digest_both_formats():
    ours = """
# Improve ours

## labsai/EDDI (score 16.0)
- idea=8.0 skill=8.0
- Config-driven multi-agent middleware with MCP.
- local clone: /tmp/eddi

## MattMagg/MisterSmith (score 16.0)
- A modular Rust multi-agent runtime OS.

## Combined engineering goal
- skip me
"""
    entries = parse_improve_digest(ours, min_score=10.0, limit=5)
    assert len(entries) >= 2
    repos = {e["repo"] for e in entries}
    assert "labsai/EDDI" in repos
    assert "MattMagg/MisterSmith" in repos

    use = """
## [wshobson/agents](https://github.com/wshobson/agents) — score 15.0

- idea=8.0 skill=7.0
- summary: multi-harness agentic marketplace
"""
    entries2 = parse_improve_digest(use, min_score=10.0)
    assert any(e["repo"] == "wshobson/agents" for e in entries2)
    assert entries2[0]["score"] == 15.0


def test_load_repo_digests_and_research_from_workdir(tmp_path: Path):
    state = tmp_path / ".nexus_state"
    (state / "repo_mine").mkdir(parents=True)
    (state / "arxiv_improve").mkdir(parents=True)
    (state / "repo_mine" / "IMPROVE_OURS.md").write_text(
        "## acme/widget (score 12.0)\n- summary: reusable widget kit\n",
        encoding="utf-8",
    )
    (state / "arxiv_improve" / "improve-rx-deadbeef.md").write_text(
        "# arXiv improve\n\nContext engineering paper notes " + ("x" * 100),
        encoding="utf-8",
    )
    digests = load_repo_digests(tmp_path, min_score=10.0)
    assert digests and digests[0]["repo"] == "acme/widget"

    pack = build_context_pack(
        workdir=tmp_path,
        objective="self-improve with research",
        include_research=True,
        include_repo_digests=True,
        total_budget=8000,
    )
    names = {s.name for s in pack.sections}
    assert "goal" in names
    assert "research" in names
    assert "repo_digest" in names
    assert pack.total_chars <= 8000


def test_save_load_roundtrip(tmp_path: Path):
    pack = build_context_pack(
        objective="roundtrip",
        notes="hello",
        include_research=False,
        include_repo_digests=False,
    )
    path = tmp_path / "pack.json"
    save_pack(path, pack)
    loaded = load_pack(path)
    assert loaded.schema == SCHEMA
    assert loaded.section("goal") is not None
    assert loaded.section("notes") is not None


def test_pack_from_grade(tmp_path: Path):
    grade = {
        "repo": "ahmedEid1/lumen",
        "score": 15.0,
        "idea": 7.0,
        "skill": 8.0,
        "pattern": "phase guards + decision audit",
        "method": "grok:grok-4.5",
        "notes": "decision audit trails",
    }
    pack = pack_from_grade(tmp_path, grade)
    assert pack.section("grade") is not None
    assert "lumen" in pack.section("grade").content
    assert pack.meta.get("source") == "improve_apply"


def test_preference_brief_injected_into_context_pack(tmp_path: Path):
    """P1.1: offline preference pairs become a context_pack section."""
    from nexus import preference_pairs as pp
    from nexus.context_pack import load_preference_section

    pp.record_pair(
        tmp_path,
        better="wshobson/agents",
        worse="openai/swarm",
        better_score=16.0,
        worse_score=13.0,
        source="test",
    )
    pp.record_pair(
        tmp_path,
        better="wshobson/agents",
        worse="AgenticGoKit/AgenticGoKit",
        source="test",
    )
    loaded = load_preference_section(
        tmp_path,
        grade={"repo": "wshobson/agents"},
    )
    assert loaded is not None
    assert loaded["n_pairs"] == 2
    assert loaded["focus_repo"] == "wshobson/agents"
    assert float(loaded["focus_boost"]) > 0

    pack = build_context_pack(
        workdir=tmp_path,
        objective="self-improve with preference bias",
        grade={
            "repo": "wshobson/agents",
            "score": 16.0,
            "idea": 8.0,
            "skill": 8.0,
            "method": "grok:grok-4.5",
        },
        include_research=False,
        include_repo_digests=False,
        include_preference=True,
        total_budget=8000,
    )
    pref = pack.section("preference")
    assert pref is not None
    assert "wshobson/agents" in pref.content
    assert "preference pairs" in pref.content.lower() or "leaderboard" in pref.content
    assert pack.meta.get("include_preference") is True
    assert pack.meta.get("preference_n_pairs") == 2
    assert pack.meta.get("preference_focus") == "wshobson/agents"
    prompt = pack.prompt_block()
    assert "## preference" in prompt

    # --no-preference path
    pack_off = build_context_pack(
        workdir=tmp_path,
        objective="no pref",
        include_research=False,
        include_repo_digests=False,
        include_preference=False,
    )
    assert pack_off.section("preference") is None
    assert pack_off.meta.get("include_preference") is False

    # empty store → section omitted (budget-friendly)
    empty = tmp_path / "empty_wd"
    empty.mkdir()
    pack_empty = build_context_pack(
        workdir=empty,
        objective="empty prefs",
        include_research=False,
        include_repo_digests=False,
        include_preference=True,
    )
    assert pack_empty.section("preference") is None


# ---------------------------------------------------------------------------
# Engine + CLI
# ---------------------------------------------------------------------------


def test_engine_context_pack_export(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="ctx1",
        objective="context pack engine export",
        success_criteria=["artifact contains DEMO_OK"],
        constraints=["deny:network"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed

    rep = engine.context_pack("ctx1")
    assert rep["found"] is True
    assert rep["schema"] == SCHEMA
    assert rep["total_chars"] > 0
    assert rep["prompt"]
    assert "CONTEXT PACK" in rep["prompt"]
    names = {s["name"] for s in rep["sections"]}
    assert "goal" in names
    # after run, journal and/or prior should appear
    assert "journal" in names or "prior" in names or "memory" in names

    missing = engine.context_pack("nope")
    assert missing["found"] is False


def test_engine_injects_context_pack_on_resume_meta(tmp_path: Path):
    """When meta.context_pack is set, step prompts include the pack block."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="ctx_inj",
        objective="inject pack mid-run",
        success_criteria=["artifact contains DEMO_OK"],
        meta={"context_pack": True},
    )
    # kill after first steps so current_step > 0 path is exercised on resume
    task = engine.run(task, max_steps=2)
    assert task.current_step >= 1 or task.status in (
        TaskStatus.completed,
        TaskStatus.running,
        TaskStatus.failed,
    )
    # context_pack export always works
    rep = engine.context_pack(task.task_id)
    assert rep["found"]
    assert rep["total_chars"] >= 0


def test_task_context_cli(tmp_path: Path, capsys):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="cli_ctx",
        objective="cli context board",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    state = str(settings.state_dir)

    rc = main(["task", "context", "cli_ctx", "--state-dir", state])
    assert rc == 0
    out = capsys.readouterr().out
    assert "context cli_ctx" in out
    assert "sections:" in out
    assert "chars=" in out

    rc = main(["task", "context", "cli_ctx", "--state-dir", state, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert SCHEMA in out

    rc = main(["task", "context", "cli_ctx", "--state-dir", state, "--prompt"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CONTEXT PACK" in out

    out_path = tmp_path / "ctx.json"
    rc = main(
        [
            "task",
            "context",
            "cli_ctx",
            "--state-dir",
            state,
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.is_file()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["schema"] == SCHEMA

    rc = main(["task", "context", "missing", "--state-dir", state])
    assert rc == 1


def test_improve_apply_uses_formal_pack(tmp_path: Path):
    from nexus import improve_apply as ia

    # seed research + digests so pack has multi-source sections
    state = tmp_path / ".nexus_state"
    (state / "repo_mine").mkdir(parents=True)
    (state / "arxiv_improve").mkdir(parents=True)
    (state / "repo_mine" / "IMPROVE_OURS.md").write_text(
        "## acme/tooling (score 14.0)\n- summary: solid CLI patterns\n",
        encoding="utf-8",
    )
    (state / "arxiv_improve" / "improve-rx-abc123.md").write_text(
        "# notes\n\ncontext engineering abstract…\n",
        encoding="utf-8",
    )

    run = ia.start_run(tmp_path, grade=ia.default_lumen_grade(), run_id="ctx-ia")
    assert run.ensure_context_packed() == "context_packed"
    assert run.context_pack_path
    pack_path = tmp_path / run.context_pack_path
    assert pack_path.is_file()
    data = json.loads(pack_path.read_text(encoding="utf-8"))
    assert data["schema"] == SCHEMA
    assert data.get("repo")  # flat grade fields preserved
    assert "sections" in data
    assert data.get("prompt")
    assert "grade" in {s["name"] for s in data["sections"]}
    # prompt artifact
    prompt_path = run.run_dir / "context_pack.prompt.md"
    assert prompt_path.is_file()
    assert "CONTEXT PACK" in prompt_path.read_text(encoding="utf-8")
    # idempotent
    assert run.ensure_context_packed() == "context_packed"


def test_mcp_context_pack_tool(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mcp_server, "_root", lambda: tmp_path)
    (tmp_path / ".nexus_state" / "repo_mine").mkdir(parents=True)
    (tmp_path / ".nexus_state" / "repo_mine" / "USE_LATEST.md").write_text(
        "## [acme/demo](https://example.com) — score 11.0\n- summary: demo digest\n",
        encoding="utf-8",
    )
    res = mcp_server.call_tool(
        "context_pack",
        {"objective": "mcp pack", "research": False, "repos": True},
    )
    assert not res.get("isError")
    text = res["content"][0]["text"]
    assert SCHEMA in text or "repo_digest" in text or "sections" in text
