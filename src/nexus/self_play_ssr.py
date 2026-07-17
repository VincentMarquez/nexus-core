"""Self-play inject→repair loop for software agents (arXiv 2512.18552).

Paper: *Toward Training Superintelligent Software Agents through Self-Play SWE-RL*
  https://arxiv.org/abs/2512.18552v3

  Self-play SWE-RL (SSR) trains agents by iteratively **injecting** and
  **repairing** bugs of increasing complexity in real codebases. Bugs are
  specified by tests (fail-to-pass), not natural-language issues.

GitHub pattern (shape only — not a vendored tree):
  wshobson/agents — single-source Markdown marketplace of named plugins
  (agents/skills/commands) with discover + validate surfaces. Here we keep a
  **self-play plugin marketplace**: named inject / repair plugins that can be
  listed, validated, and selectively enabled — same discover/validate shape
  as ``marketplace.py`` / ``patch_diff.CHECK_CATALOG``.

Novel hybrid (portfolio cross_pattern
``novel:arxiv:2512.18552v3+wshobson/agents``):

  marketplace inject/repair catalogs (named plugins)
                │
                ▼
         ┌──────────────────┐   complexity ramp
         │  Self-play SSR   │ ──► inject → verify-fail → repair → verify-pass
         │  (grok_worker)   │     offline-first; optional agentic prompt
         └──────────────────┘
                │
                └── SelfPlayReport (rounds, rewards, episodes)

Offline-first: pure text mutators + controlled ``exec`` of fixture sources.
No network, no full RL trainer, no vendored upstream trees.
Schema: ``nexus.self_play_ssr/v1``
"""

from __future__ import annotations

import hashlib
import random
import re
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

SCHEMA = "nexus.self_play_ssr/v1"
PAPER = "arxiv:2512.18552v3"
PAPER_TITLE = (
    "Toward Training Superintelligent Software Agents through Self-Play SWE-RL"
)
SOURCE_PATTERN = "wshobson/agents"
IDEA_ID = "novel:arxiv:2512.18552v3+wshobson/agents"

VALID_SURFACES: tuple[str, ...] = (
    "inject",
    "repair",
    "verify",
    "agent",
    "skill",
    "system",
)

# Complexity bands (SSR: bugs of increasing complexity across rounds).
COMPLEXITY_EASY = 1
COMPLEXITY_MEDIUM = 2
COMPLEXITY_HARD = 3

DEFAULT_MAX_ROUNDS = 3
DEFAULT_SEED = 42
DEFAULT_VERIFY_TIMEOUT_S = 1.0

# Fixture entry used by built-in sample programs.
_ENTRY = "result"

# Sentinel: expected not provided (distinct from legitimate expected=None).
_MISSING: Any = object()

# Minimal builtins for controlled fixture exec (no import/open/eval/exec).
_SAFE_BUILTINS: dict[str, Any] = {
    "True": True,
    "False": False,
    "None": None,
    "abs": abs,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "Exception": Exception,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "NameError": NameError,
    "range": range,
    "set": set,
    "str": str,
    "sum": sum,
    "SystemExit": SystemExit,
    "tuple": tuple,
    "TypeError": TypeError,
    "ValueError": ValueError,
    "zip": zip,
}


class SelfPlayError(ValueError):
    """Invalid self-play configuration or episode."""


# ── Marketplace-style plugin catalog (wshobson pattern) ─────────────────────


@dataclass(frozen=True)
class PlayPlugin:
    """One named inject or repair plugin in the self-play marketplace.

    Mirrors wshobson plugin discovery: id + surface + privilege + notes.
    """

    plugin_id: str
    display_name: str
    surface: str  # inject | repair | verify | …
    privilege: str = "write"  # read | write | ops
    complexity: int = COMPLEXITY_EASY
    description: str = ""
    enabled_by_default: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "display_name": self.display_name,
            "surface": self.surface,
            "privilege": self.privilege,
            "complexity": self.complexity,
            "description": self.description,
            "enabled_by_default": self.enabled_by_default,
        }


# Single source of truth for inject plugins.
INJECT_CATALOG: dict[str, PlayPlugin] = {
    "flip_bool_return": PlayPlugin(
        plugin_id="flip_bool_return",
        display_name="Flip boolean return",
        surface="inject",
        complexity=COMPLEXITY_EASY,
        description="Flip `return True` ↔ `return False` (easy SSR mutation).",
    ),
    "off_by_one": PlayPlugin(
        plugin_id="off_by_one",
        display_name="Off-by-one constant",
        surface="inject",
        complexity=COMPLEXITY_EASY,
        description="Bump a small integer literal by +1 (classic off-by-one).",
    ),
    "break_equality": PlayPlugin(
        plugin_id="break_equality",
        display_name="Break equality",
        surface="inject",
        complexity=COMPLEXITY_MEDIUM,
        description="Change `==` to `!=` (or reverse) in a comparison.",
    ),
    "drop_guard": PlayPlugin(
        plugin_id="drop_guard",
        display_name="Drop guard condition",
        surface="inject",
        complexity=COMPLEXITY_MEDIUM,
        description=(
            "Force a boolean guard to `False` (fixture-oriented: `ok = True` / "
            "`if flag:` / first `if <name>:`)."
        ),
    ),
    "typo_name": PlayPlugin(
        plugin_id="typo_name",
        display_name="Typo identifier",
        surface="inject",
        complexity=COMPLEXITY_HARD,
        description="Introduce a NameError via a single-char typo on an identifier.",
    ),
}

