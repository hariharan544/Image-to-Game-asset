"""LLM supervisor against a fake OpenAI-compatible server (what Ollama / LM Studio expose)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from forge.supervisor import LLMSupervisor, Observation

ANSWER = {"content": ""}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"data": []}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["messages"][0]["role"] == "system"
        out = {"choices": [{"message": {"role": "assistant", "content": ANSWER["content"]}}]}
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(out).encode())


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def obs(errors=1):
    issues = [{"code": "UV_OVERLAP", "severity": "error", "message": "m"}] * errors
    return Observation(asset="a", stage="uv", attempt=1, params={"margin_px": 8, "method": "smart"},
                       result={}, issues=issues, history=[])


def test_valid_answer_is_applied(server):
    ANSWER["content"] = '{"action": "uv_bigger_margin", "reason": "islands touch"}'
    d = LLMSupervisor(url=server, model="m").decide(obs())
    assert d.action == "uv_bigger_margin" and d.new_params["margin_px"] == 12 and d.decided_by == "llm:m"


def test_invalid_or_unsafe_answers_fall_back_to_rules(server):
    ANSWER["content"] = '{"action": "retopo_decimate"}'           # wrong stage
    assert LLMSupervisor(url=server, model="m").decide(obs()).decided_by == "rules"
    ANSWER["content"] = '{"action": "accept"}'                    # accepting a blocking error
    d = LLMSupervisor(url=server, model="m").decide(obs())
    assert d.action != "accept" and d.decided_by == "rules"


def test_offline_server_falls_back():
    d = LLMSupervisor(url="http://127.0.0.1:9/v1", model="m", timeout=1).decide(obs())
    assert d.decided_by == "rules" and "AI offline" in d.reason
