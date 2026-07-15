"""Procurement Intelligence Engine — deterministic computational core.

LLM extracts/normalizes supplier data into Supplier objects; this module
computes every NUMBER and CHART. Numbers are never invented by the model.

Stdlib-first. Optional: numpy, matplotlib (for charts).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
import math
import statistics

try:
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover
    np = None  # type: ignore

try:
    import matplotlib  # type: ignore
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # type: ignore
    HAS_MPL = True
except ImportError:  # pragma: no cover
    plt = None  # type: ignore
    HAS_MPL = False

# ----------------------------------------------------------------------------
# Defaults (override per-engagement)
# ----------------------------------------------------------------------------
DEFAULT_WEIGHTS = {
    "Technical Fit & Quality": 0.25,
    "Commercial Terms & Risk": 0.20,
    "Cost & TCO": 0.30,
    "Delivery / Lead Time / Capacity": 0.15,
    "Compliance / ESG / Reputation": 0.10,
}

DEFAULT_POLICY = {
    "preferred_payment_terms_days": 60,     # Net 60 preferred
    "max_lead_time_days": 21,               # 21 day ceiling
    "require_iso9001": True,                # must-have
    "min_warranty_months": 24,              # 24 month warranty
    "min_auto_renew_notice_days": 90,       # no auto-renew without >=90 day notice
    "max_price_escalation_pct": 5.0,        # flag anything > 5%
    "carrying_rate": 0.12,                  # 12% inventory carrying cost
    "cost_of_capital": 0.10,                # 10% for working-capital / cash-flow value
    "risk_aversion": "High",
}

GREEN, AMBER, RED = "Green", "Amber", "Red"


def _band(score10: float) -> str:
    if score10 >= 7.5:
        return GREEN
    if score10 >= 5.0:
        return AMBER
    return RED


def _flag(score10: float) -> str:
    return {GREEN: "[GREEN]", AMBER: "[AMBER]", RED: "[RED]"}[_band(score10)]


def _money(x) -> str:
    if x is None:
        return "n/a"
    return ("-$" if x < 0 else "$") + f"{abs(x):,.0f}"


def _nz(x, default=0.0):
    return default if x is None else x


# ----------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------
@dataclass
class CostLine:
    item: str
    qty: float = 1.0
    unit_price: float = 0.0
    recurring: bool = False          # True = annual recurring; False = one-time
    note: str = ""

    @property
    def total(self) -> float:
        return self.qty * self.unit_price


@dataclass
class Supplier:
    name: str
    # scores: {category: {subcriterion: {"score": 1-10, "evidence": "quote/source"}}}
    scores: Dict[str, Dict[str, Dict]] = field(default_factory=dict)

    # commercial
    payment_terms_days: Optional[int] = None
    price_validity_days: Optional[int] = None
    price_escalation_pct: Optional[float] = None
    auto_renew: Optional[bool] = None
    auto_renew_notice_days: Optional[int] = None
    termination_clause: str = ""
    ip_ownership: str = ""

    # technical / delivery
    warranty_months: Optional[int] = None
    lead_time_days: Optional[int] = None
    capacity_note: str = ""
    sla: str = ""
    iso9001: Optional[bool] = None
    other_certs: List[str] = field(default_factory=list)

    # cost / TCO
    cost_lines: List[CostLine] = field(default_factory=list)
    implementation_cost: float = 0.0   # one-time
    annual_ops_cost: float = 0.0       # recurring
    annual_maintenance_cost: float = 0.0  # recurring
    disposal_cost: float = 0.0         # one-time end of life

    notes: str = ""
    sources: List[str] = field(default_factory=list)
    # free-form extracted facts for expert lenses (incoterm, part_number, …)
    attrs: Dict[str, Any] = field(default_factory=dict)

    # ---- derived cost helpers ----
    def one_time_cost(self) -> float:
        return sum(c.total for c in self.cost_lines if not c.recurring) + _nz(self.implementation_cost)

    def annual_recurring(self) -> float:
        return (sum(c.total for c in self.cost_lines if c.recurring)
                + _nz(self.annual_ops_cost) + _nz(self.annual_maintenance_cost))


# ----------------------------------------------------------------------------
# Engine
# ----------------------------------------------------------------------------
class ProcurementAnalysis:
    def __init__(self, suppliers: List[Supplier], weights: Optional[dict] = None,
                 policy: Optional[dict] = None, years: int = 3,
                 assumptions: Optional[list] = None):
        self.suppliers = list(suppliers)
        self.weights = dict(weights) if weights else dict(DEFAULT_WEIGHTS)
        self.policy = {**DEFAULT_POLICY, **(policy or {})}
        self.years = years
        self.assumptions = list(assumptions or [])
        # normalize weights to sum 1.0
        s = sum(self.weights.values())
        if s and abs(s - 1.0) > 1e-9:
            self.assumptions.append(f"Category weights summed to {s:.2f}; normalized to 1.00.")
            self.weights = {k: v / s for k, v in self.weights.items()}

    # ---------- scoring ----------
    def category_score(self, sup: Supplier, category: str) -> Optional[float]:
        block = sup.scores.get(category)
        if not block:
            return None
        vals = [d.get("score") for d in block.values() if d.get("score") is not None]
        return float(statistics.mean(vals)) if vals else None

    def category_scores(self) -> Dict[str, Dict[str, Optional[float]]]:
        return {s.name: {c: self.category_score(s, c) for c in self.weights} for s in self.suppliers}

    def weighted_total(self, sup: Supplier) -> float:
        # weighted mean over categories that have data; reweight missing
        num, den = 0.0, 0.0
        for cat, w in self.weights.items():
            cs = self.category_score(sup, cat)
            if cs is not None:
                num += w * cs
                den += w
        return (num / den) if den else 0.0  # 0..10 scale

    def ranked(self):
        rows = [(s, self.weighted_total(s)) for s in self.suppliers]
        rows.sort(key=lambda r: r[1], reverse=True)
        return rows  # [(Supplier, total10), ...] high->low

    # ---------- TCO ----------
    def tco(self, sup: Supplier, years: Optional[int] = None, include_risk: bool = True) -> dict:
        years = years or self.years
        acquisition = sum(c.total for c in sup.cost_lines if not c.recurring)
        implementation = _nz(sup.implementation_cost)
        esc = _nz(sup.price_escalation_pct) / 100.0
        annual = sup.annual_recurring()
        ops_total = sum(annual * ((1 + esc) ** yr) for yr in range(years))
        disposal = _nz(sup.disposal_cost)
        risk = self.risk_adder(sup, years) if include_risk else {"total": 0.0, "items": []}
        total = acquisition + implementation + ops_total + disposal + risk["total"]
        return {
            "supplier": sup.name,
            "years": years,
            "Acquisition (one-time)": acquisition,
            "Implementation (one-time)": implementation,
            f"Operations+Maintenance ({years}y, esc {esc*100:.1f}%)": ops_total,
            "Disposal (end of life)": disposal,
            "Risk-adjusted add-on": risk["total"],
            "risk_items": risk["items"],
            "TOTAL TCO": total,
        }

    def risk_adder(self, sup: Supplier, years: Optional[int] = None) -> dict:
        """Transparent, listed risk premiums. Every line is explainable to a buyer."""
        years = years or self.years
        items = []
        annual = sup.annual_recurring()

        # 1) lead-time pipeline holding cost beyond policy ceiling
        max_lt = self.policy["max_lead_time_days"]
        if sup.lead_time_days and sup.lead_time_days > max_lt:
            extra = sup.lead_time_days - max_lt
            hold = (extra / 365.0) * annual * self.policy["carrying_rate"] * years
            if hold:
                items.append((f"+{extra}d lead time over {max_lt}d ceiling (pipeline holding)", hold))

        # 2) missing ISO 9001 -> quality/rework risk premium (5% of annual * years)
        if self.policy["require_iso9001"] and sup.iso9001 is False:
            pen = 0.05 * annual * years
            items.append(("No ISO 9001 (quality/rework risk premium 5%)", pen))

        # 3) warranty shortfall -> proxy extended-coverage cost
        minw = self.policy["min_warranty_months"]
        if sup.warranty_months is not None and sup.warranty_months < minw:
            short = minw - sup.warranty_months
            pen = (short / 12.0) * 0.02 * (sup.one_time_cost() or annual)
            items.append((f"Warranty short {short}mo vs {minw}mo (coverage gap)", pen))

        # 4) escalation above policy -> flagged premium on top of modeled escalation
        maxesc = self.policy["max_price_escalation_pct"]
        if sup.price_escalation_pct and sup.price_escalation_pct > maxesc:
            over = (sup.price_escalation_pct - maxesc) / 100.0
            pen = over * annual * years * 0.5
            items.append((f"Escalation {sup.price_escalation_pct:.1f}% > {maxesc:.0f}% cap (volatility premium)", pen))

        # 5) auto-renew / weak termination -> lock-in risk
        notice = self.policy["min_auto_renew_notice_days"]
        if sup.auto_renew and (sup.auto_renew_notice_days or 0) < notice:
            pen = 0.03 * annual
            items.append(("Auto-renew without >=90d notice (lock-in risk)", pen))

        return {"total": float(sum(v for _, v in items)), "items": items}

    # ---------- difference / business-impact analysis ----------
    def differences_vs(self, baseline_name: str) -> List[dict]:
        base = self._get(baseline_name)
        out = []
        cap = self.policy["cost_of_capital"]
        carry = self.policy["carrying_rate"]
        for s in self.suppliers:
            if s.name == baseline_name:
                continue
            annual = s.annual_recurring()
            base_annual = base.annual_recurring()

            # payment terms -> working capital value (longer terms = our benefit)
            if s.payment_terms_days is not None and base.payment_terms_days is not None:
                d = s.payment_terms_days - base.payment_terms_days
                val = (d / 365.0) * annual * cap
                who = "US" if d > 0 else ("SUPPLIER" if d < 0 else "neutral")
                out.append({
                    "supplier": s.name, "dimension": "Payment terms",
                    "raw": f"{s.payment_terms_days}d vs {base.payment_terms_days}d ({d:+d}d)",
                    "impact_$": val, "benefits": who,
                    "explain": f"{d:+d} days of float on {_money(annual)}/yr at {cap*100:.0f}% cost of capital",
                })

            # lead time -> holding cost (longer lead = our cost)
            if s.lead_time_days is not None and base.lead_time_days is not None:
                d = s.lead_time_days - base.lead_time_days
                cost = (d / 365.0) * annual * carry
                who = "SUPPLIER" if d > 0 else ("US" if d < 0 else "neutral")
                out.append({
                    "supplier": s.name, "dimension": "Lead time",
                    "raw": f"{s.lead_time_days}d vs {base.lead_time_days}d ({d:+d}d)",
                    "impact_$": -cost if d > 0 else cost, "benefits": who,
                    "explain": f"{d:+d} days adds {_money(abs(cost))}/yr holding at {carry*100:.0f}% carrying rate",
                })

            # escalation -> multi-year cost delta
            if s.price_escalation_pct is not None and base.price_escalation_pct is not None:
                e_s = s.price_escalation_pct / 100.0
                e_b = base.price_escalation_pct / 100.0
                cum_s = sum(annual * ((1 + e_s) ** y) for y in range(self.years))
                cum_b = sum(base_annual * ((1 + e_b) ** y) for y in range(self.years))
                # isolate escalation effect on same base spend
                cum_s_flat = sum(annual * ((1 + e_s) ** y) for y in range(self.years))
                cum_s_noesc = annual * self.years
                delta = cum_s_flat - cum_s_noesc
                out.append({
                    "supplier": s.name, "dimension": "Price escalation",
                    "raw": f"{s.price_escalation_pct:.1f}% vs {base.price_escalation_pct:.1f}%",
                    "impact_$": -delta, "benefits": "SUPPLIER" if delta > 0 else "US",
                    "explain": f"{s.price_escalation_pct:.1f}% escalation adds {_money(delta)} over {self.years}y on {_money(annual)}/yr",
                })

            # warranty -> coverage delta (months)
            if s.warranty_months is not None and base.warranty_months is not None:
                d = s.warranty_months - base.warranty_months
                out.append({
                    "supplier": s.name, "dimension": "Warranty",
                    "raw": f"{s.warranty_months}mo vs {base.warranty_months}mo ({d:+d}mo)",
                    "impact_$": None, "benefits": "US" if d > 0 else ("SUPPLIER" if d < 0 else "neutral"),
                    "explain": f"{d:+d} months of coverage; reduces post-sale risk exposure" if d else "equal coverage",
                })
        return out

    # ---------- scenarios ----------
    def scenario(self, name: str, price_mult: float = 1.0, lead_delta_days: int = 0,
                 escalation_override: Optional[float] = None, years: Optional[int] = None) -> dict:
        """Return TCO per supplier under a what-if. Non-destructive (clones)."""
        years = years or self.years
        rows = {}
        for s in self.suppliers:
            clone = Supplier(
                name=s.name, scores=s.scores,
                payment_terms_days=s.payment_terms_days,
                price_escalation_pct=(escalation_override if escalation_override is not None else s.price_escalation_pct),
                warranty_months=s.warranty_months,
                lead_time_days=(None if s.lead_time_days is None else s.lead_time_days + lead_delta_days),
                iso9001=s.iso9001, auto_renew=s.auto_renew, auto_renew_notice_days=s.auto_renew_notice_days,
                implementation_cost=s.implementation_cost * price_mult,
                annual_ops_cost=s.annual_ops_cost * price_mult,
                annual_maintenance_cost=s.annual_maintenance_cost * price_mult,
                disposal_cost=s.disposal_cost,
                cost_lines=[CostLine(c.item, c.qty, c.unit_price * price_mult, c.recurring, c.note) for c in s.cost_lines],
            )
            tmp = ProcurementAnalysis([clone], self.weights, self.policy, years, [])
            rows[s.name] = tmp.tco(clone, years)["TOTAL TCO"]
        return {"scenario": name, "years": years, "tco": rows}

    # ---------- policy compliance ----------
    def policy_flags(self) -> Dict[str, List[str]]:
        out = {}
        p = self.policy
        for s in self.suppliers:
            f = []
            if s.payment_terms_days is not None and s.payment_terms_days < p["preferred_payment_terms_days"]:
                f.append(f"[AMBER] Net {s.payment_terms_days} < preferred Net {p['preferred_payment_terms_days']}")
            if s.lead_time_days is not None and s.lead_time_days > p["max_lead_time_days"]:
                f.append(f"[RED] Lead {s.lead_time_days}d > {p['max_lead_time_days']}d ceiling")
            if p["require_iso9001"] and s.iso9001 is False:
                f.append("[RED] No ISO 9001 (must-have)")
            if p["require_iso9001"] and s.iso9001 is None:
                f.append("[AMBER] ISO 9001 status unconfirmed")
            if s.warranty_months is not None and s.warranty_months < p["min_warranty_months"]:
                f.append(f"[RED] Warranty {s.warranty_months}mo < {p['min_warranty_months']}mo required")
            if s.price_escalation_pct is not None and s.price_escalation_pct > p["max_price_escalation_pct"]:
                f.append(f"[RED] Escalation {s.price_escalation_pct:.1f}% > {p['max_price_escalation_pct']:.0f}% cap")
            if s.auto_renew and (s.auto_renew_notice_days or 0) < p["min_auto_renew_notice_days"]:
                f.append(f"[RED] Auto-renew notice < {p['min_auto_renew_notice_days']}d")
            out[s.name] = f or ["[GREEN] No policy breaches detected"]
        return out

    # ---------- markdown renderers ----------
    def scorecard_md(self) -> str:
        cats = list(self.weights)
        head = "| Supplier | " + " | ".join(f"{c} ({self.weights[c]*100:.0f}%)" for c in cats) + " | **Weighted /10** | Rank | Status |"
        sep = "|" + "---|" * (len(cats) + 4)
        lines = [head, sep]
        rk = {s.name: i + 1 for i, (s, _) in enumerate(self.ranked())}
        for s in self.suppliers:
            cells = []
            for c in cats:
                cs = self.category_score(s, c)
                cells.append("n/a" if cs is None else f"{cs:.1f}")
            tot = self.weighted_total(s)
            lines.append(f"| **{s.name}** | " + " | ".join(cells) +
                         f" | **{tot:.2f}** | {rk[s.name]} | {_flag(tot)} |")
        return "\n".join(lines)

    def subscore_md(self, category: str) -> str:
        rows = ["| Sub-criterion | " + " | ".join(s.name for s in self.suppliers) + " | Evidence |",
                "|" + "---|" * (len(self.suppliers) + 2)]
        subs = []
        for s in self.suppliers:
            for k in s.scores.get(category, {}):
                if k not in subs:
                    subs.append(k)
        for sub in subs:
            cells = []
            ev = ""
            for s in self.suppliers:
                d = s.scores.get(category, {}).get(sub, {})
                cells.append("" if d.get("score") is None else f"{d['score']}")
                if not ev and d.get("evidence"):
                    ev = d["evidence"]
            rows.append(f"| {sub} | " + " | ".join(cells) + f" | {ev} |")
        return "\n".join(rows)

    def comparison_matrix_md(self) -> str:
        fields = [
            ("Payment terms", lambda s: f"Net {s.payment_terms_days}" if s.payment_terms_days is not None else "n/a"),
            ("Price validity", lambda s: f"{s.price_validity_days}d" if s.price_validity_days is not None else "n/a"),
            ("Escalation", lambda s: f"{s.price_escalation_pct:.1f}%" if s.price_escalation_pct is not None else "n/a"),
            ("Lead time", lambda s: f"{s.lead_time_days}d" if s.lead_time_days is not None else "n/a"),
            ("Warranty", lambda s: f"{s.warranty_months}mo" if s.warranty_months is not None else "n/a"),
            ("ISO 9001", lambda s: {True: "Yes", False: "No", None: "?"}[s.iso9001]),
            ("Auto-renew", lambda s: ("Yes" if s.auto_renew else "No") if s.auto_renew is not None else "n/a"),
            ("Termination", lambda s: s.termination_clause or "n/a"),
            ("IP / ownership", lambda s: s.ip_ownership or "n/a"),
            ("1-time cost", lambda s: _money(s.one_time_cost())),
            ("Annual recurring", lambda s: _money(s.annual_recurring())),
            (f"{self.years}y TCO (risk-adj)", lambda s: _money(self.tco(s)["TOTAL TCO"])),
        ]
        head = "| Attribute | " + " | ".join(s.name for s in self.suppliers) + " |"
        sep = "|" + "---|" * (len(self.suppliers) + 1)
        rows = [head, sep]
        for label, fn in fields:
            rows.append(f"| {label} | " + " | ".join(fn(s) for s in self.suppliers) + " |")
        return "\n".join(rows)

    def cost_breakdown_md(self) -> str:
        rows = ["| Supplier | Line item | Qty | Unit | Line total | Type |",
                "|---|---|---|---|---|---|"]
        for s in self.suppliers:
            if not s.cost_lines:
                rows.append(f"| {s.name} | (no itemized lines) |  |  |  |  |")
            for c in s.cost_lines:
                rows.append(f"| {s.name} | {c.item} | {c.qty:g} | {_money(c.unit_price)} | {_money(c.total)} | {'recurring/yr' if c.recurring else 'one-time'} |")
        return "\n".join(rows)

    def tco_md(self, years: Optional[int] = None) -> str:
        years = years or self.years
        comp_keys = ["Acquisition (one-time)", "Implementation (one-time)",
                     f"Operations+Maintenance ({years}y, esc 0.0%)", "Disposal (end of life)",
                     "Risk-adjusted add-on", "TOTAL TCO"]
        tcos = {s.name: self.tco(s, years) for s in self.suppliers}
        # rebuild op label per supplier may differ; use generic
        rows = ["| TCO component | " + " | ".join(s.name for s in self.suppliers) + " |",
                "|" + "---|" * (len(self.suppliers) + 1)]
        labels = ["Acquisition (one-time)", "Implementation (one-time)", "Operations+Maintenance", "Disposal (end of life)", "Risk-adjusted add-on", "TOTAL TCO"]
        for lab in labels:
            cells = []
            for s in self.suppliers:
                t = tcos[s.name]
                if lab == "Operations+Maintenance":
                    key = [k for k in t if k.startswith("Operations+Maintenance")][0]
                    cells.append(_money(t[key]))
                else:
                    cells.append(_money(t[lab]))
            bold = "**" if lab == "TOTAL TCO" else ""
            rows.append(f"| {bold}{lab}{bold} | " + " | ".join(f"{bold}{c}{bold}" for c in cells) + " |")
        return "\n".join(rows)

    def differences_md(self, baseline_name: str) -> str:
        diffs = self.differences_vs(baseline_name)
        rows = [f"_Baseline = {baseline_name}_",
                "",
                "| Supplier | Dimension | Raw difference | $ impact / yr | Benefits | Explanation |",
                "|---|---|---|---|---|---|"]
        for d in diffs:
            imp = "—" if d["impact_$"] is None else _money(d["impact_$"])
            rows.append(f"| {d['supplier']} | {d['dimension']} | {d['raw']} | {imp} | {d['benefits']} | {d['explain']} |")
        return "\n".join(rows)

    def scenarios_md(self, scenarios: List[dict]) -> str:
        head = "| Scenario | " + " | ".join(s.name for s in self.suppliers) + " |"
        rows = [head, "|" + "---|" * (len(self.suppliers) + 1)]
        base = {s.name: self.tco(s)["TOTAL TCO"] for s in self.suppliers}
        rows.append("| **Base case** | " + " | ".join(f"**{_money(base[s.name])}**" for s in self.suppliers) + " |")
        for sc in scenarios:
            rows.append(f"| {sc['scenario']} | " + " | ".join(_money(sc['tco'].get(s.name)) for s in self.suppliers) + " |")
        return "\n".join(rows)

    def audit_md(self) -> str:
        srcs = []
        for s in self.suppliers:
            if s.sources:
                srcs.append(f"- {s.name}: " + "; ".join(s.sources))
        assum = self.assumptions + [
            f"Carrying rate {self.policy['carrying_rate']*100:.0f}%, cost of capital {self.policy['cost_of_capital']*100:.0f}%, horizon {self.years}y.",
            "Risk add-ons are explicit premiums (listed per supplier in TCO risk_items); adjust or zero them with include_risk=False.",
        ]
        return ("**Sources used from quotes:**\n" + ("\n".join(srcs) if srcs else "- (none tagged)") +
                "\n\n**Assumptions made:**\n" + "\n".join(f"- {a}" for a in assum) +
                "\n\nI am ready for your override or next step.")

    # ---------- charts (call save_plot('current') after each) ----------
    def radar_chart(self, title="Weighted scorecard - category profile"):
        if not HAS_MPL:
            raise RuntimeError("matplotlib required for charts: pip install matplotlib")
        cats = list(self.weights)
        n = len(cats)
        ang = list(__import__("math").pi * 2 * i / n for i in range(n)) if np is None else np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
        ang += ang[:1]
        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
        for s in self.suppliers:
            vals = [(_nz(self.category_score(s, c))) for c in cats]
            vals += vals[:1]
            ax.plot(ang, vals, linewidth=2, label=s.name)
            ax.fill(ang, vals, alpha=0.08)
        ax.set_xticks(ang[:-1])
        ax.set_xticklabels([c.replace(" / ", "/\n").replace(" & ", " &\n") for c in cats], fontsize=8)
        ax.set_ylim(0, 10)
        ax.set_title(title, pad=20, fontsize=12, weight="bold")
        ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1), fontsize=9)
        fig.tight_layout()
        return fig

    def weighted_bar(self, title="Weighted total score (/10)"):
        if not HAS_MPL:
            raise RuntimeError("matplotlib required for charts: pip install matplotlib")
        rows = self.ranked()
        names = [s.name for s, _ in rows]
        vals = [t for _, t in rows]
        colors = {GREEN: "#2e9e5b", AMBER: "#e0a83b", RED: "#cf4b3a"}
        fig, ax = plt.subplots(figsize=(8, 4.5))
        bars = ax.bar(names, vals, color=[colors[_band(v)] for v in vals], edgecolor="#222")
        ax.set_ylim(0, 10)
        ax.axhline(7.5, ls="--", c="#2e9e5b", lw=1, alpha=0.6)
        ax.axhline(5.0, ls="--", c="#cf4b3a", lw=1, alpha=0.6)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.15, f"{v:.2f}", ha="center", weight="bold")
        ax.set_ylabel("Weighted score")
        ax.set_title(title, weight="bold")
        fig.tight_layout()
        return fig

    def tco_waterfall(self, supplier_name: str, years: Optional[int] = None):
        if not HAS_MPL:
            raise RuntimeError("matplotlib required for charts: pip install matplotlib")
        t = self.tco(self._get(supplier_name), years)
        labels = ["Acquisition", "Implementation", "Ops+Maint", "Disposal", "Risk add-on"]
        keys = ["Acquisition (one-time)", "Implementation (one-time)",
                [k for k in t if k.startswith("Operations+Maintenance")][0],
                "Disposal (end of life)", "Risk-adjusted add-on"]
        vals = [t[k] for k in keys]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        cum = 0.0
        for i, (lab, v) in enumerate(zip(labels, vals)):
            ax.bar(i, v, bottom=cum, color="#4a73b8", edgecolor="#222")
            if v:
                ax.text(i, cum + v / 2, _money(v), ha="center", va="center", color="white", fontsize=8)
            cum += v
        ax.bar(len(labels), cum, color="#222", edgecolor="#222")
        ax.text(len(labels), cum / 2, _money(cum), ha="center", va="center", color="white", weight="bold", fontsize=8)
        ax.set_xticks(range(len(labels) + 1))
        ax.set_xticklabels(labels + ["TOTAL"], rotation=20, ha="right")
        ax.set_ylabel("Cost ($)")
        ax.set_title(f"TCO build-up - {supplier_name} ({t['years']}y)", weight="bold")
        fig.tight_layout()
        return fig

    # ---------- util ----------
    def _get(self, name: str) -> Supplier:
        for s in self.suppliers:
            if s.name == name:
                return s
        raise KeyError(name)

    def full_report_md(self, baseline_name: Optional[str] = None,
                       scenarios: Optional[List[dict]] = None) -> str:
        baseline_name = baseline_name or self.ranked()[0][0].name
        parts = []
        parts.append("## 2. Weighted Scorecard\n" + self.scorecard_md())
        parts.append("## 3. Side-by-Side Comparison Matrix\n" + self.comparison_matrix_md())
        parts.append("### Cost breakdown\n" + self.cost_breakdown_md())
        parts.append("## 4. Difference & Business-Impact Analysis\n" + self.differences_md(baseline_name))
        parts.append("## 5. TCO\n" + self.tco_md())
        if scenarios:
            parts.append("### Scenarios\n" + self.scenarios_md(scenarios))
        parts.append("## 6. Policy / Compliance Flags\n" +
                     "\n".join(f"- **{k}**: " + "; ".join(v) for k, v in self.policy_flags().items()))
        parts.append("## 8. Audit & Transparency\n" + self.audit_md())
        return "\n\n".join(parts)


if __name__ == "__main__":
    print("procurement_agent engine loaded. Build Supplier(...) objects and a ProcurementAnalysis(...).")
