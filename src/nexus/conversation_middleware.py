"""Config-driven multi-agent conversational middleware (labsai/EDDI shape).

Portable patterns only — **no Quarkus, no Java tree, no vendored EDDI**.

EDDI is production multi-agent orchestration middleware for conversational AI:
versioned JSON configs drive routing, persistent conversation memory, and API
orchestration (MCP / A2A / OpenAPI), with a strict lifecycle so non-deterministic
LLM steps stay governed.

This module keeps the *shape* offline and pure-Python:

  BotConfig (JSON) ──► ConversationEngine
        │                     │
        │              ConversationMemory
        │               (steps + scopes)
        │                     │
        ▼                     ▼
  Lifecycle: parse → rules → orchestrate → output
        │
        ├── BehaviorRule groups (first-match wins)
        ├── Actions: reply | route | handoff | memory_set | mcp | openapi | end
        └── Fail-closed when route / action / capability missing

Use for tests, dry-run enterprise chat routing, and CLI smoke
(``nexus conversation`` / ``python -m nexus.conversation_middleware``).
Live HTTP/MCP transports can map the same action kinds later.

AgentDef.privilege is reserved metadata (not enforced in v1). mcp/openapi
actions require the current agent to list that kind in ``capabilities``.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

SCHEMA = "nexus.conversation_middleware/v1"
SOURCE_PATTERN = "labsai/EDDI"
MODULE_VERSION = "0.1.1"

# Conversation lifecycle states (EDDI ConversationState shape)
STATE_READY = "READY"
STATE_IN_PROGRESS = "IN_PROGRESS"
STATE_ERROR = "ERROR"
STATE_ENDED = "ENDED"

STATES: frozenset[str] = frozenset(
    {STATE_READY, STATE_IN_PROGRESS, STATE_ERROR, STATE_ENDED}
)

# Property scopes (EDDI memory scopes)
SCOPE_STEP = "step"
SCOPE_CONVERSATION = "conversation"
SCOPE_LONG_TERM = "longTerm"

SCOPES: frozenset[str] = frozenset(
    {SCOPE_STEP, SCOPE_CONVERSATION, SCOPE_LONG_TERM}
)

# Lifecycle task types
TASK_PARSE = "parse"
TASK_RULES = "rules"
TASK_ORCHESTRATE = "orchestrate"
TASK_OUTPUT = "output"

DEFAULT_LIFECYCLE: tuple[str, ...] = (
    TASK_PARSE,
    TASK_RULES,
    TASK_ORCHESTRATE,
    TASK_OUTPUT,
)

# Action kinds (API / agent orchestration)
ACTION_REPLY = "reply"
ACTION_ROUTE = "route"
ACTION_HANDOFF = "handoff"
ACTION_MEMORY_SET = "memory_set"
ACTION_MCP = "mcp"
ACTION_OPENAPI = "openapi"
ACTION_END = "end"

ACTION_KINDS: frozenset[str] = frozenset(
    {
        ACTION_REPLY,
        ACTION_ROUTE,
        ACTION_HANDOFF,
        ACTION_MEMORY_SET,
        ACTION_MCP,
        ACTION_OPENAPI,
        ACTION_END,
    }
)

# Special action tokens (EDDI-compatible)
ACTION_CONVERSATION_END = "CONVERSATION_END"

Handler = Callable[["ConversationMemory", dict[str, Any]], dict[str, Any]]

__all__ = [
    "SCHEMA",
    "SOURCE_PATTERN",
    "MODULE_VERSION",
    "STATE_READY",
    "STATE_IN_PROGRESS",
    "STATE_ERROR",
    "STATE_ENDED",
    "STATES",
    "SCOPE_STEP",
    "SCOPE_CONVERSATION",
    "SCOPE_LONG_TERM",
    "SCOPES",
    "TASK_PARSE",
    "TASK_RULES",
    "TASK_ORCHESTRATE",
    "TASK_OUTPUT",
    "DEFAULT_LIFECYCLE",
    "ACTION_REPLY",
    "ACTION_ROUTE",
    "ACTION_HANDOFF",
    "ACTION_MEMORY_SET",
    "ACTION_MCP",
    "ACTION_OPENAPI",
    "ACTION_END",
    "ACTION_KINDS",
    "ACTION_CONVERSATION_END",
    "KNOWN_CONDITION_TYPES",
    "MiddlewareError",
    "ConversationStep",
    "ConversationMemory",
    "BehaviorRule",
    "BehaviorGroup",
    "ActionDef",
    "AgentDef",
    "BotConfig",
    "TurnResult",
    "ConversationEngine",
    "parse_expressions",
    "match_expression",
    "evaluate_condition",
    "default_bot_config",
    "load_bot_config",
    "demo_turns",
    "main",
]


class MiddlewareError(ValueError):
    """Invalid config, route, action, or lifecycle operation."""


# ── conversation memory ──────────────────────────────────────────────────────


@dataclass
class ConversationStep:
    """One user↔agent interaction cycle (EDDI conversation step)."""

    index: int
    input: str = ""
    expressions: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    routed_to: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "input": self.input,
            "expressions": list(self.expressions),
            "actions": list(self.actions),
            "outputs": list(self.outputs),
            "data": dict(self.data),
            "routed_to": self.routed_to,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ConversationStep":
        return cls(
            index=int(raw.get("index") or 0),
            input=str(raw.get("input") or ""),
            expressions=[str(x) for x in (raw.get("expressions") or [])],
            actions=[str(x) for x in (raw.get("actions") or [])],
            outputs=[str(x) for x in (raw.get("outputs") or [])],
            data=dict(raw.get("data") or {}),
            routed_to=str(raw.get("routed_to") or ""),
            ts=float(raw.get("ts") or time.time()),
        )


@dataclass
class ConversationMemory:
    """Stateful conversation object passed through the lifecycle pipeline.

    Scopes (EDDI):
      - step: cleared each turn (current step data)
      - conversation: persists for this conversation id
      - longTerm: persists across conversations for the same user
    """

    conversation_id: str
    agent_id: str = "default"
    user_id: str = "user"
    state: str = STATE_READY
    context: dict[str, Any] = field(default_factory=dict)
    conversation_props: dict[str, Any] = field(default_factory=dict)
    long_term_props: dict[str, Any] = field(default_factory=dict)
    steps: list[ConversationStep] = field(default_factory=list)
    current: Optional[ConversationStep] = None
    schema: str = SCHEMA

    def begin_step(self, user_input: str) -> ConversationStep:
        if self.state == STATE_ENDED:
            raise MiddlewareError("conversation has ended")
        step = ConversationStep(index=len(self.steps), input=str(user_input or ""))
        self.current = step
        self.state = STATE_IN_PROGRESS
        return step

    def commit_step(self) -> ConversationStep:
        if self.current is None:
            raise MiddlewareError("no current step to commit")
        done = self.current
        self.steps.append(done)
        self.current = None
        if self.state == STATE_IN_PROGRESS:
            self.state = STATE_READY
        return done

    def set_prop(self, key: str, value: Any, *, scope: str = SCOPE_CONVERSATION) -> None:
        k = str(key or "").strip()
        if not k:
            raise MiddlewareError("property key required")
        sc = str(scope or SCOPE_CONVERSATION).strip()
        if sc not in SCOPES:
            raise MiddlewareError(f"unknown property scope: {scope!r}")
        if sc == SCOPE_STEP:
            if self.current is None:
                raise MiddlewareError("no current step for step-scoped property")
            self.current.data[k] = value
        elif sc == SCOPE_CONVERSATION:
            self.conversation_props[k] = value
        else:
            self.long_term_props[k] = value

    def get_prop(
        self, key: str, *, scope: Optional[str] = None, default: Any = None
    ) -> Any:
        k = str(key or "").strip()
        if not k:
            return default
        if scope == SCOPE_STEP:
            if self.current is None:
                return default
            return self.current.data.get(k, default)
        if scope == SCOPE_CONVERSATION:
            return self.conversation_props.get(k, default)
        if scope == SCOPE_LONG_TERM:
            return self.long_term_props.get(k, default)
        # Search current step → conversation → longTerm
        if self.current is not None and k in self.current.data:
            return self.current.data[k]
        if k in self.conversation_props:
            return self.conversation_props[k]
        if k in self.long_term_props:
            return self.long_term_props[k]
        return default

    def previous_expressions(self) -> list[str]:
        out: list[str] = []
        for s in self.steps:
            out.extend(s.expressions)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "conversation_id": self.conversation_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "state": self.state,
            "context": dict(self.context),
            "conversation_props": dict(self.conversation_props),
            "long_term_props": dict(self.long_term_props),
            "steps": [s.to_dict() for s in self.steps],
            "current": self.current.to_dict() if self.current else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ConversationMemory":
        if not isinstance(raw, dict):
            raise MiddlewareError("memory must be a dict")
        cur = raw.get("current")
        state = str(raw.get("state") or STATE_READY)
        if state not in STATES:
            state = STATE_READY
        return cls(
            conversation_id=str(raw.get("conversation_id") or _new_id("c")),
            agent_id=str(raw.get("agent_id") or "default"),
            user_id=str(raw.get("user_id") or "user"),
            state=state,
            context=dict(raw.get("context") or {}),
            conversation_props=dict(raw.get("conversation_props") or {}),
            long_term_props=dict(raw.get("long_term_props") or {}),
            steps=[ConversationStep.from_dict(s) for s in (raw.get("steps") or [])],
            current=ConversationStep.from_dict(cur) if isinstance(cur, dict) else None,
            schema=str(raw.get("schema") or SCHEMA),
        )


# ── expression parse / match ─────────────────────────────────────────────────


def _normalize_token(s: str) -> str:
    return re.sub(r"[^a-z0-9_*]+", "", str(s or "").strip().lower())


def parse_expressions(
    text: str,
    *,
    dictionary: Optional[dict[str, Sequence[str]]] = None,
) -> list[str]:
    """Map free text to EDDI-style expressions via a keyword dictionary.

    Dictionary maps expression type → list of trigger words/phrases.
    Example: ``{"greeting": ["hello", "hi"], "goodbye": ["bye"]}``
    yields ``greeting(hello)`` when input contains "hello".
    """
    raw = str(text or "").strip()
    if not raw:
        return []
    lower = raw.lower()
    tokens = {_normalize_token(t) for t in re.split(r"\s+", lower) if t}
    exprs: list[str] = []
    seen: set[str] = set()
    d = dictionary or {}
    for etype, triggers in d.items():
        et = _normalize_token(str(etype))
        if not et:
            continue
        for trig in triggers or []:
            t = str(trig or "").strip().lower()
            if not t:
                continue
            hit = False
            if " " in t:
                hit = t in lower
            else:
                hit = _normalize_token(t) in tokens
            if hit:
                value = _normalize_token(t) or t
                expr = f"{et}({value})"
                if expr not in seen:
                    seen.add(expr)
                    exprs.append(expr)
                break
    # Always attach a bag-of-words fallback for open routing
    if not exprs:
        for tok in sorted(tokens):
            if len(tok) >= 2:
                exprs.append(f"word({tok})")
                break
    return exprs


def _split_or_patterns(pat: str) -> list[str]:
    """Split comma-OR patterns only at commas outside parentheses."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in pat:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            piece = "".join(buf).strip()
            if piece:
                parts.append(piece)
            buf = []
        else:
            buf.append(ch)
    piece = "".join(buf).strip()
    if piece:
        parts.append(piece)
    return parts


