"""Orchestration façade: async tasks with durable envelopes + OpsStore.

Design: docs/design/nexus-orchestration-mcp-server.md

Public API used by MCP:
  - run_task(...)
  - get_task_status(..., action=status|cancel|logs)
  - worker_main() for subprocess workers

task_id == ops job id == envelope filename stem.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .ops_store import (
    JOB_KINDS,
    JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    OpsError,
    OpsStore,
)

SCHEMA = "nexus.orchestrator/v1"
PUBLIC_KINDS = frozenset({"task", "research"})
AGENT_MODES = frozenset({"demo", "fake", "bus", "auto"})
_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class OrchError(RuntimeError):
    """Orchestrator client error (maps to MCP isError)."""

    def __init__(self, message: str, *, code: str = "orch_error"):
        super().__init__(message)
        self.code = code


def project_root(workdir: Optional[Path | str] = None) -> Path:
    if workdir is not None:
        return Path(workdir).resolve()
    return Path(os.environ.get("NEXUS_PROJECT_ROOT") or Path.cwd()).resolve()


def orch_dir(root: Path) -> Path:
    d = root / ".nexus_state" / "orchestrator"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sanitize_task_id(raw: Optional[str] = None) -> str:
    if raw:
        tid = str(raw).strip()
        if not _ID_RE.match(tid):
            raise OrchError(
                f"invalid task_id: {raw!r} (use [a-zA-Z0-9._-] max 64)",
                code="invalid_id",
            )
        if ".." in tid or "/" in tid or "\\" in tid:
            raise OrchError(f"invalid task_id path chars: {raw!r}", code="invalid_id")
        return tid
    return f"task-{uuid.uuid4().hex[:12]}"


@dataclass
class Envelope:
    """On-disk job envelope (JSON under .nexus_state/orchestrator/)."""

    task_id: str
    kind: str
    goal: str
    status: str = "running"
    agent_mode: str = "demo"
    backend: str = "fake"
    cancel_requested: bool = False
    pid: Optional[int] = None
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    log_tail: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Envelope":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kw = {k: v for k, v in data.items() if k in known}
        kw.setdefault("meta", {})
        kw.setdefault("log_tail", [])
        return cls(**kw)


def _envelope_path(root: Path, task_id: str) -> Path:
    # Jail: only basename under orch dir
    safe = sanitize_task_id(task_id)
    return orch_dir(root) / f"{safe}.json"


def load_envelope(root: Path, task_id: str) -> Optional[Envelope]:
    p = _envelope_path(root, task_id)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return Envelope.from_dict(data)


def save_envelope(root: Path, env: Envelope) -> None:
    env.updated_at = time.time()
    p = _envelope_path(root, env.task_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(env.to_dict(), indent=2, default=str) + "\n", encoding="utf-8"
    )
    tmp.replace(p)


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_worker_pid(pid: Optional[int], *, grace_s: float = 10.0) -> None:
    """SIGTERM then SIGKILL. Not RuntimeManager (bus bridges only)."""
    if not pid or pid <= 0:
        return
    if not _pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + max(0.1, grace_s)
    while time.time() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


class Orchestrator:
    """High-level run_task / get_task_status façade."""

    def __init__(self, workdir: Optional[Path | str] = None):
        self.root = project_root(workdir)
        orch_dir(self.root)

    def _ops(self) -> OpsStore:
        return OpsStore.open(self.root)

    def run_task(
        self,
        description: str,
        *,
        kind: str = "task",
        agent_mode: str = "auto",
        task_id: Optional[str] = None,
        wait: bool = False,
        wait_timeout_s: float = 120.0,
        with_brief: bool = False,
        meta: Optional[dict[str, Any]] = None,
        sync_fake: bool = False,
    ) -> dict[str, Any]:
        """Start a task; returns status payload including task_id."""
        goal = str(description or "").strip()
        if not goal:
            raise OrchError("description required", code="invalid_args")

        k = str(kind or "task").strip().lower()
        if k not in PUBLIC_KINDS:
            raise OrchError(
                f"invalid kind {kind!r}; allowed: {sorted(PUBLIC_KINDS)}",
                code="invalid_kind",
            )
        if k not in JOB_KINDS:
            raise OrchError(f"kind not in JOB_KINDS: {k}", code="invalid_kind")

        mode = str(agent_mode or "auto").strip().lower()
        if mode not in AGENT_MODES:
            raise OrchError(
                f"invalid agent_mode {agent_mode!r}; allowed: {sorted(AGENT_MODES)}",
                code="invalid_args",
            )
        if mode == "auto":
            mode = "demo"

        tid = sanitize_task_id(task_id)
        if load_envelope(self.root, tid) is not None:
            raise OrchError(f"task_id already exists: {tid}", code="already_exists")

        backend = "fake" if mode == "fake" else ("research" if k == "research" else "engine")
        env = Envelope(
            task_id=tid,
            kind=k,
            goal=goal,
            status="running",
            agent_mode=mode,
            backend=backend,
            meta={
                **(meta or {}),
                "with_brief": bool(with_brief),
                "schema": SCHEMA,
            },
        )
        env.log_tail.append(f"created kind={k} mode={mode} backend={backend}")

        with self._ops() as store:
            store.ensure_job(
                tid,
                kind=k,
                title=goal[:80] or tid,
                status="running",
                goal=goal,
                meta={"orchestrator": True, "agent_mode": mode, "backend": backend},
            )

        save_envelope(self.root, env)

        # In-process fake for unit tests / instant path
        if backend == "fake" and (
            sync_fake or os.environ.get("NEXUS_ORCH_SYNC_FAKE", "").strip() == "1"
        ):
            self._run_fake(env)
            return self.get_task_status(tid)

        if backend == "fake" and wait:
            self._run_fake(env)
            return self.get_task_status(tid)

        # Subprocess worker for durable async work
        pid = self._spawn_worker(tid)
        env.pid = pid
        env.log_tail.append(f"spawned worker pid={pid}")
        save_envelope(self.root, env)

        if wait:
            self._wait_done(tid, timeout_s=min(float(wait_timeout_s), 300.0))
        return self.get_task_status(tid)

    def _spawn_worker(self, task_id: str) -> int:
        env = os.environ.copy()
        env["NEXUS_PROJECT_ROOT"] = str(self.root)
        env["PYTHONPATH"] = os.pathsep.join(
            [
                str(Path(__file__).resolve().parents[1]),
                env.get("PYTHONPATH", ""),
            ]
        ).strip(os.pathsep)
        cmd = [
            sys.executable,
            "-m",
            "nexus.orchestrator",
            "worker",
            "--task-id",
            task_id,
            "--root",
            str(self.root),
        ]
        log_path = orch_dir(self.root) / f"{task_id}.worker.log"
        log_f = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.root),
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return int(proc.pid)

    def _wait_done(self, task_id: str, *, timeout_s: float) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            st = self.get_task_status(task_id)
            if st.get("status") in TERMINAL_JOB_STATUSES:
                return
            time.sleep(0.15)
        # leave running; client can poll

    def _run_fake(self, env: Envelope) -> None:
        """Complete immediately (test / fake mode)."""
        if env.cancel_requested or env.status == "cancelled":
            return
        env.status = "completed"
        env.detail = "fake backend completed"
        env.log_tail.append("fake: completed")
        save_envelope(self.root, env)
        with self._ops() as store:
            try:
                store.set_status(env.task_id, "completed")
            except OpsError:
                pass

    def reap_if_needed(self, task_id: str) -> None:
        """If worker died without terminal status, mark failed (reaper)."""
        env = load_envelope(self.root, task_id)
        if env is None:
            return
        if env.status in TERMINAL_JOB_STATUSES:
            return
        if env.cancel_requested:
            self._force_status(env, "cancelled", "reaper: cancel_requested")
            return
        if env.pid and not _pid_alive(env.pid):
            # brief grace: worker may be exiting
            time.sleep(0.05)
            env2 = load_envelope(self.root, task_id)
            if env2 and env2.status not in TERMINAL_JOB_STATUSES:
                self._force_status(
                    env2, "failed", f"reaper: worker pid {env.pid} exited"
                )

    def _force_status(self, env: Envelope, status: str, detail: str) -> None:
        env.status = status
        env.detail = detail
        env.log_tail.append(detail)
        env.pid = None
        save_envelope(self.root, env)
        with self._ops() as store:
            try:
                store.set_status(env.task_id, status, force=False)
            except OpsError:
                pass

    def cancel(self, task_id: str) -> dict[str, Any]:
        tid = sanitize_task_id(task_id)
        env = load_envelope(self.root, tid)
        with self._ops() as store:
            job = store.get(tid)

        if env is None and job is None:
            raise OrchError(f"not found: {tid}", code="not_found")

        # Idempotent if already terminal
        cur = (env.status if env else None) or (job or {}).get("status")
        if cur in TERMINAL_JOB_STATUSES:
            return self.get_task_status(tid)

        if env is None:
            env = Envelope(
                task_id=tid,
                kind=str((job or {}).get("kind") or "task"),
                goal=str((job or {}).get("goal") or ""),
                status="cancelled",
                cancel_requested=True,
                detail="cancel without envelope",
            )
        else:
            env.cancel_requested = True
            env.status = "cancelled"
            env.detail = "cancelled by client"
            env.log_tail.append("cancel_requested")

        grace = float(os.environ.get("NEXUS_ORCH_CANCEL_GRACE_S") or 10)
        pid = env.pid
        kill_worker_pid(pid, grace_s=grace)
        env.pid = None
        save_envelope(self.root, env)

        with self._ops() as store:
            if store.get(tid) is None:
                store.ensure_job(
                    tid,
                    kind=env.kind if env.kind in JOB_KINDS else "task",
                    title=env.goal[:80] or tid,
                    status="cancelled",
                    goal=env.goal,
                    meta={"cancel_requested": True},
                )
            else:
                store.set_status(tid, "cancelled", force=False)
                store.ensure_job(tid, meta={"cancel_requested": True, "reason": "cancelled"})

        return self.get_task_status(tid)

    def get_task_status(
        self,
        task_id: str,
        *,
        action: str = "status",
        log_lines: int = 40,
    ) -> dict[str, Any]:
        action = str(action or "status").strip().lower()
        tid = sanitize_task_id(task_id)

        if action == "cancel":
            return self.cancel(tid)

        self.reap_if_needed(tid)
        env = load_envelope(self.root, tid)
        with self._ops() as store:
            job = store.get(tid)

        if env is None and job is None:
            # legacy best-effort (engine checkpoint only)
            legacy = self._legacy_lookup(tid)
            if legacy:
                legacy["legacy"] = True
                return legacy
            raise OrchError(f"not found: {tid}", code="not_found")

        status = (env.status if env else None) or (job or {}).get("status") or "running"
        # Prefer ops if terminal sticky won
        if job and job.get("status") in TERMINAL_JOB_STATUSES:
            status = job["status"]

        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "task_id": tid,
            "status": status,
            "kind": (env.kind if env else None) or (job or {}).get("kind"),
            "goal": (env.goal if env else None) or (job or {}).get("goal"),
            "detail": (env.detail if env else "") or "",
            "agent_mode": env.agent_mode if env else None,
            "backend": env.backend if env else None,
            "cancel_requested": bool(env.cancel_requested) if env else False,
            "pid": env.pid if env else None,
            "worker_alive": _pid_alive(env.pid) if env else False,
            "updated_at": (env.updated_at if env else None)
            or (job or {}).get("updated_at"),
            "ops": {
                "tokens": (job or {}).get("tokens"),
                "cost": (job or {}).get("cost"),
                "title": (job or {}).get("title"),
            }
            if job
            else None,
            "legacy": False,
        }
        if action == "logs":
            n = max(1, min(int(log_lines or 40), 200))
            lines = list(env.log_tail if env else [])[-n:]
            log_path = orch_dir(self.root) / f"{tid}.worker.log"
            if log_path.is_file():
                try:
                    file_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    lines = (lines + file_lines)[-n:]
                except OSError:
                    pass
            payload["logs"] = lines
        return payload

    def _legacy_lookup(self, task_id: str) -> Optional[dict[str, Any]]:
        try:
            from .config import Settings
            from .engine import DurableEngine

            settings = Settings(state_dir=self.root / ".nexus_state")
            engine = DurableEngine(settings=settings, auto_approve=True)
            task = engine.load(task_id)
            return {
                "schema": SCHEMA,
                "task_id": task_id,
                "status": _map_engine_status(task.status.value),
                "kind": "task",
                "goal": task.objective,
                "detail": f"legacy engine checkpoint step={task.current_step}",
                "legacy": True,
            }
        except Exception:
            return None


def _map_engine_status(st: str) -> str:
    m = {
        "pending": "inbox",
        "running": "running",
        "waiting_human": "blocked",
        "completed": "completed",
        "failed": "failed",
    }
    return m.get(st, "running")


# ---------------------------------------------------------------------------
# Worker process
# ---------------------------------------------------------------------------


def worker_main(task_id: str, root: Optional[Path] = None) -> int:
    """Entry for ``python -m nexus.orchestrator worker``."""
    root = project_root(root)
    os.environ["NEXUS_PROJECT_ROOT"] = str(root)
    tid = sanitize_task_id(task_id)
    env = load_envelope(root, tid)
    if env is None:
        print(f"envelope missing: {tid}", file=sys.stderr)
        return 2

    def _cancelled() -> bool:
        e = load_envelope(root, tid)
        if e is None:
            return True
        if e.cancel_requested or e.status == "cancelled":
            return True
        try:
            with OpsStore.open(root) as store:
                job = store.get(tid)
                if job and job.get("status") == "cancelled":
                    return True
        except Exception:
            pass
        return False

    def _set(status: str, detail: str = "") -> None:
        e = load_envelope(root, tid) or env
        # K15/K16: refuse to write completed if cancelled
        if status == "completed" and (
            e.cancel_requested or e.status == "cancelled" or _cancelled()
        ):
            status = "cancelled"
            detail = detail or "completed suppressed; already cancelled"
        e.status = status
        e.detail = detail or e.detail
        e.log_tail.append(f"worker: {status} {detail}".strip())
        if status in TERMINAL_JOB_STATUSES:
            e.pid = None
        save_envelope(root, e)
        try:
            with OpsStore.open(root) as store:
                store.set_status(tid, status, force=False)
        except OpsError as ex:
            print(f"ops set_status: {ex}", file=sys.stderr)

    if _cancelled():
        _set("cancelled", "worker start aborted; cancelled")
        return 0

    try:
        if env.backend == "fake" or env.agent_mode == "fake":
            time.sleep(0.05)
            if _cancelled():
                _set("cancelled", "cancelled during fake")
                return 0
            _set("completed", "fake backend ok")
            return 0

        if env.kind == "research" or env.backend == "research":
            return _worker_research(root, env, _cancelled, _set)

        return _worker_engine(root, env, _cancelled, _set)
    except Exception as e:
        if _cancelled():
            _set("cancelled", f"cancelled after error: {e}")
            return 0
        _set("failed", f"{type(e).__name__}: {e}")
        return 1


def _worker_engine(root: Path, env: Envelope, _cancelled, _set) -> int:
    from .agents import AgentPanel
    from .config import Settings
    from .engine import DurableEngine, Task

    if _cancelled():
        _set("cancelled", "cancelled before engine")
        return 0

    settings = Settings(autonomy=False, state_dir=root / ".nexus_state")
    settings.ensure_dirs()
    # demo panel — no bus auto-start
    if env.agent_mode == "bus":
        try:
            panel = AgentPanel.from_bus()
        except Exception as e:
            _set("blocked", f"bus_down: {e}")
            return 0
    else:
        panel = AgentPanel.demo()

    engine = DurableEngine(
        settings=settings,
        panel=panel,
        auto_approve=True,
    )
    task = Task(
        task_id=env.task_id,
        objective=env.goal,
        success_criteria=["pipeline completes"],
        namespace=f"orch/{env.task_id}",
    )
    task.meta["orchestrator"] = True
    task.meta["cancel_check"] = True

    # Run with cooperative cancel between steps via max_steps loop
    # DurableEngine.run may take a while; check cancel before start
    if _cancelled():
        _set("cancelled", "cancelled before run")
        return 0

    try:
        # Optional step-budget from env for faster tests
        max_steps = os.environ.get("NEXUS_ORCH_MAX_STEPS")
        ms = int(max_steps) if max_steps else None
        result = engine.run(task, max_steps=ms)
    except Exception as e:
        if _cancelled():
            _set("cancelled", str(e))
            return 0
        _set("failed", f"engine: {e}")
        return 1

    if _cancelled():
        _set("cancelled", "cancelled after engine")
        return 0

    st = _map_engine_status(result.status.value)
    if st == "blocked":
        _set("blocked", "waiting_human or bus")
        return 0
    if st == "completed":
        _set("completed", f"engine step={result.current_step}")
        return 0
    if st == "failed":
        _set("failed", str(result.meta.get("error") or "engine failed"))
        return 1
    _set(st, f"engine status={result.status.value}")
    return 0 if st == "completed" else 1


def _worker_research(root: Path, env: Envelope, _cancelled, _set) -> int:
    from .research_job import ResearchJobRunner

    if _cancelled():
        _set("cancelled", "cancelled before research")
        return 0

    with_brief = bool((env.meta or {}).get("with_brief"))
    # K14: default False
    runner = ResearchJobRunner(
        project_root=root,
        state_dir=root / ".nexus_state" / "research_jobs",
    )
    try:
        out = runner.run(
            env.goal,
            with_brief=with_brief,
            job_id=env.task_id,
            download_pdf=False,
            max_results=5,
        )
    except Exception as e:
        if _cancelled():
            _set("cancelled", str(e))
            return 0
        _set("failed", f"research: {e}")
        return 1

    if _cancelled():
        _set("cancelled", "cancelled after research")
        return 0

    st = getattr(out, "status", None) or "completed"
    if st == "failed":
        _set("failed", "research job failed")
        return 1
    _set("completed", f"research ok with_brief={with_brief} status={st}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(prog="nexus.orchestrator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("worker", help="Run worker for a task envelope")
    w.add_argument("--task-id", required=True)
    w.add_argument("--root", default=None)

    r = sub.add_parser("run", help="CLI submit task")
    r.add_argument("description")
    r.add_argument("--kind", default="task")
    r.add_argument("--mode", default="fake")
    r.add_argument("--wait", action="store_true")
    r.add_argument("--root", default=None)

    s = sub.add_parser("status", help="Poll task")
    s.add_argument("task_id")
    s.add_argument("--root", default=None)

    c = sub.add_parser("cancel", help="Cancel task")
    c.add_argument("task_id")
    c.add_argument("--root", default=None)

    args = ap.parse_args(argv)
    if args.cmd == "worker":
        return worker_main(args.task_id, Path(args.root) if args.root else None)
    orch = Orchestrator(args.root)
    if args.cmd == "run":
        out = orch.run_task(
            args.description,
            kind=args.kind,
            agent_mode=args.mode,
            wait=args.wait,
            sync_fake=(args.mode == "fake"),
        )
        print(json.dumps(out, indent=2, default=str))
        return 0
    if args.cmd == "status":
        print(json.dumps(orch.get_task_status(args.task_id), indent=2, default=str))
        return 0
    if args.cmd == "cancel":
        print(json.dumps(orch.cancel(args.task_id), indent=2, default=str))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
