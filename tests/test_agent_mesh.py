"""Tests for in-process agent mesh (SolaceLabs/solace-agent-mesh shape)."""

from __future__ import annotations

import json
import time

import pytest

from nexus import agent_mesh as am


# ── topics ───────────────────────────────────────────────────────────────────


def test_topic_helpers_namespace_scoped():
    assert am.mesh_base_topic("nexus") == "nexus/mesh/v1"
    assert am.discovery_topic("lab") == "lab/mesh/v1/discovery/agentcards"
    assert am.agent_request_topic("researcher", namespace="lab").endswith(
        "/agent/request/researcher"
    )
    assert "status/worker/t1" in am.agent_status_topic("worker", "t1", namespace="lab")
    assert "response/worker/t1" in am.agent_response_topic(
        "worker", "t1", namespace="lab"
    )
    assert am.system_event_topic("heartbeat").endswith("/events/heartbeat")


def test_topic_sanitize_rejects_empty_and_path_tricks():
    with pytest.raises(am.MeshError):
        am.mesh_base_topic("")
    with pytest.raises(am.MeshError):
        am.agent_request_topic("../evil")
    with pytest.raises(am.MeshError):
        am.agent_request_topic("bad name")
    # Single-level only: slash would spoof topic hierarchy
    with pytest.raises(am.MeshError):
        am.agent_request_topic("worker/evil")
    with pytest.raises(am.MeshError):
        am.AgentCard(name="a/b", capabilities=["x"])
    # Dots/underscores still allowed for single-level names
    assert am.agent_request_topic("worker.v2").endswith("/request/worker.v2")


def test_topic_match_solace_wildcards():
    assert am.topic_match("nexus/mesh/v1/agent/request/*", "nexus/mesh/v1/agent/request/a")
    assert not am.topic_match(
        "nexus/mesh/v1/agent/request/*", "nexus/mesh/v1/agent/request/a/b"
    )
    assert am.topic_match("nexus/mesh/v1/>", "nexus/mesh/v1/discovery/agentcards")
    assert am.topic_match("a/*/c", "a/b/c")
    assert not am.topic_match("a/*/c", "a/b/x")
    assert am.topic_match("a/>", "a/b/c/d")
    assert not am.topic_match("", "a")
    # `>` only valid as final segment — pattern with mid `>` does not match
    assert not am.topic_match("a/>/c", "a/b/c")
    # Solace: `>` needs ≥1 trailing level (zero-tail must not match)
    assert not am.topic_match("a/b/>", "a/b")
    assert not am.topic_match("a/>", "a")
    assert am.topic_match("a/b/>", "a/b/c")


# ── agent card / registry ────────────────────────────────────────────────────


def test_agent_card_normalize_and_capability():
    c = am.AgentCard(
        name="  scout  ",
        capabilities=["Research", " code ", ""],
        skills=["s1", ""],
    )
    assert c.name == "scout"
    assert c.capabilities == ["research", "code"]
    assert c.has_capability("RESEARCH")
    assert not c.has_capability("")
    back = am.AgentCard.from_dict(c.to_dict())
    assert back.name == "scout"
    assert back.capabilities == ["research", "code"]


def test_agent_card_requires_name():
    with pytest.raises(am.MeshError):
        am.AgentCard(name="")


def test_registry_add_ttl_expire_and_find():
    reg = am.AgentRegistry(ttl_s=0.05)
    assert reg.add_or_update(am.AgentCard(name="a", capabilities=["x"])) is True
    assert reg.add_or_update(am.AgentCard(name="a", capabilities=["x", "y"])) is False
    assert reg.get("a") is not None
    assert reg.names() == ["a"]
    assert [c.name for c in reg.find_by_capability("y")] == ["a"]

    reg.add_or_update(am.AgentCard(name="b", capabilities=["x"]))
    assert reg.heartbeat("b") is True
    assert reg.heartbeat("missing") is False

    time.sleep(0.07)
    # a expired unless heartbeated; heartbeat b before expire check
    reg.heartbeat("b")
    removed = reg.expire_stale()
    assert "a" in removed
    assert reg.get("a") is None
    assert reg.get("b") is not None

    exp, age = reg.check_ttl("missing")
    assert exp is True and age == 0.0


