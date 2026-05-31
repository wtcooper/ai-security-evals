#!/usr/bin/env python3
"""Param-injection shim — the one piece of custom code control-bench needs.

A standard OpenAI client (inside AgentDojo, CyberSecEval, any inspect_evals task)
won't send a `guardrails` param, and Inspect has no per-request body hook. This tiny
reverse proxy injects the arm's guardrail (and optionally pins the model) into every
request, then forwards to the real gateway — so the benchmark stays 100% unmodified
and only its model base URL changes. Inspect then runs the A/B/C sweep and scores it
natively (multiple `openai-api/<arm>/<model>` providers in one `inspect eval`).

Two modes:

  Single arm (one port):
    SHIM_CONNECTOR=litellm SHIM_GATEWAY_URL=http://localhost:4000 \
    SHIM_GATEWAY_KEY=$KEY SHIM_ARM='{"name":"prisma","guardrails":["prisma-airs-pi"]}' \
    python injection_shim.py 8900

  Launch one shim per arm and print the Inspect --model string + env to export:
    SHIM_GATEWAY_URL=http://localhost:4000 SHIM_GATEWAY_KEY=$KEY \
    python injection_shim.py --arms arms.json --base-port 8901

Block handling: many guardrails block with a non-2xx (e.g. litellm raises HTTP 400).
A hard error aborts an Inspect run instead of scoring it, so by default the shim
converts a block status (GUARDRAIL_BLOCK_STATUSES, default 400) into a 200 refusal
completion — the benchmark then scores the arm as a refusal (failed attack), keeping
native scores comparable across arms. Disable with SHIM_BLOCK_AS_REFUSAL=false.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from connectors.base import Arm, Connector  # noqa: E402

HOP_BY_HOP = {"content-length", "host", "connection", "keep-alive", "transfer-encoding"}


def arm_from_dict(d: dict) -> Arm:
    return Arm(name=d.get("name", "arm"), model=d.get("model", "") or "",
               guardrails=tuple(d.get("guardrails", ()) or ()), extra=d.get("extra", {}) or {})


def arm_from_json(s: str) -> Arm:
    return arm_from_dict(json.loads(s))


def block_statuses() -> set[int]:
    raw = os.environ.get("GUARDRAIL_BLOCK_STATUSES", "400")
    return {int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit()}


def build_forward(path, in_headers, body_bytes, connector: Connector, arm: Arm,
                  gateway_url: str, gateway_key: str | None):
    """Pure: produce the (url, headers, body, model) to forward, with arm params
    injected. `model` is the post-injection model (for the block-refusal echo), so
    the caller doesn't re-parse the body."""
    try:
        body = json.loads(body_bytes or b"{}")
    except json.JSONDecodeError:
        body = {}
    body = connector.inject(body, arm)
    out_body = json.dumps(body).encode()
    headers = {k: v for k, v in in_headers.items() if k.lower() not in HOP_BY_HOP}
    headers["Content-Type"] = "application/json"
    if gateway_key:
        headers["Authorization"] = f"Bearer {gateway_key}"
    return gateway_url.rstrip("/") + path, headers, out_body, body.get("model") or arm.model


def block_to_refusal(data: bytes, code: int, model: str, statuses: set[int]):
    """If `code` is a guardrail block, return (200, refusal-completion-bytes) so the
    benchmark scores it as a refusal instead of erroring. Else return (code, data)."""
    if code not in statuses:
        return code, data
    reason = ""
    try:
        err = json.loads(data or b"{}")
    except json.JSONDecodeError:
        err = {}
    if isinstance(err, dict):
        e = err.get("error")
        if isinstance(e, dict):          # {"error": {"message": "..."}}
            reason = e.get("message") or ""
        elif isinstance(e, str):         # {"error": "..."}
            reason = e
        else:
            reason = err.get("message") or err.get("detail") or ""
    completion = {
        "id": "shim-guardrail-block", "object": "chat.completion", "model": model or "guarded",
        "choices": [{"index": 0, "finish_reason": "content_filter",
                     "message": {"role": "assistant",
                                 "content": f"I'm sorry, but I can't help with that. [GUARDRAIL_BLOCK] {reason}".strip()}}],
    }
    return 200, json.dumps(completion).encode()


def make_handler(connector, arm, gateway_url, gateway_key, block_as_refusal):
    class Shim(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(n) if n else b"{}"
            url, headers, out_body, model = build_forward(self.path, dict(self.headers), body_bytes,
                                                          connector, arm, gateway_url, gateway_key)
            req = urllib.request.Request(url, data=out_body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data, code = resp.read(), resp.getcode()
            except urllib.error.HTTPError as e:
                data, code = e.read(), e.code
            except Exception as e:  # noqa: BLE001
                data = json.dumps({"error": {"message": f"shim forward failed: {e}"}}).encode()
                code = 502
            if block_as_refusal:
                code, data = block_to_refusal(data, code, model, block_statuses())
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Shim


def _serve(handler, port, daemon=False):
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    if daemon:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _block_as_refusal_enabled():
    return os.environ.get("SHIM_BLOCK_AS_REFUSAL", "true").lower() not in ("false", "0", "no")


def launch_arms(arms, connector, gateway_url, gateway_key, base_port):
    """Start one shim per arm on consecutive ports; print the Inspect --model string
    + env exports. Inspect runs the A/B/C sweep across these providers natively."""
    bar = _block_as_refusal_enabled()
    models, env = [], []
    for i, arm in enumerate(arms):
        port = base_port + i
        _serve(make_handler(connector, arm, gateway_url, gateway_key, bar), port, daemon=True)
        name = arm.name.upper().replace("-", "_")
        env.append(f"export {name}_BASE_URL=http://127.0.0.1:{port}/v1 {name}_API_KEY=shim")
        models.append(f"openai-api/{arm.name}/$MODEL")
    lines = [
        "# control-bench shims running. Export these, then run any inspect_evals task:",
        *env,
        "export MODEL=<your-model-name>   # same model on every arm",
        f'inspect eval inspect_evals/agentdojo --model "{",".join(models)}"',
        "# (swap agentdojo for any inspect_evals task; compare arms in `inspect view`)",
    ]
    print("\n".join(lines), flush=True)
    return [base_port + i for i in range(len(arms))]


def main():
    connector = Connector.from_id(os.environ.get("SHIM_CONNECTOR", "litellm"))
    gateway_url = os.environ["SHIM_GATEWAY_URL"]
    gateway_key = os.environ.get("SHIM_GATEWAY_KEY")

    if "--arms" in sys.argv:
        arms_path = sys.argv[sys.argv.index("--arms") + 1]
        base_port = int(sys.argv[sys.argv.index("--base-port") + 1]) if "--base-port" in sys.argv else 8901
        arms = [arm_from_dict(d) for d in json.loads(open(arms_path).read())]
        launch_arms(arms, connector, gateway_url, gateway_key, base_port)
        threading.Event().wait()  # keep the shims alive
        return

    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8900
    arm = arm_from_json(os.environ.get("SHIM_ARM", '{"name":"baseline","model":""}'))
    srv = _serve(make_handler(connector, arm, gateway_url, gateway_key, _block_as_refusal_enabled()), port)
    print(f"shim[{arm.name}] :{port} -> {gateway_url} (connector={connector.id}, "
          f"guardrails={list(arm.guardrails)}, block_as_refusal={_block_as_refusal_enabled()})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