def match_expression(pattern: str, expressions: Sequence[str]) -> bool:
    """Match EDDI-style expression patterns (supports ``type(*)`` wildcards)."""
    pat = str(pattern or "").strip()
    if not pat:
        return False
    # multi-pattern: comma-separated OR (commas inside parens are literal)
    if "," in pat:
        alts = _split_or_patterns(pat)
        if len(alts) > 1:
            return any(match_expression(p, expressions) for p in alts)
    m = re.fullmatch(r"([a-zA-Z0-9_]+)\((.*)\)", pat)
    if not m:
        # bare type matches any type(...)
        bare = _normalize_token(pat)
        return any(
            re.fullmatch(rf"{re.escape(bare)}\(.*\)", e) is not None
            for e in expressions
        )
    etype = _normalize_token(m.group(1))
    val = m.group(2)
    if val == "*":
        rx = re.compile(rf"^{re.escape(etype)}\(.*\)$")
        return any(rx.match(e) for e in expressions)
    exact = f"{etype}({val})"
    # expressions from parse_expressions are already lowercased types
    return exact in expressions or any(
        e.lower() == exact.lower() for e in expressions
    )


# ── conditions / rules ──────────────────────────────────────────────────────


def evaluate_condition(
    condition: dict[str, Any],
    memory: ConversationMemory,
    *,
    expressions: Optional[Sequence[str]] = None,
) -> bool:
    """Evaluate one EDDI-shaped condition against conversation memory."""
    if not isinstance(condition, dict):
        return False
    ctype = str(condition.get("type") or "").strip().lower()
    configs = condition.get("configs") or {}
    if not isinstance(configs, dict):
        configs = {}
    exprs = list(expressions if expressions is not None else ())
    if not exprs and memory.current is not None:
        exprs = list(memory.current.expressions)

    if ctype in ("", "true", "always"):
        return True

    if ctype == "negation":
        subs = condition.get("conditions") or []
        if not isinstance(subs, list) or not subs:
            return True
        return not all(
            evaluate_condition(s, memory, expressions=exprs)
            for s in subs
            if isinstance(s, dict)
        )

    if ctype == "connector":
        # AND of sub-conditions (EDDI connector shape, simplified)
        op = str(configs.get("operator") or configs.get("type") or "and").lower()
        subs = [
            s
            for s in (condition.get("conditions") or [])
            if isinstance(s, dict)
        ]
        if not subs:
            return True
        results = [evaluate_condition(s, memory, expressions=exprs) for s in subs]
        if op in ("or", "||"):
            return any(results)
        return all(results)

    if ctype == "inputmatcher":
        pattern = str(configs.get("expressions") or configs.get("expression") or "")
        occurrence = str(configs.get("occurrence") or "currentStep").strip()
        if occurrence == "currentStep":
            pool = exprs
        elif occurrence == "lastStep":
            pool = list(memory.steps[-1].expressions) if memory.steps else []
        elif occurrence == "anyStep":
            pool = memory.previous_expressions() + exprs
        elif occurrence == "never":
            pool = memory.previous_expressions() + exprs
            return not match_expression(pattern, pool)
        else:
            pool = exprs
        return match_expression(pattern, pool)

    if ctype == "contextmatcher":
        key = str(configs.get("contextKey") or configs.get("key") or "").strip()
        if not key:
            return False
        # Support dotted path under context
        cur: Any = memory.context
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                # also check conversation props
                val = memory.get_prop(key)
                return val is not None and val != "" and val is not False
            cur = cur[part]
        object_path = str(configs.get("objectKeyPath") or "").strip()
        if object_path and isinstance(cur, dict):
            for part in object_path.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    return False
                cur = cur[part]
        expected = configs.get("value")
        if expected is not None:
            return cur == expected
        return cur is not None and cur != "" and cur is not False

    if ctype == "actionmatcher":
        wanted = str(configs.get("actions") or configs.get("action") or "").strip()
        if not wanted:
            return False
        want_set = {a.strip() for a in wanted.split(",") if a.strip()}
        seen: set[str] = set()
        for s in memory.steps:
            seen.update(s.actions)
        if memory.current is not None:
            seen.update(memory.current.actions)
        return bool(want_set & seen)

    if ctype == "occurrence":
        rule_name = str(
            configs.get("behaviorRuleName") or configs.get("rule") or ""
        ).strip()
        try:
            max_times = int(configs.get("maxTimesOccurred", 0))
        except (TypeError, ValueError):
            max_times = 0
        count = 0
        for s in memory.steps:
            if rule_name and rule_name in (s.data.get("matched_rules") or []):
                count += 1
            elif not rule_name and s.actions:
                count += 1
        return count <= max_times

    if ctype == "dynamicvaluematcher":
        key = str(configs.get("key") or "").strip()
        expected = configs.get("value")
        got = memory.get_prop(key)
        if expected is None:
            return got is not None
        return got == expected

    raise MiddlewareError(f"unknown condition type: {ctype!r}")


