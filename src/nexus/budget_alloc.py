"""Budget-aware multi-agent compute allocation (FutureWeaver pattern).

arXiv:2512.11213v2 — *FutureWeaver: Planning Test-Time Compute for Multi-Agent
Systems with Modularized Collaboration*.

Plans a shared **test-time compute pool** across collaborating agents, tracks
per-agent consumption, hard-limits overspend, and (modular strategy) reclaims
unused shares for residual reallocation.

Does **not** vendor FutureWeaver; shape only. Composes with
``durability.RunBudget`` (per-run caps) and ``usage.Budget`` (daily/monthly).

Schema: ``nexus.budget_alloc/v1``
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

SCHEMA = "nexus.budget_alloc/v1"
PAPER = "arxiv:2512.11213v2"
PAPER_TITLE = (
    "FutureWeaver: Planning Test-Time Compute for Multi-Agent Systems "
    "with Modularized Collaboration"
)

# Strategies for initial pool split
STRATEGIES = frozenset({"equal", "weighted", "modular"})

# Default collaboration weights (implementer gets most test-time compute)
DEFAULT_ROLE_WEIGHTS: dict[str, float] = {
    "operator": 0.2,
    "planner": 1.5,
    "adversary": 1.0,
    "implementer": 3.0,
    "tester": 1.5,
    "reviewer": 1.0,
    "logger": 0.3,
    "local": 1.0,
}

# Modular strategy: fraction of each share that is *reserved* (not reclaimable
# until the agent finishes). Remainder is pool-share that can be reclaimed.
MODULAR_RESERVED_FRACTION = 0.5


class AllocationExhausted(RuntimeError):
    """Raised when an agent (or the shared pool) cannot grant more compute.

    Attributes:
        agent: agent id that requested grant (or ``*`` for pool-level).
        kind: ``tokens`` | ``steps`` | ``pool``.
        used: amount already used on that dimension.
        limit: configured cap.
    """

    def __init__(
        self,
        message: str,
        *,
        agent: str,
        kind: str,
        used: float,
        limit: float,
    ) -> None:
        super().__init__(message)
        self.agent = agent
        self.kind = kind
        self.used = used
        self.limit = limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "AllocationExhausted",
            "message": str(self),
            "agent": self.agent,
            "kind": self.kind,
            "used": self.used,
            "limit": self.limit,
        }


@dataclass
class AgentQuota:
    """Per-agent compute share inside a multi-agent pool."""

    agent: str
    max_tokens: int = 0
    max_steps: Optional[int] = None
    tokens_used: int = 0
    steps_used: int = 0
    weight: float = 1.0
    # modular: floor that stays with the agent until reclaim/finish
    reserved_tokens: int = 0
    finished: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def remaining_tokens(self) -> int:
        return max(0, int(self.max_tokens) - int(self.tokens_used))

    def remaining_steps(self) -> Optional[int]:
        if self.max_steps is None:
            return None
        return max(0, int(self.max_steps) - int(self.steps_used))

    def exhausted_kind(self) -> Optional[str]:
        if self.max_steps is not None and self.steps_used >= self.max_steps:
            return "steps"
        if self.max_tokens > 0 and self.tokens_used >= self.max_tokens:
            return "tokens"
        if self.max_tokens <= 0 and self.tokens_used > 0:
            return "tokens"
        return None

    def exhausted(self) -> bool:
        return self.exhausted_kind() is not None

    def reclaimable_tokens(self) -> int:
        """Tokens not yet used that are above the modular reserved floor."""
        unused = self.remaining_tokens()
        if self.reserved_tokens <= 0:
            return unused
        # reserved must remain until finished; only surplus is reclaimable
        keep = max(0, int(self.reserved_tokens) - int(self.tokens_used))
        return max(0, unused - keep)

    def snapshot(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "max_tokens": int(self.max_tokens),
            "max_steps": self.max_steps,
            "tokens_used": int(self.tokens_used),
            "steps_used": int(self.steps_used),
            "weight": float(self.weight),
            "reserved_tokens": int(self.reserved_tokens),
            "remaining_tokens": self.remaining_tokens(),
            "remaining_steps": self.remaining_steps(),
            "exhausted": self.exhausted(),
            "exhausted_kind": self.exhausted_kind(),
            "finished": bool(self.finished),
            "reclaimable_tokens": self.reclaimable_tokens(),
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentQuota":
        return cls(
            agent=str(d.get("agent") or ""),
            max_tokens=int(d.get("max_tokens") or 0),
            max_steps=_opt_int(d.get("max_steps")),
            tokens_used=int(d.get("tokens_used") or 0),
            steps_used=int(d.get("steps_used") or 0),
            weight=float(d.get("weight") or 1.0),
            reserved_tokens=int(d.get("reserved_tokens") or 0),
            finished=bool(d.get("finished", False)),
            extra=dict(d.get("extra") or {})
            if isinstance(d.get("extra"), dict)
            else {},
        )


@dataclass
class BudgetAllocator:
    """Shared test-time compute pool with per-agent limits.

    Lifecycle (FutureWeaver modular collaboration shape):
      1. ``plan(...)`` — split total_tokens across agents
      2. ``grant`` / ``consume`` — track usage before/after agent work
      3. ``finish`` + ``reclaim`` — return unused modular share to residual pool
      4. ``rebalance`` — redistribute residual to still-active agents
    """

    total_tokens: int
    strategy: str = "weighted"
    agents: dict[str, AgentQuota] = field(default_factory=dict)
    total_steps: Optional[int] = None
    steps_used: int = 0
    # residual pool: unallocated at plan-time + reclaimed unused shares
    residual_tokens: int = 0
    hard: bool = True
    paper: str = PAPER
    schema: str = SCHEMA
    meta: dict[str, Any] = field(default_factory=dict)
    # soft-mode bookkeeping
    soft_stop: bool = False
    soft_reason: str = ""

    # ── planning ────────────────────────────────────────────────────────

    @classmethod
    def plan(
        cls,
        agents: Iterable[str],
        *,
        total_tokens: int,
        strategy: str = "weighted",
        weights: Optional[dict[str, float]] = None,
        total_steps: Optional[int] = None,
        hard: bool = True,
        reserved_fraction: float = MODULAR_RESERVED_FRACTION,
        meta: Optional[dict[str, Any]] = None,
    ) -> "BudgetAllocator":
        """Build a planned allocation for the given agent roster.

        Strategies:
        - ``equal`` — even split of *total_tokens*
        - ``weighted`` — proportional to role weights (DEFAULT_ROLE_WEIGHTS)
        - ``modular`` — weighted split + reserved floor; surplus reclaimable
        """
        names = [str(a).strip() for a in agents if str(a).strip()]
        if not names:
            raise ValueError("agents required for compute budget plan")
        total = max(0, int(total_tokens))
        strat = str(strategy or "weighted").strip().lower()
        if strat not in STRATEGIES:
            raise ValueError(
                f"invalid strategy {strategy!r}; allowed: {sorted(STRATEGIES)}"
            )
        wmap = dict(DEFAULT_ROLE_WEIGHTS)
        if weights:
            for k, v in weights.items():
                try:
                    wmap[str(k)] = max(0.0, float(v))
                except (TypeError, ValueError):
                    continue

        # compute weights for roster
        ws = [max(0.0, float(wmap.get(n, 1.0))) for n in names]
        if strat == "equal":
            ws = [1.0] * len(names)
        wsum = sum(ws) or float(len(names))

        # integer split with largest-remainder so sum(max) <= total
        raw = [(total * w) / wsum for w in ws]
        floors = [int(x) for x in raw]
        rem = total - sum(floors)
        # distribute remainder to highest fractional parts
        order = sorted(
            range(len(names)),
            key=lambda i: (raw[i] - floors[i], ws[i]),
            reverse=True,
        )
        for i in order:
            if rem <= 0:
                break
            floors[i] += 1
            rem -= 1

        reserved_frac = max(0.0, min(1.0, float(reserved_fraction)))
        quotas: dict[str, AgentQuota] = {}
        for n, share, w in zip(names, floors, ws):
            reserved = 0
            if strat == "modular":
                reserved = int(share * reserved_frac)
            quotas[n] = AgentQuota(
                agent=n,
                max_tokens=int(share),
                max_steps=None,
                weight=float(w),
                reserved_tokens=reserved,
            )

        # optional per-agent step share (equal when total_steps set)
        if total_steps is not None and int(total_steps) > 0:
            ts = int(total_steps)
            base = ts // len(names)
            extra = ts - base * len(names)
            for i, n in enumerate(names):
                quotas[n].max_steps = base + (1 if i < extra else 0)

        allocated = sum(q.max_tokens for q in quotas.values())
        residual = max(0, total - allocated)

        return cls(
            total_tokens=total,
            strategy=strat,
            agents=quotas,
            total_steps=int(total_steps) if total_steps is not None else None,
            residual_tokens=residual,
            hard=bool(hard),
            meta={
                "paper_title": PAPER_TITLE,
                "reserved_fraction": reserved_frac if strat == "modular" else None,
                **(meta or {}),
            },
        )

    @classmethod
    def from_meta(cls, meta: Optional[dict[str, Any]]) -> Optional["BudgetAllocator"]:
        """Load from task/envelope meta (``meta.budget_alloc`` or nested)."""
        if not meta or not isinstance(meta, dict):
            return None
        raw = meta.get("budget_alloc")
        if raw is None and isinstance(meta.get("compute_budget"), dict):
            # plan-from-spec path
            return cls.from_spec(meta["compute_budget"])
        if not isinstance(raw, dict):
            return None
        return cls.from_dict(raw)

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> "BudgetAllocator":
        """Plan from a compact compute_budget spec dict."""
        agents = spec.get("agents") or list(DEFAULT_ROLE_WEIGHTS.keys())
        if isinstance(agents, str):
            agents = [a.strip() for a in agents.split(",") if a.strip()]
        return cls.plan(
            agents,
            total_tokens=int(spec.get("total_tokens") or spec.get("max_tokens") or 0),
            strategy=str(spec.get("strategy") or "weighted"),
            weights=spec.get("weights") if isinstance(spec.get("weights"), dict) else None,
            total_steps=_opt_int(spec.get("total_steps") or spec.get("max_steps")),
            hard=bool(spec.get("hard", True)),
            reserved_fraction=float(
                spec.get("reserved_fraction", MODULAR_RESERVED_FRACTION)
            ),
            meta=spec.get("meta") if isinstance(spec.get("meta"), dict) else None,
        )

    # ── inspection ──────────────────────────────────────────────────────

    def tokens_used(self) -> int:
        return sum(int(q.tokens_used) for q in self.agents.values())

    def tokens_allocated(self) -> int:
        return sum(int(q.max_tokens) for q in self.agents.values())

    def remaining_tokens(self) -> int:
        """Unused agent shares + residual pool."""
        unused = sum(q.remaining_tokens() for q in self.agents.values())
        return unused + int(self.residual_tokens)

    def remaining_steps(self) -> Optional[int]:
        if self.total_steps is None:
            return None
        return max(0, int(self.total_steps) - int(self.steps_used))

    def get(self, agent: str) -> AgentQuota:
        a = str(agent).strip()
        if a not in self.agents:
            raise KeyError(f"unknown agent in compute pool: {a!r}")
        return self.agents[a]

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "paper": self.paper,
            "strategy": self.strategy,
            "total_tokens": int(self.total_tokens),
            "total_steps": self.total_steps,
            "tokens_used": self.tokens_used(),
            "tokens_allocated": self.tokens_allocated(),
            "residual_tokens": int(self.residual_tokens),
            "remaining_tokens": self.remaining_tokens(),
            "steps_used": int(self.steps_used),
            "remaining_steps": self.remaining_steps(),
            "hard": bool(self.hard),
            "soft_stop": bool(self.soft_stop),
            "soft_reason": self.soft_reason,
            "exhausted": self.remaining_tokens() <= 0
            and (
                self.total_steps is None
                or (self.remaining_steps() is not None and self.remaining_steps() <= 0)
            ),
            "agents": {k: q.snapshot() for k, q in self.agents.items()},
            "meta": dict(self.meta or {}),
        }

    # ── mutation ────────────────────────────────────────────────────────

    def _raise_or_soft(
        self, *, agent: str, kind: str, used: float, limit: float
    ) -> None:
        msg = (
            f"compute allocation exhausted: agent={agent} {kind} "
            f"used={used} limit={limit}"
        )
        if self.hard:
            raise AllocationExhausted(
                msg, agent=agent, kind=kind, used=used, limit=limit
            )
        self.soft_stop = True
        self.soft_reason = msg

    def would_exceed(
        self,
        agent: str,
        *,
        tokens: int = 0,
        steps: int = 0,
    ) -> Optional[str]:
        """Predict which dimension would fail (agent tokens/steps or pool steps)."""
        q = self.get(agent)
        tokens = int(tokens or 0)
        steps = int(steps or 0)
        if tokens and int(q.tokens_used) + tokens > int(q.max_tokens):
            return "tokens"
        if (
            q.max_steps is not None
            and steps
            and int(q.steps_used) + steps > int(q.max_steps)
        ):
            return "steps"
        if (
            self.total_steps is not None
            and steps
            and int(self.steps_used) + steps > int(self.total_steps)
        ):
            return "steps"
        return None

    def grant(
        self,
        agent: str,
        *,
        tokens: int = 0,
        steps: int = 0,
        consume: bool = True,
    ) -> dict[str, Any]:
        """Request compute for *agent*.

        When *consume* is True (default), accrues usage immediately (pre-pay).
        When False, only checks — caller must ``consume`` after work.

        Returns a grant receipt. Raises ``AllocationExhausted`` in hard mode.
        """
        q = self.get(agent)
        tokens = max(0, int(tokens or 0))
        steps = max(0, int(steps or 0))
        if q.finished:
            self._raise_or_soft(
                agent=agent, kind="tokens", used=q.tokens_used, limit=q.max_tokens
            )
            return {
                "ok": False,
                "agent": agent,
                "tokens": 0,
                "steps": 0,
                "reason": "agent_finished",
            }

        kind = self.would_exceed(agent, tokens=tokens, steps=steps)
        if kind is not None:
            if kind == "tokens":
                used, limit = q.tokens_used, q.max_tokens
            else:
                used = q.steps_used if q.max_steps is not None else self.steps_used
                limit = (
                    q.max_steps
                    if q.max_steps is not None
                    else (self.total_steps or 0)
                )
            self._raise_or_soft(agent=agent, kind=kind, used=used, limit=float(limit))
            return {
                "ok": False,
                "agent": agent,
                "tokens": 0,
                "steps": 0,
                "reason": f"exceeds_{kind}",
            }

        if consume:
            if tokens:
                q.tokens_used = int(q.tokens_used) + tokens
            if steps:
                q.steps_used = int(q.steps_used) + steps
                self.steps_used = int(self.steps_used) + steps

        return {
            "ok": True,
            "agent": agent,
            "tokens": tokens,
            "steps": steps,
            "remaining_tokens": q.remaining_tokens(),
            "remaining_steps": q.remaining_steps(),
            "consumed": bool(consume),
        }

    def consume(
        self,
        agent: str,
        *,
        tokens: int = 0,
        steps: int = 0,
        check: bool = True,
    ) -> dict[str, Any]:
        """Accrue usage after work (post-pay path)."""
        if check:
            return self.grant(agent, tokens=tokens, steps=steps, consume=True)
        q = self.get(agent)
        tokens = max(0, int(tokens or 0))
        steps = max(0, int(steps or 0))
        if tokens:
            q.tokens_used = int(q.tokens_used) + tokens
        if steps:
            q.steps_used = int(q.steps_used) + steps
            self.steps_used = int(self.steps_used) + steps
        return {
            "ok": True,
            "agent": agent,
            "tokens": tokens,
            "steps": steps,
            "remaining_tokens": q.remaining_tokens(),
            "check": False,
        }

    def finish(self, agent: str, *, reclaim: bool = True) -> dict[str, Any]:
        """Mark agent done; optionally reclaim unused modular share to residual."""
        q = self.get(agent)
        q.finished = True
        reclaimed = 0
        if reclaim:
            reclaimed = self.reclaim(agent)
        return {
            "ok": True,
            "agent": agent,
            "finished": True,
            "reclaimed_tokens": reclaimed,
            "residual_tokens": int(self.residual_tokens),
        }

    def reclaim(self, agent: str) -> int:
        """Return reclaimable unused tokens from *agent* to residual pool.

        Shrinks the agent's max_tokens to tokens_used (or reserved floor if
        still active). Finished agents release all unused tokens.
        """
        q = self.get(agent)
        if q.finished:
            free = q.remaining_tokens()
            q.max_tokens = int(q.tokens_used)
            q.reserved_tokens = 0
        else:
            free = q.reclaimable_tokens()
            if free <= 0:
                return 0
            q.max_tokens = int(q.max_tokens) - free
        self.residual_tokens = int(self.residual_tokens) + free
        return free

    def rebalance(
        self,
        *,
        targets: Optional[Iterable[str]] = None,
        strategy: Optional[str] = None,
    ) -> dict[str, Any]:
        """Distribute residual_tokens across still-active agents.

        FutureWeaver modular collaboration: unused compute is re-planned for
        remaining collaborators rather than left idle.
        """
        residual = int(self.residual_tokens)
        if residual <= 0:
            return {
                "ok": True,
                "distributed": 0,
                "residual_tokens": 0,
                "targets": [],
            }
        if targets is None:
            names = [
                n
                for n, q in self.agents.items()
                if not q.finished and not q.exhausted()
            ]
        else:
            names = [str(t).strip() for t in targets if str(t).strip() in self.agents]
            names = [n for n in names if not self.agents[n].finished]

        if not names:
            return {
                "ok": True,
                "distributed": 0,
                "residual_tokens": residual,
                "targets": [],
                "reason": "no_active_agents",
            }

        strat = str(strategy or self.strategy or "weighted").strip().lower()
        if strat == "equal":
            ws = [1.0] * len(names)
        else:
            ws = [max(0.0, float(self.agents[n].weight)) for n in names]
        wsum = sum(ws) or float(len(names))
        raw = [(residual * w) / wsum for w in ws]
        floors = [int(x) for x in raw]
        rem = residual - sum(floors)
        order = sorted(
            range(len(names)),
            key=lambda i: (raw[i] - floors[i], ws[i]),
            reverse=True,
        )
        for i in order:
            if rem <= 0:
                break
            floors[i] += 1
            rem -= 1

        given: dict[str, int] = {}
        for n, share in zip(names, floors):
            if share <= 0:
                continue
            self.agents[n].max_tokens = int(self.agents[n].max_tokens) + share
            given[n] = share
        distributed = sum(given.values())
        self.residual_tokens = residual - distributed
        return {
            "ok": True,
            "distributed": distributed,
            "residual_tokens": int(self.residual_tokens),
            "targets": names,
            "given": given,
            "strategy": strat,
        }

    def top_up(self, agent: str, tokens: int) -> dict[str, Any]:
        """Grant residual pool tokens to one agent (manual modular boost)."""
        q = self.get(agent)
        tokens = max(0, int(tokens or 0))
        if tokens <= 0:
            return {"ok": True, "agent": agent, "added": 0}
        take = min(tokens, int(self.residual_tokens))
        if take < tokens and self.hard:
            self._raise_or_soft(
                agent=agent,
                kind="pool",
                used=self.tokens_used(),
                limit=float(self.total_tokens),
            )
            return {
                "ok": False,
                "agent": agent,
                "added": 0,
                "reason": "residual_insufficient",
                "residual_tokens": int(self.residual_tokens),
            }
        self.residual_tokens = int(self.residual_tokens) - take
        q.max_tokens = int(q.max_tokens) + take
        return {
            "ok": True,
            "agent": agent,
            "added": take,
            "max_tokens": q.max_tokens,
            "residual_tokens": int(self.residual_tokens),
        }

    # ── serde ───────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "paper": self.paper,
            "total_tokens": int(self.total_tokens),
            "strategy": self.strategy,
            "total_steps": self.total_steps,
            "steps_used": int(self.steps_used),
            "residual_tokens": int(self.residual_tokens),
            "hard": bool(self.hard),
            "soft_stop": bool(self.soft_stop),
            "soft_reason": self.soft_reason,
            "agents": {k: q.to_dict() for k, q in self.agents.items()},
            "meta": dict(self.meta or {}),
        }

    def to_meta(self) -> dict[str, Any]:
        """Compact dict for ``task.meta['budget_alloc']`` / envelope."""
        return self.to_dict()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BudgetAllocator":
        agents_raw = d.get("agents") or {}
        agents: dict[str, AgentQuota] = {}
        if isinstance(agents_raw, dict):
            for k, v in agents_raw.items():
                if isinstance(v, dict):
                    q = AgentQuota.from_dict({**v, "agent": v.get("agent") or k})
                    agents[str(k)] = q
        return cls(
            total_tokens=int(d.get("total_tokens") or 0),
            strategy=str(d.get("strategy") or "weighted"),
            agents=agents,
            total_steps=_opt_int(d.get("total_steps")),
            steps_used=int(d.get("steps_used") or 0),
            residual_tokens=int(d.get("residual_tokens") or 0),
            hard=bool(d.get("hard", True)),
            paper=str(d.get("paper") or PAPER),
            schema=str(d.get("schema") or SCHEMA),
            meta=dict(d.get("meta") or {}) if isinstance(d.get("meta"), dict) else {},
            soft_stop=bool(d.get("soft_stop", False)),
            soft_reason=str(d.get("soft_reason") or ""),
        )


def _opt_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        n = int(v)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def default_pipeline_agents() -> list[str]:
    """Canonical NEXUS multi-agent roster for compute planning."""
    return [
        "planner",
        "adversary",
        "implementer",
        "tester",
        "reviewer",
        "logger",
    ]


def plan_for_orchestrator(
    *,
    total_tokens: int,
    agents: Optional[Iterable[str]] = None,
    strategy: str = "weighted",
    weights: Optional[dict[str, float]] = None,
    total_steps: Optional[int] = None,
    hard: bool = True,
    reserved_fraction: float = MODULAR_RESERVED_FRACTION,
) -> BudgetAllocator:
    """Convenience used by ``Orchestrator`` when meta.compute_budget is set."""
    roster = list(agents) if agents is not None else default_pipeline_agents()
    return BudgetAllocator.plan(
        roster,
        total_tokens=total_tokens,
        strategy=strategy,
        weights=weights,
        total_steps=total_steps,
        hard=hard,
        reserved_fraction=reserved_fraction,
        meta={"source": "orchestrator"},
    )


def format_brief(alloc: BudgetAllocator) -> str:
    """One-screen operator brief of the compute plan."""
    snap = alloc.snapshot()
    lines = [
        f"compute budget ({snap['schema']}) paper={snap['paper']}",
        f"  strategy={snap['strategy']} total={snap['total_tokens']} "
        f"used={snap['tokens_used']} residual={snap['residual_tokens']} "
        f"remaining={snap['remaining_tokens']}",
    ]
    for name, a in sorted(snap["agents"].items()):
        lines.append(
            f"  - {name}: {a['tokens_used']}/{a['max_tokens']} tok "
            f"w={a['weight']} rem={a['remaining_tokens']}"
            + (" [done]" if a.get("finished") else "")
            + (" [EXHAUSTED]" if a.get("exhausted") else "")
        )
    return "\n".join(lines)
