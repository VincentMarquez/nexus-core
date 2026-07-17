import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

from nexus.bus_client import BusClient
from nexus.agents import AgentPanel, _parse_json_object


def test_parse_json_object():
    assert _parse_json_object('{"a": 1}')["a"] == 1
    assert _parse_json_object('here\n```json\n{"b": 2}\n```')["b"] == 2


def test_bus_client_against_stub_server():
    """Hermetic: stub both bus status AND Ollama shapes so unit tests never hit live :11434.

    Design note: local/kairos route through Ollama (``_message_ollama``), not async
    ``/api/message``. The stub must serve ``/api/chat`` in Ollama form.
    """

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/health":
                body = {"ok": True}
            elif self.path == "/api/status":
                # both list and dict shapes accepted by agent_online
                body = {
                    "uptime": 1,
                    "agents": {"local": True, "claude": True},
                }
            elif self.path == "/api/tags":
                # Ollama tags (agent_online local/kairos)
                body = {"models": [{"name": "gemma4:26b"}]}
            else:
                self.send_response(404)
                self.end_headers()
                return
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            n = int(self.headers.get("content-length", 0))
            _ = self.rfile.read(n)
            # Ollama chat shape used by BusClient._message_ollama
            if self.path == "/api/chat":
                raw = json.dumps(
                    {"message": {"role": "assistant", "content": "hello-from-stub"}}
                ).encode()
            else:
                # legacy bus-shaped reply (unused by local route today)
                raw = json.dumps(
                    {"id": "1", "agent": "local", "text": "hello-from-stub"}
                ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    httpd = HTTPServer(("127.0.0.1", 0), H)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        c = BusClient(base_url=base, ollama_url=base)
        assert c.is_reachable()
        assert c.agent_online("local")
        assert c.message("local", "hi") == "hello-from-stub"
    finally:
        httpd.shutdown()


def test_from_bus_fallback_when_down():
    panel = AgentPanel.from_bus(
        base_url="http://127.0.0.1:1",  # nothing listening
        mock_fallback=True,
    )
    # roles should be mock-fallback so health is still true
    assert panel.health().get("planner") is True
