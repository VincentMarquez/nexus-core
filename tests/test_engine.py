from pathlib import Path

from nexus import DurableEngine, Settings, Task
from nexus.agents import AgentPanel, MockAgent
from nexus.engine import TaskStatus
from nexus.steps import StepDef, StepPolicy


def test_full_pipeline_completes(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="t1",
        objective="demo",
        success_criteria=["artifact contains DEMO_OK"],
        namespace="proj/demo",
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    assert task.current_step == 10
    assert (tmp_path / "state" / "tasks" / "t1.json").exists()


def test_resume_after_partial(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="t2",
        objective="demo resume",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task, max_steps=4)  # complete through step 4 only... wait
    # max_steps means stop when step.number > current + max_steps at start
    # After 0 completed, max_steps=4 allows steps 1..4
    assert task.current_step == 4
    assert task.status == TaskStatus.running
    task = engine.resume("t2")
    assert task.status == TaskStatus.completed
    assert task.current_step == 10


def test_autonomy_blocks_auto_created(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings)
    task = Task(task_id="auto1", objective="x", meta={"auto_created": True})
    task = engine.run(task)
    assert task.status == TaskStatus.failed
    assert "autonomy" in task.meta.get("error", "")


def test_handoff_events_when_agent_changes(tmp_path: Path):
    """Swarm-style handoff journal rows appear when resolve() switches agents."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="ho1",
        objective="handoff demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    events = engine.events("ho1")
    handoffs = [e for e in events if e.get("event") == "handoff"]
    assert handoffs, "expected at least one agent handoff in default pipeline"
    for h in handoffs:
        assert h.get("from_agent")
        assert h.get("to_agent")
        assert h["from_agent"] != h["to_agent"]


def test_journal_context_on_resume(tmp_path: Path):
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="jc1",
        objective="journal context",
        success_criteria=["artifact contains DEMO_OK"],
    )
    engine.run(task, max_steps=3)
    blk = engine.journal_context("jc1", limit=5)
    assert "RECENT TASK JOURNAL" in blk
    assert "step_start" in blk or "step_complete" in blk
    # limit 0 disables
    assert engine.journal_context("jc1", limit=0) == ""


def test_review_veto_fails_closed(tmp_path: Path):
    """Edict-style review reject hard-fails the task and records a veto event."""

    class RejectReviewer(MockAgent):
        def run(self, prompt: str, *, step, task):
            if step.name == "review":
                return {"findings": ["blocker"], "severity": "high", "verdict": "reject"}
            return super().run(prompt, step=step, task=task)

    panel = AgentPanel.demo()
    panel.agents["reviewer"] = RejectReviewer(name="reviewer", vendor="anthropic")
    panel.vendor_of["reviewer"] = "anthropic"

    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, panel=panel, auto_approve=True)
    task = Task(
        task_id="veto1",
        objective="should be vetoed",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.failed
    assert "veto" in task.meta.get("error", "").lower() or "reject" in task.meta.get("error", "")
    events = engine.events("veto1")
    assert any(e.get("event") == "veto" for e in events)
    assert any(e.get("event") == "failed" for e in events)
    # failed at review step (6), after implement+test
    assert task.current_step < 6 or 6 in task.outputs


def test_step_complete_records_why(tmp_path: Path):
    """Judge rationale is journaled as why on step_complete (CEMA audit)."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="why1",
        objective="why field demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task, max_steps=3)
    completes = [e for e in engine.events("why1") if e.get("event") == "step_complete"]
    assert completes, "expected step_complete events"
    # at least one complete should carry decision and/or why from the judge
    assert any(e.get("decision") for e in completes)
    # why may be empty for pure structural steps, but key must exist on judged steps
    with_why_key = [e for e in completes if "why" in e]
    assert with_why_key, "step_complete should include why field"


def test_replay_timeline_and_explain(tmp_path: Path):
    """replay() normalizes journal; explain() builds causal decision chain."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="rx1",
        objective="replay explain demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed

    timeline = engine.replay("rx1")
    assert timeline, "replay should return journal rows"
    assert timeline[0]["i"] == 0
    assert "event" in timeline[0]
    # completed marker present
    assert any(e.get("event") == "completed" for e in timeline)
    # handoff rows keep from/to
    handoff_rows = [e for e in timeline if e.get("event") == "handoff"]
    if handoff_rows:
        assert handoff_rows[0].get("from_agent")
        assert handoff_rows[0].get("to_agent")

    # limit tail works via events() path
    short = engine.replay("rx1", limit=3)
    assert len(short) <= 3

    rep = engine.explain("rx1")
    assert rep["found"] is True
    assert rep["status"] == "completed"
    assert rep["task_id"] == "rx1"
    assert rep["n_events"] >= 1
    assert rep["steps"], "explain should list completed steps"
    assert "COMPLETED" in rep["story"]
    # steps carry agent + decision when judged
    judged = [s for s in rep["steps"] if s.get("decision")]
    assert judged, "expected at least one judged step with decision"

    missing = engine.explain("does-not-exist")
    assert missing["found"] is False


def test_step_complete_score_tokens_and_cost(tmp_path: Path):
    """P3: judge score + token estimates journaled; cost() rolls them up."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="cost1",
        objective="cost rollup demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    assert int(task.meta.get("tokens_total") or 0) > 0

    completes = [e for e in engine.events("cost1") if e.get("event") == "step_complete"]
    assert completes
    with_tokens = [e for e in completes if e.get("tokens")]
    assert with_tokens, "step_complete should carry tokens"
    with_score = [e for e in completes if e.get("score") is not None]
    assert with_score, "step_complete should carry judge score"
    # value-system thresholds present on judged steps
    with_thr = [e for e in completes if isinstance(e.get("thresholds"), dict)]
    assert with_thr
    thr = with_thr[0]["thresholds"]
    assert thr.get("pass") == 0.7
    assert thr.get("revise") == 0.45

    rep = engine.cost("cost1")
    assert rep["found"] is True
    assert rep["total_tokens"] > 0
    assert rep["request_count"] >= 1
    assert rep["by_agent"]
    assert rep["avg_score"] is not None
    assert rep["thresholds"]["pass"] == 0.7

    explained = engine.explain("cost1")
    assert explained["cost"]["total_tokens"] == rep["total_tokens"]
    assert explained["cost"]["avg_score"] == rep["avg_score"]

    missing = engine.cost("nope")
    assert missing["found"] is False


def test_provenance_export(tmp_path: Path):
    """P4: PROV-AGENT style agents/activities/entities/relations export."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="prov1",
        objective="provenance export demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed

    doc = engine.provenance("prov1")
    assert doc["found"] is True
    assert doc["schema"] == "nexus.prov/v1"
    assert doc["status"] == "completed"
    assert doc["agents"], "expected at least one agent"
    assert doc["activities"], "expected step activities"
    assert any(a.get("id") for a in doc["activities"])
    assert doc["entities"]
    ent_types = {e.get("type") for e in doc["entities"]}
    assert "task" in ent_types
    assert "journal" in ent_types
    rel_types = {r.get("type") for r in doc["relations"]}
    assert "wasAssociatedWith" in rel_types
    assert "used" in rel_types
    assert "wasInformedBy" in rel_types
    assert doc["cost"]["total_tokens"] > 0
    assert "COMPLETED" in (doc.get("story") or "") or "completed" in doc["status"]

    missing = engine.provenance("nope")
    assert missing["found"] is False


def test_verify_checkpoint_journal_ok_and_drift(tmp_path: Path):
    """P4: verify() passes on healthy run; flags status/step drift."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="vfy1",
        objective="verify integrity demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed

    rep = engine.verify("vfy1")
    assert rep["found"] is True
    assert rep["ok"] is True
    assert rep["n_errors"] == 0
    assert rep["checks"].get("checkpoint_exists") is True
    assert rep["checks"].get("journal_exists") is True
    assert rep["checks"].get("status_alignment") is True
    assert rep["max_step_complete"] == task.current_step

    # Inject status drift: mark completed without completed event removed
    # (simulate checkpoint ahead of journal terminal)
    import json as _json

    tpath = settings.state_dir / "tasks" / "vfy1.json"
    data = _json.loads(tpath.read_text(encoding="utf-8"))
    data["status"] = "failed"
    data["meta"]["error"] = "injected drift"
    tpath.write_text(_json.dumps(data), encoding="utf-8")
    bad = engine.verify("vfy1")
    assert bad["ok"] is False
    codes = {i["code"] for i in bad["issues"]}
    assert "missing_failed_event" in codes

    missing = engine.verify("does-not-exist")
    assert missing["found"] is False
    assert missing["ok"] is False


def test_task_budget_hard_stop(tmp_path: Path):
    """P5: meta.max_tokens fails closed after overshoot (open-multi-agent shape)."""
    from nexus.engine import task_max_tokens

    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="bud1",
        objective="budget gate demo",
        success_criteria=["artifact contains DEMO_OK"],
        meta={"max_tokens": 1},  # tiny cap → fail after first step tokens
    )
    assert task_max_tokens(task) == 1
    task = engine.run(task)
    assert task.status == TaskStatus.failed
    assert task.meta.get("budget_exhausted") is True
    assert "budget exceeded" in (task.meta.get("error") or "")
    events = engine.events("bud1")
    assert any(e.get("event") == "budget" for e in events)
    assert any(e.get("event") == "failed" for e in events)
    # at least one step may have completed before overshoot
    assert task.current_step >= 1

    rep = engine.cost("bud1")
    assert rep["found"] is True
    assert rep["max_tokens"] == 1
    assert rep["budget_exhausted"] is True
    assert rep["remaining_tokens"] == 0

    # constraints form also resolves
    t2 = Task(task_id="x", objective="y", constraints=["max_tokens=42"])
    assert task_max_tokens(t2) == 42
    assert task_max_tokens(Task(task_id="z", objective="y")) is None


def test_call_graph_profile(tmp_path: Path):
    """P5: graph() builds agent nodes, handoff edges, and space-time sequence."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="g1",
        objective="call graph demo",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed

    g = engine.graph("g1")
    assert g["found"] is True
    assert g["schema"] == "nexus.graph/v1"
    assert g["n_agents"] >= 1
    assert g["nodes"]
    assert any(n.get("n_completes", 0) > 0 for n in g["nodes"])
    # default multi-agent pipeline should hand off at least once
    assert g["n_handoffs"] >= 1
    assert g["edges"]
    for e in g["edges"]:
        assert e.get("from") and e.get("to") and e.get("kind") == "handoff"
    assert g["sequence"]
    assert any(s.get("event") == "step_complete" for s in g["sequence"])
    assert "flowchart" in (g.get("mermaid") or "")
    assert g["cost"]["total_tokens"] > 0

    missing = engine.graph("nope")
    assert missing["found"] is False

