#!/usr/bin/env python3
"""Mock decision-model server for the keyless smoke test and the unit tests. Stdlib only.

    python mock_server.py --port 8765

It speaks the three wire formats on these paths:

    systemone   POST /v1/systemone
                POST /providers/microsoft/v1/systemone
                POST /api/alpha/decisions
    openai      POST /v1/decisions
    gemini      POST /v1beta/decisions

Behind them is a toy "model": bag-of-words overlap between the state and each option's
text, plus three deliberate weaknesses so that a keyless run produces numbers that are not
all zero. It is NOT a decision model and its numbers say nothing about any real one.

  position bias   the first option gets a bonus (the gemini path sorts option keys first,
                  as the real API documents, so option order has no effect there)
  injection       a quoted option label, or `result=<label>`, inside the state pulls the
                  answer toward that label; text delivered as a tool output pulls less
  label appeal    a label that sounds reassuring ("compliant", "safe", "contained") gets a bonus

Model ids: `mock-decision-a` (strong weaknesses), `mock-decision-b` (weaker ones, and it
refuses base64-wrapped input). `mock-latest` is an alias for `mock-decision-a`; the
systemone and openai paths echo the resolved id, the gemini path echoes nothing.

Triggers inside the state, for tests: `[[mock:refuse]]`, `[[mock:http500]]`,
`[[mock:malformed]]`.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PATHS = {
    "/v1/systemone": "systemone",
    "/providers/microsoft/v1/systemone": "systemone",
    "/api/alpha/decisions": "systemone",
    "/v1/decisions": "openai",
    "/v1beta/decisions": "gemini",
}
MODELS = {
    "mock-decision-a": {"alpha": 16.0, "position": 0.9, "inject": 3.5, "appeal": 2.2,
                        "tool_factor": 0.5, "refuse_base64": False},
    "mock-decision-b": {"alpha": 16.0, "position": 0.25, "inject": 0.6, "appeal": 0.7,
                        "tool_factor": 0.2, "refuse_base64": True},
}
ALIASES = {"mock-latest": "mock-decision-a"}
STOPWORDS = frozenset("""a an and any are as at be been but by can count counts do does for from
has have holds how if in into is it its may no not of on one only or other part some such than
that the their them then there these this to was what when where which while who will with
without yes""".split())
APPEAL_STEMS = ("safe", "compl", "verif", "conta", "recom", "trust")
AUTH_HEADERS = {"systemone": ("authorization", "api-key"), "openai": ("authorization",),
                "gemini": ("x-goog-api-key",)}


def stems(text: str) -> set[str]:
    """Lower-case ASCII word stems (first five letters). Non-ASCII look-alikes and
    zero-width characters break words apart, which is what makes the toy model sensitive
    to the encoding axis."""
    return {w[:5] for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) >= 3 and w not in STOPWORDS}


def overlap(state: set[str], option: set[str]) -> float:
    if not state or not option:
        return 0.0
    return len(state & option) / math.sqrt(len(state) * len(option))


def injected(text: str, label: str) -> int:
    low, lab = text.lower(), label.lower()
    return low.count(f'"{lab}"') + low.count(f"result={lab}")


def appeal(label: str) -> int:
    parts = re.findall(r"[a-z0-9]+", label.lower())
    return int(any(p.startswith(APPEAL_STEMS) for p in parts))


def softmax(logits: list[float]) -> list[float]:
    top = max(logits)
    exps = [math.exp(x - top) for x in logits]
    total = sum(exps)
    return [e / total for e in exps]


class ToyModel:
    def __init__(self, jitter: float = 0.0, jitter_seed: int = 0):
        self.jitter = jitter
        self._rng = random.Random(jitter_seed)
        self._lock = threading.Lock()

    def _noise(self) -> float:
        if not self.jitter:
            return 0.0
        with self._lock:
            return self._rng.gauss(0.0, self.jitter)

    def distribution(self, params: dict, main_text: str, tool_text: str, instructions: str,
                     options: list[tuple[str, str]], positional: bool) -> list[float]:
        """Probability per option. options: [(label, criteria text)] in evaluation order."""
        state = stems(main_text + " " + tool_text)
        logits = []
        for pos, (label, criteria) in enumerate(options):
            logit = params["alpha"] * overlap(state, stems(label.replace("_", " ") + " " + criteria))
            if positional and pos == 0:
                logit += params["position"]
            logit += params["appeal"] * appeal(label)
            logit += params["inject"] * (injected(main_text, label)
                                         + params["tool_factor"] * injected(tool_text, label))
            logits.append(logit + self._noise())
        return softmax(logits)


def flatten(value) -> str:
    """JSON as plain text: keys and values in order, strings not escaped. A real model
    reads the content of a string, not its JSON escaping."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(f"{k}: {flatten(v)}" for k, v in value.items())
    if isinstance(value, list):
        return "\n".join(flatten(v) for v in value)
    return json.dumps(value)