# Single source of truth for repair plugins.
REPAIR_CATALOG: dict[str, PlayPlugin] = {
    "oracle_inverse": PlayPlugin(
        plugin_id="oracle_inverse",
        display_name="Oracle inverse",
        surface="repair",
        privilege="write",
        complexity=COMPLEXITY_EASY,
        description=(
            "Apply the known inverse of the inject plugin (self-play training signal)."
        ),
    ),
    "restore_baseline": PlayPlugin(
        plugin_id="restore_baseline",
        display_name="Restore baseline",
        surface="repair",
        privilege="write",
        complexity=COMPLEXITY_EASY,
        description="Restore original pre-inject source (trivial repair baseline).",
    ),
    "heuristic_scan": PlayPlugin(
        plugin_id="heuristic_scan",
        display_name="Heuristic scan",
        surface="repair",
        privilege="write",
        complexity=COMPLEXITY_MEDIUM,
        description=(
            "Try common inverse mutations without using the inject id "
            "(partial agent-shaped repair)."
        ),
    ),
    "noop": PlayPlugin(
        plugin_id="noop",
        display_name="No-op repair",
        surface="repair",
        privilege="read",
        complexity=COMPLEXITY_EASY,
        description="Leave source unchanged (always fails unless already correct).",
        enabled_by_default=False,
    ),
}

# Combined marketplace for list / validate / self-check.
PLUGIN_CATALOG: dict[str, PlayPlugin] = {**INJECT_CATALOG, **REPAIR_CATALOG}


def list_plugins(
    *,
    surface: Optional[str] = None,
    enabled_only: bool = False,
    max_complexity: Optional[int] = None,
) -> list[dict[str, Any]]:
    """List marketplace self-play plugins (discover surface)."""
    out: list[dict[str, Any]] = []
    for plugin in PLUGIN_CATALOG.values():
        if surface and plugin.surface != surface:
            continue
        if enabled_only and not plugin.enabled_by_default:
            continue
        if max_complexity is not None and plugin.complexity > max_complexity:
            continue
        out.append(plugin.to_dict())
    return sorted(out, key=lambda r: (r["surface"], r["complexity"], r["plugin_id"]))


def validate_plugin_ids(plugin_ids: Sequence[str]) -> list[str]:
    """Return unknown plugin ids (empty list ⇒ valid catalog selection)."""
    unknown: list[str] = []
    for pid in plugin_ids:
        key = str(pid or "").strip()
        if key and key not in PLUGIN_CATALOG:
            unknown.append(key)
    return unknown


def catalog_self_check() -> dict[str, Any]:
    """Structural gate over the self-play marketplace (wshobson validate shape)."""
    issues: list[str] = []
    if not INJECT_CATALOG:
        issues.append("empty_inject_catalog")
    if not REPAIR_CATALOG:
        issues.append("empty_repair_catalog")
    # Cross-catalog id collisions are masked by PLUGIN_CATALOG merge — check explicitly.
    for pid in sorted(set(INJECT_CATALOG) & set(REPAIR_CATALOG)):
        issues.append(f"duplicate:{pid}")
    seen: set[str] = set()
    for pid, plugin in PLUGIN_CATALOG.items():
        if pid != plugin.plugin_id:
            issues.append(f"id_mismatch:{pid}")
        if plugin.plugin_id in seen:
            issues.append(f"duplicate:{plugin.plugin_id}")
        seen.add(plugin.plugin_id)
        if plugin.surface not in VALID_SURFACES:
            issues.append(f"bad_surface:{plugin.plugin_id}:{plugin.surface}")
        if plugin.complexity < 1:
            issues.append(f"bad_complexity:{plugin.plugin_id}")
        if not plugin.display_name.strip():
            issues.append(f"empty_name:{plugin.plugin_id}")
    inject_n = sum(1 for p in PLUGIN_CATALOG.values() if p.surface == "inject")
    repair_n = sum(1 for p in PLUGIN_CATALOG.values() if p.surface == "repair")
    return {
        "schema": SCHEMA,
        "ok": not issues,
        "issues": issues,
        "plugin_count": len(PLUGIN_CATALOG),
        "inject_count": inject_n,
        "repair_count": repair_n,
        "surfaces": sorted({p.surface for p in PLUGIN_CATALOG.values()}),
    }


# ── Fixture programs + verification ────────────────────────────────────────


