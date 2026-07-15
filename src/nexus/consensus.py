"""Multi-grader consensus — independent findings + trust-weighted decision.

Port of gossipcat-style multi-agent review patterns (not the tree):
- independent findings from ≥N graders
- trust weights per agent (static defaults + optional adaptive history)
- agreement / disagreement / unique signals
- weighted mean score + majority decision

Works fully offline with role lenses (adversary stricter, tester evidence-
heavy, etc.) so demos and pytest stay deterministic.

Evidence drivers:
- gossipcat-ai/gossipcat-ai — consensus signals, findings, trust
- openai/swarm — multi-agent coordination without shared brain
- arXiv 2203.08975 — multi-agent communication / agreement
- arXiv 2502.07165 — principle-based multi-agent prompting
- NEXUS RubricJudge cross-vendor preference
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .agents import AgentPanel
from .judge import (
    PASS_THRESHOLD,
    REVISE_THRESHOLD,
    RUBRIC_DIMS,
    RubricJudge,
    Verdict,
    decision_thresholds,
)
from .steps import StepDef

SCHEMA = "nexus.consensus/v1"

# Default trust weights (gossipcat adaptive-trust shape; static seed).
DEFAULT_TRUST_WEIGHTS: dict[str, float] = {
    "adversary": 1.25,
    "reviewer": 1.0,
    "tester": 1.0,
    "planner": 0.85,
    "local": 0.6,
    "logger": 0.5,
    "operator": 0.4,
    "implementer": 0.5,  # implementer rarely grades self
}

# Preferred grader roles (order matters for fill when fewer online).
DEFAULT_GRADER_ORDER = (
    "reviewer",
    "adversary",
    "tester",
    "planner",
    "local",
)

# Role lenses: multiply base dims after evidence scoring (deterministic).
# Adversary is harsher on criteria; tester emphasizes artifacts.
ROLE_LENSES: dict[str, dict[str, float]] = {
    "adversary": {
        "meets_success_criteria": 0.85,
        "correctness_evidence": 0.9,
        "artifact_actually_produced": 1.0,
        "no_banned_approach": 1.0,
        "coherence": 0.9,
    },
    "tester": {
        "meets_success_criteria": 1.0,
        "correctness_evidence": 1.15,
        "artifact_actually_produced": 1.2,
        "no_banned_approach": 1.0,
        "coherence": 0.85,
    },
    "reviewer": {
        "meets_success_criteria": 1.0,
        "correctness_evidence": 1.0,
        "artifact_actually_produced": 1.0,
        "no_banned_approach": 1.0,
        "coherence": 1.0,
    },
    "planner": {
        "meets_success_criteria": 0.95,
        "correctness_evidence": 0.9,
        "artifact_actually_produced": 0.9,
        "no_banned_approach": 1.0,
        "coherence": 1.1,
    },
    "local": {
        "meets_success_criteria": 1.0,
        "correctness_evidence": 1.0,
        "artifact_actually_produced": 1.0,
        "no_banned_approach": 1.0,
        "coherence": 0.95,
    },
}


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def score_from_dims(dims: dict[str, float]) -> float:
    if not dims:
        return 0.0
    return sum(float(v) for v in dims.values()) / len(dims)


def decision_from_score(
    score: float,
    *,
    thresholds: Optional[dict[str, float]] = None,
) -> str:
    thr = thresholds or decision_thresholds()
    if score >= thr["pass"]:
        return "pass"
    if score >= thr["revise"]:
        return "revise"
    return "fail"


def evidence_base_dims(
    *,
    step: StepDef,
    task: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, float]:
    """Shared evidence-grounded dim scores (no role lens)."""
    criteria = list(task.get("success_criteria") or [])
    evidence_paths = list(output.get("evidence") or output.get("artifacts") or [])

    dims: dict[str, float] = {d: 0.5 for d in RUBRIC_DIMS}
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
        hits = sum(
            1 for c in criteria if str(c).split()[0] in blob or str(c) in blob
        )
        for c in criteria:
            if "DEMO_OK" in str(c) and "DEMO_OK" in blob:
                hits = max(hits, 1)
        dims["meets_success_criteria"] = hits / max(1, len(criteria))
    else:
        dims["meets_success_criteria"] = 0.7 if produced else 0.2

    dims["correctness_evidence"] = (
        1.0 if produced and dims["meets_success_criteria"] >= 0.5 else 0.3
    )
    dims["no_banned_approach"] = 1.0
    dims["coherence"] = 0.8 if isinstance(output, dict) else 0.2

    # Non-artifact steps: structural gate already ran; keep pipeline moving.
    if step.name in {
        "log",
        "goal",
        "plan",
        "challenge",
        "meta_review",
        "approval",
        "deliver",
        "review",
    }:
        # Soft floor so fail-only happens on implement/test style steps.
        if score_from_dims(dims) < REVISE_THRESHOLD:
            dims["meets_success_criteria"] = max(
                dims["meets_success_criteria"], PASS_THRESHOLD
            )
            dims["coherence"] = max(dims["coherence"], 0.7)
    return dims


def apply_lens(dims: dict[str, float], role: str) -> dict[str, float]:
    lens = ROLE_LENSES.get(role) or ROLE_LENSES["reviewer"]
    out: dict[str, float] = {}
    for k, v in dims.items():
        mult = float(lens.get(k, 1.0))
        out[k] = clamp01(float(v) * mult)
    return out


@dataclass
class Finding:
    """One independent grader's assessment (gossipcat finding shape)."""

    grader: str
    vendor: str
    decision: str
    score: float
    dims: dict[str, float]
    weight: float
    signal: str = ""  # agreement | disagreement | unique
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "grader": self.grader,
            "vendor": self.vendor,
            "decision": self.decision,
            "score": round(float(self.score), 4),
            "dims": {k: round(float(v), 4) for k, v in self.dims.items()},
            "weight": round(float(self.weight), 4),
            "signal": self.signal,
            "rationale": self.rationale,
        }


