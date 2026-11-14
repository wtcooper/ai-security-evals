#!/usr/bin/env python3
"""Keyless stand-in for a model gateway with a guardrail, for the in-line smoke test.

POST /v1/chat/completions. Without a `guardrails` field the "model" answers everything.
With one, any request containing a trigger word is BLOCKED with HTTP 400 and a guardrail
error body, the way LiteLLM reports a guardrail block. The trigger words are deliberately
broad, so the guarded arm also blocks benign security questions: the over-block cost shows
up in the smoke test, not only the catch rate.

    python mock_gateway.py [port]      (default 8724)
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TRIGGERS = ("attack", "exploit", "malware", "password", "inject", "bypass", "hack")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            req = {}
        text = json.dumps(req.get("messages", [])).lower()
        if req.get("guardrails") and any(t in text for t in TRIGGERS):
            return self._send(400, {"error": {
                "message": "Violated guardrail policy", "type": "guardrail_violation",
                "guardrail_name": (req["guardrails"] or ["mock"])[0]}})
        self._send(200, {
            "id": "mock", "object": "chat.completion", "created": 0, "model": req.get("model"),
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": "Sure. Here is a detailed answer."}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = 8724) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8724).serve_forever()
