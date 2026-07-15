"""Domain MCP eval smoke (P2.3/P2.4) — AssetOpsBench-shaped, offline-first.

Pattern (shape only, not vendored trees):
- IBM/AssetOpsBench — scenario → trajectory → scorer → pass-rate report;
  JSON scenario packs under ``scenarios/`` + static_json / judge scorers
- builderz-labs/mission-control — CLI/MCP/export parity
- arXiv 2511.15755 — deterministic audit of multi-agent tooling
- arXiv 2203.08975 — multi-agent communication surface health

Flow::

    scenarios (builtin and/or JSON packs)
      → run MCP call_tool (in-process, no network)
      → trajectory per scenario
      → code-based scorers (+ optional pluggable llm_judge)
      → nexus.mcp_eval/v1 report + optional export

Non-goals: no industrial IoT fixtures, no vendored AssetOpsBench trees,
no secrets in reports. LLM-as-judge is opt-in via injected callable only.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .persist import atomic_write_json, atomic_write_text

SCHEMA_VERSION = "nexus.mcp_eval/v1"
SCENARIO_PACK_SCHEMA = "nexus.scenario_pack/v1"
DEFAULT_OUT_DIR = ".nexus_state/mcp_eval"
DEFAULT_PACK_DIR = ".nexus_state/mcp_eval/packs"

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """Ground-truth MCP smoke case (AssetOpsBench Scenario shape, lite)."""

    id: str
    domain: str
    text: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    scoring_method: str = "tool_ok"
    expected: Any = None
    tags: list[str] = field(default_factory=list)
    privilege: str = "read"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Trajectory:
    """One tool invocation result (persisted-shape trajectory, lite)."""

    run_id: str
    scenario_id: str
    tool: str
    arguments: dict[str, Any]
    is_error: bool
    answer: str
    ms: float
    raw_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "is_error": self.is_error,
            "answer": self.answer,
            "ms": self.ms,
            "raw_keys": list(self.raw_keys),
        }


@dataclass
class ScorerResult:
    ok: bool
    score: float
    reason: str
    method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioResult:
    scenario_id: str
    domain: str
    text: str
    tool: str
    ok: bool
    score: float
    reason: str
    method: str
    is_error: bool
    answer_preview: str
    ms: float
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Built-in domain scenarios (offline / local-only)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# JSON scenario packs (P2.4 — AssetOpsBench scenarios/*.json shape)
# ---------------------------------------------------------------------------


class ScenarioPackError(ValueError):
    """Invalid scenario pack JSON or scenario object."""


def scenario_from_dict(raw: dict[str, Any], *, source: str = "") -> Scenario:
    """Parse one scenario object (NEXUS or AssetOpsBench-lite aliases).

    Accepted keys (NEXUS preferred, aliases in parens):
    - id (required)
    - domain (type / category → domain when missing)
    - text (question / characteristic_form for docs only)
    - tool (required for executable smoke; optional for doc-only packs)
    - arguments / args
    - scoring_method / scorer / scoring
    - expected / ground_truth / characteristic_form (for judge-style scorers)
    - tags / tag
    - privilege
    """
    if not isinstance(raw, dict):
        raise ScenarioPackError(f"scenario must be an object{source}")
    sid = raw.get("id")
    if sid is None or str(sid).strip() == "":
        raise ScenarioPackError(f"scenario missing id{source}")
    domain = (
        raw.get("domain")
        or raw.get("type")
        or raw.get("category")
        or "custom"
    )
    text = (
        raw.get("text")
        or raw.get("question")
        or raw.get("prompt")
        or raw.get("characteristic_form")
        or ""
    )
    tool = raw.get("tool") or raw.get("mcp_tool") or raw.get("name") or ""
    args = raw.get("arguments") or raw.get("args") or {}
    if not isinstance(args, dict):
        raise ScenarioPackError(f"scenario.arguments must be object for {sid!r}")
    method = (
        raw.get("scoring_method")
        or raw.get("scorer")
        or raw.get("scoring")
        or "tool_ok"
    )
    expected = raw.get("expected")
    if expected is None:
        expected = raw.get("ground_truth")
    if expected is None and raw.get("characteristic_form") is not None:
        # judge-style packs use characteristic_form as expected criteria
        expected = raw.get("characteristic_form")
    tags_raw = raw.get("tags") or raw.get("tag") or []
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(t) for t in tags_raw]
    else:
        tags = []
    if source and "pack" not in tags:
        tags = list(tags) + ["pack"]
    privilege = str(raw.get("privilege") or "read")
    return Scenario(
        id=str(sid),
        domain=str(domain),
        text=str(text),
        tool=str(tool),
        arguments=dict(args),
        scoring_method=str(method),
        expected=expected,
        tags=tags,
        privilege=privilege,
    )


def load_scenario_pack(path: Path | str) -> list[Scenario]:
    """Load scenarios from a JSON pack file.

    Accepts:
    - ``{"schema": "nexus.scenario_pack/v1", "scenarios": [...]}``
    - bare ``[...]`` array of scenario objects
    - single scenario object ``{...}``
    """
    p = Path(path)
    if not p.is_file():
        raise ScenarioPackError(f"scenario pack not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ScenarioPackError(f"invalid scenario pack JSON {path}: {e}") from e

    source = f" ({p.name})"
    items: list[Any]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if "scenarios" in data:
            items = data["scenarios"]
            if not isinstance(items, list):
                raise ScenarioPackError(
                    f"pack.scenarios must be a list{source}"
                )
        else:
            # single scenario object
            items = [data]
    else:
        raise ScenarioPackError(f"pack must be object or array{source}")

    out: list[Scenario] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ScenarioPackError(
                f"scenario[{i}] must be object{source}"
            )
        sc = scenario_from_dict(raw, source=f"{source}[{i}]")
        out.append(sc)
    return out


def load_scenario_packs(
    paths: Iterable[Path | str],
) -> list[Scenario]:
    """Load and concatenate multiple pack files (order preserved)."""
    out: list[Scenario] = []
    for path in paths:
        out.extend(load_scenario_pack(path))
    return out


def discover_packs(
    workdir: Path | str,
    *,
    pack_dir: str = DEFAULT_PACK_DIR,
) -> list[Path]:
    """List ``*.json`` packs under ``workdir/pack_dir`` (sorted)."""
    root = Path(workdir).resolve()
    rel = str(pack_dir or DEFAULT_PACK_DIR).lstrip("/\\")
    if ".." in Path(rel).parts:
        raise ScenarioPackError("pack_dir escapes project root")
    d = root / rel
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.json") if p.is_file())


def merge_scenarios(
    *groups: Iterable[Scenario],
    prefer_later: bool = True,
) -> list[Scenario]:
    """Merge scenario groups; later ids override earlier when *prefer_later*."""
    by_id: dict[str, Scenario] = {}
    order: list[str] = []
    for group in groups:
        for sc in group:
            sid = sc.id
            if sid not in by_id:
                order.append(sid)
                by_id[sid] = sc
            elif prefer_later:
                by_id[sid] = sc
    return [by_id[i] for i in order if i in by_id]


def resolve_scenarios(
    *,
    workdir: Optional[Path | str] = None,
    packs: Optional[Iterable[Path | str]] = None,
    include_builtin: bool = True,
    discover: bool = False,
    pack_dir: str = DEFAULT_PACK_DIR,
) -> list[Scenario]:
    """Builtin suite ± explicit packs ± optional auto-discover under pack_dir."""
    groups: list[list[Scenario]] = []
    if include_builtin:
        groups.append(builtin_scenarios())
    pack_paths: list[Path | str] = list(packs or [])
    if discover and workdir is not None:
        pack_paths.extend(discover_packs(workdir, pack_dir=pack_dir))
    if pack_paths:
        groups.append(load_scenario_packs(pack_paths))
    if not groups:
        return []
    return merge_scenarios(*groups, prefer_later=True)


def pack_to_dict(
    scenarios: Iterable[Scenario],
    *,
    name: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Serialize scenarios as a ``nexus.scenario_pack/v1`` document."""
    rows = [s.to_dict() for s in scenarios]
    return {
        "schema": SCENARIO_PACK_SCHEMA,
        "name": name,
        "description": description,
        "count": len(rows),
        "scenarios": rows,
    }