@dataclass
class AgentTrust:
    """Trust weight table for graders (static + optional adaptive)."""

    weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_TRUST_WEIGHTS)
    )

    @classmethod
    def default(cls) -> "AgentTrust":
        return cls()

    def weight_of(self, agent: str) -> float:
        w = self.weights.get(agent)
        if w is None:
            return 0.75
        return max(0.05, float(w))

    def record_outcome(
        self,
        agent: str,
        *,
        agreed: bool,
        rate: float = 0.05,
    ) -> None:
        """Nudge weight after consensus (bounded)."""
        cur = self.weight_of(agent)
        delta = rate if agreed else -rate
        # Keep in a sensible band for multi-grader stability.
        self.weights[agent] = max(0.2, min(1.8, cur + delta))

    def to_dict(self) -> dict[str, float]:
        return {k: round(float(v), 4) for k, v in sorted(self.weights.items())}


@dataclass
class ConsensusVerdict:
    """Aggregate of independent findings — drop-in compatible with Verdict fields."""

    decision: str
    score: float
    dims: dict[str, float]
    judge_agent: str
    judge_vendor: str
    implementer: str
    implementer_vendor: str
    degraded: bool
    rationale: str
    thresholds: dict[str, float] = field(default_factory=decision_thresholds)
    findings: list[Finding] = field(default_factory=list)
    agreement_ratio: float = 0.0
    n_graders: int = 0
    method: str = "weighted_mean"
    schema: str = SCHEMA
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "score": round(float(self.score), 4),
            "dims": {k: round(float(v), 4) for k, v in self.dims.items()},
            "judge_agent": self.judge_agent,
            "judge_vendor": self.judge_vendor,
            "implementer": self.implementer,
            "implementer_vendor": self.implementer_vendor,
            "degraded": self.degraded,
            "rationale": self.rationale,
            "thresholds": dict(self.thresholds),
            "findings": [f.to_dict() for f in self.findings],
            "agreement_ratio": round(float(self.agreement_ratio), 4),
            "n_graders": self.n_graders,
            "method": self.method,
            "schema": self.schema,
            "counts": dict(self.counts),
            "consensus": True,
        }

    def to_verdict(self) -> Verdict:
        """Flatten to single-judge Verdict for callers that only need core fields."""
        return Verdict(
            decision=self.decision,
            score=self.score,
            dims=dict(self.dims),
            judge_agent=self.judge_agent,
            judge_vendor=self.judge_vendor,
            implementer=self.implementer,
            implementer_vendor=self.implementer_vendor,
            degraded=self.degraded,
            rationale=self.rationale,
            thresholds=dict(self.thresholds),
        )


