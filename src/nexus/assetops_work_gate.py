"""Cedar promote gate for AssetOps work plans (arXiv 2606.26649 × IBM/AssetOpsBench).

Novel hybrid (portfolio cross_pattern):

  AssetOpsBench domain MCP plan (iot / fmsr / tsfm / wo / …)
                │
                ▼
         ┌──────────────┐   resource attrs: servers, write, ready, …
         │  work plane  │
         └──────┬───────┘
                │
                ▼
         ┌──────────────┐   Cedar Policy Language (fail-closed)
         │ validate_    │──► permit | forbid | deny_default
         │ work_promote │   before consensus / handoff promote
         └──────────────┘

Paper: *Autoformalization of Agent Instructions into Policy-as-Code*
https://arxiv.org/abs/2606.26649v1

GitHub pattern (shape only — not a vendored tree):
  IBM/AssetOpsBench — Industry 4.0 multi-agent benchmark with domain MCP
  servers (iot, fmsr, tsfm, wo, vibration, utilities) and plan-execute
  work order / diagnostic walks.

This module is the **Cedar validation step for domain work decisions**:
before promoting a multi-domain diagnostic plan (or consensus over it),
apply policy-as-code that encodes industrial work-plane rules
(e.g. no work-order write without IoT + FMSR evidence; diagnostic must
touch enough domain servers; plan must be ready).

Does **not** vendor AWS Cedar, AssetOpsBench trees, CouchDB, or industrial
backends. Reuses in-tree ``cedar_policy`` + ``assetops_planner`` shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Union

from . import assetops_planner as aop
from . import multi_llm_agent as mla
from .cedar_policy import (
    ACTION_PROMOTE,
    SCHEMA as CEDAR_SCHEMA,
    CedarDecision,
    PolicyStatement,
    authorize,
    default_promote_policies,
    evaluate_policies,
    make_request,
    resource_from_consensus,
    validate_promote as cedar_validate_promote,
)

SCHEMA = "nexus.assetops_work_gate/v1"
PROMOTE_SCHEMA = "nexus.assetops_work_gate.promote/v1"
PAPER = "arxiv:2606.26649v1"
SOURCE_PATTERN = aop.SOURCE_PATTERN  # IBM/AssetOpsBench
SOURCE_CEDAR = "arxiv:2606.26649v1"

# Domain servers that count as evidence planes for write promote.
EVIDENCE_SERVERS = frozenset(
    {
        aop.SERVER_IOT,
        aop.SERVER_FMSR,
        aop.SERVER_TSFM,
        aop.SERVER_VIBRATION,
        aop.SERVER_UTILITIES,
    }
)
# Minimum distinct domain MCP servers for a "healthy" diagnostic promote.
DEFAULT_MIN_DOMAINS = 3
# Write tools that require prior evidence domains (AssetOps work-order safety).
_WRITE_HINTS = frozenset(
    {
        "create_workorder",
        "update_workorder",
        "close_workorder",
        "raise_work_order",
        "write",
    }
)


class AssetOpsWorkGateError(ValueError):
    """Invalid plan / promote request for the AssetOps work gate."""


PlanLike = Union[mla.ToolPlan, dict[str, Any], None]
VerdictLike = Any


# ── plan → Cedar resource ────────────────────────────────────────────────────


def _plan_steps(plan: PlanLike) -> list[Any]:
    if plan is None:
        return []
    if isinstance(plan, mla.ToolPlan):
        return list(plan.steps or [])
    if isinstance(plan, dict):
        return list(plan.get("steps") or [])
    steps = getattr(plan, "steps", None)
    return list(steps or [])


def _plan_meta(plan: PlanLike) -> dict[str, Any]:
    if plan is None:
        return {}
    if isinstance(plan, mla.ToolPlan):
        return dict(plan.meta or {})
    if isinstance(plan, dict):
        meta = plan.get("meta")
        return dict(meta) if isinstance(meta, dict) else {}
    meta = getattr(plan, "meta", None)
    return dict(meta) if isinstance(meta, dict) else {}


def _plan_ready(plan: PlanLike) -> bool:
    if plan is None:
        return False
    if isinstance(plan, mla.ToolPlan):
        return bool(plan.is_ready())
    if isinstance(plan, dict):
        status = str(plan.get("status") or "").strip().lower()
        if status == mla.STATUS_READY:
            return True
        # meta stamp from plan_payload
        meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
        if meta.get("ready") is True:
            return True
        return status == "ready"
    if hasattr(plan, "is_ready") and callable(plan.is_ready):
        try:
            return bool(plan.is_ready())
        except Exception:
            pass
    return str(getattr(plan, "status", "") or "").lower() == mla.STATUS_READY


def _step_tool(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("tool") or "")
    return str(getattr(step, "tool", "") or "")


def _step_args(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        a = step.get("args")
        return dict(a) if isinstance(a, dict) else {}
    a = getattr(step, "args", None)
    return dict(a) if isinstance(a, dict) else {}


def servers_from_plan(plan: PlanLike) -> list[str]:
    """Distinct domain MCP servers touched by plan steps (ordered)."""
    seen: list[str] = []
    for step in _plan_steps(plan):
        tool = _step_tool(step)
        args = _step_args(step)
        srv = str(args.get("server") or "").strip().lower()
        if not srv and tool:
            srv = str(aop.parse_tool_id(tool).get("server") or "").strip().lower()
        if srv and srv not in seen:
            seen.append(srv)
    meta = _plan_meta(plan)
    # Prefer meta.n_servers_touched consistency: do not invent servers.
    return seen


def write_tools_from_plan(plan: PlanLike) -> list[str]:
    """Tool ids that look like write / work-order mutation steps."""
    out: list[str] = []
    for step in _plan_steps(plan):
        tool = _step_tool(step)
        if not tool:
            continue
        parsed = aop.parse_tool_id(tool)
        bare = str(parsed.get("tool") or tool).lower()
        priv = str(_step_args(step).get("privilege") or "").lower()
        if priv == "write" or bare in _WRITE_HINTS or any(
            h in bare for h in _WRITE_HINTS
        ):
            out.append(tool)
    return out


def resource_from_work(
    plan: PlanLike = None,
    verdict: VerdictLike = None,
    *,
    execution: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    min_domains: int = DEFAULT_MIN_DOMAINS,
) -> dict[str, Any]:
    """Project AssetOps plan (+ optional consensus) into a Cedar resource entity.

    Combines consensus score/decision attrs (arXiv 2606.26649) with
    AssetOpsBench domain-MCP plan geometry (servers, write, readiness).
    """
    # Base consensus-shaped resource (decision/score/agreement/degraded/…)
    if verdict is not None:
        base = resource_from_consensus(verdict)
    else:
        # Plan-only promote path: optimistic defaults; policies still
        # enforce readiness / domain completeness / write safety.
        base = {
            "type": "ConsensusDecision",
            "decision": "pass",
            "score": 1.0,
            "agreement_ratio": 1.0,
            "degraded": False,
            "n_graders": 1,
            "method": "plan_only",
            "implementer": "",
            "judge_agent": "assetops_work_gate",
        }

    servers = servers_from_plan(plan)
    writes = write_tools_from_plan(plan)
    meta = _plan_meta(plan)
    n_steps = len(_plan_steps(plan))
    n_servers = len(servers)
    meta_n = meta.get("n_servers_touched")
    if isinstance(meta_n, int) and meta_n > n_servers:
        # meta may count more when plan was built with that stamp
        n_servers = max(n_servers, int(meta_n))

    # Execution summary can narrow "evidence actually hit"
    exec_servers: list[str] = []
    if isinstance(execution, dict):
        hit = execution.get("servers_hit")
        if isinstance(hit, (list, tuple)):
            exec_servers = [str(s).strip().lower() for s in hit if s]
        if execution.get("ok") is False:
            base["decision"] = str(base.get("decision") or "fail")
            if base["decision"] == "pass":
                base["decision"] = "fail"
            base["score"] = min(float(base.get("score") or 0.0), 0.4)

    has = {sid: (sid in servers) for sid in aop.DOMAIN_SERVER_IDS}
    # If execution reported hits, require evidence from executed set for flags
    evidence_pool = set(exec_servers) if exec_servers else set(servers)

    resource: dict[str, Any] = {
        **base,
        "type": "AssetOpsWorkDecision",
        "schema": SCHEMA,
        "source_pattern": SOURCE_PATTERN,
        "paper": PAPER,
        "plan_ready": _plan_ready(plan),
        "n_steps": n_steps,
        "n_servers_touched": n_servers,
        "servers": list(servers),
        "servers_csv": ",".join(servers),
        "has_iot": aop.SERVER_IOT in evidence_pool or has.get(aop.SERVER_IOT, False),
        "has_fmsr": aop.SERVER_FMSR in evidence_pool or has.get(aop.SERVER_FMSR, False),
        "has_tsfm": aop.SERVER_TSFM in evidence_pool or has.get(aop.SERVER_TSFM, False),
        "has_wo": aop.SERVER_WO in servers or has.get(aop.SERVER_WO, False),
        "has_utilities": aop.SERVER_UTILITIES in servers
        or has.get(aop.SERVER_UTILITIES, False),
        "has_vibration": aop.SERVER_VIBRATION in servers
        or has.get(aop.SERVER_VIBRATION, False),
        "has_write": bool(writes),
        "write_count": len(writes),
        "write_tools": list(writes),
        "workflow": str(meta.get("workflow") or ("diagnostic" if n_servers >= 3 else "custom")),
        "min_domains": int(min_domains),
        "min_domains_met": n_servers >= int(min_domains),
        "site_name": str(meta.get("site_name") or ""),
        "asset_id": str(meta.get("asset_id") or ""),
        "asset_class": str(meta.get("asset_class") or ""),
        "executed": bool(exec_servers),
        "n_servers_executed": len(exec_servers),
    }
    if extra:
        resource.update(extra)
    return resource


# ── domain-aware Cedar policy set ────────────────────────────────────────────


def default_assetops_promote_policies(
    *,
    min_score: float = 0.7,
    min_agreement: float = 0.5,
    min_graders: int = 1,
    min_domains: int = DEFAULT_MIN_DOMAINS,
    require_iot_for_write: bool = True,
    require_fmsr_for_write: bool = True,
) -> list[PolicyStatement]:
    """Cedar policies for promoting AssetOps work / consensus decisions.

    Layers:

    1. Base consensus promote forbids/permits (score, degraded, fail, …)
    2. AssetOpsBench work-plane rules (plan ready, multi-domain, write safety)
    """
    # Start from consensus defaults but relax min_graders default to 1 for
    # plan-only path; callers pass min_graders=2 for multi-grader consensus.
    base = default_promote_policies(
        min_score=min_score,
        min_agreement=min_agreement,
        min_graders=min_graders,
    )
    domain: list[PolicyStatement] = [
        PolicyStatement(
            effect="forbid",
            action=ACTION_PROMOTE,
            policy_id="forbid-unready-plan",
            description="refuse promote when AssetOps plan is not ready",
            when=[("resource.plan_ready", "==", False)],
            raw="forbid (...) when { resource.plan_ready == false };",
        ),
        PolicyStatement(
            effect="forbid",
            action=ACTION_PROMOTE,
            policy_id="forbid-empty-plan",
            description="refuse promote when plan has no steps",
            when=[("resource.n_steps", "<", 1)],
            raw="forbid (...) when { resource.n_steps < 1 };",
        ),
        PolicyStatement(
            effect="forbid",
            action=ACTION_PROMOTE,
            policy_id="forbid-thin-diagnostic",
            description=(
                f"refuse diagnostic promote when n_servers_touched < {min_domains}"
            ),
            when=[
                ("resource.workflow", "==", "diagnostic"),
                ("resource.n_servers_touched", "<", int(min_domains)),
            ],
            raw=(
                "forbid (...) when {\n"
                '  resource.workflow == "diagnostic" &&\n'
                f"  resource.n_servers_touched < {int(min_domains)}\n"
                "};"
            ),
        ),
    ]
    if require_iot_for_write:
        domain.append(
            PolicyStatement(
                effect="forbid",
                action=ACTION_PROMOTE,
                policy_id="forbid-write-without-iot",
                description="refuse work-order write promote without IoT evidence",
                when=[
                    ("resource.has_write", "==", True),
                    ("resource.has_iot", "==", False),
                ],
                raw=(
                    "forbid (...) when {\n"
                    "  resource.has_write == true &&\n"
                    "  resource.has_iot == false\n"
                    "};"
                ),
            )
        )
    if require_fmsr_for_write:
        domain.append(
            PolicyStatement(
                effect="forbid",
                action=ACTION_PROMOTE,
                policy_id="forbid-write-without-fmsr",
                description="refuse work-order write promote without FMSR evidence",
                when=[
                    ("resource.has_write", "==", True),
                    ("resource.has_fmsr", "==", False),
                ],
                raw=(
                    "forbid (...) when {\n"
                    "  resource.has_write == true &&\n"
                    "  resource.has_fmsr == false\n"
                    "};"
                ),
            )
        )
    # Explicit permits for healthy AssetOps work (in addition to base permits).
    domain.append(
        PolicyStatement(
            effect="permit",
            action=ACTION_PROMOTE,
            policy_id="permit-healthy-domain-pass",
            description="allow promote for healthy multi-domain AssetOps pass",
            when=[
                ("resource.decision", "==", "pass"),
                ("resource.score", ">=", float(min_score)),
                ("resource.plan_ready", "==", True),
                ("resource.n_steps", ">=", 1),
                ("resource.degraded", "==", False),
                ("resource.min_domains_met", "==", True),
            ],
            raw=(
                "permit (...) when {\n"
                '  resource.decision == "pass" &&\n'
                f"  resource.score >= {min_score} &&\n"
                "  resource.plan_ready == true &&\n"
                "  resource.min_domains_met == true\n"
                "};"
            ),
        )
    )
    domain.append(
        PolicyStatement(
            effect="permit",
            action=ACTION_PROMOTE,
            policy_id="permit-healthy-write-pass",
            description="allow write promote when IoT+FMSR evidence present",
            when=[
                ("resource.decision", "==", "pass"),
                ("resource.score", ">=", float(min_score)),
                ("resource.plan_ready", "==", True),
                ("resource.has_write", "==", True),
                ("resource.has_iot", "==", True),
                ("resource.has_fmsr", "==", True),
                ("resource.degraded", "==", False),
            ],
            raw=(
                "permit (...) when {\n"
                '  resource.decision == "pass" &&\n'
                "  resource.has_write == true &&\n"
                "  resource.has_iot == true &&\n"
                "  resource.has_fmsr == true\n"
                "};"
            ),
        )
    )
    # Forbid statements first (evaluation order is forbid>permit anyway, but
    # listing domain forbids before base keeps audit dumps readable).
    forbids = [p for p in domain if p.effect == "forbid"]
    permits = [p for p in domain if p.effect == "permit"]
    base_forbids = [p for p in base if p.effect == "forbid"]
    base_permits = [p for p in base if p.effect == "permit"]
    return forbids + base_forbids + permits + base_permits


def default_assetops_promote_cedar_text(
    *,
    min_score: float = 0.7,
    min_agreement: float = 0.5,
    min_graders: int = 1,
    min_domains: int = DEFAULT_MIN_DOMAINS,
) -> str:
    """Human-readable Cedar dump of the AssetOps work promote policy set."""
    policies = default_assetops_promote_policies(
        min_score=min_score,
        min_agreement=min_agreement,
        min_graders=min_graders,
        min_domains=min_domains,
    )
    header = (
        f"// {SCHEMA} — AssetOps work promote (Cedar × domain MCP)\n"
        f"// paper={PAPER} pattern={SOURCE_PATTERN}\n"
        f"// min_score={min_score} min_domains={min_domains} "
        f"min_graders={min_graders}\n\n"
    )
    return header + "\n\n".join(p.to_cedar() for p in policies) + "\n"


# ── public gate API ──────────────────────────────────────────────────────────


def validate_work_promote(
    plan: PlanLike = None,
    verdict: VerdictLike = None,
    *,
    principal: str = "assetops_work_gate",
    policies: Optional[list[PolicyStatement]] = None,
    min_score: float = 0.7,
    min_agreement: float = 0.5,
    min_graders: int = 1,
    min_domains: int = DEFAULT_MIN_DOMAINS,
    execution: Optional[dict[str, Any]] = None,
    extra_resource: Optional[dict[str, Any]] = None,
    require_iot_for_write: bool = True,
    require_fmsr_for_write: bool = True,
) -> CedarDecision:
    """Cedar Policy Language validation before promoting an AssetOps work decision.

    Integration point for arXiv 2606.26649 inside the AssetOps work plane:
    domain plan (+ optional multi-grader consensus) must pass policy-as-code
    before promotion / handoff is allowed. Fail-closed.
    """
    resource = resource_from_work(
        plan,
        verdict,
        execution=execution,
        extra=extra_resource,
        min_domains=min_domains,
    )
    pols = (
        policies
        if policies is not None
        else default_assetops_promote_policies(
            min_score=min_score,
            min_agreement=min_agreement,
            min_graders=min_graders,
            min_domains=min_domains,
            require_iot_for_write=require_iot_for_write,
            require_fmsr_for_write=require_fmsr_for_write,
        )
    )
    return authorize(
        principal=principal,
        action=ACTION_PROMOTE,
        resource=resource,
        policies=pols,
        min_score=min_score,
        min_agreement=min_agreement,
        min_graders=min_graders,
    )


@dataclass
class WorkPromoteReport:
    """Audit blob for an AssetOps work promote attempt."""

    ok: bool
    allowed: bool
    principal: str = "assetops_work_gate"
    schema: str = PROMOTE_SCHEMA
    cedar_schema: str = CEDAR_SCHEMA
    work_schema: str = SCHEMA
    paper: str = PAPER
    source_pattern: str = SOURCE_PATTERN
    reason: str = ""
    cedar_policy: dict[str, Any] = field(default_factory=dict)
    resource: dict[str, Any] = field(default_factory=dict)
    decision: str = ""
    score: float = 0.0
    plan_ready: bool = False
    n_servers_touched: int = 0
    has_write: bool = False
    servers: list[str] = field(default_factory=list)
    policy_text_preview: str = ""
    require: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ok": self.ok,
            "allowed": self.allowed,
            "require": self.require,
            "principal": self.principal,
            "paper": self.paper,
            "source_pattern": self.source_pattern,
            "work_schema": self.work_schema,
            "cedar_schema": self.cedar_schema,
            "cedar_policy": dict(self.cedar_policy),
            "resource": dict(self.resource),
            "decision": self.decision,
            "score": self.score,
            "plan_ready": self.plan_ready,
            "n_servers_touched": self.n_servers_touched,
            "has_write": self.has_write,
            "servers": list(self.servers),
            "reason": self.reason,
            "policy_text_preview": self.policy_text_preview,
        }


def promote_work_decision(
    plan: PlanLike = None,
    verdict: VerdictLike = None,
    *,
    principal: str = "assetops_work_gate",
    min_score: float = 0.7,
    min_agreement: float = 0.5,
    min_graders: int = 1,
    min_domains: int = DEFAULT_MIN_DOMAINS,
    execution: Optional[dict[str, Any]] = None,
    require: bool = True,
    policies: Optional[list[PolicyStatement]] = None,
) -> dict[str, Any]:
    """Validate then (soft) promote an AssetOps work decision under Cedar policy.

    Returns a ``nexus.assetops_work_gate.promote/v1`` audit blob. When
    *require* is True and policy denies, ``ok`` is False (fail-closed).
    Does not mutate external state — pure gate + audit.
    """
    resource = resource_from_work(
        plan,
        verdict,
        execution=execution,
        min_domains=min_domains,
    )
    gate = validate_work_promote(
        plan,
        verdict,
        principal=principal,
        policies=policies,
        min_score=min_score,
        min_agreement=min_agreement,
        min_graders=min_graders,
        min_domains=min_domains,
        execution=execution,
    )
    # Optionally stamp consensus verdict when present.
    if verdict is not None and hasattr(verdict, "promote_allowed"):
        try:
            verdict.promote_allowed = bool(gate.allowed)
            verdict.cedar_policy = gate.to_dict()
        except Exception:
            pass

    preview = default_assetops_promote_cedar_text(
        min_score=min_score,
        min_agreement=min_agreement,
        min_graders=min_graders,
        min_domains=min_domains,
    )
    # Compact window: prefer domain forbid + permit heads
    window = preview
    for needle in ("forbid-write-without-iot", "forbid-unready-plan", "\npermit "):
        i = preview.find(needle)
        if i >= 0:
            start = max(0, i - 80)
            window = preview[start : start + 500]
            break
    else:
        window = preview[:500]

    ok = bool(gate.allowed)
    report = WorkPromoteReport(
        ok=ok,
        allowed=ok,
        principal=principal,
        require=bool(require),
        reason=(gate.reasons[0] if gate.reasons else gate.decision),
        cedar_policy=gate.to_dict(),
        resource=resource,
        decision=str(resource.get("decision") or ""),
        score=float(resource.get("score") or 0.0),
        plan_ready=bool(resource.get("plan_ready")),
        n_servers_touched=int(resource.get("n_servers_touched") or 0),
        has_write=bool(resource.get("has_write")),
        servers=list(resource.get("servers") or []),
        policy_text_preview=window,
    )
    return report.to_dict()


def gate_plan_for_handoff(
    plan: PlanLike,
    *,
    verdict: VerdictLike = None,
    principal: str = "assetops_work_gate",
    min_domains: int = DEFAULT_MIN_DOMAINS,
    min_score: float = 0.7,
    require: bool = True,
) -> dict[str, Any]:
    """Convenience: promote gate on a ready AssetOps plan before orchestrator handoff.

    Soft integration surface for :mod:`nexus.assetops_planner` plan_and_handoff /
    plan_and_run callers that want Cedar fail-closed before execution.
    """
    if plan is None:
        raise AssetOpsWorkGateError("plan is required for handoff gate")
    return promote_work_decision(
        plan,
        verdict,
        principal=principal,
        min_domains=min_domains,
        min_score=min_score,
        require=require,
        min_graders=1 if verdict is None else 2,
    )


def consensus_with_work_gate(
    verdict: VerdictLike,
    plan: PlanLike = None,
    *,
    principal: str = "consensus",
    min_score: Optional[float] = None,
    min_agreement: float = 0.5,
    min_graders: int = 2,
    min_domains: int = DEFAULT_MIN_DOMAINS,
    require: bool = True,
) -> dict[str, Any]:
    """Run the hybrid gate: multi-grader consensus *and* AssetOps work geometry.

    Prefer this over bare ``consensus.promote_decision`` when the decision
    concerns a domain MCP / diagnostic work plan.
    """
    thr = 0.7
    if min_score is not None:
        thr = float(min_score)
    elif hasattr(verdict, "thresholds") and isinstance(verdict.thresholds, dict):
        thr = float(verdict.thresholds.get("pass", 0.7))
    elif isinstance(verdict, dict) and isinstance(verdict.get("thresholds"), dict):
        thr = float(verdict["thresholds"].get("pass", 0.7))

    work = promote_work_decision(
        plan,
        verdict,
        principal=principal,
        min_score=thr,
        min_agreement=min_agreement,
        min_graders=min_graders,
        min_domains=min_domains,
        require=require,
    )
    # Also surface plain consensus cedar for dual-audit when no plan.
    if plan is None:
        plain = cedar_validate_promote(
            verdict,
            principal=principal,
            min_score=thr,
            min_agreement=min_agreement,
            min_graders=min_graders,
        )
        work["consensus_cedar"] = plain.to_dict()
    work["hybrid"] = True
    work["schema"] = PROMOTE_SCHEMA
    return work


# ── module CLI ───────────────────────────────────────────────────────────────


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json
    import sys

    p = argparse.ArgumentParser(
        prog="python -m nexus.assetops_work_gate",
        description=(
            "Cedar × AssetOpsBench work promote gate "
            f"({PAPER} × {SOURCE_PATTERN})"
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_pol = sub.add_parser("policies", help="print default Cedar promote policies")
    p_pol.add_argument("--min-domains", type=int, default=DEFAULT_MIN_DOMAINS)
    p_pol.add_argument("--min-score", type=float, default=0.7)
    p_pol.add_argument("--json", action="store_true")

    p_diag = sub.add_parser(
        "check-diagnostic",
        help="build diagnostic plan and run promote gate",
    )
    p_diag.add_argument(
        "task",
        nargs="?",
        default="diagnose chiller asset failure and list work orders",
    )
    p_diag.add_argument("--write", action="store_true", help="include WO create")
    p_diag.add_argument("--vibration", action="store_true")
    p_diag.add_argument("--min-domains", type=int, default=DEFAULT_MIN_DOMAINS)
    p_diag.add_argument("--json", action="store_true")

    p_gate = sub.add_parser("gate", help="gate a ready diagnostic (alias of check)")
    p_gate.add_argument(
        "task",
        nargs="?",
        default="diagnose chiller asset failure and list work orders",
    )
    p_gate.add_argument("--write", action="store_true")
    p_gate.add_argument("--json", action="store_true")

    args = p.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "policies":
        text = default_assetops_promote_cedar_text(
            min_score=float(args.min_score),
            min_domains=int(args.min_domains),
        )
        if args.json:
            pols = default_assetops_promote_policies(
                min_score=float(args.min_score),
                min_domains=int(args.min_domains),
            )
            print(json.dumps([x.to_dict() for x in pols], indent=2))
        else:
            print(text)
        return 0

    if args.cmd in {"check-diagnostic", "gate"}:
        write = bool(getattr(args, "write", False))
        vib = bool(getattr(args, "vibration", False))
        min_d = int(getattr(args, "min_domains", DEFAULT_MIN_DOMAINS))
        plan = aop.diagnostic_workflow_plan(
            str(args.task),
            include_vibration=vib,
            include_workorder_write=write,
        )
        report = promote_work_decision(plan, min_domains=min_d)
        if getattr(args, "json", False):
            print(json.dumps(report, indent=2, default=str))
        else:
            status = "ALLOW" if report["ok"] else "DENY"
            print(f"{status}  reason={report.get('reason')}")
            print(
                f"  servers={report.get('servers')} "
                f"n={report.get('n_servers_touched')} "
                f"write={report.get('has_write')} "
                f"ready={report.get('plan_ready')}"
            )
            print(f"  schema={report.get('schema')} paper={PAPER}")
        return 0 if report["ok"] else 2

    p.error(f"unknown cmd {args.cmd}")
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    return _cli(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "SCHEMA",
    "PROMOTE_SCHEMA",
    "PAPER",
    "SOURCE_PATTERN",
    "SOURCE_CEDAR",
    "DEFAULT_MIN_DOMAINS",
    "EVIDENCE_SERVERS",
    "AssetOpsWorkGateError",
    "WorkPromoteReport",
    "servers_from_plan",
    "write_tools_from_plan",
    "resource_from_work",
    "default_assetops_promote_policies",
    "default_assetops_promote_cedar_text",
    "validate_work_promote",
    "promote_work_decision",
    "gate_plan_for_handoff",
    "consensus_with_work_gate",
    "main",
]