# Small pure programs used offline. Each defines `result` after exec.
SAMPLE_PROGRAMS: dict[str, str] = {
    "bool_gate": (
        "def check(flag):\n"
        "    if flag:\n"
        "        return True\n"
        "    return False\n"
        "\n"
        "result = check(True)\n"
    ),
    "counter": (
        "def count_up(n):\n"
        "    total = 0\n"
        "    for i in range(n):\n"
        "        total = total + 1\n"
        "    return total\n"
        "\n"
        "result = count_up(3)\n"
    ),
    "equality": (
        "def same(a, b):\n"
        "    if a == b:\n"
        "        return 1\n"
        "    return 0\n"
        "\n"
        "result = same(2, 2)\n"
    ),
    "guarded": (
        "def guarded(x):\n"
        "    ok = True\n"
        "    if ok:\n"
        "        return x + 1\n"
        "    return x\n"
        "\n"
        "result = guarded(10)\n"
    ),
    "named": (
        "value = 7\n"
        "result = value * 2\n"
    ),
}

# Expected `result` for each healthy sample program.
SAMPLE_EXPECTED: dict[str, Any] = {
    "bool_gate": True,
    "counter": 3,
    "equality": 1,
    "guarded": 11,
    "named": 14,
}

# Prefer inject plugins per sample (best structural match).
_SAMPLE_INJECT_PREF: dict[str, tuple[str, ...]] = {
    "bool_gate": ("flip_bool_return", "break_equality", "drop_guard"),
    "counter": ("off_by_one", "break_equality"),
    "equality": ("break_equality", "off_by_one"),
    "guarded": ("drop_guard", "off_by_one", "break_equality"),
    "named": ("typo_name", "off_by_one"),
}


def _exec_source_value(source: str, entry: str) -> Any:
    """Compile+exec source under restricted builtins; return ``entry`` value.

    Raises on compile/exec failure (caller maps to verify report).
    """
    ns: dict[str, Any] = {"__builtins__": dict(_SAFE_BUILTINS)}
    compiled = compile(source, "<self_play_ssr>", "exec")
    exec(compiled, ns, ns)  # noqa: S102 — restricted fixture verifier
    return ns.get(entry)


def verify_source(
    source: str,
    *,
    expected: Any,
    entry: str = _ENTRY,
    timeout_s: float = DEFAULT_VERIFY_TIMEOUT_S,
) -> dict[str, Any]:
    """Execute controlled source and compare ``entry`` to expected.

    Uses restricted builtins (no import/open/eval) and a wall-clock timeout so
    public ``sources=`` callers cannot hang or RCE the worker process as easily.
    Full OS sandbox (subprocess/container) remains a follow-up.

    Returns a small report: ok / value / error. Never raises for user code
    failures (NameError, SyntaxError, SystemExit, timeout, …) — those are
    repair signals.
    """
    timeout = max(0.05, float(timeout_s))

    def _run() -> Any:
        return _exec_source_value(source, entry)

    try:
        value = _run_with_timeout(_run, timeout)
    except TimeoutError as exc:
        return {
            "ok": False,
            "value": None,
            "error": str(exc) or f"timeout after {timeout}s",
            "expected": expected,
        }
    except BaseException as exc:  # noqa: BLE001 — capture as fail-to-pass signal
        # Includes SystemExit from hostile fixtures.
        return {
            "ok": False,
            "value": None,
            "error": f"{type(exc).__name__}: {exc}",
            "expected": expected,
        }
    ok = value == expected
    return {
        "ok": ok,
        "value": value,
        "error": None if ok else f"value_mismatch: got={value!r} expected={expected!r}",
        "expected": expected,
    }


def _run_with_timeout(fn, timeout: float) -> Any:
    """Run ``fn`` with a wall-clock cap.

    Prefers ``signal.setitimer`` on the main thread (Unix); falls back to a
    non-blocking ThreadPoolExecutor shutdown so infinite loops do not hang the
    worker on pool teardown.
    """
    use_alarm = (
        hasattr(signal, "setitimer")
        and hasattr(signal, "SIGALRM")
        and threading.current_thread() is threading.main_thread()
    )
    if use_alarm:
        def _handler(_signum, _frame):  # noqa: ANN001
            raise TimeoutError(f"timeout after {timeout}s")

        prev = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            return fn()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, prev)

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(fn)
        return fut.result(timeout=timeout)
    except FuturesTimeout as exc:
        raise TimeoutError(f"timeout after {timeout}s") from exc
    finally:
        # Do not wait on a runaway thread (infinite loop fixtures).
        pool.shutdown(wait=False, cancel_futures=True)


# ── Inject / repair mutators ────────────────────────────────────────────────


