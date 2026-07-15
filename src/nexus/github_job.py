"""GitHub URL → clone → understand → install → run → fix loop.

Zero-friction path for "paste a repo, make it work."
Heuristic-first; uses bus agents when online for analysis and patches.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


# --- URL / clone -----------------------------------------------------------------

_GITHUB_RE = re.compile(
    r"""(?ix)
    ^(?:https?://)?(?:www\.)?github\.com/
    (?P<owner>[A-Za-z0-9_.-]+)/
    (?P<repo>[A-Za-z0-9_.-]+?)
    (?:\.git)?/?$
    """
)
_SLUG_RE = re.compile(r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)$")


@dataclass
class RepoRef:
    owner: str
    repo: str
    clone_url: str
    https_url: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_github_ref(raw: str) -> RepoRef:
    """Accept full URLs, git@, or owner/repo."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("empty GitHub reference")

    # git@github.com:owner/repo.git
    m = re.match(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", s)
    if m:
        owner, repo = m.group("owner"), m.group("repo")
        return RepoRef(
            owner=owner,
            repo=repo.removesuffix(".git"),
            clone_url=f"https://github.com/{owner}/{repo.removesuffix('.git')}.git",
            https_url=f"https://github.com/{owner}/{repo.removesuffix('.git')}",
        )

    m = _GITHUB_RE.match(s.rstrip("/"))
    if not m:
        m = _SLUG_RE.match(s)
    if not m:
        raise ValueError(
            f"not a GitHub URL or owner/repo slug: {raw!r}\n"
            "  examples: https://github.com/owner/repo  |  owner/repo"
        )
    owner, repo = m.group("owner"), m.group("repo").removesuffix(".git")
    return RepoRef(
        owner=owner,
        repo=repo,
        clone_url=f"https://github.com/{owner}/{repo}.git",
        https_url=f"https://github.com/{owner}/{repo}",
    )


def _run(
    cmd: list[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
    timeout: float = 600,
) -> dict[str, Any]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=full_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "cwd": str(cwd) if cwd else None,
            "returncode": p.returncode,
            "stdout": (p.stdout or "")[-8000:],
            "stderr": (p.stderr or "")[-8000:],
            "ok": p.returncode == 0,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "cmd": cmd,
            "cwd": str(cwd) if cwd else None,
            "returncode": -1,
            "stdout": (e.stdout or "")[-4000:] if isinstance(e.stdout, str) else "",
            "stderr": f"timeout after {timeout}s",
            "ok": False,
        }
    except FileNotFoundError as e:
        return {
            "cmd": cmd,
            "cwd": str(cwd) if cwd else None,
            "returncode": 127,
            "stdout": "",
            "stderr": str(e),
            "ok": False,
        }


# --- project detection ------------------------------------------------------------

@dataclass
class ProjectProfile:
    root: str
    languages: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    install_cmds: list[list[str]] = field(default_factory=list)
    check_cmds: list[list[str]] = field(default_factory=list)
    run_cmds: list[list[str]] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    readme_summary: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_text(path: Path, limit: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def detect_project(root: Path) -> ProjectProfile:
    root = root.resolve()
    prof = ProjectProfile(root=str(root))
    files = {p.name for p in root.iterdir() if p.is_file()} if root.is_dir() else set()

    readme = None
    for name in ("README.md", "README.rst", "README", "readme.md"):
        if (root / name).is_file():
            readme = root / name
            break
    if readme:
        text = _read_text(readme, 4000)
        prof.readme_summary = text[:1500]
        # crude goal hints from README headings
        for line in text.splitlines()[:40]:
            if line.strip().startswith("#"):
                prof.entrypoints.append(line.strip()[:120])

    # Python
    if "pyproject.toml" in files or "setup.py" in files or "requirements.txt" in files:
        prof.languages.append("python")
        prof.package_managers.append("pip")
        if "pyproject.toml" in files or "setup.py" in files:
            prof.install_cmds.append(["python3", "-m", "pip", "install", "-e", ".[dev]"])
            prof.install_cmds.append(["python3", "-m", "pip", "install", "-e", "."])
        if "requirements.txt" in files:
            prof.install_cmds.append(
                ["python3", "-m", "pip", "install", "-r", "requirements.txt"]
            )
        if "requirements-dev.txt" in files:
            prof.install_cmds.append(
                ["python3", "-m", "pip", "install", "-r", "requirements-dev.txt"]
            )
        # checks
        if (root / "tests").is_dir() or (root / "test").is_dir() or any(
            root.glob("test_*.py")
        ):
            prof.check_cmds.append(["python3", "-m", "pytest", "-q"])
        if "Makefile" in files:
            mk = _read_text(root / "Makefile", 3000)
            if re.search(r"(?m)^test:", mk):
                prof.check_cmds.insert(0, ["make", "test"])
            if re.search(r"(?m)^install:", mk):
                prof.install_cmds.insert(0, ["make", "install"])
        # common run
        if "manage.py" in files:
            prof.run_cmds.append(["python3", "manage.py", "check"])
        for cand in ("main.py", "app.py", "src/main.py"):
            if (root / cand).is_file():
                prof.run_cmds.append(["python3", cand])
                prof.entrypoints.append(cand)

    # Node
    if "package.json" in files:
        prof.languages.append("javascript")
        pkg = {}
        try:
            pkg = json.loads(_read_text(root / "package.json", 50000))
        except Exception:
            pass
        scripts = pkg.get("scripts") or {}
        lock_npm = (root / "package-lock.json").is_file()
        lock_yarn = (root / "yarn.lock").is_file()
        lock_pnpm = (root / "pnpm-lock.yaml").is_file()
        if lock_pnpm:
            prof.package_managers.append("pnpm")
            prof.install_cmds.append(["pnpm", "install"])
        elif lock_yarn:
            prof.package_managers.append("yarn")
            prof.install_cmds.append(["yarn", "install"])
        else:
            prof.package_managers.append("npm")
            prof.install_cmds.append(["npm", "install"])
            if not lock_npm:
                prof.notes.append("no package-lock.json — using npm install")
        for key in ("test", "lint", "typecheck", "build", "check"):
            if key in scripts:
                runner = "pnpm" if lock_pnpm else ("yarn" if lock_yarn else "npm")
                if runner == "npm":
                    prof.check_cmds.append(["npm", "run", key])
                else:
                    prof.check_cmds.append([runner, key] if key != "test" else [runner, "test"])
        if "start" in scripts:
            prof.run_cmds.append(
                ["npm", "start"] if not lock_pnpm and not lock_yarn else (
                    ["pnpm", "start"] if lock_pnpm else ["yarn", "start"]
                )
            )
        if "dev" in scripts and "start" not in scripts:
            prof.notes.append("has npm run dev (long-running — not auto-started)")

    # Go
    if "go.mod" in files:
        prof.languages.append("go")
        prof.package_managers.append("go")
        prof.install_cmds.append(["go", "mod", "download"])
        prof.check_cmds.append(["go", "test", "./..."])
        prof.run_cmds.append(["go", "build", "./..."])

    # Rust
    if "Cargo.toml" in files:
        prof.languages.append("rust")
        prof.package_managers.append("cargo")
        prof.install_cmds.append(["cargo", "fetch"])
        prof.check_cmds.append(["cargo", "test"])
        prof.check_cmds.append(["cargo", "build"])

    # Docker (info only — do not auto-run compose without flag)
    if "docker-compose.yml" in files or "compose.yml" in files:
        prof.notes.append("Docker Compose present — not auto-started (use --with-docker later)")

    if not prof.install_cmds and not prof.check_cmds:
        prof.notes.append("unknown stack — will inventory files and ask agents for a plan")
        # still list top-level files as entrypoints
        prof.entrypoints.extend(sorted(files)[:20])

    # de-dupe commands
    def dedupe(cmds: list[list[str]]) -> list[list[str]]:
        seen = set()
        out = []
        for c in cmds:
            key = tuple(c)
            if key not in seen:
                seen.add(key)
                out.append(c)
        return out

    prof.install_cmds = dedupe(prof.install_cmds)
    prof.check_cmds = dedupe(prof.check_cmds)
    prof.run_cmds = dedupe(prof.run_cmds)
    return prof


# --- job state --------------------------------------------------------------------

@dataclass
class GithubJob:
    job_id: str
    ref: dict[str, str]
    goal: str
    work_dir: str
    status: str = "pending"  # pending|running|completed|failed
    phase: str = "init"
    profile: dict[str, Any] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    fix_rounds: int = 0
    max_fix_rounds: int = 3
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GithubJob":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class GithubJobRunner:
    """Orchestrates clone → detect → install → check → agent fix → report."""

    def __init__(
        self,
        *,
        workspace_root: Optional[Path] = None,
        state_dir: Optional[Path] = None,
        panel: Any = None,
        auto_start_stack: bool = True,
    ):
        self.repo_root = Path(__file__).resolve().parents[2]
        self.workspace_root = Path(
            workspace_root or self.repo_root / ".nexus_workspaces"
        )
        self.state_dir = Path(state_dir or self.repo_root / ".nexus_state" / "github_jobs")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.panel = panel
        self.auto_start_stack = auto_start_stack

    def _job_path(self, job_id: str) -> Path:
        return self.state_dir / f"{job_id}.json"

    def save(self, job: GithubJob) -> None:
        job.touch()
        self._job_path(job.job_id).write_text(
            json.dumps(job.to_dict(), indent=2), encoding="utf-8"
        )

    def load(self, job_id: str) -> GithubJob:
        return GithubJob.from_dict(
            json.loads(self._job_path(job_id).read_text(encoding="utf-8"))
        )

    def log(self, job: GithubJob, event: str, **data: Any) -> None:
        entry = {"ts": time.time(), "event": event, **data}
        job.log.append(entry)
        # keep log bounded
        if len(job.log) > 200:
            job.log = job.log[-200:]
        print(f"  [{job.phase}] {event}" + (f"  {data}" if data else ""))
        self.save(job)

    def create(self, github: str, *, goal: str = "", job_id: Optional[str] = None) -> GithubJob:
        ref = parse_github_ref(github)
        jid = job_id or f"gh-{ref.owner}-{ref.repo}-{uuid.uuid4().hex[:8]}"
        work = self.workspace_root / f"{ref.owner}__{ref.repo}"
        goal = (goal or "").strip() or (
            f"Clone {ref.slug}, install dependencies, run tests/checks, "
            "fix failures, and leave the project working."
        )
        job = GithubJob(
            job_id=jid,
            ref={
                "owner": ref.owner,
                "repo": ref.repo,
                "clone_url": ref.clone_url,
                "https_url": ref.https_url,
                "slug": ref.slug,
            },
            goal=goal,
            work_dir=str(work),
            max_fix_rounds=3,
        )
        self.save(job)
        return job

    # --- phases ---

    def phase_clone(self, job: GithubJob) -> bool:
        job.phase = "clone"
        self.save(job)
        work = Path(job.work_dir)
        if (work / ".git").is_dir():
            self.log(job, "already_cloned", path=str(work))
            # refresh
            r = _run(["git", "pull", "--ff-only"], cwd=work, timeout=120)
            job.results["pull"] = {
                "ok": r["ok"],
                "returncode": r["returncode"],
                "stderr": r["stderr"][-500:],
            }
            self.save(job)
            return True
        if work.exists() and any(work.iterdir()):
            self.log(job, "work_dir_nonempty_reusing", path=str(work))
            return True
        work.parent.mkdir(parents=True, exist_ok=True)
        self.log(job, "cloning", url=job.ref["clone_url"], dest=str(work))
        r = _run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                job.ref["clone_url"],
                str(work),
            ],
            timeout=300,
        )
        job.results["clone"] = {
            "ok": r["ok"],
            "returncode": r["returncode"],
            "stderr": r["stderr"][-800:],
        }
        self.save(job)
        if not r["ok"]:
            self.log(job, "clone_failed", stderr=r["stderr"][-400:])
            return False
        self.log(job, "cloned_ok")
        return True

    def phase_detect(self, job: GithubJob) -> ProjectProfile:
        job.phase = "detect"
        self.save(job)
        prof = detect_project(Path(job.work_dir))
        job.profile = prof.to_dict()
        self.log(
            job,
            "detected",
            languages=prof.languages,
            package_managers=prof.package_managers,
            install=len(prof.install_cmds),
            checks=len(prof.check_cmds),
        )
        # optional agent plan
        plan = self._agent_plan(job, prof)
        if plan:
            job.results["agent_plan"] = plan
            # merge agent-suggested commands if they look safe
            for key, dest in (
                ("install_cmds", "install_cmds"),
                ("check_cmds", "check_cmds"),
            ):
                extra = plan.get(key) or []
                for c in extra:
                    if isinstance(c, list) and c and _cmd_allowed(c):
                        if c not in getattr(prof, dest):
                            getattr(prof, dest).append(c)
            job.profile = prof.to_dict()
            self.save(job)
        return prof

    def phase_install(self, job: GithubJob, prof: ProjectProfile) -> bool:
        job.phase = "install"
        self.save(job)
        work = Path(job.work_dir)
        results = []
        any_ok = not prof.install_cmds  # nothing to install counts as ok
        for cmd in prof.install_cmds:
            if not _cmd_allowed(cmd):
                self.log(job, "install_skipped_unsafe", cmd=cmd)
                continue
            self.log(job, "install_run", cmd=cmd)
            # prefer project venv for python pip
            env = None
            r = _run(cmd, cwd=work, env=env, timeout=900)
            results.append(
                {
                    "cmd": cmd,
                    "ok": r["ok"],
                    "returncode": r["returncode"],
                    "stderr_tail": r["stderr"][-600:],
                    "stdout_tail": r["stdout"][-400:],
                }
            )
            if r["ok"]:
                any_ok = True
                # if editable install failed with extras, next cmd may work
                if cmd[:4] == ["python3", "-m", "pip", "install"] and "-e" in cmd:
                    break
            # pip install -e ".[dev]" often fails if no extras — continue
        job.results["install"] = results
        self.save(job)
        if not any_ok and prof.install_cmds:
            self.log(job, "install_all_failed")
            return False
        self.log(job, "install_done", ok=any_ok)
        return True

    def phase_check(self, job: GithubJob, prof: ProjectProfile) -> dict[str, Any]:
        job.phase = "check"
        self.save(job)
        work = Path(job.work_dir)
        results = []
        all_ok = True
        if not prof.check_cmds:
            # inventory only
            listing = _run(["find", ".", "-maxdepth", "2", "-type", "f"], cwd=work, timeout=30)
            results.append(
                {
                    "cmd": ["inventory"],
                    "ok": True,
                    "stdout_tail": listing.get("stdout", "")[:1500],
                    "note": "no automatic check commands detected",
                }
            )
            job.results["checks"] = results
            self.save(job)
            return {"ok": True, "results": results, "empty": True}

        for cmd in prof.check_cmds:
            if not _cmd_allowed(cmd):
                continue
            self.log(job, "check_run", cmd=cmd)
            r = _run(cmd, cwd=work, timeout=900)
            entry = {
                "cmd": cmd,
                "ok": r["ok"],
                "returncode": r["returncode"],
                "stdout_tail": r["stdout"][-1500:],
                "stderr_tail": r["stderr"][-1500:],
            }
            results.append(entry)
            if not r["ok"]:
                all_ok = False
                # try next alternative (e.g. make test vs pytest)
            else:
                # one green check is enough if we only needed one
                break
        # if we broke on first success, mark remaining skipped; if all failed, all_ok False
        if any(x["ok"] for x in results):
            all_ok = True
        job.results["checks"] = results
        self.save(job)
        self.log(job, "check_done", ok=all_ok, n=len(results))
        return {"ok": all_ok, "results": results, "empty": False}

    def phase_fix(self, job: GithubJob, prof: ProjectProfile, check: dict[str, Any]) -> bool:
        """Ask agents for patches / commands, apply safely, re-check."""
        job.phase = "fix"
        job.fix_rounds += 1
        self.save(job)
        if job.fix_rounds > job.max_fix_rounds:
            self.log(job, "fix_budget_exhausted")
            return False

        failures = [
            r for r in (check.get("results") or []) if not r.get("ok")
        ]
        proposal = self._agent_fix(job, prof, failures)
        job.results.setdefault("fixes", []).append(
            {"round": job.fix_rounds, "proposal": proposal}
        )
        self.save(job)

        applied = 0
        work = Path(job.work_dir)
        # Apply file writes (jail under work dir)
        for f in proposal.get("files") or []:
            if not isinstance(f, dict):
                continue
            rel = str(f.get("path") or "").lstrip("/")
            content = f.get("content")
            if content is None or not rel:
                continue
            target = (work / rel).resolve()
            if work.resolve() not in target.parents and target != work.resolve():
                self.log(job, "fix_path_escape_blocked", path=rel)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            applied += 1
            self.log(job, "fix_wrote_file", path=rel)

        # Apply allowed shell commands
        for cmd in proposal.get("commands") or []:
            if isinstance(cmd, str):
                cmd_list = shlex.split(cmd)
            elif isinstance(cmd, list):
                cmd_list = [str(x) for x in cmd]
            else:
                continue
            if not _cmd_allowed(cmd_list):
                self.log(job, "fix_cmd_blocked", cmd=cmd_list)
                continue
            r = _run(cmd_list, cwd=work, timeout=600)
            self.log(job, "fix_cmd", cmd=cmd_list, ok=r["ok"])
            applied += 1 if r["ok"] else 0

        if applied == 0 and not proposal.get("notes"):
            # heuristic last-ditch: create minimal pytest.ini / skip nothing
            self.log(job, "fix_noop")
            return False
        return True

    def phase_report(self, job: GithubJob) -> Path:
        job.phase = "report"
        work = Path(job.work_dir)
        report_path = work / "NEXUS_REPORT.md"
        checks = job.results.get("checks") or []
        install = job.results.get("install") or []
        lines = [
            f"# NEXUS report — {job.ref.get('slug')}",
            "",
            f"- **Job:** `{job.job_id}`",
            f"- **Goal:** {job.goal}",
            f"- **Status:** {job.status}",
            f"- **Workdir:** `{job.work_dir}`",
            f"- **Repo:** {job.ref.get('https_url')}",
            f"- **Fix rounds:** {job.fix_rounds}",
            "",
            "## Detected",
            f"- Languages: {', '.join(job.profile.get('languages') or []) or 'unknown'}",
            f"- Package managers: {', '.join(job.profile.get('package_managers') or []) or '—'}",
            f"- Notes: {'; '.join(job.profile.get('notes') or []) or '—'}",
            "",
            "## Install",
        ]
        if not install:
            lines.append("_no install steps_")
        for r in install:
            mark = "OK" if r.get("ok") else "FAIL"
            lines.append(f"- **{mark}** `{' '.join(r.get('cmd') or [])}`")
        lines.append("")
        lines.append("## Checks")
        if not checks:
            lines.append("_no checks_")
        for r in checks:
            mark = "OK" if r.get("ok") else "FAIL"
            cmd = r.get("cmd") or []
            lines.append(f"- **{mark}** `{' '.join(cmd) if isinstance(cmd, list) else cmd}`")
            if not r.get("ok"):
                err = (r.get("stderr_tail") or r.get("stdout_tail") or "")[:500]
                if err:
                    lines.append("```")
                    lines.append(err)
                    lines.append("```")
        plan = job.results.get("agent_plan")
        if plan:
            lines.extend(["", "## Agent plan", "```json", json.dumps(plan, indent=2)[:3000], "```"])
        lines.extend(
            [
                "",
                "## Next",
                f"```bash",
                f"cd {job.work_dir}",
                f"# inspect NEXUS_REPORT.md and re-run: nexus do {job.ref.get('slug')} --resume {job.job_id}",
                f"```",
                "",
            ]
        )
        report_path.write_text("\n".join(lines), encoding="utf-8")
        job.results["report"] = str(report_path)
        self.save(job)
        self.log(job, "report_written", path=str(report_path))
        return report_path

    # --- agent helpers ---

    def _agent_plan(self, job: GithubJob, prof: ProjectProfile) -> Optional[dict[str, Any]]:
        if not self.panel:
            return self._heuristic_plan(prof, job.goal)
        try:
            from .steps import StepDef

            step = StepDef(
                2,
                "plan",
                "Plan how to make this GitHub repo work",
                "planner",
                output_keys=("approach", "risks", "estimated_steps"),
            )
            prompt = (
                f"You are planning work on a cloned GitHub repo.\n"
                f"Repo: {job.ref.get('slug')}\n"
                f"Goal: {job.goal}\n"
                f"Detected profile JSON:\n{json.dumps(prof.to_dict(), indent=2)[:4000]}\n"
                f"README excerpt:\n{prof.readme_summary[:1200]}\n\n"
                f"Also suggest install_cmds and check_cmds as arrays of argv arrays "
                f"using only safe package managers (pip, npm, yarn, pnpm, go, cargo, make, pytest).\n"
                f"Return JSON with keys: approach, risks, estimated_steps, install_cmds, check_cmds.\n"
            )
            agent = self.panel.resolve(step)
            out = self.panel.run(
                agent,
                prompt,
                step=step,
                task={"objective": job.goal, "success_criteria": ["checks pass"]},
            )
            # free-form extras may be in _raw
            raw = out.get("_raw") or ""
            parsed = out if isinstance(out, dict) else {}
            if "install_cmds" not in parsed and raw:
                from .agents import _parse_json_object

                alt = _parse_json_object(raw)
                if alt:
                    parsed = {**parsed, **alt}
            return {
                "approach": parsed.get("approach"),
                "risks": parsed.get("risks"),
                "estimated_steps": parsed.get("estimated_steps"),
                "install_cmds": parsed.get("install_cmds"),
                "check_cmds": parsed.get("check_cmds"),
                "_agent": agent,
            }
        except Exception as e:
            self.log(job, "agent_plan_fallback", error=str(e))
            return self._heuristic_plan(prof, job.goal)

    def _heuristic_plan(self, prof: ProjectProfile, goal: str) -> dict[str, Any]:
        return {
            "approach": (
                f"Use detected stack ({', '.join(prof.languages) or 'unknown'}) to install "
                f"deps and run checks. Goal: {goal[:200]}"
            ),
            "risks": ["missing system packages", "network for deps", "flaky tests"],
            "estimated_steps": 4,
            "install_cmds": prof.install_cmds,
            "check_cmds": prof.check_cmds,
            "_agent": "heuristic",
        }

    def _agent_fix(
        self, job: GithubJob, prof: ProjectProfile, failures: list[dict[str, Any]]
    ) -> dict[str, Any]:
        fail_blob = json.dumps(failures, indent=2)[:6000]
        if not self.panel:
            return self._heuristic_fix(job, failures)

        try:
            from .steps import StepDef
            from .agents import _parse_json_object

            step = StepDef(
                4,
                "implement",
                "Fix the repository so checks pass",
                "implementer",
                output_keys=("artifacts", "notes"),
            )
            prompt = (
                f"Fix this GitHub project so automated checks pass.\n"
                f"Repo workdir: {job.work_dir}\n"
                f"Goal: {job.goal}\n"
                f"Profile: {json.dumps(prof.to_dict())[:2000]}\n"
                f"Failures:\n{fail_blob}\n\n"
                f"Return JSON with:\n"
                f'  "files": [{{"path": "relative/path", "content": "full new file contents"}}],\n'
                f'  "commands": [["safe", "argv", "..."]],\n'
                f'  "notes": "what you changed"\n'
                f"Only write paths inside the repo. Prefer minimal fixes. "
                f"Allowed commands: pip, npm, yarn, pnpm, pytest, python3, go, cargo, make.\n"
            )
            agent = self.panel.resolve(step)
            out = self.panel.run(
                agent,
                prompt,
                step=step,
                task={"objective": job.goal, "success_criteria": ["checks pass"]},
            )
            raw = out.get("_raw") or out.get("notes") or ""
            parsed = _parse_json_object(raw) if isinstance(raw, str) else None
            if not parsed:
                parsed = out if isinstance(out, dict) else {}
            return {
                "files": parsed.get("files") or [],
                "commands": parsed.get("commands") or [],
                "notes": parsed.get("notes") or out.get("notes") or "",
                "_agent": agent,
            }
        except Exception as e:
            self.log(job, "agent_fix_fallback", error=str(e))
            return self._heuristic_fix(job, failures)

    def _heuristic_fix(self, job: GithubJob, failures: list[dict[str, Any]]) -> dict[str, Any]:
        """Simple automatic remediations without an LLM."""
        cmds: list[list[str]] = []
        files: list[dict[str, str]] = []
        notes = []
        blob = json.dumps(failures).lower()
        work = Path(job.work_dir)

        if "pytest" in blob and "no module named pytest" in blob:
            cmds.append(["python3", "-m", "pip", "install", "pytest"])
            notes.append("install pytest")
        if "modulenotfounderror" in blob or "no module named" in blob:
            # try requirements again
            if (work / "requirements.txt").is_file():
                cmds.append(
                    ["python3", "-m", "pip", "install", "-r", "requirements.txt"]
                )
                notes.append("reinstall requirements")
            if (work / "pyproject.toml").is_file():
                cmds.append(["python3", "-m", "pip", "install", "-e", "."])
                notes.append("reinstall package editable")
        if "npm err" in blob or "cannot find module" in blob:
            cmds.append(["npm", "install"])
            notes.append("npm install retry")

        return {"files": files, "commands": cmds, "notes": "; ".join(notes) or "no heuristic fix", "_agent": "heuristic"}

    # --- main entry ---

    def run(
        self,
        github: str,
        *,
        goal: str = "",
        resume_id: Optional[str] = None,
        max_fix_rounds: int = 3,
    ) -> GithubJob:
        if resume_id and self._job_path(resume_id).exists():
            job = self.load(resume_id)
            self.log(job, "resuming")
        else:
            job = self.create(github, goal=goal)
            job.max_fix_rounds = max_fix_rounds

        job.status = "running"
        self.save(job)
        print(f"=== NEXUS do {job.ref.get('slug')} ===")
        print(f"  job:  {job.job_id}")
        print(f"  goal: {job.goal[:160]}")
        print(f"  dir:  {job.work_dir}")
        print()

        if not self.phase_clone(job):
            job.status = "failed"
            job.results["error"] = "clone failed"
            self.phase_report(job)
            self.save(job)
            return job

        prof = self.phase_detect(job)
        # rebuild profile object after agent merges
        prof = ProjectProfile(**{k: job.profile[k] for k in ProjectProfile.__dataclass_fields__ if k in job.profile})

        self.phase_install(job, prof)
        check = self.phase_check(job, prof)

        while not check.get("ok") and job.fix_rounds < job.max_fix_rounds:
            if not self.phase_fix(job, prof, check):
                break
            check = self.phase_check(job, prof)

        if check.get("ok"):
            job.status = "completed"
            self.log(job, "success")
        else:
            job.status = "failed"
            job.results["error"] = "checks still failing after fix rounds"
            self.log(job, "failed_after_fixes")

        report = self.phase_report(job)
        self.save(job)
        print()
        print(f"=== done: {job.status} ===")
        print(f"  workdir: {job.work_dir}")
        print(f"  report:  {report}")
        print(f"  resume:  nexus do {job.ref.get('slug')} --resume {job.job_id}")
        return job


# commands allowed for install / check / fix (argv[0] basenames)
_ALLOWED_BINARIES = {
    "python",
    "python3",
    "pip",
    "pip3",
    "npm",
    "npx",
    "yarn",
    "pnpm",
    "node",
    "go",
    "cargo",
    "make",
    "pytest",
    "git",
    "find",
    "ls",
    "bash",
    "sh",
}


def _cmd_allowed(cmd: list[str]) -> bool:
    if not cmd:
        return False
    bin0 = Path(cmd[0]).name
    if bin0 not in _ALLOWED_BINARIES:
        return False
    joined = " ".join(cmd).lower()
    # block obvious foot-guns
    banned = ["rm -rf /", "sudo ", ":(){", "mkfs", "dd if=", ">/dev/sd", "curl | sh", "wget | sh"]
    if any(b in joined for b in banned):
        return False
    # python -m pip / pytest ok
    if bin0 in {"bash", "sh"}:
        # only allow simple -c with pip/npm? safer to deny bash -c freeform
        return False
    return True


def ensure_panel_for_job(bus_port: Optional[int] = None):
    """Build AgentPanel from running bus, or mock demo panel."""
    from .agents import AgentPanel
    from .bus_client import BusClient
    from .runtime import RuntimeManager

    rt = RuntimeManager()
    port = bus_port or rt.bus_port or 3099
    base = f"http://127.0.0.1:{port}"
    bus = BusClient(base_url=base)
    if bus.is_reachable():
        return AgentPanel.from_bus(bus, mock_fallback=True)
    return AgentPanel.demo()
