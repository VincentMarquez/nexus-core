"""Tests for SWE-Adept two-phase planning (localization → resolution).

arXiv 2603.01327v2 — structure only; offline heuristic, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus import swe_adept_plan as sap
from nexus.orchestrator import Orchestrator, OrchError, load_envelope
from nexus.ops_store import OpsStore


def _mini_repo(tmp_path: Path) -> Path:
    """Layout with path tokens that match issue text."""
    (tmp_path / "src" / "nexus").mkdir(parents=True)
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "src" / "nexus" / "orchestrator.py").write_text(
        '"""Orchestrator façade."""\nSCHEMA = "nexus.orchestrator/v1"\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / "nexus" / "multi_llm_agent.py").write_text(
        '"""Multi-LLM planner."""\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / "nexus" / "failure_patterns.py").write_text(
        '"""Failure pattern mine."""\n',
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_orchestrator.py").write_text(
        "def test_orch():\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "README.md").write_text("# docs\n", encoding="utf-8")
    return tmp_path


# ── pure helpers ────────────────────────────────────────────────────────────


def test_tokenize_issue_extracts_identifiers():
    toks = sap.tokenize_issue(
        "Fix orchestrator localization in multi_llm_agent and run pytest"
    )
    assert "orchestrator" in toks
    assert "localization" in toks
    # snake_case splits into compound pieces
    assert "multi" in toks
    assert "llm" in toks
    assert "agent" in toks
    # stopwords dropped
    assert "the" not in toks
    assert "and" not in toks


def test_score_path_prefers_name_overlap():
    toks = sap.tokenize_issue("orchestrator localization plan")
    hi, _ = sap.score_path("src/nexus/orchestrator.py", toks)
    lo, _ = sap.score_path("docs/README.md", toks)
    assert hi > lo
    assert hi > 0


def test_localize_ranks_relevant_files(tmp_path: Path):
    root = _mini_repo(tmp_path)
    phase = sap.localize(
        "Implement structured localization planning in the orchestrator module",
        workdir=root,
        max_targets=5,
    )
    assert phase.name == sap.PHASE_LOCALIZATION
    assert phase.targets
    assert any("orchestrator" in t for t in phase.targets)
    assert phase.steps
    assert phase.steps[0].action == "locate.scan"
    assert all(s.phase == sap.PHASE_LOCALIZATION for s in phase.steps)
    # hits carry scores
    assert phase.hits
    assert phase.hits[0].score >= phase.hits[-1].score


def test_localize_honors_explicit_path_hint(tmp_path: Path):
    root = _mini_repo(tmp_path)
    phase = sap.localize(
        "See `src/nexus/failure_patterns.py` for the bug",
        workdir=root,
        max_targets=5,
    )
    assert any("failure_patterns" in t for t in phase.targets)


def test_localize_empty_issue_fails():
    with pytest.raises(sap.SweAdeptPlanError):
        sap.localize("")


def test_plan_resolution_separates_phase_and_targets():
    res = sap.plan_resolution(
        "Fix orchestrator and verify with pytest",
        ["src/nexus/orchestrator.py", "tests/test_orchestrator.py"],
        max_steps=10,
    )
    assert res.name == sap.PHASE_RESOLUTION
    assert res.steps
    assert all(s.phase == sap.PHASE_RESOLUTION for s in res.steps)
    actions = {s.action for s in res.steps}
    assert "resolve.read" in actions
    assert "resolve.edit" in actions
    assert "resolve.test" in actions or "resolve.verify" in actions
    # steps reference localized paths
    assert any(s.target.endswith("orchestrator.py") for s in res.steps)


def test_build_swe_adept_plan_two_phases(tmp_path: Path):
    root = _mini_repo(tmp_path)
    plan = sap.build_swe_adept_plan(
        "Add localization phase to orchestrator before applying fixes",
        workdir=root,
        max_targets=4,
        max_resolution_steps=9,
    )
    assert plan.schema == sap.SCHEMA
    assert plan.paper == sap.PAPER
    assert plan.status == sap.STATUS_READY
    assert plan.localization.name == sap.PHASE_LOCALIZATION
    assert plan.resolution.name == sap.PHASE_RESOLUTION
    assert plan.localization.targets
    assert plan.resolution.steps
    # Phase separation invariant: no resolution action in localization
    for s in plan.localization.steps:
        assert s.action.startswith("locate.")
        assert s.phase == sap.PHASE_LOCALIZATION
    for s in plan.resolution.steps:
        assert s.action.startswith("resolve.")
        assert s.phase == sap.PHASE_RESOLUTION
    assert plan.is_ready()


def test_mark_ready_fail_closed_on_empty_resolution():
    plan = sap.SweAdeptPlan(
        task="x",
        localization=sap.PlanPhase(
            name=sap.PHASE_LOCALIZATION,
            steps=[
                sap.PhaseStep(
                    id=1, phase=sap.PHASE_LOCALIZATION, action="locate.scan"
                )
            ],
            targets=["a.py"],
        ),
        resolution=sap.PlanPhase(name=sap.PHASE_RESOLUTION, steps=[]),
    )
    with pytest.raises(sap.SweAdeptPlanError, match="resolution"):
        sap.mark_ready(plan)


def test_parse_and_payload_roundtrip(tmp_path: Path):
    root = _mini_repo(tmp_path)
    plan = sap.build_swe_adept_plan(
        "Fix multi_llm_agent planner handoff",
        workdir=root,
    )
    raw = plan.to_json()
    back = sap.parse_swe_plan_json(raw)
    assert back.task == plan.task
    assert back.localization.targets == plan.localization.targets
    assert len(back.resolution.steps) == len(plan.resolution.steps)

    payload = sap.plan_payload_for_meta(plan)
    assert payload["schema"] == sap.SCHEMA
    assert payload["paper"] == sap.PAPER
    assert payload["phases"] == [sap.PHASE_LOCALIZATION, sap.PHASE_RESOLUTION]
    assert payload["n_targets"] >= 1
    assert payload["localization"]["name"] == sap.PHASE_LOCALIZATION
    assert payload["resolution"]["name"] == sap.PHASE_RESOLUTION
    assert "brief" in payload
    brief = sap.format_brief(plan)
    assert "localization" in brief.lower()
    assert "resolution" in brief.lower()


def test_as_tool_plan_steps_preserves_phase_order(tmp_path: Path):
    root = _mini_repo(tmp_path)
    plan = sap.build_swe_adept_plan(
        "orchestrator localization resolution",
        workdir=root,
        max_targets=2,
        max_resolution_steps=4,
    )
    steps = sap.as_tool_plan_steps(plan)
    assert steps
    # localization tools first
    phases = [s["phase"] for s in steps]
    first_res = next(i for i, p in enumerate(phases) if p == sap.PHASE_RESOLUTION)
    assert all(p == sap.PHASE_LOCALIZATION for p in phases[:first_res])


def test_parse_fenced_json():
    text = """
