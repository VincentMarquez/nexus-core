"""User Intent Model — ToM-SWE × wshobson/agents marketplace.

Paper: *TOM-SWE: User Mental Modeling For Software Engineering Agents*
https://arxiv.org/abs/2510.21903v2

GitHub pattern (shape only — not a vendored tree):
  wshobson/agents — single-source Markdown marketplace of plugins with
  agents/*.md, skills/*/SKILL.md, commands/*.md (+ multi-harness adapters).

Novel hybrid (portfolio cross_pattern):

  interaction history + ambiguous instruction
                │
                ▼
         ┌──────────────────┐   IntentHypothesis
         │ User Intent Model│ ──► goals / constraints / preferences
         │ (ToM-SWE shape)  │     + marketplace component suggestions
         └──────────────────┘
                │
                ├── persistent UserMemory (per user_id)
                ├── clarify underspecified goals for the SWE agent
                └── route to agents | skills | commands (wshobson surfaces)

ToM-SWE pairs a primary software-engineering agent with a lightweight
theory-of-mind partner that infers user goals, constraints, and preferences
from instructions and interaction history, and keeps a **persistent memory**
of the user. This module is a thin, offline-first User Intent Model for NEXUS:

- process interaction history + current instruction
- detect ambiguity / underspecification signals
- extract goals, constraints, preferences (heuristic, deterministic)
- blend with durable per-user memory
- suggest marketplace agents/skills/commands that match the inferred intent
- produce a clarified instruction for the orchestrator / SWE agent

Storage (JSON, atomic)::

  ``.nexus_state/orchestrator/user_intent/<user_id>.json``
  ``.nexus_state/orchestrator/user_intent/history/<user_id>.jsonl``

No network; no secrets; pattern only — not a vendored upstream tree.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .persist import append_jsonl, atomic_write_json, read_jsonl

SCHEMA = "nexus.user_intent/v1"
PAPER = "arxiv:2510.21903v2"
SOURCE_PATTERN = "wshobson/agents"

MEMORY_REL = Path(".nexus_state") / "orchestrator" / "user_intent"
DEFAULT_USER_ID = "default"
DEFAULT_HISTORY_LIMIT = 50
DEFAULT_SUGGEST_TOP_K = 5
DEFAULT_MAX_MEMORY_GOALS = 20
DEFAULT_MAX_MEMORY_CONSTRAINTS = 30
DEFAULT_MAX_MEMORY_NOTES = 40

# Marketplace surfaces (wshobson shape)
SURFACE_AGENT = "agent"
SURFACE_SKILL = "skill"
SURFACE_COMMAND = "command"
MARKETPLACE_SURFACES: frozenset[str] = frozenset(
    {SURFACE_AGENT, SURFACE_SKILL, SURFACE_COMMAND}
)

ROLES: frozenset[str] = frozenset(
    {"user", "assistant", "system", "agent", "tool", "evaluator"}
)

# Ambiguity cue words (underspecified / context-dependent instructions)
_AMBIGUOUS_WORDS = frozenset(
    {
        "it",
        "this",
        "that",
        "these",
        "those",
        "them",
        "something",
        "somehow",
        "stuff",
        "things",
        "properly",
        "better",
        "nicely",
        "correctly",
        "appropriately",
        "whatever",
        "etc",
        "somehow",
        "fix",
        "improve",
        "handle",
        "do",
        "make",
        "update",
        "change",
    }
)

# Action/goal cue lemmas → normalized goal verbs
_GOAL_CUES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(implement|add|create|build|write|scaffold)\b", re.I), "implement"),
    (re.compile(r"\b(fix|repair|debug|resolve|patch)\b", re.I), "fix"),
    (re.compile(r"\b(refactor|cleanup|clean\s*up|simplify)\b", re.I), "refactor"),
    (re.compile(r"\b(test|cover|pytest|unit\s*test)\b", re.I), "test"),
    (re.compile(r"\b(review|audit|inspect|explain)\b", re.I), "review"),
    (re.compile(r"\b(document|docs|readme)\b", re.I), "document"),
    (re.compile(r"\b(research|arxiv|paper|survey)\b", re.I), "research"),
    (re.compile(r"\b(deploy|release|publish|ship)\b", re.I), "deploy"),
    (re.compile(r"\b(optimize|speed\s*up|performance)\b", re.I), "optimize"),
    (re.compile(r"\b(plan|design|architect)\b", re.I), "plan"),
    (re.compile(r"\b(mine|scout|improve-ours|self-improve)\b", re.I), "self_improve"),
)

# Constraint patterns
_CONSTRAINT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:without|no|don'?t|do not|never|avoid)\s+([^.!?\n,]{3,60})",
        re.I,
    ),
    re.compile(
        r"\b(?:must|should|need to|have to|required to)\s+([^.!?\n,]{3,60})",
        re.I,
    ),
    re.compile(
        r"\b(?:only|just)\s+([^.!?\n,]{3,40})",
        re.I,
    ),
    re.compile(
        r"\b(?:max(?:imum)?|at most|no more than)\s+(\d+\s*\w*)",
        re.I,
    ),
    re.compile(
        r"\bkeep\s+(tests?\s+green|pytest\s+green|small(?:\s+scoped)?(?:\s+change)?s?)",
        re.I,
    ),
    re.compile(
        r"\b(?:do not|don't)\s+(force-?push|vendor|commit\s+secrets)",
        re.I,
    ),
)

# Preference patterns
_PREF_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bprefer(?:s|red)?\s+([^.!?\n,]{2,40})", re.I), "prefer"),
    (re.compile(r"\blike(?:s)?\s+to\s+([^.!?\n,]{2,40})", re.I), "like"),
    (re.compile(r"\buse\s+(pytest|make\s+test|typed|dataclasses?)\b", re.I), "use"),
    (re.compile(r"\bin\s+(python|rust|go|typescript|markdown)\b", re.I), "language"),
)


class UserIntentError(ValueError):
    """User intent model invalid input or storage error."""


# ── helpers ─────────────────────────────────────────────────────────────────


def _root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is None:
        return Path.cwd().resolve()
    return Path(workdir).resolve()


def _new_id(prefix: str = "intent") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def sanitize_user_id(user_id: str) -> str:
    raw = str(user_id or "").strip() or DEFAULT_USER_ID
    # Fail-closed path segment: alnum + ._- only
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw)[:64]
    if not cleaned or cleaned in {".", ".."}:
        raise UserIntentError(f"invalid user_id: {user_id!r}")
    return cleaned


def memory_dir(workdir: Optional[Path | str] = None) -> Path:
    d = _root(workdir) / MEMORY_REL
    d.mkdir(parents=True, exist_ok=True)
    (d / "history").mkdir(parents=True, exist_ok=True)
    return d


def memory_path(workdir: Optional[Path | str], user_id: str) -> Path:
    return memory_dir(workdir) / f"{sanitize_user_id(user_id)}.json"


def history_path(workdir: Optional[Path | str], user_id: str) -> Path:
    return memory_dir(workdir) / "history" / f"{sanitize_user_id(user_id)}.jsonl"


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9_\-]{1,}", str(text or "").lower())


def _unique_preserve(items: Iterable[str], *, limit: int = 50) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        s = str(raw or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


# ── data ────────────────────────────────────────────────────────────────────


@dataclass
class InteractionTurn:
    """One turn in the interaction history (ToM-SWE history surface)."""

    role: str
    content: str
    ts: float = field(default_factory=lambda: time.time())
    turn_id: str = field(default_factory=lambda: _new_id("turn"))
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.role = str(self.role or "user").strip().lower() or "user"
        if self.role not in ROLES:
            # Soft-accept unknown roles as "user" rather than hard-fail history import
            self.role = "user"
        self.content = str(self.content or "")
        self.ts = float(self.ts or time.time())
        self.turn_id = str(self.turn_id or _new_id("turn"))
        if not isinstance(self.meta, dict):
            self.meta = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "ts": self.ts,
            "turn_id": self.turn_id,
            "meta": dict(self.meta or {}),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "InteractionTurn":
        d = dict(raw or {})
        return cls(
            role=str(d.get("role") or "user"),
            content=str(d.get("content") or d.get("text") or ""),
            ts=float(d.get("ts") or time.time()),
            turn_id=str(d.get("turn_id") or _new_id("turn")),
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
        )


@dataclass
class UserMemory:
    """Persistent mental model of the user (ToM-SWE memory)."""

    user_id: str = DEFAULT_USER_ID
    goals: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    n_interactions: int = 0
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    schema: str = SCHEMA
    paper: str = PAPER
    source_pattern: str = SOURCE_PATTERN

    def __post_init__(self) -> None:
        self.user_id = sanitize_user_id(self.user_id)
        self.goals = _unique_preserve(self.goals, limit=DEFAULT_MAX_MEMORY_GOALS)
        self.constraints = _unique_preserve(
            self.constraints, limit=DEFAULT_MAX_MEMORY_CONSTRAINTS
        )
        self.notes = _unique_preserve(self.notes, limit=DEFAULT_MAX_MEMORY_NOTES)
        if not isinstance(self.preferences, dict):
            self.preferences = {}
        self.n_interactions = max(0, int(self.n_interactions or 0))
        self.schema = SCHEMA
        self.paper = PAPER
        self.source_pattern = SOURCE_PATTERN

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "paper": self.paper,
            "source_pattern": self.source_pattern,
            "user_id": self.user_id,
            "goals": list(self.goals),
            "constraints": list(self.constraints),
            "preferences": dict(self.preferences),
            "notes": list(self.notes),
            "n_interactions": self.n_interactions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "UserMemory":
        d = dict(raw or {})
        return cls(
            user_id=str(d.get("user_id") or DEFAULT_USER_ID),
            goals=list(d.get("goals") or []),
            constraints=list(d.get("constraints") or []),
            preferences=dict(d.get("preferences") or {})
            if isinstance(d.get("preferences"), dict)
            else {},
            notes=list(d.get("notes") or []),
            n_interactions=int(d.get("n_interactions") or 0),
            created_at=float(d.get("created_at") or time.time()),
            updated_at=float(d.get("updated_at") or time.time()),
        )

    def blend(
        self,
        *,
        goals: Optional[Sequence[str]] = None,
        constraints: Optional[Sequence[str]] = None,
        preferences: Optional[dict[str, Any]] = None,
        notes: Optional[Sequence[str]] = None,
        touch_interaction: bool = True,
    ) -> "UserMemory":
        """Return updated memory with new signals merged in."""
        if goals:
            self.goals = _unique_preserve(
                list(goals) + list(self.goals), limit=DEFAULT_MAX_MEMORY_GOALS
            )
        if constraints:
            self.constraints = _unique_preserve(
                list(constraints) + list(self.constraints),
                limit=DEFAULT_MAX_MEMORY_CONSTRAINTS,
            )
        if notes:
            self.notes = _unique_preserve(
                list(notes) + list(self.notes), limit=DEFAULT_MAX_MEMORY_NOTES
            )
        if preferences:
            for k, v in preferences.items():
                if v is None or v == "":
                    continue
                self.preferences[str(k)] = v
        if touch_interaction:
            self.n_interactions += 1
        self.updated_at = time.time()
        return self


@dataclass
class ComponentSuggestion:
    """Marketplace component suggested for the inferred intent (wshobson surface)."""

    kind: str
    name: str
    plugin_id: str = ""
    score: float = 0.0
    reason: str = ""
    path: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        self.kind = str(self.kind or "").strip().lower()
        if self.kind not in MARKETPLACE_SURFACES:
            raise UserIntentError(
                f"suggestion kind must be one of {sorted(MARKETPLACE_SURFACES)}; "
                f"got {self.kind!r}"
            )
        self.name = str(self.name or "").strip()
        if not self.name:
            raise UserIntentError("suggestion name must be non-empty")
        self.plugin_id = str(self.plugin_id or "").strip()
        self.score = float(self.score or 0.0)
        self.reason = str(self.reason or "")
        self.path = str(self.path or "")
        self.description = str(self.description or "")

    @property
    def tool_id(self) -> str:
        if self.plugin_id:
            return f"{self.kind}:{self.name}@{self.plugin_id}"
        return f"{self.kind}:{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "plugin_id": self.plugin_id,
            "score": round(self.score, 4),
            "reason": self.reason,
            "path": self.path,
            "description": self.description,
            "tool_id": self.tool_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ComponentSuggestion":
        d = dict(raw or {})
        return cls(
            kind=str(d.get("kind") or SURFACE_AGENT),
            name=str(d.get("name") or ""),
            plugin_id=str(d.get("plugin_id") or ""),
            score=float(d.get("score") or 0.0),
            reason=str(d.get("reason") or ""),
            path=str(d.get("path") or ""),
            description=str(d.get("description") or ""),
        )


@dataclass
class IntentHypothesis:
    """Structured user intent (ToM partner output for the SWE agent)."""

    goal: str
    constraints: list[str] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)
    ambiguity: list[str] = field(default_factory=list)
    confidence: float = 0.0
    clarified_instruction: str = ""
    suggested_components: list[ComponentSuggestion] = field(default_factory=list)
    history_used: int = 0
    memory_used: bool = False
    goal_verbs: list[str] = field(default_factory=list)
    raw_instruction: str = ""
    user_id: str = DEFAULT_USER_ID
    intent_id: str = field(default_factory=lambda: _new_id("intent"))
    ts: float = field(default_factory=lambda: time.time())
    schema: str = SCHEMA
    paper: str = PAPER
    source_pattern: str = SOURCE_PATTERN
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.goal = str(self.goal or "").strip()
        self.constraints = _unique_preserve(self.constraints, limit=40)
        if not isinstance(self.preferences, dict):
            self.preferences = {}
        self.ambiguity = _unique_preserve(self.ambiguity, limit=20)
        self.confidence = max(0.0, min(1.0, float(self.confidence or 0.0)))
        self.clarified_instruction = str(
            self.clarified_instruction or self.goal or self.raw_instruction or ""
        )
        self.history_used = max(0, int(self.history_used or 0))
        self.goal_verbs = _unique_preserve(self.goal_verbs, limit=12)
        self.raw_instruction = str(self.raw_instruction or "")
        self.user_id = sanitize_user_id(self.user_id)
        self.schema = SCHEMA
        self.paper = PAPER
        self.source_pattern = SOURCE_PATTERN
        self.notes = _unique_preserve(self.notes, limit=20)

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguity) or self.confidence < 0.55

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "paper": self.paper,
            "source_pattern": self.source_pattern,
            "intent_id": self.intent_id,
            "user_id": self.user_id,
            "ts": self.ts,
            "goal": self.goal,
            "goal_verbs": list(self.goal_verbs),
            "constraints": list(self.constraints),
            "preferences": dict(self.preferences),
            "ambiguity": list(self.ambiguity),
            "is_ambiguous": self.is_ambiguous,
            "confidence": round(self.confidence, 4),
            "clarified_instruction": self.clarified_instruction,
            "suggested_components": [c.to_dict() for c in self.suggested_components],
            "history_used": self.history_used,
            "memory_used": self.memory_used,
            "raw_instruction": self.raw_instruction,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "IntentHypothesis":
        d = dict(raw or {})
        comps: list[ComponentSuggestion] = []
        for c in d.get("suggested_components") or []:
            if isinstance(c, dict):
                try:
                    comps.append(ComponentSuggestion.from_dict(c))
                except UserIntentError:
                    continue
        return cls(
            goal=str(d.get("goal") or ""),
            constraints=list(d.get("constraints") or []),
            preferences=dict(d.get("preferences") or {})
            if isinstance(d.get("preferences"), dict)
            else {},
            ambiguity=list(d.get("ambiguity") or []),
            confidence=float(d.get("confidence") or 0.0),
            clarified_instruction=str(d.get("clarified_instruction") or ""),
            suggested_components=comps,
            history_used=int(d.get("history_used") or 0),
            memory_used=bool(d.get("memory_used")),
            goal_verbs=list(d.get("goal_verbs") or []),
            raw_instruction=str(d.get("raw_instruction") or ""),
            user_id=str(d.get("user_id") or DEFAULT_USER_ID),
            intent_id=str(d.get("intent_id") or _new_id("intent")),
            ts=float(d.get("ts") or time.time()),
            notes=list(d.get("notes") or []),
        )

    def summary(self) -> str:
        amb = f" ambiguous={len(self.ambiguity)}" if self.ambiguity else ""
        n_s = len(self.suggested_components)
        return (
            f"intent[{self.intent_id[:16]}…] goal={self.goal!r} "
            f"conf={self.confidence:.2f} constraints={len(self.constraints)} "
            f"suggestions={n_s}{amb}"
        )


# ── extraction (offline heuristics) ─────────────────────────────────────────


def detect_ambiguity(text: str, *, history: Optional[Sequence[InteractionTurn]] = None) -> list[str]:
    """Return human-readable underspecification signals (ToM-SWE gap cues)."""
    raw = str(text or "").strip()
    signals: list[str] = []
    if not raw:
        signals.append("empty_instruction")
        return signals

    tokens = _tokenize(raw)
    if len(tokens) < 4:
        signals.append("very_short_instruction")

    # Pronouns / vague words without nearby noun context
    vague_hits = [t for t in tokens if t in _AMBIGUOUS_WORDS]
    # Count only weak/vague without strong goal object
    weak = {"it", "this", "that", "these", "those", "them", "something", "stuff", "things", "whatever"}
    if any(t in weak for t in tokens):
        # If history is empty, pronouns are more dangerous
        if not history:
            signals.append("deictic_without_history")
        else:
            # Still flag when instruction is mostly deictic
            if sum(1 for t in tokens if t in weak) >= 1 and len(tokens) <= 8:
                signals.append("deictic_underspecified")

    if any(t in {"properly", "better", "nicely", "correctly", "appropriately"} for t in tokens):
        signals.append("subjective_quality_unspecified")

    # Action without object: "fix it", "make better", "update"
    if re.search(r"^\s*(fix|update|change|improve|handle|do)\s+(it|this|that)\s*[.!]?\s*$", raw, re.I):
        signals.append("action_without_object")

    if re.search(r"^\s*(fix|improve|update|handle)\s*[.!]?\s*$", raw, re.I):
        signals.append("bare_action_verb")

    # Missing success criteria
    if not re.search(r"\b(test|pytest|pass|green|verify|assert|criteria|until)\b", raw, re.I):
        if any(v.search(raw) for v, _ in _GOAL_CUES if _ in {"implement", "fix", "refactor"}):
            signals.append("no_success_criteria")

    # Duplicate vague cue
    if vague_hits and len(set(vague_hits) & weak) >= 2:
        signals.append("multiple_vague_referents")

    return _unique_preserve(signals, limit=12)


def extract_goal_verbs(text: str) -> list[str]:
    """Map instruction text to normalized goal verbs."""
    found: list[str] = []
    for pat, verb in _GOAL_CUES:
        if pat.search(text or ""):
            found.append(verb)
    return _unique_preserve(found, limit=12)


def extract_constraints(text: str) -> list[str]:
    """Pull constraint phrases from instruction text."""
    out: list[str] = []
    raw = str(text or "")
    for pat in _CONSTRAINT_PATTERNS:
        for m in pat.finditer(raw):
            frag = m.group(0).strip()
            if len(frag) >= 5:
                out.append(frag[:120])
    # Also split semicolon/newline bullet constraints
    for line in re.split(r"[\n;]+", raw):
        s = line.strip().lstrip("-*• ").strip()
        if re.match(r"^(do not|don't|never|must|without|no vendor|no force)", s, re.I):
            out.append(s[:120])
    return _unique_preserve(out, limit=20)


def extract_preferences(text: str) -> dict[str, Any]:
    """Pull soft preferences from instruction text."""
    prefs: dict[str, Any] = {}
    raw = str(text or "")
    for pat, key in _PREF_PATTERNS:
        m = pat.search(raw)
        if not m:
            continue
        val = (m.group(1) if m.lastindex else m.group(0)).strip()[:80]
        if key in prefs:
            # keep list when multiple
            prev = prefs[key]
            if isinstance(prev, list):
                prev.append(val)
            else:
                prefs[key] = [prev, val]
        else:
            prefs[key] = val
    if re.search(r"\bsmall\s+scoped\b", raw, re.I):
        prefs["scope"] = "small"
    if re.search(r"\boffline[- ]first\b", raw, re.I):
        prefs["offline"] = True
    return prefs


def extract_goal_phrase(text: str, *, goal_verbs: Optional[Sequence[str]] = None) -> str:
    """Best-effort single-line goal from the instruction."""
    raw = " ".join(str(text or "").split())
    if not raw:
        return ""
    # First sentence, capped
    first = re.split(r"[.!?\n]", raw, maxsplit=1)[0].strip()
    if not first:
        first = raw
    verbs = list(goal_verbs or extract_goal_verbs(raw))
    if verbs and not any(v in first.lower() for v in verbs):
        return f"{verbs[0]}: {first[:200]}"
    return first[:240]


def history_context_snippets(
    history: Sequence[InteractionTurn],
    *,
    max_turns: int = 8,
    max_chars: int = 400,
) -> list[str]:
    """Recent user-side snippets for clarifying deictic references."""
    userish = [t for t in history if t.role in {"user", "system"} and t.content.strip()]
    tail = userish[-max_turns:]
    out: list[str] = []
    for t in tail:
        snippet = " ".join(t.content.split())[:max_chars]
        if snippet:
            out.append(snippet)
    return out


# ── marketplace suggestions (wshobson surfaces) ─────────────────────────────


def _list_marketplace_components(
    workdir: Optional[Path | str],
    *,
    plugins_dir: str = "plugins",
    include_skillpacks: bool = True,
) -> list[dict[str, Any]]:
    """Reuse marketplace discovery when available; else lightweight scan."""
    root = _root(workdir)
    components: list[dict[str, Any]] = []
    try:
        from . import marketplace as mp

        infos = mp.list_plugins(
            root,
            plugins_dir=plugins_dir,
            include_skillpacks=include_skillpacks,
        )
        for info in infos:
            pid = getattr(info, "id", "") or ""
            for name in list(getattr(info, "agents", None) or []):
                components.append(
                    {
                        "kind": SURFACE_AGENT,
                        "name": name,
                        "plugin_id": pid,
                        "path": f"agents/{name}.md",
                        "description": "",
                    }
                )
            for name in list(getattr(info, "skills", None) or []):
                components.append(
                    {
                        "kind": SURFACE_SKILL,
                        "name": name,
                        "plugin_id": pid,
                        "path": f"skills/{name}/SKILL.md",
                        "description": "",
                    }
                )
            for name in list(getattr(info, "commands", None) or []):
                components.append(
                    {
                        "kind": SURFACE_COMMAND,
                        "name": name,
                        "plugin_id": pid,
                        "path": f"commands/{name}.md",
                        "description": "",
                    }
                )
        return components
    except Exception:
        pass

    plugins_path = root / plugins_dir
    if not plugins_path.is_dir():
        return components
    for pdir in sorted(plugins_path.iterdir()):
        if not pdir.is_dir() or pdir.name.startswith("."):
            continue
        pid = pdir.name
        for kind, sub, pattern in (
            (SURFACE_AGENT, "agents", "*.md"),
            (SURFACE_COMMAND, "commands", "*.md"),
        ):
            d = pdir / sub
            if d.is_dir():
                for f in sorted(d.glob(pattern)):
                    components.append(
                        {
                            "kind": kind,
                            "name": f.stem,
                            "plugin_id": pid,
                            "path": f"{sub}/{f.name}",
                            "description": "",
                        }
                    )
        skills = pdir / "skills"
        if skills.is_dir():
            for sd in sorted(skills.iterdir()):
                if sd.is_dir() and (sd / "SKILL.md").is_file():
                    components.append(
                        {
                            "kind": SURFACE_SKILL,
                            "name": sd.name,
                            "plugin_id": pid,
                            "path": f"skills/{sd.name}/SKILL.md",
                            "description": "",
                        }
                    )
    return components


def score_component(
    component: dict[str, Any],
    *,
    query_tokens: Sequence[str],
    goal_verbs: Sequence[str],
    constraints: Sequence[str],
) -> tuple[float, str]:
    """Token-overlap score between intent and a marketplace component."""
    name = str(component.get("name") or "").lower()
    kind = str(component.get("kind") or "").lower()
    plugin = str(component.get("plugin_id") or "").lower()
    desc = str(component.get("description") or "").lower()
    bag = set(_tokenize(f"{name} {plugin} {desc} {kind}"))
    q = set(t for t in query_tokens if len(t) > 2)
    if not bag or not q:
        base = 0.05 if goal_verbs else 0.0
        return base, "weak_default" if base else "no_overlap"

    overlap = bag & q
    score = 0.0
    reasons: list[str] = []
    if overlap:
        score += 0.35 * (len(overlap) / max(1, len(q)))
        reasons.append(f"token_overlap={sorted(overlap)[:4]}")

    # Goal verb affinity
    verb_boost = {
        "implement": {SURFACE_AGENT, SURFACE_SKILL},
        "fix": {SURFACE_AGENT, SURFACE_SKILL},
        "test": {SURFACE_SKILL, SURFACE_COMMAND},
        "review": {SURFACE_AGENT, SURFACE_COMMAND},
        "research": {SURFACE_AGENT, SURFACE_SKILL},
        "document": {SURFACE_SKILL, SURFACE_COMMAND},
        "deploy": {SURFACE_COMMAND, SURFACE_AGENT},
        "self_improve": {SURFACE_AGENT, SURFACE_SKILL, SURFACE_COMMAND},
        "plan": {SURFACE_AGENT},
        "optimize": {SURFACE_SKILL, SURFACE_AGENT},
        "refactor": {SURFACE_AGENT, SURFACE_SKILL},
    }
    for v in goal_verbs:
        kinds = verb_boost.get(v, set())
        if kind in kinds:
            score += 0.12
            reasons.append(f"verb_affinity={v}:{kind}")
        # Name contains verb-ish stem
        stem = v.split("_")[0]
        if stem and stem in name:
            score += 0.2
            reasons.append(f"name_has_{stem}")

    # Constraints that mention a component name
    for c in constraints:
        ct = set(_tokenize(c))
        if bag & ct:
            score += 0.08
            reasons.append("constraint_match")
            break

    # Prefer agents slightly for open-ended goals
    if kind == SURFACE_AGENT and goal_verbs:
        score += 0.05

    score = max(0.0, min(1.0, score))
    reason = "; ".join(reasons) if reasons else "low_score"
    return score, reason


def suggest_marketplace_components(
    workdir: Optional[Path | str],
    *,
    instruction: str,
    goal_verbs: Optional[Sequence[str]] = None,
    constraints: Optional[Sequence[str]] = None,
    top_k: int = DEFAULT_SUGGEST_TOP_K,
    plugins_dir: str = "plugins",
    min_score: float = 0.08,
) -> list[ComponentSuggestion]:
    """Rank marketplace agents/skills/commands for the inferred intent."""
    verbs = list(goal_verbs or extract_goal_verbs(instruction))
    cons = list(constraints or extract_constraints(instruction))
    q_tokens = _tokenize(instruction) + [v for v in verbs]
    # expand goal verb stems into query
    for v in verbs:
        q_tokens.extend(v.split("_"))

    components = _list_marketplace_components(
        workdir, plugins_dir=plugins_dir, include_skillpacks=True
    )
    scored: list[ComponentSuggestion] = []
    for c in components:
        sc, reason = score_component(
            c, query_tokens=q_tokens, goal_verbs=verbs, constraints=cons
        )
        if sc < min_score:
            continue
        try:
            scored.append(
                ComponentSuggestion(
                    kind=str(c.get("kind") or SURFACE_AGENT),
                    name=str(c.get("name") or ""),
                    plugin_id=str(c.get("plugin_id") or ""),
                    score=sc,
                    reason=reason,
                    path=str(c.get("path") or ""),
                    description=str(c.get("description") or ""),
                )
            )
        except UserIntentError:
            continue
    scored.sort(key=lambda s: (-s.score, s.kind, s.name))
    return scored[: max(0, int(top_k))]


# ── clarify / confidence ────────────────────────────────────────────────────


def clarify_instruction(
    instruction: str,
    *,
    goal: str,
    goal_verbs: Sequence[str],
    constraints: Sequence[str],
    preferences: dict[str, Any],
    ambiguity: Sequence[str],
    history: Optional[Sequence[InteractionTurn]] = None,
    memory: Optional[UserMemory] = None,
) -> str:
    """Build a clarified instruction the SWE agent can execute more reliably."""
    parts: list[str] = []
    base = str(instruction or "").strip()
    g = str(goal or base).strip()

    if ambiguity and history:
        snippets = history_context_snippets(history, max_turns=3, max_chars=160)
        if snippets:
            parts.append("Context from prior turns: " + " | ".join(snippets))

    if memory and memory.goals:
        # Only inject memory goals when instruction is ambiguous/short
        if ambiguity or len(_tokenize(base)) < 6:
            mem_g = "; ".join(memory.goals[:3])
            parts.append(f"User's standing goals: {mem_g}")

    if goal_verbs:
        parts.append(f"Inferred intent: {', '.join(goal_verbs)} — {g}")
    else:
        parts.append(f"Goal: {g}")

    if constraints:
        parts.append("Constraints: " + "; ".join(constraints[:8]))
    elif memory and memory.constraints and ambiguity:
        parts.append(
            "Standing constraints: " + "; ".join(memory.constraints[:5])
        )

    pref_bits: list[str] = []
    for k, v in (preferences or {}).items():
        pref_bits.append(f"{k}={v}")
    if not pref_bits and memory and memory.preferences and ambiguity:
        for k, v in list(memory.preferences.items())[:5]:
            pref_bits.append(f"{k}={v}")
    if pref_bits:
        parts.append("Preferences: " + ", ".join(pref_bits))

    if ambiguity:
        parts.append(
            "Ambiguity flags (resolve using history/memory when possible): "
            + ", ".join(ambiguity)
        )

    # Always keep original instruction visible
    if base and base not in " ".join(parts):
        parts.insert(0, f"Original: {base}")

    return "\n".join(parts)


def compute_confidence(
    *,
    instruction: str,
    goal_verbs: Sequence[str],
    constraints: Sequence[str],
    ambiguity: Sequence[str],
    history_used: int,
    memory_used: bool,
) -> float:
    """Deterministic confidence in [0, 1]."""
    tokens = _tokenize(instruction)
    conf = 0.35
    if goal_verbs:
        conf += 0.2
    if len(tokens) >= 8:
        conf += 0.1
    if len(tokens) >= 16:
        conf += 0.05
    if constraints:
        conf += min(0.15, 0.05 * len(constraints))
    if history_used > 0:
        conf += min(0.1, 0.03 * history_used)
    if memory_used:
        conf += 0.05
    # Ambiguity penalties
    conf -= 0.08 * len(ambiguity)
    if "empty_instruction" in ambiguity:
        conf = min(conf, 0.1)
    if "bare_action_verb" in ambiguity:
        conf -= 0.1
    return max(0.0, min(1.0, round(conf, 4)))


# ── core infer ──────────────────────────────────────────────────────────────


def infer_intent(
    instruction: str,
    *,
    history: Optional[Sequence[InteractionTurn | dict[str, Any]]] = None,
    memory: Optional[UserMemory | dict[str, Any]] = None,
    workdir: Optional[Path | str] = None,
    user_id: str = DEFAULT_USER_ID,
    suggest: bool = True,
    top_k: int = DEFAULT_SUGGEST_TOP_K,
    plugins_dir: str = "plugins",
    update_memory: bool = False,
) -> IntentHypothesis:
    """Infer structured user intent from instruction + history + memory.

    Offline, deterministic ToM-SWE-shaped User Intent Model. Optionally ranks
    marketplace components (agents/skills/commands) for routing.
    """
    raw = str(instruction or "")
    turns: list[InteractionTurn] = []
    for h in history or []:
        if isinstance(h, InteractionTurn):
            turns.append(h)
        elif isinstance(h, dict):
            turns.append(InteractionTurn.from_dict(h))

    mem: Optional[UserMemory] = None
    if isinstance(memory, UserMemory):
        mem = memory
    elif isinstance(memory, dict):
        mem = UserMemory.from_dict(memory)

    # Blend history text for extraction (user turns + current)
    history_text = "\n".join(
        t.content for t in turns if t.role in {"user", "system"} and t.content.strip()
    )
    combined = (history_text + "\n" + raw).strip() if history_text else raw

    goal_verbs = extract_goal_verbs(combined)
    # Prefer current-instruction verbs when present
    cur_verbs = extract_goal_verbs(raw)
    if cur_verbs:
        goal_verbs = _unique_preserve(list(cur_verbs) + list(goal_verbs), limit=12)

    constraints = extract_constraints(combined)
    if mem and mem.constraints:
        # Standing constraints always apply
        constraints = _unique_preserve(
            list(constraints) + list(mem.constraints), limit=30
        )

    preferences = extract_preferences(combined)
    if mem and mem.preferences:
        for k, v in mem.preferences.items():
            preferences.setdefault(k, v)

    ambiguity = detect_ambiguity(raw, history=turns)
    goal = extract_goal_phrase(raw, goal_verbs=goal_verbs)
    if not goal and mem and mem.goals:
        goal = mem.goals[0]
        ambiguity = _unique_preserve(
            list(ambiguity) + ["goal_from_memory"], limit=12
        )

    history_used = len(turns)
    memory_used = bool(
        mem
        and (
            mem.goals
            or mem.constraints
            or mem.preferences
            or mem.n_interactions > 0
        )
    )

    confidence = compute_confidence(
        instruction=raw,
        goal_verbs=goal_verbs,
        constraints=constraints,
        ambiguity=ambiguity,
        history_used=history_used,
        memory_used=memory_used,
    )

    clarified = clarify_instruction(
        raw,
        goal=goal or raw,
        goal_verbs=goal_verbs,
        constraints=constraints,
        preferences=preferences,
        ambiguity=ambiguity,
        history=turns,
        memory=mem,
    )

    suggestions: list[ComponentSuggestion] = []
    if suggest and workdir is not None:
        suggestions = suggest_marketplace_components(
            workdir,
            instruction=combined or raw,
            goal_verbs=goal_verbs,
            constraints=constraints,
            top_k=top_k,
            plugins_dir=plugins_dir,
        )
    elif suggest and workdir is None:
        # Still allow cwd-based discovery when caller wants suggestions
        try:
            suggestions = suggest_marketplace_components(
                Path.cwd(),
                instruction=combined or raw,
                goal_verbs=goal_verbs,
                constraints=constraints,
                top_k=top_k,
                plugins_dir=plugins_dir,
            )
        except Exception:
            suggestions = []

    notes: list[str] = []
    if suggestions:
        notes.append(
            f"top_component={suggestions[0].tool_id} score={suggestions[0].score:.2f}"
        )
    if memory_used:
        notes.append("blended_user_memory")

    hyp = IntentHypothesis(
        goal=goal or raw.strip()[:240],
        constraints=constraints,
        preferences=preferences,
        ambiguity=ambiguity,
        confidence=confidence,
        clarified_instruction=clarified,
        suggested_components=suggestions,
        history_used=history_used,
        memory_used=memory_used,
        goal_verbs=goal_verbs,
        raw_instruction=raw,
        user_id=user_id,
        notes=notes,
    )

    if update_memory and mem is not None:
        mem.blend(
            goals=[hyp.goal] if hyp.goal else None,
            constraints=hyp.constraints,
            preferences=hyp.preferences,
            notes=[f"intent:{hyp.intent_id}"] if hyp.intent_id else None,
        )

    return hyp


# ── UserIntentModel (store + API) ───────────────────────────────────────────


@dataclass
class UserIntentModel:
    """Durable ToM-style user intent model for a workdir."""

    workdir: Path
    user_id: str = DEFAULT_USER_ID
    history_limit: int = DEFAULT_HISTORY_LIMIT

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir).resolve()
        self.user_id = sanitize_user_id(self.user_id)
        self.history_limit = max(1, int(self.history_limit or DEFAULT_HISTORY_LIMIT))
        memory_dir(self.workdir)

    @classmethod
    def open(
        cls,
        workdir: Optional[Path | str] = None,
        *,
        user_id: str = DEFAULT_USER_ID,
        **kw: Any,
    ) -> "UserIntentModel":
        return cls(workdir=_root(workdir), user_id=user_id, **kw)

    # ── memory ──────────────────────────────────────────────────────────

    def load_memory(self) -> UserMemory:
        path = memory_path(self.workdir, self.user_id)
        if not path.is_file():
            return UserMemory(user_id=self.user_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return UserMemory(user_id=self.user_id)
        if not isinstance(data, dict):
            return UserMemory(user_id=self.user_id)
        mem = UserMemory.from_dict(data)
        mem.user_id = self.user_id
        return mem

    def save_memory(self, memory: UserMemory) -> Path:
        memory.user_id = self.user_id
        memory.updated_at = time.time()
        path = memory_path(self.workdir, self.user_id)
        atomic_write_json(path, memory.to_dict())
        return path

    # ── history ─────────────────────────────────────────────────────────

    def append_turn(self, turn: InteractionTurn | dict[str, Any]) -> InteractionTurn:
        t = turn if isinstance(turn, InteractionTurn) else InteractionTurn.from_dict(turn)
        path = history_path(self.workdir, self.user_id)
        append_jsonl(path, t.to_dict())
        return t

    def load_history(self, *, limit: Optional[int] = None) -> list[InteractionTurn]:
        path = history_path(self.workdir, self.user_id)
        if not path.is_file():
            return []
        rows = read_jsonl(path)
        cap = int(limit if limit is not None else self.history_limit)
        # Keep newest *cap* turns
        if cap > 0 and len(rows) > cap:
            rows = rows[-cap:]
        out: list[InteractionTurn] = []
        for r in rows:
            if isinstance(r, dict):
                out.append(InteractionTurn.from_dict(r))
        return out

    def observe(
        self,
        content: str,
        *,
        role: str = "user",
        meta: Optional[dict[str, Any]] = None,
    ) -> InteractionTurn:
        """Record an interaction turn into durable history."""
        turn = InteractionTurn(role=role, content=content, meta=dict(meta or {}))
        return self.append_turn(turn)

    # ── infer ───────────────────────────────────────────────────────────

    def infer(
        self,
        instruction: str,
        *,
        history: Optional[Sequence[InteractionTurn | dict[str, Any]]] = None,
        suggest: bool = True,
        top_k: int = DEFAULT_SUGGEST_TOP_K,
        plugins_dir: str = "plugins",
        persist: bool = True,
        record_instruction: bool = True,
    ) -> IntentHypothesis:
        """Infer intent; optionally persist memory + record the instruction turn."""
        mem = self.load_memory()
        turns: list[InteractionTurn | dict[str, Any]]
        if history is not None:
            turns = list(history)
        else:
            turns = list(self.load_history())

        if record_instruction and str(instruction or "").strip():
            self.observe(str(instruction), role="user", meta={"source": "infer"})
            # include the just-recorded turn in this inference's history
            turns = list(turns) + [
                InteractionTurn(role="user", content=str(instruction))
            ]

        hyp = infer_intent(
            instruction,
            history=turns,
            memory=mem,
            workdir=self.workdir,
            user_id=self.user_id,
            suggest=suggest,
            top_k=top_k,
            plugins_dir=plugins_dir,
            update_memory=True,
        )

        if persist:
            # mem was mutated by update_memory=True
            self.save_memory(mem)

        return hyp

    def stats(self) -> dict[str, Any]:
        mem = self.load_memory()
        hist = self.load_history()
        return {
            "schema": SCHEMA,
            "paper": PAPER,
            "source_pattern": SOURCE_PATTERN,
            "user_id": self.user_id,
            "workdir": str(self.workdir),
            "n_history": len(hist),
            "n_interactions": mem.n_interactions,
            "n_goals": len(mem.goals),
            "n_constraints": len(mem.constraints),
            "n_preferences": len(mem.preferences),
            "memory_path": str(memory_path(self.workdir, self.user_id)),
        }


# ── orchestrator soft hook ──────────────────────────────────────────────────


def maybe_infer_for_task(
    workdir: Optional[Path | str],
    task_id: str,
    goal: str,
    meta: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """If meta requests user_intent, run the ToM User Intent Model.

    Trigger keys on meta:
      - ``user_intent``: truthy
      - ``with_user_intent``: truthy
      - ``infer_intent``: truthy

    Optional:
      - ``user_id``: memory key (default ``default``)
      - ``intent_suggest``: bool (default True) — marketplace suggestions
      - ``intent_top_k``: int
      - ``intent_persist``: bool (default True)

    Returns a small summary dict (plus full hypothesis under ``intent``) or None.
    """
    if not meta or not isinstance(meta, dict):
        return None
    enabled = bool(
        meta.get("user_intent")
        or meta.get("with_user_intent")
        or meta.get("infer_intent")
    )
    if not enabled:
        return None

    user_id = str(meta.get("user_id") or DEFAULT_USER_ID)
    suggest = meta.get("intent_suggest")
    if suggest is None:
        suggest = True
    top_k = int(meta.get("intent_top_k") or DEFAULT_SUGGEST_TOP_K)
    persist = meta.get("intent_persist")
    if persist is None:
        persist = True

    model = UserIntentModel.open(workdir, user_id=user_id)
    # External history can be passed as list of {role, content}
    extra_hist = meta.get("intent_history")
    history: Optional[list[Any]] = None
    if isinstance(extra_hist, list):
        history = extra_hist

    hyp = model.infer(
        str(goal or ""),
        history=history,
        suggest=bool(suggest),
        top_k=top_k,
        persist=bool(persist),
        # goal already is the task instruction; still record once
        record_instruction=True,
    )

    return {
        "ok": True,
        "schema": SCHEMA,
        "paper": PAPER,
        "source_pattern": SOURCE_PATTERN,
        "task_id": str(task_id or ""),
        "user_id": hyp.user_id,
        "intent_id": hyp.intent_id,
        "goal": hyp.goal,
        "confidence": hyp.confidence,
        "is_ambiguous": hyp.is_ambiguous,
        "ambiguity": list(hyp.ambiguity),
        "constraints": list(hyp.constraints),
        "goal_verbs": list(hyp.goal_verbs),
        "clarified_instruction": hyp.clarified_instruction,
        "n_suggestions": len(hyp.suggested_components),
        "top_suggestions": [c.to_dict() for c in hyp.suggested_components[:5]],
        "intent": hyp.to_dict(),
    }


# ── Module CLI ──────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(
        prog="python -m nexus.user_intent",
        description="User Intent Model (ToM-SWE × wshobson marketplace)",
    )
    p.add_argument("--workdir", default=".", help="Project workdir")
    p.add_argument("--user-id", default=DEFAULT_USER_ID, help="User memory key")
    sub = p.add_subparsers(dest="cmd", required=True)

    inf = sub.add_parser("infer", help="Infer intent from instruction")
    inf.add_argument("instruction", nargs="+", help="Instruction text")
    inf.add_argument("--no-suggest", action="store_true")
    inf.add_argument("--no-persist", action="store_true")
    inf.add_argument("--top-k", type=int, default=DEFAULT_SUGGEST_TOP_K)
    inf.add_argument("--json", action="store_true")

    obs = sub.add_parser("observe", help="Append a history turn")
    obs.add_argument("content", nargs="+", help="Turn content")
    obs.add_argument("--role", default="user")

    sub.add_parser("memory", help="Show durable user memory")
    sub.add_parser("history", help="Show interaction history")
    sub.add_parser("stats", help="Show model stats")

    clr = sub.add_parser("clear-history", help="Clear history jsonl for user")
    clr.add_argument("--yes", action="store_true")

    args = p.parse_args(list(argv) if argv is not None else None)
    model = UserIntentModel.open(args.workdir, user_id=args.user_id)

    if args.cmd == "infer":
        text = " ".join(args.instruction)
        hyp = model.infer(
            text,
            suggest=not args.no_suggest,
            top_k=args.top_k,
            persist=not args.no_persist,
        )
        if args.json:
            print(json.dumps(hyp.to_dict(), indent=2, sort_keys=True))
        else:
            print(hyp.summary())
            print("--- clarified ---")
            print(hyp.clarified_instruction)
            if hyp.suggested_components:
                print("--- suggestions ---")
                for c in hyp.suggested_components:
                    print(f"  {c.score:.2f}  {c.tool_id}  ({c.reason})")
        return 0

    if args.cmd == "observe":
        turn = model.observe(" ".join(args.content), role=args.role)
        print(json.dumps(turn.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.cmd == "memory":
        print(json.dumps(model.load_memory().to_dict(), indent=2, sort_keys=True))
        return 0

    if args.cmd == "history":
        rows = [t.to_dict() for t in model.load_history()]
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.cmd == "stats":
        print(json.dumps(model.stats(), indent=2, sort_keys=True))
        return 0

    if args.cmd == "clear-history":
        if not args.yes:
            print("refusing to clear without --yes", file=sys.stderr)
            return 2
        path = history_path(model.workdir, model.user_id)
        if path.is_file():
            path.unlink()
        print(json.dumps({"ok": True, "cleared": str(path)}))
        return 0

    print(f"unknown cmd: {args.cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SCHEMA",
    "PAPER",
    "SOURCE_PATTERN",
    "DEFAULT_USER_ID",
    "MARKETPLACE_SURFACES",
    "SURFACE_AGENT",
    "SURFACE_SKILL",
    "SURFACE_COMMAND",
    "UserIntentError",
    "InteractionTurn",
    "UserMemory",
    "ComponentSuggestion",
    "IntentHypothesis",
    "UserIntentModel",
    "detect_ambiguity",
    "extract_goal_verbs",
    "extract_constraints",
    "extract_preferences",
    "extract_goal_phrase",
    "clarify_instruction",
    "compute_confidence",
    "infer_intent",
    "suggest_marketplace_components",
    "score_component",
    "maybe_infer_for_task",
    "memory_dir",
    "memory_path",
    "history_path",
    "sanitize_user_id",
    "main",
]
