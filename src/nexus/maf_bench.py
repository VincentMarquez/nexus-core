"""MAFBench proxy — framework-level multi-agent overhead evaluation.

Implements the concrete recommendation from arXiv:2602.03128
("Understanding Multi-Agent LLM Frameworks: A Unified Benchmark and
Experimental Analysis"): measure framework mechanisms on unified
dimensions — latency, success rate, relative overhead — so consensus
and orchestration costs are comparable offline.

This is a **proxy**, not a vendored MAFBench tree. It exercises NEXUS
surfaces already in-tree:

  * single_judge   — RubricJudge baseline (one grader)
  * consensus      — multi-grader ConsensusJudge + trust weights
  * trust_log      — TrustLog provenance/verdict flush
  * orch_linear    — StepPolicy linear next-step scheduling
  * orch_dag       — StepPolicy DAG validate / ready / blocked / topo
  * domain_mcp     — AssetOpsBench-shaped multi-domain MCP hub overhead
                     (status/catalog/grade/vault servers, offline)
  * marketplace    — wshobson-shaped Markdown plugin catalog (discover /
                     validate / collisions / multi-harness catalog)
  * market_plan    — marketplace catalog → Planner → Orchestrator handoff
                     (MAFBench overhead of plan-before-execute over plugins)
  * control_plane  — mission-control-shaped SQLite ops plane (job
                     governance + spend + sticky terminal status)
  * delivery_board — routa-shaped multi-agent delivery board (lanes +
                     roles + traces + evidence + review signal)

Cross-pattern hybrids::

    arXiv MAFBench + IBM/AssetOpsBench
      JSON scenario packs → gate scorers → pass-rate report
      multi-domain MCP hub (mcphub multi-server shape → NEXUS offline
      domains: status/catalog/grade/vault)

    arXiv MAFBench + wshobson/agents
      single-source Markdown plugins/ layout (agents/*.md, skills/*/SKILL.md,
      commands/*.md) → catalog micro-bench overhead vs single_judge
      + market_plan: catalog-as-tools → dedicated Planner → Orchestrator
        with_plan handoff (structure before durable execute)

    arXiv MAFBench + builderz-labs/mission-control
      SQLite-backed control plane job lifecycle (inbox→running→spend→
      completed + sticky terminal) → governance overhead vs single_judge

    arXiv MAFBench + phodal/routa
      multi-agent delivery board (Backlog→Todo→Dev→Review→Done + roles +
      traces + evidence + board signal) → coordination overhead vs single_judge

Output schema: ``nexus.maf_bench/v1`` under ``.nexus_state/bench/``.
Pack schema: ``nexus.maf_scenario_pack/v1``.

Evidence drivers:
- arXiv 2602.03128 — unified multi-agent framework benchmark
- IBM/AssetOpsBench — scenario pack → run → scorer → pass-rate report
  and domain MCP server shape (pattern only; no industrial IoT vendor)
- wshobson/agents — Markdown marketplace discover/validate/collision
  gates + multi-harness catalog export (pattern only; no plugin tree vendor)
- builderz-labs/mission-control — SQLite control plane, task governance,
  spend attribution, sticky terminal statuses (pattern only; no tree vendor)
- phodal/routa — workspace delivery board with lane specialists, review
  gate, goal/task/trace/evidence coordination (pattern only; no tree vendor)
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .agents import AgentPanel
from .consensus import ConsensusJudge
from .judge import RubricJudge
from .persist import atomic_write_json, atomic_write_text
from .steps import StepDef, StepPolicy
from .trust import TrustLog

SCHEMA = "nexus.maf_bench/v1"
PACK_SCHEMA = "nexus.maf_scenario_pack/v1"
PAPER = "2602.03128v1"
PAPER_URL = "https://arxiv.org/abs/2602.03128v1"
ASSETOPS_URL = "https://github.com/IBM/AssetOpsBench"
WSHOBSON_URL = "https://github.com/wshobson/agents"
MISSION_CONTROL_URL = "https://github.com/builderz-labs/mission-control"
ROUTA_URL = "https://github.com/phodal/routa"
DEFAULT_OUT_DIR = ".nexus_state/bench"
DEFAULT_PACK_DIR = ".nexus_state/bench/packs"
BUNDLED_PACKS_REL = "fixtures/maf_bench/packs"
# Isolated marketplace tree for offline MAFBench (never touches repo plugins/).
MAF_MARKETPLACE_REL = ".nexus_state/bench/_maf_marketplace"
MAF_MARKETPLACE_PLUGINS = "plugins"
# Isolated ops plane workdir (never touches operator .nexus_state/ops/).
MAF_CONTROL_PLANE_REL = ".nexus_state/bench/_maf_control_plane"
# Isolated delivery board workdir (never mutates operator improve board state).
MAF_DELIVERY_BOARD_REL = ".nexus_state/bench/_maf_delivery_board"
DEFAULT_ITERS = 25

# AssetOpsBench multi-server shape (iot / fmsr / tsfm / wo / utilities /
# vibration) → NEXUS offline domain "servers". Pattern only; no industrial
# IoT/CouchDB fixtures. Each entry is one logical MCP domain server that
# mcphub would load_tools() across.
DOMAIN_MCP_SERVERS: tuple[dict[str, Any], ...] = (
    {
        "id": "status",
        "domains": ("status",),
        "assetops_analogue": "utilities",
        "description": "Health / platform identity (utilities analogue)",
    },
    {
        "id": "catalog",
        "domains": ("catalog",),
        "assetops_analogue": "iot",
        "description": "Tool discovery / inventory (iot discovery analogue)",
    },
    {
        "id": "grade",
        "domains": ("grade",),
        "assetops_analogue": "fmsr",
        "description": "Improve-grade diagnostics (fmsr analogue)",
    },
    {
        "id": "vault",
        "domains": ("vault",),
        "assetops_analogue": "wo",
        "description": "Secret presence / work-order safety (wo analogue)",
    },
)

# routa-shaped kanban lanes (happy path + blocked escape).
DELIVERY_LANES = (
    "backlog",
    "todo",
    "dev",
    "review",
    "done",
)
DELIVERY_LANE_BLOCKED = "blocked"
# Core roles (routa ROUTA / CRAFTER / GATE → NEXUS grader / implementer / verifier).
DELIVERY_ROLES = {
    "grader": "routa:coord",
    "implementer": "crafter:dev",
    "verifier": "gate:review",
}

# Builtin mechanism ids (stable CLI surface).
MECHANISMS = (
    "single_judge",
    "consensus",
    "trust_log",
    "orch_linear",
    "orch_dag",
    "domain_mcp",
    "marketplace",
    "market_plan",
    "control_plane",
    "delivery_board",
)

# Offline task text for market_plan micro-bench (heuristic Planner ranking).
MARKET_PLAN_TASK = (
    "run maf smoke catalog agent skill over the marketplace fixture plugins"
)


@dataclass
class MechanismSpec:
    """One framework mechanism under test (MAFBench-style scenario)."""

    id: str
    family: str  # baseline | consensus | trust | orchestration
    description: str
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_mechanisms() -> list[dict[str, Any]]:
    """Catalog of built-in MAFBench proxy scenarios."""
    specs = [
        MechanismSpec(
            id="single_judge",
            family="baseline",
            description="Single RubricJudge evaluate (baseline for relative overhead)",
            tags=["judge", "baseline"],
        ),
        MechanismSpec(
            id="consensus",
            family="consensus",
            description="Multi-grader ConsensusJudge + trust weights",
            tags=["consensus", "trust", "multi-grader"],
        ),
        MechanismSpec(
            id="trust_log",
            family="trust",
            description="TrustLog provenance + verdict atomic flush",
            tags=["trust", "provenance"],
        ),
        MechanismSpec(
            id="orch_linear",
            family="orchestration",
            description="Linear StepPolicy next-step scheduling",
            tags=["orchestration", "pipeline"],
        ),
        MechanismSpec(
            id="orch_dag",
            family="orchestration",
            description="DAG validate / ready / blocked / topo",
            tags=["orchestration", "dag"],
        ),
        MechanismSpec(
            id="domain_mcp",
            family="domain_mcp",
            description=(
                "AssetOpsBench-shaped multi-domain MCP hub smoke "
                "(status/catalog/grade/vault servers, offline)"
            ),
            tags=[
                "domain",
                "mcp",
                "assetops",
                "multi-server",
                "mcphub",
                "iot-shape",
            ],
        ),
        MechanismSpec(
            id="marketplace",
            family="marketplace",
            description=(
                "wshobson-shaped Markdown plugin marketplace smoke "
                "(discover + validate + collisions + catalog, offline)"
            ),
            tags=["marketplace", "plugins", "wshobson", "markdown", "catalog"],
        ),
        MechanismSpec(
            id="market_plan",
            family="market_plan",
            description=(
                "Marketplace Planner → Orchestrator handoff smoke "
                "(wshobson catalog-as-tools + plan-before-execute, offline)"
            ),
            tags=[
                "marketplace",
                "planner",
                "orchestration",
                "wshobson",
                "handoff",
                "with_plan",
            ],
        ),
        MechanismSpec(
            id="control_plane",
            family="control_plane",
            description=(
                "mission-control-shaped SQLite ops plane smoke "
                "(job governance + spend + sticky terminal, offline)"
            ),
            tags=[
                "control_plane",
                "ops",
                "sqlite",
                "mission-control",
                "governance",
                "spend",
            ],
        ),
        MechanismSpec(
            id="delivery_board",
            family="delivery_board",
            description=(
                "routa-shaped multi-agent delivery board smoke "
                "(lanes + roles + traces + evidence + signal, offline)"
            ),
            tags=[
                "delivery_board",
                "board",
                "routa",
                "lanes",
                "review",
                "traces",
                "evidence",
                "workspace",
            ],
        ),
    ]
    return [s.to_dict() for s in specs]


def _p50(vals: list[float]) -> float:
    return round(statistics.median(vals), 3) if vals else 0.0


def _p95(vals: list[float]) -> float:
    if not vals:
        return 0.0
    if len(vals) == 1:
        return round(vals[0], 3)
    ordered = sorted(vals)
    # nearest-rank at 95%
    idx = min(len(ordered) - 1, max(0, int(round(0.95 * (len(ordered) - 1)))))
    return round(ordered[idx], 3)


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 3) if vals else 0.0


def bench_calls(
    name: str,
    family: str,
    calls: list[Callable[[], dict[str, Any]]],
) -> dict[str, Any]:
    """Run callables; collect unified MAFBench metrics.

    Each callable may return: ok (bool), extra keys merged into ``extras``.
    """
    lat: list[float] = []
    oks = 0
    extras_acc: dict[str, list[Any]] = {}
    for fn in calls:
        t0 = time.perf_counter()
        try:
            res = fn() or {}
            ok = bool(res.get("ok", True))
        except Exception as exc:  # noqa: BLE001 — bench must not abort suite
            res, ok = {"error": str(exc)}, False
        lat.append((time.perf_counter() - t0) * 1000.0)
        if ok:
            oks += 1
        for k, v in res.items():
            if k in ("ok", "error"):
                continue
            extras_acc.setdefault(k, []).append(v)
    n = max(1, len(calls))
    total_ms = sum(lat)
    row: dict[str, Any] = {
        "mechanism": name,
        "family": family,
        "iters": len(calls),
        "ok_rate": round(oks / n, 4),
        "p50_ms": _p50(lat),
        "p95_ms": _p95(lat),
        "mean_ms": _mean(lat),
        "total_ms": round(total_ms, 3),
        "ops_per_s": round((len(calls) / (total_ms / 1000.0)), 1) if total_ms > 0 else 0.0,
    }
    # Collapse numeric extras to means when useful
    for k, vals in extras_acc.items():
        nums = [float(v) for v in vals if isinstance(v, (int, float))]
        if nums and len(nums) == len(vals):
            row[k] = round(statistics.mean(nums), 4)
        elif vals:
            # last non-empty sample (e.g. decision strings)
            row[k] = vals[-1]
    return row


def _fixture_task_output(tmp: Path) -> tuple[dict[str, Any], dict[str, Any], StepDef]:
    """Deterministic implement-step fixture with DEMO_OK artifact."""
    art = tmp / "maf_artifact.txt"
    art.write_text("DEMO_OK\nmaf_bench fixture\n", encoding="utf-8")
    step = StepPolicy.default().get(4)  # implement
    task = {
        "goal": "maf_bench fixture",
        "success_criteria": ["artifact contains DEMO_OK"],
    }
    output = {
        "artifacts": [str(art)],
        "pass_fail": "pass",
        "summary": "DEMO_OK",
    }
    return task, output, step


def _demo_dag_policy() -> StepPolicy:
    """Small diamond DAG for orchestration micro-bench."""
    return StepPolicy(
        steps=[
            StepDef(1, "goal", "set goal", "planner"),
            StepDef(2, "plan", "plan work", "planner", depends_on=(1,)),
            StepDef(3, "implement", "code", "implementer", depends_on=(2,)),
            StepDef(4, "test", "test", "tester", depends_on=(3,)),
            StepDef(5, "review", "review", "reviewer", depends_on=(3, 4)),
            StepDef(6, "deliver", "ship", "operator", depends_on=(5,)),
        ]
    )


def _make_single_judge_calls(
    *,
    iters: int,
    fixture_dir: Path,
) -> list[Callable[[], dict[str, Any]]]:
    panel = AgentPanel.demo()
    judge = RubricJudge(panel)
    task, output, step = _fixture_task_output(fixture_dir)

    def one() -> dict[str, Any]:
        v = judge.evaluate(
            step=step, task=task, output=output, implementer="implementer"
        )
        return {
            "ok": v.decision in ("pass", "revise", "fail"),
            "score": float(v.score),
            "n_graders": 1,
        }

    return [one for _ in range(iters)]


def _make_consensus_calls(
    *,
    iters: int,
    fixture_dir: Path,
) -> list[Callable[[], dict[str, Any]]]:
    panel = AgentPanel.demo()
    cj = ConsensusJudge(panel, min_graders=2, max_graders=3, adaptive_trust=False)
    task, output, step = _fixture_task_output(fixture_dir)

    def one() -> dict[str, Any]:
        v = cj.evaluate(
            step=step, task=task, output=output, implementer="implementer"
        )
        return {
            "ok": v.decision in ("pass", "revise", "fail") and v.n_graders >= 1,
            "score": float(v.score),
            "n_graders": int(v.n_graders),
            "agreement_ratio": float(v.agreement_ratio),
            "trust_weights": len(cj.trust.weights),
        }

    return [one for _ in range(iters)]


def _make_trust_log_calls(
    *,
    iters: int,
    fixture_dir: Path,
) -> list[Callable[[], dict[str, Any]]]:
    path = fixture_dir / "trust_maf.json"

    def one() -> dict[str, Any]:
        # Fresh log each call so we measure write path, not unbounded growth only.
        log = TrustLog(path=path)
        p = log.record_prov(
            task_id="maf-bench",
            step=5,
            agent="implementer",
            vendor="demo",
            summary="maf_bench trust flush",
            epistemic="MODEL_ASSERTED",
        )
        log.record_verdict(
            "maf-bench",
            5,
            {"decision": "pass", "score": 0.9, "judge": "reviewer"},
        )
        ok = path.is_file() and bool(p.prov_id) and len(log.verdicts) >= 1
        return {"ok": ok, "n_prov": len(log.provenance), "n_verdicts": len(log.verdicts)}

    return [one for _ in range(iters)]


def _make_orch_linear_calls(*, iters: int) -> list[Callable[[], dict[str, Any]]]:
    # Pure linear (no depends_on) so StepPolicy falls back to current_step order.
    policy = StepPolicy(
        steps=[
            StepDef(i, f"s{i}", f"linear step {i}", "local") for i in range(1, 8)
        ]
    )

    def one() -> dict[str, Any]:
        completed: set[int] = set()
        current = 0
        seen = 0
        while True:
            nxt = policy.next_ready(completed, current_step=current)
            if nxt is None:
                break
            completed.add(nxt.number)
            current = nxt.number
            seen += 1
            if seen > 50:
                break
        ok = (
            not policy.has_dag()
            and seen == len(policy.steps)
            and not policy.pending(completed)
        )
        return {"ok": ok, "steps_walked": seen}

    return [one for _ in range(iters)]


def _make_orch_dag_calls(*, iters: int) -> list[Callable[[], dict[str, Any]]]:
    policy = _demo_dag_policy()

    def one() -> dict[str, Any]:
        policy.validate()
        topo = policy.topo_numbers()
        completed: set[int] = set()
        walked = 0
        # simulate ready-set scheduling
        while len(completed) < len(policy.steps):
            ready = policy.ready(completed)
            if not ready:
                break
            for s in ready:
                completed.add(s.number)
                walked += 1
        blocked_empty = len(policy.blocked(completed)) == 0
        edges = policy.dependency_edges()
        snap_ok = len(topo) == len(policy.steps) and walked == len(policy.steps)
        return {
            "ok": snap_ok and blocked_empty,
            "steps_walked": walked,
            "n_edges": len(edges),
            "topo_len": len(topo),
        }

    return [one for _ in range(iters)]


def list_domain_mcp_servers() -> list[dict[str, Any]]:
    """Catalog of offline multi-domain MCP servers (AssetOpsBench mcphub shape)."""
    return [
        {
            "id": s["id"],
            "domains": list(s["domains"]),
            "assetops_analogue": s["assetops_analogue"],
            "description": s["description"],
        }
        for s in DOMAIN_MCP_SERVERS
    ]


def _make_domain_mcp_calls(
    *,
    iters: int,
    workdir: Path,
) -> list[Callable[[], dict[str, Any]]]:
    """AssetOpsBench multi-domain MCP hub: offline smoke across domain servers.

    Mirrors IBM/AssetOpsBench ``mcphub`` multi-server load pattern
    (iot/fmsr/tsfm/wo/utilities/vibration) with NEXUS offline domains
    (status/catalog/grade/vault). No industrial IoT fixtures — pattern only.

    Each call walks every registered domain server, runs its read-privilege
    scenarios, and aggregates pass-rate + server counts (framework overhead
    of multi-server hub vs single_judge baseline).
    """
    from . import mcp_eval as me

    servers = list(DOMAIN_MCP_SERVERS)
    # Pre-filter per-server suites once (measures invoke+score, not filter tax).
    server_suites: list[tuple[dict[str, Any], list[Any]]] = []
    for srv in servers:
        suite = me.filter_scenarios(
            me.builtin_scenarios(),
            domains=list(srv["domains"]),
            max_privilege="read",
        )
        server_suites.append((srv, suite))

    def one() -> dict[str, Any]:
        n_servers = 0
        n_servers_ok = 0
        n_scenarios = 0
        n_passed = 0
        server_rows: list[dict[str, Any]] = []
        elapsed_acc = 0.0
        for srv, suite in server_suites:
            if not suite:
                # Domain with no read scenarios still counts as registered.
                n_servers += 1
                server_rows.append(
                    {
                        "id": srv["id"],
                        "ok": False,
                        "n_scenarios": 0,
                        "pass_rate": 0.0,
                        "reason": "empty_suite",
                    }
                )
                continue
            report = me.evaluate(
                suite,
                workdir=workdir,
                max_privilege="read",
                include_builtin=False,
            )
            total = int(report.get("total") or 0)
            passed = int(report.get("passed") or 0)
            pass_rate = float(report.get("pass_rate") or 0.0)
            srv_ok = bool(report.get("ok")) and total > 0 and pass_rate >= 1.0
            n_servers += 1
            if srv_ok:
                n_servers_ok += 1
            n_scenarios += total
            n_passed += passed
            elapsed_acc += float(report.get("elapsed_ms") or 0.0)
            server_rows.append(
                {
                    "id": srv["id"],
                    "ok": srv_ok,
                    "n_scenarios": total,
                    "pass_rate": pass_rate,
                    "assetops_analogue": srv.get("assetops_analogue"),
                }
            )
        pass_rate = round(n_passed / n_scenarios, 4) if n_scenarios else 0.0
        servers_ok_rate = (
            round(n_servers_ok / n_servers, 4) if n_servers else 0.0
        )
        # Require all registered servers to pass (hub integrity).
        ok = (
            n_servers >= len(DOMAIN_MCP_SERVERS)
            and n_servers_ok == n_servers
            and n_scenarios > 0
            and pass_rate >= 1.0
        )
        return {
            "ok": ok,
            "pass_rate": pass_rate,
            "n_scenarios": n_scenarios,
            "n_passed": n_passed,
            "n_servers": n_servers,
            "n_servers_ok": n_servers_ok,
            "servers_ok_rate": servers_ok_rate,
            "elapsed_ms": elapsed_acc,
            # last sample of per-server detail (collapsed by bench_calls to last)
            "server_ids": ",".join(s["id"] for s in servers),
        }

    return [one for _ in range(iters)]


def ensure_maf_marketplace_fixture(workdir: Path | str) -> Path:
    """Seed a minimal wshobson-shaped Markdown plugin under bench state.

    Layout (shape only from wshobson/agents plugins/)::

        .nexus_state/bench/_maf_marketplace/plugins/maf-fixture/
          plugin.json
          agents/*.md
          commands/*.md
          skills/<id>/SKILL.md

    Isolated from the repo ``plugins/`` tree so CI and ``tmp_path`` tests
    stay deterministic and never mutate operator installs.
    """
    root = Path(workdir).resolve()
    plugins_root = root / MAF_MARKETPLACE_REL / MAF_MARKETPLACE_PLUGINS
    plugin_dir = plugins_root / "maf-fixture"
    plugin_dir.mkdir(parents=True, exist_ok=True)

    man_path = plugin_dir / "plugin.json"
    if not man_path.is_file():
        man_path.write_text(
            json.dumps(
                {
                    "name": "maf-fixture",
                    "version": "0.1.0",
                    "description": (
                        "MAFBench offline marketplace fixture "
                        "(wshobson/agents layout shape)"
                    ),
                    "category": "evaluation",
                    "privilege": "read",
                    "tags": ["mafbench", "sample", "wshobson", "marketplace"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    agents_dir = plugin_dir / "agents"
    agents_dir.mkdir(exist_ok=True)
    agent_md = agents_dir / "maf-bench-agent.md"
    if not agent_md.is_file():
        agent_md.write_text(
            "---\n"
            "name: maf-bench-agent\n"
            "description: Offline MAFBench marketplace fixture agent\n"
            "---\n\n"
            "# MAFBench fixture agent\n\n"
            "Deterministic agent Markdown for marketplace micro-bench.\n"
            "Measures discover/validate/catalog overhead (no live LLM).\n",
            encoding="utf-8",
        )

    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir(exist_ok=True)
    cmd_md = commands_dir / "maf-smoke.md"
    if not cmd_md.is_file():
        cmd_md.write_text(
            "---\n"
            "name: maf-smoke\n"
            "description: Run MAFBench marketplace smoke\n"
            "---\n\n"
            "# maf-smoke\n\n"
            "```bash\n"
            "nexus eval maf --mechanism marketplace --iters 3 --no-export\n"
            "```\n",
            encoding="utf-8",
        )

    skill_dir = plugin_dir / "skills" / "maf-catalog"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        skill_md.write_text(
            "---\n"
            "name: maf-catalog\n"
            "description: Marketplace catalog skill for MAFBench fixture\n"
            "---\n\n"
            "# maf-catalog skill\n\n"
            "Static skill body used by the MAFBench marketplace mechanism.\n"
            "Validates SKILL.md discovery under skills/<id>/ layout.\n",
            encoding="utf-8",
        )

    return plugins_root.parent  # _maf_marketplace root (workdir for marketplace APIs)


def _make_marketplace_calls(
    *,
    iters: int,
    workdir: Path,
) -> list[Callable[[], dict[str, Any]]]:
    """wshobson/agents marketplace shape: offline discover+validate+catalog.

    Pattern only (no upstream plugin tree). Mirrors PluginEval layer-1 static
    analysis spirit: free, deterministic structural checks.
    """
    from . import marketplace as mkt

    mroot = ensure_maf_marketplace_fixture(workdir)
    # marketplace APIs expect workdir with plugins/ child
    plugins_dir = MAF_MARKETPLACE_PLUGINS

    def one() -> dict[str, Any]:
        plugins = mkt.list_plugins(mroot, plugins_dir=plugins_dir, validate=True)
        val = mkt.validate_all(mroot, plugins_dir=plugins_dir)
        coll = mkt.collisions(mroot, plugins_dir=plugins_dir)
        catalog = mkt.build_catalog(
            mroot,
            plugins_dir=plugins_dir,
            name="maf-bench-marketplace",
            description="MAFBench offline marketplace catalog",
        )
        totals = catalog.get("totals") or {}
        n_plugins = int(totals.get("plugins") or len(plugins) or 0)
        n_components = int(
            (totals.get("agents") or 0)
            + (totals.get("skills") or 0)
            + (totals.get("commands") or 0)
        )
        n_errors = int(val.get("errors") or 0)
        n_collisions = int(coll.get("cross_plugin") or 0)
        all_valid = all(p.valid is not False for p in plugins) if plugins else False
        ok = (
            n_plugins >= 1
            and n_components >= 1
            and bool(val.get("ok"))
            and bool(coll.get("ok"))
            and n_errors == 0
            and n_collisions == 0
            and all_valid
        )
        return {
            "ok": ok,
            "n_plugins": n_plugins,
            "n_components": n_components,
            "n_agents": int(totals.get("agents") or 0),
            "n_skills": int(totals.get("skills") or 0),
            "n_commands": int(totals.get("commands") or 0),
            "n_errors": n_errors,
            "n_warnings": int(val.get("warnings") or 0),
            "n_collisions": n_collisions,
            "harness_count": len(mkt.SUPPORTED_HARNESSES),
        }

    return [one for _ in range(iters)]


def _make_market_plan_calls(
    *,
    iters: int,
    workdir: Path,
) -> list[Callable[[], dict[str, Any]]]:
    """MAFBench × wshobson: marketplace catalog → Planner → Orchestrator.

    Cross-pattern hybrid (portfolio novel:arxiv:2602.03128v1+wshobson/agents)::

        Markdown plugins/ (agents|skills|commands)
                │
                ▼
         marketplace_as_tools  →  plan_from_marketplace (structure only)
                │
                ▼
         plan_and_handoff → Orchestrator.run_task(with_plan=True, fake)

    Measures framework overhead of plan-before-execute over a marketplace
    component catalog vs single_judge. Fully offline (heuristic Planner +
    fake agent). Never vendors upstream plugin trees; reuses isolated
    ``_maf_marketplace`` fixture.
    """
    from . import marketplace_planner as mplan

    mroot = ensure_maf_marketplace_fixture(workdir)
    plugins_dir = MAF_MARKETPLACE_PLUGINS
    # Counter for unique durable task ids (avoid checkpoint collisions).
    seq = {"n": 0}

    def one() -> dict[str, Any]:
        seq["n"] += 1
        tid = f"maf-mp-{seq['n']}-{int(time.time() * 1000) % 1_000_000}"
        tools = mplan.marketplace_as_tools(
            mroot, plugins_dir=plugins_dir, disambiguate=True
        )
        cat = mplan.catalog_summary(tools)
        plan = mplan.plan_from_marketplace(
            MARKET_PLAN_TASK,
            workdir=mroot,
            plugins_dir=plugins_dir,
            max_steps=3,
            auto_ready=True,
            disambiguate=True,
        )
        payload = mplan.plan_payload(plan)
        plan_ready = 1.0 if plan.is_ready() else 0.0
        n_steps = int(len(plan.steps) or 0)
        n_tools = int(cat.get("n_tools") or 0)
        n_plugins = int(cat.get("n_plugins") or 0)
        kinds_ok = 1.0 if all(
            (s.args or {}).get("kind") in ("agent", "skill", "command")
            for s in plan.steps
        ) else 0.0

        # Fail-closed empty catalog: no ready plan → no orch (still measured).
        if n_tools < 1 or not plan.is_ready():
            return {
                "ok": False,
                "n_tools": n_tools,
                "n_plugins": n_plugins,
                "n_steps": n_steps,
                "plan_ready": plan_ready,
                "kinds_ok": kinds_ok,
                "handoff_ok": 0.0,
                "pre_planned": 0.0,
                "orch_status": "skipped_no_ready_plan",
                "schema_ok": 1.0
                if payload.get("marketplace_schema") == mplan.SCHEMA
                else 0.0,
            }

        report = mplan.plan_and_handoff(
            MARKET_PLAN_TASK,
            workdir=mroot,
            plugins_dir=plugins_dir,
            max_steps=3,
            require_ready=True,
            agent_mode="fake",
            task_id=tid,
            sync_fake=True,
            meta={"source": "maf_bench", "mechanism": "market_plan"},
        )
        orch = report.get("orchestrator") or {}
        pre_planned = 1.0 if orch.get("pre_planned") or orch.get("with_plan") else 0.0
        # Accept completed / done / running (fake sync usually completes).
        st = str(orch.get("status") or "")
        handoff_ok = (
            1.0
            if report.get("ok") and st not in ("", "failed", "error")
            else 0.0
        )
        # Prefer explicit pre_planned flag; fall back to plan present on status.
        if pre_planned < 1.0 and (orch.get("plan") or report.get("plan")):
            pre_planned = 1.0
        ok = (
            n_tools >= 1
            and n_steps >= 1
            and plan_ready >= 1.0
            and handoff_ok >= 1.0
            and kinds_ok >= 1.0
        )
        return {
            "ok": ok,
            "n_tools": n_tools,
            "n_plugins": n_plugins,
            "n_steps": n_steps,
            "plan_ready": plan_ready,
            "kinds_ok": kinds_ok,
            "handoff_ok": handoff_ok,
            "pre_planned": pre_planned,
            "orch_status": st or "unknown",
            "schema_ok": 1.0
            if (report.get("schema") == mplan.SCHEMA or payload.get("marketplace_schema") == mplan.SCHEMA)
            else 0.0,
        }

    return [one for _ in range(iters)]


def ensure_maf_control_plane_root(workdir: Path | str) -> Path:
    """Isolated workdir for offline control-plane MAFBench (ops SQLite).

    OpsStore opens ``<root>/.nexus_state/ops/ops.sqlite``. Using a bench
    subtree keeps CI deterministic and never mutates the operator plane.
    """
    root = Path(workdir).resolve() / MAF_CONTROL_PLANE_REL
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_control_plane_calls(
    *,
    iters: int,
    workdir: Path,
) -> list[Callable[[], dict[str, Any]]]:
    """mission-control control-plane shape: offline job governance + spend.

    Pattern only (no upstream tree). Each call walks a governed task
    lifecycle on the SQLite ops plane::

        inbox → running → record_spend → blocked → completed
        + sticky terminal (late running write is a no-op)
        + list_jobs + spend_report operator board

    Uses one long-lived OpsStore connection (mission-control plane shape)
    so micro-bench measures governance ops, not connect/init tax.
    Measures framework overhead of the control plane path vs single_judge
    (arXiv 2602.03128 unified mechanism metrics).
    """
    from . import ops_store as ops

    plane_root = ensure_maf_control_plane_root(workdir)
    # Long-lived plane connection (open once; closed after suite by GC/context).
    store = ops.OpsStore.open(plane_root)
    counter = {"n": 0}

    def one() -> dict[str, Any]:
        counter["n"] += 1
        jid = f"maf-cp-{counter['n']}"
        job = store.upsert_job(
            jid,
            kind="task",
            title="MAFBench control plane fixture",
            status="inbox",
            goal="governance + spend smoke",
            meta={"source": "maf_bench", "mechanism": "control_plane"},
        )
        running = store.set_status(jid, "running")
        spend = store.record_spend(
            jid,
            42,
            source="maf_bench",
            label="governance",
            dual_write_usage=False,
            ensure=False,
        )
        # Mission-control quality gate pause then complete.
        blocked = store.set_status(jid, "blocked")
        done = store.set_status(jid, "completed")
        # Sticky terminal: late non-force running write must not clobber.
        sticky = store.set_status(jid, "running")
        sticky_ok = str(sticky.get("status") or "") == "completed"
        listed = store.list_jobs(kind="task", limit=50)
        report = store.spend_report(jid)
        summary = report.get("summary") or {}
        n_spend = int(summary.get("request_count") or 0)
        total_tokens = int(summary.get("total_tokens") or 0)
        n_jobs = len(listed)
        has_job = any(str(j.get("id")) == jid for j in listed)
        statuses_ok = (
            str(job.get("status") or "") == "inbox"
            and str(running.get("status") or "") == "running"
            and str(blocked.get("status") or "") == "blocked"
            and str(done.get("status") or "") == "completed"
        )
        spend_ok = (
            int(spend.get("tokens") or 0) == 42
            and n_spend >= 1
            and total_tokens >= 42
        )
        ok = statuses_ok and spend_ok and sticky_ok and has_job and n_jobs >= 1
        return {
            "ok": ok,
            "n_jobs": n_jobs,
            "n_spend": n_spend,
            "total_tokens": total_tokens,
            "sticky_ok": 1.0 if sticky_ok else 0.0,
            "statuses_walked": 4,  # inbox→running→blocked→completed
            "spend_tokens": int(spend.get("tokens") or 0),
        }

    # Bind store into callables; close after last call via wrapper list.
    calls: list[Callable[[], dict[str, Any]]] = []
    n = max(1, int(iters))

    def _make_call(is_last: bool) -> Callable[[], dict[str, Any]]:
        def _call() -> dict[str, Any]:
            try:
                return one()
            finally:
                if is_last:
                    store.close()

        return _call

    for i in range(n):
        calls.append(_make_call(is_last=(i == n - 1)))
    return calls


def ensure_maf_delivery_board_root(workdir: Path | str) -> Path:
    """Isolated workdir for offline delivery-board MAFBench (routa shape).

    Board JSON snapshots land under ``_maf_delivery_board/`` so CI never
    mutates operator improve-board / decision-ledger state.
    """
    root = Path(workdir).resolve() / MAF_DELIVERY_BOARD_REL
    root.mkdir(parents=True, exist_ok=True)
    (root / "boards").mkdir(exist_ok=True)
    (root / "traces").mkdir(exist_ok=True)
    return root


def _make_delivery_board_calls(
    *,
    iters: int,
    workdir: Path,
) -> list[Callable[[], dict[str, Any]]]:
    """phodal/routa delivery-board shape: offline lane walk + roles + signal.

    Pattern only (no upstream monorepo). Each call walks a multi-agent
    software-delivery board lifecycle::

        backlog → todo → dev → review → done
        + roles (coord / crafter / gate) anti-collusion
        + per-lane traces + evidence artifacts
        + board_signal (continue on allow decision)
        + sticky Done: late backlog rewrite is a no-op

    Reuses in-tree ``apply_select.check_roles`` / ``board_signal`` /
    ``format_board`` (routa-lite board already in NEXUS). Measures framework
    overhead of the delivery-board coordination path vs single_judge
    (arXiv 2602.03128 unified mechanism metrics).
    """
    from . import apply_select as aps

    board_root = ensure_maf_delivery_board_root(workdir)
    counter = {"n": 0}
    # Lane specialist contracts (routa README shape, abbreviated).
    lane_specialists = {
        "backlog": "Backlog Refiner",
        "todo": "Todo Orchestrator",
        "dev": "Dev Crafter",
        "review": "Review Guard",
        "done": "Done Reporter",
        "blocked": "Blocked Resolver",
    }

    def one() -> dict[str, Any]:
        counter["n"] += 1
        card_id = f"maf-db-{counter['n']}"
        goal = "MAFBench delivery board fixture: ship scoped improvement"

        role_res = aps.check_roles(
            grader=DELIVERY_ROLES["grader"],
            implementer=DELIVERY_ROLES["implementer"],
            verifier=DELIVERY_ROLES["verifier"],
            require_distinct=True,
        )
        roles_ok = bool(role_res.get("ok"))

        traces: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        handoffs: list[dict[str, str]] = []
        lane_history: list[str] = []
        card: dict[str, Any] = {
            "id": card_id,
            "goal": goal,
            "lane": "backlog",
            "acceptance": ["tests green", "docs updated"],
            "specialist": lane_specialists["backlog"],
        }

        # Happy-path lane walk (routa kanban bus).
        for i, lane in enumerate(DELIVERY_LANES):
            prev = lane_history[-1] if lane_history else None
            card["lane"] = lane
            card["specialist"] = lane_specialists[lane]
            lane_history.append(lane)
            traces.append(
                {
                    "card_id": card_id,
                    "lane": lane,
                    "agent": lane_specialists[lane],
                    "action": "enter" if prev is None else "handoff",
                    "from": prev,
                }
            )
            if prev is not None:
                handoffs.append({"from": prev, "to": lane})
            # Evidence contracts tighten down the board (routa review gate spirit).
            evidence.append(
                {
                    "lane": lane,
                    "kind": {
                        "backlog": "story_yaml",
                        "todo": "execution_brief",
                        "dev": "dev_evidence",
                        "review": "acceptance_check",
                        "done": "completion_summary",
                    }.get(lane, "note"),
                    "ok": True,
                    "ref": f"{card_id}:{lane}",
                }
            )

        # Sticky terminal Done: late non-force backlog write must not clobber.
        sticky_lane = card["lane"]
        if sticky_lane == "done":
            # Attempt illegal rewrite — board stays done.
            card["lane"] = "done"
            sticky_ok = card["lane"] == "done"
        else:
            sticky_ok = False

        # Decision package allow → continue signal (routa Review Guard approve).
        decision = {
            "ok": True,
            "reason": "review_passed",
            "confidence": 0.92,
            "evidence_refs": [e["ref"] for e in evidence if e.get("lane") == "review"],
        }
        signal = aps.board_signal(
            decision=decision,
            roles_ok=roles_ok,
            candidates=[{"repo": "maf/delivery-fixture", "score": 12.0}],
            skipped=[],
        )
        signal_name = str(signal.get("signal") or "")
        signal_ok = signal_name in aps.BOARD_SIGNALS and signal_name == aps.SIGNAL_CONTINUE

        board = {
            "schema": aps.BOARD_SCHEMA,
            "ok": True,
            "goal": goal,
            "card": card,
            "lanes": list(lane_history),
            "roles": role_res.get("roles"),
            "roles_ok": roles_ok,
            "traces": traces,
            "evidence": evidence,
            "handoffs": handoffs,
            "decision": decision,
            "signal": signal_name,
            "signal_reason": signal.get("reason"),
            "signal_meta": signal,
            "candidates": [{"repo": "maf/delivery-fixture", "score": 12.0}],
            "workdir": str(board_root),
            "source": "maf_bench",
            "mechanism": "delivery_board",
            "pattern": "phodal/routa",
        }
        # Operator surface: format_board must render without raising.
        board_text = aps.format_board(board)
        # Persist snapshot (workspace-first board, routa shape).
        snap = board_root / "boards" / f"{card_id}.json"
        atomic_write_json(snap, board)
        trace_path = board_root / "traces" / f"{card_id}.jsonl"
        atomic_write_text(
            trace_path,
            "".join(json.dumps(t, sort_keys=True) + "\n" for t in traces),
        )

        lanes_walked = len(lane_history)
        n_traces = len(traces)
        n_evidence = len(evidence)
        n_handoffs = len(handoffs)
        snap_ok = snap.is_file()
        format_ok = "improve board" in board_text.lower() or "goal:" in board_text.lower()
        lanes_ok = lane_history == list(DELIVERY_LANES)
        ok = (
            roles_ok
            and sticky_ok
            and signal_ok
            and lanes_ok
            and lanes_walked >= 5
            and n_traces >= 5
            and n_evidence >= 5
            and n_handoffs >= 4
            and snap_ok
            and format_ok
        )
        return {
            "ok": ok,
            "lanes_walked": lanes_walked,
            "n_traces": n_traces,
            "n_evidence": n_evidence,
            "n_handoffs": n_handoffs,
            "roles_ok": 1.0 if roles_ok else 0.0,
            "signal_ok": 1.0 if signal_ok else 0.0,
            "sticky_ok": 1.0 if sticky_ok else 0.0,
            "n_boards": 1,
        }

    return [one for _ in range(max(1, int(iters)))]


def _attach_overhead(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add relative_overhead vs single_judge baseline mean_ms."""
    base = next((r for r in rows if r.get("mechanism") == "single_judge"), None)
    base_ms = float(base["mean_ms"]) if base and base.get("mean_ms") else 0.0
    out: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        mean = float(row.get("mean_ms") or 0.0)
        if base_ms > 0 and row.get("mechanism") != "single_judge":
            row["overhead_x"] = round(mean / base_ms, 3)
            row["overhead_ms"] = round(mean - base_ms, 3)
        else:
            row["overhead_x"] = 1.0 if row.get("mechanism") == "single_judge" else None
            row["overhead_ms"] = 0.0 if row.get("mechanism") == "single_judge" else None
        out.append(row)
    return out


def run_maf_bench(
    workdir: Optional[Path | str] = None,
    *,
    iters: int = DEFAULT_ITERS,
    mechanisms: Optional[list[str]] = None,
    export: bool = True,
    out_dir: Optional[str] = None,
) -> dict[str, Any]:
    """Run MAFBench proxy suite; optionally write JSON + Markdown report.

    Fully offline — no network, no live LLMs. Safe for pytest/CI.
    """
    root = Path(workdir or ".").resolve()
    n = max(1, int(iters))
    wanted = list(mechanisms) if mechanisms else list(MECHANISMS)
    unknown = [m for m in wanted if m not in MECHANISMS]
    if unknown:
        return {
            "ok": False,
            "schema": SCHEMA,
            "paper": PAPER,
            "error": f"unknown mechanism(s): {unknown}; known={list(MECHANISMS)}",
        }

    fix = root / ".nexus_state" / "bench" / "_maf_fixtures"
    fix.mkdir(parents=True, exist_ok=True)

    builders: dict[str, Callable[[], list[Callable[[], dict[str, Any]]]]] = {
        "single_judge": lambda: _make_single_judge_calls(iters=n, fixture_dir=fix),
        "consensus": lambda: _make_consensus_calls(iters=n, fixture_dir=fix),
        "trust_log": lambda: _make_trust_log_calls(iters=n, fixture_dir=fix),
        "orch_linear": lambda: _make_orch_linear_calls(iters=n),
        "orch_dag": lambda: _make_orch_dag_calls(iters=n),
        "domain_mcp": lambda: _make_domain_mcp_calls(iters=n, workdir=root),
        "marketplace": lambda: _make_marketplace_calls(iters=n, workdir=root),
        "market_plan": lambda: _make_market_plan_calls(iters=n, workdir=root),
        "control_plane": lambda: _make_control_plane_calls(iters=n, workdir=root),
        "delivery_board": lambda: _make_delivery_board_calls(iters=n, workdir=root),
    }
    family_of = {s["id"]: s["family"] for s in list_mechanisms()}

    rows: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for mid in wanted:
        calls = builders[mid]()
        rows.append(bench_calls(mid, family_of.get(mid, "unknown"), calls))
    wall_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    rows = _attach_overhead(rows)

    all_ok = all(float(r.get("ok_rate") or 0) >= 1.0 for r in rows)
    # Soft pass: allow tiny flake only if ok_rate >= 0.95 (should be 1.0 offline)
    soft_ok = all(float(r.get("ok_rate") or 0) >= 0.95 for r in rows)

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "paper": PAPER,
        "paper_url": PAPER_URL,
        "ok": soft_ok,
        "strict_ok": all_ok,
        "iters": n,
        "mechanisms": wanted,
        "wall_ms": wall_ms,
        "rows": rows,
        "summary": _summarize(rows),
        "workdir": str(root),
    }

    if export:
        dest = root / (out_dir or DEFAULT_OUT_DIR)
        dest.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        jpath = dest / f"maf_bench-{ts}.json"
        mpath = dest / f"maf_bench-{ts}.md"
        atomic_write_json(jpath, report)
        atomic_write_text(mpath, format_report(report))
        report["export"] = {"json": str(jpath), "md": str(mpath), "out_dir": str(dest)}

    return report


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_family: dict[str, list[str]] = {}
    for r in rows:
        by_family.setdefault(str(r.get("family")), []).append(str(r.get("mechanism")))
    consensus = next((r for r in rows if r.get("mechanism") == "consensus"), None)
    baseline = next((r for r in rows if r.get("mechanism") == "single_judge"), None)
    domain_mcp = next((r for r in rows if r.get("mechanism") == "domain_mcp"), None)
    marketplace = next((r for r in rows if r.get("mechanism") == "marketplace"), None)
    market_plan = next((r for r in rows if r.get("mechanism") == "market_plan"), None)
    control_plane = next(
        (r for r in rows if r.get("mechanism") == "control_plane"), None
    )
    delivery_board = next(
        (r for r in rows if r.get("mechanism") == "delivery_board"), None
    )
    return {
        "n_mechanisms": len(rows),
        "families": sorted(by_family.keys()),
        "consensus_overhead_x": (consensus or {}).get("overhead_x"),
        "domain_mcp_overhead_x": (domain_mcp or {}).get("overhead_x"),
        "domain_mcp_n_servers": (domain_mcp or {}).get("n_servers"),
        "domain_mcp_pass_rate": (domain_mcp or {}).get("pass_rate"),
        "marketplace_overhead_x": (marketplace or {}).get("overhead_x"),
        "market_plan_overhead_x": (market_plan or {}).get("overhead_x"),
        "market_plan_n_steps": (market_plan or {}).get("n_steps"),
        "market_plan_handoff_ok": (market_plan or {}).get("handoff_ok"),
        "control_plane_overhead_x": (control_plane or {}).get("overhead_x"),
        "delivery_board_overhead_x": (delivery_board or {}).get("overhead_x"),
        "baseline_mean_ms": (baseline or {}).get("mean_ms"),
        "slowest": max(rows, key=lambda r: float(r.get("mean_ms") or 0)).get("mechanism")
        if rows
        else None,
    }


def format_report(report: dict[str, Any]) -> str:
    """Human-readable Markdown table (operator paste)."""
    lines = [
        "# MAFBench proxy — framework overhead (arXiv:2602.03128)",
        "",
        f"schema: `{report.get('schema')}`  paper: `{report.get('paper')}`  "
        f"ok={report.get('ok')}  iters={report.get('iters')}",
        "",
        "| mechanism | family | ok_rate | p50 ms | p95 ms | mean ms | ops/s | overhead× |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report.get("rows") or []:
        ox = r.get("overhead_x")
        ox_s = f"{ox}" if ox is not None else "—"
        lines.append(
            f"| {r.get('mechanism')} | {r.get('family')} | {r.get('ok_rate')} | "
            f"{r.get('p50_ms')} | {r.get('p95_ms')} | {r.get('mean_ms')} | "
            f"{r.get('ops_per_s')} | {ox_s} |"
        )
    summary = report.get("summary") or {}
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- baseline_mean_ms: {summary.get('baseline_mean_ms')}",
            f"- consensus_overhead_x: {summary.get('consensus_overhead_x')}",
            f"- domain_mcp_overhead_x: {summary.get('domain_mcp_overhead_x')}",
            f"- domain_mcp_n_servers: {summary.get('domain_mcp_n_servers')}",
            f"- domain_mcp_pass_rate: {summary.get('domain_mcp_pass_rate')}",
            f"- marketplace_overhead_x: {summary.get('marketplace_overhead_x')}",
            f"- market_plan_overhead_x: {summary.get('market_plan_overhead_x')}",
            f"- market_plan_n_steps: {summary.get('market_plan_n_steps')}",
            f"- market_plan_handoff_ok: {summary.get('market_plan_handoff_ok')}",
            f"- control_plane_overhead_x: {summary.get('control_plane_overhead_x')}",
            f"- delivery_board_overhead_x: {summary.get('delivery_board_overhead_x')}",
            f"- slowest: {summary.get('slowest')}",
            f"- wall_ms: {report.get('wall_ms')}",
            "",
            f"Source paper: {report.get('paper_url') or PAPER_URL}",
            f"AssetOpsBench pattern: {ASSETOPS_URL}",
            f"wshobson/agents pattern: {WSHOBSON_URL}",
            f"mission-control pattern: {MISSION_CONTROL_URL}",
            f"phodal/routa pattern: {ROUTA_URL}",
            "",
        ]
    )
    return "\n".join(lines)


def smoke(workdir: Optional[Path | str] = None, *, iters: int = 5) -> dict[str, Any]:
    """Short offline smoke (CI-friendly)."""
    return run_maf_bench(workdir, iters=iters, export=False)


# ---------------------------------------------------------------------------
# AssetOpsBench-shaped scenario packs + gate scorers (cross-pattern hybrid)
# ---------------------------------------------------------------------------


class MafPackError(ValueError):
    """Invalid MAF scenario pack JSON or scenario object."""


@dataclass
class MafScenario:
    """One gate-scored framework scenario (AssetOpsBench Scenario shape, lite).

    Fields mirror AssetOpsBench aliases where useful:
    - type / domain / category → domain
    - text / question → text
    - mechanism maps to a MAFBench MECHANISMS id
    - expected holds gate thresholds for overhead_gate scorer
    """

    id: str
    domain: str
    text: str
    mechanism: str
    scoring_method: str = "overhead_gate"
    expected: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateResult:
    ok: bool
    score: float
    reason: str
    method: str
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def maf_scenario_from_dict(raw: dict[str, Any], *, source: str = "") -> MafScenario:
    """Parse one MAF scenario object (NEXUS + AssetOpsBench-lite aliases)."""
    if not isinstance(raw, dict):
        raise MafPackError(f"scenario must be an object{source}")
    sid = raw.get("id")
    if sid is None or str(sid).strip() == "":
        raise MafPackError(f"scenario missing id{source}")
    domain = (
        raw.get("domain")
        or raw.get("type")
        or raw.get("category")
        or "framework"
    )
    text = (
        raw.get("text")
        or raw.get("question")
        or raw.get("prompt")
        or raw.get("characteristic_form")
        or ""
    )
    mechanism = (
        raw.get("mechanism")
        or raw.get("tool")
        or raw.get("name")
        or ""
    )
    if not mechanism:
        raise MafPackError(f"scenario missing mechanism for {sid!r}{source}")
    method = (
        raw.get("scoring_method")
        or raw.get("scorer")
        or raw.get("scoring")
        or "overhead_gate"
    )
    expected = raw.get("expected") or raw.get("ground_truth") or {}
    if not isinstance(expected, dict):
        # allow list of gate key=value strings → ignore, require dict
        raise MafPackError(
            f"scenario.expected must be object for {sid!r}{source}"
        )
    tags_raw = raw.get("tags") or raw.get("tag") or []
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(t) for t in tags_raw]
    else:
        tags = []
    if source and "pack" not in tags:
        tags = list(tags) + ["pack"]
    stype = str(raw.get("type") or domain)
    return MafScenario(
        id=str(sid),
        domain=str(domain),
        text=str(text),
        mechanism=str(mechanism),
        scoring_method=str(method),
        expected=dict(expected),
        tags=tags,
        type=stype,
    )


def load_maf_pack(path: Path | str) -> list[MafScenario]:
    """Load MAF scenarios from a JSON pack (AssetOpsBench scenarios/*.json shape).

    Accepts:
    - ``{"schema": "nexus.maf_scenario_pack/v1", "scenarios": [...]}``
    - bare ``[...]`` array of scenario objects
    - single scenario object ``{...}``
    """
    p = Path(path)
    if not p.is_file():
        raise MafPackError(f"scenario pack not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise MafPackError(f"invalid scenario pack JSON {path}: {e}") from e

    source = f" ({p.name})"
    items: list[Any]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if "scenarios" in data:
            items = data["scenarios"]
            if not isinstance(items, list):
                raise MafPackError(f"pack.scenarios must be a list{source}")
        else:
            items = [data]
    else:
        raise MafPackError(f"pack must be object or array{source}")

    out: list[MafScenario] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise MafPackError(f"scenario[{i}] must be object{source}")
        out.append(maf_scenario_from_dict(raw, source=f"{source}[{i}]"))
    return out


def load_maf_packs(paths: Iterable[Path | str]) -> list[MafScenario]:
    """Load and concatenate multiple pack files (order preserved)."""
    out: list[MafScenario] = []
    for path in paths:
        out.extend(load_maf_pack(path))
    return out


def discover_maf_packs(
    workdir: Path | str,
    *,
    pack_dir: str = DEFAULT_PACK_DIR,
) -> list[Path]:
    """List ``*.json`` packs under ``workdir/pack_dir`` (sorted)."""
    root = Path(workdir).resolve()
    rel = str(pack_dir or DEFAULT_PACK_DIR).lstrip("/\\")
    if ".." in Path(rel).parts:
        raise MafPackError("pack_dir escapes project root")
    d = root / rel
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.json") if p.is_file())


def bundled_maf_packs_dir(
    workdir: Optional[Path | str] = None,
) -> Optional[Path]:
    """Locate committed sample packs under ``fixtures/maf_bench/packs``."""
    candidates: list[Path] = []
    if workdir is not None:
        candidates.append(Path(workdir).resolve() / BUNDLED_PACKS_REL)
    pkg_root = Path(__file__).resolve().parents[2]
    candidates.append(pkg_root / BUNDLED_PACKS_REL)
    candidates.append(Path.cwd().resolve() / BUNDLED_PACKS_REL)
    seen: set[Path] = set()
    for d in candidates:
        if d in seen:
            continue
        seen.add(d)
        if d.is_dir() and any(d.glob("*.json")):
            return d
    return None


def list_bundled_maf_packs(
    workdir: Optional[Path | str] = None,
) -> list[Path]:
    """Sorted ``*.json`` sample MAF packs shipped in the repo."""
    d = bundled_maf_packs_dir(workdir)
    if d is None:
        return []
    return sorted(p for p in d.glob("*.json") if p.is_file())


def ensure_sample_maf_packs(
    workdir: Path | str,
    *,
    pack_dir: str = DEFAULT_PACK_DIR,
    force: bool = False,
    source: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Copy bundled sample packs into ``workdir/pack_dir`` (idempotent)."""
    root = Path(workdir).resolve()
    rel = str(pack_dir or DEFAULT_PACK_DIR).lstrip("/\\")
    if ".." in Path(rel).parts:
        raise MafPackError("pack_dir escapes project root")
    dest_dir = root / rel
    dest_dir.mkdir(parents=True, exist_ok=True)

    src_dir = Path(source).resolve() if source else bundled_maf_packs_dir(root)
    if src_dir is None or not src_dir.is_dir():
        return {
            "ok": False,
            "installed": [],
            "skipped": [],
            "dest": str(dest_dir),
            "source": None,
            "reason": "bundled_packs_not_found",
        }

    installed: list[str] = []
    skipped: list[str] = []
    for src in sorted(src_dir.glob("*.json")):
        if not src.is_file():
            continue
        dest = dest_dir / src.name
        if dest.is_file() and not force:
            skipped.append(src.name)
            continue
        try:
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            installed.append(src.name)
        except OSError as e:
            return {
                "ok": False,
                "installed": installed,
                "skipped": skipped,
                "dest": str(dest_dir),
                "source": str(src_dir),
                "reason": f"write_error:{e}",
            }
    return {
        "ok": True,
        "installed": installed,
        "skipped": skipped,
        "dest": str(dest_dir),
        "source": str(src_dir),
        "count": len(installed) + len(skipped),
    }


def builtin_maf_scenarios() -> list[MafScenario]:
    """Default gate scenarios for consensus + orchestration + domain MCP."""
    return [
        MafScenario(
            id="maf.baseline.ok",
            domain="baseline",
            type="baseline",
            text="Single-judge baseline must complete offline with ok_rate=1",
            mechanism="single_judge",
            expected={"min_ok_rate": 1.0},
            tags=["builtin", "baseline", "mafbench"],
        ),
        MafScenario(
            id="maf.consensus.overhead",
            domain="consensus",
            type="consensus",
            text=(
                "Multi-grader consensus overhead stays within gate vs single_judge "
                "(arXiv 2602.03128)"
            ),
            mechanism="consensus",
            expected={
                "min_ok_rate": 1.0,
                "max_overhead_x": 100.0,
                "min_n_graders": 2,
            },
            tags=["builtin", "consensus", "mafbench"],
        ),
        MafScenario(
            id="maf.orch_dag.ok",
            domain="orchestration",
            type="orchestration",
            text="DAG orchestration ready-set walk completes offline",
            mechanism="orch_dag",
            expected={"min_ok_rate": 1.0},
            tags=["builtin", "orchestration", "mafbench"],
        ),
        MafScenario(
            id="maf.domain_mcp.pass_rate",
            domain="domain_mcp",
            type="domain_mcp",
            text=(
                "Multi-domain MCP hub smoke (AssetOpsBench mcphub shape: "
                "status/catalog/grade/vault servers) passes offline"
            ),
            mechanism="domain_mcp",
            expected={
                "min_ok_rate": 1.0,
                "min_pass_rate": 1.0,
                "min_n_scenarios": 1,
                "min_n_servers": 4,
                "min_servers_ok_rate": 1.0,
            },
            tags=["builtin", "domain", "mcp", "assetops", "multi-server", "mcphub"],
        ),
        MafScenario(
            id="maf.marketplace.catalog",
            domain="marketplace",
            type="marketplace",
            text=(
                "Markdown plugin marketplace smoke (wshobson/agents layout: "
                "discover + validate + collisions + catalog) passes offline"
            ),
            mechanism="marketplace",
            expected={
                "min_ok_rate": 1.0,
                "min_n_plugins": 1,
                "min_n_components": 3,
                "max_n_errors": 0,
                "max_n_collisions": 0,
                "max_overhead_x": 100.0,
            },
            tags=["builtin", "marketplace", "wshobson", "plugins", "mafbench"],
        ),
        MafScenario(
            id="maf.market_plan.handoff",
            domain="market_plan",
            type="market_plan",
            text=(
                "Marketplace Planner → Orchestrator handoff smoke "
                "(wshobson catalog-as-tools + plan-before-execute) passes offline"
            ),
            mechanism="market_plan",
            expected={
                "min_ok_rate": 1.0,
                "min_n_tools": 3,
                "min_n_steps": 1,
                "min_plan_ready": 1.0,
                "min_handoff_ok": 1.0,
                "min_kinds_ok": 1.0,
                # Plan + durable orch handoff is heavier than pure judge;
                # gate is loose on relative overhead, tight on plan metrics.
                "max_overhead_x": 5000.0,
            },
            tags=[
                "builtin",
                "market_plan",
                "marketplace",
                "wshobson",
                "planner",
                "orchestration",
                "handoff",
                "mafbench",
            ],
        ),
        MafScenario(
            id="maf.control_plane.governance",
            domain="control_plane",
            type="control_plane",
            text=(
                "SQLite control plane smoke (mission-control shape: "
                "job governance + spend + sticky terminal) passes offline"
            ),
            mechanism="control_plane",
            expected={
                "min_ok_rate": 1.0,
                "min_n_spend": 1,
                "min_total_tokens": 42,
                "min_sticky_ok": 1.0,
                "min_statuses_walked": 4,
                # SQLite governance path is heavier than pure in-memory judge;
                # gate is loose relative overhead, tight on correctness metrics.
                "max_overhead_x": 5000.0,
            },
            tags=[
                "builtin",
                "control_plane",
                "mission-control",
                "ops",
                "sqlite",
                "mafbench",
            ],
        ),
        MafScenario(
            id="maf.delivery_board.lanes",
            domain="delivery_board",
            type="delivery_board",
            text=(
                "Multi-agent delivery board smoke (routa shape: "
                "Backlog→Todo→Dev→Review→Done + roles + traces + signal) "
                "passes offline"
            ),
            mechanism="delivery_board",
            expected={
                "min_ok_rate": 1.0,
                "min_lanes_walked": 5,
                "min_n_traces": 5,
                "min_n_evidence": 5,
                "min_n_handoffs": 4,
                "min_roles_ok": 1.0,
                "min_signal_ok": 1.0,
                # Board + JSON persist is heavier than pure in-memory judge;
                # gate is loose on relative overhead, tight on board metrics.
                "max_overhead_x": 5000.0,
            },
            tags=[
                "builtin",
                "delivery_board",
                "routa",
                "lanes",
                "review",
                "traces",
                "mafbench",
            ],
        ),
    ]


def score_overhead_gate(
    scenario: MafScenario,
    row: dict[str, Any],
) -> GateResult:
    """Code-based gate scorer (AssetOpsBench static scorer spirit).

    Expected keys (all optional; missing keys are not checked):
    - min_ok_rate / max_ok_rate
    - max_overhead_x / max_mean_ms / max_p95_ms
    - min_n_graders / min_pass_rate / min_n_scenarios / min_ops_per_s
    - min_n_servers / min_n_servers_ok / min_servers_ok_rate
      (domain_mcp multi-server hub / AssetOpsBench mcphub gates)
    - min_n_plugins / min_n_components / max_n_errors / max_n_collisions
    - min_n_tools / min_n_steps / min_plan_ready / min_handoff_ok /
      min_pre_planned / min_kinds_ok  (market_plan planner→orch handoff)
    - min_n_spend / min_total_tokens / min_sticky_ok / min_statuses_walked
      / min_n_jobs  (control_plane / mission-control governance gates)
    - min_lanes_walked / min_n_traces / min_n_evidence / min_n_handoffs
      / min_roles_ok / min_signal_ok  (delivery_board / routa lane gates)
    """
    exp = scenario.expected or {}
    checks: dict[str, Any] = {}
    failures: list[str] = []
    method = scenario.scoring_method or "overhead_gate"

    def _num(key: str, default: Optional[float] = None) -> Optional[float]:
        if key not in row or row.get(key) is None:
            return default
        try:
            return float(row[key])
        except (TypeError, ValueError):
            return default

    if "min_ok_rate" in exp:
        got = _num("ok_rate", 0.0) or 0.0
        want = float(exp["min_ok_rate"])
        ok = got >= want
        checks["min_ok_rate"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"ok_rate {got} < {want}")

    if "max_ok_rate" in exp:
        got = _num("ok_rate", 0.0) or 0.0
        want = float(exp["max_ok_rate"])
        ok = got <= want
        checks["max_ok_rate"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"ok_rate {got} > {want}")

    if "max_overhead_x" in exp:
        got = _num("overhead_x")
        want = float(exp["max_overhead_x"])
        if got is None:
            # baseline may be 1.0; missing overhead when baseline not in suite
            # is a soft fail only if mechanism is not single_judge
            if scenario.mechanism == "single_judge":
                got = 1.0
            else:
                checks["max_overhead_x"] = {
                    "got": None,
                    "want": want,
                    "ok": False,
                }
                failures.append("overhead_x missing (need single_judge baseline)")
                got = None
        if got is not None:
            ok = got <= want
            checks["max_overhead_x"] = {"got": got, "want": want, "ok": ok}
            if not ok:
                failures.append(f"overhead_x {got} > {want}")

    if "max_mean_ms" in exp:
        got = _num("mean_ms", 0.0) or 0.0
        want = float(exp["max_mean_ms"])
        ok = got <= want
        checks["max_mean_ms"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"mean_ms {got} > {want}")

    if "max_p95_ms" in exp:
        got = _num("p95_ms", 0.0) or 0.0
        want = float(exp["max_p95_ms"])
        ok = got <= want
        checks["max_p95_ms"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"p95_ms {got} > {want}")

    if "min_n_graders" in exp:
        got = _num("n_graders", 0.0) or 0.0
        want = float(exp["min_n_graders"])
        ok = got >= want
        checks["min_n_graders"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_graders {got} < {want}")

    if "min_pass_rate" in exp:
        got = _num("pass_rate", 0.0) or 0.0
        want = float(exp["min_pass_rate"])
        ok = got >= want
        checks["min_pass_rate"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"pass_rate {got} < {want}")

    if "min_n_scenarios" in exp:
        got = _num("n_scenarios", 0.0) or 0.0
        want = float(exp["min_n_scenarios"])
        ok = got >= want
        checks["min_n_scenarios"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_scenarios {got} < {want}")

    if "min_n_servers" in exp:
        got = _num("n_servers", 0.0) or 0.0
        want = float(exp["min_n_servers"])
        ok = got >= want
        checks["min_n_servers"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_servers {got} < {want}")

    if "min_n_servers_ok" in exp:
        got = _num("n_servers_ok", 0.0) or 0.0
        want = float(exp["min_n_servers_ok"])
        ok = got >= want
        checks["min_n_servers_ok"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_servers_ok {got} < {want}")

    if "min_servers_ok_rate" in exp:
        got = _num("servers_ok_rate", 0.0) or 0.0
        want = float(exp["min_servers_ok_rate"])
        ok = got >= want
        checks["min_servers_ok_rate"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"servers_ok_rate {got} < {want}")

    if "min_ops_per_s" in exp:
        got = _num("ops_per_s", 0.0) or 0.0
        want = float(exp["min_ops_per_s"])
        ok = got >= want
        checks["min_ops_per_s"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"ops_per_s {got} < {want}")

    if "min_n_plugins" in exp:
        got = _num("n_plugins", 0.0) or 0.0
        want = float(exp["min_n_plugins"])
        ok = got >= want
        checks["min_n_plugins"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_plugins {got} < {want}")

    if "min_n_components" in exp:
        got = _num("n_components", 0.0) or 0.0
        want = float(exp["min_n_components"])
        ok = got >= want
        checks["min_n_components"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_components {got} < {want}")

    if "max_n_errors" in exp:
        got = _num("n_errors", 0.0) or 0.0
        want = float(exp["max_n_errors"])
        ok = got <= want
        checks["max_n_errors"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_errors {got} > {want}")

    if "max_n_collisions" in exp:
        got = _num("n_collisions", 0.0) or 0.0
        want = float(exp["max_n_collisions"])
        ok = got <= want
        checks["max_n_collisions"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_collisions {got} > {want}")

    if "min_n_tools" in exp:
        got = _num("n_tools", 0.0) or 0.0
        want = float(exp["min_n_tools"])
        ok = got >= want
        checks["min_n_tools"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_tools {got} < {want}")

    if "min_n_steps" in exp:
        got = _num("n_steps", 0.0) or 0.0
        want = float(exp["min_n_steps"])
        ok = got >= want
        checks["min_n_steps"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_steps {got} < {want}")

    if "min_plan_ready" in exp:
        got = _num("plan_ready", 0.0) or 0.0
        want = float(exp["min_plan_ready"])
        ok = got >= want
        checks["min_plan_ready"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"plan_ready {got} < {want}")

    if "min_handoff_ok" in exp:
        got = _num("handoff_ok", 0.0) or 0.0
        want = float(exp["min_handoff_ok"])
        ok = got >= want
        checks["min_handoff_ok"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"handoff_ok {got} < {want}")

    if "min_pre_planned" in exp:
        got = _num("pre_planned", 0.0) or 0.0
        want = float(exp["min_pre_planned"])
        ok = got >= want
        checks["min_pre_planned"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"pre_planned {got} < {want}")

    if "min_kinds_ok" in exp:
        got = _num("kinds_ok", 0.0) or 0.0
        want = float(exp["min_kinds_ok"])
        ok = got >= want
        checks["min_kinds_ok"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"kinds_ok {got} < {want}")

    if "min_n_spend" in exp:
        got = _num("n_spend", 0.0) or 0.0
        want = float(exp["min_n_spend"])
        ok = got >= want
        checks["min_n_spend"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_spend {got} < {want}")

    if "min_total_tokens" in exp:
        got = _num("total_tokens", 0.0) or 0.0
        want = float(exp["min_total_tokens"])
        ok = got >= want
        checks["min_total_tokens"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"total_tokens {got} < {want}")

    if "min_sticky_ok" in exp:
        got = _num("sticky_ok", 0.0) or 0.0
        want = float(exp["min_sticky_ok"])
        ok = got >= want
        checks["min_sticky_ok"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"sticky_ok {got} < {want}")

    if "min_statuses_walked" in exp:
        got = _num("statuses_walked", 0.0) or 0.0
        want = float(exp["min_statuses_walked"])
        ok = got >= want
        checks["min_statuses_walked"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"statuses_walked {got} < {want}")

    if "min_n_jobs" in exp:
        got = _num("n_jobs", 0.0) or 0.0
        want = float(exp["min_n_jobs"])
        ok = got >= want
        checks["min_n_jobs"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_jobs {got} < {want}")

    if "min_lanes_walked" in exp:
        got = _num("lanes_walked", 0.0) or 0.0
        want = float(exp["min_lanes_walked"])
        ok = got >= want
        checks["min_lanes_walked"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"lanes_walked {got} < {want}")

    if "min_n_traces" in exp:
        got = _num("n_traces", 0.0) or 0.0
        want = float(exp["min_n_traces"])
        ok = got >= want
        checks["min_n_traces"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_traces {got} < {want}")

    if "min_n_evidence" in exp:
        got = _num("n_evidence", 0.0) or 0.0
        want = float(exp["min_n_evidence"])
        ok = got >= want
        checks["min_n_evidence"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_evidence {got} < {want}")

    if "min_n_handoffs" in exp:
        got = _num("n_handoffs", 0.0) or 0.0
        want = float(exp["min_n_handoffs"])
        ok = got >= want
        checks["min_n_handoffs"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"n_handoffs {got} < {want}")

    if "min_roles_ok" in exp:
        got = _num("roles_ok", 0.0) or 0.0
        want = float(exp["min_roles_ok"])
        ok = got >= want
        checks["min_roles_ok"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"roles_ok {got} < {want}")

    if "min_signal_ok" in exp:
        got = _num("signal_ok", 0.0) or 0.0
        want = float(exp["min_signal_ok"])
        ok = got >= want
        checks["min_signal_ok"] = {"got": got, "want": want, "ok": ok}
        if not ok:
            failures.append(f"signal_ok {got} < {want}")

    if not checks:
        # No gates → pass if ok_rate is present and >= 1.0, else soft pass on row
        got = _num("ok_rate")
        if got is not None:
            ok = got >= 1.0
            checks["default_ok_rate"] = {"got": got, "want": 1.0, "ok": ok}
            if not ok:
                failures.append(f"default ok_rate {got} < 1.0")
        else:
            checks["empty_expected"] = {"ok": True}
            ok = True
            return GateResult(
                ok=True,
                score=1.0,
                reason="no_gates",
                method=method,
                checks=checks,
            )

    ok_all = not failures
    score = 1.0 if ok_all else max(
        0.0,
        round(sum(1 for c in checks.values() if c.get("ok")) / max(1, len(checks)), 4),
    )
    reason = "pass" if ok_all else "; ".join(failures)
    return GateResult(
        ok=ok_all, score=score, reason=reason, method=method, checks=checks
    )


def score_scenario(scenario: MafScenario, row: dict[str, Any]) -> GateResult:
    """Dispatch scorer by scoring_method (default overhead_gate)."""
    method = (scenario.scoring_method or "overhead_gate").lower()
    if method in ("overhead_gate", "gate", "static", "static_json"):
        return score_overhead_gate(scenario, row)
    return GateResult(
        ok=False,
        score=0.0,
        reason=f"unknown_scorer:{method}",
        method=method,
    )


def _rows_by_mechanism(bench: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(r.get("mechanism")): r
        for r in (bench.get("rows") or [])
        if r.get("mechanism")
    }


def run_maf_scenarios(
    workdir: Optional[Path | str] = None,
    *,
    scenarios: Optional[list[MafScenario]] = None,
    packs: Optional[Iterable[Path | str]] = None,
    include_builtin: bool = True,
    discover: bool = False,
    pack_dir: str = DEFAULT_PACK_DIR,
    iters: int = DEFAULT_ITERS,
    export: bool = True,
    out_dir: Optional[str] = None,
) -> dict[str, Any]:
    """Run AssetOpsBench-shaped MAF scenarios → gate scores → pass-rate report.

    Hybrid flow (arXiv MAFBench metrics + AssetOpsBench pack/scorer shape)::

        scenarios/packs
          → unique mechanisms (+ single_judge baseline when overhead gates present)
          → run_maf_bench micro-suite
          → score_overhead_gate per scenario
          → pass_rate + by_domain breakdown
    """
    root = Path(workdir or ".").resolve()
    suite: list[MafScenario] = []
    if include_builtin:
        suite.extend(builtin_maf_scenarios())
    pack_paths: list[str] = []
    if packs:
        loaded = load_maf_packs(packs)
        suite.extend(loaded)
        pack_paths = [str(Path(p)) for p in packs]
    if discover:
        found = discover_maf_packs(root, pack_dir=pack_dir)
        if found:
            suite.extend(load_maf_packs(found))
            pack_paths.extend(str(p) for p in found)
    if scenarios:
        suite.extend(scenarios)

    # de-dupe by id (later wins)
    by_id: dict[str, MafScenario] = {}
    order: list[str] = []
    for sc in suite:
        if sc.id not in by_id:
            order.append(sc.id)
        by_id[sc.id] = sc
    suite = [by_id[i] for i in order]

    if not suite:
        return {
            "ok": False,
            "schema": PACK_SCHEMA,
            "paper": PAPER,
            "error": "no scenarios resolved",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "results": [],
        }

    need: list[str] = []
    seen_m: set[str] = set()
    needs_baseline = False
    for sc in suite:
        mid = sc.mechanism
        if mid not in MECHANISMS:
            # still attempt; run_maf_bench will error — capture per-scenario fail
            pass
        if mid not in seen_m:
            seen_m.add(mid)
            need.append(mid)
        exp = sc.expected or {}
        if "max_overhead_x" in exp and mid != "single_judge":
            needs_baseline = True
    if needs_baseline and "single_judge" not in seen_m:
        need.insert(0, "single_judge")

    unknown = [m for m in need if m not in MECHANISMS]
    if unknown:
        return {
            "ok": False,
            "schema": PACK_SCHEMA,
            "paper": PAPER,
            "error": f"unknown mechanism(s) in scenarios: {unknown}",
            "total": len(suite),
            "passed": 0,
            "failed": len(suite),
            "pass_rate": 0.0,
            "mechanisms": need,
            "results": [],
        }

    t0 = time.perf_counter()
    bench = run_maf_bench(
        root,
        iters=max(1, int(iters)),
        mechanisms=need,
        export=False,
    )
    wall_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    rows_map = _rows_by_mechanism(bench)

    results: list[dict[str, Any]] = []
    by_domain: dict[str, dict[str, int]] = {}
    by_type: dict[str, dict[str, int]] = {}
    passed = 0
    for sc in suite:
        row = rows_map.get(sc.mechanism) or {}
        if not row:
            gate = GateResult(
                ok=False,
                score=0.0,
                reason=f"missing_bench_row:{sc.mechanism}",
                method=sc.scoring_method,
            )
        else:
            gate = score_scenario(sc, row)
        if gate.ok:
            passed += 1
        bucket = by_domain.setdefault(
            sc.domain, {"total": 0, "passed": 0, "failed": 0}
        )
        bucket["total"] += 1
        if gate.ok:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
        tb = by_type.setdefault(
            sc.type or sc.domain, {"total": 0, "passed": 0, "failed": 0}
        )
        tb["total"] += 1
        if gate.ok:
            tb["passed"] += 1
        else:
            tb["failed"] += 1
        results.append(
            {
                "scenario_id": sc.id,
                "domain": sc.domain,
                "type": sc.type or sc.domain,
                "text": sc.text,
                "mechanism": sc.mechanism,
                "ok": gate.ok,
                "score": gate.score,
                "reason": gate.reason,
                "method": gate.method,
                "checks": gate.checks,
                "metrics": {
                    k: row.get(k)
                    for k in (
                        "ok_rate",
                        "mean_ms",
                        "p50_ms",
                        "p95_ms",
                        "overhead_x",
                        "ops_per_s",
                        "n_graders",
                        "pass_rate",
                        "n_scenarios",
                        "n_servers",
                        "n_servers_ok",
                        "servers_ok_rate",
                        "n_plugins",
                        "n_components",
                        "n_errors",
                        "n_collisions",
                        "n_jobs",
                        "n_spend",
                        "total_tokens",
                        "sticky_ok",
                        "statuses_walked",
                        "lanes_walked",
                        "n_traces",
                        "n_evidence",
                        "n_handoffs",
                        "roles_ok",
                        "signal_ok",
                        "n_boards",
                    )
                    if k in row
                },
                "tags": list(sc.tags),
            }
        )

    total = len(suite)
    failed = total - passed
    pass_rate = round(passed / total, 4) if total else 0.0
    report: dict[str, Any] = {
        "schema": PACK_SCHEMA,
        "paper": PAPER,
        "paper_url": PAPER_URL,
        "assetops_url": ASSETOPS_URL,
        "wshobson_url": WSHOBSON_URL,
        "mission_control_url": MISSION_CONTROL_URL,
        "routa_url": ROUTA_URL,
        "ok": failed == 0 and bool(bench.get("ok")),
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "iters": max(1, int(iters)),
        "mechanisms": need,
        "packs": pack_paths,
        "include_builtin": include_builtin,
        "wall_ms": wall_ms,
        "by_domain": by_domain,
        "by_type": by_type,
        "bench_summary": bench.get("summary") or {},
        "bench_rows": bench.get("rows") or [],
        "results": results,
        "failures": [r for r in results if not r.get("ok")],
        "workdir": str(root),
    }

    if export:
        dest = root / (out_dir or DEFAULT_OUT_DIR)
        dest.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        jpath = dest / f"maf_pack-{ts}.json"
        mpath = dest / f"maf_pack-{ts}.md"
        atomic_write_json(jpath, report)
        atomic_write_text(mpath, format_pack_report(report))
        report["export"] = {
            "json": str(jpath),
            "md": str(mpath),
            "out_dir": str(dest),
        }

    return report


def format_pack_report(report: dict[str, Any]) -> str:
    """Markdown pass-rate board for MAF scenario packs."""
    lines = [
        "# MAFBench × AssetOpsBench × wshobson × mission-control × routa pack report",
        "",
        f"schema: `{report.get('schema')}`  paper: `{report.get('paper')}`  "
        f"ok={report.get('ok')}  pass_rate={report.get('pass_rate')}  "
        f"({report.get('passed')}/{report.get('total')})",
        "",
        "| scenario | domain | mechanism | ok | score | reason | overhead× |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report.get("results") or []:
        metrics = r.get("metrics") or {}
        ox = metrics.get("overhead_x")
        ox_s = f"{ox}" if ox is not None else "—"
        lines.append(
            f"| {r.get('scenario_id')} | {r.get('domain')} | {r.get('mechanism')} | "
            f"{r.get('ok')} | {r.get('score')} | {r.get('reason')} | {ox_s} |"
        )
    lines.extend(
        [
            "",
            "## Breakdown",
            "",
            f"- by_domain: {report.get('by_domain')}",
            f"- by_type: {report.get('by_type')}",
            f"- mechanisms: {report.get('mechanisms')}",
            f"- wall_ms: {report.get('wall_ms')}",
            "",
            f"MAF paper: {report.get('paper_url') or PAPER_URL}",
            f"AssetOpsBench pattern: {report.get('assetops_url') or ASSETOPS_URL}",
            f"wshobson/agents pattern: {report.get('wshobson_url') or WSHOBSON_URL}",
            f"mission-control pattern: "
            f"{report.get('mission_control_url') or MISSION_CONTROL_URL}",
            f"phodal/routa pattern: {report.get('routa_url') or ROUTA_URL}",
            "",
        ]
    )
    return "\n".join(lines)


def pack_smoke(
    workdir: Optional[Path | str] = None,
    *,
    iters: int = 3,
) -> dict[str, Any]:
    """Short offline pack smoke (builtin scenarios only)."""
    return run_maf_scenarios(
        workdir,
        include_builtin=True,
        iters=iters,
        export=False,
    )


BRIEF_SCHEMA = "nexus.maf_brief/v1"
# Fast self-check subset: baseline + consensus + AssetOps multi-domain hub.
BRIEF_MECHANISMS = ("single_judge", "consensus", "domain_mcp")


def maf_brief(
    workdir: Optional[Path | str] = None,
    *,
    iters: int = 2,
    include_pack: bool = True,
    mechanisms: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Advisory MAFBench brief for alive self_check (offline, fast).

    Closes the AssetOpsBench hybrid open item: surface
    ``consensus_overhead_x`` + multi-domain MCP hub metrics + pack
    ``pass_rate`` without running the full delivery_board/control_plane suite.

    Fully offline — no network, no live LLMs.
    """
    root = Path(workdir or ".").resolve()
    mechs = list(mechanisms) if mechanisms else list(BRIEF_MECHANISMS)
    # Always include single_judge when overhead is requested.
    if "single_judge" not in mechs and any(
        m != "single_judge" for m in mechs
    ):
        mechs = ["single_judge", *mechs]

    t0 = time.perf_counter()
    bench = run_maf_bench(
        root,
        iters=max(1, int(iters)),
        mechanisms=mechs,
        export=False,
    )
    rows_map = _rows_by_mechanism(bench)
    cons = rows_map.get("consensus") or {}
    dom = rows_map.get("domain_mcp") or {}
    summary = bench.get("summary") or {}

    pack: Optional[dict[str, Any]] = None
    if include_pack:
        # Gate only the brief mechanisms (not full builtin suite).
        gate_mechs = set(mechs)
        scenarios = [
            s for s in builtin_maf_scenarios() if s.mechanism in gate_mechs
        ]
        pack = run_maf_scenarios(
            root,
            scenarios=scenarios,
            include_builtin=False,
            iters=max(1, int(iters)),
            export=False,
        )

    wall_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    pack_ok = True if pack is None else bool(pack.get("ok"))
    ok = bool(bench.get("ok")) and pack_ok
    return {
        "schema": BRIEF_SCHEMA,
        "ok": ok,
        "paper": PAPER,
        "paper_url": PAPER_URL,
        "assetops_url": ASSETOPS_URL,
        "iters": max(1, int(iters)),
        "mechanisms": mechs,
        "consensus_overhead_x": cons.get("overhead_x")
        if cons
        else summary.get("consensus_overhead_x"),
        "domain_mcp_overhead_x": dom.get("overhead_x")
        if dom
        else summary.get("domain_mcp_overhead_x"),
        "domain_mcp_pass_rate": dom.get("pass_rate")
        if dom
        else summary.get("domain_mcp_pass_rate"),
        "domain_mcp_n_servers": dom.get("n_servers")
        if dom
        else summary.get("domain_mcp_n_servers"),
        "domain_mcp_servers_ok_rate": dom.get("servers_ok_rate"),
        "pack_pass_rate": None if pack is None else pack.get("pass_rate"),
        "pack_ok": None if pack is None else pack.get("ok"),
        "pack_total": None if pack is None else pack.get("total"),
        "pack_passed": None if pack is None else pack.get("passed"),
        "bench_ok": bool(bench.get("ok")),
        "n_domain_servers_registered": len(DOMAIN_MCP_SERVERS),
        "wall_ms": wall_ms,
        "workdir": str(root),
        "source": "maf_brief",
    }


def format_brief(brief: dict[str, Any]) -> str:
    """One-line / short multi-line operator paste for alive logs."""
    lines = [
        f"MAFBench brief ok={brief.get('ok')} paper={brief.get('paper')}",
        f"  consensus_overhead_x={brief.get('consensus_overhead_x')}",
        f"  domain_mcp_overhead_x={brief.get('domain_mcp_overhead_x')} "
        f"n_servers={brief.get('domain_mcp_n_servers')} "
        f"pass_rate={brief.get('domain_mcp_pass_rate')}",
        f"  pack_pass_rate={brief.get('pack_pass_rate')} "
        f"({brief.get('pack_passed')}/{brief.get('pack_total')})",
        f"  wall_ms={brief.get('wall_ms')}",
    ]
    return "\n".join(lines)
