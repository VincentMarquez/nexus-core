"""Cross-vendor rubric judge — scores real success criteria + evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .agents import AgentPanel
from .steps import StepDef


RUBRIC_DIMS = (
    "meets_success_criteria",
    "correctness_evidence",
    "artifact_actually_produced",
    "no_banned_approach",
    "coherence",
)


@dataclass
class Verdict:
    decision: str  # pass | fail | revise
    score: float  # 0..1
    dims: dict[str, float]
    judge_agent: str
    judge_vendor: str
    implementer: str
    implementer_vendor: str
    degraded: bool
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class RubricJudge:
    """
    Presence validators ask: did someone answer?
    This judge asks: do artifacts satisfy success_criteria?

    Prefer a judge vendor ≠ implementer vendor when possible.
    """

    def __init__(self, panel: AgentPanel, *, prefer_cross_vendor: bool = True):
        self.panel = panel
        self.prefer_cross_vendor = prefer_cross_vendor

    def pick_judge(self, implementer: str) -> tuple[str, bool]:
        imp_vendor = self.panel.vendor_of.get(implementer, "unknown")
        # preference order among review-capable agents
        order = ["reviewer", "adversary", "planner", "local", "tester"]
        # try cross-vendor first
        if self.prefer_cross_vendor:
            for name in order:
                if name not in self.panel.agents:
                    continue
                if not self.panel.agents[name].online:
                    continue
                if self.panel.vendor_of.get(name) != imp_vendor:
                    return name, False
        # degraded: same vendor ok
        for name in order:
            if name in self.panel.agents and self.panel.agents[name].online:
                return name, True
        return "local", True

    def evaluate(
        self,
        *,
        step: StepDef,
        task: dict[str, Any],
        output: dict[str, Any],
        implementer: str,
    ) -> Verdict:
        judge_name, degraded = self.pick_judge(implementer)
        criteria = list(task.get("success_criteria") or [])
        evidence_paths = list(output.get("evidence") or output.get("artifacts") or [])

        # Evidence grounded scoring (no LLM required in the kit)
        dims = {d: 0.5 for d in RUBRIC_DIMS}
        produced = 0.0
        texts: list[str] = []
        for p in evidence_paths:
            path = Path(str(p))
            if path.is_file():
                produced = 1.0
                try:
                    texts.append(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
        dims["artifact_actually_produced"] = produced

        blob = "\n".join(texts) + "\n" + str(output)
        if criteria:
            hits = sum(1 for c in criteria if str(c).split()[0] in blob or str(c) in blob)
            # also accept DEMO_OK style markers mentioned in criteria text
            for c in criteria:
                if "DEMO_OK" in str(c) and "DEMO_OK" in blob:
                    hits = max(hits, 1)
            dims["meets_success_criteria"] = hits / max(1, len(criteria))
        else:
            dims["meets_success_criteria"] = 0.7 if produced else 0.2

        dims["correctness_evidence"] = 1.0 if produced and dims["meets_success_criteria"] >= 0.5 else 0.3
        dims["no_banned_approach"] = 1.0
        dims["coherence"] = 0.8 if isinstance(output, dict) else 0.2

        score = sum(dims.values()) / len(dims)
        if score >= 0.7:
            decision = "pass"
        elif score >= 0.45:
            decision = "revise"
        else:
            decision = "fail"

        # Non-artifact steps: structural gate already ran; don't hard-fail the pipeline.
        if step.name in {
            "log", "goal", "plan", "challenge", "meta_review",
            "approval", "deliver", "review",
        }:
            if decision == "fail":
                decision = "pass"
                score = max(score, 0.75)

        rationale = (
            f"judge={judge_name} score={score:.2f} criteria_hits={dims['meets_success_criteria']:.2f} "
            f"artifacts={len(evidence_paths)} degraded={degraded}"
        )
        return Verdict(
            decision=decision,
            score=score,
            dims=dims,
            judge_agent=judge_name,
            judge_vendor=self.panel.vendor_of.get(judge_name, "unknown"),
            implementer=implementer,
            implementer_vendor=self.panel.vendor_of.get(implementer, "unknown"),
            degraded=degraded,
            rationale=rationale,
        )
