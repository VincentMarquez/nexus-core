import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge" / "bridges"))
sys.path.insert(0, str(ROOT / "src"))
os.environ["NEXUS_PROJECT_ROOT"] = str(ROOT)


def test_tool_catalog_and_run():
    import ollama_tools as ot

    cat = ot._tool_catalog()
    assert "run_project_checks" in cat or "list_project_files" in cat
    out = ot._run_tool("list_platforms", {})
    assert "nexus" in out.lower() or "Grok" in out or "grok" in out


def test_handle_turn_tool_then_final(monkeypatch):
    import ollama_tools as ot

    calls = {"n": 0}

    def fake_gen(host, model, prompt, num_predict=768):
        calls["n"] += 1
        if calls["n"] == 1:
            return 'TOOL_CALL {"name": "list_platforms", "arguments": {}}'
        return "Platforms look good."

    monkeypatch.setattr(ot, "_ollama_generate", fake_gen)
    text = ot.handle_turn("list platforms", host="http://x", model="m", agent="local")
    assert "Platforms look good" in text
    assert calls["n"] >= 2
