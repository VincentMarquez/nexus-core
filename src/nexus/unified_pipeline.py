"""One pipeline for lab, alive, and MCP — DurableEngine + Judge.

Do **not** invent parallel phase machines. All review/implement/meta paths
share the same step graph and the same judge gates:

  goal → plan → challenge → implement → test → review → log
       → meta_review → approval → deliver

Research (GitHub ≥5K★, arXiv) is **input context**, not a second workflow.
Judge: ConsensusJudge / RubricJudge (pass ≥0.7, revise ≥0.45, else fail).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from .engine import DurableEngine, Task, TaskStatus
from .judge import PASS_THRESHOLD, REVISE_THRESHOLD, decision_thresholds

# Canonical order — must match StepPolicy.default() names
CANONICAL_FLOW: tuple[str, ...] = (
    "goal",
    "plan",
    "challenge",
    "implement",
    "test",
    "review",
    "log",
    "meta_review",
    "approval",
    "deliver",
)

# Map old lab/alive labels → canonical steps (documentation / migration)
ALIAS_TO_CANONICAL: dict[str, str] = {
    "github_review": "goal",  # research feeds goal/plan
    "arxiv_review": "plan",
    "dual_review": "challenge",
    "github_mine": "goal",
    "self_approve_apply": "implement",
    "self_check": "test",
    "paper_improve": "plan",
}


def canonical_flow() -> list[str]:
    return list(CANONICAL_FLOW)


def normalize_phase(name: str) -> str:
    n = str(name or "").strip().lower()
    return ALIAS_TO_CANONICAL.get(n, n)


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir:
        return Path(workdir).resolve()
    import os

    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.home() / "nexus-core").resolve()


def build_objective(
    query: str,
    *,
    research_brief: str = "",
    goal_hint: str = "",
) -> tuple[str, list[str]]:
    """Compose engine objective + success_criteria from research context."""
    q = (query or "improve product safely").strip()
    brief = (research_brief or "").strip()[:6000]
    hint = (goal_hint or "").strip()[:500]
    objective = (
        f"{hint + ' — ' if hint else ''}"
        f"Follow the canonical pipeline (goal→plan→challenge→implement→test→"
        f"review→log→meta_review→approval→deliver) with RubricJudge/ConsensusJudge "
        f"on every step. Topic: {q}. "
        f"Product root only; no GitHub push unless approval step says so. "
        f"Prefer patterns from high-star GitHub + arXiv brief when present."
    )
    criteria = [
        "plan artifact or approach recorded",
        "review or meta_review verdict present",
        "judge decision is pass or revise (not silent drop)",
        f"addresses: {q[:80]}",
    ]
    if brief:
        objective += "\n\n--- RESEARCH BRIEF (GitHub/arXiv; context only) ---\n" + brief
        criteria.append("uses research brief where relevant")
    return objective, criteria


def run_canonical(
    workdir: Optional[Path | str] = None,
    *,
    query: str = "multi agent product improve",
    research_brief: str = "",
    goal_hint: str = "",
    success_criteria: Optional[list[str]] = None,
    auto_approve: bool = True,
    max_steps: Optional[int] = None,
    task_id: Optional[str] = None,
    source: str = "unified",
) -> dict[str, Any]:
    """Run the **one** pipeline: DurableEngine + ConsensusJudge.

    Returns a status payload including per-step judge decisions so the lab
    workspace (and alive) never need a parallel phase machine.
    """
    root = _root(workdir)
    objective, criteria = build_objective(
        query, research_brief=research_brief, goal_hint=goal_hint
    )
    if success_criteria:
        criteria = list(success_criteria)

    tid = (task_id or f"canon-{int(time.time())}").replace("/", "-")[:80]
    engine = DurableEngine(auto_approve=auto_approve, journal=True)
    task = Task(
        task_id=tid,
        objective=objective,
        success_criteria=criteria,
        namespace="proj/nexus-core",
        constraints=[
            "product tree only",
            "no independent lab phase machine",
            "judge gates implement/test hard-fail",
            "review veto fail-closed",
        ],
        meta={
            "source": source,
            "pipeline": list(CANONICAL_FLOW),
            "pipeline_kind": "canonical_engine",
            "query": query,
            "research_brief_chars": len(research_brief or ""),
            "judge": "ConsensusJudge|RubricJudge",
            "thresholds": decision_thresholds(),
            "auto_created": False,
        },
    )
    engine.save(task)
    task = engine.run(task, max_steps=max_steps)

    steps_out: list[dict[str, Any]] = []
    for num, out in sorted((task.outputs or {}).items(), key=lambda x: int(x[0])):
        if not isinstance(out, dict):
            continue
        v = out.get("_verdict") or {}
        # Map step number → name from policy
        name = ""
        try:
            for s in engine.policy.steps:
                if s.number == int(num):
                    name = s.name
                    break
        except Exception:
            name = str(num)
        steps_out.append(
            {
                "step": int(num),
                "name": name,
                "canonical": normalize_phase(name),
                "judge_decision": v.get("decision"),
                "judge_score": v.get("score"),
                "judge_rationale": (v.get("rationale") or "")[:240],
                "output_keys": [k for k in out.keys() if not str(k).startswith("_")],
            }
        )

    # Persist a thin pointer for lab UI / alive
    try:
        ptr = root / ".nexus_state" / "LAST_CANONICAL_PIPELINE.json"
        ptr.parent.mkdir(parents=True, exist_ok=True)
        ptr.write_text(
            json.dumps(
                {
                    "task_id": task.task_id,
                    "status": task.status.value,
                    "current_step": task.current_step,
                    "steps": steps_out,
                    "ts": time.time(),
                    "source": source,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    return {
        "ok": task.status == TaskStatus.completed
        or (
            task.status == TaskStatus.running and bool(steps_out)
        )
        or task.status == TaskStatus.waiting_human,
        "pipeline": list(CANONICAL_FLOW),
        "pipeline_kind": "canonical_engine",
        "task_id": task.task_id,
        "status": task.status.value,
        "current_step": task.current_step,
        "steps": steps_out,
        "error": (task.meta or {}).get("error"),
        "judge_thresholds": decision_thresholds(),
        "pass_threshold": PASS_THRESHOLD,
        "revise_threshold": REVISE_THRESHOLD,
        "message": (
            f"Canonical engine pipeline status={task.status.value} "
            f"step={task.current_step}/{len(CANONICAL_FLOW)} "
            f"(judge on every step — not a parallel lab line)"
        ),
    }


def format_pipeline_summary(result: dict[str, Any]) -> str:
    """Human/chat summary of judge-gated run."""
    if not result:
        return "No pipeline result."
    lines = [
        "▶ CANONICAL PIPELINE (DurableEngine + Judge)",
        f"task: {result.get('task_id')} · status: {result.get('status')}",
        f"flow: {' → '.join(result.get('pipeline') or CANONICAL_FLOW)}",
        f"thresholds: pass≥{result.get('pass_threshold', PASS_THRESHOLD)} "
        f"revise≥{result.get('revise_threshold', REVISE_THRESHOLD)}",
        "",
    ]
    if result.get("error"):
        lines.append(f"error: {result.get('error')}")
    for s in result.get("steps") or []:
        jd = s.get("judge_decision") or "?"
        sc = s.get("judge_score")
        sc_s = f"{float(sc):.2f}" if sc is not None else "-"
        lines.append(
            f"  {s.get('step')}:{s.get('name')} → judge={jd} score={sc_s}"
        )
    lines.append("")
    lines.append(result.get("message") or "")
    return "\n".join(lines)
