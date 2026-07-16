#!/usr/bin/env python3
"""Full SWE-bench Pro suite: Grok CLI *subscription* agent + official Docker eval.

Uses grok.com subscription (OIDC) — NEVER the XAI_API_KEY API billing path.
Strips XAI_API_KEY / OPENAI_API_KEY from the Grok child env unless
NEXUS_GROK_USE_API=1 is explicitly set.

  # Solve all 731 instances (subscription Grok)
  PYTHONPATH=src python3 scripts/swe_pro_full_suite.py solve --workers 1

  # Official harness on whatever patches we have so far
  PYTHONPATH=src python3 scripts/swe_pro_full_suite.py eval --num-workers 2

  # Continuous: solve loop + periodic eval
  PYTHONPATH=src python3 scripts/swe_pro_full_suite.py run --workers 1 --num-workers 2
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
PRO_OS = Path(os.environ.get("SWE_PRO_OS", Path.home() / "SWE-bench_Pro-os"))
OUT = Path(os.environ.get("SWE_PRO_FULL_OUT", ROOT / ".nexus_state" / "swe_pro" / "full"))
META = OUT / "instances_meta.jsonl"
RAW = OUT / "raw_samples_full.jsonl"
REPOS = OUT / "repos"
WORK = OUT / "agent_workspaces"
PREDS_DIR = OUT / "preds"
PATCHES_JSON = OUT / "agent_patches_full.json"
LOG = OUT / "logs" / "full_suite.log"
SCOREBOARD = OUT / "SCOREBOARD.json"

DEFAULT_MODEL = os.environ.get("NEXUS_GROK_MODEL", "grok-4.5")
DEFAULT_EFFORT = os.environ.get("NEXUS_GROK_REASONING_EFFORT", "high")
LOCK = threading.Lock()


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_meta() -> list[dict[str, Any]]:
    if not META.is_file():
        raise SystemExit(f"Missing {META} — export dataset first")
    rows = []
    with META.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def subscription_env() -> dict[str, str]:
    """Child env for Grok CLI: force subscription, strip API billing keys."""
    env = os.environ.copy()
    # User mandate: use Grok subscription, not API credits
    for k in (
        "XAI_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "XAI_BASE_URL",
    ):
        env.pop(k, None)
    env["NEXUS_GROK_USE_API"] = "0"
    # Avoid accidental litellm/openai fallthrough
    env.pop("LITELLM_API_KEY", None)
    return env


def run_grok_subscription(
    prompt: str,
    *,
    cwd: Path,
    model: str,
    effort: str,
    max_turns: int,
    timeout_s: float,
) -> tuple[int, str, str]:
    """Invoke headless Grok CLI on subscription auth only."""
    effort_map = {
        "max": "xhigh",
        "ultra": "xhigh",
        "xhigh": "xhigh",
        "high": "high",
        "medium": "medium",
        "low": "low",
        "minimal": "minimal",
        "none": "none",
    }
    eff = effort_map.get(effort.strip().lower(), "high")
    cmd = [
        "grok",
        "-p",
        prompt,
        "-m",
        model,
        "--cwd",
        str(cwd),
        "--max-turns",
        str(max_turns),
        "--output-format",
        "plain",
        "--always-approve",
        "--no-plan",
        "--reasoning-effort",
        eff,
        "--disable-web-search",
    ]
    env = subscription_env()
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            cwd=str(cwd),
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else "timeout"
        return 124, out, err


def ensure_repo(repo: str) -> Path:
    """Mirror-clone GitHub repo once under OUT/repos."""
    REPOS.mkdir(parents=True, exist_ok=True)
    name = repo.replace("/", "__")
    dest = REPOS / name
    if (dest / ".git").exists():
        return dest
    url = f"https://github.com/{repo}.git"
    _log(f"cloning {repo} → {dest}")
    # Shallow not enough (need arbitrary base commits) — full clone
    subprocess.run(
        ["git", "clone", "--filter=blob:none", url, str(dest)],
        check=True,
        timeout=3600,
    )
    return dest


def prepare_worktree(row: dict[str, Any]) -> Path:
    """Detach worktree at base_commit for this instance."""
    iid = row["instance_id"]
    repo = row["repo"]
    base = row["base_commit"]
    mirror = ensure_repo(repo)
    wt = WORK / iid
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    # fetch commit if missing
    subprocess.run(
        ["git", "fetch", "--depth=1", "origin", base],
        cwd=str(mirror),
        capture_output=True,
        timeout=600,
    )
    # try worktree; fall back to clone + checkout
    r = subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt), base],
        cwd=str(mirror),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if r.returncode != 0:
        # deepen history for this commit
        subprocess.run(
            ["git", "fetch", "origin", base],
            cwd=str(mirror),
            capture_output=True,
            timeout=1800,
        )
        r2 = subprocess.run(
            ["git", "worktree", "add", "--detach", str(wt), base],
            cwd=str(mirror),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r2.returncode != 0:
            # last resort: temporary checkout clone
            if wt.exists():
                shutil.rmtree(wt, ignore_errors=True)
            subprocess.run(
                ["git", "clone", "--no-checkout", str(mirror), str(wt)],
                check=True,
                timeout=600,
            )
            subprocess.run(
                ["git", "checkout", base],
                cwd=str(wt),
                check=True,
                capture_output=True,
                timeout=300,
            )
    return wt


def build_prompt(row: dict[str, Any]) -> str:
    ps = row.get("problem_statement") or ""
    req = row.get("requirements") or ""
    iface = row.get("interface") or ""
    tests = row.get("fail_to_pass") or ""
    files = row.get("selected_test_files_to_run") or ""
    return f"""You are solving a SWE-bench Pro instance. Implement a correct patch in this repo working tree.

