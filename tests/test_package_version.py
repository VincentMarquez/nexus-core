from __future__ import annotations

import tomllib
from pathlib import Path

import nexus


def test_runtime_version_matches_project_metadata():
    project = Path(__file__).resolve().parents[1]
    data = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    assert nexus.__version__ == data["project"]["version"]
