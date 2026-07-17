"""Grok CLI headless worker — hard grading + hard improve work.

Local LLM (Ollama) stays for light bus turns; **Grok** does scoring and
agentic hard work when ``grader=grok`` / ``worker=grok`` (defaults under auto).

  grok -p "…" -m grok-4.5 --max-turns N --json-schema '…'
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from . import usage as usage_mod

# Tools to strip for pure text/JSON grading (no agentic exploration).
_GRADE_DISALLOWED = (
    "run_terminal_command,run_terminal_cmd,bash,web_search,web_fetch,"
    "search_replace,write,read_file,list_dir,grep,image_gen,image_edit,"
    "Agent,spawn_subagent"
)

_GRADE_SCHEMA = (
    '{"type":"object","properties":{'
    '"idea":{"type":"number","description":"novelty/usefulness 1-10"},'
    '"skill":{"type":"number","description":"engineering quality 1-10"},'
    '"description":{"type":"string","description":"one English sentence"}'
    '},"required":["idea","skill","description"]}'
)


def grok_available() -> bool:
    return bool(shutil.which("grok"))


def default_model() -> str:
    """Prefer NEXUS_GROK_MODEL; ignore broken XAI_MODEL pins (e.g. unknown ids)."""
    explicit = (os.environ.get("NEXUS_GROK_MODEL") or "").strip()
    if explicit:
        return explicit
    # Latest cloud Grok for product work (subscription preferred over API).
    return "grok-4.5"


def default_effort() -> str:
    """Reasoning effort clamped to what the grok CLI accepts: high|medium|low.

    The CLI rejects anything else ("unknown effort level"), so aliases like
    xhigh/max/ultra map to high and unknown values fall back to high.
    """
    raw = (os.environ.get("NEXUS_GROK_EFFORT") or "high").strip().lower() or "high"
    if raw in ("xhigh", "max", "ultra", "highest"):
        return "high"
    if raw in ("none", "minimal"):
        return "low"
    if raw not in ("high", "medium", "low"):
        return "high"
    return raw


def _child_env() -> dict[str, str]:
    """Env for headless grok.

    Default: **subscription (OIDC)** — strip XAI_API_KEY so CLI uses grok.com login.
    Set NEXUS_GROK_USE_API=1 to keep API key billing instead.
    """
    env = os.environ.copy()
    # Avoid child inheriting a broken model pin when we pass -m ourselves.
    bad = env.get("XAI_MODEL") or ""
    if bad and bad not in ("grok-4.5", "grok-composer-2.5-fast") and not os.environ.get(
        "NEXUS_GROK_MODEL"
    ):
        env.pop("XAI_MODEL", None)
    # Prefer subscription over API unless explicitly requested
    use_api = (os.environ.get("NEXUS_GROK_USE_API") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "api",
    )
    if not use_api:
        env.pop("XAI_API_KEY", None)
        env.pop("XAI_API_BASE", None)
    return env


def _parse_json_obj(text: str) -> Optional[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    # strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[^{}]*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    # nested braces
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def grok_prompt(
    prompt: str,
    *,
    model: Optional[str] = None,
    cwd: Optional[Path] = None,
    max_turns: int = 2,
    tools: bool = False,
    timeout_s: float = 300,
    label: str = "grok",
    enforce_budget: bool = True,
    json_schema: Optional[str] = None,
    allow_subagents: bool = False,
    allow_plan: bool = False,
    soft_ok: bool = False,
) -> dict[str, Any]:
    """Run headless Grok. tools=False disables shell/edit for pure JSON grading.

    ``soft_ok``: treat non-zero exit as ok when there is substantial text (agentic
    runs often exit 1 after max-turns while still landing useful work).
    """
    if not grok_available():
        return {"ok": False, "error": "grok CLI not on PATH", "text": ""}

    model = model or default_model()
    effort = default_effort()
    est = usage_mod.estimate_tokens(prompt) + 1024
    try:
        usage_mod.check_budget(est, raise_on_exceed=enforce_budget)
    except usage_mod.BudgetExceeded as e:
        return {"ok": False, "error": f"budget: {e}", "text": ""}

    cmd = [
        "grok",
        "-p",
        prompt,
        "-m",
        model,
        "--reasoning-effort",
        effort,
        "--max-turns",
        str(max_turns),
        "--disable-web-search",
    ]
    if not allow_subagents:
        cmd.append("--no-subagents")
    if not allow_plan:
        cmd.append("--no-plan")
    if json_schema:
        cmd += ["--json-schema", json_schema]
    else:
        cmd += ["--output-format", "plain"]
    if not tools:
        cmd += ["--disallowed-tools", _GRADE_DISALLOWED]
    else:
        # hard work: allow tools; always-approve for unattended apply
        cmd += ["--always-approve"]

    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=_child_env(),
        )
        text = (p.stdout or "").strip()
        if not text and p.stderr:
            text = (p.stderr or "").strip()[-4000:]
        usage_mod.record_text(
            prompt,
            text,
            source=f"grok:{model}",
            label=label,
            enforce=False,  # already pre-checked
        )
        parsed_ok = bool(_parse_json_obj(text)) if json_schema else False
        # Envelope from json-schema mode: structuredOutput or long plain text
        substantial = len(text) >= 200
        ok = bool(text) and (
            p.returncode == 0
            or parsed_ok
            or (soft_ok and substantial)
        )
        return {
            "ok": ok,
            "text": text,
            "returncode": p.returncode,
            "stderr": (p.stderr or "")[-500:],
            "model": model,
            "effort": effort,
            "auth": "api" if (os.environ.get("NEXUS_GROK_USE_API") or "").strip() else "subscription",
            "max_turns": max_turns,
            "timeout_s": timeout_s,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout_s}s", "text": ""}
    except Exception as e:
        return {"ok": False, "error": str(e), "text": ""}


def _extract_grade_obj(text: str) -> Optional[dict[str, Any]]:
    """Pull idea/skill/description from plain JSON or Grok --json-schema envelope."""
    if not text:
        return None
    outer = _parse_json_obj(text)
    if not outer:
        return None
    # Headless json-schema mode wraps as {structuredOutput: {...}, text: "...", ...}
    for key in ("structuredOutput", "structured_output", "result", "output", "data", "json"):
        inner = outer.get(key)
        if isinstance(inner, dict) and ("idea" in inner or "skill" in inner):
            return inner
        if isinstance(inner, str):
            nested = _parse_json_obj(inner)
            if nested and ("idea" in nested or "skill" in nested):
                return nested
    if "idea" in outer or "skill" in outer:
        return outer
    # text field may hold stringified JSON
    if isinstance(outer.get("text"), str):
        nested = _parse_json_obj(outer["text"])
        if nested and ("idea" in nested or "skill" in nested):
            return nested
    return None


def grok_grade(
    digest: str,
    full_name: str,
    *,
    model: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Grok grades a repo for *reuse* (idea + skill + description). Hard work."""
    prompt = (
        "You are a strict grader. You have NO tools and must NOT inspect any filesystem.\n"
        "The DIGEST below is the entire evidence. Score for REUSE in another engineering "
        "project (not social popularity, follow, or star).\n"
        "Return JSON only with fields idea (1-10 novelty/usefulness), "
        "skill (1-10 engineering quality), description (one English sentence).\n\n"
        f"Repo name: {full_name}\n\n"
        f"DIGEST (complete):\n{digest[:12000]}\n"
    )
    res = grok_prompt(
        prompt,
        model=model,
        max_turns=2,
        tools=False,
        timeout_s=300,
        label=f"grade:{full_name}",
        json_schema=_GRADE_SCHEMA,
        soft_ok=True,
    )
    text = res.get("text") or ""
    obj = _extract_grade_obj(text)
    if not obj:
        return None
    try:
        idea = max(1.0, min(10.0, float(obj.get("idea") or 5)))
        skill = max(1.0, min(10.0, float(obj.get("skill") or 5)))
    except (TypeError, ValueError):
        return None
    return {
        "idea": round(idea, 2),
        "skill": round(skill, 2),
        "description": str(obj.get("description") or "")[:400],
        "method": f"grok:{res.get('model')}",
    }


