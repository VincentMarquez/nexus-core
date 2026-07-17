"""S12/S13 capability factory tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import capability_factory as cf
from nexus import factory_tools as ft


def test_propose_skill_quarantine_only(tmp_path: Path):
    r = cf.propose_skill(
        tmp_path,
        skill_id="code-review-demo",
        title="Code review demo",
        purpose="Review a slice",
        evidence="test",
    )
    assert r["ok"] is True
    cand = Path(r["path"])
    assert "capability_factory" in str(cand)
    assert "candidates/skills" in str(cand).replace("\\", "/")
    assert not (tmp_path / "skillpacks" / "code-review-demo").exists()
    assert (cand / "SKILL.md").is_file()
    assert (cand / "manifest.json").is_file()


def test_propose_tool_no_mcp(tmp_path: Path):
    r = cf.propose_tool(
        tmp_path,
        tool_name="nexus_demo_tool",
        purpose="demo",
        privilege="read",
    )
    assert r["ok"] is True
    assert r["privilege"] == "read"
    cand = Path(r["path"])
    assert (cand / "handler.py").is_file()
    assert (cand / "TOOL.md").is_file()


def test_invalid_ids_rejected(tmp_path: Path):
    with pytest.raises(cf.FactoryError):
        cf.sanitize_capability_id("../evil")
    with pytest.raises(cf.FactoryError):
        cf.propose_tool(tmp_path, tool_name="1starts_with_digit", privilege="read")
    with pytest.raises(cf.FactoryError):
        cf.propose_tool(tmp_path, tool_name="", privilege="read")


def test_soft_accept_and_activate_skill(tmp_path: Path):
    r = cf.propose_skill(tmp_path, skill_id="activate-me", purpose="p", evidence="e")
    cand = Path(r["path"])
    acc = cf.soft_accept_skill(cand)
    assert acc["accept"] is True
    act = cf.activate_skill(tmp_path, cand)
    assert act["ok"] is True
    assert (tmp_path / "skillpacks" / "activate-me" / "SKILL.md").is_file()
    # refuse double activate without force
    with pytest.raises(cf.FactoryError):
        cf.activate_skill(tmp_path, cand)


def test_activate_skill_refuses_outside_factory(tmp_path: Path):
    fake = tmp_path / "skillpacks" / "x"
    fake.mkdir(parents=True)
    (fake / "SKILL.md").write_text("# x\n", encoding="utf-8")
    (fake / "manifest.json").write_text('{"id":"x"}\n', encoding="utf-8")
    (fake / "STATUS.json").write_text(
        '{"id":"x","status":"accepted"}\n', encoding="utf-8"
    )
    with pytest.raises(cf.FactoryError):
        cf.activate_skill(tmp_path, fake)


def test_write_tool_activate_requires_flag(tmp_path: Path):
    r = cf.propose_tool(
        tmp_path, tool_name="nexus_write_demo", purpose="w", privilege="write"
    )
    with pytest.raises(cf.FactoryError):
        cf.activate_tool_record(tmp_path, r["path"], allow_write=False)
    ok = cf.activate_tool_record(tmp_path, r["path"], allow_write=True)
    assert ok["ok"] is True


def test_builtin_tools(tmp_path: Path):
    # seed a lesson
    from nexus import cross_run_lessons as crl

    crl.append_lesson(
        tmp_path, code="panel_timeout_or_offline", text="timed out", severity="med"
    )
    r = ft.nexus_lesson_query(tmp_path, query="timeout")
    assert r["ok"] is True
    assert r["count"] >= 1

    r2 = ft.nexus_scope_check(
        tmp_path, paths=["src/nexus/a.py", ".venv/x"]
    )
    assert r2["ok"] is True
    assert ".venv/x" in r2["classification"]["forbidden_hit"] or ".venv/x" in r2[
        "classification"
    ]["out_of_scope"]

    # skill search after propose
    cf.propose_skill(tmp_path, skill_id="find-me", purpose="p")
    r3 = ft.nexus_skill_search(tmp_path, query="find-me")
    assert r3["count"] >= 1

    r4 = ft.nexus_code_review(tmp_path, paths=["nope.py"])
    assert r4["ok"] is True
    assert any(f.get("issue") == "missing_file" for f in r4["findings"])


def test_invoke_tool_dispatch(tmp_path: Path):
    r = ft.invoke_tool("nexus_skill_search", tmp_path, query="")
    assert r["ok"] is True
    r2 = ft.invoke_tool("not_a_tool", tmp_path)
    assert r2["ok"] is False


def test_bootstrap_wave(tmp_path: Path):
    out = cf.bootstrap_wave_ab(tmp_path)
    assert out["ok"] is True
    assert out["skill"] is not None
    assert out["tools"] is not None
    # second bootstrap does not duplicate golden skill path error
    out2 = cf.bootstrap_wave_ab(tmp_path)
    assert out2["skill"].get("skipped") or out2["skill"].get("ok")


def test_harvest_from_lessons(tmp_path: Path):
    from nexus import cross_run_lessons as crl

    for _ in range(2):
        crl.append_lesson(
            tmp_path,
            code="panel_timeout_or_offline",
            text="bridge timeout",
            severity="med",
        )
    out = cf.harvest_skill_proposals_from_lessons(
        tmp_path, limit=3, fill=True, auto_accept=True, use_grok_fill=False
    )
    assert out["ok"] is True
    ids = [p.get("id") for p in out["proposed"] if p.get("ok")]
    assert "panel-timeout-resilience" in ids or any(
        "panel" in str(p) for p in out["proposed"]
    )
    # fill path should leave candidate filled/accepted
    filled = [p for p in out["proposed"] if p.get("fill") or p.get("accept")]
    assert filled


def test_fill_skill_heuristic(tmp_path: Path):
    r = cf.propose_skill(
        tmp_path, skill_id="fill-me", purpose="Do a careful review", evidence="e"
    )
    out = cf.fill_skill_candidate(tmp_path, r["path"], use_grok=False)
    assert out["ok"] is True
    assert out["filled_by"] == "heuristic"
    text = Path(r["path"]).joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "## Procedure" in text
    assert "1. …" not in text
    st = json.loads(Path(r["path"]).joinpath("STATUS.json").read_text(encoding="utf-8"))
    assert st["status"] == "filled"


def test_fill_skill_with_mock_grok(tmp_path: Path):
    r = cf.propose_skill(
        tmp_path, skill_id="grok-fill-me", purpose="p", evidence="e"
    )

    def fake_grok(_root, prompt, **_kw):
        body = (
            "# Skill: Grok Fill\n\n"
            "## When to use\n\n- Use for portfolio slice reviews.\n\n"
            "## Steps\n\n1. Orient on the delta.\n2. Diagnose risks.\n"
            "3. Act with minimal edits.\n4. Verify tests.\n5. Leave trail.\n\n"
            "## Procedure\n\n1. **Orient** — list in-scope files.\n"
            "2. **Diagnose** — map symptoms to one root cause.\n"
            "3. **Act** — smallest change that satisfies Success.\n"
            "4. **Verify** — run focused tests.\n"
            "5. **Leave trail** — record residuals.\n\n"
            "## Tools\n\n- `nexus_scope_check`\n- `nexus_code_review`\n\n"
            "## Rules\n\n1. Prefer small, tested changes.\n"
            "2. Do not force-push or commit secrets.\n\n"
            "## Success\n\n- Procedure complete or residual noted\n"
            "- Layout tests pass\n"
        )
        return {"text": body}

    out = cf.fill_skill_candidate(
        tmp_path, r["path"], use_grok=True, grok_fn=fake_grok
    )
    assert out["ok"] is True
    assert out["filled_by"] == "grok"
    assert "Grok Fill" in Path(r["path"]).joinpath("SKILL.md").read_text(
        encoding="utf-8"
    )


def test_spawn_required_tools_on_propose(tmp_path: Path):
    r = cf.propose_skill(
        tmp_path,
        skill_id="needs-tools",
        purpose="p",
        required_tools=["nexus_custom_helper_xyz"],
    )
    # builtin names are not re-spawned; custom gets a candidate
    tools = cf.list_candidates(tmp_path, kind="tools")
    ids = {t.get("id") for t in tools}
    assert "nexus_custom_helper_xyz" in ids or any(
        "custom_helper" in str(i) for i in ids
    )
    assert r["ok"] is True


def test_collect_and_implement_capability_skill(tmp_path: Path):
    cf.propose_skill(tmp_path, skill_id="cap-skill-a", purpose="review slice")
    ideas = cf.collect_capability_ideas(tmp_path, limit=4)
    assert ideas
    skill_ideas = [i for i in ideas if i.get("capability_kind") == "skill"]
    assert skill_ideas
    res = cf.implement_capability_idea(
        tmp_path,
        skill_ideas[0],
        use_grok_fill=False,
        auto_activate_skill=True,
    )
    assert res.get("ok") is True
    assert res.get("fill")
    assert res.get("accept", {}).get("accept") is True
    sid = skill_ideas[0]["capability_id"]
    assert (tmp_path / "skillpacks" / sid / "SKILL.md").is_file()


def test_implement_novel_capability_skill(tmp_path: Path):
    idea = {
        "source": "capability_skill",
        "id": "capability:skill:novel-diff-review",
        "capability_id": "novel-diff-review",
        "capability_kind": "skill",
        "title": "Create skill novel-diff-review",
        "concrete": "Review only the git delta",
        "summary": "delta review",
    }
    res = cf.implement_capability_idea(
        tmp_path, idea, use_grok_fill=False, auto_activate_skill=True
    )
    assert res.get("ok") is True
    assert (tmp_path / "skillpacks" / "novel-diff-review" / "SKILL.md").is_file()


def test_auto_activate_and_retire(tmp_path: Path):
    r = cf.propose_skill(tmp_path, skill_id="retire-me", purpose="p", evidence="e")
    cf.fill_skill_candidate(tmp_path, r["path"], use_grok=False)
    acc = cf.soft_accept_skill(r["path"])
    assert acc["accept"] is True
    out = cf.auto_activate_ready_skills(tmp_path, limit=2, fill_first=False)
    assert out["ok"] is True
    assert any(a.get("id") == "retire-me" or a.get("ok") for a in out["activated"])
    assert (tmp_path / "skillpacks" / "retire-me").is_dir()
    ret = cf.retire_skill(tmp_path, "retire-me", reason="test")
    assert ret["ok"] is True
    assert not (tmp_path / "skillpacks" / "retire-me").exists()
    assert "retired" in ret["path"]


def test_portfolio_selects_capability_ideas(tmp_path: Path):
    from nexus import idea_portfolio as ip

    # minimal arxiv/github seeds so portfolio can form
    arxiv = [
        {
            "id": "arxiv:1",
            "source": "arxiv",
            "title": "A",
            "score": 5,
            "summary": "s",
            "concrete": "c",
            "url": "",
            "arxiv_id": "2401.00001",
        }
    ]
    github = [
        {
            "id": "github:1",
            "source": "github",
            "title": "G",
            "score": 5,
            "summary": "s",
            "concrete": "c",
            "url": "",
        }
    ]
    caps = cf.collect_capability_ideas(tmp_path, limit=3)
    # ensure at least one novel capability idea even without candidates
    assert any(str(c.get("id") or "").startswith("capability:") for c in caps)
    port = ip.select_portfolio(
        arxiv, github, [], max_ideas=6, capability=caps, max_capability=2
    )
    cap_sel = [p for p in port if str(p.get("source") or "").startswith("capability")]
    assert len(cap_sel) >= 1
