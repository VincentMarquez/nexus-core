
"""
experts.py  —  Multi-disciplinary review panel for supplier quotes.
==================================================================
Each expert is a "lens" that reads the same ingested quote data (Supplier.attrs + raw text)
and raises structured Findings from its discipline:

  * IncotermsExpert  — logistics: Incoterms 2020, who bears freight/insurance/duty, risk
                       transfer, price-comparability (EXW vs DDP), wrong-term-for-mode errors.
  * LegalExpert      — contract clauses: liability cap, termination symmetry, IP, governing law,
                       auto-renew, indemnity/force-majeure/insurance/dispute presence.
  * TechnicalExpert  — engineering: part-number & revision validation vs the RFQ and across
                       suppliers, 'equivalent/substitute' parts, superseded revisions, missing specs.

ExpertPanel runs them all and assembles findings. The procurement engine scores; these lenses
catch the things a price comparison misses. Pure-Python; pairs with nexus.procurement.engine (no pandas required).
"""
from __future__ import annotations
from dataclasses import dataclass
import re

SEV_RANK = {"critical": 3, "warn": 2, "info": 1}
SEV_ICON = {"critical": "🔴 critical", "warn": "🟠 warn", "info": "🔵 info"}


@dataclass
class Finding:
    expert: str
    supplier: str
    severity: str          # critical | warn | info
    category: str
    finding: str
    recommendation: str = ""
    evidence: str = ""


class ExpertLens:
    name = "Expert"
    def review(self, suppliers, reference=None) -> list: return []


# ======================================================================= Incoterms / logistics
# Incoterms 2020: freight = who pays MAIN carriage; ins = insurance; exp/imp = customs clearance
INCOTERMS_2020 = {
    "EXW": dict(name="Ex Works", freight="Buyer", ins="Buyer", exp="Buyer", imp="Buyer", sea_only=False, risk="at seller's premises (goods placed at buyer's disposal)"),
    "FCA": dict(name="Free Carrier", freight="Buyer", ins="Buyer", exp="Seller", imp="Buyer", sea_only=False, risk="when handed to buyer's carrier"),
    "FAS": dict(name="Free Alongside Ship", freight="Buyer", ins="Buyer", exp="Seller", imp="Buyer", sea_only=True, risk="alongside the vessel at origin port"),
    "FOB": dict(name="Free On Board", freight="Buyer", ins="Buyer", exp="Seller", imp="Buyer", sea_only=True, risk="once on board the vessel at origin port"),
    "CFR": dict(name="Cost and Freight", freight="Seller", ins="Buyer", exp="Seller", imp="Buyer", sea_only=True, risk="on board at origin (cost to dest port, risk transfers early)"),
    "CIF": dict(name="Cost Insurance & Freight", freight="Seller", ins="Seller(min)", exp="Seller", imp="Buyer", sea_only=True, risk="on board at origin (risk transfers early)"),
    "CPT": dict(name="Carriage Paid To", freight="Seller", ins="Buyer", exp="Seller", imp="Buyer", sea_only=False, risk="at first carrier (cost to named place)"),
    "CIP": dict(name="Carriage & Insurance Paid", freight="Seller", ins="Seller(all-risk)", exp="Seller", imp="Buyer", sea_only=False, risk="at first carrier"),
    "DAP": dict(name="Delivered At Place", freight="Seller", ins="Seller", exp="Seller", imp="Buyer", sea_only=False, risk="at destination, ready for unloading"),
    "DPU": dict(name="Delivered At Place Unloaded", freight="Seller", ins="Seller", exp="Seller", imp="Buyer", sea_only=False, risk="at destination, unloaded by seller"),
    "DDP": dict(name="Delivered Duty Paid", freight="Seller", ins="Seller", exp="Seller", imp="Seller", sea_only=False, risk="at destination, duties paid (max seller obligation)"),
}
_REMOVED = {"DAT": "DPU", "DDU": "DAP", "DEQ": "DPU/DAP", "DES": "DAP", "DAF": "DAP/DPU"}