def grok_reason(
    evidence: str,
    *,
    goal: str = "self-improve this multi-agent repository",
    model: Optional[str] = None,
    label: str = "reason",
) -> dict[str, Any]:
    """Grok 4.5 pure reasoning over papers + repos (no tools). Returns markdown text."""
    prompt = (
        "You are the research+engineering reasoner for NEXUS self-improvement.\n"
        "You have NO tools. Use only the EVIDENCE below.\n"
        f"GOAL: {goal}\n\n"
        "Write a concrete markdown plan with these sections:\n"
        "1. ## Executive summary (5 bullets)\n"
        "2. ## 10 arXiv papers — what to steal for this codebase (table or numbered list: "
        "id, idea, concrete NEXUS change)\n"
        "3. ## 10 GitHub repos — portable patterns (repo, score if given, pattern, where to port)\n"
        "4. ## Prioritized engineering backlog (P0/P1/P2, each with files/modules to touch)\n"
        "5. ## First apply slice (smallest PR-sized change that proves the loop, tests to run)\n"
        "Be specific to multi-agent durability, MCP, mine/alive loops, grading, and demos. "
        "Do not invent paper ids or repos not present in EVIDENCE.\n\n"
        f"EVIDENCE:\n{evidence[:50000]}\n"
    )
    return grok_prompt(
        prompt,
        model=model,
        max_turns=4,
        tools=False,
        timeout_s=600,
        label=label,
        enforce_budget=True,
        soft_ok=True,
    )