@dataclass
class BehaviorRule:
    """IF-THEN rule: all conditions true → fire actions (first match in group)."""

    name: str
    actions: list[str] = field(default_factory=list)
    conditions: list[dict[str, Any]] = field(default_factory=list)

    def matches(self, memory: ConversationMemory) -> bool:
        if not self.conditions:
            return True
        return all(
            evaluate_condition(c, memory) for c in self.conditions if isinstance(c, dict)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "actions": list(self.actions),
            "conditions": list(self.conditions),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BehaviorRule":
        if not isinstance(raw, dict):
            raise MiddlewareError("behavior rule must be a dict")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise MiddlewareError("behavior rule name required")
        acts = raw.get("actions") or []
        if not isinstance(acts, list):
            acts = [acts]
        conds = raw.get("conditions") or []
        if not isinstance(conds, list):
            conds = []
        return cls(
            name=name,
            actions=[str(a) for a in acts],
            conditions=[c for c in conds if isinstance(c, dict)],
        )


@dataclass
class BehaviorGroup:
    """Ordered rules; first successful rule wins (EDDI group semantics)."""

    name: str
    rules: list[BehaviorRule] = field(default_factory=list)

    def evaluate(self, memory: ConversationMemory) -> Optional[BehaviorRule]:
        for rule in self.rules:
            if rule.matches(memory):
                return rule
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "behaviorRules": [r.to_dict() for r in self.rules],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BehaviorGroup":
        if not isinstance(raw, dict):
            raise MiddlewareError("behavior group must be a dict")
        name = str(raw.get("name") or "").strip() or "default"
        rules_raw = raw.get("behaviorRules") or raw.get("rules") or []
        if not isinstance(rules_raw, list):
            rules_raw = []
        return cls(
            name=name,
            rules=[BehaviorRule.from_dict(r) for r in rules_raw if isinstance(r, dict)],
        )


# ── config model ─────────────────────────────────────────────────────────────


@dataclass
class ActionDef:
    """Declarative action: reply text, route target, MCP tool, OpenAPI op, …"""

    name: str
    kind: str = ACTION_REPLY
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "config": dict(self.config),
        }

    @classmethod
    def from_dict(cls, name: str, raw: Any) -> "ActionDef":
        if isinstance(raw, str):
            return cls(name=name, kind=ACTION_REPLY, config={"text": raw})
        if not isinstance(raw, dict):
            raise MiddlewareError(f"action {name!r} must be str or dict")
        kind = str(raw.get("kind") or raw.get("type") or ACTION_REPLY).strip().lower()
        if kind not in ACTION_KINDS:
            raise MiddlewareError(f"unknown action kind: {kind!r}")
        cfg = dict(raw.get("config") or {})
        # Allow flat fields alongside config
        for k, v in raw.items():
            if k not in {"kind", "type", "config", "name"} and k not in cfg:
                cfg[k] = v
        return cls(name=str(name), kind=kind, config=cfg)


