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


def test_task_max_steps_hard_stop(tmp_path: Path):
    """P10: meta.max_steps fail-closed (durability RunBudget / cycgraph shape)."""
    from nexus.engine import task_max_steps, task_run_budget

    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="ms1",
        objective="step budget demo",
        success_criteria=["artifact contains DEMO_OK"],
        meta={"max_steps": 2},
    )
    assert task_max_steps(task) == 2
    b = task_run_budget(task)
    assert b.max_steps == 2
    task = engine.run(task)
    assert task.status == TaskStatus.failed
    assert task.meta.get("budget_exhausted") is True
    assert "step budget exceeded" in (task.meta.get("error") or "")
    assert task.current_step == 2  # completed 2 steps then refused 3rd
    events = engine.events("ms1")
    assert any(e.get("event") == "budget" and e.get("kind") == "steps" for e in events)

    # soft run(max_steps=) still leaves running (unchanged contract)
    t_soft = Task(
        task_id="ms2",
        objective="soft stop",
        success_criteria=["artifact contains DEMO_OK"],
    )
    t_soft = engine.run(t_soft, max_steps=2)
    assert t_soft.status == TaskStatus.running
    assert t_soft.current_step == 2

    # constraints form
    assert task_max_steps(Task(task_id="c", objective="y", constraints=["max_steps=3"])) == 3


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


def test_task_norms_parse():
    """P6: constraints/meta → structured norms (NorMAS light)."""
    from nexus.engine import task_norms

    t = Task(
        task_id="n1",
        objective="norms",
        constraints=[
            "require:tests",
            "deny:network",
            "must:review",
            "max_tokens=900",
            "keep artifacts small",
        ],
        meta={"require_human": True},
    )
    n = task_norms(t)
    assert n["max_tokens"] == 900
    assert "tests" in n["require"]
    assert "review" in n["require"]
    assert "human" in n["require"]
    assert "network" in n["deny"]
    kinds = {r["kind"] for r in n["rules"]}
    assert "budget" in kinds
    assert "require" in kinds
    assert "deny" in kinds
    assert "constraint" in kinds
    assert n["n_rules"] >= 5

    # meta-only budget
    t2 = Task(task_id="n2", objective="x", meta={"max_tokens": 42})
    n2 = task_norms(t2)
    assert n2["max_tokens"] == 42
    assert any(r.get("key") == "max_tokens" for r in n2["rules"])


def test_hitl_resume_approve_and_reject(tmp_path: Path):
    """P7: auto_approve=False pauses at human gate; resume approve/reject."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)

    # --- approve path ---
    engine = DurableEngine(settings=settings, auto_approve=False)
    task = Task(
        task_id="hitl1",
        objective="hitl approve",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.waiting_human
    waiting = int(task.meta.get("waiting_step") or 0)
    assert waiting >= 1
    events = engine.events("hitl1")
    assert any(e.get("event") == "waiting_human" for e in events)

    task = engine.resume("hitl1", approve=True, feedback="lgtm")
    assert task.status == TaskStatus.completed
    assert task.current_step == 10
    assert task.outputs[waiting].get("approved") is True
    assert task.outputs[waiting].get("feedback") == "lgtm"
    events2 = engine.events("hitl1")
    assert any(e.get("event") == "human_decision" and e.get("approve") is True for e in events2)
    exp = engine.explain("hitl1")
    assert exp["human_decisions"]
    assert "human@" in exp["story"] or "COMPLETED" in exp["story"]

    # --- reject path ---
    engine2 = DurableEngine(settings=settings, auto_approve=False)
    task2 = Task(
        task_id="hitl2",
        objective="hitl reject",
        success_criteria=["artifact contains DEMO_OK"],
    )
    task2 = engine2.run(task2)
    assert task2.status == TaskStatus.waiting_human
    task2 = engine2.resume("hitl2", approve=False, feedback="needs work")
    assert task2.status == TaskStatus.failed
    assert "rejected by human" in (task2.meta.get("error") or "")
    events3 = engine2.events("hitl2")
    assert any(e.get("event") == "human_decision" and e.get("approve") is False for e in events3)
    assert any(e.get("event") == "failed" for e in events3)

    pack = engine2.evidence("hitl2")
    assert pack["ready"] is False
    assert pack["gates"].get("not_waiting_human") is True  # failed, not waiting
    assert pack["gates"]["completed"] is False


def test_dag_scheduling_and_action_order(tmp_path: Path):
    """P1.2: engine schedules via depends_on + records action_order + dag()."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    # Diamond DAG: goal → (plan | challenge) → review  (parallel ready after root)
    # Step names match MockAgent so structural pre-gate stays green.
    policy = StepPolicy(
        steps=[
            StepDef(
                1, "goal", "define", "operator",
                output_keys=("objective", "constraints", "success_criteria"),
            ),
            StepDef(
                2, "plan", "left branch", "planner", depends_on=(1,),
                required_capability="can_plan",
                output_keys=("approach", "risks", "estimated_steps"),
            ),
            StepDef(
                3, "challenge", "right branch", "adversary", depends_on=(1,),
                required_capability="can_review",
                output_keys=("concerns", "alternatives", "recommendation"),
            ),
            StepDef(
                4, "review", "join", "reviewer", depends_on=(2, 3),
                required_capability="can_review",
                output_keys=("findings", "severity", "verdict"),
            ),
        ]
    )
    engine = DurableEngine(settings=settings, auto_approve=True, policy=policy)
    task = Task(task_id="dag1", objective="diamond dag", success_criteria=["ok"])
    task = engine.run(task)
    assert task.status == TaskStatus.completed, task.meta.get("error")
    assert set(task.outputs) == {1, 2, 3, 4}
    order = task.meta.get("action_order") or []
    assert order[0] == "1:goal"
    # After root, lowest-number ready first (2 before 3), then join
    assert order == ["1:goal", "2:plan", "3:challenge", "4:review"]

    rep = engine.dag("dag1")
    assert rep["found"] is True
    assert rep["schema"] == "nexus.dag/v1"
    assert rep["n_completed"] == 4
    assert rep["n_ready"] == 0
    assert rep["action_order"] == order
    assert "flowchart" in (rep.get("mermaid") or "")

    # step_complete carries depends_on / action_order_i
    completes = [e for e in engine.events("dag1") if e.get("event") == "step_complete"]
    assert any(list(e.get("depends_on") or []) == [2, 3] for e in completes)