class IncotermsExpert(ExpertLens):
    name = "Logistics / Incoterms"

    @staticmethod
    def price_basis(code):
        t = INCOTERMS_2020[code]
        inc = [x for x, on in [("main freight", t["freight"] == "Seller"),
                               ("insurance", t["ins"].startswith("Seller")),
                               ("import duty/clearance", t["imp"] == "Seller")] if on]
        out = [x for x, on in [("main freight", t["freight"] == "Buyer"),
                               ("import duty/clearance", t["imp"] == "Buyer"),
                               ("export clearance", t["exp"] == "Buyer")] if on]
        return ("includes " + ", ".join(inc) if inc else "covers carriage to handover only"), \
               ("buyer bears " + ", ".join(out) if out else "buyer bears nothing further")

    def review(self, suppliers, reference=None):
        F = []
        terms_seen = {}
        for n, s in suppliers.items():
            code = (s.attrs.get("incoterm") or "").upper()
            place = s.attrs.get("incoterm_place", "")
            if not code:
                F.append(Finding(self.name, n, "critical", "Missing Incoterm",
                                 "No Incoterm stated — landed cost and risk transfer are undefined.",
                                 "Require an Incoterms 2020 rule + named place before comparing prices.")); continue
            if code in _REMOVED:
                F.append(Finding(self.name, n, "warn", "Deprecated term",
                                 f"{code} is not an Incoterms 2020 rule.",
                                 f"Replace with {_REMOVED[code]} (2020).", code)); 
            t = INCOTERMS_2020.get(code)
            if not t:
                F.append(Finding(self.name, n, "warn", "Unknown term", f"Unrecognised term '{code}'.", "Confirm intended Incoterm.")); continue
            terms_seen[n] = code
            incl, bears = self.price_basis(code)
            F.append(Finding(self.name, n, "info", "Cost responsibility",
                             f"{code} ({t['name']}{', ' + place if place else ''}): price {incl}; {bears}. Risk transfers {t['risk']}.",
                             "", f"{code} {place}"))
            if t["sea_only"]:
                F.append(Finding(self.name, n, "warn", "Term vs transport mode",
                                 f"{code} is for sea/inland-waterway (bulk/break-bulk). For containerised or air freight it is technically incorrect.",
                                 f"If shipping containers/air, switch to {'FCA' if code in ('FAS','FOB') else 'CPT/CIP/DAP'}.", f"{code} {place}"))
            ft = s.attrs.get("freight_terms")
            if ft == "prepaid" and t["freight"] == "Buyer":
                F.append(Finding(self.name, n, "warn", "Inconsistent freight terms",
                                 f"'{code}' puts main freight on the buyer, but quote says freight prepaid — contradiction.",
                                 "Clarify who actually pays/arranges main carriage."))
        # comparability across suppliers
        if len(set(terms_seen.values())) > 1:
            spread = ", ".join(f"{n}={c}" for n, c in terms_seen.items())
            F.append(Finding(self.name, "(all)", "critical", "Prices not comparable",
                             f"Quotes use different Incoterms ({spread}); an EXW/FOB price excludes freight & duties that a DDP price already includes.",
                             "Normalise every quote to the same delivered/landed basis (e.g., DDP-equivalent) before ranking on price."))
        return F


