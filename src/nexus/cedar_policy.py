"""Cedar-shaped policy-as-code validation (arXiv 2606.26649 pattern).

Autoformalize agent / consensus *instructions* into fail-closed Policy-as-Code
before a decision is promoted. Shape only — does **not** vendor AWS Cedar /
``cedar-policy`` crates or the paper's full autoformalizer.

Supported subset (enough for consensus promote gates):

.. code-block:: text

    permit (
      principal,
      action == Action::"promote",
      resource
    ) when {
      resource.decision == "pass" &&
      resource.score >= 0.7
    };

    forbid (
      principal,
      action == Action::"promote",
      resource
    ) when { resource.degraded == true };

Evaluation order (Cedar-like):

1. Any matching **forbid** → Deny
2. Else any matching **permit** → Allow
3. Else **default Deny** (fail-closed for promote)

Evidence drivers:
- arXiv 2606.26649 — Autoformalization of Agent Instructions into Policy-as-Code
- AWS Cedar authorization model (shape only)
- NEXUS consensus promote / IndependentVerify gates
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

SCHEMA = "nexus.cedar_policy/v1"
ACTION_PROMOTE = "promote"

# Condition atom: (path, op, value) — path uses dotted resource.* / principal.*
Condition = tuple[str, str, Any]


@dataclass
class PolicyStatement:
    """One permit/forbid statement (Cedar-shaped)."""

    effect: str  # permit | forbid
    action: str = ACTION_PROMOTE
    when: list[Condition] = field(default_factory=list)
    # when_any: list of AND-groups OR'd together (empty → match all attrs)
    when_any: list[list[Condition]] = field(default_factory=list)
    policy_id: str = ""
    raw: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect": self.effect,
            "action": self.action,
            "when": [list(c) for c in self.when],
            "when_any": [[list(c) for c in g] for g in self.when_any],
            "policy_id": self.policy_id,
            "description": self.description,
            "raw": self.raw,
        }

    def to_cedar(self) -> str:
        """Serialize to a readable Cedar-like snippet."""
        effect = self.effect if self.effect in {"permit", "forbid"} else "permit"
        conds = self.when
        if self.when_any and not conds:
            # single-group OR not expressible cleanly; join first group
            conds = self.when_any[0] if self.when_any else []
        body = _conditions_to_cedar(conds) if conds else "true"
        pid = f"// {self.policy_id}\n" if self.policy_id else ""
        return (
            f"{pid}{effect} (\n"
            f"  principal,\n"
            f'  action == Action::"{self.action}",\n'
            f"  resource\n"
            f") when {{\n"
            f"  {body}\n"
            f"}};"
        )


@dataclass
class CedarDecision:
    """Authorization outcome for one request."""

    allowed: bool
    decision: str  # permit | forbid | deny_default
    reasons: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    schema: str = SCHEMA
    action: str = ACTION_PROMOTE
    principal: str = ""
    resource: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": self.decision,
            "reasons": list(self.reasons),
            "matched": list(self.matched),
            "schema": self.schema,
            "action": self.action,
            "principal": self.principal,
            "resource": dict(self.resource),
        }


class CedarPolicyError(ValueError):
    """Invalid policy text or request shape."""


def _conditions_to_cedar(conds: list[Condition]) -> str:
    parts: list[str] = []
    for path, op, val in conds:
        if isinstance(val, bool):
            lit = "true" if val else "false"
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            lit = str(val)
        else:
            lit = f'"{val}"'
        parts.append(f"{path} {op} {lit}")
    return " &&\n  ".join(parts) if parts else "true"


def _resolve_path(request: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    if not parts:
        return None
    root = parts[0]
    if root in {"resource", "principal", "action", "context"}:
        cur: Any = request.get(root)
        parts = parts[1:]
    else:
        cur = request.get("resource")
    for p in parts:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = getattr(cur, p, None)
    return cur


def _compare(left: Any, op: str, right: Any) -> bool:
    if op == "==":
        if isinstance(right, bool) or isinstance(left, bool):
            return bool(left) is bool(right) if (
                isinstance(left, bool) or isinstance(right, bool)
            ) else left == right
        # numeric tolerance
        try:
            if isinstance(right, (int, float)) and not isinstance(right, bool):
                return float(left) == float(right)
        except (TypeError, ValueError):
            pass
        return left == right
    if op == "!=":
        return not _compare(left, "==", right)
    try:
        lf = float(left)
        rf = float(right)
    except (TypeError, ValueError):
        return False
    if op == "<":
        return lf < rf
    if op == "<=":
        return lf <= rf
    if op == ">":
        return lf > rf
    if op == ">=":
        return lf >= rf
    raise CedarPolicyError(f"unsupported operator: {op!r}")


def _conds_match(request: dict[str, Any], conds: list[Condition]) -> bool:
    for path, op, val in conds:
        left = _resolve_path(request, path)
        if not _compare(left, op, val):
            return False
    return True


def statement_matches(stmt: PolicyStatement, request: dict[str, Any]) -> bool:
    """True when action matches and when-clause holds."""
    action = str(request.get("action") or "")
    if stmt.action and stmt.action != action:
        return False
    # when_any: OR of AND-groups
    if stmt.when_any:
        return any(_conds_match(request, g) for g in stmt.when_any)
    if stmt.when:
        return _conds_match(request, stmt.when)
    # empty when → matches any resource for this action
    return True


def evaluate_policies(
    policies: list[PolicyStatement],
    request: dict[str, Any],
) -> CedarDecision:
    """Cedar evaluation: forbid > permit > deny_default."""
    principal = ""
    p = request.get("principal")
    if isinstance(p, dict):
        principal = str(p.get("id") or p.get("name") or "")
    else:
        principal = str(p or "")
    resource = request.get("resource") if isinstance(request.get("resource"), dict) else {}
    action = str(request.get("action") or ACTION_PROMOTE)

    forbids = [s for s in policies if s.effect == "forbid" and statement_matches(s, request)]
    if forbids:
        ids = [s.policy_id or s.effect for s in forbids]
        reasons = [
            s.description or f"forbid matched: {s.policy_id or s.to_cedar()[:60]}"
            for s in forbids
        ]
        return CedarDecision(
            allowed=False,
            decision="forbid",
            reasons=reasons,
            matched=ids,
            action=action,
            principal=principal,
            resource=dict(resource or {}),
        )

    permits = [s for s in policies if s.effect == "permit" and statement_matches(s, request)]
    if permits:
        ids = [s.policy_id or s.effect for s in permits]
        reasons = [
            s.description or f"permit matched: {s.policy_id or 'permit'}"
            for s in permits
        ]
        return CedarDecision(
            allowed=True,
            decision="permit",
            reasons=reasons,
            matched=ids,
            action=action,
            principal=principal,
            resource=dict(resource or {}),
        )

    return CedarDecision(
        allowed=False,
        decision="deny_default",
        reasons=["no permit matched (fail-closed)"],
        matched=[],
        action=action,
        principal=principal,
        resource=dict(resource or {}),
    )


# ---------------------------------------------------------------------------
# Default consensus-promote policy set (autoformalized agent instructions)
# ---------------------------------------------------------------------------

def default_promote_policies(
    *,
    min_score: float = 0.7,
    min_agreement: float = 0.5,
    min_graders: int = 2,
) -> list[PolicyStatement]:
    """Built-in policies for promoting a multi-grader consensus decision."""
    return [
        PolicyStatement(
            effect="forbid",
            action=ACTION_PROMOTE,
            policy_id="forbid-fail-decision",
            description="refuse promote when consensus decision is fail",
            when=[("resource.decision", "==", "fail")],
            raw='forbid (...) when { resource.decision == "fail" };',
        ),
        PolicyStatement(
            effect="forbid",
            action=ACTION_PROMOTE,
            policy_id="forbid-veto-decision",
            description="refuse promote on veto/reject/deny/blocked",
            when_any=[
                [("resource.decision", "==", "veto")],
                [("resource.decision", "==", "reject")],
                [("resource.decision", "==", "deny")],
                [("resource.decision", "==", "blocked")],
            ],
            raw='forbid (...) when { resource.decision in {"veto","reject","deny","blocked"} };',
        ),
        PolicyStatement(
            effect="forbid",
            action=ACTION_PROMOTE,
            policy_id="forbid-degraded",
            description="refuse promote when consensus ran degraded (< min graders)",
            when=[("resource.degraded", "==", True)],
            raw="forbid (...) when { resource.degraded == true };",
        ),
        PolicyStatement(
            effect="forbid",
            action=ACTION_PROMOTE,
            policy_id="forbid-low-score",
            description=f"refuse promote when score < {min_score}",
            when=[("resource.score", "<", float(min_score))],
            raw=f"forbid (...) when {{ resource.score < {min_score} }};",
        ),
        PolicyStatement(
            effect="forbid",
            action=ACTION_PROMOTE,
            policy_id="forbid-low-agreement",
            description=f"refuse promote when agreement_ratio < {min_agreement}",
            when=[("resource.agreement_ratio", "<", float(min_agreement))],
            raw=f"forbid (...) when {{ resource.agreement_ratio < {min_agreement} }};",
        ),
        PolicyStatement(
            effect="permit",
            action=ACTION_PROMOTE,
            policy_id="permit-healthy-pass",
            description="allow promote for healthy pass consensus",
            when=[
                ("resource.decision", "==", "pass"),
                ("resource.score", ">=", float(min_score)),
                ("resource.agreement_ratio", ">=", float(min_agreement)),
                ("resource.degraded", "==", False),
                ("resource.n_graders", ">=", int(min_graders)),
            ],
            raw=(
                "permit (...) when {\n"
                '  resource.decision == "pass" &&\n'
                f"  resource.score >= {min_score} &&\n"
                f"  resource.agreement_ratio >= {min_agreement} &&\n"
                "  resource.degraded == false &&\n"
                f"  resource.n_graders >= {min_graders}\n"
                "};"
            ),
        ),
        # Soft path: revise may promote only if score still clears threshold
        # (explicit permit; forbids above still win on low score / degraded).
        PolicyStatement(
            effect="permit",
            action=ACTION_PROMOTE,
            policy_id="permit-high-score-revise",
            description="allow promote for high-score revise with agreement",
            when=[
                ("resource.decision", "==", "revise"),
                ("resource.score", ">=", float(min_score)),
                ("resource.agreement_ratio", ">=", float(min_agreement)),
                ("resource.degraded", "==", False),
                ("resource.n_graders", ">=", int(min_graders)),
            ],
            raw=(
                "permit (...) when {\n"
                '  resource.decision == "revise" &&\n'
                f"  resource.score >= {min_score}\n"
                "};"
            ),
        ),
    ]


def default_promote_cedar_text(
    *,
    min_score: float = 0.7,
    min_agreement: float = 0.5,
    min_graders: int = 2,
) -> str:
    """Human-readable Cedar dump of the default promote policy set."""
    policies = default_promote_policies(
        min_score=min_score,
        min_agreement=min_agreement,
        min_graders=min_graders,
    )
    header = (
        f"// nexus.cedar_policy/v1 — consensus promote defaults\n"
        f"// arXiv 2606.26649 policy-as-code gate (offline subset)\n"
        f"// min_score={min_score} min_agreement={min_agreement} "
        f"min_graders={min_graders}\n\n"
    )
    return header + "\n\n".join(p.to_cedar() for p in policies) + "\n"


# ---------------------------------------------------------------------------
# Lightweight Cedar text parser (subset)
# ---------------------------------------------------------------------------

_STMT_RE = re.compile(
    r"(?P<effect>permit|forbid)\s*\(\s*"
    r"principal\s*,\s*"
    r'action\s*==\s*Action::"(?P<action>[^"]+)"\s*,\s*'
    r"resource\s*"
    r"\)\s*"
    r"(?:when\s*\{(?P<when>.*?)\}\s*)?;",
    re.IGNORECASE | re.DOTALL,
)

_ATOM_RE = re.compile(
    r"(?P<path>[A-Za-z_][A-Za-z0-9_.]*)\s*"
    r"(?P<op>==|!=|<=|>=|<|>)\s*"
    r"(?P<val>true|false|null|-?\d+(?:\.\d+)?|\"[^\"]*\"|'[^']*')",
    re.IGNORECASE,
)


def _parse_value(raw: str) -> Any:
    s = raw.strip()
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null":
        return None
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        return s[1:-1]
    if "." in s:
        return float(s)
    return int(s)


def _parse_when(body: str) -> list[Condition]:
    if not body or not body.strip() or body.strip() == "true":
        return []
    # Only AND of atoms in this subset (&&); ignore || for parser simplicity
    # by treating the whole as AND-group after splitting on &&.
    atoms: list[Condition] = []
    # strip comments
    cleaned = re.sub(r"//.*?$", "", body, flags=re.MULTILINE)
    for part in re.split(r"&&", cleaned):
        part = part.strip().rstrip(";").strip()
        if not part or part.lower() == "true":
            continue
        m = _ATOM_RE.search(part)
        if not m:
            raise CedarPolicyError(f"cannot parse when-atom: {part!r}")
        atoms.append((m.group("path"), m.group("op"), _parse_value(m.group("val"))))
    return atoms


def parse_cedar_text(text: str) -> list[PolicyStatement]:
    """Parse a subset of Cedar permit/forbid statements into PolicyStatement."""
    if not text or not str(text).strip():
        return []
    # Strip line comments for matching (keep raw per statement via slice)
    statements: list[PolicyStatement] = []
    for i, m in enumerate(_STMT_RE.finditer(text)):
        effect = m.group("effect").lower()
        action = m.group("action")
        when_body = m.group("when") or ""
        conds = _parse_when(when_body)
        statements.append(
            PolicyStatement(
                effect=effect,
                action=action,
                when=conds,
                policy_id=f"parsed-{i + 1}",
                raw=m.group(0).strip(),
            )
        )
    if not statements and (
        "permit" in text.lower() or "forbid" in text.lower()
    ):
        if not _STMT_RE.search(text):
            raise CedarPolicyError("no Cedar permit/forbid statements parsed")
    return statements


def make_request(
    *,
    principal: str,
    action: str = ACTION_PROMOTE,
    resource: Optional[dict[str, Any]] = None,
    context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "principal": {"id": str(principal or ""), "type": "Agent"},
        "action": str(action or ACTION_PROMOTE),
        "resource": dict(resource or {}),
        "context": dict(context or {}),
    }


def authorize(
    *,
    principal: str,
    action: str = ACTION_PROMOTE,
    resource: Optional[dict[str, Any]] = None,
    policies: Optional[list[PolicyStatement]] = None,
    min_score: float = 0.7,
    min_agreement: float = 0.5,
    min_graders: int = 2,
) -> CedarDecision:
    """Authorize *action* for *principal* on *resource* under policies."""
    pols = policies if policies is not None else default_promote_policies(
        min_score=min_score,
        min_agreement=min_agreement,
        min_graders=min_graders,
    )
    req = make_request(principal=principal, action=action, resource=resource)
    return evaluate_policies(pols, req)


def resource_from_consensus(
    verdict: Any,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Project a ConsensusVerdict / Verdict / dict into a Cedar resource entity."""
    if isinstance(verdict, dict):
        get = verdict.get
    else:

        def get(k: str, default: Any = None) -> Any:
            if hasattr(verdict, k):
                val = getattr(verdict, k)
                if val is not None:
                    return val
            to_dict = getattr(verdict, "to_dict", None)
            if callable(to_dict):
                try:
                    td = to_dict()
                    if isinstance(td, dict) and k in td:
                        return td.get(k, default)
                except Exception:
                    pass
            return default

    decision = str(get("decision") or "").strip().lower()
    try:
        score = float(get("score") if get("score") is not None else 0.0)
    except (TypeError, ValueError):
        score = 0.0
    try:
        agree = float(
            get("agreement_ratio") if get("agreement_ratio") is not None else 1.0
        )
    except (TypeError, ValueError):
        agree = 1.0
    try:
        n_graders = int(get("n_graders") if get("n_graders") is not None else 0)
    except (TypeError, ValueError):
        n_graders = 0
    degraded = bool(get("degraded") or False)
    # Single-judge Verdict: treat as non-degraded n=1 if no findings
    findings = get("findings")
    if findings is not None and n_graders == 0:
        try:
            n_graders = len(findings)
        except TypeError:
            pass
    if n_graders == 0 and decision:
        # single judge path: not multi-grader, mark n_graders=1, agreement=1
        n_graders = 1
        agree = 1.0

    resource: dict[str, Any] = {
        "type": "ConsensusDecision",
        "decision": decision,
        "score": score,
        "agreement_ratio": agree,
        "degraded": degraded,
        "n_graders": n_graders,
        "method": str(get("method") or ""),
        "implementer": str(get("implementer") or ""),
        "judge_agent": str(get("judge_agent") or ""),
    }
    if extra:
        resource.update(extra)
    return resource


def validate_promote(
    verdict: Any,
    *,
    principal: str = "consensus",
    policies: Optional[list[PolicyStatement]] = None,
    min_score: float = 0.7,
    min_agreement: float = 0.5,
    min_graders: int = 2,
    extra_resource: Optional[dict[str, Any]] = None,
) -> CedarDecision:
    """Cedar Policy Language validation step before promoting a decision.

    This is the arXiv 2606.26649 integration point: consensus (or any verdict)
    must pass policy-as-code before promotion is allowed.
    """
    resource = resource_from_consensus(verdict, extra=extra_resource)
    return authorize(
        principal=principal,
        action=ACTION_PROMOTE,
        resource=resource,
        policies=policies,
        min_score=min_score,
        min_agreement=min_agreement,
        min_graders=min_graders,
    )


__all__ = [
    "SCHEMA",
    "ACTION_PROMOTE",
    "PolicyStatement",
    "CedarDecision",
    "CedarPolicyError",
    "evaluate_policies",
    "statement_matches",
    "default_promote_policies",
    "default_promote_cedar_text",
    "parse_cedar_text",
    "make_request",
    "authorize",
    "resource_from_consensus",
    "validate_promote",
]
