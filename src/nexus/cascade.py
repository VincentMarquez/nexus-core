"""Cascade index — shallow map first, deep files later (D*-style)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CascadeIndex:
    """
    Navigation aid injected at the top of agent context.

    Production systems often store this as JSON on disk and rebuild when
    agents write new outputs. Here it is an in-memory map for clarity.
    """

    system: dict[str, Any] = field(default_factory=dict)
    branches: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def demo(cls) -> "CascadeIndex":
        return cls(
            system={
                "name": "nexus-core-demo",
                "purpose": "Multi-agent research workflow kit",
                "projects": ["demo"],
                "entrypoints": {
                    "engine": "nexus.engine.DurableEngine",
                    "memory": "nexus.memory.MemorySpine",
                    "pipeline": "nexus.steps.StepPolicy",
                },
                "laws": [
                    "Read this index before deep files",
                    "Autonomy default off",
                    "Judge scores success_criteria, not presence",
                ],
            },
            branches={
                "engine": {
                    "modules": ["engine.py", "steps.py", "agents.py", "judge.py"],
                    "role": "Durable 10-step orchestration",
                },
                "memory": {
                    "modules": ["memory.py"],
                    "role": "Namespaced hybrid retrieval",
                },
                "trust": {
                    "modules": ["trust.py"],
                    "role": "Provenance and verdicts",
                },
            },
        )

    def overview(self) -> str:
        """D*≈1 block — keep short; inject often."""
        import json

        return json.dumps(self.system, indent=2)

    def branch(self, name: str) -> str:
        import json

        b = self.branches.get(name)
        if not b:
            return f"(unknown branch: {name})"
        return json.dumps({name: b}, indent=2)

    def prompt_block(self, *, max_chars: int = 1200) -> str:
        """Material for agent system/context prompts."""
        text = (
            "# CASCADE INDEX (read first)\n"
            + self.overview()
            + "\n# BRANCHES\n"
            + ", ".join(sorted(self.branches))
            + "\n# RULE: do not open deep files until you know which branch applies.\n"
        )
        return text[:max_chars]
