# 07 — Procurement intelligence agents

**Goal:** Run the deterministic procurement engine + expert panel that lives inside NEXUS.

## Demo (no private quotes)

```bash
./run                 # optional: bus/agents
nexus procure demo
less .nexus_state/procurement_demo/report.md
```

Synthetic 3-supplier RFQ → scorecard, TCO, scenarios, policy flags, logistics/legal/engineering expert review.

## Persona for LLM agents

```bash
nexus procure persona
# or open docs/agents/PROCUREMENT.md
```

Load that as the system prompt for Claude / local LLM / bus agent.  
**Rule:** the model extracts `Supplier(...)`; **all numbers** come from `nexus.procurement`.

## Python

```python
from nexus.procurement import Supplier, CostLine, ProcurementAnalysis, ExpertPanel

# build suppliers from your quotes (see docs/agents/PROCUREMENT.md)
an = ProcurementAnalysis([/* ... */], years=3)
print(an.full_report_md(baseline_name="..."))
ExpertPanel().review(an.suppliers, reference={"part_number": "...", "revision": "..."})
```

## Charts (optional)

```bash
pip install "nexus-multi-agent[charts]"   # or: pip install matplotlib
nexus procure demo
ls .nexus_state/procurement_demo/plots/
```