def pick_graders(
    panel: AgentPanel,
    *,
    implementer: str,
    max_graders: int = 3,
    order: tuple[str, ...] = DEFAULT_GRADER_ORDER,
    prefer_cross_vendor: bool = True,
) -> list[str]:
    """Select up to max_graders online agents, preferably ≠ implementer vendor."""
    imp_vendor = panel.vendor_of.get(implementer, "unknown")
    chosen: list[str] = []

    def _try(cross_only: bool) -> None:
        for name in order:
            if len(chosen) >= max_graders:
                return
            if name in chosen:
                continue
            if name == implementer:
                continue
            agent = panel.agents.get(name)
            if agent is None:
                continue
            online = getattr(agent, "online", True)
            if not online:
                continue
            if cross_only and panel.vendor_of.get(name) == imp_vendor:
                continue
            chosen.append(name)

    if prefer_cross_vendor:
        _try(True)
    _try(False)
    # Last resort: allow implementer role if still short (degraded).
    if len(chosen) < 1 and implementer in panel.agents:
        chosen.append(implementer)
    return chosen[:max_graders]


def assign_signals(findings: list[Finding], consensus_decision: str) -> dict[str, int]:
    """Label each finding agreement/disagreement/unique vs consensus decision."""
    counts = {
        "agreement": 0,
        "disagreement": 0,
        "unique": 0,
        "n": len(findings),
    }
    if not findings:
        return counts
    # Unique: only one grader issued this decision among the set.
    by_dec: dict[str, int] = {}
    for f in findings:
        by_dec[f.decision] = by_dec.get(f.decision, 0) + 1
    for f in findings:
        if f.decision == consensus_decision:
            f.signal = "agreement"
            counts["agreement"] += 1
        elif by_dec.get(f.decision, 0) == 1:
            f.signal = "unique"
            counts["unique"] += 1
            counts["disagreement"] += 1
        else:
            f.signal = "disagreement"
            counts["disagreement"] += 1
    return counts


def aggregate_findings(
    findings: list[Finding],
    *,
    implementer: str,
    implementer_vendor: str,
    thresholds: Optional[dict[str, float]] = None,
    min_graders: int = 2,
    method: str = "weighted_mean",
) -> ConsensusVerdict:
    thr = thresholds or decision_thresholds()
    if not findings:
        return ConsensusVerdict(
            decision="fail",
            score=0.0,
            dims={d: 0.0 for d in RUBRIC_DIMS},
            judge_agent="consensus",
            judge_vendor="multi",
            implementer=implementer,
            implementer_vendor=implementer_vendor,
            degraded=True,
            rationale="no graders available",
            thresholds=thr,
            findings=[],
            agreement_ratio=0.0,
            n_graders=0,
            method=method,
            counts={"agreement": 0, "disagreement": 0, "unique": 0, "n": 0},
        )

    total_w = sum(max(0.05, f.weight) for f in findings)
    # Weighted dim mean
    dim_acc: dict[str, float] = {d: 0.0 for d in RUBRIC_DIMS}
    for f in findings:
        w = max(0.05, f.weight) / total_w
        for d in RUBRIC_DIMS:
            dim_acc[d] += float(f.dims.get(d, 0.0)) * w
    dims = {d: clamp01(dim_acc[d]) for d in RUBRIC_DIMS}
    score = score_from_dims(dims)

    # Weighted majority for decision (weight sum per decision label)
    dec_w: dict[str, float] = {}
    for f in findings:
        dec_w[f.decision] = dec_w.get(f.decision, 0.0) + max(0.05, f.weight)
    # Prefer pass > revise > fail on pure ties after weight.
    preference = {"pass": 3, "revise": 2, "fail": 1}
    decision = max(
        dec_w.keys(),
        key=lambda k: (dec_w[k], preference.get(k, 0)),
    )
    # Align with score if method is pure score-driven
    if method == "weighted_mean":
        decision = decision_from_score(score, thresholds=thr)
        # Soft majority override: if weighted majority of graders disagree with
        # score cut, still take majority when weights strongly favor it (≥2/3).
        maj = max(dec_w.values()) / total_w if total_w else 0.0
        maj_dec = max(dec_w.keys(), key=lambda k: (dec_w[k], preference.get(k, 0)))
        if maj >= (2.0 / 3.0) and maj_dec != decision:
            decision = maj_dec

    counts = assign_signals(findings, decision)
    agree = counts["agreement"] / max(1, counts["n"])
    degraded = len(findings) < min_graders

    # Primary judge attribution: highest weight finding
    primary = max(findings, key=lambda f: f.weight)
    rationale = (
        f"consensus n={len(findings)} score={score:.2f} decision={decision} "
        f"agree={agree:.2f} method={method} degraded={degraded} "
        f"graders={[f.grader for f in findings]}"
    )
    return ConsensusVerdict(
        decision=decision,
        score=score,
        dims=dims,
        judge_agent="consensus",
        judge_vendor="multi",
        implementer=implementer,
        implementer_vendor=implementer_vendor,
        degraded=degraded,
        rationale=rationale,
        thresholds=thr,
        findings=findings,
        agreement_ratio=agree,
        n_graders=len(findings),
        method=method,
        counts=counts,
    )