@dataclass
class BugEpisode:
    """One inject→repair unit (SSR episode)."""

    episode_id: str
    sample_id: str
    inject_plugin: str
    complexity: int
    baseline_source: str
    buggy_source: str
    expected: Any
    mutation_note: str = ""
    inverse_hint: str = ""  # opaque hint for oracle_inverse

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "sample_id": self.sample_id,
            "inject_plugin": self.inject_plugin,
            "complexity": self.complexity,
            "mutation_note": self.mutation_note,
            "baseline_sha256": _sha(self.baseline_source),
            "buggy_sha256": _sha(self.buggy_source),
            "expected": self.expected,
        }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _episode_id(sample_id: str, inject_id: str, seed: int, round_i: int) -> str:
    raw = f"{sample_id}:{inject_id}:{seed}:{round_i}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def inject_bug(
    source: str,
    inject_id: str,
    *,
    sample_id: str = "custom",
    expected: Any = _MISSING,
    seed: int = DEFAULT_SEED,
    round_index: int = 0,
) -> BugEpisode:
    """Apply a named inject plugin; return a BugEpisode.

    Raises ``SelfPlayError`` for unknown plugins or failed mutations.
    Pass ``expected=_MISSING`` (default) to look up SAMPLE_EXPECTED or infer
    from a single baseline exec; pass ``expected=None`` when None is the
    legitimate expected value.
    """
    unknown = validate_plugin_ids([inject_id])
    if unknown:
        raise SelfPlayError(f"unknown inject plugin: {unknown[0]}")
    plugin = INJECT_CATALOG.get(inject_id) or PLUGIN_CATALOG.get(inject_id)
    if plugin is None:
        raise SelfPlayError(f"unknown inject plugin: {inject_id}")
    if plugin.surface != "inject":
        raise SelfPlayError(f"plugin is not an inject surface: {inject_id}")

    buggy, note, inverse = _apply_inject(source, inject_id, seed=seed)
    if buggy == source:
        raise SelfPlayError(f"inject {inject_id} made no change on sample={sample_id}")

    if expected is not _MISSING:
        exp = expected
    elif sample_id in SAMPLE_EXPECTED:
        exp = SAMPLE_EXPECTED[sample_id]
    else:
        # Infer expected from healthy baseline once (restricted exec).
        try:
            exp = _exec_source_value(source, _ENTRY)
        except BaseException as exc:  # noqa: BLE001
            raise SelfPlayError(f"baseline does not exec: {exc}") from exc

    return BugEpisode(
        episode_id=_episode_id(sample_id, inject_id, seed, round_index),
        sample_id=sample_id,
        inject_plugin=inject_id,
        complexity=plugin.complexity,
        baseline_source=source,
        buggy_source=buggy,
        expected=exp,
        mutation_note=note,
        inverse_hint=inverse,
    )


def _splice(source: str, start: int, end: int, replacement: str) -> str:
    """Replace source[start:end] with replacement (position-exact)."""
    return source[:start] + replacement + source[end:]


def _pos_hint(start: int, new_text: str, orig_text: str) -> str:
    """Inverse hint: restore orig_text over the span starting at start of length len(new)."""
    # Encode orig with length prefix so colons inside original are safe.
    return f"pos:{start}:{len(new_text)}:{len(orig_text)}:{orig_text}"


def _apply_pos_inverse(buggy: str, hint: str) -> Optional[str]:
    """Apply a pos:start:new_len:orig_len:orig_text inverse hint."""
    if not hint.startswith("pos:"):
        return None
    parts = hint.split(":", 4)
    if len(parts) != 5:
        return None
    try:
        start = int(parts[1])
        new_len = int(parts[2])
        orig_len = int(parts[3])
    except ValueError:
        return None
    orig = parts[4]
    if len(orig) != orig_len:
        return None
    end = start + new_len
    if start < 0 or end > len(buggy):
        return None
    return _splice(buggy, start, end, orig)


def _apply_inject(
    source: str, inject_id: str, *, seed: int
) -> tuple[str, str, str]:
    """Return (buggy_source, note, inverse_hint).

    Mutations splice by match position (never unanchored ``str.replace`` of a
    substring that may appear earlier in the source).
    """
    rng = random.Random(seed)

    if inject_id == "flip_bool_return":
        for old, new in (("return True", "return False"), ("return False", "return True")):
            idx = source.find(old)
            if idx >= 0:
                buggy = _splice(source, idx, idx + len(old), new)
                return (
                    buggy,
                    f"flipped {old} → {new}",
                    _pos_hint(idx, new, old),
                )
        raise SelfPlayError("flip_bool_return: no boolean return found")

    if inject_id == "off_by_one":
        # Prefer range(N) → range(N-1) when N>0, else bump a bare small int.
        m = re.search(r"range\((\d+)\)", source)
        if m and int(m.group(1)) > 0:
            n = int(m.group(1))
            start, end = m.start(1), m.end(1)
            new_txt = str(n - 1)
            orig_txt = m.group(1)
            buggy = _splice(source, start, end, new_txt)
            return (
                buggy,
                f"range({n}) → range({n - 1})",
                _pos_hint(start, new_txt, orig_txt),
            )
        m = re.search(r"\b([1-9]\d*)\b", source)
        if not m:
            raise SelfPlayError("off_by_one: no integer literal found")
        n = int(m.group(1))
        start, end = m.start(1), m.end(1)
        new_txt = str(n + 1)
        orig_txt = m.group(1)
        buggy = _splice(source, start, end, new_txt)
        return (
            buggy,
            f"literal {n} → {n + 1}",
            _pos_hint(start, new_txt, orig_txt),
        )

    if inject_id == "break_equality":
        for old, new in ((" == ", " != "), (" != ", " == ")):
            idx = source.find(old)
            if idx >= 0:
                buggy = _splice(source, idx, idx + len(old), new)
                return (
                    buggy,
                    f"replaced {old.strip()} with {new.strip()}",
                    _pos_hint(idx, new, old),
                )
        raise SelfPlayError("break_equality: no ==/!= found")

    if inject_id == "drop_guard":
        # Fixture-oriented patterns first, then generic named guard.
        for old, new, note in (
            ("ok = True", "ok = False", "forced ok = False"),
            ("if flag:", "if False:", "forced if False"),
        ):
            idx = source.find(old)
            if idx >= 0:
                buggy = _splice(source, idx, idx + len(old), new)
                return buggy, note, _pos_hint(idx, new, old)
        m = re.search(r"\bif\s+\w+\s*:", source)
        if m:
            old = m.group(0)
            new = "if False:"
            buggy = _splice(source, m.start(), m.end(), new)
            return (
                buggy,
                "forced if False on named guard",
                _pos_hint(m.start(), new, old),
            )
        raise SelfPlayError("drop_guard: no guard pattern found")

    if inject_id == "typo_name":
        # Typo the RHS identifier of `result = <name> …` (span of the name only).
        m = re.search(r"result\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", source)
        if m:
            name = m.group(1)
            if name not in ("True", "False", "None") and not name.isdigit():
                typo = name[:-1] + ("q" if name[-1] != "q" else "z")
                start, end = m.start(1), m.end(1)
                buggy = _splice(source, start, end, typo)
                return (
                    buggy,
                    f"typo {name} → {typo} in result expr",
                    _pos_hint(start, typo, name),
                )
        # Fallback: typo one identifier occurrence by word-boundary match.
        ids = re.findall(r"\b([a-z_][a-z0-9_]{2,})\b", source)
        ids = [i for i in ids if i not in ("result", "return", "range", "total", "def")]
        if not ids:
            raise SelfPlayError("typo_name: no identifier found")
        name = ids[rng.randrange(len(ids))]
        typo = name + "x"
        m = re.search(rf"\b{re.escape(name)}\b", source)
        if not m:
            raise SelfPlayError("typo_name: identifier span not found")
        buggy = _splice(source, m.start(), m.end(), typo)
        return buggy, f"typo {name} → {typo}", _pos_hint(m.start(), typo, name)

    raise SelfPlayError(f"unhandled inject plugin: {inject_id}")