# ======================================================================= Legal
class LegalExpert(ExpertLens):
    name = "Legal / Contracts"
    CLAUSES = {  # raw-text presence checks -> (label, severity if missing)
        "indemnif": ("Indemnification", "warn"),
        "force\\s+majeure": ("Force majeure", "info"),
        "confidential|non-disclosure|\\bNDA\\b": ("Confidentiality", "info"),
        "insur(?:e|ance)": ("Insurance requirement", "info"),
        "arbitrat|dispute\\s+resolution|jurisdiction|venue": ("Dispute resolution", "warn"),
        "consequential|indirect\\s+damages": ("Consequential-damages waiver", "info"),
    }

    def review(self, suppliers, reference=None):
        F = []; pref = reference or {}
        min_war = pref.get("min_warranty_months", 24)
        for n, s in suppliers.items():
            a = s.attrs; text = a.get("_text", "") or ""
            # liability cap
            cap = a.get("liability_cap")
            if not cap:
                F.append(Finding(self.name, n, "critical", "Liability cap",
                                 "No limitation-of-liability clause found — uncapped exposure or unstated.",
                                 "Require an aggregate liability cap (≥ 12 months' fees)."))
            elif re.search(r"50%|%\s*of\s*fees|3[- ]?mo", str(cap), re.I) or "3" in str(cap) and "month" in str(cap).lower():
                F.append(Finding(self.name, n, "warn", "Weak liability cap",
                                 f"Liability cap is supplier-favourable ({cap}).",
                                 "Negotiate to ≥ 12 months' / 1× annual fees.", str(cap)))
            else:
                F.append(Finding(self.name, n, "info", "Liability cap", f"Liability capped at {cap}.", "", str(cap)))
            # termination symmetry
            term = str(a.get("termination") or "")
            if "buyer cannot terminate" in term.lower() or "may not terminate" in text.lower():
                F.append(Finding(self.name, n, "critical", "One-sided termination",
                                 "Supplier may terminate but buyer may not terminate for convenience.",
                                 "Demand mutual termination-for-convenience rights.", term))
            elif not term:
                F.append(Finding(self.name, n, "warn", "Termination", "No termination clause found.",
                                 "Add mutual termination for convenience with reasonable notice."))
            # IP
            ip = str(a.get("ip_ownership") or "")
            if ip.startswith("supplier"):
                F.append(Finding(self.name, n, "warn", "IP ownership",
                                 "Supplier retains IP / tooling in the work product.",
                                 "For bespoke work, buyer should own work-product IP (and paid-for tooling).", ip))
            # governing law
            if not a.get("governing_law"):
                F.append(Finding(self.name, n, "warn", "Governing law",
                                 "No governing law / jurisdiction specified.",
                                 "Specify governing law and venue.", ""))
            # auto-renew
            if a.get("auto_renew") is True:
                notice = a.get("auto_renew_notice_days")
                F.append(Finding(self.name, n, "warn", "Auto-renewal",
                                 f"Evergreen auto-renewal with {notice}-day notice." if notice else "Evergreen auto-renewal clause.",
                                 "Convert to fixed term or require ≥90-day non-renewal notice.", ""))
            # warranty
            war = a.get("warranty_months")
            if war is not None and war < min_war:
                F.append(Finding(self.name, n, "warn", "Warranty",
                                 f"Warranty {war} mo is below the {min_war}-mo standard.",
                                 f"Extend warranty to ≥{min_war} months.", f"{war} mo"))
            # clause presence (only if we have raw text)
            if text:
                for pat, (label, sev) in self.CLAUSES.items():
                    if not re.search(pat, text, re.I):
                        F.append(Finding(self.name, n, sev, f"Missing: {label}",
                                         f"{label} clause not found in the quote.",
                                         f"Confirm whether {label.lower()} is addressed in the master terms."))
        return F


# ======================================================================= Technical / engineering
def _rev_rank(r):
    if r is None: return None
    r = str(r).strip().upper()
    if r.isdigit(): return ("n", int(r))
    if len(r) == 1 and r.isalpha(): return ("a", ord(r))
    return ("s", r)

def _rev_cmp(a, b):   # -1 if a older, 0 equal, 1 a newer, None incomparable
    ra, rb = _rev_rank(a), _rev_rank(b)
    if ra is None or rb is None or ra[0] != rb[0]: return None
    return (ra[1] > rb[1]) - (ra[1] < rb[1])