def test_dag_deadlock_unknown_path(tmp_path: Path):
    """Incomplete DAG with unsatisfiable edge fails closed (no spin)."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    # Step 2 depends on 1, but step 1 is missing from policy → validate fails at start
    policy = StepPolicy(
        steps=[
            StepDef(2, "orphan", "o", "planner", depends_on=(1,)),
        ]
    )
    engine = DurableEngine(settings=settings, auto_approve=True, policy=policy)
    task = Task(task_id="dag_bad", objective="bad dag")
    task = engine.run(task)
    assert task.status == TaskStatus.failed
    assert "invalid step DAG" in (task.meta.get("error") or "")


def test_evidence_pack(tmp_path: Path):
    """P6: evidence() unifies timeline/cost/prov/verify/graph + readiness gates."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="ev1",
        objective="evidence pack demo",
        success_criteria=["artifact contains DEMO_OK"],
        constraints=["require:tests", "deny:prod-write", "max_tokens=500000"],
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed

    pack = engine.evidence("ev1")
    assert pack["found"] is True
    assert pack["schema"] == "nexus.evidence/v1"
    assert pack["ready"] is True
    assert pack["gates"]["integrity_ok"] is True
    assert pack["gates"]["completed"] is True
    assert pack["gates"]["budget_ok"] is True
    assert pack["gates"]["has_timeline"] is True
    assert pack["n_timeline"] > 0
    assert pack["timeline"]
    assert pack["cost"]["total_tokens"] > 0
    assert pack["verify"]["ok"] is True
    assert pack["story"]
    assert pack["norms"]["max_tokens"] == 500_000
    assert "tests" in pack["norms"]["require"]
    assert "prod-write" in pack["norms"]["deny"]
    # full pack includes agents list
    assert (pack.get("provenance") or {}).get("agents")
    assert (pack.get("graph") or {}).get("nodes")

    compact = engine.evidence("ev1", compact=True)
    assert compact["compact"] is True
    assert compact["ready"] is True
    # compact provenance is summary counts, not full agent list
    assert "n_agents" in (compact.get("provenance") or {})
    assert "agents" not in (compact.get("provenance") or {})

    missing = engine.evidence("nope")
    assert missing["found"] is False
    assert missing["schema"] == "nexus.evidence/v1"

    # budget-failed task is not ready
    t2 = Task(
        task_id="ev2",
        objective="budget fail",
        success_criteria=["artifact contains DEMO_OK"],
        meta={"max_tokens": 1},
    )
    t2 = engine.run(t2)
    assert t2.status == TaskStatus.failed
    bad = engine.evidence("ev2")
    assert bad["found"] is True
    assert bad["ready"] is False
    assert bad["gates"]["budget_ok"] is False or bad["gates"]["completed"] is False



def test_promote_on_review_opt_in(tmp_path: Path):
    """P3: meta.promote_on_review runs IndependentVerify after review."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="prom1",
        objective="promote after review",
        success_criteria=["artifact contains DEMO_OK"],
        meta={
            "promote_on_review": True,
            "promote_implementer": "coder",
            "promote_keys": ["artifact"],
            "verify_min_score": 0.3,
        },
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    assert task.meta.get("verified") is True
    prom = task.meta.get("promote") or {}
    assert prom.get("ok") is True
    assert prom.get("cross_agent") is True
    assert "artifact" in (prom.get("promoted_keys") or [])
    events = engine.events("prom1")
    assert any(e.get("event") == "promote" for e in events)
    taint = task.meta.get("taint") or {}
    reg = taint.get("registry") or {}
    assert (reg.get("artifact") or {}).get("level") == "trusted"


def test_promote_denied_records_event(tmp_path: Path):
    """P3: low score → promote_denied; task still completes unless require."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="prom2",
        objective="promote deny soft",
        success_criteria=["artifact contains DEMO_OK"],
        meta={
            "promote_on_review": True,
            "promote_implementer": "coder",
            "verify_min_score": 0.99,  # almost always deny mock scores
        },
    )
    task = engine.run(task)
    assert task.status == TaskStatus.completed
    prom = task.meta.get("promote") or {}
    assert prom.get("ok") is False
    events = engine.events("prom2")
    assert any(e.get("event") == "promote_denied" for e in events)


def test_promote_require_fail_closed(tmp_path: Path):
    """P3: promote_require=true fails the task when verify denies."""
    settings = Settings(state_dir=tmp_path / "state", autonomy=False)
    engine = DurableEngine(settings=settings, auto_approve=True)
    task = Task(
        task_id="prom3",
        objective="promote require",
        success_criteria=["artifact contains DEMO_OK"],
        meta={
            "promote_on_review": True,
            "promote_require": True,
            "promote_implementer": "coder",
            "verify_min_score": 0.99,
        },
    )
    task = engine.run(task)
    assert task.status == TaskStatus.failed
    assert "promote denied" in (task.meta.get("error") or "")