def repair_bug(
    episode: BugEpisode,
    repair_id: str,
) -> dict[str, Any]:
    """Apply a named repair plugin to a BugEpisode.

    Returns dict with repaired_source, ok (vs expected), plugin, note.
    """
    unknown = validate_plugin_ids([repair_id])
    if unknown:
        raise SelfPlayError(f"unknown repair plugin: {unknown[0]}")
    plugin = REPAIR_CATALOG.get(repair_id) or PLUGIN_CATALOG[repair_id]
    if plugin.surface != "repair":
        raise SelfPlayError(f"plugin is not a repair surface: {repair_id}")

    source = episode.buggy_source
    note = ""

    if repair_id == "noop":
        repaired = source
        note = "no changes"
    elif repair_id == "restore_baseline":
        repaired = episode.baseline_source
        note = "restored baseline source"
    elif repair_id == "oracle_inverse":
        repaired, note = _oracle_inverse(episode)
    elif repair_id == "heuristic_scan":
        repaired, note = _heuristic_repair(episode)
    else:
        raise SelfPlayError(f"unhandled repair plugin: {repair_id}")

    verdict = verify_source(repaired, expected=episode.expected)
    return {
        "repair_plugin": repair_id,
        "repaired_source": repaired,
        "note": note,
        "verify": verdict,
        "ok": bool(verdict.get("ok")),
        "restored_baseline": repaired == episode.baseline_source,
        "repaired_sha256": _sha(repaired),
    }


def _oracle_inverse(episode: BugEpisode) -> tuple[str, str]:
    """Invert the known inject using inverse_hint / inject id.

    Always verify the candidate; if it fails (or no hint), restore baseline so
    the oracle is infallible by construction for the reward signal.
    """
    repaired, note = _oracle_inverse_try(episode)
    if verify_source(repaired, expected=episode.expected).get("ok"):
        return repaired, note
    return (
        episode.baseline_source,
        f"oracle fallback restore (verify failed; was: {note})",
    )