def _maybe_json(text: str) -> str:
    """The gemini path receives objects serialised to a string; read them as objects."""
    if text[:1] in "{[":
        try:
            return flatten(json.loads(text))
        except ValueError:
            pass
    return text


def _parts_text(content) -> str:
    """Text of an OpenAI-style content value: a string or a list of typed parts."""
    if isinstance(content, str):
        return content
    out = []
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        if "text" in part:
            out.append(str(part["text"]))
        elif part.get("type") == "input_json":
            out.append(flatten(part.get("data")))
    return "\n".join(out)


def read_input(fmt: str, body: dict) -> tuple[str, str]:
    """(main text, text that arrived as tool output)."""
    if fmt == "systemone":
        return flatten(body.get("state")), ""
    value = body.get("input")
    if isinstance(value, str):
        return _maybe_json(value), ""
    main, tool = [], []
    for item in value if isinstance(value, list) else [value]:
        if not isinstance(item, dict):
            continue
        if item.get("type") in ("function_call_output", "custom_tool_call_output"):
            tool.append(_parts_text(item.get("output")))
        elif item.get("type") in ("function_call", "custom_tool_call"):
            main.append(str(item.get("arguments") or item.get("input") or ""))
        elif "content" in item:
            main.append(_parts_text(item["content"]))
        elif "text" in item:                       # gemini text block
            main.append(str(item["text"]))
    return "\n".join(main), "\n".join(tool)


def read_questions(fmt: str, body: dict) -> list[dict]:
    """Questions as [{name, type, instructions, options: [(label, criteria)]}]."""
    out = []
    raw = body.get("questions")
    if fmt == "openai":
        for i, q in enumerate(raw if isinstance(raw, list) else []):
            kind = q.get("type")
            ins = _parts_text(q.get("instructions"))
            if kind == "predicate":
                yes = re.search(r"^Answer true when: (.*)$", ins, re.M)
                no = re.search(r"^Answer false when: (.*)$", ins, re.M)
                opts = [("yes", yes.group(1) if yes else ins), ("no", no.group(1) if no else "")]
            elif kind == "choice":
                opts = [(str(c.get("value")), c.get("description") or "")
                        for c in q.get("choices", [])]
            elif kind == "score":
                opts = [(l.get("label", ""), l.get("description") or "")
                        for l in q.get("levels", [])]
            else:
                raise ValueError(f"unknown question type {kind!r}")
            out.append({"name": q.get("name"), "index": i, "type": kind, "instructions": ins,
                        "options": opts})
        return out
    keys = ("true", "false") if fmt == "systemone" else ("true_description", "false_description")
    for name, q in (raw if isinstance(raw, dict) else {}).items():
        kind, crit = q.get("type"), q.get("criteria")
        ins = q.get("instructions") if isinstance(q.get("instructions"), str) else json.dumps(
            q.get("instructions"))
        if kind == "noul":
            crit = crit or {}
            opts = [("yes", crit.get(keys[0]) or ins), ("no", crit.get(keys[1]) or "")]
        elif kind == "choice":
            if not isinstance(crit, dict) or not crit:
                raise ValueError("choice needs a criteria object")
            items = sorted(crit.items()) if fmt == "gemini" else list(crit.items())
            opts = [(k, v or "") for k, v in items]
        elif kind == "score":
            if not isinstance(crit, list) or not crit:
                raise ValueError("score needs a criteria array")
            # Level text is "<name>: <description>" when it comes from adapter.py.
            opts = [tuple(str(level).split(": ", 1)) if ": " in str(level)
                    else (str(i), str(level)) for i, level in enumerate(crit)]
        else:
            raise ValueError(f"unknown question type {kind!r}")
        out.append({"name": name, "type": kind, "instructions": ins, "options": opts})
    return out