# Condition types accepted by evaluate_condition / BotConfig.validate
KNOWN_CONDITION_TYPES: frozenset[str] = frozenset(
    {
        "",
        "true",
        "always",
        "negation",
        "connector",
        "inputmatcher",
        "contextmatcher",
        "actionmatcher",
        "occurrence",
        "dynamicvaluematcher",
    }
)


@dataclass
class AgentDef:
    """One routable agent (specialist) in the multi-agent graph.

    ``capabilities`` is enforced for mcp/openapi actions (kind must be listed).
    ``privilege`` is reserved metadata — not enforced in v1.
    """

    id: str
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    privilege: str = "ops"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "privilege": self.privilege,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AgentDef":
        if not isinstance(raw, dict):
            raise MiddlewareError("agent must be a dict")
        aid = str(raw.get("id") or raw.get("name") or "").strip()
        if not aid:
            raise MiddlewareError("agent id required")
        caps = raw.get("capabilities") or raw.get("skills") or []
        if not isinstance(caps, list):
            caps = [caps]
        return cls(
            id=aid,
            description=str(raw.get("description") or ""),
            capabilities=[str(c).strip().lower() for c in caps if str(c).strip()],
            privilege=str(raw.get("privilege") or "ops").strip() or "ops",
        )


@dataclass
class BotConfig:
    """Versioned bot/agent configuration (EDDI .agent / behavior / httpcalls shape)."""

    id: str = "default"
    version: int = 1
    name: str = "NEXUS Conversation Bot"
    dictionary: dict[str, list[str]] = field(default_factory=dict)
    groups: list[BehaviorGroup] = field(default_factory=list)
    actions: dict[str, ActionDef] = field(default_factory=dict)
    agents: dict[str, AgentDef] = field(default_factory=dict)
    lifecycle: list[str] = field(default_factory=lambda: list(DEFAULT_LIFECYCLE))
    default_agent: str = "default"
    fallback_action: str = "fallback"
    schema: str = SCHEMA

    def validate(self) -> list[str]:
        """Return list of config problems (empty = ok). Fail-closed callers raise."""
        problems: list[str] = []
        if not self.id:
            problems.append("bot id required")

        if self.fallback_action and self.fallback_action not in self.actions:
            problems.append(
                f"fallback_action {self.fallback_action!r} is not a defined action"
            )
        if self.agents and self.default_agent and self.default_agent not in self.agents:
            problems.append(
                f"default_agent {self.default_agent!r} is not a defined agent"
            )

        def _walk_condition(cond: Any, path: str) -> None:
            if not isinstance(cond, dict):
                problems.append(f"{path}: condition must be a dict")
                return
            ctype = str(cond.get("type") or "").strip().lower()
            if ctype not in KNOWN_CONDITION_TYPES:
                problems.append(f"{path}: unknown condition type: {ctype!r}")
            for i, sub in enumerate(cond.get("conditions") or []):
                if isinstance(sub, dict):
                    _walk_condition(sub, f"{path}.conditions[{i}]")
                elif sub is not None:
                    problems.append(f"{path}.conditions[{i}]: condition must be a dict")

        for g in self.groups:
            for rule in g.rules:
                for act in rule.actions:
                    if act == ACTION_CONVERSATION_END:
                        continue
                    if act not in self.actions:
                        problems.append(
                            f"rule {rule.name!r} references unknown action {act!r}"
                        )
                for i, cond in enumerate(rule.conditions):
                    _walk_condition(cond, f"rule {rule.name!r} condition[{i}]")

        for name, adef in self.actions.items():
            if adef.kind == ACTION_ROUTE:
                target = str(adef.config.get("agent") or adef.config.get("target") or "")
                if target and target not in self.agents and target != self.default_agent:
                    problems.append(
                        f"action {name!r} routes to unknown agent {target!r}"
                    )
                if (
                    target
                    and target == self.default_agent
                    and self.agents
                    and target not in self.agents
                ):
                    problems.append(
                        f"action {name!r} routes to default_agent {target!r} "
                        "which is not a defined agent"
                    )
            if adef.kind == ACTION_HANDOFF:
                target = str(adef.config.get("agent") or adef.config.get("target") or "")
                if target and target not in self.agents:
                    problems.append(
                        f"action {name!r} handoff to unknown agent {target!r}"
                    )
            if adef.kind == ACTION_MCP:
                tool = str(adef.config.get("tool") or adef.config.get("name") or "").strip()
                if not tool:
                    problems.append(f"mcp action {name!r} missing tool")
            if adef.kind == ACTION_OPENAPI:
                op = str(
                    adef.config.get("operation")
                    or adef.config.get("path")
                    or adef.config.get("op")
                    or ""
                ).strip()
                if not op:
                    problems.append(f"openapi action {name!r} missing operation")
            if adef.kind == ACTION_MEMORY_SET:
                key = str(adef.config.get("key") or "").strip()
                if not key:
                    problems.append(f"memory_set action {name!r} missing key")
        for task in self.lifecycle:
            if task not in {
                TASK_PARSE,
                TASK_RULES,
                TASK_ORCHESTRATE,
                TASK_OUTPUT,
            }:
                problems.append(f"unknown lifecycle task: {task!r}")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "dictionary": {k: list(v) for k, v in self.dictionary.items()},
            "behaviorGroups": [g.to_dict() for g in self.groups],
            "actions": {k: v.to_dict() for k, v in self.actions.items()},
            "agents": {k: v.to_dict() for k, v in self.agents.items()},
            "lifecycle": list(self.lifecycle),
            "default_agent": self.default_agent,
            "fallback_action": self.fallback_action,
            "source_pattern": SOURCE_PATTERN,
            "module_version": MODULE_VERSION,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BotConfig":
        if not isinstance(raw, dict):
            raise MiddlewareError("bot config must be a dict")
        groups_raw = raw.get("behaviorGroups") or raw.get("groups") or []
        if not isinstance(groups_raw, list):
            groups_raw = []
        actions_raw = raw.get("actions") or {}
        if not isinstance(actions_raw, dict):
            raise MiddlewareError("actions must be a mapping")
        agents_raw = raw.get("agents") or {}
        if not isinstance(agents_raw, dict):
            # allow list form
            if isinstance(agents_raw, list):
                agents_raw = {
                    str(a.get("id") or a.get("name")): a
                    for a in agents_raw
                    if isinstance(a, dict)
                }
            else:
                agents_raw = {}
        dict_raw = raw.get("dictionary") or {}
        if not isinstance(dict_raw, dict):
            dict_raw = {}
        dictionary: dict[str, list[str]] = {}
        for k, v in dict_raw.items():
            if isinstance(v, (list, tuple)):
                dictionary[str(k)] = [str(x) for x in v]
            elif v:
                dictionary[str(k)] = [str(v)]
        agents: dict[str, AgentDef] = {}
        for k, v in agents_raw.items():
            if isinstance(v, dict):
                body = dict(v)
                body.setdefault("id", k)
                ad = AgentDef.from_dict(body)
            else:
                ad = AgentDef(id=str(k), description=str(v))
            agents[ad.id] = ad
        actions: dict[str, ActionDef] = {}
        for k, v in actions_raw.items():
            actions[str(k)] = ActionDef.from_dict(str(k), v)
        life = raw.get("lifecycle") or list(DEFAULT_LIFECYCLE)
        if not isinstance(life, list):
            life = list(DEFAULT_LIFECYCLE)
        return cls(
            id=str(raw.get("id") or "default"),
            version=int(raw.get("version") or 1),
            name=str(raw.get("name") or "NEXUS Conversation Bot"),
            dictionary=dictionary,
            groups=[
                BehaviorGroup.from_dict(g) for g in groups_raw if isinstance(g, dict)
            ],
            actions=actions,
            agents=agents,
            lifecycle=[str(t) for t in life],
            default_agent=str(raw.get("default_agent") or "default"),
            fallback_action=str(raw.get("fallback_action") or "fallback"),
            schema=str(raw.get("schema") or SCHEMA),
        )