def _resolve_turns_timeout(
    max_turns: int,
    timeout_s: float,
    *,
    turns_lo: int = 4,
    turns_hi: int = 128,
    timeout_lo: float = 120.0,
    timeout_hi: float = 7200.0,
) -> tuple[int, float]:
    """Apply env overrides and clamp agentic turn/timeout budgets."""
    try:
        max_turns = int(os.environ.get("NEXUS_GROK_MAX_TURNS") or max_turns)
    except ValueError:
        pass
    try:
        timeout_s = float(os.environ.get("NEXUS_GROK_TIMEOUT_S") or timeout_s)
    except ValueError:
        pass
    max_turns = max(turns_lo, min(int(max_turns), turns_hi))
    timeout_s = max(timeout_lo, min(float(timeout_s), timeout_hi))
    return max_turns, timeout_s


def _git_porcelain(workdir: Path) -> list[str]:
    """Return ``git status --porcelain`` lines (empty if not a git repo / error)."""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []
    return [ln for ln in (r.stdout or "").splitlines() if ln.strip()]


def grok_hard_improve(
    workdir: Path,
    goal: str,
    *,
    model: Optional[str] = None,
    max_turns: int = 64,
    timeout_s: float = 3600,
) -> dict[str, Any]:
    """Hard work: Grok agentically improves the local checkout toward the goal.

    Defaults are intentionally high (maxed agentic budget) for unattended cycles.
    Override with ``NEXUS_GROK_MAX_TURNS`` / ``NEXUS_GROK_TIMEOUT_S`` if needed.
    """
    workdir = Path(workdir).resolve()
    # hard caps so we don't hang forever
    max_turns, timeout_s = _resolve_turns_timeout(
        max_turns,
        timeout_s,
        turns_lo=8,
        turns_hi=128,
        timeout_lo=300.0,
        timeout_hi=7200.0,
    )

    prompt = (
        "You are the hard-worker for NEXUS self-improvement on this git checkout.\n"
        f"Working directory: {workdir}\n"
        "Model: Grok 4.5 CLI. You MAY use tools to read/edit/test. Subagents allowed.\n"
        "Rules:\n"
        "- Prefer small, tested changes; keep make test / pytest green.\n"
        "- Do NOT force-push; do NOT commit secrets; do NOT vendor whole upstream trees.\n"
        "- Port patterns from local clones under .nexus_workspaces/scout_repos/ if useful.\n"
        "- Read docs/SELF_IMPROVE_CYCLE.md and .nexus_state/repo_mine/IMPROVE_OURS.md if present.\n"
        "- Update docs/LATEST_IMPROVE_PLAN.md and docs/ALIVE_IMPROVEMENTS.md when you change behavior.\n"
        "- Implement the **First apply slice** from the plan if feasible in this session; "
        "otherwise land 1–3 high-value code or docs improvements with tests.\n"
        "- Finish cleanly: run pytest, summarize files changed.\n\n"
        f"GOAL:\n{goal}\n"
    )
    res = grok_prompt(
        prompt,
        model=model,
        cwd=workdir,
        max_turns=max_turns,
        tools=True,
        timeout_s=timeout_s,
        label="hard_improve",
        allow_subagents=True,
        allow_plan=True,
        soft_ok=True,
    )
    return res


