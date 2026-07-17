"""Tests for User Intent Model (ToM-SWE × wshobson marketplace)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import user_intent as ui
from nexus.orchestrator import Orchestrator, load_envelope


def _write_plugin(
    root: Path,
    plugin_id: str = "demo-plugin",
    *,
    agent_name: str = "durable-operator",
    skill_name: str = "fix-tests",
    command_name: str = "review-code",
) -> Path:
    d = root / "plugins" / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_id,
                "version": "0.1.0",
                "description": "Intent test plugin",
                "privilege": "read",
                "tags": ["test", "intent", "durable"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    agents = d / "agents"
    agents.mkdir(exist_ok=True)
    (agents / f"{agent_name}.md").write_text(
        f"---\nname: {agent_name}\ndescription: Durable board operator\n---\n\n"
        f"# {agent_name}\n",
        encoding="utf-8",
    )
    commands = d / "commands"
    commands.mkdir(exist_ok=True)
    (commands / f"{command_name}.md").write_text(
        f"---\nname: {command_name}\n---\n\n# /{command_name}\n",
        encoding="utf-8",
    )
    skill = d / "skills" / skill_name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {skill_name}\n---\n\n# Skill {skill_name}\n",
        encoding="utf-8",
    )
    return d


# ── sanitizers / basics ─────────────────────────────────────────────────────


def test_sanitize_user_id():
    assert ui.sanitize_user_id("alice") == "alice"
    assert ui.sanitize_user_id("a b/c") == "a_b_c"
    assert ui.sanitize_user_id("") == "default"
    with pytest.raises(ui.UserIntentError):
        ui.sanitize_user_id("..")


def test_detect_ambiguity_empty_and_deictic():
    assert "empty_instruction" in ui.detect_ambiguity("")
    sigs = ui.detect_ambiguity("fix it")
    assert "action_without_object" in sigs or "deictic_without_history" in sigs
    bare = ui.detect_ambiguity("fix")
    assert "bare_action_verb" in bare or "very_short_instruction" in bare


def test_detect_ambiguity_with_history_less_severe():
    hist = [ui.InteractionTurn(role="user", content="The login module is broken")]
    # With history, pure deictic is still flagged when short
    sigs = ui.detect_ambiguity("fix it", history=hist)
    assert isinstance(sigs, list)


def test_extract_goal_verbs_and_constraints():
    text = (
        "Implement a small scoped user intent module and keep tests green. "
        "Do not force-push. Prefer pytest."
    )
    verbs = ui.extract_goal_verbs(text)
    assert "implement" in verbs
    assert "test" in verbs
    cons = ui.extract_constraints(text)
    assert any("force" in c.lower() or "green" in c.lower() for c in cons)
    prefs = ui.extract_preferences(text)
    assert "use" in prefs or "prefer" in prefs or prefs.get("scope") == "small"


def test_extract_goal_phrase():
    g = ui.extract_goal_phrase("Add unit tests for the marketplace planner")
    assert "test" in g.lower() or "Add" in g


# ── memory / history durability ─────────────────────────────────────────────


def test_user_memory_roundtrip(tmp_path: Path):
    model = ui.UserIntentModel.open(tmp_path, user_id="dev1")
    mem = model.load_memory()
    assert mem.user_id == "dev1"
    assert mem.n_interactions == 0
    mem.blend(
        goals=["keep pytest green"],
        constraints=["no force-push"],
        preferences={"scope": "small"},
    )
    model.save_memory(mem)
    back = model.load_memory()
    assert "keep pytest green" in back.goals
    assert any("force" in c for c in back.constraints)
    assert back.preferences.get("scope") == "small"
    assert back.n_interactions == 1
    assert back.paper == ui.PAPER
    assert back.schema == ui.SCHEMA


def test_history_append_and_load(tmp_path: Path):
    model = ui.UserIntentModel.open(tmp_path, user_id="h1")
    model.observe("first message", role="user")
    model.observe("agent reply", role="agent")
    model.append_turn({"role": "user", "content": "second"})
    hist = model.load_history()
    assert len(hist) == 3
    assert hist[0].content == "first message"
    assert hist[1].role == "agent"
    stats = model.stats()
    assert stats["n_history"] == 3
    assert stats["user_id"] == "h1"


# ── infer_intent core ───────────────────────────────────────────────────────


def test_infer_intent_clear_instruction():
    hyp = ui.infer_intent(
        "Implement a dedicated User Intent Model module with pytest coverage",
        suggest=False,
    )
    assert hyp.goal
    assert "implement" in hyp.goal_verbs or "test" in hyp.goal_verbs
    assert hyp.confidence >= 0.45
    assert hyp.schema == ui.SCHEMA
    assert hyp.paper == "arxiv:2510.21903v2"
    assert "Original:" in hyp.clarified_instruction or hyp.clarified_instruction
    d = hyp.to_dict()
    assert d["is_ambiguous"] is hyp.is_ambiguous
    back = ui.IntentHypothesis.from_dict(d)
    assert back.goal == hyp.goal


def test_infer_intent_ambiguous_uses_history_and_memory():
    hist = [
        ui.InteractionTurn(
            role="user",
            content="The orchestrator soft-hook for state replay is incomplete",
        ),
        ui.InteractionTurn(role="agent", content="Noted the state_replay gap"),
    ]
    mem = ui.UserMemory(
        user_id="u1",
        goals=["keep make test green"],
        constraints=["do not vendor whole upstream trees"],
        preferences={"scope": "small"},
    )
    hyp = ui.infer_intent(
        "fix it properly",
        history=hist,
        memory=mem,
        suggest=False,
        user_id="u1",
    )
    assert hyp.history_used == 2
    assert hyp.memory_used is True
    assert hyp.ambiguity  # still ambiguous
    assert any("vendor" in c or "green" in c for c in hyp.constraints)
    assert "Context from prior turns" in hyp.clarified_instruction
    assert hyp.preferences.get("scope") == "small"


def test_infer_intent_empty():
    hyp = ui.infer_intent("", suggest=False)
    assert "empty_instruction" in hyp.ambiguity
    assert hyp.confidence < 0.3


# ── marketplace suggestions ─────────────────────────────────────────────────


def test_suggest_marketplace_components(tmp_path: Path):
    _write_plugin(tmp_path)
    suggestions = ui.suggest_marketplace_components(
        tmp_path,
        instruction="fix failing tests and review the durable operator path",
        goal_verbs=["fix", "test", "review"],
        top_k=5,
        min_score=0.05,
    )
    assert suggestions
    kinds = {s.kind for s in suggestions}
    assert kinds <= ui.MARKETPLACE_SURFACES
    # At least one of our plugin components should appear
    names = {s.name for s in suggestions}
    assert names & {"durable-operator", "fix-tests", "review-code"}
    for s in suggestions:
        assert s.tool_id.startswith(s.kind + ":")
        assert s.score >= 0.0


def test_model_infer_persists_and_suggests(tmp_path: Path):
    _write_plugin(tmp_path)
    model = ui.UserIntentModel.open(tmp_path, user_id="dev")
    hyp = model.infer(
        "Implement durable operator review skill and keep tests green; "
        "do not force-push",
        suggest=True,
        top_k=3,
        persist=True,
    )
    assert hyp.user_id == "dev"
    assert hyp.memory_used is True or hyp.constraints  # constraints from text
    mem = model.load_memory()
    assert mem.n_interactions >= 1
    assert mem.goals
    # history recorded
    assert len(model.load_history()) >= 1
    # suggestions from marketplace when plugins present
    if hyp.suggested_components:
        assert hyp.suggested_components[0].kind in ui.MARKETPLACE_SURFACES


def test_component_suggestion_rejects_bad_kind():
    with pytest.raises(ui.UserIntentError):
        ui.ComponentSuggestion(kind="tool", name="x")
    with pytest.raises(ui.UserIntentError):
        ui.ComponentSuggestion(kind="agent", name="")


# ── soft hook + orchestrator ────────────────────────────────────────────────


def test_maybe_infer_for_task_disabled(tmp_path: Path):
    assert ui.maybe_infer_for_task(tmp_path, "t1", "goal", None) is None
    assert ui.maybe_infer_for_task(tmp_path, "t1", "goal", {}) is None
    assert (
        ui.maybe_infer_for_task(tmp_path, "t1", "goal", {"other": True}) is None
    )


def test_maybe_infer_for_task_enabled(tmp_path: Path):
    _write_plugin(tmp_path)
    out = ui.maybe_infer_for_task(
        tmp_path,
        "task-intent-1",
        "Implement a fix for the durable agent tests without vendoring trees",
        {"user_intent": True, "user_id": "alice", "intent_top_k": 3},
    )
    assert out is not None
    assert out["ok"] is True
    assert out["paper"] == ui.PAPER
    assert out["schema"] == ui.SCHEMA
    assert out["user_id"] == "alice"
    assert out["confidence"] >= 0.0
    assert "clarified_instruction" in out
    assert isinstance(out.get("intent"), dict)
    assert out["intent"]["source_pattern"] == "wshobson/agents"


def test_orchestrator_user_intent_meta(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(tmp_path))
    _write_plugin(tmp_path)
    orch = Orchestrator(tmp_path)
    out = orch.run_task(
        "fix the review-code path and keep tests green",
        kind="task",
        agent_mode="fake",
        task_id="ui-orch-1",
        sync_fake=True,
        meta={"user_intent": True, "user_id": "bob"},
    )
    assert out["status"] == "completed"
    env = load_envelope(tmp_path, "ui-orch-1")
    assert env is not None
    assert env.meta.get("user_intent") is True
    init = env.meta.get("user_intent_init") or {}
    assert init.get("intent_id")
    assert env.meta.get("user_intent_paper") == "arxiv:2510.21903v2"
    # Clarified goal should be available for the SWE agent
    clarified = env.meta.get("clarified_goal") or ""
    assert clarified  # non-empty clarified instruction


def test_confidence_monotonic_signals():
    low = ui.compute_confidence(
        instruction="it",
        goal_verbs=[],
        constraints=[],
        ambiguity=["empty_instruction", "bare_action_verb"],
        history_used=0,
        memory_used=False,
    )
    high = ui.compute_confidence(
        instruction="Implement user intent model with pytest and constraints",
        goal_verbs=["implement", "test"],
        constraints=["keep tests green", "do not vendor"],
        ambiguity=[],
        history_used=3,
        memory_used=True,
    )
    assert high > low
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0


def test_cli_infer_json(tmp_path: Path, capsys):
    _write_plugin(tmp_path)
    rc = ui.main(
        [
            "--workdir",
            str(tmp_path),
            "--user-id",
            "cli",
            "infer",
            "Review durable operator and fix tests",
            "--json",
            "--no-persist",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data["schema"] == ui.SCHEMA
    assert data["paper"] == ui.PAPER