def load_bot_config(path: Path | str) -> BotConfig:
    """Load bot config from a JSON file."""
    p = Path(path)
    if not p.is_file():
        raise MiddlewareError(f"bot config not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise MiddlewareError(f"invalid bot config JSON: {e}") from e
    return BotConfig.from_dict(data)


def default_bot_config() -> BotConfig:
    """Small enterprise-chat demo config (greeting / support / end)."""
    return BotConfig.from_dict(
        {
            "id": "demo-support",
            "version": 1,
            "name": "Demo Support Bot",
            "default_agent": "triage",
            "dictionary": {
                "greeting": ["hello", "hi", "hey", "good morning"],
                "goodbye": ["bye", "goodbye", "see you", "quit", "exit"],
                "support": ["help", "issue", "problem", "broken", "error", "bug"],
                "billing": ["invoice", "bill", "payment", "charge", "refund"],
            },
            "agents": {
                "triage": {
                    "id": "triage",
                    "description": "Front-door router",
                    "capabilities": ["route", "greet"],
                },
                "support": {
                    "id": "support",
                    "description": "Technical support specialist",
                    "capabilities": ["support", "mcp"],
                },
                "billing": {
                    "id": "billing",
                    "description": "Billing / OpenAPI specialist",
                    "capabilities": ["billing", "openapi"],
                },
            },
            "actions": {
                "welcome": {
                    "kind": "reply",
                    "text": "Welcome! I can help with support or billing.",
                },
                "greet": {
                    "kind": "reply",
                    "text": "Hello! How can I help you today?",
                },
                "route_support": {
                    "kind": "route",
                    "agent": "support",
                    "text": "Routing you to support.",
                },
                "route_billing": {
                    "kind": "route",
                    "agent": "billing",
                    "text": "Routing you to billing.",
                },
                "mcp_ticket": {
                    "kind": "mcp",
                    "tool": "create_ticket",
                    "args": {"priority": "normal"},
                    "text": "Created a support ticket via MCP (dry-run).",
                },
                "openapi_invoice": {
                    "kind": "openapi",
                    "operation": "GET /invoices/latest",
                    "text": "Fetched latest invoice via OpenAPI (dry-run).",
                },
                "remember_topic": {
                    "kind": "memory_set",
                    "key": "last_topic",
                    "value": "support",
                    "scope": "conversation",
                },
                "say_goodbye": {
                    "kind": "reply",
                    "text": "Goodbye! Conversation ended.",
                },
                "fallback": {
                    "kind": "reply",
                    "text": "I did not understand. Try hello, help, invoice, or bye.",
                },
            },
            "behaviorGroups": [
                {
                    "name": "Session",
                    "behaviorRules": [
                        # Goodbye before Welcome so first-turn "bye" ends cleanly
                        {
                            "name": "Goodbye",
                            "actions": ["say_goodbye", "CONVERSATION_END"],
                            "conditions": [
                                {
                                    "type": "inputmatcher",
                                    "configs": {
                                        "expressions": "goodbye(*)",
                                        "occurrence": "currentStep",
                                    },
                                }
                            ],
                        },
                        {
                            "name": "Welcome",
                            "actions": ["welcome"],
                            "conditions": [
                                {
                                    "type": "occurrence",
                                    "configs": {
                                        "maxTimesOccurred": "0",
                                        "behaviorRuleName": "Welcome",
                                    },
                                }
                            ],
                        },
                    ],
                },
                {
                    "name": "Intent",
                    "behaviorRules": [
                        {
                            "name": "Greeting",
                            "actions": ["greet"],
                            "conditions": [
                                {
                                    "type": "inputmatcher",
                                    "configs": {
                                        "expressions": "greeting(*)",
                                        "occurrence": "currentStep",
                                    },
                                }
                            ],
                        },
                        {
                            "name": "Support",
                            "actions": [
                                "route_support",
                                "remember_topic",
                                "mcp_ticket",
                            ],
                            "conditions": [
                                {
                                    "type": "inputmatcher",
                                    "configs": {
                                        "expressions": "support(*)",
                                        "occurrence": "currentStep",
                                    },
                                }
                            ],
                        },
                        {
                            "name": "Billing",
                            "actions": ["route_billing", "openapi_invoice"],
                            "conditions": [
                                {
                                    "type": "inputmatcher",
                                    "configs": {
                                        "expressions": "billing(*)",
                                        "occurrence": "currentStep",
                                    },
                                }
                            ],
                        },
                    ],
                },
            ],
        }
    )


# ── engine ───────────────────────────────────────────────────────────────────


@dataclass
class TurnResult:
    """Result of one user turn through the lifecycle."""

    conversation_id: str
    state: str
    outputs: list[str]
    actions: list[str]
    expressions: list[str]
    matched_rules: list[str]
    routed_to: str
    orchestrations: list[dict[str, Any]]
    step_index: int
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "conversation_id": self.conversation_id,
            "state": self.state,
            "outputs": list(self.outputs),
            "actions": list(self.actions),
            "expressions": list(self.expressions),
            "matched_rules": list(self.matched_rules),
            "routed_to": self.routed_to,
            "orchestrations": list(self.orchestrations),
            "step_index": self.step_index,
        }