def test_registry_on_added_removed_callbacks():
    added: list[str] = []
    removed: list[str] = []
    reg = am.AgentRegistry(
        ttl_s=90,
        on_added=lambda c: added.append(c.name),
        on_removed=lambda n: removed.append(n),
    )
    reg.add_or_update(am.AgentCard(name="x", capabilities=["k"]))
    reg.remove("x")
    assert added == ["x"]
    assert removed == ["x"]


# ── mesh pub/sub ─────────────────────────────────────────────────────────────


def test_publish_subscribe_and_history():
    mesh = am.AgentMesh(namespace="test")
    seen: list[str] = []

    mesh.subscribe("test/mesh/v1/events/>", lambda e: seen.append(e.kind))
    mesh.publish(
        am.MeshEvent(
            kind=am.KIND_SYSTEM,
            topic=am.system_event_topic("boot", namespace="test"),
            source="core",
            payload={"msg": "hi"},
        )
    )
    assert seen == [am.KIND_SYSTEM]
    hist = mesh.history(kind=am.KIND_SYSTEM)
    assert len(hist) == 1
    assert hist[0].payload["msg"] == "hi"
    assert hist[0].to_dict()["schema"] == am.SCHEMA


def test_announce_registers_and_emits_discovery():
    mesh = am.AgentMesh()
    disc: list[am.MeshEvent] = []
    mesh.subscribe(mesh.discovery_topic(), lambda e: disc.append(e))
    card = am.AgentCard(name="planner", capabilities=["plan"])
    evt = mesh.announce(card)
    assert evt.kind == am.KIND_DISCOVERY
    assert mesh.registry.get("planner") is not None
    assert len(disc) == 1
    assert disc[0].payload["card"]["name"] == "planner"
    assert disc[0].payload["is_new"] is True
    # re-announce is update
    evt2 = mesh.announce(card)
    assert evt2.payload["is_new"] is False


def test_bind_agent_request_auto_responds():
    mesh = am.AgentMesh()

    def handler(evt: am.MeshEvent) -> dict:
        return {"ok": True, "echo": evt.payload.get("q")}

    mesh.bind_agent(
        am.AgentCard(name="echo", capabilities=["echo"]),
        handler,
    )
    req = mesh.request("echo", {"q": "ping"}, from_agent="caller", task_id="t-1")
    assert req.kind == am.KIND_REQUEST
    reply = mesh.get_reply(req.correlation_id)
    assert reply is not None
    assert reply.kind == am.KIND_RESPONSE
    assert reply.payload["echo"] == "ping"
    assert reply.payload["ok"] is True
    assert reply.task_id == "t-1"


def test_status_and_respond_topics():
    mesh = am.AgentMesh(namespace="n")
    st = mesh.status("worker", "tid", {"pct": 50}, correlation_id="c1")
    assert st.kind == am.KIND_STATUS
    assert st.topic == am.agent_status_topic("worker", "tid", namespace="n")
    assert st.payload["is_final"] is False
    rsp = mesh.respond("worker", "tid", {"result": 1}, correlation_id="c1", ok=True)
    assert rsp.kind == am.KIND_RESPONSE
    assert mesh.get_reply("c1") is rsp


def test_delegate_routes_by_capability():
    mesh = am.AgentMesh()
    mesh.bind_agent(
        am.AgentCard(name="r1", capabilities=["research"]),
        lambda e: {"ok": True, "who": "r1"},
    )
    mesh.bind_agent(
        am.AgentCard(name="i1", capabilities=["implement", "code"]),
        lambda e: {"ok": True, "who": "i1"},
    )
    out = mesh.delegate("research", {"query": "mesh"})
    assert out["ok"] is True
    assert out["peer"] == "r1"
    assert out["schema"] == am.SCHEMA
    assert out["response"]["payload"]["who"] == "r1"

    out2 = mesh.delegate("code", {"objective": "x"}, prefer="i1")
    assert out2["ok"] is True
    assert out2["peer"] == "i1"


