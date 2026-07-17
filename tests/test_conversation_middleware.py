"""Tests for config-driven conversation middleware (labsai/EDDI shape)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import conversation_middleware as cm


# ── expressions ──────────────────────────────────────────────────────────────


def test_parse_expressions_dictionary():
    d = {"greeting": ["hello", "hi"], "support": ["help", "problem"]}
    assert cm.parse_expressions("Hello world", dictionary=d) == [
        "greeting(hello)"
    ]
    assert "support(problem)" in cm.parse_expressions(
        "I have a problem", dictionary=d
    )
    # empty input
    assert cm.parse_expressions("", dictionary=d) == []


def test_match_expression_wildcard_and_exact():
    exprs = ["greeting(hello)", "support(help)"]
    assert cm.match_expression("greeting(*)", exprs)
    assert cm.match_expression("greeting(hello)", exprs)
    assert not cm.match_expression("greeting(hi)", exprs)
    assert cm.match_expression("greeting(*),billing(*)", exprs)  # OR
    assert cm.match_expression("greeting", exprs)  # bare type
    assert not cm.match_expression("billing(*)", exprs)
    assert not cm.match_expression("", exprs)
    # case-insensitive type + commas inside parentheses stay one pattern
    assert cm.match_expression("Greeting(*)", exprs)
    assert cm.match_expression("weather(city,date)", ["weather(city,date)"])
    assert not cm.match_expression("weather(city,date)", ["weather(city)"])


# ── memory ───────────────────────────────────────────────────────────────────


def test_conversation_memory_scopes_and_roundtrip():
    mem = cm.ConversationMemory(conversation_id="c1", user_id="u1")
    mem.begin_step("hi")
    mem.set_prop("tmp", 1, scope=cm.SCOPE_STEP)
    mem.set_prop("pref", "dark", scope=cm.SCOPE_CONVERSATION)
    mem.set_prop("locale", "en", scope=cm.SCOPE_LONG_TERM)
    assert mem.get_prop("tmp", scope=cm.SCOPE_STEP) == 1
    assert mem.get_prop("pref") == "dark"
    assert mem.get_prop("locale", scope=cm.SCOPE_LONG_TERM) == "en"
    # search order
    assert mem.get_prop("pref") == "dark"
    mem.current.expressions = ["greeting(hi)"]
    mem.current.actions = ["greet"]
    mem.current.outputs = ["Hello"]
    mem.commit_step()
    assert len(mem.steps) == 1
    assert mem.state == cm.STATE_READY
    back = cm.ConversationMemory.from_dict(mem.to_dict())
    assert back.conversation_id == "c1"
    assert back.conversation_props["pref"] == "dark"
    assert back.long_term_props["locale"] == "en"
    assert back.steps[0].expressions == ["greeting(hi)"]


def test_memory_ended_rejects_new_step():
    mem = cm.ConversationMemory(conversation_id="c2", state=cm.STATE_ENDED)
    with pytest.raises(cm.MiddlewareError, match="ended"):
        mem.begin_step("hi")


def test_memory_set_prop_validation():
    mem = cm.ConversationMemory(conversation_id="c3")
    with pytest.raises(cm.MiddlewareError, match="key"):
        mem.set_prop("", "x")
    with pytest.raises(cm.MiddlewareError, match="scope"):
        mem.set_prop("k", "v", scope="galaxy")
    with pytest.raises(cm.MiddlewareError, match="no current step"):
        mem.set_prop("k", "v", scope=cm.SCOPE_STEP)


# ── conditions / rules ───────────────────────────────────────────────────────


def test_inputmatcher_and_negation():
    mem = cm.ConversationMemory(conversation_id="c4")
    mem.begin_step("hello")
    mem.current.expressions = ["greeting(hello)"]
    cond = {
        "type": "inputmatcher",
        "configs": {"expressions": "greeting(*)", "occurrence": "currentStep"},
    }
    assert cm.evaluate_condition(cond, mem) is True
    neg = {"type": "negation", "conditions": [cond]}
    assert cm.evaluate_condition(neg, mem) is False


def test_contextmatcher_and_connector():
    mem = cm.ConversationMemory(
        conversation_id="c5",
        context={"userInfo": {"username": "ada"}},
    )
    mem.begin_step("x")
    ok = {
        "type": "contextmatcher",
        "configs": {
            "contextKey": "userInfo",
            "objectKeyPath": "username",
        },
    }
    assert cm.evaluate_condition(ok, mem) is True
    missing = {
        "type": "contextmatcher",
        "configs": {"contextKey": "missing"},
    }
    assert cm.evaluate_condition(missing, mem) is False
    both = {
        "type": "connector",
        "configs": {"operator": "and"},
        "conditions": [ok, missing],
    }
    assert cm.evaluate_condition(both, mem) is False
    either = {
        "type": "connector",
        "configs": {"operator": "or"},
        "conditions": [ok, missing],
    }
    assert cm.evaluate_condition(either, mem) is True


def test_behavior_group_first_match_wins():
    g = cm.BehaviorGroup.from_dict(
        {
            "name": "G",
            "behaviorRules": [
                {
                    "name": "A",
                    "actions": ["a"],
                    "conditions": [
                        {
                            "type": "inputmatcher",
                            "configs": {"expressions": "greeting(*)"},
                        }
                    ],
                },
                {
                    "name": "B",
                    "actions": ["b"],
                    "conditions": [
                        {
                            "type": "inputmatcher",
                            "configs": {"expressions": "greeting(*)"},
                        }
                    ],
                },
            ],
        }
    )
    mem = cm.ConversationMemory(conversation_id="c6")
    mem.begin_step("hi")
    mem.current.expressions = ["greeting(hi)"]
    rule = g.evaluate(mem)
    assert rule is not None
    assert rule.name == "A"
    assert rule.actions == ["a"]


def test_unknown_condition_type_raises():
    mem = cm.ConversationMemory(conversation_id="c7")
    mem.begin_step("x")
    with pytest.raises(cm.MiddlewareError, match="unknown condition"):
        cm.evaluate_condition({"type": "not_a_real_type"}, mem)


# ── bot config ───────────────────────────────────────────────────────────────


def test_default_bot_config_validates():
    cfg = cm.default_bot_config()
    assert cfg.schema == cm.SCHEMA
    assert cfg.validate() == []
    d = cfg.to_dict()
    assert d["source_pattern"] == cm.SOURCE_PATTERN
    back = cm.BotConfig.from_dict(d)
    assert back.id == cfg.id
    assert "support" in back.agents
    assert "route_support" in back.actions


def test_config_validate_unknown_route_and_action():
    cfg = cm.BotConfig.from_dict(
        {
            "id": "bad",
            "actions": {
                "go": {"kind": "route", "agent": "ghost"},
                "fallback": "sorry",
            },
            "behaviorGroups": [
                {
                    "name": "G",
                    "behaviorRules": [
                        {
                            "name": "R",
                            "actions": ["missing_action"],
                            "conditions": [],
                        }
                    ],
                }
            ],
        }
    )
    problems = cfg.validate()
    assert any("missing_action" in p for p in problems)
    assert any("ghost" in p for p in problems)
    with pytest.raises(cm.MiddlewareError, match="invalid bot config"):
        cm.ConversationEngine(cfg, strict=True)


def test_config_validate_fallback_default_agent_and_conditions():
    """Fail-closed: undefined fallback/default_agent/condition types at load."""
    cfg = cm.BotConfig.from_dict(
        {
            "id": "bad2",
            "fallback_action": "nope_not_defined",
            "default_agent": "ghost_agent",
            "agents": {"a": {"id": "a", "capabilities": ["route"]}},
            "actions": {"say": {"kind": "reply", "text": "hi"}},
            "behaviorGroups": [
                {
                    "name": "G",
                    "behaviorRules": [
                        {
                            "name": "R",
                            "actions": ["say"],
                            "conditions": [{"type": "llm_judge", "configs": {}}],
                        }
                    ],
                }
            ],
        }
    )
    problems = cfg.validate()
    assert any("fallback_action" in p and "nope_not_defined" in p for p in problems)
    assert any("default_agent" in p and "ghost_agent" in p for p in problems)
    assert any("unknown condition type" in p and "llm_judge" in p for p in problems)
    with pytest.raises(cm.MiddlewareError, match="invalid bot config"):
        cm.ConversationEngine(cfg, strict=True)


def test_load_bot_config_json(tmp_path: Path):
    cfg = cm.default_bot_config()
    path = tmp_path / "bot.json"
    path.write_text(json.dumps(cfg.to_dict()), encoding="utf-8")
    loaded = cm.load_bot_config(path)
    assert loaded.id == cfg.id
    with pytest.raises(cm.MiddlewareError, match="not found"):
        cm.load_bot_config(tmp_path / "nope.json")


def test_action_def_unknown_kind():
    with pytest.raises(cm.MiddlewareError, match="unknown action kind"):
        cm.ActionDef.from_dict("x", {"kind": "teleport"})


# ── engine lifecycle ─────────────────────────────────────────────────────────


def test_engine_greeting_and_fallback():
    eng = cm.ConversationEngine(cm.default_bot_config())
    # first message triggers Welcome (occurrence max 0)
    r1 = eng.process("hello", conversation_id="t1")
    assert r1.state == cm.STATE_READY
    assert "Welcome" in " ".join(r1.outputs)
    assert "welcome" in r1.actions
    # unknown intent → fallback
    r2 = eng.process("zzzz not a word", conversation_id="t1")
    assert r2.actions == ["fallback"]
    assert "understand" in " ".join(r2.outputs).lower() or r2.outputs


def test_engine_support_routes_mcp_and_memory():
    eng = cm.ConversationEngine(cm.default_bot_config())
    eng.process("hi", conversation_id="t2")  # welcome
    r = eng.process("I have a problem", conversation_id="t2")
    assert "route_support" in r.actions
    assert r.routed_to == "support"
    assert any(o.get("kind") == "mcp" for o in r.orchestrations)
    snap = eng.snapshot("t2")
    mem = snap["memory"]
    assert mem["conversation_props"].get("last_topic") == "support"
    assert mem["agent_id"] == "support"


def test_engine_billing_openapi_dry_run():
    eng = cm.ConversationEngine(cm.default_bot_config())
    r = eng.process("need my invoice please", conversation_id="t3")
    assert "route_billing" in r.actions
    assert r.routed_to == "billing"
    assert any(
        o.get("kind") == "openapi" and o.get("result", {}).get("dry_run")
        for o in r.orchestrations
    )


def test_engine_goodbye_ends_conversation():
    eng = cm.ConversationEngine(cm.default_bot_config())
    # First-turn goodbye must win over Welcome (Goodbye ordered first)
    r0 = eng.process("bye", conversation_id="t4a")
    assert r0.state == cm.STATE_ENDED
    assert "say_goodbye" in r0.actions
    assert r0.outputs == ["Goodbye! Conversation ended."]

    eng2 = cm.ConversationEngine(cm.default_bot_config())
    eng2.process("hello", conversation_id="t4")
    r = eng2.process("goodbye", conversation_id="t4")
    assert r.state == cm.STATE_ENDED
    assert "say_goodbye" in r.actions
    assert "Goodbye" in " ".join(r.outputs)
    with pytest.raises(cm.MiddlewareError, match="ended"):
        eng2.process("hello again", conversation_id="t4")


def test_engine_custom_handler_and_long_term():
    cfg = cm.default_bot_config()
    eng = cm.ConversationEngine(cfg)
    eng.action_handlers["greet"] = lambda mem, conf: {
        "text": f"Custom hi {mem.user_id}"
    }
    # force greeting rule on non-first turn: seed a welcome first
    eng.process("noise", conversation_id="t5", user_id="ada")
    r = eng.process("hello", conversation_id="t5", user_id="ada")
    assert any("Custom hi ada" in o for o in r.outputs)

    # longTerm write-through: set in conv A, visible in B without hand-seeding
    eng.process("noise", conversation_id="t5a", user_id="ada")
    mem_a = eng.get_or_create("t5a", user_id="ada")
    mem_a.set_prop("loyalty", "gold", scope=cm.SCOPE_LONG_TERM)
    # process any turn so engine keeps running; store already shared
    eng.process("zzzz", conversation_id="t5a", user_id="ada")
    assert eng.long_term_store["ada"].get("loyalty") == "gold"

    # interleaved conv B must not clobber longTerm from A
    eng.process("noise", conversation_id="t5b", user_id="ada")
    assert eng.long_term_store["ada"].get("loyalty") == "gold"
    mem_b = eng.get_or_create("t5b", user_id="ada")
    assert mem_b.long_term_props.get("loyalty") == "gold"
    mem_b.set_prop("tier", "1", scope=cm.SCOPE_LONG_TERM)
    eng.process("zzzz", conversation_id="t5b", user_id="ada")
    # A still sees B's update (shared store)
    assert eng.get_or_create("t5a", user_id="ada").long_term_props.get("tier") == "1"
    assert eng.long_term_store["ada"] == {"loyalty": "gold", "tier": "1"}


def test_engine_fail_closed_missing_route():
    cfg = cm.BotConfig.from_dict(
        {
            "id": "x",
            "default_agent": "a",
            "agents": {"a": {"id": "a", "capabilities": ["route"]}},
            "actions": {
                "go": {"kind": "route", "agent": "a", "text": "ok"},
                "fallback": "sorry",
            },
            "behaviorGroups": [
                {
                    "name": "G",
                    "behaviorRules": [
                        {
                            "name": "Always",
                            "actions": ["go"],
                            "conditions": [],
                        }
                    ],
                }
            ],
        }
    )
    # mutate after validate to inject bad target
    eng = cm.ConversationEngine(cfg, strict=True)
    eng.config.actions["go"].config["agent"] = "missing"
    with pytest.raises(cm.MiddlewareError, match="not in config"):
        eng.process("anything", conversation_id="fail1")
    # failed step is audited
    mem = eng.memories["fail1"]
    assert mem.state == cm.STATE_ERROR
    assert mem.current is None
    assert len(mem.steps) == 1
    assert "error" in mem.steps[0].data


def test_handoff_requires_known_agent():
    cfg = cm.BotConfig.from_dict(
        {
            "id": "h",
            "default_agent": "a",
            "agents": {
                "a": {"id": "a"},
                "b": {"id": "b"},
            },
            "actions": {
                "pass": {
                    "kind": "handoff",
                    "agent": "b",
                    "memory_keys": ["topic"],
                    "text": "passed",
                },
                "fallback": "nope",
            },
            "behaviorGroups": [
                {
                    "name": "G",
                    "behaviorRules": [
                        {
                            "name": "H",
                            "actions": ["pass"],
                            "conditions": [],
                        }
                    ],
                }
            ],
        }
    )
    eng = cm.ConversationEngine(cfg)
    mem = eng.get_or_create("h1")
    mem.conversation_props["topic"] = "billing"
    r = eng.process("go", conversation_id="h1")
    assert r.routed_to == "b"
    hand = next(o for o in r.orchestrations if o["kind"] == "handoff")
    assert hand["result"]["memory_keys"]["topic"] == "billing"


def test_capability_gate_mcp_requires_agent_capability():
    cfg = cm.BotConfig.from_dict(
        {
            "id": "cap",
            "default_agent": "triage",
            "agents": {
                "triage": {
                    "id": "triage",
                    "capabilities": ["route"],  # no mcp
                }
            },
            "actions": {
                "ticket": {
                    "kind": "mcp",
                    "tool": "create_ticket",
                    "text": "ticket",
                },
                "fallback": "nope",
            },
            "behaviorGroups": [
                {
                    "name": "G",
                    "behaviorRules": [
                        {
                            "name": "Always",
                            "actions": ["ticket"],
                            "conditions": [],
                        }
                    ],
                }
            ],
        }
    )
    eng = cm.ConversationEngine(cfg)
    with pytest.raises(cm.MiddlewareError, match="lacks capability"):
        eng.process("go", conversation_id="cap1")


def test_conversation_ownership_rejects_cross_user():
    eng = cm.ConversationEngine(cm.default_bot_config())
    eng.process("hello", conversation_id="own1", user_id="alice")
    with pytest.raises(cm.MiddlewareError, match="belongs to user"):
        eng.process("hello", conversation_id="own1", user_id="bob")


def test_demo_turns_and_main(capsys, tmp_path: Path):
    turns = cm.demo_turns()
    assert len(turns) >= 4
    assert turns[0]["schema"] == cm.SCHEMA
    assert "snapshot" in turns[-1]
    # ending turn keeps farewell in outputs
    ended = [t for t in turns[:-1] if t.get("state") == cm.STATE_ENDED]
    assert ended
    assert any("Goodbye" in o for o in ended[-1].get("outputs") or [])

    assert cm.main(["config"]) == 0
    out = capsys.readouterr().out
    assert cm.SCHEMA in out or "demo-support" in out
    assert cm.main(["turn", "hello"]) == 0
    assert cm.main(["demo"]) == 0
    assert cm.main(["help"]) == 0
    # unknown command fails loudly
    assert cm.main(["cofnig"]) == 2
    # --config path works
    path = tmp_path / "bot.json"
    path.write_text(json.dumps(cm.default_bot_config().to_dict()), encoding="utf-8")
    assert cm.main(["config", "--config", str(path)]) == 0


def test_schema_constants():
    assert cm.SCHEMA == "nexus.conversation_middleware/v1"
    assert cm.SOURCE_PATTERN == "labsai/EDDI"
    assert cm.TASK_PARSE in cm.DEFAULT_LIFECYCLE
    assert "TASK_PARSE" in cm.__all__
    assert "KNOWN_CONDITION_TYPES" in cm.__all__
    assert "mcp" in cm.ACTION_KINDS
    assert "openapi" in cm.ACTION_KINDS
    assert "inputmatcher" in cm.KNOWN_CONDITION_TYPES