@dataclass
class ConversationEngine:
    """Config-driven conversation middleware engine (EDDI lifecycle shape)."""

    config: BotConfig
    memories: dict[str, ConversationMemory] = field(default_factory=dict)
    long_term_store: dict[str, dict[str, Any]] = field(default_factory=dict)
    action_handlers: dict[str, Handler] = field(default_factory=dict)
    strict: bool = True  # fail-closed on bad config / missing routes

    def __post_init__(self) -> None:
        problems = self.config.validate()
        if problems and self.strict:
            raise MiddlewareError(
                "invalid bot config: " + "; ".join(problems[:5])
            )

    def get_or_create(
        self,
        conversation_id: Optional[str] = None,
        *,
        user_id: str = "user",
        context: Optional[dict[str, Any]] = None,
    ) -> ConversationMemory:
        cid = str(conversation_id or _new_id("c"))
        uid = str(user_id or "user")
        if cid in self.memories:
            mem = self.memories[cid]
            if mem.user_id != uid:
                raise MiddlewareError(
                    f"conversation {cid!r} belongs to user {mem.user_id!r}, "
                    f"not {uid!r}"
                )
            if context:
                mem.context.update(context)
            return mem
        # Share the store dict (write-through) — no copy/clobber across convs
        lt = self.long_term_store.setdefault(uid, {})
        mem = ConversationMemory(
            conversation_id=cid,
            agent_id=self.config.default_agent,
            user_id=uid,
            context=dict(context or {}),
            long_term_props=lt,
        )
        self.memories[cid] = mem
        return mem

    def process(
        self,
        user_input: str,
        *,
        conversation_id: Optional[str] = None,
        user_id: str = "user",
        context: Optional[dict[str, Any]] = None,
    ) -> TurnResult:
        """Run one user message through the configured lifecycle pipeline."""
        mem = self.get_or_create(
            conversation_id, user_id=user_id, context=context
        )
        if mem.state == STATE_ENDED:
            raise MiddlewareError("conversation has ended")

        step = mem.begin_step(user_input)
        matched: list[str] = []
        fired_actions: list[str] = []
        orchestrations: list[dict[str, Any]] = []
        outputs: list[str] = []
        routed_to = mem.agent_id

        try:
            for task in self.config.lifecycle:
                if task == TASK_PARSE:
                    step.expressions = parse_expressions(
                        step.input, dictionary=self.config.dictionary
                    )
                elif task == TASK_RULES:
                    matched, fired_actions = self._run_rules(mem)
                    step.actions = list(fired_actions)
                    step.data["matched_rules"] = list(matched)
                elif task == TASK_ORCHESTRATE:
                    outs, route, orchs = self._run_actions(mem, fired_actions)
                    outputs.extend(outs)
                    orchestrations.extend(orchs)
                    if route:
                        routed_to = route
                        step.routed_to = route
                        mem.agent_id = route
                elif task == TASK_OUTPUT:
                    step.outputs = list(outputs)
                    if not step.outputs and fired_actions:
                        # actions without reply still surface action names
                        step.outputs = [
                            f"[actions: {', '.join(fired_actions)}]"
                        ]
                        outputs = list(step.outputs)
                else:
                    raise MiddlewareError(f"unknown lifecycle task: {task!r}")
                if mem.state == STATE_ENDED:
                    break
            # Ending mid-lifecycle must still surface reply text (before commit)
            if not step.outputs:
                step.outputs = list(outputs) or (
                    [f"[actions: {', '.join(fired_actions)}]"]
                    if fired_actions
                    else []
                )
        except MiddlewareError as e:
            mem.state = STATE_ERROR
            if mem.current is not None:
                mem.current.data["error"] = str(e)
                if fired_actions and not mem.current.actions:
                    mem.current.actions = list(fired_actions)
                mem.steps.append(mem.current)
                mem.current = None
            raise
        except Exception as e:
            mem.state = STATE_ERROR
            if mem.current is not None:
                mem.current.data["error"] = str(e)
                mem.steps.append(mem.current)
                mem.current = None
            raise MiddlewareError(f"lifecycle failed: {e}") from e

        committed = mem.commit_step()
        # long_term_props is already the shared store dict (write-through)

        return TurnResult(
            conversation_id=mem.conversation_id,
            state=mem.state,
            outputs=list(committed.outputs),
            actions=list(committed.actions),
            expressions=list(committed.expressions),
            matched_rules=list(committed.data.get("matched_rules") or matched),
            routed_to=committed.routed_to or routed_to,
            orchestrations=orchestrations,
            step_index=committed.index,
        )

    def _run_rules(
        self, memory: ConversationMemory
    ) -> tuple[list[str], list[str]]:
        matched: list[str] = []
        actions: list[str] = []
        for group in self.config.groups:
            rule = group.evaluate(memory)
            if rule is None:
                continue
            matched.append(rule.name)
            for a in rule.actions:
                if a not in actions:
                    actions.append(a)
        if not actions and self.config.fallback_action:
            actions.append(self.config.fallback_action)
            matched.append("__fallback__")
        return matched, actions

    def _run_actions(
        self,
        memory: ConversationMemory,
        action_names: Sequence[str],
    ) -> tuple[list[str], str, list[dict[str, Any]]]:
        outputs: list[str] = []
        orchestrations: list[dict[str, Any]] = []
        routed_to = ""

        for name in action_names:
            if name == ACTION_CONVERSATION_END:
                memory.state = STATE_ENDED
                orchestrations.append(
                    {
                        "action": name,
                        "kind": ACTION_END,
                        "ok": True,
                        "result": {"ended": True},
                    }
                )
                continue

            adef = self.config.actions.get(name)
            if adef is None:
                if self.strict:
                    raise MiddlewareError(f"unknown action: {name!r}")
                orchestrations.append(
                    {
                        "action": name,
                        "kind": "unknown",
                        "ok": False,
                        "error": "unknown_action",
                    }
                )
                continue

            # Custom handler override
            if name in self.action_handlers:
                result = self.action_handlers[name](memory, adef.config)
                orchestrations.append(
                    {
                        "action": name,
                        "kind": adef.kind,
                        "ok": True,
                        "result": result,
                    }
                )
                text = result.get("text") if isinstance(result, dict) else None
                if text:
                    outputs.append(str(text))
                continue

            orch = self._dispatch_action(memory, name, adef)
            orchestrations.append(orch)
            if orch.get("output"):
                outputs.append(str(orch["output"]))
            if orch.get("routed_to"):
                routed_to = str(orch["routed_to"])
            if adef.kind == ACTION_END:
                memory.state = STATE_ENDED

        return outputs, routed_to, orchestrations

    def _require_capability(
        self, memory: ConversationMemory, kind: str, action_name: str
    ) -> None:
        """Fail closed when agent lacks capability for mcp/openapi kinds."""
        agent = self.config.agents.get(memory.agent_id)
        if agent is None:
            raise MiddlewareError(
                f"action {action_name!r} requires agent {memory.agent_id!r} "
                f"with capability {kind!r}"
            )
        if kind not in agent.capabilities:
            raise MiddlewareError(
                f"agent {memory.agent_id!r} lacks capability {kind!r} "
                f"for action {action_name!r}"
            )

    def _dispatch_action(
        self,
        memory: ConversationMemory,
        name: str,
        adef: ActionDef,
    ) -> dict[str, Any]:
        cfg = adef.config
        kind = adef.kind

        if kind in (ACTION_MCP, ACTION_OPENAPI):
            self._require_capability(memory, kind, name)

        if kind == ACTION_REPLY:
            text = str(cfg.get("text") or cfg.get("output") or "")
            return {
                "action": name,
                "kind": kind,
                "ok": True,
                "output": text,
                "result": {"text": text},
            }

        if kind == ACTION_ROUTE:
            target = str(cfg.get("agent") or cfg.get("target") or "").strip()
            if not target:
                raise MiddlewareError(f"route action {name!r} missing agent")
            if (
                target not in self.config.agents
                and target != self.config.default_agent
            ):
                raise MiddlewareError(
                    f"route action {name!r} target agent {target!r} not in config"
                )
            text = str(cfg.get("text") or f"Routed to {target}.")
            memory.agent_id = target
            return {
                "action": name,
                "kind": kind,
                "ok": True,
                "output": text,
                "routed_to": target,
                "result": {"agent": target},
            }

        if kind == ACTION_HANDOFF:
            target = str(cfg.get("agent") or cfg.get("target") or "").strip()
            if not target:
                raise MiddlewareError(f"handoff action {name!r} missing agent")
            if target not in self.config.agents:
                raise MiddlewareError(
                    f"handoff action {name!r} unknown agent {target!r}"
                )
            # Memory handoff keys must be explicit (EDDI-style durable keys)
            keys = cfg.get("memory_keys") or cfg.get("handoff_keys") or []
            if isinstance(keys, str):
                keys = [keys]
            payload = {
                k: memory.get_prop(str(k)) for k in keys if str(k).strip()
            }
            memory.agent_id = target
            text = str(cfg.get("text") or f"Handed off to {target}.")
            return {
                "action": name,
                "kind": kind,
                "ok": True,
                "output": text,
                "routed_to": target,
                "result": {"agent": target, "memory_keys": payload},
            }

        if kind == ACTION_MEMORY_SET:
            key = str(cfg.get("key") or "").strip()
            if not key:
                raise MiddlewareError(f"memory_set action {name!r} missing key")
            scope = str(cfg.get("scope") or SCOPE_CONVERSATION)
            value = cfg.get("value")
            memory.set_prop(key, value, scope=scope)
            return {
                "action": name,
                "kind": kind,
                "ok": True,
                "result": {"key": key, "scope": scope, "value": value},
            }

        if kind == ACTION_MCP:
            tool = str(cfg.get("tool") or cfg.get("name") or "").strip()
            if not tool:
                raise MiddlewareError(f"mcp action {name!r} missing tool")
            args = dict(cfg.get("args") or cfg.get("arguments") or {})
            # Dry-run: no live MCP. Record orchestration intent only.
            text = str(
                cfg.get("text")
                or f"MCP tool {tool} invoked (dry-run) with {args}."
            )
            return {
                "action": name,
                "kind": kind,
                "ok": True,
                "output": text,
                "result": {
                    "tool": tool,
                    "args": args,
                    "dry_run": True,
                    "protocol": "mcp",
                },
            }

        if kind == ACTION_OPENAPI:
            op = str(
                cfg.get("operation") or cfg.get("path") or cfg.get("op") or ""
            ).strip()
            if not op:
                raise MiddlewareError(f"openapi action {name!r} missing operation")
            method = str(cfg.get("method") or "GET").upper()
            text = str(
                cfg.get("text")
                or f"OpenAPI {method} {op} (dry-run)."
            )
            return {
                "action": name,
                "kind": kind,
                "ok": True,
                "output": text,
                "result": {
                    "operation": op,
                    "method": method,
                    "dry_run": True,
                    "protocol": "openapi",
                },
            }

        if kind == ACTION_END:
            memory.state = STATE_ENDED
            text = str(cfg.get("text") or "Conversation ended.")
            return {
                "action": name,
                "kind": kind,
                "ok": True,
                "output": text,
                "result": {"ended": True},
            }

        raise MiddlewareError(f"unhandled action kind: {kind!r}")

    def snapshot(self, conversation_id: str) -> dict[str, Any]:
        mem = self.memories.get(conversation_id)
        if mem is None:
            raise MiddlewareError(f"unknown conversation: {conversation_id!r}")
        return {
            "schema": SCHEMA,
            "source_pattern": SOURCE_PATTERN,
            "config_id": self.config.id,
            "config_version": self.config.version,
            "memory": mem.to_dict(),
        }


