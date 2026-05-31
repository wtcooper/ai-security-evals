#!/usr/bin/env python3
"""Tiny stdlib mock server for offline, keyless smoke tests.

Routes (POST, JSON body):
  /target  -> an app under test. Default: always refuses (returns a refusal in a
              200 OpenAI-shaped body). Query/header knobs let a test force other
              behaviors:
                X-Mock-Mode: refuse | comply | block400 | error500
  /judge   -> an llm-rubric grader. Returns a JSON verdict {pass,score,reason}.
              X-Mock-Verdict: pass | fail  (default pass)
  /guardrail -> a direct guardrail/classifier. Returns {"action": "...", ...}.
              Blocks when the candidate text contains any word in $MOCK_BLOCK_WORDS
              (default: "bomb,malware,exploit"); otherwise allows.

Run: python mock_server.py [port]   (default 8723)
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BLOCK_WORDS = [w for w in os.environ.get("MOCK_BLOCK_WORDS", "bomb,malware,exploit").split(",") if w]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _read(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _last_user(self, payload):
        msgs = payload.get("messages") or []
        for m in reversed(msgs):
            if m.get("role") == "user":
                return m.get("content", "")
        return payload.get("input") or payload.get("prompt") or ""

    def do_POST(self):
        payload = self._read()
        path = self.path.split("?")[0]
        if path == "/target":
            return self._target(payload)
        if path == "/judge":
            return self._judge(payload)
        if path == "/guardrail":
            return self._guardrail(payload)
        if path == "/echo":
            # echo the received body back (for verifying shim param injection)
            return self._send(200, {"received": payload})
        self._send(404, {"error": "no route"})

    def _target(self, payload):
        mode = self.headers.get("X-Mock-Mode", "auto")
        if mode == "block400":
            return self._send(400, {"error": {"message": "blocked by policy"}})
        if mode == "error500":
            return self._send(500, {"error": {"message": "upstream boom"}})
        if mode == "refuse":
            refused = True
        elif mode == "comply":
            refused = False
        else:
            # auto: simulate a gateway that applies a guardrail ONLY when a
            # guardrails param is present (control ON). Unguarded (baseline) complies
            # with everything -> high ASR; guarded blocks block-word content -> low ASR.
            text = (self._last_user(payload) or "").lower()
            guarded = bool(payload.get("guardrails"))
            refused = guarded and any(w.lower() in text for w in BLOCK_WORDS)
        out = ("I'm sorry, but I can't help with that request." if refused
               else "Sure, here you go: ...")
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": out}}]})

    def _judge(self, payload):
        verdict = self.headers.get("X-Mock-Verdict", "pass")
        passed = verdict != "fail"
        result = {"pass": passed, "score": 1.0 if passed else 0.0,
                  "reason": "mock verdict"}
        # llm-rubric reads the model's text output and parses JSON from it
        self._send(200, {"choices": [{"message": {"content": json.dumps(result)}}]})

    def _guardrail(self, payload):
        text = (self._last_user(payload) or json.dumps(payload)).lower()
        blocked = any(w.lower() in text for w in BLOCK_WORDS)
        self._send(200, {"action": "block" if blocked else "allow",
                         "category": "malicious" if blocked else "benign"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8723
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock server on http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
