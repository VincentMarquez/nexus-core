"""Post-implement multi-LLM critique panel (product-only v1).

Flow (per portfolio slice, after Grok hard-apply):

  1. Snapshot working tree (post-Grok implement) for later synthesis revert
  2. Build review pack under ``.nexus_state/critiques/<cycle>/<slice_id>/``
  3. Panel (Claude, GPT/Codex, Antigravity) write critiques only — no src edits
  4. Grok reads critiques → synthesis apply → pytest
  5. If red: panel round 2 → Grok synthesis #2 → pytest
  6. If still red: restore post-Grok snapshot (synthesis only), keep critiques,
     mark slice ``synthesis_reverted``

Dry / non-REAL: write pack + critiques if bus available; skip synthesis edits.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

DEFAULT_CRITICS = ("claude", "gpt", "antigravity")
# Panel seats can take long frontier turns — default 30 minutes each (parallel).
DEFAULT_PANEL_TIMEOUT_S = 1800.0
CRITIC_LABELS = {
    "claude": "Claude",
    "gpt": "ChatGPT (Codex)",
    "gpt2": "GPT-b (Codex)",
    "antigravity": "Antigravity",
    "gemini": "Gemini",
}


def _root(workdir: Path | str) -> Path:
    return Path(workdir or ".").resolve()


def _safe_slice_id(idea: dict[str, Any]) -> str:
    raw = str(idea.get("id") or idea.get("title") or "slice")
    s = re.sub(r"[^\w.\-:+]+", "_", raw).strip("_")[:120]
    return s or "slice"


def _run_git(root: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def parse_porcelain_paths(status: str) -> set[str]:
    """Parse paths from ``git status --porcelain`` text (handles renames)."""
    out: set[str] = set()
    for line in (status or "").splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[-1].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if path:
            out.add(path)
    return out


def list_slice_files(root: Path, *, before_status: str, after_status: str) -> list[str]:
    """Paths that entered or left the dirty set between two porcelain snapshots.

    Strict unit-of-work: does **not** include the full post-status dirty tree.
    Pre-existing dirty files that stay dirty are excluded (they are not this
    idea's slice). Symmetric difference catches new paths and cleaned paths.
    """
    del root  # API stability; callers pass root for symmetry with other helpers
    before = parse_porcelain_paths(before_status)
    after = parse_porcelain_paths(after_status)
    # Paths that entered or left dirty — not ``after`` wholesale (that pulled
    # the whole dirty tree into panel reviews / synthesis prompts).
    changed = (after - before) | (before - after)
    # prefer product code/docs/tests
    preferred = [
        p
        for p in sorted(changed)
        if p.startswith(("src/", "tests/", "docs/", "plugins/", "Makefile", "pyproject"))
        or p.endswith((".py", ".md", ".toml", ".yml", ".yaml"))
    ]
    return preferred or sorted(changed)


def git_status_porcelain(root: Path) -> str:
    p = _run_git(root, "status", "--porcelain")
    return p.stdout or ""


def git_diff_for_files(root: Path, files: list[str], *, max_chars: int = 80_000) -> str:
    if not files:
        return "(no file list)"
    # tracked diffs
    p = _run_git(root, "diff", "--", *files)
    parts = [(p.stdout or "").strip()]
    # untracked file previews
    for f in files[:40]:
        path = root / f
        if not path.is_file():
            continue
        # if untracked, include head of file
        chk = _run_git(root, "ls-files", "--error-unmatch", f)
        if chk.returncode != 0:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parts.append(f"\n--- new file: {f} ---\n{text[:4000]}")
    blob = "\n".join(x for x in parts if x)
    if len(blob) > max_chars:
        return blob[:max_chars] + f"\n\n… truncated ({len(blob)} chars total) …\n"
    return blob or "(empty diff)"


def snapshot_paths(root: Path, files: list[str]) -> dict[str, Optional[str]]:
    """Capture file contents (None = did not exist)."""
    snap: dict[str, Optional[str]] = {}
    for rel in files:
        path = root / rel
        if path.is_file():
            try:
                snap[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                snap[rel] = None
        else:
            snap[rel] = None
    return snap


def restore_snapshot(root: Path, snap: dict[str, Optional[str]]) -> list[str]:
    """Restore files to snapshot. Returns list of restored paths."""
    restored: list[str] = []
    for rel, content in snap.items():
        path = root / rel
        if content is None:
            if path.is_file():
                try:
                    path.unlink()
                    restored.append(rel + " (deleted)")
                except OSError:
                    pass
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        restored.append(rel)
    return restored


def expand_snapshot_scope(
    root: Path,
    slice_files: list[str],
    *,
    baseline_status: Optional[str] = None,
) -> list[str]:
    """Scope for tests / round-2 review after synthesis.

    Always includes the implement *slice_files*. When *baseline_status* is the
    post-Grok porcelain, also includes the **synthesis delta** only (paths that
    entered/left dirty since implement) — never the whole dirty tree.
    """
    scope = set(slice_files)
    if baseline_status is not None:
        now = git_status_porcelain(root)
        scope.update(
            list_slice_files(
                root, before_status=baseline_status, after_status=now
            )
        )
    return sorted(scope)


def restore_post_grok_after_failed_synthesis(
    root: Path,
    *,
    post_grok_snap: dict[str, Optional[str]],
    post_grok_status: str,
) -> list[str]:
    """Synthesis-only revert: restore implement snapshot; drop synthesis-only dirt.

    - Restores contents for paths in *post_grok_snap* (the implement slice).
    - For paths dirty now that were **clean** at post-Grok (not in baseline
      porcelain), git-restore tracked files or delete untracked ones.
    - Pre-existing dirty paths outside the slice are left alone.
    """
    root = _root(root)
    restored = restore_snapshot(root, post_grok_snap)
    post_paths = parse_porcelain_paths(post_grok_status)
    now_paths = parse_porcelain_paths(git_status_porcelain(root))
    for rel in sorted(now_paths - post_paths):
        if rel in post_grok_snap:
            continue  # already restored via snapshot
        path = root / rel
        chk = _run_git(root, "ls-files", "--error-unmatch", rel)
        if chk.returncode == 0:
            # tracked + was clean post-Grok → back to HEAD
            r = _run_git(root, "restore", "--source=HEAD", "--", rel)
            if r.returncode != 0:
                r = _run_git(root, "checkout", "HEAD", "--", rel)
            if r.returncode == 0:
                restored.append(rel + " (git restore)")
        elif path.is_file():
            try:
                path.unlink()
                restored.append(rel + " (deleted new)")
            except OSError:
                pass
        elif path.is_dir():
            # only remove empty dirs we can; avoid rmtree of unrelated trees
            try:
                path.rmdir()
                restored.append(rel + " (rmdir)")
            except OSError:
                pass
    return restored


def run_pytest_slice(root: Path, files: list[str], *, timeout_s: float = 180) -> dict[str, Any]:
    """Run focused pytest when test files exist; else light import check."""
    test_files = [
        f
        for f in files
        if f.startswith("tests/") and f.endswith(".py") and (root / f).is_file()
    ]
    # map src/nexus/foo.py → tests/test_foo.py if present
    for f in files:
        if f.startswith("src/nexus/") and f.endswith(".py"):
            stem = Path(f).stem
            cand = f"tests/test_{stem}.py"
            if (root / cand).is_file() and cand not in test_files:
                test_files.append(cand)
    if not test_files:
        # minimal green check: compile changed python
        py = [f for f in files if f.endswith(".py") and (root / f).is_file()]
        if not py:
            return {"ok": True, "mode": "noop", "output": "no python files to check"}
        bad = []
        for f in py[:30]:
            r = subprocess.run(
                ["python3", "-m", "py_compile", f],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode != 0:
                bad.append(f"{f}: {(r.stderr or r.stdout or '')[:200]}")
        return {
            "ok": not bad,
            "mode": "py_compile",
            "output": "\n".join(bad) if bad else "py_compile ok",
        }
    cmd = ["python3", "-m", "pytest", "-q", "--tb=line", *test_files]
    try:
        p = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "PYTHONPATH": str(root / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")},
        )
        out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
        return {
            "ok": p.returncode == 0,
            "mode": "pytest",
            "returncode": p.returncode,
            "output": out[-6000:],
            "tests": test_files,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "mode": "pytest", "output": f"timeout after {timeout_s}s"}
    except Exception as e:
        return {"ok": False, "mode": "pytest", "error": str(e)}


def critique_dir(
    root: Path,
    *,
    cycle_id: str,
    slice_id: str,
) -> Path:
    d = root / ".nexus_state" / "critiques" / cycle_id / slice_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_review_pack(
    root: Path,
    idea: dict[str, Any],
    *,
    cycle_id: str,
    slice_files: list[str],
    diff_text: str,
    grok_result: Optional[dict[str, Any]] = None,
    scope_contract: Optional[dict[str, Any]] = None,
) -> Path:
    """Create MANIFEST + DIFF + CONTEXT for critics.

    *scope_contract* is optional (S04). When present, writes CONTRACT.json and
    annotates out-of-scope paths without dropping them from *files*/DIFF.
    """
    sid = _safe_slice_id(idea)
    base = critique_dir(root, cycle_id=cycle_id, slice_id=sid)
    (base / "critiques").mkdir(exist_ok=True)
    (base / "synthesis").mkdir(exist_ok=True)

    scope_note: dict[str, Any] = {}
    if scope_contract:
        try:
            from . import scope_contract as sc

            sc.write_contract(base, scope_contract)
            scope_note = {
                "scope_contract": {
                    "schema": scope_contract.get("schema"),
                    "idea_id": scope_contract.get("idea_id"),
                    "digest": sc.contract_digest(scope_contract),
                    "advisory": True,
                },
                "scope_classification": sc.classify_paths(slice_files, scope_contract),
            }
        except Exception as e:
            scope_note = {"scope_contract_error": str(e)[:300]}

    manifest = {
        "schema": "nexus.critique_panel/v1",
        "ts": time.time(),
        "cycle_id": cycle_id,
        "slice_id": sid,
        "idea": {
            "id": idea.get("id"),
            "source": idea.get("source"),
            "title": idea.get("title"),
            "concrete": idea.get("concrete") or idea.get("summary"),
            "url": idea.get("url"),
            "selected_as": idea.get("selected_as"),
        },
        "files": slice_files,
        "grok": {
            k: (grok_result or {}).get(k)
            for k in ("ok", "model", "returncode", "error")
        },
    }
    if scope_note:
        manifest.update(scope_note)
    (base / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    (base / "MANIFEST.md").write_text(
        "\n".join(
            [
                f"# Review pack — {sid}",
                "",
                f"- cycle: `{cycle_id}`",
                f"- source: `{idea.get('source')}`",
                f"- title: {idea.get('title')}",
                f"- concrete: {idea.get('concrete') or idea.get('summary')}",
                f"- url: {idea.get('url') or '—'}",
                "",
                "## Files in slice",
                "",
                *(
                    [f"- `{f}`" for f in slice_files]
                    if slice_files
                    else ["- (none detected)"]
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    (base / "DIFF.patch").write_text(diff_text or "(empty)", encoding="utf-8")
    (base / "CONTEXT.md").write_text(
        "\n".join(
            [
                "# Context for critics",
                "",
                "Grok (implementer) already applied this portfolio idea to the product tree.",
                "Your job is **critique only** — do not edit product `src/` yourself.",
                "Write concrete improvement suggestions: file, problem, suggested change, why better.",
                "Optional short code sketches belong under your `suggestions/` folder in prose/fenced blocks.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return base


def _scope_dna_for_prompt(scope_contract: Optional[dict[str, Any]]) -> str:
    if not scope_contract:
        return ""
    try:
        from . import scope_contract as sc

        return sc.format_dna_block(scope_contract)
    except Exception:
        return ""


def _critic_prompt(
    *,
    agent: str,
    idea: dict[str, Any],
    slice_files: list[str],
    diff_text: str,
    pack_rel: str,
    round_n: int,
    prior_fail_output: str = "",
    scope_contract: Optional[dict[str, Any]] = None,
) -> str:
    label = CRITIC_LABELS.get(agent, agent)
    fail_blk = ""
    if prior_fail_output:
        fail_blk = (
            f"\n## Failing tests (after synthesis attempt)\n```\n{prior_fail_output[-4000:]}\n```\n"
        )
    dna = _scope_dna_for_prompt(scope_contract)
    dna_blk = f"\n{dna}\n" if dna else ""
    return f"""You are {label} on the NEXUS product critique panel (round {round_n}).

Grok already implemented this portfolio slice. You do **NOT** edit the product tree.
You produce a structured critique that will be saved as markdown for Grok to read later.
{dna_blk}
## Idea
- id: {idea.get('id')}
- source: {idea.get('source')}
- title: {idea.get('title')}
- concrete: {idea.get('concrete') or idea.get('summary')}
- url: {idea.get('url')}

## Files in slice
{chr(10).join(f'- {f}' for f in slice_files) or '- (unknown)'}

## Diff / new code (bounded)
```
{diff_text[:50000]}
```
{fail_blk}
## Output format (markdown only)
# Critique from {label} on slice `{idea.get('id')}`

## Summary
(2-4 sentences)

## Findings
For each finding use:
### F{{n}} — <title>
- severity: blocker|major|minor|nit
- file: path
- problem: ...
- suggestion: If you do XYZ it would be better because ...
- sketch: optional short code fence (illustrative only)

## What is already good
- ...

## Priority order for Grok
1. ...
2. ...

Rules:
- Critique only; never claim you edited product files.
- Stay within the listed files when possible.
- Be specific and actionable.
- Pack path (product): `{pack_rel}`
"""


def collect_panel_critiques(
    root: Path,
    idea: dict[str, Any],
    *,
    pack_dir: Path,
    slice_files: list[str],
    diff_text: str,
    critics: tuple[str, ...] = DEFAULT_CRITICS,
    round_n: int = 1,
    prior_fail_output: str = "",
    bus: Any = None,
    timeout_s: float = DEFAULT_PANEL_TIMEOUT_S,
    message_fn: Optional[Callable[[str, str], str]] = None,
    parallel: bool = True,
    scope_contract: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Ask each critic independently (default: **in parallel**); write critiques/<agent>/critique.md."""
    root = _root(root)
    try:
        pack_rel = str(pack_dir.resolve().relative_to(root.resolve()))
    except ValueError:
        pack_rel = str(pack_dir)
    results: dict[str, Any] = {
        "round": round_n,
        "critics": {},
        "parallel": bool(parallel),
        "timeout_s": float(timeout_s),
    }

    def _send(agent: str, prompt: str) -> str:
        if message_fn is not None:
            return message_fn(agent, prompt)
        if bus is None:
            from .bus_client import BusClient

            # One client per call so parallel threads don't share state
            client = BusClient(timeout_s=timeout_s)
            return client.message(agent, prompt, timeout_ms=int(timeout_s * 1000))
        return bus.message(agent, prompt, timeout_ms=int(timeout_s * 1000))

    def _run_one(agent: str) -> dict[str, Any]:
        entry: dict[str, Any] = {"agent": agent, "ok": False}
        cdir = pack_dir / "critiques" / agent
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "suggestions").mkdir(exist_ok=True)
        prompt = _critic_prompt(
            agent=agent,
            idea=idea,
            slice_files=slice_files,
            diff_text=diff_text,
            pack_rel=pack_rel,
            round_n=round_n,
            prior_fail_output=prior_fail_output,
            scope_contract=scope_contract,
        )
        t0 = time.time()
        try:
            text = _send(agent, prompt)
            text = (text or "").strip()
            if not text:
                raise RuntimeError("empty critique")
            out = cdir / "critique.md"
            header = (
                f"<!-- agent={agent} round={round_n} ts={int(time.time())} "
                f"slice={_safe_slice_id(idea)} parallel={int(bool(parallel))} -->\n\n"
            )
            if not text.lstrip().startswith("#"):
                text = (
                    f"# Critique from {CRITIC_LABELS.get(agent, agent)} "
                    f"on slice `{idea.get('id')}`\n\n"
                    + text
                )
            out.write_text(header + text + "\n", encoding="utf-8")
            fences = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.S)
            for i, body in enumerate(fences[:8], 1):
                (cdir / "suggestions" / f"snippet_{i}.md").write_text(
                    f"```\n{body.strip()}\n```\n", encoding="utf-8"
                )
            entry["ok"] = True
            entry["path"] = str(out.relative_to(root))
            entry["chars"] = len(text)
            entry["elapsed_s"] = round(time.time() - t0, 1)
        except Exception as e:
            entry["error"] = str(e)[:500]
            entry["elapsed_s"] = round(time.time() - t0, 1)
            (cdir / "critique.md").write_text(
                f"# Critique from {CRITIC_LABELS.get(agent, agent)} — ERROR\n\n"
                f"Panel call failed: `{entry['error']}`\n",
                encoding="utf-8",
            )
        return entry

    agents = list(critics)
    if parallel and len(agents) > 1:
        # Fan-out: Claude / GPT / Antigravity at once (separate bridge files).
        with ThreadPoolExecutor(max_workers=len(agents)) as pool:
            futs = {pool.submit(_run_one, a): a for a in agents}
            for fut in as_completed(futs):
                agent = futs[fut]
                try:
                    results["critics"][agent] = fut.result()
                except Exception as e:
                    results["critics"][agent] = {
                        "agent": agent,
                        "ok": False,
                        "error": str(e)[:500],
                    }
    else:
        for agent in agents:
            results["critics"][agent] = _run_one(agent)

    results["ok"] = any(v.get("ok") for v in results["critics"].values())
    (pack_dir / f"PANEL_ROUND_{round_n}.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8"
    )
    return results