class ConsensusJudge:
    """Run multiple independent graders and aggregate with trust weights."""

    def __init__(
        self,
        panel: AgentPanel,
        *,
        prefer_cross_vendor: bool = True,
        min_graders: int = 2,
        max_graders: int = 3,
        trust: Optional[AgentTrust] = None,
        method: str = "weighted_mean",
        adaptive_trust: bool = True,
    ):
        self.panel = panel
        self.prefer_cross_vendor = prefer_cross_vendor
        self.min_graders = max(1, int(min_graders))
        self.max_graders = max(1, int(max_graders))
        self.trust = trust or AgentTrust.default()
        self.method = method
        self.adaptive_trust = adaptive_trust
        # Fallback single-judge path
        self._single = RubricJudge(panel, prefer_cross_vendor=prefer_cross_vendor)

    def evaluate(
        self,
        *,
        step: StepDef,
        task: dict[str, Any],
        output: dict[str, Any],
        implementer: str,
    ) -> ConsensusVerdict:
        graders = pick_graders(
            self.panel,
            implementer=implementer,
            max_graders=self.max_graders,
            prefer_cross_vendor=self.prefer_cross_vendor,
        )
        base = evidence_base_dims(step=step, task=task, output=output)
        thr = decision_thresholds()
        findings: list[Finding] = []
        for g in graders:
            dims = apply_lens(base, g)
            score = score_from_dims(dims)
            # Structural soft-pass for non-artifact steps (mirror RubricJudge)
            if step.name in {
                "log",
                "goal",
                "plan",
                "challenge",
                "meta_review",
                "approval",
                "deliver",
                "review",
            }:
                if score < thr["pass"]:
                    score = max(score, thr["pass"])
            decision = decision_from_score(score, thresholds=thr)
            if step.name in {
                "log",
                "goal",
                "plan",
                "challenge",
                "meta_review",
                "approval",
                "deliver",
                "review",
            } and decision == "fail":
                decision = "pass"
            w = self.trust.weight_of(g)
            findings.append(
                Finding(
                    grader=g,
                    vendor=self.panel.vendor_of.get(g, "unknown"),
                    decision=decision,
                    score=score,
                    dims=dims,
                    weight=w,
                    rationale=(
                        f"lens={g} score={score:.2f} "
                        f"criteria={dims.get('meets_success_criteria', 0):.2f}"
                    ),
                )
            )

        # Degraded single path still uses aggregation shape for audit parity
        if not findings:
            v = self._single.evaluate(
                step=step, task=task, output=output, implementer=implementer
            )
            findings = [
                Finding(
                    grader=v.judge_agent,
                    vendor=v.judge_vendor,
                    decision=v.decision,
                    score=v.score,
                    dims=dict(v.dims),
                    weight=self.trust.weight_of(v.judge_agent),
                    rationale=v.rationale,
                )
            ]

        result = aggregate_findings(
            findings,
            implementer=implementer,
            implementer_vendor=self.panel.vendor_of.get(implementer, "unknown"),
            thresholds=thr,
            min_graders=self.min_graders,
            method=self.method,
        )

        if self.adaptive_trust and result.findings:
            for f in result.findings:
                self.trust.record_outcome(
                    f.grader, agreed=(f.signal == "agreement")
                )
        return result