def test_delegate_no_peer_fail_closed():
    mesh = am.AgentMesh()
    mesh.bind_agent(
        am.AgentCard(name="only-code", capabilities=["code"]),
        lambda e: {"ok": True},
    )
    out = mesh.delegate("research", {"query": "x"})
    assert out["ok"] is False
    assert out["peer"] is None
    assert "no healthy peer" in (out["error"] or "")


def test_delegate_exclude_and_empty_capability():
    mesh = am.AgentMesh()
    mesh.bind_agent(
        am.AgentCard(name="a", capabilities=["x"]),
        lambda e: {"ok": True, "who": "a"},
    )
    mesh.bind_agent(
        am.AgentCard(name="b", capabilities=["x"]),
        lambda e: {"ok": True, "who": "b"},
    )
    out = mesh.delegate("x", {}, exclude=["a"])
    assert out["ok"] is True
    assert out["peer"] == "b"
    bad = mesh.delegate("", {})
    assert bad["ok"] is False
    assert "capability is required" in (bad["error"] or "")


def test_heartbeat_and_snapshot():
    mesh = am.AgentMesh(namespace="snap")
    mesh.announce(am.AgentCard(name="alive", capabilities=["ping"]))
    assert mesh.heartbeat("alive") is True
    assert mesh.heartbeat("ghost") is False
    snap = mesh.snapshot()
    assert snap["schema"] == am.SCHEMA
    assert snap["source_pattern"] == am.SOURCE_PATTERN
    assert snap["namespace"] == "snap"
    assert snap["base_topic"] == "snap/mesh/v1"
    assert snap["registry"]["n_agents"] == 1
    assert "alive" in snap["registry"]["agents"]
    assert snap["n_history"] >= 2  # discovery + heartbeat


def test_handler_exception_does_not_break_mesh():
    mesh = am.AgentMesh()

    def boom(_evt: am.MeshEvent) -> None:
        raise RuntimeError("handler blew up")

    mesh.subscribe(mesh.discovery_topic(), boom)
    # should not raise
    mesh.announce(am.AgentCard(name="x", capabilities=["y"]))
    assert mesh.registry.get("x") is not None


def test_history_capped():
    mesh = am.AgentMesh(max_history=5)
    for i in range(12):
        mesh.publish(
            am.MeshEvent(
                kind=am.KIND_SYSTEM,
                topic=am.system_event_topic("tick", namespace=mesh.namespace),
                source="core",
                payload={"i": i},
            )
        )
    assert len(mesh.history(limit=100)) == 5
    assert mesh.history(limit=100)[-1].payload["i"] == 11


def test_replies_capped_like_history():
    mesh = am.AgentMesh(max_history=5, max_replies=5)
    for i in range(12):
        mesh.respond("w", f"t{i}", {"i": i}, correlation_id=f"c{i}")
    with mesh._lock:
        n = len(mesh._replies)
    assert n == 5
    assert mesh.get_reply("c0") is None  # oldest evicted
    assert mesh.get_reply("c11") is not None


def test_injected_registry_ttl_not_clobbered():
    reg = am.AgentRegistry(ttl_s=30.0)
    mesh = am.AgentMesh(registry=reg)
    assert mesh.registry.ttl_s == 30.0
    assert mesh.ttl_s == 30.0  # mesh adopts registry when registry is explicit


def test_mesh_ttl_pushed_when_registry_default():
    mesh = am.AgentMesh(ttl_s=12.0)
    assert mesh.registry.ttl_s == 12.0


def test_bind_agent_ignores_non_request_kinds():
    mesh = am.AgentMesh()
    hits: list[str] = []

    def handler(evt: am.MeshEvent) -> dict:
        hits.append(evt.kind)
        return {"ok": True}

    mesh.bind_agent(am.AgentCard(name="echo", capabilities=["echo"]), handler)
    # Status event on the request topic must not invoke the request handler
    mesh.publish(
        am.MeshEvent(
            kind=am.KIND_STATUS,
            topic=am.agent_request_topic("echo"),
            source="attacker",
            target="echo",
            payload={"pct": 1},
        )
    )
    assert hits == []
    # Real request still works
    mesh.request("echo", {"q": 1}, task_id="t1")
    assert hits == [am.KIND_REQUEST]