def _oracle_inverse_try(episode: BugEpisode) -> tuple[str, str]:
    """Best-effort inverse without baseline short-circuit (except last resort)."""
    hint = episode.inverse_hint or ""
    buggy = episode.buggy_source

    # Preferred path: position-anchored pos: hints from inject mutators.
    if hint.startswith("pos:"):
        restored = _apply_pos_inverse(buggy, hint)
        if restored is not None:
            return restored, "oracle pos-inverse"

    # Legacy / generic fallbacks for older hints or hand-built episodes.
    if hint.startswith("flip_bool:") or episode.inject_plugin == "flip_bool_return":
        if "return False" in buggy and "return True" in episode.baseline_source:
            idx = buggy.find("return False")
            if idx >= 0:
                return (
                    _splice(buggy, idx, idx + len("return False"), "return True"),
                    "oracle flip → True",
                )
        if "return True" in buggy and "return False" in episode.baseline_source:
            idx = buggy.find("return True")
            if idx >= 0:
                return (
                    _splice(buggy, idx, idx + len("return True"), "return False"),
                    "oracle flip → False",
                )

    if hint.startswith("range:") and hint.count(":") == 2:
        _, cur, orig = hint.split(":")
        target = f"range({cur})"
        idx = buggy.find(target)
        if idx >= 0:
            return (
                _splice(buggy, idx, idx + len(target), f"range({orig})"),
                f"oracle range({cur}) → range({orig})",
            )

    if hint.startswith("lit:") and hint.count(":") == 2:
        _, cur, orig = hint.split(":")
        # Prefer word-boundary match of the injected literal.
        m = re.search(rf"\b{re.escape(str(cur))}\b", buggy)
        if m:
            return (
                _splice(buggy, m.start(), m.end(), str(orig)),
                f"oracle lit {cur} → {orig}",
            )

    if hint.startswith("eq:") or episode.inject_plugin == "break_equality":
        # Prefer first comparison operator that differs from baseline intent.
        if " != " in buggy:
            idx = buggy.find(" != ")
            return _splice(buggy, idx, idx + 4, " == "), "oracle != → =="
        if " == " in buggy and " != " in episode.baseline_source:
            idx = buggy.find(" == ")
            return _splice(buggy, idx, idx + 4, " != "), "oracle == → !="

    if hint.startswith("typo:") and hint.count(":") >= 2:
        _, typo, name = hint.split(":", 2)
        m = re.search(rf"\b{re.escape(typo)}\b", buggy)
        if m:
            return _splice(buggy, m.start(), m.end(), name), f"oracle typo {typo} → {name}"
        idx = buggy.find(typo)
        if idx >= 0:
            return _splice(buggy, idx, idx + len(typo), name), f"oracle typo {typo} → {name}"

    return episode.baseline_source, "oracle fallback restore"


def _heuristic_repair(episode: BugEpisode) -> tuple[str, str]:
    """Agent-shaped repair: try common inverses without trusting inject id fully."""
    buggy = episode.buggy_source
    candidates: list[tuple[str, str]] = []

    if "return False" in buggy:
        candidates.append(
            (buggy.replace("return False", "return True", 1), "heuristic flip False→True")
        )
    if "return True" in buggy and "return True" not in episode.baseline_source:
        candidates.append(
            (buggy.replace("return True", "return False", 1), "heuristic flip True→False")
        )
    if " != " in buggy:
        candidates.append((buggy.replace(" != ", " == ", 1), "heuristic != → =="))
    if "ok = False" in buggy:
        candidates.append(
            (buggy.replace("ok = False", "ok = True", 1), "heuristic ok = True")
        )
    if "if False:" in buggy:
        candidates.append((buggy.replace("if False:", "if True:", 1), "heuristic if True:"))
    # range(n) expand by 1
    m = re.search(r"range\((\d+)\)", buggy)
    if m:
        n = int(m.group(1))
        candidates.append(
            (
                buggy.replace(f"range({n})", f"range({n + 1})", 1),
                f"heuristic range({n}) → range({n + 1})",
            )
        )

    for cand, note in candidates:
        if verify_source(cand, expected=episode.expected).get("ok"):
            return cand, note

    # Last resort: baseline restore (still a valid repair strategy)
    if verify_source(episode.baseline_source, expected=episode.expected).get("ok"):
        return episode.baseline_source, "heuristic fallback restore baseline"
    return buggy, "heuristic found no fix"


# ── Self-play loop ──────────────────────────────────────────────────────────


@dataclass
class RoundResult:
    """One self-play round outcome."""

    round_index: int
    complexity_cap: int
    episode: BugEpisode
    inject_verify: dict[str, Any]
    repair: dict[str, Any]
    reward: float
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "complexity_cap": self.complexity_cap,
            "episode": self.episode.to_dict(),
            "inject_verify": self.inject_verify,
            "repair_plugin": self.repair.get("repair_plugin"),
            "repair_ok": self.repair.get("ok"),
            "repair_note": self.repair.get("note"),
            "reward": self.reward,
            "ok": self.ok,
        }


def complexity_for_round(round_index: int, max_rounds: int) -> int:
    """Ramp complexity 1→3 across rounds (SSR increasing difficulty)."""
    if max_rounds <= 1:
        return COMPLEXITY_EASY
    # Map round 0..max-1 onto 1..3
    t = round_index / max(1, max_rounds - 1)
    if t < 0.34:
        return COMPLEXITY_EASY
    if t < 0.67:
        return COMPLEXITY_MEDIUM
    return COMPLEXITY_HARD


def pick_inject_plugin(
    sample_id: str,
    *,
    complexity_cap: int,
    seed: int,
    round_index: int,
    prefer: Optional[Sequence[str]] = None,
) -> str:
    """Choose an inject plugin within complexity_cap for the sample.

    Among sample preferences that fit the cap, pick the **highest** complexity
    (curriculum pressure). Otherwise pick the highest-complexity enabled plugin
    under the cap (seeded among ties).
    """
    prefs = list(prefer or _SAMPLE_INJECT_PREF.get(sample_id, ()))
    enabled = [
        p
        for p in INJECT_CATALOG.values()
        if p.enabled_by_default and p.complexity <= complexity_cap
    ]
    if not enabled:
        raise SelfPlayError(f"no inject plugins at complexity ≤ {complexity_cap}")

    rng = random.Random(seed + round_index * 17)

    # Sample-matched plugins that fit the cap — highest complexity first.
    matched: list[PlayPlugin] = []
    for pid in prefs:
        plug = INJECT_CATALOG.get(pid)
        if plug and plug.complexity <= complexity_cap and plug.enabled_by_default:
            matched.append(plug)
    if matched:
        matched.sort(key=lambda p: (p.complexity, p.plugin_id))
        top_c = matched[-1].complexity
        pool = [p for p in matched if p.complexity == top_c]
        return rng.choice(pool).plugin_id

    # Prefer highest complexity under the cap (curriculum pressure).
    enabled.sort(key=lambda p: (p.complexity, p.plugin_id))
    top_c = enabled[-1].complexity
    pool = [p for p in enabled if p.complexity == top_c]
    return rng.choice(pool).plugin_id