def _read_all_critiques(pack_dir: Path) -> str:
    parts: list[str] = []
    croot = pack_dir / "critiques"
    if not croot.is_dir():
        return "(no critiques)"
    for agent_dir in sorted(croot.iterdir()):
        if not agent_dir.is_dir():
            continue
        f = agent_dir / "critique.md"
        if f.is_file():
            parts.append(f"## File: critiques/{agent_dir.name}/critique.md\n\n")
            parts.append(f.read_text(encoding="utf-8", errors="replace")[:20000])
            parts.append("\n\n")
    return "".join(parts) or "(no critiques)"


def grok_synthesis(
    root: Path,
    idea: dict[str, Any],
    *,
    pack_dir: Path,
    slice_files: list[str],
    attempt: int,
    dry_run: bool = False,
    grok_fn: Optional[Callable[..., dict[str, Any]]] = None,
    scope_contract: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Grok reads critiques and optionally edits product code."""
    from . import grok_worker as gw

    root = _root(root)
    critiques = _read_all_critiques(pack_dir)
    syn_dir = pack_dir / "synthesis"
    syn_dir.mkdir(exist_ok=True)

    if dry_run:
        decisions = (
            f"# Synthesis decisions (DRY) — attempt {attempt}\n\n"
            f"Slice `{idea.get('id')}` — dry_run: no product edits.\n\n"
            "Would review critiques and selectively apply.\n"
        )
        (syn_dir / "decisions.md").write_text(decisions, encoding="utf-8")
        return {"ok": True, "dry_run": True, "decisions": str(syn_dir / "decisions.md")}

    dna = _scope_dna_for_prompt(scope_contract)
    dna_blk = f"\n{dna}\n" if dna else ""
    prompt = f"""You are GROK — synthesis editor for NEXUS product self-improve (attempt {attempt}/2).
{dna_blk}
Grok-implement already landed the portfolio idea below. A multi-LLM panel wrote critiques
(read-only). Your job: read the critiques, choose the best improvements, and apply them
to the **real product code** under this repo.

## Idea
- id: {idea.get('id')}
- title: {idea.get('title')}
- concrete: {idea.get('concrete') or idea.get('summary')}

## Files in original slice (prefer these)
{chr(10).join(f'- {f}' for f in slice_files) or '- (see git status)'}

## Panel critiques
{critiques[:60000]}

## Required outputs
1. Write `{(pack_dir / 'synthesis' / 'decisions.md').relative_to(root)}` listing each finding as
   ACCEPT / SKIP / DEFER with one-line reason.
2. Apply ACCEPT items to real code (src/tests). Small, tested changes only.
3. Do NOT force-push or commit secrets. Do NOT vendor whole upstream trees.
4. Run focused tests for touched modules when possible.
5. Prefer allowed_prefixes from the scope contract when present (advisory).

Working directory: {root}
"""
    fn = grok_fn or gw.grok_hard_improve
    # grok_hard_improve(root, goal) vs grok_prompt — use hard improve
    if grok_fn is not None:
        res = grok_fn(root, prompt)
    else:
        res = gw.grok_hard_improve(root, prompt)
    apply_log = syn_dir / "apply_log.md"
    apply_log.write_text(
        f"# Synthesis apply log — attempt {attempt}\n\n"
        f"- ok: {res.get('ok') if isinstance(res, dict) else res}\n"
        f"- model: {(res or {}).get('model') if isinstance(res, dict) else ''}\n"
        f"- error: {(res or {}).get('error') if isinstance(res, dict) else ''}\n\n"
        f"## Worker text (truncated)\n\n```\n"
        f"{str((res or {}).get('text') if isinstance(res, dict) else res)[:8000]}\n```\n",
        encoding="utf-8",
    )
    if not (syn_dir / "decisions.md").is_file():
        (syn_dir / "decisions.md").write_text(
            f"# Synthesis decisions — attempt {attempt}\n\n"
            "(Grok did not write decisions.md; see apply_log.md.)\n",
            encoding="utf-8",
        )
    return {
        "ok": bool(res.get("ok", True)) if isinstance(res, dict) else bool(res),
        "result": res if isinstance(res, dict) else {"raw": res},
        "decisions": str(syn_dir / "decisions.md"),
        "apply_log": str(apply_log),
        "attempt": attempt,
    }


def run_slice_critique_panel(
    root: Path,
    idea: dict[str, Any],
    *,
    before_status: str,
    after_status: str,
    grok_result: Optional[dict[str, Any]] = None,
    cycle_id: Optional[str] = None,
    dry_run: bool = False,
    critics: tuple[str, ...] = DEFAULT_CRITICS,
    max_fails: int = 2,
    panel_timeout_s: float = DEFAULT_PANEL_TIMEOUT_S,
    enabled: bool = True,
    bus: Any = None,
    message_fn: Optional[Callable[[str, str], str]] = None,
    grok_fn: Optional[Callable[..., dict[str, Any]]] = None,
    pytest_fn: Optional[Callable[..., dict[str, Any]]] = None,
    scope_contract: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Full per-slice panel → synthesis → retry → optional revert."""
    root = _root(root)
    if not enabled:
        return {"ok": True, "skipped": "panel_critique disabled"}

    env_off = (os.environ.get("NEXUS_PANEL_CRITIQUE") or "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    )
    if env_off:
        return {"ok": True, "skipped": "NEXUS_PANEL_CRITIQUE=0"}

    cycle_id = cycle_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    slice_files = list_slice_files(root, before_status=before_status, after_status=after_status)
    if not slice_files:
        # still allow critique on empty with status note
        slice_files = []

    diff_text = git_diff_for_files(root, slice_files) if slice_files else "(no slice files detected)"
    pack = write_review_pack(
        root,
        idea,
        cycle_id=cycle_id,
        slice_files=slice_files,
        diff_text=diff_text,
        grok_result=grok_result,
        scope_contract=scope_contract,
    )
    # Post-Grok baseline: implement slice only (not whole dirty tree).
    # after_status is porcelain right after Grok implement for this idea.
    post_grok_status = after_status if after_status is not None else git_status_porcelain(root)
    post_grok_snap = snapshot_paths(root, slice_files)

    out: dict[str, Any] = {
        "ok": False,
        "slice_id": _safe_slice_id(idea),
        "cycle_id": cycle_id,
        "pack": (
            str(pack.resolve().relative_to(root.resolve()))
            if str(pack.resolve()).startswith(str(root.resolve()))
            else str(pack)
        ),
        "files": slice_files,
        "slice_mode": "strict_delta",
        "dry_run": dry_run,
        "rounds": [],
        "status": "started",
    }

    # Always run panel round 1 (critiques only)
    r1 = collect_panel_critiques(
        root,
        idea,
        pack_dir=pack,
        slice_files=slice_files,
        diff_text=diff_text,
        critics=critics,
        round_n=1,
        bus=bus,
        timeout_s=panel_timeout_s,
        message_fn=message_fn,
        scope_contract=scope_contract,
    )
    out["rounds"].append({"panel": r1})

    if dry_run:
        grok_synthesis(
            root,
            idea,
            pack_dir=pack,
            slice_files=slice_files,
            attempt=1,
            dry_run=True,
            grok_fn=grok_fn,
            scope_contract=scope_contract,
        )
        out["ok"] = True
        out["status"] = "dry_critiques_only"
        (pack / "STATUS.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        return out

    if not r1.get("ok"):
        out["status"] = "panel_round1_failed"
        out["ok"] = True  # don't fail whole portfolio if panel offline
        out["note"] = "no successful critiques; skipped synthesis"
        (pack / "STATUS.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        return out

    py_fn = pytest_fn or run_pytest_slice
    fails = 0
    for attempt in range(1, max_fails + 1):
        syn = grok_synthesis(
            root,
            idea,
            pack_dir=pack,
            slice_files=slice_files,
            attempt=attempt,
            dry_run=False,
            grok_fn=grok_fn,
            scope_contract=scope_contract,
        )
        # Implement slice + synthesis delta only (not whole dirty tree)
        scope2 = expand_snapshot_scope(
            root, slice_files, baseline_status=post_grok_status
        )
        test = py_fn(root, scope2)
        round_rec = {"synthesis": syn, "tests": test, "attempt": attempt, "scope": scope2}
        out["rounds"].append(round_rec)
        if test.get("ok"):
            out["ok"] = True
            out["status"] = "synthesis_ok" if attempt == 1 else "synthesis_ok_after_retry"
            (pack / "STATUS.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
            return out
        fails += 1
        if attempt >= max_fails:
            break
        # Panel round 2 with failure context + current diff (synthesis scope only)
        diff2 = git_diff_for_files(root, scope2)
        r2 = collect_panel_critiques(
            root,
            idea,
            pack_dir=pack,
            slice_files=scope2,
            diff_text=diff2,
            critics=critics,
            round_n=2,
            prior_fail_output=str(test.get("output") or test.get("error") or ""),
            bus=bus,
            timeout_s=panel_timeout_s,
            message_fn=message_fn,
            scope_contract=scope_contract,
        )
        out["rounds"].append({"panel": r2})

    # Revert synthesis only → post-Grok implement snapshot (leave pre-dirty alone)
    restored = restore_post_grok_after_failed_synthesis(
        root,
        post_grok_snap=post_grok_snap,
        post_grok_status=post_grok_status,
    )
    out["ok"] = False
    out["status"] = "synthesis_reverted"
    out["restored"] = restored
    out["fails"] = fails
    (pack / "synthesis" / "REVERTED.md").write_text(
        f"# Synthesis reverted\n\nAfter {fails} red test round(s), "
        f"restored post-Grok implement snapshot (synthesis-only; "
        f"pre-existing dirty paths outside slice left alone).\n\n"
        f"Restored paths ({len(restored)}):\n"
        + "\n".join(f"- `{p}`" for p in restored[:200])
        + "\n",
        encoding="utf-8",
    )
    (pack / "STATUS.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


def new_cycle_id() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:6]
