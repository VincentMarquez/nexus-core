"""Token / usage ledger and throttles.

People can cap spend/energy so self-improvement stays under control.

  nexus usage status
  nexus usage set --daily 200000 --monthly 5000000
  nexus usage record --tokens 1200 --source ollama --label evaluate
  nexus usage reset-day

Storage: ``.nexus_state/usage/`` (JSONL + budget.json + counters).
Estimates use ~4 chars/token when providers don't return usage.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class BudgetExceeded(RuntimeError):
    """Raised when a call would exceed configured limits."""


@dataclass
class Budget:
    enabled: bool = True
    daily_tokens: int = 500_000
    monthly_tokens: int = 10_000_000
    per_call_max: int = 100_000
    # soft warning fraction (0-1)
    warn_at: float = 0.8
    # block when true; if false only warn
    hard_limit: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Budget":
        return cls(
            enabled=bool(d.get("enabled", True)),
            daily_tokens=int(d.get("daily_tokens") or 500_000),
            monthly_tokens=int(d.get("monthly_tokens") or 10_000_000),
            per_call_max=int(d.get("per_call_max") or 100_000),
            warn_at=float(d.get("warn_at") or 0.8),
            hard_limit=bool(d.get("hard_limit", True)),
            extra={k: v for k, v in d.items() if k not in {
                "enabled", "daily_tokens", "monthly_tokens", "per_call_max",
                "warn_at", "hard_limit",
            }},
        )


def _root(workdir: Optional[Path] = None) -> Path:
    return Path(workdir or os.environ.get("NEXUS_PROJECT_ROOT") or os.getcwd()).resolve()


def usage_dir(workdir: Optional[Path] = None) -> Path:
    d = _root(workdir) / ".nexus_state" / "usage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def budget_path(workdir: Optional[Path] = None) -> Path:
    return usage_dir(workdir) / "budget.json"


def ledger_path(workdir: Optional[Path] = None) -> Path:
    return usage_dir(workdir) / "ledger.jsonl"


def load_budget(workdir: Optional[Path] = None) -> Budget:
    p = budget_path(workdir)
    if p.is_file():
        try:
            return Budget.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    # env overrides for zero-config throttles
    b = Budget()
    if os.environ.get("NEXUS_DAILY_TOKENS"):
        b.daily_tokens = int(os.environ["NEXUS_DAILY_TOKENS"])
    if os.environ.get("NEXUS_MONTHLY_TOKENS"):
        b.monthly_tokens = int(os.environ["NEXUS_MONTHLY_TOKENS"])
    if os.environ.get("NEXUS_USAGE_OFF") in {"1", "true", "yes"}:
        b.enabled = False
    return b


def save_budget(budget: Budget, workdir: Optional[Path] = None) -> Path:
    p = budget_path(workdir)
    p.write_text(json.dumps(budget.to_dict(), indent=2) + "\n", encoding="utf-8")
    return p


def estimate_tokens(text: str) -> int:
    """Rough token estimate when APIs omit usage (~4 chars/token)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _day_key(ts: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(ts or time.time(), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _month_key(ts: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(ts or time.time(), tz=timezone.utc)
    return dt.strftime("%Y-%m")


def _iter_ledger(workdir: Optional[Path] = None) -> list[dict[str, Any]]:
    p = ledger_path(workdir)
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def totals(workdir: Optional[Path] = None) -> dict[str, Any]:
    rows = _iter_ledger(workdir)
    day = _day_key()
    month = _month_key()
    by_source: dict[str, int] = {}
    day_tok = 0
    month_tok = 0
    all_tok = 0
    day_calls = 0
    for r in rows:
        tok = int(r.get("tokens") or 0)
        all_tok += tok
        ts = float(r.get("ts") or 0)
        src = str(r.get("source") or "unknown")
        by_source[src] = by_source.get(src, 0) + tok
        if _day_key(ts) == day:
            day_tok += tok
            day_calls += 1
        if _month_key(ts) == month:
            month_tok += tok
    return {
        "day": day,
        "month": month,
        "day_tokens": day_tok,
        "month_tokens": month_tok,
        "all_tokens": all_tok,
        "day_calls": day_calls,
        "by_source": by_source,
        "entries": len(rows),
    }


def check_budget(
    tokens: int,
    workdir: Optional[Path] = None,
    *,
    raise_on_exceed: bool = True,
) -> dict[str, Any]:
    """Return ok/warn/block for a prospective spend."""
    b = load_budget(workdir)
    t = totals(workdir)
    if not b.enabled:
        return {"ok": True, "enabled": False, "tokens": tokens, "totals": t}
    warnings: list[str] = []
    block = False
    reasons: list[str] = []
    if tokens > b.per_call_max:
        block = True
        reasons.append(f"per_call_max {b.per_call_max} < request {tokens}")
    if t["day_tokens"] + tokens > b.daily_tokens:
        block = True
        reasons.append(
            f"daily budget {b.daily_tokens} would become {t['day_tokens'] + tokens}"
        )
    if t["month_tokens"] + tokens > b.monthly_tokens:
        block = True
        reasons.append(
            f"monthly budget {b.monthly_tokens} would become {t['month_tokens'] + tokens}"
        )
    # warnings near limit
    if t["day_tokens"] >= b.daily_tokens * b.warn_at:
        warnings.append(
            f"daily usage {t['day_tokens']}/{b.daily_tokens} "
            f"({100 * t['day_tokens'] / max(1, b.daily_tokens):.0f}%)"
        )
    if t["month_tokens"] >= b.monthly_tokens * b.warn_at:
        warnings.append(
            f"monthly usage {t['month_tokens']}/{b.monthly_tokens} "
            f"({100 * t['month_tokens'] / max(1, b.monthly_tokens):.0f}%)"
        )
    ok = not (block and b.hard_limit)
    result = {
        "ok": ok,
        "block": block and b.hard_limit,
        "soft_block": block and not b.hard_limit,
        "warnings": warnings,
        "reasons": reasons,
        "tokens": tokens,
        "budget": b.to_dict(),
        "totals": t,
    }
    if not ok and raise_on_exceed:
        raise BudgetExceeded("; ".join(reasons) or "budget exceeded")
    return result


def record(
    tokens: int,
    *,
    source: str = "unknown",
    label: str = "",
    meta: Optional[dict[str, Any]] = None,
    workdir: Optional[Path] = None,
    enforce: bool = True,
) -> dict[str, Any]:
    """Check budget (optional), append ledger row, return status."""
    tokens = max(0, int(tokens))
    gate = check_budget(tokens, workdir, raise_on_exceed=enforce)
    row = {
        "ts": time.time(),
        "tokens": tokens,
        "source": source,
        "label": label,
        "meta": meta or {},
        "day": _day_key(),
        "month": _month_key(),
    }
    with open(ledger_path(workdir), "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    gate["recorded"] = row
    gate["totals_after"] = totals(workdir)
    return gate


def record_text(
    prompt: str,
    response: str = "",
    *,
    source: str = "llm",
    label: str = "",
    workdir: Optional[Path] = None,
    enforce: bool = True,
) -> dict[str, Any]:
    tok = estimate_tokens(prompt) + estimate_tokens(response)
    return record(
        tok,
        source=source,
        label=label,
        meta={"prompt_chars": len(prompt or ""), "response_chars": len(response or "")},
        workdir=workdir,
        enforce=enforce,
    )


def status(workdir: Optional[Path] = None) -> dict[str, Any]:
    b = load_budget(workdir)
    t = totals(workdir)
    day_pct = 100.0 * t["day_tokens"] / max(1, b.daily_tokens)
    mon_pct = 100.0 * t["month_tokens"] / max(1, b.monthly_tokens)
    return {
        "budget": b.to_dict(),
        "totals": t,
        "day_pct": round(day_pct, 1),
        "month_pct": round(mon_pct, 1),
        "throttle": "on" if b.enabled else "off",
        "hint": {
            "set": "nexus usage set --daily 200000 --monthly 3000000",
            "off": "nexus usage set --off   # or NEXUS_USAGE_OFF=1",
            "alive": "nexus alive once   # self-improve under budget",
        },
    }


def reset_day(workdir: Optional[Path] = None) -> dict[str, Any]:
    """Archive ledger and start fresh (does not change budget)."""
    p = ledger_path(workdir)
    if p.is_file():
        arch = usage_dir(workdir) / f"ledger-{_day_key()}-{int(time.time())}.jsonl"
        p.rename(arch)
        return {"archived": str(arch)}
    return {"archived": None}