## Instance
- instance_id: {row['instance_id']}
- repo: {row['repo']}
- base_commit: {row['base_commit']}

## Problem statement
{ps}

## Requirements
{req}

## Interface (APIs you must implement / respect)
{iface}

## Fail-to-pass tests (must pass after your change)
{tests}

## Related test files (do NOT edit tests unless absolutely required; prefer production code)
{files}

## Instructions
1. Explore the codebase with shell/tools; find the right files.
2. Implement the minimal correct fix in source code (not test files when possible).
3. Keep changes focused and consistent with project style.
4. When done, ensure `git diff` shows your full fix as a unified diff against HEAD.
5. Do not commit. Do not push. Do not modify unrelated files.

Work until the implementation is complete.
"""


def git_diff(cwd: Path) -> str:
    subprocess.run(["git", "add", "-A"], cwd=str(cwd), capture_output=True, timeout=60)
    # staged+unstaged unified diff vs original HEAD
    r = subprocess.run(
        ["git", "diff", "--cached", "HEAD"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )
    diff = r.stdout or ""
    if not diff.strip():
        r2 = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )
        diff = r2.stdout or ""
    # unstage so tree stays clean for re-runs
    subprocess.run(["git", "reset", "HEAD"], cwd=str(cwd), capture_output=True, timeout=60)
    return diff


def load_patches() -> list[dict[str, Any]]:
    if PATCHES_JSON.is_file():
        return json.loads(PATCHES_JSON.read_text())
    return []


def save_patch(instance_id: str, patch: str, meta: dict[str, Any]) -> None:
    with LOCK:
        patches = load_patches()
        patches = [p for p in patches if p.get("instance_id") != instance_id]
        patches.append(
            {
                "instance_id": instance_id,
                "patch": patch,
                "prefix": "nexus-grok-sub",
                "model_name_or_path": meta.get("model", DEFAULT_MODEL),
                "auth": "grok_subscription",
                **{k: meta[k] for k in ("rc", "seconds", "patch_bytes") if k in meta},
            }
        )
        PATCHES_JSON.write_text(json.dumps(patches, indent=2) + "\n")
        # also per-instance pred
        PREDS_DIR.mkdir(parents=True, exist_ok=True)
        (PREDS_DIR / f"{instance_id}.json").write_text(
            json.dumps(
                {
                    "instance_id": instance_id,
                    "model_patch": patch,
                    "model_name_or_path": meta.get("model", DEFAULT_MODEL),
                },
                indent=2,
            )
            + "\n"
        )


def already_solved() -> set[str]:
    done = set()
    for p in load_patches():
        if (p.get("patch") or "").strip():
            done.add(p["instance_id"])
    for f in PREDS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            if (d.get("model_patch") or d.get("patch") or "").strip():
                done.add(d.get("instance_id") or f.stem)
        except Exception:
            pass
    return done


def solve_one(
    row: dict[str, Any],
    *,
    model: str,
    effort: str,
    max_turns: int,
    timeout_s: float,
    keep_workspace: bool,
) -> dict[str, Any]:
    iid = row["instance_id"]
    t0 = time.time()
    _log(f"SOLVE start {iid}")
    try:
        wt = prepare_worktree(row)
        prompt = build_prompt(row)
        rc, stdout, stderr = run_grok_subscription(
            prompt,
            cwd=wt,
            model=model,
            effort=effort,
            max_turns=max_turns,
            timeout_s=timeout_s,
        )
        patch = git_diff(wt)
        # sometimes agent writes patch file
        if not patch.strip():
            for cand in wt.glob("*.diff"):
                patch = cand.read_text()
                if patch.strip():
                    break
        meta = {
            "model": model,
            "rc": rc,
            "seconds": round(time.time() - t0, 1),
            "patch_bytes": len(patch),
        }
        save_patch(iid, patch, meta)
        # log tail
        (OUT / "logs" / f"{iid}.log").write_text(
            f"rc={rc}\nseconds={meta['seconds']}\n---stdout---\n{stdout[-20000:]}\n---stderr---\n{stderr[-10000:]}\n"
        )
        if not keep_workspace:
            # remove worktree
            mirror = REPOS / row["repo"].replace("/", "__")
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt)],
                cwd=str(mirror),
                capture_output=True,
                timeout=120,
            )
            shutil.rmtree(wt, ignore_errors=True)
        status = "ok" if patch.strip() else "empty_patch"
        _log(f"SOLVE {status} {iid} bytes={len(patch)} rc={rc} t={meta['seconds']}s")
        return {"instance_id": iid, "status": status, **meta}
    except Exception as e:
        _log(f"SOLVE FAIL {iid}: {e!r}")
        save_patch(iid, "", {"model": model, "rc": -1, "seconds": round(time.time() - t0, 1), "patch_bytes": 0, "error": str(e)})
        return {"instance_id": iid, "status": "error", "error": str(e)}


def cmd_solve(args: argparse.Namespace) -> int:
    rows = load_meta()
    done = already_solved() if not args.redo else set()
    todo = [r for r in rows if r["instance_id"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    if args.filter:
        rx = re.compile(args.filter)
        todo = [r for r in todo if rx.search(r["instance_id"])]
    _log(f"solve queue={len(todo)} already_done={len(done)} workers={args.workers} model={args.model} auth=subscription")
    if not todo:
        _log("nothing to solve")
        return 0

    # Pre-clone unique repos serially (avoids race)
    for repo in sorted({r["repo"] for r in todo}):
        try:
            ensure_repo(repo)
        except Exception as e:
            _log(f"clone failed {repo}: {e}")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(
                solve_one,
                row,
                model=args.model,
                effort=args.effort,
                max_turns=args.max_turns,
                timeout_s=args.timeout,
                keep_workspace=args.keep_workspace,
            ): row["instance_id"]
            for row in todo
        }
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                _log(f"worker crash {futs[fut]}: {e}")
    nonempty = sum(1 for r in results if r.get("status") == "ok")
    _log(f"solve batch done: {nonempty}/{len(results)} nonempty patches; total saved={len(load_patches())}")
    write_scoreboard_partial()
    return 0


def write_scoreboard_partial() -> None:
    patches = load_patches()
    nonempty = sum(1 for p in patches if (p.get("patch") or "").strip())
    sb = {
        "benchmark": "ScaleAI/SWE-bench_Pro full suite (n=731)",
        "agent": "grok-cli-subscription",
        "model": DEFAULT_MODEL,
        "auth": "grok.com subscription (no XAI_API_KEY)",
        "patches_total": len(patches),
        "patches_nonempty": nonempty,
        "eval": None,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if (OUT / "eval_out" / "eval_results.json").is_file():
        try:
            ev = json.loads((OUT / "eval_out" / "eval_results.json").read_text())
            if isinstance(ev, dict):
                resolved = sum(1 for v in ev.values() if v is True)
                total = len(ev)
                sb["eval"] = {
                    "resolved": resolved,
                    "total": total,
                    "accuracy": (resolved / total) if total else None,
                }
        except Exception:
            pass
    SCOREBOARD.write_text(json.dumps(sb, indent=2) + "\n")
    (OUT / "SCOREBOARD.md").write_text(
        f"""# SWE-bench Pro FULL suite