Here is the plan:
```json
{
  "task": "fix foo",
  "status": "ready",
  "localization": {
    "name": "localization",
    "status": "ready",
    "targets": ["src/foo.py"],
    "steps": [{"id": 1, "action": "locate.scan", "phase": "localization"}]
  },
  "resolution": {
    "name": "resolution",
    "status": "ready",
    "steps": [
      {"id": 1, "action": "resolve.edit", "phase": "resolution", "args": {"path": "src/foo.py"}}
    ]
  }
}
```
"""
    plan = sap.parse_swe_plan_json(text)
    assert plan.task == "fix foo"
    assert plan.localization.targets == ["src/foo.py"]
    assert plan.resolution.steps[0].action == "resolve.edit"


def test_maybe_build_for_task_opt_in(tmp_path: Path):
    root = _mini_repo(tmp_path)
    assert sap.maybe_build_for_task(root, "t1", "orchestrator fix", {}) is None
    assert (
        sap.maybe_build_for_task(root, "t1", "orchestrator fix", {"other": True})
        is None
    )
    out = sap.maybe_build_for_task(
        root,
        "t1",
        "Fix localization in orchestrator module",
        {"with_swe_plan": True, "swe_max_targets": 4},
    )
    assert out is not None
    assert out["ok"] is True
    assert out["paper"] == sap.PAPER
    assert out["n_targets"] >= 1
    assert out["plan"]["phases"] == [sap.PHASE_LOCALIZATION, sap.PHASE_RESOLUTION]


def test_maybe_build_require_targets_fails_closed(tmp_path: Path):
    # Empty tree under search roots → no targets
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "src").mkdir()
    out = sap.maybe_build_for_task(
        empty,
        "t-empty",
        "zzzznonexistenttokenqqq",
        {
            "with_swe_plan": True,
            "swe_require_targets": True,
            "swe_search_roots": ["src"],
        },
    )
    assert out is not None
    assert out["ok"] is False
    assert out["status"] == sap.STATUS_FAILED


def test_module_main_json(tmp_path: Path, capsys):
    root = _mini_repo(tmp_path)
    rc = sap.main(
        [
            "orchestrator localization",
            "--path",
            str(root),
            "--json",
            "--max-targets",
            "3",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == sap.SCHEMA
    assert data["paper"] == sap.PAPER


# ── orchestrator integration ────────────────────────────────────────────────


def test_orchestrator_with_swe_plan(tmp_path: Path, monkeypatch):
    root = _mini_repo(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    out = orch.run_task(
        "Implement localization vs resolution planning in the orchestrator",
        kind="task",
        agent_mode="fake",
        task_id="swe-1",
        with_swe_plan=True,
        swe_max_targets=5,
        sync_fake=True,
    )
    assert out["task_id"] == "swe-1"
    assert out["status"] == "completed"
    assert out.get("swe_adept") is True
    plan = out.get("swe_adept_plan") or {}
    assert plan.get("paper") == sap.PAPER
    assert plan.get("phases") == [sap.PHASE_LOCALIZATION, sap.PHASE_RESOLUTION]
    summary = out.get("swe_adept_summary") or {}
    assert summary.get("n_targets", 0) >= 1
    assert "localization" in (summary.get("phases") or [])

    env = load_envelope(root, "swe-1")
    assert env is not None
    assert env.meta.get("with_swe_plan") is True
    assert env.meta.get("swe_adept_plan", {}).get("n_targets", 0) >= 1
    assert env.meta.get("swe_adept_paper") == sap.PAPER

    logs = orch.get_task_status("swe-1", action="logs").get("logs") or []
    assert any("swe_adept" in str(line).lower() for line in logs)
    assert any(str(line).startswith("localize:") for line in logs)

    with OpsStore.open(root) as store:
        job = store.get("swe-1")
        assert job is not None
        meta = job.get("meta") or {}
        assert meta.get("with_swe_plan") is True
        assert meta.get("swe_adept_paper") == sap.PAPER
        assert (meta.get("swe_adept_plan") or {}).get("n_targets", 0) >= 1


def test_orchestrator_swe_plan_via_meta_only(tmp_path: Path, monkeypatch):
    root = _mini_repo(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    out = orch.run_task(
        "Fix failure_patterns classification in orchestrator path walk",
        agent_mode="fake",
        task_id="swe-meta",
        meta={"swe_adept": True, "swe_max_targets": 3},
        sync_fake=True,
    )
    assert out.get("swe_adept") is True
    assert (out.get("swe_adept_summary") or {}).get("n_targets", 0) >= 1


def test_orchestrator_swe_require_targets_can_fail(tmp_path: Path, monkeypatch):
    empty = tmp_path / "blank"
    empty.mkdir()
    (empty / "src").mkdir()
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(empty))
    orch = Orchestrator(empty)
    with pytest.raises(OrchError) as ei:
        orch.run_task(
            "zzzznonexistenttokenqqq nothing matches",
            agent_mode="fake",
            task_id="swe-fail",
            with_swe_plan=True,
            swe_require_targets=True,
            sync_fake=True,
        )
    assert ei.value.code == "swe_plan_failed"
    # Fail-closed before job/envelope creation
    assert load_envelope(empty, "swe-fail") is None
    with OpsStore.open(empty) as store:
        assert store.get("swe-fail") is None


def test_orchestrator_swe_require_via_meta_only(tmp_path: Path, monkeypatch):
    """meta swe_require_targets must fail-closed even without with_swe_plan kwarg."""
    empty = tmp_path / "blank-meta"
    empty.mkdir()
    (empty / "src").mkdir()
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(empty))
    orch = Orchestrator(empty)
    with pytest.raises(OrchError) as ei:
        orch.run_task(
            "zzzznonexistenttokenqqq nothing matches",
            agent_mode="fake",
            task_id="swe-meta-req",
            meta={"swe_adept": True, "swe_require_targets": True},
            sync_fake=True,
        )
    assert ei.value.code == "swe_plan_failed"


def test_orchestrator_swe_plan_off_is_zero_cost(tmp_path: Path, monkeypatch):
    root = _mini_repo(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    walked = {"n": 0}
    real_iter = sap._iter_candidate_paths

    def _count_walk(*a, **k):
        walked["n"] += 1
        return real_iter(*a, **k)

    monkeypatch.setattr(sap, "_iter_candidate_paths", _count_walk)
    orch = Orchestrator(root)
    out = orch.run_task(
        "plain task no swe plan",
        agent_mode="fake",
        task_id="swe-off",
        with_swe_plan=False,
        sync_fake=True,
    )
    assert out.get("swe_adept") in (False, None)
    assert not out.get("swe_adept_plan")
    env = load_envelope(root, "swe-off")
    assert env is not None
    assert not env.meta.get("swe_adept")
    assert not env.meta.get("swe_adept_plan")
    # Off means no localization walk
    assert walked["n"] == 0


def test_orchestrator_status_summary_from_init(tmp_path: Path, monkeypatch):
    root = _mini_repo(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    out = orch.run_task(
        "Implement localization planning in orchestrator",
        agent_mode="fake",
        task_id="swe-status",
        with_swe_plan=True,
        swe_max_targets=4,
        sync_fake=True,
    )
    summary = out.get("swe_adept_summary") or {}
    assert summary.get("state") == "ready" or summary.get("status") == "ready"
    assert summary.get("n_targets", 0) >= 1
    assert summary.get("n_localization_steps") is not None
    assert summary.get("phases")
    # Full plan present from envelope
    plan = out.get("swe_adept_plan") or {}
    assert "localization" in plan or plan.get("schema")


def test_orchestrator_soft_fail_without_require(tmp_path: Path, monkeypatch):
    """When require_targets is False, empty localization still builds a plan."""
    empty = tmp_path / "soft-ok"
    empty.mkdir()
    (empty / "src").mkdir()
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(empty))
    orch = Orchestrator(empty)
    out = orch.run_task(
        "zzzznonexistenttokenqqq nothing matches",
        agent_mode="fake",
        task_id="swe-soft-ok",
        with_swe_plan=True,
        swe_require_targets=False,
        sync_fake=True,
    )
    # Unlocalized fallback still yields a ready two-phase structure
    assert out.get("swe_adept") is True
    summary = out.get("swe_adept_summary") or {}
    assert summary.get("state") == "ready" or summary.get("status") == "ready"


def test_orchestrator_meta_string_max_targets_clamped(tmp_path: Path, monkeypatch):
    root = _mini_repo(tmp_path)
    monkeypatch.setenv("NEXUS_PROJECT_ROOT", str(root))
    orch = Orchestrator(root)
    out = orch.run_task(
        "Fix orchestrator localization",
        agent_mode="fake",
        task_id="swe-clamp",
        meta={"with_swe_plan": True, "swe_max_targets": "50"},
        sync_fake=True,
    )
    assert out.get("swe_adept") is True
    env = load_envelope(root, "swe-clamp")
    assert env is not None
    # clamped to SWE_LIMIT_MAX (64) but 50 is within range
    assert int(env.meta.get("swe_max_targets") or 0) == 50


def test_sanitize_plan_path_rejects_hostile():
    with pytest.raises(sap.SweAdeptPlanError):
        sap.sanitize_plan_path("../../.env")
    with pytest.raises(sap.SweAdeptPlanError):
        sap.sanitize_plan_path("/etc/passwd")
    with pytest.raises(sap.SweAdeptPlanError):
        sap.sanitize_plan_path(".nexus_state/secrets.json")
    assert sap.sanitize_plan_path("src/nexus/orchestrator.py") == (
        "src/nexus/orchestrator.py"
    )
    assert sap.safe_plan_path("../foo") is None


def test_mark_ready_rejects_mutating_localization_action():
    plan = sap.SweAdeptPlan(
        task="inject evil",
        localization=sap.PlanPhase(
            name=sap.PHASE_LOCALIZATION,
            steps=[
                sap.PhaseStep(
                    id=1,
                    phase=sap.PHASE_LOCALIZATION,
                    action="resolve.edit",
                    args={"path": "a.py"},
                    target="a.py",
                )
            ],
            targets=["a.py"],
        ),
        resolution=sap.PlanPhase(
            name=sap.PHASE_RESOLUTION,
            steps=[
                sap.PhaseStep(
                    id=1,
                    phase=sap.PHASE_RESOLUTION,
                    action="resolve.edit",
                    args={"path": "a.py"},
                    target="a.py",
                )
            ],
        ),
    )
    with pytest.raises(sap.SweAdeptPlanError, match="non-locate"):
        sap.mark_ready(plan)


def test_injected_ready_plan_still_validated():
    """status=ready must not bypass mark_ready / action purity."""
    out = sap.maybe_build_for_task(
        Path("."),
        "t-inject",
        "fix",
        {
            "with_swe_plan": True,
            "swe_plan": {
                "task": "fix",
                "status": "ready",
                "localization": {
                    "name": "localization",
                    "status": "ready",
                    "targets": ["src/ok.py"],
                    "steps": [
                        {
                            "id": 1,
                            "action": "resolve.edit",
                            "phase": "localization",
                            "args": {"path": "src/ok.py"},
                        }
                    ],
                },
                "resolution": {
                    "name": "resolution",
                    "status": "ready",
                    "steps": [
                        {
                            "id": 1,
                            "action": "resolve.edit",
                            "phase": "resolution",
                            "args": {"path": "src/ok.py"},
                        }
                    ],
                },
            },
        },
    )
    assert out is not None
    assert out["ok"] is False


def test_plan_resolution_covers_full_lifecycle_only():
    targets = [f"src/f{i}.py" for i in range(8)]
    res = sap.plan_resolution("Fix files", targets, max_steps=12)
    # 3 actions/target default → at most 4 full targets under budget 12
    assert len(res.targets) <= 4
    assert len(res.targets) == 4
    # every covered target has a complete lifecycle (read+edit+verify)
    by_target: dict[str, set[str]] = {}
    for s in res.steps:
        by_target.setdefault(s.target, set()).add(s.action)
    for t in res.targets:
        acts = by_target[t]
        assert "resolve.read" in acts
        assert "resolve.edit" in acts
        assert "resolve.verify" in acts or "resolve.test" in acts
    assert "dropped" in (res.notes or "")


def test_plan_resolution_tiny_budget_emits_one_lifecycle():
    res = sap.plan_resolution(
        "Fix one file",
        ["src/a.py"],
        max_steps=1,
    )
    # Budget < lifecycle still emits one full lifecycle (structural minimum)
    assert res.steps
    assert res.targets == ["src/a.py"]
    acts = {s.action for s in res.steps}
    assert "resolve.read" in acts
    assert "resolve.edit" in acts


def test_score_path_no_false_targets_without_match():
    toks = sap.tokenize_issue("zzzznonexistenttokenqqq")
    sc, reason = sap.score_path("src/nexus/orchestrator.py", toks)
    assert sc == 0.0
    assert "no token match" in reason


def test_clamp_swe_limit():
    assert sap.clamp_swe_limit("50") == 50
    assert sap.clamp_swe_limit(10**9) == 64
    assert sap.clamp_swe_limit(0) == 1
    assert sap.clamp_swe_limit("nope", 8) == 8


def test_localization_hit_from_dict_rejects_traversal():
    with pytest.raises(sap.SweAdeptPlanError):
        sap.LocalizationHit.from_dict({"path": "../../.env", "score": 9})


def test_payload_counts_match_full_plan(tmp_path: Path):
    root = _mini_repo(tmp_path)
    plan = sap.build_swe_adept_plan(
        "orchestrator localization",
        workdir=root,
        max_targets=2,
        max_resolution_steps=40,  # above lean-step truncate of 30
    )
    # force more resolution steps than lean slice if possible
    payload = sap.plan_payload_for_meta(plan)
    assert payload["n_localization_steps"] == len(plan.localization.steps)
    assert payload["n_resolution_steps"] == len(plan.resolution.steps)
    assert payload["n_steps"] == (
        len(plan.localization.steps) + len(plan.resolution.steps)
    )
