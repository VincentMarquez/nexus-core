"""Agent wiring helpers used by automatic start."""

from nexus.cli import enable_agent_bridges, _model_installed, _resolve_model_name


class FakeRT:
    def __init__(self):
        self.started = []
        self.stopped = []

    def start_ollama_bridge(self, agent, model):
        self.started.append(("ollama", agent, model))
        return 1

    def start_mock_bridge(self, agent):
        self.started.append(("mock", agent))
        return 1

    def start_cli_bridge(self, agent, cmd):
        self.started.append(("cli", agent, tuple(cmd)))
        return 1

    def stop(self, name):
        self.stopped.append(name)
        return True


class HW:
    def __init__(self, tools):
        self.tools = tools


def test_model_installed_prefix():
    assert _model_installed("gemma2:2b", ["gemma2:2b"])
    assert _model_installed("gemma2:2b", ["gemma2:2b-instruct-q4"])
    assert not _model_installed("gemma2:2b", ["nomic-embed-text"])


def test_resolve_model_name():
    assert _resolve_model_name("gemma2:2b", ["gemma2:2b-q4"]) == "gemma2:2b-q4"


def test_enable_agents_auto_cli():
    rt = FakeRT()
    hw = HW({"claude": True, "codex": False, "gemini": True})
    backends = enable_agent_bridges(rt, hw, use_cli=True, ollama_ok=True, model="gemma2:2b")
    assert backends["local"].startswith("ollama:")
    assert backends["claude"].startswith("cli:")
    assert backends["gpt"] == "mock"
    assert backends["gemini"].startswith("cli:")
    kinds = {t[0] for t in rt.started}
    assert "cli" in kinds
    assert "mock" in kinds


def test_enable_agents_no_cli():
    rt = FakeRT()
    hw = HW({"claude": True, "codex": True, "gemini": True})
    backends = enable_agent_bridges(rt, hw, use_cli=False, ollama_ok=False, model="x")
    assert backends == {"local": "mock", "claude": "mock", "gpt": "mock", "gemini": "mock"}
    assert all(t[0] == "mock" for t in rt.started)