def run_self_play(
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    seed: int = DEFAULT_SEED,
    sample_ids: Optional[Sequence[str]] = None,
    repair_plugin: str = "oracle_inverse",
    require_inject_fails: bool = True,
    sources: Optional[dict[str, str]] = None,
    expected_map: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Run an offline self-play inject→repair loop (SSR shape).

    Parameters
    ----------
    max_rounds:
        Number of inject/repair iterations (complexity ramps).
    seed:
        RNG seed for plugin selection.
    sample_ids:
        Which SAMPLE_PROGRAMS (or custom ``sources`` keys) to cycle.
    repair_plugin:
        Marketplace repair plugin id.
    require_inject_fails:
        If True, a round is invalid when the bug does not break the test.
    sources / expected_map:
        Optional custom programs; default uses SAMPLE_PROGRAMS.

    Returns
    -------
    SelfPlayReport dict (schema ``nexus.self_play_ssr/v1``).
    """
    if max_rounds < 1:
        raise SelfPlayError("max_rounds must be >= 1")
    repair_key = str(repair_plugin or "").strip()
    if not repair_key:
        raise SelfPlayError("repair_plugin is required")
    unknown = validate_plugin_ids([repair_key])
    if unknown:
        raise SelfPlayError(f"unknown repair plugin: {unknown[0]}")
    repair_meta = PLUGIN_CATALOG.get(repair_key)
    if repair_meta is None or repair_meta.surface != "repair":
        raise SelfPlayError(f"plugin is not a repair surface: {repair_key}")
    repair_plugin = repair_key

    catalog = catalog_self_check()
    if not catalog["ok"]:
        raise SelfPlayError(f"catalog self-check failed: {catalog['issues']}")

    programs = dict(sources or SAMPLE_PROGRAMS)
    expects = dict(expected_map or SAMPLE_EXPECTED)
    ids = list(sample_ids or programs.keys())
    if not ids:
        raise SelfPlayError("no sample programs")

    rounds: list[RoundResult] = []
    total_reward = 0.0
    errors: list[str] = []

    for i in range(max_rounds):
        sample_id = ids[i % len(ids)]
        if sample_id not in programs:
            errors.append(f"round {i}: missing sample {sample_id}")
            continue
        source = programs[sample_id]
        expected = expects.get(sample_id)
        if expected is None:
            errors.append(f"round {i}: no expected for {sample_id}")
            continue

        # Healthy baseline must pass.
        base_v = verify_source(source, expected=expected)
        if not base_v.get("ok"):
            errors.append(f"round {i}: baseline broken for {sample_id}: {base_v.get('error')}")
            continue

        cap = complexity_for_round(i, max_rounds)
        try:
            inject_id = pick_inject_plugin(
                sample_id, complexity_cap=cap, seed=seed, round_index=i
            )
            episode = inject_bug(
                source,
                inject_id,
                sample_id=sample_id,
                expected=expected,
                seed=seed,
                round_index=i,
            )
        except SelfPlayError as exc:
            # Soft fall back: try any inject that applies.
            episode = None
            last_err = str(exc)
            for alt in list_plugins(surface="inject", enabled_only=True, max_complexity=cap):
                try:
                    episode = inject_bug(
                        source,
                        alt["plugin_id"],
                        sample_id=sample_id,
                        expected=expected,
                        seed=seed + i,
                        round_index=i,
                    )
                    inject_id = alt["plugin_id"]
                    break
                except SelfPlayError as e2:
                    last_err = str(e2)
            if episode is None:
                errors.append(f"round {i}: inject failed ({last_err})")
                continue

        inj_v = verify_source(episode.buggy_source, expected=episode.expected)
        if require_inject_fails and inj_v.get("ok"):
            errors.append(
                f"round {i}: inject {episode.inject_plugin} did not break test"
            )
            continue

        rep = repair_bug(episode, repair_plugin)
        # Reward: 1.0 full repair that matches baseline; 0.5 pass with drift; 0 fail.
        if rep.get("ok") and rep.get("restored_baseline"):
            reward = 1.0
        elif rep.get("ok"):
            reward = 0.5
        else:
            reward = 0.0
        total_reward += reward
        rounds.append(
            RoundResult(
                round_index=i,
                complexity_cap=cap,
                episode=episode,
                inject_verify=inj_v,
                repair=rep,
                reward=reward,
                ok=bool(rep.get("ok")),
            )
        )

    n = len(rounds)
    mean_reward = (total_reward / n) if n else 0.0
    repaired = sum(1 for r in rounds if r.ok)
    report = {
        "schema": SCHEMA,
        "ok": n > 0 and repaired == n and not errors,
        "paper": PAPER,
        "paper_title": PAPER_TITLE,
        "source_pattern": SOURCE_PATTERN,
        "idea_id": IDEA_ID,
        "max_rounds": max_rounds,
        "seed": seed,
        "repair_plugin": repair_plugin,
        "rounds_completed": n,
        "rounds_repaired": repaired,
        "mean_reward": round(mean_reward, 4),
        "total_reward": round(total_reward, 4),
        "errors": errors,
        "catalog": {
            "inject_count": catalog["inject_count"],
            "repair_count": catalog["repair_count"],
            "ok": catalog["ok"],
        },
        "rounds": [r.to_dict() for r in rounds],
    }
    return report


# ── grok_worker integration (prompt / brief — no live call required) ───────


def build_self_play_prompt(
    workdir: Path | str,
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    goal_extra: str = "",
) -> str:
    """Build a Grok hard-work prompt for agentic self-play inject→repair.

    Used by ``grok_worker.grok_self_play_ssr``; safe to call offline.
    """
    workdir = Path(workdir).resolve()
    injects = list_plugins(surface="inject", enabled_only=True)
    repairs = list_plugins(surface="repair", enabled_only=True)
    inj_lines = "\n".join(
        f"  - `{p['plugin_id']}` (c={p['complexity']}): {p['description']}"
        for p in injects
    )
    rep_lines = "\n".join(
        f"  - `{p['plugin_id']}` (c={p['complexity']}): {p['description']}"
        for p in repairs
    )
    extra = f"\n{goal_extra.strip()}\n" if goal_extra.strip() else ""
    return (
        "You are running a **self-play SWE-RL style** inject→repair loop "
        f"(arXiv {PAPER}) inside this checkout.\n"
        f"Working directory: {workdir}\n"
        "Model: Grok CLI. Tools allowed for read/edit/test.\n\n"
        "Rules:\n"
        "- Prefer small, tested mutations; keep pytest green on the *baseline*.\n"
        "- Work in a throwaway path or revert mutations after each round.\n"
        "- Do NOT force-push; do NOT commit secrets; do NOT vendor upstream trees.\n"
        "- Use the named marketplace plugins below (wshobson-shaped catalog).\n"
        f"- Run up to {max_rounds} rounds; ramp complexity each round.\n"
        "- Each bug should be witnessed by a failing test (fail-to-pass), "
        "then repaired until the test passes.\n"
        "- Finish by summarizing rounds, rewards (1=restored, 0.5=pass-with-drift, "
        "0=fail), and files touched.\n"
        f"{extra}\n"
        "## Inject plugins (marketplace)\n"
        f"{inj_lines}\n\n"
        "## Repair plugins (marketplace)\n"
        f"{rep_lines}\n\n"
        "## Offline reference\n"
        "For a deterministic dry-run without LLM edits, call:\n"
        "  PYTHONPATH=src python -c \"from nexus.self_play_ssr import run_self_play; "
        "import json; print(json.dumps(run_self_play(max_rounds=3), indent=2))\"\n"
    )


def self_play_brief(
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    seed: int = DEFAULT_SEED,
    report: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Compact offline brief: catalog + one dry-run summary for workers/docs.

    Pass ``report=`` (an already-computed ``run_self_play`` result) to avoid a
    second curriculum execution when the worker already has the offline report.
    """
    if report is not None:
        dry = report
    else:
        dry = run_self_play(
            max_rounds=max_rounds, seed=seed, repair_plugin="oracle_inverse"
        )
    return {
        "schema": SCHEMA,
        "paper": PAPER,
        "idea_id": IDEA_ID,
        "plugins": list_plugins(enabled_only=True),
        "catalog_ok": catalog_self_check()["ok"],
        "dry_run": {
            "ok": dry.get("ok"),
            "rounds_completed": dry.get("rounds_completed", 0),
            "rounds_repaired": dry.get("rounds_repaired", 0),
            "mean_reward": dry.get("mean_reward", 0.0),
        },
    }


def run_self_play_or_report(**kwargs: Any) -> dict[str, Any]:
    """Soft wrapper: never raises; returns ok=False report on config/runtime errors."""
    try:
        return run_self_play(**kwargs)
    except SelfPlayError as exc:
        return {
            "schema": SCHEMA,
            "ok": False,
            "error": str(exc),
            "paper": PAPER,
            "idea_id": IDEA_ID,
            "rounds": [],
            "rounds_completed": 0,
            "rounds_repaired": 0,
            "mean_reward": 0.0,
            "errors": [str(exc)],
        }
    except (KeyError, TypeError, ValueError) as exc:
        # Misconfiguration that slipped past SelfPlayError (e.g. blank ids).
        return {
            "schema": SCHEMA,
            "ok": False,
            "error": str(exc),
            "paper": PAPER,
            "idea_id": IDEA_ID,
            "rounds": [],
            "rounds_completed": 0,
            "rounds_repaired": 0,
            "mean_reward": 0.0,
            "errors": [str(exc)],
        }