def write_scenario_pack(
    path: Path | str,
    scenarios: Iterable[Scenario],
    *,
    name: str = "",
    description: str = "",
) -> Path:
    """Atomically write a scenario pack JSON file."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        dest,
        pack_to_dict(scenarios, name=name, description=description),
    )
    return dest


def builtin_scenarios() -> list[Scenario]:
    """Default NEXUS domain MCP smoke suite.

    Prefer **read** tools so the suite is safe in CI without mutating state
    beyond workspace chat / temp project root.
    """
    return [
        Scenario(
            id="ws.list_root",
            domain="workspace",
            text="List files under project root",
            tool="list_project_files",
            arguments={"path": ".", "max_entries": 50},
            scoring_method="tool_ok",
            tags=["workspace", "read"],
        ),
        Scenario(
            id="ws.write_probe",
            domain="workspace",
            text="Write a jailed project file under .nexus_state",
            tool="write_to_project",
            arguments={
                "path": ".nexus_state/mcp_eval/_smoke_probe.txt",
                "content": "NEXUS_MCP_EVAL_OK\n",
            },
            scoring_method="contains",
            expected="wrote",
            privilege="write",
            tags=["workspace", "write"],
        ),
        Scenario(
            id="ws.path_jail",
            domain="workspace",
            text="Reject path escape outside project root",
            tool="read_project_file",
            arguments={"path": "../outside_escape.txt"},
            scoring_method="is_error",
            expected=True,
            tags=["workspace", "security"],
        ),
        Scenario(
            id="status.nexus",
            domain="status",
            text="Report NEXUS project root and server identity",
            tool="nexus_status",
            arguments={},
            scoring_method="contains_all",
            expected=["project_root=", "server=nexus-workspace"],
            tags=["status", "read"],
        ),
        Scenario(
            id="status.platforms",
            domain="status",
            text="List detected agent platforms",
            tool="list_platforms",
            arguments={},
            scoring_method="tool_ok",
            tags=["status", "read"],
        ),
        Scenario(
            id="status.vault",
            domain="vault",
            text="Vault presence report never leaks secret values",
            tool="vault_status",
            arguments={},
            scoring_method="json_keys",
            expected=["schema", "present", "n_present"],
            tags=["vault", "read", "security"],
        ),
        Scenario(
            id="catalog.list",
            domain="catalog",
            text="List MCP tools with privilege tags",
            tool="tool_catalog",
            arguments={"action": "list"},
            scoring_method="json_keys",
            expected=["schema", "count", "tools"],
            tags=["catalog", "read"],
        ),
        Scenario(
            id="catalog.validate",
            domain="catalog",
            text="Structural validate of live TOOLS[]",
            tool="tool_catalog",
            arguments={"action": "validate"},
            scoring_method="json_path_eq",
            expected={"ok": True},
            tags=["catalog", "smoke"],
        ),
        Scenario(
            id="grade.list",
            domain="grade",
            text="List offline graded candidates from IMPROVE_OURS",
            tool="list_graded_candidates",
            arguments={"min_score": 10.0, "limit": 5},
            scoring_method="tool_ok",
            tags=["grade", "read"],
        ),
        Scenario(
            id="skill.list",
            domain="skill",
            text="List skill packs under skillpacks/",
            tool="skillpacks",
            arguments={"action": "list"},
            scoring_method="tool_ok",
            tags=["skill", "read"],
        ),
        Scenario(
            id="ops.status",
            domain="ops",
            text="Ops control plane status summary",
            tool="ops_control",
            arguments={"action": "status"},
            scoring_method="tool_ok",
            tags=["ops", "read"],
        ),
        Scenario(
            id="context.pack",
            domain="context",
            text="Build a bounded multi-source context pack",
            tool="context_pack",
            arguments={
                "objective": "mcp eval smoke",
                "research": False,
                "repos": False,
            },
            scoring_method="tool_ok",
            tags=["context", "read"],
        ),
        Scenario(
            id="gap.list",
            domain="gap",
            text="List principled-stop gap board",
            tool="gap_board",
            arguments={"action": "list"},
            scoring_method="tool_ok",
            tags=["gap", "read"],
        ),
    ]


# ---------------------------------------------------------------------------
# Scorers (code-based only — no LLM)
# ---------------------------------------------------------------------------

Scorer = Callable[[Scenario, Trajectory], ScorerResult]


def _parse_json_answer(answer: str) -> Optional[Any]:
    text = (answer or "").strip()
    if not text:
        return None
    # MCP results are often pure JSON; tolerate leading chatter
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # find first {…} or […]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    chunk = text[start : i + 1]
                    try:
                        return json.loads(chunk)
                    except json.JSONDecodeError:
                        break
    return None


def score_tool_ok(scenario: Scenario, traj: Trajectory) -> ScorerResult:
    ok = not traj.is_error
    return ScorerResult(
        ok=ok,
        score=1.0 if ok else 0.0,
        reason="tool_ok" if ok else "tool_error",
        method="tool_ok",
    )


def score_is_error(scenario: Scenario, traj: Trajectory) -> ScorerResult:
    want = True if scenario.expected is None else bool(scenario.expected)
    ok = traj.is_error is want
    return ScorerResult(
        ok=ok,
        score=1.0 if ok else 0.0,
        reason="is_error_match" if ok else f"is_error={traj.is_error} want={want}",
        method="is_error",
    )


def score_contains(scenario: Scenario, traj: Trajectory) -> ScorerResult:
    if traj.is_error:
        return ScorerResult(
            ok=False, score=0.0, reason="tool_error", method="contains"
        )
    needle = str(scenario.expected or "")
    ok = needle in (traj.answer or "")
    return ScorerResult(
        ok=ok,
        score=1.0 if ok else 0.0,
        reason="contains" if ok else f"missing:{needle[:60]}",
        method="contains",
    )


def score_contains_all(scenario: Scenario, traj: Trajectory) -> ScorerResult:
    if traj.is_error:
        return ScorerResult(
            ok=False, score=0.0, reason="tool_error", method="contains_all"
        )
    needles: list[str]
    if isinstance(scenario.expected, (list, tuple)):
        needles = [str(x) for x in scenario.expected]
    else:
        needles = [str(scenario.expected or "")]
    missing = [n for n in needles if n and n not in (traj.answer or "")]
    ok = not missing
    return ScorerResult(
        ok=ok,
        score=1.0 if ok else 0.0,
        reason="contains_all" if ok else f"missing:{missing[:3]}",
        method="contains_all",
    )


def score_json_keys(scenario: Scenario, traj: Trajectory) -> ScorerResult:
    if traj.is_error:
        return ScorerResult(
            ok=False, score=0.0, reason="tool_error", method="json_keys"
        )
    data = _parse_json_answer(traj.answer)
    if not isinstance(data, dict):
        return ScorerResult(
            ok=False, score=0.0, reason="not_json_object", method="json_keys"
        )
    keys: list[str]
    if isinstance(scenario.expected, (list, tuple)):
        keys = [str(k) for k in scenario.expected]
    elif isinstance(scenario.expected, str):
        keys = [scenario.expected]
    else:
        keys = []
    missing = [k for k in keys if k not in data]
    ok = not missing
    return ScorerResult(
        ok=ok,
        score=1.0 if ok else 0.0,
        reason="json_keys" if ok else f"missing_keys:{missing}",
        method="json_keys",
    )


def score_json_path_eq(scenario: Scenario, traj: Trajectory) -> ScorerResult:
    """Require JSON answer to contain expected key→value pairs (shallow)."""
    if traj.is_error:
        return ScorerResult(
            ok=False, score=0.0, reason="tool_error", method="json_path_eq"
        )
    data = _parse_json_answer(traj.answer)
    if not isinstance(data, dict):
        return ScorerResult(
            ok=False, score=0.0, reason="not_json_object", method="json_path_eq"
        )
    expect = scenario.expected if isinstance(scenario.expected, dict) else {}
    mismatches: list[str] = []
    for k, v in expect.items():
        if k not in data:
            mismatches.append(f"missing:{k}")
        elif data[k] != v:
            mismatches.append(f"{k}:{data[k]!r}!={v!r}")
    ok = not mismatches
    return ScorerResult(
        ok=ok,
        score=1.0 if ok else 0.0,
        reason="json_path_eq" if ok else f"mismatch:{mismatches[:4]}",
        method="json_path_eq",
    )


def score_no_secret_leak(scenario: Scenario, traj: Trajectory) -> ScorerResult:
    """Fail if answer looks like it embeds raw API keys / tokens."""
    if traj.is_error:
        return ScorerResult(
            ok=False, score=0.0, reason="tool_error", method="no_secret_leak"
        )
    text = traj.answer or ""
    patterns = [
        r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}",
        r"sk-[A-Za-z0-9]{20,}",
        r"ghp_[A-Za-z0-9]{20,}",
    ]
    for pat in patterns:
        if re.search(pat, text):
            return ScorerResult(
                ok=False,
                score=0.0,
                reason=f"possible_secret_pattern:{pat[:40]}",
                method="no_secret_leak",
            )
    return ScorerResult(
        ok=True, score=1.0, reason="no_secret_leak", method="no_secret_leak"
    )


def _criteria_tokens(expected: Any) -> list[str]:
    """Tokenize expected / characteristic_form into keyword criteria."""
    if expected is None:
        return []
    if isinstance(expected, (list, tuple)):
        return [str(x).strip() for x in expected if str(x).strip()]
    text = str(expected)
    # Prefer quoted phrases and multi-word CAPS/identifiers; else words ≥4 chars
    quoted = re.findall(r"['\"]([^'\"]{3,})['\"]", text)
    if quoted:
        return [q.strip() for q in quoted if q.strip()]
    # split on commas / semicolons for AssetOpsBench characteristic_form lists
    parts = re.split(r"[,;]", text)
    tokens: list[str] = []
    for part in parts:
        words = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{3,}", part)
        tokens.extend(words)
    # de-dupe preserving order, drop stopwords
    stop = {
        "that",
        "this",
        "with",
        "from",
        "should",
        "include",
        "expected",
        "response",
        "provide",
        "return",
        "using",
        "have",
        "been",
        "will",
        "into",
        "their",
        "them",
        "such",
        "also",
        "when",
        "where",
        "which",
        "must",
        "note",
        "list",
        "full",
    }
    out: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        key = t.lower()
        if key in stop or key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out[:24]


def score_heuristic_judge(scenario: Scenario, traj: Trajectory) -> ScorerResult:
    """Offline AssetOpsBench-style judge: keyword coverage of expected criteria.

    Not an LLM. Used as the default implementation of ``llm_judge`` when no
    external judge callable is injected — deterministic and CI-safe.
    """
    if traj.is_error:
        return ScorerResult(
            ok=False, score=0.0, reason="tool_error", method="heuristic_judge"
        )
    criteria = _criteria_tokens(scenario.expected)
    if not criteria:
        # no criteria → pass if tool succeeded (lenient)
        return ScorerResult(
            ok=True, score=1.0, reason="no_criteria", method="heuristic_judge"
        )
    answer_l = (traj.answer or "").lower()
    hits = [c for c in criteria if c.lower() in answer_l]
    ratio = len(hits) / max(len(criteria), 1)
    # pass if ≥50% criteria covered (or at least 2 hits when many criteria)
    ok = ratio >= 0.5 or (len(hits) >= 2 and ratio >= 0.33)
    return ScorerResult(
        ok=ok,
        score=round(ratio, 4),
        reason=(
            f"heuristic_judge hits={len(hits)}/{len(criteria)}"
            if ok
            else f"heuristic_judge_miss hits={len(hits)}/{len(criteria)}"
        ),
        method="heuristic_judge",
    )


# Optional external LLM judge: Callable[[Scenario, Trajectory], ScorerResult]
_LLM_JUDGE_FN: Optional[Callable[[Scenario, Trajectory], ScorerResult]] = None


def set_llm_judge(
    fn: Optional[Callable[[Scenario, Trajectory], ScorerResult]],
) -> None:
    """Register or clear a process-wide LLM-as-judge scorer (opt-in)."""
    global _LLM_JUDGE_FN
    _LLM_JUDGE_FN = fn


def score_llm_judge(scenario: Scenario, traj: Trajectory) -> ScorerResult:
    """Opt-in LLM-as-judge: uses injected callable, else heuristic_judge.

    Fail-closed only when scenario.expected explicitly sets
    ``{"require_llm": true}`` and no judge is registered.
    """
    require_llm = False
    if isinstance(scenario.expected, dict):
        require_llm = bool(scenario.expected.get("require_llm"))
    if _LLM_JUDGE_FN is not None:
        try:
            result = _LLM_JUDGE_FN(scenario, traj)
            if isinstance(result, ScorerResult):
                return result
            if isinstance(result, dict):
                return ScorerResult(
                    ok=bool(result.get("ok")),
                    score=float(result.get("score") or 0.0),
                    reason=str(result.get("reason") or "llm_judge"),
                    method="llm_judge",
                )
        except Exception as e:
            return ScorerResult(
                ok=False,
                score=0.0,
                reason=f"llm_judge_error:{type(e).__name__}",
                method="llm_judge",
            )
    if require_llm:
        return ScorerResult(
            ok=False,
            score=0.0,
            reason="llm_judge_not_configured",
            method="llm_judge",
        )
    # Offline default: heuristic keyword coverage (AssetOpsBench static spirit)
    base = score_heuristic_judge(scenario, traj)
    return ScorerResult(
        ok=base.ok,
        score=base.score,
        reason=f"llm_judge_fallback:{base.reason}",
        method="llm_judge",
    )


SCORERS: dict[str, Scorer] = {
    "tool_ok": score_tool_ok,
    "is_error": score_is_error,
    "contains": score_contains,
    "contains_all": score_contains_all,
    "json_keys": score_json_keys,
    "json_path_eq": score_json_path_eq,
    "no_secret_leak": score_no_secret_leak,
    "heuristic_judge": score_heuristic_judge,
    "llm_judge": score_llm_judge,
    # AssetOpsBench alias
    "static_json": score_json_path_eq,
}


def get_scorer(name: str) -> Scorer:
    key = (name or "tool_ok").strip().lower()
    if key not in SCORERS:
        raise KeyError(f"unknown scorer {name!r}; registered: {sorted(SCORERS)}")
    return SCORERS[key]


# ---------------------------------------------------------------------------
# Runner / evaluator
# ---------------------------------------------------------------------------


def _extract_answer(result: dict[str, Any]) -> tuple[bool, str]:
    is_error = bool(result.get("isError"))
    content = result.get("content") or []
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
    elif isinstance(content, str):
        parts.append(content)
    return is_error, "\n".join(parts)


def run_scenario(
    scenario: Scenario,
    *,
    call_tool: Optional[Callable[[str, dict[str, Any]], dict[str, Any]]] = None,
    run_id: str = "",
) -> tuple[Trajectory, ScenarioResult]:
    """Invoke one scenario tool and score the trajectory."""
    from . import mcp_server

    fn = call_tool or mcp_server.call_tool
    t0 = time.perf_counter()
    try:
        raw = fn(scenario.tool, dict(scenario.arguments or {}))
        if not isinstance(raw, dict):
            raw = {
                "content": [{"type": "text", "text": str(raw)}],
                "isError": True,
            }
    except Exception as e:  # pragma: no cover — call_tool usually catches
        raw = {
            "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
            "isError": True,
        }
    ms = (time.perf_counter() - t0) * 1000.0
    is_error, answer = _extract_answer(raw)
    traj = Trajectory(
        run_id=run_id or f"run-{scenario.id}",
        scenario_id=scenario.id,
        tool=scenario.tool,
        arguments=dict(scenario.arguments or {}),
        is_error=is_error,
        answer=answer,
        ms=round(ms, 3),
        raw_keys=sorted(str(k) for k in raw.keys()),
    )
    try:
        scorer = get_scorer(scenario.scoring_method)
        scored = scorer(scenario, traj)
    except KeyError as e:
        scored = ScorerResult(
            ok=False, score=0.0, reason=str(e), method=scenario.scoring_method
        )
    # Security overlay for vault domain
    if scenario.domain == "vault" and scored.ok:
        leak = score_no_secret_leak(scenario, traj)
        if not leak.ok:
            scored = leak
    preview = (traj.answer or "").replace("\n", " ")[:160]
    result = ScenarioResult(
        scenario_id=scenario.id,
        domain=scenario.domain,
        text=scenario.text,
        tool=scenario.tool,
        ok=scored.ok,
        score=float(scored.score),
        reason=scored.reason,
        method=scored.method,
        is_error=traj.is_error,
        answer_preview=preview,
        ms=traj.ms,
        tags=list(scenario.tags),
    )
    return traj, result


def filter_scenarios(
    scenarios: Iterable[Scenario],
    *,
    domains: Optional[Iterable[str]] = None,
    ids: Optional[Iterable[str]] = None,
    tags: Optional[Iterable[str]] = None,
    max_privilege: Optional[str] = None,
) -> list[Scenario]:
    from .tool_catalog import PRIVILEGE_RANK

    out = list(scenarios)
    if domains:
        want = {d.strip().lower() for d in domains if d}
        out = [s for s in out if s.domain.lower() in want]
    if ids:
        want_ids = {i.strip() for i in ids if i}
        out = [s for s in out if s.id in want_ids]
    if tags:
        want_tags = {t.strip().lower() for t in tags if t}
        out = [
            s
            for s in out
            if want_tags.intersection({t.lower() for t in s.tags})
        ]
    if max_privilege:
        cap = PRIVILEGE_RANK.get(str(max_privilege).lower())
        if cap is not None:
            out = [
                s
                for s in out
                if PRIVILEGE_RANK.get(s.privilege, 2) <= cap
            ]
    return out


def evaluate(
    scenarios: Optional[list[Scenario]] = None,
    *,
    call_tool: Optional[Callable[[str, dict[str, Any]], dict[str, Any]]] = None,
    run_id: Optional[str] = None,
    domains: Optional[Iterable[str]] = None,
    ids: Optional[Iterable[str]] = None,
    tags: Optional[Iterable[str]] = None,
    max_privilege: Optional[str] = None,
    workdir: Optional[Path | str] = None,
    packs: Optional[Iterable[Path | str]] = None,
    include_builtin: bool = True,
    discover_packs_flag: bool = False,
    pack_dir: str = DEFAULT_PACK_DIR,
) -> dict[str, Any]:
    """Run scenarios → trajectories → scorers → aggregate report.

    When *scenarios* is None, resolves builtin ± *packs* ± discovered packs.
    """
    if scenarios is None:
        base = resolve_scenarios(
            workdir=workdir,
            packs=packs,
            include_builtin=include_builtin,
            discover=discover_packs_flag,
            pack_dir=pack_dir,
        )
    else:
        base = list(scenarios)
        if packs:
            base = merge_scenarios(base, load_scenario_packs(packs))
    suite = filter_scenarios(
        base,
        domains=domains,
        ids=ids,
        tags=tags,
        max_privilege=max_privilege,
    )
    rid = run_id or f"mcp-eval-{int(time.time())}"
    trajectories: list[dict[str, Any]] = []
    results: list[ScenarioResult] = []
    t0 = time.perf_counter()
    for sc in suite:
        if not sc.tool:
            # doc-only pack row (no tool) → soft-fail unless is_error expected
            traj = Trajectory(
                run_id=rid,
                scenario_id=sc.id,
                tool="",
                arguments={},
                is_error=True,
                answer="missing tool field",
                ms=0.0,
            )
            scored = ScorerResult(
                ok=False,
                score=0.0,
                reason="missing_tool",
                method=sc.scoring_method,
            )
            res = ScenarioResult(
                scenario_id=sc.id,
                domain=sc.domain,
                text=sc.text,
                tool=sc.tool,
                ok=scored.ok,
                score=scored.score,
                reason=scored.reason,
                method=scored.method,
                is_error=True,
                answer_preview="missing tool field",
                ms=0.0,
                tags=list(sc.tags),
            )
            trajectories.append(traj.to_dict())
            results.append(res)
            continue
        traj, res = run_scenario(sc, call_tool=call_tool, run_id=rid)
        trajectories.append(traj.to_dict())
        results.append(res)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    n = len(results)
    passed = sum(1 for r in results if r.ok)
    failed = n - passed
    pass_rate = (passed / n) if n else 0.0

    by_domain: dict[str, dict[str, Any]] = {}
    for r in results:
        bucket = by_domain.setdefault(
            r.domain, {"total": 0, "passed": 0, "failed": 0}
        )
        bucket["total"] += 1
        if r.ok:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
    for bucket in by_domain.values():
        tot = bucket["total"] or 1
        bucket["pass_rate"] = round(bucket["passed"] / tot, 4)

    failures = [
        {
            "scenario_id": r.scenario_id,
            "domain": r.domain,
            "tool": r.tool,
            "reason": r.reason,
            "preview": r.answer_preview,
        }
        for r in results
        if not r.ok
    ]

    pack_names = [str(p) for p in (packs or [])]
    return {
        "schema": SCHEMA_VERSION,
        "run_id": rid,
        "ok": failed == 0 and n > 0,
        "total": n,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(pass_rate, 4),
        "elapsed_ms": round(elapsed_ms, 3),
        "by_domain": by_domain,
        "scorers": sorted(SCORERS.keys()),
        "packs": pack_names,
        "include_builtin": include_builtin if scenarios is None else None,
        "results": [r.to_dict() for r in results],
        "trajectories": trajectories,
        "failures": failures,
        "ts": time.time(),
    }


def export_report(
    workdir: Path | str,
    report: dict[str, Any],
    *,
    out_dir: str = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    """Write report.json + summary.md + trajectories.jsonl under out_dir."""
    root = Path(workdir).resolve()
    rel = str(out_dir or DEFAULT_OUT_DIR).lstrip("/\\")
    if ".." in Path(rel).parts:
        raise ValueError("out_dir escapes project root")
    dest = root / rel
    dest.mkdir(parents=True, exist_ok=True)

    report_path = dest / "report.json"
    # keep export lean: drop full trajectories from report.json (in jsonl)
    slim = {k: v for k, v in report.items() if k != "trajectories"}
    atomic_write_json(report_path, slim)

    traj_path = dest / "trajectories.jsonl"
    lines = [
        json.dumps(t, default=str)
        for t in (report.get("trajectories") or [])
    ]
    atomic_write_text(traj_path, "\n".join(lines) + ("\n" if lines else ""))

    summary_path = dest / "summary.md"
    atomic_write_text(summary_path, format_report(report, markdown=True))

    return {
        "ok": bool(report.get("ok")),
        "out_dir": str(dest),
        "report": str(report_path),
        "trajectories": str(traj_path),
        "summary": str(summary_path),
        "pass_rate": report.get("pass_rate"),
        "passed": report.get("passed"),
        "failed": report.get("failed"),
        "total": report.get("total"),
    }


def format_report(report: dict[str, Any], *, markdown: bool = False) -> str:
    """Human-readable pass-rate summary."""
    lines: list[str] = []
    title = "NEXUS domain MCP eval smoke"
    if markdown:
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"- schema: `{report.get('schema')}`")
        lines.append(f"- run_id: `{report.get('run_id')}`")
    else:
        lines.append(f"=== {title} ===")
        lines.append(f"schema:  {report.get('schema')}")
        lines.append(f"run_id:  {report.get('run_id')}")

    total = int(report.get("total") or 0)
    passed = int(report.get("passed") or 0)
    failed = int(report.get("failed") or 0)
    rate = float(report.get("pass_rate") or 0.0) * 100.0
    status = "PASS" if report.get("ok") else "FAIL"
    lines.append(
        f"result:  {status}  {passed}/{total}  pass_rate={rate:.1f}%  "
        f"failed={failed}  elapsed_ms={report.get('elapsed_ms')}"
    )

    by_domain = report.get("by_domain") or {}
    if by_domain:
        lines.append("")
        lines.append("by domain:" if not markdown else "## By domain")
        for dom in sorted(by_domain):
            b = by_domain[dom]
            pr = float(b.get("pass_rate") or 0.0) * 100.0
            lines.append(
                f"  {dom:12} {b.get('passed')}/{b.get('total')}  ({pr:.0f}%)"
            )

    results = report.get("results") or []
    if results:
        lines.append("")
        lines.append("scenarios:" if not markdown else "## Scenarios")
        for r in results:
            mark = "ok" if r.get("ok") else "FAIL"
            lines.append(
                f"  [{mark:4}] {r.get('scenario_id'):28} "
                f"tool={r.get('tool')}  {r.get('reason')}  "
                f"({r.get('ms')}ms)"
            )

    failures = report.get("failures") or []
    if failures:
        lines.append("")
        lines.append("failures:" if not markdown else "## Failures")
        for f in failures:
            lines.append(
                f"  - {f.get('scenario_id')}: {f.get('reason')} "
                f"({f.get('preview', '')[:80]})"
            )

    return "\n".join(lines) + "\n"


def list_scenarios(
    scenarios: Optional[list[Scenario]] = None,
    *,
    workdir: Optional[Path | str] = None,
    packs: Optional[Iterable[Path | str]] = None,
    include_builtin: bool = True,
    discover_packs_flag: bool = False,
    pack_dir: str = DEFAULT_PACK_DIR,
    **filters: Any,
) -> list[dict[str, Any]]:
    if scenarios is None:
        scenarios = resolve_scenarios(
            workdir=workdir,
            packs=packs,
            include_builtin=include_builtin,
            discover=discover_packs_flag,
            pack_dir=pack_dir,
        )
    suite = filter_scenarios(
        scenarios,
        **{k: v for k, v in filters.items() if v is not None},
    )
    return [s.to_dict() for s in suite]


def run_and_export(
    workdir: Path | str,
    *,
    domains: Optional[Iterable[str]] = None,
    ids: Optional[Iterable[str]] = None,
    tags: Optional[Iterable[str]] = None,
    max_privilege: Optional[str] = None,
    out_dir: str = DEFAULT_OUT_DIR,
    export: bool = True,
    call_tool: Optional[Callable[[str, dict[str, Any]], dict[str, Any]]] = None,
    packs: Optional[Iterable[Path | str]] = None,
    include_builtin: bool = True,
    discover_packs_flag: bool = False,
    pack_dir: str = DEFAULT_PACK_DIR,
    scenarios: Optional[list[Scenario]] = None,
) -> dict[str, Any]:
    """Convenience: evaluate + optional export under workdir."""
    report = evaluate(
        scenarios,
        call_tool=call_tool,
        domains=domains,
        ids=ids,
        tags=tags,
        max_privilege=max_privilege,
        workdir=workdir,
        packs=packs,
        include_builtin=include_builtin,
        discover_packs_flag=discover_packs_flag,
        pack_dir=pack_dir,
    )
    if export:
        meta = export_report(workdir, report, out_dir=out_dir)
        report["export"] = meta
    return report