def test_expired_agent_stops_auto_responding():
    mesh = am.AgentMesh(ttl_s=0.05)
    mesh.bind_agent(
        am.AgentCard(name="short", capabilities=["x"]),
        lambda e: {"ok": True, "who": "short"},
    )
    assert mesh.delegate("x", {})["ok"] is True
    time.sleep(0.07)
    removed = mesh.registry.expire_stale()
    assert "short" in removed
    # Zombie handler must be gone — direct request yields no reply
    req = mesh.request("short", {"q": 1}, task_id="after-expire")
    assert mesh.get_reply(req.correlation_id) is None
    out = mesh.delegate("x", {})
    assert out["ok"] is False


def test_rebind_replaces_handler_not_stacks():
    mesh = am.AgentMesh()
    calls: list[str] = []

    mesh.bind_agent(
        am.AgentCard(name="w", capabilities=["x"]),
        lambda e: calls.append("a") or {"ok": True, "v": "a"},
    )
    mesh.bind_agent(
        am.AgentCard(name="w", capabilities=["x"]),
        lambda e: calls.append("b") or {"ok": True, "v": "b"},
    )
    out = mesh.delegate("x", {})
    assert out["ok"] is True
    assert out["response"]["payload"]["v"] == "b"
    assert calls == ["b"]


def test_unbind_agent_drops_subscription():
    mesh = am.AgentMesh()
    mesh.bind_agent(
        am.AgentCard(name="u", capabilities=["x"]),
        lambda e: {"ok": True},
    )
    assert mesh.unbind_agent("u") is True
    assert mesh.registry.get("u") is None
    req = mesh.request("u", {}, task_id="t-unbound")
    assert mesh.get_reply(req.correlation_id) is None


def test_handler_error_recorded_in_history():
    mesh = am.AgentMesh()

    def boom(_evt: am.MeshEvent) -> None:
        raise RuntimeError("boom")

    mesh.subscribe(mesh.discovery_topic(), boom)
    mesh.announce(am.AgentCard(name="x", capabilities=["y"]))
    errs = [
        e
        for e in mesh.history(kind=am.KIND_SYSTEM, limit=50)
        if (e.payload or {}).get("where") == "publish.handler"
    ]
    assert len(errs) >= 1
    assert "boom" in str(errs[-1].payload.get("error"))


def test_request_and_wait_returns_inline_reply():
    mesh = am.AgentMesh()
    mesh.bind_agent(
        am.AgentCard(name="echo", capabilities=["echo"]),
        lambda e: {"ok": True, "echo": e.payload.get("q")},
    )
    reply = mesh.request_and_wait("echo", {"q": "hi"}, timeout=1.0, task_id="t-wait")
    assert reply is not None
    assert reply.payload["echo"] == "hi"
    # Missing peer → timeout None
    assert mesh.request_and_wait("ghost", {}, timeout=0.05) is None


def test_build_demo_mesh_and_main_demo(capsys):
    mesh = am.build_demo_mesh()
    assert set(mesh.registry.names()) == {"implementer", "researcher", "tester"}
    r = mesh.delegate("research", {"query": "solace"})
    assert r["ok"] and r["peer"] == "researcher"
    i = mesh.delegate("implement", {"objective": "port pattern"})
    assert i["ok"] and i["peer"] == "implementer"
    t = mesh.delegate("test", {})
    assert t["ok"] and t["peer"] == "tester"

    rc = am.main(["demo"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["schema"] == am.SCHEMA
    assert len(out["steps"]) == 3

    rc2 = am.main(["topics"])
    assert rc2 == 0
    topics_out = capsys.readouterr().out
    assert "discovery" in topics_out

    rc3 = am.main(["snapshot"])
    assert rc3 == 0
    snap = json.loads(capsys.readouterr().out)
    assert snap["n_subscriptions"] >= 3


def test_cli_mesh_subcommand(capsys):
    from nexus.cli import main as cli_main

    rc = cli_main(["mesh", "topics"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "discovery" in out
    assert "mesh/v1" in out

    rc2 = cli_main(["mesh", "demo"])
    assert rc2 == 0
    demo = json.loads(capsys.readouterr().out)
    assert demo["ok"] is True
    assert demo["schema"] == am.SCHEMA