| Metric | Value |
|--------|-------|
| Instances | 731 |
| Agent | Grok CLI **subscription** (no API key) |
| Model | `{DEFAULT_MODEL}` |
| Patches nonempty | {nonempty}/{len(patches)} |
| Official eval | {json.dumps(sb.get('eval'))} |

Updated: {sb['updated']}
"""
    )


def cmd_eval(args: argparse.Namespace) -> int:
    patches = [p for p in load_patches() if (p.get("patch") or "").strip()]
    if not patches:
        _log("no nonempty patches to eval")
        return 1
    patch_path = OUT / "agent_patches_eval.json"
    # harness format
    payload = [
        {"instance_id": p["instance_id"], "patch": p["patch"], "prefix": p.get("prefix") or "nexus-grok-sub"}
        for p in patches
    ]
    patch_path.write_text(json.dumps(payload, indent=2) + "\n")
    if not RAW.is_file():
        _log(f"missing {RAW}")
        return 1
    out_dir = OUT / "eval_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PRO_OS / ".venv" / "bin" / "python"),
        str(PRO_OS / "swe_bench_pro_eval.py"),
        f"--raw_sample_path={RAW}",
        f"--patch_path={patch_path}",
        f"--output_dir={out_dir}",
        "--scripts_dir=run_scripts",
        f"--num_workers={args.num_workers}",
        "--dockerhub_username=jefzda",
        "--use_local_docker",
        "--docker_platform=linux/amd64",
    ]
    if args.redo:
        cmd.append("--redo")
    _log(f"official eval n={len(payload)} workers={args.num_workers}")
    env = os.environ.copy()
    p = subprocess.run(cmd, cwd=str(PRO_OS), env=env)
    write_scoreboard_partial()
    res = out_dir / "eval_results.json"
    if res.is_file():
        ev = json.loads(res.read_text())
        if isinstance(ev, dict):
            resolved = sum(1 for v in ev.values() if v is True)
            _log(f"EVAL accuracy {resolved}/{len(ev)} = {resolved/len(ev):.4f}")
    return p.returncode


def cmd_run(args: argparse.Namespace) -> int:
    """Solve all, then eval (and optional loop)."""
    rc = cmd_solve(args)
    if args.skip_eval:
        return rc
    return cmd_eval(args)


def cmd_status(_: argparse.Namespace) -> int:
    write_scoreboard_partial()
    print(SCOREBOARD.read_text() if SCOREBOARD.is_file() else "{}")
    patches = load_patches()
    print(f"patches: {len(patches)} nonempty={sum(1 for p in patches if (p.get('patch') or '').strip())}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Full SWE-bench Pro suite (Grok subscription)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_solve_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--workers", type=int, default=1)
        p.add_argument("--model", default=DEFAULT_MODEL)
        p.add_argument("--effort", default=DEFAULT_EFFORT)
        p.add_argument("--max-turns", type=int, default=int(os.environ.get("NEXUS_GROK_BRIDGE_TURNS") or 40))
        p.add_argument("--timeout", type=float, default=float(os.environ.get("NEXUS_CLI_TIMEOUT_S") or 900))
        p.add_argument("--limit", type=int, default=0, help="Max instances this run (0=all)")
        p.add_argument("--filter", default="", help="Regex on instance_id")
        p.add_argument("--redo", action="store_true")
        p.add_argument("--keep-workspace", action="store_true")

    p_solve = sub.add_parser("solve", help="Generate agent patches with Grok subscription")
    add_solve_args(p_solve)
    p_solve.set_defaults(func=cmd_solve)

    p_eval = sub.add_parser("eval", help="Official Docker harness on saved patches")
    p_eval.add_argument("--num-workers", type=int, default=2)
    p_eval.add_argument("--redo", action="store_true")
    p_eval.set_defaults(func=cmd_eval)

    p_run = sub.add_parser("run", help="Solve then eval")
    add_solve_args(p_run)
    p_run.add_argument("--num-workers", type=int, default=2)
    p_run.add_argument("--skip-eval", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_st = sub.add_parser("status", help="Print scoreboard")
    p_st.set_defaults(func=cmd_status)

    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
