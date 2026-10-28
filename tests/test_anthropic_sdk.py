"""Runs AnthropicLLM through the real Anthropic SDK against a local mock of the Messages API.

This checks that the SDK accepts our request options and that our parsing handles a real
response object, without network access or an API key.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anthropic
import pytest

from joop.agent.llm import AnthropicLLM


class _MockApi:
    def __init__(self, reject_structured: bool = False):
        self.reject_structured = reject_structured
        self.requests: list[dict] = []
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output quiet
                pass

            def do_POST(self):  # noqa: N802 - http.server API
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                mock.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                fmt = (body.get("output_config") or {}).get("format")
                if mock.reject_structured and fmt:
                    self._send(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "format not supported"}})
                    return
                text = json.dumps({"reply": "Здравствуйте! Есть время завтра в 10:00.", "booking": None, "handoff": None}, ensure_ascii=False)
                self._send(200, {
                    "id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
                    "content": [{"type": "text", "text": text}],
                    "stop_reason": "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                })

            def _send(self, status, payload):
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def mock_api():
    api = _MockApi()
    yield api
    api.close()


def test_request_through_sdk(mock_api):
    client = anthropic.Anthropic(api_key="test-key", base_url=mock_api.url, max_retries=0)
    llm = AnthropicLLM(api_key="unused", model="claude-haiku-5-5", thinking="disabled", effort="low", client=client)
    reply = llm.respond("Ты администратор.", [{"role": "user", "content": "Можно завтра?"}])
    assert reply.reply.startswith("Здравствуйте")
    req = mock_api.requests[0]
    assert req["path"] == "/v1/messages"
    assert req["headers"]["authorization"] == "Bearer test-key"  # SDK 2.x sends the key as a bearer token
    body = req["body"]
    assert body["model"] == "claude-haiku-5-5"
    assert body["system"] == "Ты администратор."
    assert body["thinking"] == {"type": "disabled"}
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["required"] == ["reply", "booking", "handoff"]


def test_sdk_bad_request_falls_back():
    api = _MockApi(reject_structured=True)
    try:
        client = anthropic.Anthropic(api_key="test-key", base_url=api.url, max_retries=0)
        llm = AnthropicLLM(api_key="unused", model="claude-haiku-5-5", client=client)
        assert llm.respond("s", [{"role": "user", "content": "x"}]).reply.startswith("Здравствуйте")
        assert len(api.requests) == 2
        assert "format" not in (api.requests[1]["body"].get("output_config") or {})
    finally:
        api.close()
