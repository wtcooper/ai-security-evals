#!/usr/bin/env python3
"""Mock OpenAI-compatible chat-completions endpoint (stdlib only) for adapter plumbing tests.

It never judges anything: it replays one canned assistant message for every request, as a
streaming (SSE) or plain JSON response depending on the request's `stream` flag. Use it to
check that an adapter invokes its scanner, that the scanner writes its report and that the
report converts, without a real model or key. It says nothing about detection quality.

  python3 mock_openai_server.py --reply-file reply.txt [--port 0]
Prints `PORT=<n>` on stdout once listening.
"""
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(reply: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep test output quiet
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                req = {}
            model = req.get("model", "mock")
            usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
            if req.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chunks = [
                    {"id": "mock", "object": "chat.completion.chunk", "model": model,
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply}, "finish_reason": None}]},
                    {"id": "mock", "object": "chat.completion.chunk", "model": model,
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                    {"id": "mock", "object": "chat.completion.chunk", "model": model, "choices": [], "usage": usage},
                ]
                for c in chunks:
                    self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
                return
            out = json.dumps({"id": "mock", "object": "chat.completion", "model": model, "usage": usage,
                              "choices": [{"index": 0, "finish_reason": "stop",
                                           "message": {"role": "assistant", "content": reply}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reply-file", required=True)
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args()
    with open(a.reply_file, encoding="utf-8") as fh:
        reply = fh.read()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(reply))
    print(f"PORT={srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