def answer(fmt: str, q: dict, probs: list[float]) -> dict:
    labels = [label for label, _ in q["options"]]
    rounded = [round(p, 4) for p in probs]
    top = max(range(len(labels)), key=lambda i: rounded[i])
    kind = q["type"]
    if kind in ("noul", "predicate"):
        p_yes = rounded[0]
        if fmt == "openai":
            return {"type": "predicate", "name": q["name"], "probability": p_yes}
        if fmt == "gemini":
            p_yes = min(0.99, max(0.01, p_yes))
            return {"type": "noul", "noul": p_yes, "confidence": max(p_yes, 1 - p_yes)}
        return {"type": "noul", "noul": p_yes}
    if kind == "choice":
        if fmt == "openai":
            return {"type": "choice", "name": q["name"], "choice": labels[top],
                    "probabilities": [{"value": l, "probability": p}
                                      for l, p in zip(labels, rounded)],
                    "confidence": rounded[top]}
        return {"type": "choice", "choice": labels[top], "confidence": rounded[top],
                "probabilities": dict(zip(labels, rounded))}
    score = round(sum(i * p for i, p in enumerate(rounded)), 4)
    if fmt == "openai":
        return {"type": "score", "name": q["name"], "score": score, "confidence": rounded[top],
                "probabilities": [{"value": i, "label": l, "probability": p}
                                  for i, (l, p) in enumerate(zip(labels, rounded))]}
    return {"type": "score", "score": score, "confidence": rounded[top],
            "legend": {str(i): crit for i, (_, crit) in enumerate(q["options"])},
            "probabilities": {str(i): p for i, p in enumerate(rounded)}}


def respond(fmt: str, body: dict, toy: ToyModel) -> tuple[int, dict]:
    """(HTTP status, response body) for one request."""
    requested = body.get("model")
    resolved = ALIASES.get(requested, requested)
    if resolved not in MODELS:
        return 422, {"detail": [{"loc": ["body", "model"], "msg": f"unknown model {requested!r}",
                                 "type": "value_error"}]}
    params = MODELS[resolved]
    try:
        main_text, tool_text = read_input(fmt, body)
        questions = read_questions(fmt, body)
    except (ValueError, AttributeError, TypeError) as exc:
        return 400, {"detail": str(exc)} if fmt == "systemone" else {
            "error": {"code": "invalid_request", "message": str(exc)}}
    if not questions:
        return 400, {"detail": "questions is required"} if fmt == "systemone" else {
            "error": {"code": "invalid_request", "message": "questions is required"}}
    everything = main_text + "\n" + tool_text
    if "[[mock:http500]]" in everything:
        return 500, {"error": {"code": "internal", "message": "mock failure"}}
    refuse = "[[mock:refuse]]" in everything or (
        params["refuse_base64"] and "base64-encoded:" in everything)
    if refuse and fmt == "gemini":
        return 400, {"error": {"code": "safety", "message": "Request blocked due to safety "
                               "violations (mock). Please modify your input and retry."}}
    answers = []
    for q in questions:
        if refuse:
            ans = {"type": "refusal", "name": q["name"]} if fmt == "openai" else {"type": "refusal"}
        else:
            probs = toy.distribution(params, main_text, tool_text, q["instructions"],
                                     q["options"], positional=q["type"] == "choice")
            ans = answer(fmt, q, probs)
        answers.append((q["name"], ans))
    tokens = math.ceil(len(json.dumps(body, ensure_ascii=False)) / 4)
    if "[[mock:malformed]]" in everything:
        return 200, {"model": resolved, "usage": {"input_tokens": tokens}}
    if fmt == "openai":
        return 200, {"model": resolved, "answers": [a for _, a in answers],
                     "usage": {"input_tokens": tokens,
                               "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                               "output_tokens": 0, "output_tokens_details": {"reasoning_tokens": 0},
                               "total_tokens": tokens}}
    if fmt == "gemini":
        return 200, {"answers": dict(answers),
                     "usage": {"total_input_tokens": tokens,
                               "input_tokens_by_modality": [{"modality": "text", "tokens": tokens}],
                               "total_output_tokens": 0, "total_tokens": tokens}}
    return 200, {"model": resolved, "answers": dict(answers),
                 "usage": {"input_tokens": tokens, "output_tokens": 0}}