def grok_self_play_ssr(
    workdir: Path,
    *,
    model: Optional[str] = None,
    max_rounds: int = 3,
    max_turns: int = 32,
    timeout_s: float = 1800,
    offline_only: bool = False,
    goal_extra: str = "",
) -> dict[str, Any]:
    """Self-play inject→repair loop (arXiv 2512.18552 × wshobson marketplace).

    Offline path (default for tests / no grok): runs ``self_play_ssr.run_self_play``
    with deterministic mutators — no LLM, no network.

    Agentic path: builds a marketplace-aware prompt and calls headless Grok with
    tools so the worker can inject/repair in the target checkout.

    Schema: ``nexus.self_play_ssr/v1`` (see ``nexus.self_play_ssr``).

    TODO(next-slice): wire into ``alive.py`` / ``repo_mine`` self-improve loop
    and run agentic episodes in a disposable worktree (GPT F1 isolation).
    """
    from . import self_play_ssr as ssr

    workdir = Path(workdir).resolve()
    try:
        max_rounds = int(max_rounds)
    except (TypeError, ValueError):
        max_rounds = 3
    max_rounds = max(1, min(max_rounds, 12))

    # Soft offline once — never raise out of the worker entrypoint.
    offline = ssr.run_self_play_or_report(
        max_rounds=max_rounds, repair_plugin="oracle_inverse"
    )
    brief = ssr.self_play_brief(max_rounds=max_rounds, report=offline)
    offline_ok = bool(offline.get("ok"))

    out: dict[str, Any] = {
        "schema": ssr.SCHEMA,
        "paper": ssr.PAPER,
        "idea_id": ssr.IDEA_ID,
        "workdir": str(workdir),
        "max_rounds": max_rounds,
        "offline": offline,
        "brief": brief,
        "offline_ok": offline_ok,
        "agentic": None,
        "agentic_ok": None,
    }

    if offline_only or not grok_available():
        out["ok"] = offline_ok
        out["mode"] = "offline"
        if not grok_available() and not offline_only:
            out["note"] = "grok CLI not on PATH; offline self-play only"
        return out

    prompt = ssr.build_self_play_prompt(
        workdir, max_rounds=max_rounds, goal_extra=goal_extra
    )
    max_turns, timeout_s = _resolve_turns_timeout(
        max_turns,
        timeout_s,
        turns_lo=4,
        turns_hi=128,
        timeout_lo=120.0,
        timeout_hi=7200.0,
    )

    agentic = grok_prompt(
        prompt,
        model=model,
        cwd=workdir,
        max_turns=max_turns,
        tools=True,
        timeout_s=timeout_s,
        label="self_play_ssr",
        allow_subagents=True,
        allow_plan=True,
        soft_ok=True,
    )
    text = agentic.get("text") or ""
    dirty = _git_porcelain(workdir)
    agentic_process_ok = bool(agentic.get("ok"))
    # Leftover injected bugs after a crash/max-turns run are a hard safety fail.
    agentic_ok = agentic_process_ok and not dirty
    out["agentic"] = {
        "ok": agentic_process_ok,
        "model": agentic.get("model"),
        "returncode": agentic.get("returncode"),
        "text_len": len(text),
        "text_head": text[:2000],
        "error": agentic.get("error"),
        "dirty_files": dirty,
        "clean": not dirty,
    }
    out["agentic_ok"] = agentic_ok
    out["mode"] = "agentic"
    # Offline health gates; agentic outcome is required when mode is agentic.
    out["ok"] = offline_ok and agentic_ok
    return out