def _new_id(prefix: str = "c") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ── demo / CLI ───────────────────────────────────────────────────────────────


def demo_turns(
    inputs: Optional[Sequence[str]] = None,
    *,
    config: Optional[BotConfig] = None,
) -> list[dict[str, Any]]:
    """Run a canned multi-turn demo; return list of turn dicts."""
    eng = ConversationEngine(config or default_bot_config())
    lines = list(
        inputs
        or (
            "hello there",
            "I have a problem with login",
            "need my invoice",
            "bye",
        )
    )
    cid = "demo-conversation"
    results: list[dict[str, Any]] = []
    for line in lines:
        tr = eng.process(line, conversation_id=cid, user_id="demo-user")
        results.append(tr.to_dict())
    results.append({"snapshot": eng.snapshot(cid)})
    return results


def _cli_load_config(args: list[str]) -> tuple[BotConfig, list[str]]:
    """Parse optional ``--config PATH``; return (config, remaining_args)."""
    remaining: list[str] = []
    path: Optional[str] = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--config" and i + 1 < len(args):
            path = args[i + 1]
            i += 2
            continue
        if a.startswith("--config="):
            path = a.split("=", 1)[1]
            i += 1
            continue
        remaining.append(a)
        i += 1
    if path:
        return load_bot_config(path), remaining
    return default_bot_config(), remaining


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry: demo | config | turn [--config PATH]."""
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    cmd = (args[0] if args else "demo").strip().lower()
    rest = args[1:] if args else []

    usage = (
        "usage: python -m nexus.conversation_middleware "
        "[demo|config|turn <text>...] [--config PATH]\n"
        "  demo   — multi-turn support/billing demo (JSON)\n"
        "  config — print bot config JSON (default or --config)\n"
        "  turn   — process remaining args as one user turn\n"
        "  --config PATH — load bot config JSON (demo/turn/config)"
    )

    if cmd in {"-h", "--help", "help"}:
        print(usage)
        return 0

    known = {"demo", "config", "turn"}
    if cmd not in known:
        print(usage, file=sys.stderr)
        print(f"unknown command: {cmd!r}", file=sys.stderr)
        return 2

    try:
        cfg, rest = _cli_load_config(rest)
    except MiddlewareError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if cmd == "config":
        print(json.dumps(cfg.to_dict(), indent=2))
        return 0

    if cmd == "turn":
        text = " ".join(rest).strip() or "hello"
        eng = ConversationEngine(cfg)
        tr = eng.process(text, conversation_id="cli-turn")
        print(json.dumps(tr.to_dict(), indent=2))
        return 0

    # demo
    print(json.dumps({"schema": SCHEMA, "turns": demo_turns(config=cfg)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