class MockServer(ThreadingHTTPServer):
    """`requests` keeps (path, headers, body) of every request for the tests to inspect."""
    daemon_threads = True

    def __init__(self, port: int = 0, jitter: float = 0.0, jitter_seed: int = 0,
                 require_auth: bool = False, fail_first: int = 0, fail_status: int = 503):
        super().__init__(("127.0.0.1", port), _Handler)
        self.toy = ToyModel(jitter, jitter_seed)
        self.require_auth = require_auth
        self.fail_first = fail_first
        self.fail_status = fail_status
        self.requests: list[dict] = []
        self.lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def url(self, fmt: str) -> str:
        return self.base_url + {"systemone": "/v1/systemone", "openai": "/v1/decisions",
                                "gemini": "/v1beta/decisions"}[fmt]

    def start(self) -> "MockServer":
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.02},
                         daemon=True).start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


class _Handler(BaseHTTPRequestHandler):
    server: MockServer

    def log_message(self, *args) -> None:  # keep test and smoke output quiet
        return

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        fmt = PATHS.get(self.path.split("?")[0])
        headers = {k.lower(): v for k, v in self.headers.items()}
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = None
        with self.server.lock:
            self.server.requests.append({"path": self.path, "headers": headers, "body": body})
            failing = self.server.fail_first > 0
            if failing:
                self.server.fail_first -= 1
        if fmt is None:
            return self._send(404, {"error": {"code": "not_found", "message": self.path}})
        if failing:
            return self._send(self.server.fail_status,
                              {"error": {"code": "unavailable", "message": "mock overload"}})
        if self.server.require_auth and not any(headers.get(h) for h in AUTH_HEADERS[fmt]):
            return self._send(401, {"error": {"code": "unauthorized",
                                              "message": "missing credential header"}})
        if not isinstance(body, dict):
            return self._send(400, {"error": {"code": "invalid_json", "message": "bad JSON"}})
        self._send(*respond(fmt, body, self.server.toy))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mock decision-model server (three wire formats).")
    p.add_argument("--port", type=int, default=8765, help="0 picks a free port")
    p.add_argument("--jitter", type=float, default=0.0,
                   help="standard deviation of random noise added to each logit; 0 (default) "
                        "makes identical requests return identical answers")
    p.add_argument("--jitter-seed", type=int, default=0)
    p.add_argument("--require-auth", action="store_true",
                   help="answer 401 unless the format's credential header is present")
    args = p.parse_args(argv)
    server = MockServer(args.port, args.jitter, args.jitter_seed, args.require_auth)
    print(f"mock decision server on {server.base_url}", flush=True)
    for path, fmt in PATHS.items():
        print(f"  {fmt:<10} POST {server.base_url}{path}", flush=True)
    print(f"  models     {', '.join(MODELS)} (alias: mock-latest)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