class TechnicalExpert(ExpertLens):
    name = "Engineering / Technical"

    def review(self, suppliers, reference=None):
        F = []; ref = reference or {}
        ref_pn = (ref.get("part_number") or "").upper().replace(" ", "")
        ref_rev = ref.get("revision")
        # per-supplier vs RFQ
        for n, s in suppliers.items():
            a = s.attrs
            pn = (a.get("part_number") or "")
            rev = a.get("revision")
            if not pn:
                F.append(Finding(self.name, n, "warn", "Part number",
                                 "No part number quoted — cannot verify the item matches the RFQ.",
                                 "Require the exact P/N (and revision) on the quote."))
            elif ref_pn and pn.upper().replace(" ", "") != ref_pn:
                F.append(Finding(self.name, n, "critical", "Wrong part number",
                                 f"Quotes P/N {pn} but the RFQ specifies {ref.get('part_number')}.",
                                 "Reject or clarify — this may be the wrong item entirely.", pn))
            if a.get("part_equivalent"):
                F.append(Finding(self.name, n, "warn", "Non-exact part",
                                 "Offered as 'equivalent/substitute', not the exact specified part.",
                                 "Require engineering equivalency evidence and sign-off before acceptance.", "equivalent"))
            if ref_rev and rev:
                c = _rev_cmp(rev, ref_rev)
                if c is None and str(rev).upper() != str(ref_rev).upper():
                    F.append(Finding(self.name, n, "warn", "Revision mismatch",
                                     f"Quotes Rev {rev}; RFQ is Rev {ref_rev} (cannot order them).",
                                     "Confirm which revision is correct.", f"Rev {rev}"))
                elif c is not None and c < 0:
                    F.append(Finding(self.name, n, "critical", "Superseded revision",
                                     f"Quotes Rev {rev}, which is older than the current Rev {ref_rev} — risk of obsolete/incorrect design.",
                                     "Require quote against the current revision.", f"Rev {rev}"))
                elif c is not None and c > 0:
                    F.append(Finding(self.name, n, "info", "Newer revision",
                                     f"Quotes Rev {rev}, newer than the RFQ Rev {ref_rev} — confirm it is approved.", "", f"Rev {rev}"))
            elif rev is None and pn:
                F.append(Finding(self.name, n, "info", "Revision not stated",
                                 f"P/N {pn} quoted without a revision.", "Pin the drawing revision to avoid ambiguity."))
        # cross-supplier consistency (catches 'someone is quoting the wrong part')
        pns = {n: (s.attrs.get("part_number") or "").upper().replace(" ", "") for n, s in suppliers.items() if s.attrs.get("part_number")}
        revs = {n: s.attrs.get("revision") for n, s in suppliers.items() if s.attrs.get("revision")}
        if len(set(pns.values())) > 1:
            F.append(Finding(self.name, "(all)", "critical", "Inconsistent part numbers",
                             "Suppliers quoted different part numbers: " + ", ".join(f"{n}={p}" for n, p in pns.items()) + ".",
                             "Confirm the correct P/N — at least one supplier is quoting the wrong item."))
        if len(set(str(v).upper() for v in revs.values())) > 1:
            F.append(Finding(self.name, "(all)", "warn", "Inconsistent revisions",
                             "Suppliers quoted different revisions: " + ", ".join(f"{n}=Rev {v}" for n, v in revs.items()) + ".",
                             "Align all suppliers to the same (current) revision before comparing."))
        return F


# ======================================================================= Panel
class ExpertPanel:
    def __init__(self, lenses=None):
        self.lenses = lenses or [IncotermsExpert(), LegalExpert(), TechnicalExpert()]

    def review(self, suppliers, reference=None):
        # accept list[Supplier] or dict[name, Supplier]
        if not isinstance(suppliers, dict):
            suppliers = {getattr(s, "name", str(i)): s for i, s in enumerate(suppliers)}
        # ensure .attrs exists
        for s in suppliers.values():
            if not hasattr(s, "attrs") or s.attrs is None:
                s.attrs = {}
        out = []
        for lens in self.lenses:
            out.extend(lens.review(suppliers, reference))
        self.findings = out
        return out

    def findings_table(self):
        return [
            {
                "Severity": SEV_ICON[f.severity],
                "Expert": f.expert,
                "Supplier": f.supplier,
                "Category": f.category,
                "Finding": f.finding,
                "Recommendation": f.recommendation,
            }
            for f in sorted(self.findings, key=lambda x: (-SEV_RANK[x.severity], x.expert))
        ]

    def counts(self):
        from collections import Counter
        c = Counter(f.severity for f in self.findings)
        return {"critical": c.get("critical", 0), "warn": c.get("warn", 0), "info": c.get("info", 0)}

    def report_md(self):
        L = [
            f"### Expert Panel Review — {self.counts()['critical']} critical, "
            f"{self.counts()['warn']} warnings, {self.counts()['info']} notes\n"
        ]
        for lens in self.lenses:
            fs = [f for f in self.findings if f.expert == lens.name]
            if not fs:
                continue
            L.append(f"#### {lens.name}\n")
            L.append("| Sev | Supplier | Finding | Recommendation |")
            L.append("|---|---|---|---|")
            for f in sorted(fs, key=lambda x: -SEV_RANK[x.severity]):
                sev = SEV_ICON[f.severity].split()[0]
                finding = (f.finding or "").replace("|", "/")
                rec = (f.recommendation or "").replace("|", "/")
                L.append(f"| {sev} | {f.supplier} | {finding} | {rec} |")
            L.append("")
        return "\n".join(L)
