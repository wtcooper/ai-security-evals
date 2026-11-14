#!/usr/bin/env python3
"""Vendor-neutral adapter for decision models. Stdlib only (urllib); no vendor SDK.

One canonical case goes in, one canonical result comes out, whatever the wire format.

Canonical case
    {"state": <str | dict | list>,
     "untrusted_field": "<dotted path into state>" (optional),
     "questions": {<name>: {"type": "noul" | "choice" | "score",
                            "instructions": "<text>",
                            "options": [{"label": "<id>", "criteria": "<text>"}, ...]}}}

    noul    two options labelled exactly "yes" and "no"; criteria optional.
    choice  two or more options; the order given is the order sent.
    score   two or more options ordered lowest to highest; the label names the level.

Canonical result (one per question)
    outcome       "answered" | "refusal" | "error"   (refusals and errors are never a label)
    label         argmax of the returned distribution, computed here, not read from the vendor
    probs         {label: probability} exactly as returned (not renormalised)
    top_p/margin  our own confidence: top probability, and top minus runner-up
    refusal, latency_ms, input_tokens, model_echo, http_status, error

Vendor `confidence` fields are recorded as `vendor_confidence` and used for nothing: they are
defined differently by each vendor (see references/wire-formats.md).

Three wire formats:
    systemone  `state` + `questions` map        TypeSafe, Microsoft, Clef, OpenRouter, local
    openai     `input` + `questions` array      OpenAI Decisions API (yes/no is `predicate`)
    gemini     `input` + `questions` map        Gemini Decisions API (yes/no is `noul`)
"""
from __future__ import annotations

import copy
import json
import math
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

NOUL_LABELS = ("yes", "no")
QUESTION_TYPES = ("noul", "choice", "score")
OUTCOMES = ("answered", "refusal", "error")
RETRY_STATUS = (429, 500, 502, 503, 504)
# Gemini returns HTTP 400 with one of these codes when an input filter blocks a request.
GEMINI_BLOCK_CODES = ("safety", "prohibited_content", "blocklist", "image_safety",
                      "content_blocked")

# `verified` means: the request AND response JSON were read in a primary source (vendor
# documentation or OpenAPI file) on 2026-11-14. It does not mean a live call was made;
# no live service was called while building this skill. `not_confirmed` lists what was not
# seen in a primary source.
WIRE_FORMATS = {
    "systemone": {
        "verified": True,
        "source": "https://docs.typesafe.ai/api/system-one.md (OpenAPI 0.2.0, operation "
                  "systemone_v1_systemone_post)",
        "not_confirmed": [
            "A per-question refusal answer ({\"type\": \"refusal\"}) is documented by OpenRouter "
            "for this format, not by TypeSafe; the parser accepts it from any server.",
        ],
    },
    "openai": {
        "verified": True,
        "source": "https://developers.openai.com/api/docs/guides/decisions and "
                  "https://developers.openai.com/api/reference/resources/decisions/methods/create",
        "not_confirmed": [
            "The error body is not described on either page; the parser reads "
            "error.message / error.code when present and keeps the raw text otherwise.",
        ],
    },
    "gemini": {
        "verified": True,
        "source": "https://aistudio.google.com/docs/decisions-api (REST examples and the "
                  "request and response reference table)",
        "not_confirmed": [
            "The response carries no model field in any documented example, so the server "
            "cannot confirm which model answered; model_echo is null for this format.",
            "Only the safety-block error body is documented; other 400 bodies are kept as text.",
        ],
    },
}

# Named endpoints. `url` may hold {resource}, which the arm must supply as a full URL.
PROVIDERS = {
    "typesafe": {
        "format": "systemone", "url": "https://api.typesafe.ai/v1/systemone", "auth": "bearer",
        "verified": True, "not_confirmed": []},
    "microsoft": {
        "format": "systemone", "url": None, "auth": "bearer",
        "url_hint": "<foundry-resource-endpoint>/providers/microsoft/v1/systemone",
        "verified": False,
        "not_confirmed": [
            "The Microsoft Learn page shows request JSON and the path, but no raw response "
            "JSON. Its sample code reads answers[name].type and answers[name].choice; the "
            "field names probabilities, noul, score and usage.input_tokens are assumed to "
            "match System One because the page calls the pattern 'similar to a system-one API'.",
            "Auth is 'Authorization: Bearer <Entra token>' or 'api-key: <key>' (use auth=api-key).",
            "The request `model` is the deployment name; the response `model` is documented "
            "to name the underlying model.",
        ]},
    "openrouter": {
        "format": "systemone", "url": "https://openrouter.ai/api/alpha/decisions",
        "auth": "bearer", "verified": True,
        "not_confirmed": ["The error body is not described; non-200 bodies are kept as text.",
                          "The path is under /api/alpha and may change."]},
    "clef": {
        "format": "systemone", "url": None, "auth": "bearer",
        "url_hint": "the Workers AI or self-hosted URL of your Clef deployment",
        "verified": False,
        "not_confirmed": ["Clef's request and response JSON were not read in a primary "
                          "source. It is described as compatible with the System One format; "
                          "run the smoke depth against it and read the errors before "
                          "trusting it."]},
    "local": {
        "format": "systemone", "url": None, "auth": "none",
        "url_hint": "http://<host>:<port>/v1/systemone",
        "verified": False,
        "not_confirmed": ["Any self-hosted server: compatibility is whatever that server "
                          "implements."]},
    "openai": {
        "format": "openai", "url": "https://api.openai.com/v1/decisions", "auth": "bearer",
        "verified": True, "not_confirmed": []},
    "azure-openai": {
        "format": "openai", "url": None, "auth": "api-key",
        "url_hint": "the Decisions URL of your Azure OpenAI resource",
        "verified": False,
        "not_confirmed": ["The Azure OpenAI Decisions path, api-version parameter and auth "
                          "header were not read in a primary source."]},
    "gemini": {
        "format": "gemini", "url": "https://generativelanguage.googleapis.com/v1beta/decisions",
        "auth": "x-goog-api-key", "verified": True, "not_confirmed": []},
    "mock": {
        "format": "systemone", "url": None, "auth": "none", "verified": True,
        "url_hint": "http://127.0.0.1:<port>/v1/systemone (mock_server.py)",
        "not_confirmed": []},
}

ALIAS_HINTS = ("latest", "preview", "default", "stable")


class CaseError(ValueError):
    """The canonical case or question is malformed."""


# --------------------------------------------------------------------------------------
# Canonical case helpers
# --------------------------------------------------------------------------------------

def validate_question(q: dict) -> None:
    if q.get("type") not in QUESTION_TYPES:
        raise CaseError(f"question type must be one of {QUESTION_TYPES}, got {q.get('type')!r}")
    if not isinstance(q.get("instructions"), str) or not q["instructions"].strip():
        raise CaseError("question needs non-empty instructions")
    opts = q.get("options")
    if not isinstance(opts, list) or len(opts) < 2:
        raise CaseError("question needs at least two options")
    labels = [o.get("label") for o in opts]
    if any(not isinstance(l, str) or not l for l in labels) or len(set(labels)) != len(labels):
        raise CaseError(f"option labels must be unique non-empty strings: {labels}")
    if q["type"] == "noul" and tuple(labels) != NOUL_LABELS:
        raise CaseError('a noul question has exactly the options "yes" and "no", in that order')


def labels_of(q: dict) -> list[str]:
    return [o["label"] for o in q["options"]]


def get_path(state, dotted: str):
    """Value at a dotted path in a dict state, or None when it is not there."""
    cur = state
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def set_path(state: dict, dotted: str, value) -> dict:
    """A deep copy of `state` with the value at a dotted path replaced."""
    out = copy.deepcopy(state)
    cur = out
    parts = dotted.split(".")
    for part in parts[:-1]:
        cur = cur[part]
    cur[parts[-1]] = value
    return out


def del_path(state: dict, dotted: str) -> dict:
    out = copy.deepcopy(state)
    cur = out
    parts = dotted.split(".")
    for part in parts[:-1]:
        cur = cur[part]
    cur.pop(parts[-1], None)
    return out


def state_text(state) -> str:
    """The state as one string. Dict key order is kept; nothing is escaped to ASCII."""
    return state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)


def estimate_tokens(case: dict) -> int:
    """Rough input-token estimate (characters / 4) for the cost plan. Real tokenisers differ,
    and each vendor adds its own framing; the server-reported count is what gets recorded."""
    chars = len(state_text(case["state"]))
    for q in case["questions"].values():
        chars += len(q["instructions"]) + sum(len(o["label"]) + len(o.get("criteria") or "")
                                              for o in q["options"])
    return max(1, math.ceil(chars / 4))


# --------------------------------------------------------------------------------------
# Canonical case -> wire request
# --------------------------------------------------------------------------------------

def _level_text(option: dict) -> str:
    return f"{option['label']}: {option['criteria']}" if option.get("criteria") else option["label"]


def _map_question(q: dict, noul_keys: tuple[str, str]) -> dict:
    """System One and Gemini share the shape; only the yes/no criteria keys differ."""
    out = {"type": q["type"], "instructions": q["instructions"]}
    if q["type"] == "noul":
        crit = {key: o["criteria"] for key, o in zip(noul_keys, q["options"]) if o.get("criteria")}
        if crit:
            out["criteria"] = crit
    elif q["type"] == "choice":
        out["criteria"] = {o["label"]: o.get("criteria") or "" for o in q["options"]}
    else:
        out["criteria"] = [_level_text(o) for o in q["options"]]
    return out


def to_systemone(case: dict, model: str) -> dict:
    """Format A. `state` is sent as given (string, object or array)."""
    return {"model": model, "state": case["state"],
            "questions": {name: _map_question(q, ("true", "false"))
                          for name, q in case["questions"].items()}}


def to_gemini(case: dict, model: str) -> dict:
    """Format C. Google's guide says to serialise JSON to a string and pass it as text.
    The API sorts choice option keys alphabetically before evaluation, so the order sent
    here has no effect on a Gemini arm."""
    return {"model": model, "input": state_text(case["state"]),
            "questions": {name: _map_question(q, ("true_description", "false_description"))
                          for name, q in case["questions"].items()}}


def _openai_question(name: str, q: dict) -> dict:
    out = {"type": "predicate" if q["type"] == "noul" else q["type"], "name": name,
           "instructions": q["instructions"]}
    if q["type"] == "noul":
        # `predicate` has no criteria field, so the yes/no criteria go into the instructions.
        yes, no = q["options"]
        extra = [f"Answer true when: {yes['criteria']}" if yes.get("criteria") else "",
                 f"Answer false when: {no['criteria']}" if no.get("criteria") else ""]
        out["instructions"] = "\n".join([q["instructions"], *[e for e in extra if e]])
    elif q["type"] == "choice":
        out["choices"] = [{"value": o["label"], "description": o.get("criteria") or ""}
                          for o in q["options"]]
    else:
        out["levels"] = [{"label": o["label"], "description": o.get("criteria") or ""}
                         for o in q["options"]]
    return out


def to_openai(case: dict, model: str, placement: str = "user") -> dict:
    """Format B. A string state is sent as a string. An object state is sent as an
    `input_json` part of a user message.

    placement="tool_output" moves the text at `untrusted_field` out of the user message and
    into a function-call output, the position OpenAI documents for tool results. Run the same
    model as two arms (user / tool_output) to see whether the position changes the answers.
    It falls back to "user" when the state is not an object or has no such field."""
    if placement not in ("user", "tool_output"):
        raise CaseError("placement must be 'user' or 'tool_output'")
    state = case["state"]
    field = case.get("untrusted_field")
    untrusted = get_path(state, field) if (field and isinstance(state, dict)) else None
    if isinstance(state, str):
        wire_input = state
    elif placement == "tool_output" and isinstance(untrusted, str):
        wire_input = [
            {"role": "user", "content": [{"type": "input_json", "data": del_path(state, field)}]},
            {"type": "function_call", "call_id": "call_1", "name": "read_content",
             "arguments": json.dumps({"field": field})},
            {"type": "function_call_output", "call_id": "call_1", "output": untrusted},
        ]
    elif isinstance(state, dict) or (isinstance(state, list)
                                     and all(isinstance(x, dict) for x in state)):
        wire_input = [{"role": "user", "content": [{"type": "input_json", "data": state}]}]
    else:
        wire_input = state_text(state)
    return {"model": model, "input": wire_input,
            "questions": [_openai_question(n, q) for n, q in case["questions"].items()]}


def build_request(fmt: str, case: dict, model: str, placement: str = "user") -> dict:
    for q in case["questions"].values():
        validate_question(q)
    if fmt == "systemone":
        return to_systemone(case, model)
    if fmt == "openai":
        return to_openai(case, model, placement)
    if fmt == "gemini":
        return to_gemini(case, model)
    raise CaseError(f"unknown wire format {fmt!r}; expected one of {sorted(WIRE_FORMATS)}")


# --------------------------------------------------------------------------------------
# Wire response -> canonical result
# --------------------------------------------------------------------------------------

def blank_result() -> dict:
    return {"outcome": "error", "label": None, "probs": None, "top_p": None, "margin": None,
            "prob_sum": None, "tie": False, "refusal": False, "vendor_confidence": None,
            "vendor_choice": None, "error": None}


def confidence(probs: dict, order: list[str]) -> tuple[str, float, float, bool]:
    """Argmax label, top probability, margin over the runner-up, and whether the top was tied.
    A tie goes to the option that comes first in `order` (the order the options were sent)."""
    ranked = sorted(order, key=lambda l: (-probs[l], order.index(l)))
    top, second = ranked[0], ranked[1]
    return top, probs[top], probs[top] - probs[second], probs[top] == probs[second]


def _is_prob(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and 0.0 <= float(x) <= 1.0 \
        and not math.isnan(float(x))


def _finish(res: dict, probs: dict, order: list[str]) -> dict:
    missing = [l for l in order if l not in probs]
    extra = [l for l in probs if l not in order]
    if missing or extra or not all(_is_prob(v) for v in probs.values()):
        res["error"] = (f"malformed_response: probabilities do not cover the options "
                        f"(missing={missing}, unexpected={extra})")
        return res
    probs = {l: float(probs[l]) for l in order}
    label, top, margin, tie = confidence(probs, order)
    res.update({"outcome": "answered", "label": label, "probs": probs, "top_p": top,
                "margin": margin, "tie": tie, "prob_sum": sum(probs.values())})
    return res


def _parse_answer(ans, q: dict, fmt: str) -> dict:
    """One answer object -> canonical result fields. Anything that is not a well-formed
    answer of the question's own type is `refusal` (when the server says so) or `error`;
    it is never read as a label."""
    res = blank_result()
    order = labels_of(q)
    if not isinstance(ans, dict):
        res["error"] = "malformed_response: no answer for this question"
        return res
    if ans.get("type") == "refusal":
        res.update({"outcome": "refusal", "refusal": True})
        return res
    want = "predicate" if (fmt == "openai" and q["type"] == "noul") else q["type"]
    if ans.get("type") != want:
        res["error"] = f"malformed_response: answer type {ans.get('type')!r}, expected {want!r}"
        return res
    res["vendor_confidence"] = ans.get("confidence")
    if q["type"] == "noul":
        p = ans.get("probability") if fmt == "openai" else ans.get("noul")
        if not _is_prob(p):
            res["error"] = "malformed_response: yes/no probability missing or out of range"
            return res
        return _finish(res, {"yes": float(p), "no": 1.0 - float(p)}, order)
    raw = ans.get("probabilities")
    res["vendor_choice"] = ans.get("choice") if q["type"] == "choice" else None
    if fmt == "openai":
        if not isinstance(raw, list) or not all(isinstance(e, dict) for e in raw):
            res["error"] = "malformed_response: probabilities is not a list of objects"
            return res
        if q["type"] == "choice":
            probs = {e.get("value"): e.get("probability") for e in raw}
        else:
            probs = {}
            for e in raw:
                idx = e.get("value")
                key = order[idx] if isinstance(idx, int) and 0 <= idx < len(order) else f"#{idx}"
                probs[key] = e.get("probability")
    else:
        if not isinstance(raw, dict):
            res["error"] = "malformed_response: probabilities is not an object"
            return res
        if q["type"] == "choice":
            probs = dict(raw)
        else:
            probs = {}
            for key, value in raw.items():
                idx = int(key) if str(key).isdigit() else -1
                probs[order[idx] if 0 <= idx < len(order) else f"#{key}"] = value
    return _finish(res, probs, order)


def parse_response(fmt: str, body, case: dict) -> dict:
    """Wire response body (already JSON-decoded) -> {"model_echo", "input_tokens",
    "answers": {question name: canonical result fields}}."""
    out = {"model_echo": None, "input_tokens": None, "answers": {}}
    questions = case["questions"]
    if not isinstance(body, dict):
        for name in questions:
            res = blank_result()
            res["error"] = "malformed_response: body is not a JSON object"
            out["answers"][name] = res
        return out
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    tokens = usage.get("total_input_tokens") if fmt == "gemini" else usage.get("input_tokens")
    out["input_tokens"] = tokens if isinstance(tokens, int) and not isinstance(tokens, bool) \
        else None
    out["model_echo"] = body.get("model") if isinstance(body.get("model"), str) else None
    answers = body.get("answers")
    for i, (name, q) in enumerate(questions.items()):
        if fmt == "openai":
            ans = None
            if isinstance(answers, list):
                named = [a for a in answers if isinstance(a, dict) and a.get("name") == name]
                # Answers come back in question order; fall back to position for unnamed ones.
                ans = named[0] if named else (answers[i] if i < len(answers) and isinstance(
                    answers[i], dict) and answers[i].get("name") is None else None)
        else:
            ans = answers.get(name) if isinstance(answers, dict) else None
        out["answers"][name] = _parse_answer(ans, q, fmt)
    return out


def parse_error(fmt: str, status: int | None, text: str) -> dict:
    """An HTTP error or transport failure -> canonical result fields. A Gemini input-filter
    block is the one HTTP error that is a refusal; everything else is `error`."""
    res = blank_result()
    detail = (text or "").strip()
    code = None
    try:
        body = json.loads(detail)
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            code = err.get("code")
            detail = str(err.get("message") or detail)
        elif isinstance(body, dict) and "detail" in body:
            detail = json.dumps(body["detail"])
    except ValueError:
        pass
    if fmt == "gemini" and status == 400 and code in GEMINI_BLOCK_CODES:
        res.update({"outcome": "refusal", "refusal": True, "error": f"blocked: {code}"})
        return res
    res["error"] = f"http_{status}: {detail[:300]}" if status else f"transport: {detail[:300]}"
    return res


# --------------------------------------------------------------------------------------
# Arms and HTTP
# --------------------------------------------------------------------------------------

def looks_like_alias(model: str) -> bool:
    parts = model.lower().replace("/", "-").replace("_", "-").split("-")
    return any(h in parts for h in ALIAS_HINTS)


def resolve_arm(spec: dict, env: dict | None = None) -> dict:
    """Fill an arm from its spec, a provider preset and the environment.

    spec keys: name, provider, format, url, model, expect, auth, key_env, placement,
    price_per_m, header.<Name>. `expect` is the model id the server is expected to report
    (the pin). `price_per_m` is US dollars per million input tokens, for the cost columns.
    Environment fallbacks: DMB_PROVIDER, DMB_FORMAT, DMB_URL, DMB_MODEL, DMB_AUTH,
    DMB_KEY_ENV (the NAME of the variable that holds the key; default DMB_API_KEY).
    The key itself is read from that variable and never from the command line."""
    env = os.environ if env is None else env
    spec = {k.replace("-", "_") if not k.startswith("header.") else k: v for k, v in spec.items()}
    provider = spec.get("provider") or env.get("DMB_PROVIDER")
    preset = {}
    if provider:
        if provider not in PROVIDERS:
            raise CaseError(f"unknown provider {provider!r}; known: {sorted(PROVIDERS)}")
        preset = PROVIDERS[provider]
    fmt = spec.get("format") or preset.get("format") or env.get("DMB_FORMAT")
    if fmt not in WIRE_FORMATS:
        raise CaseError(f"arm needs format= one of {sorted(WIRE_FORMATS)} (or a provider=)")
    url = spec.get("url") or preset.get("url") or env.get("DMB_URL")
    if not url:
        hint = preset.get("url_hint", "the full endpoint URL")
        raise CaseError(f"arm needs url= ({hint})")
    model = spec.get("model") or env.get("DMB_MODEL")
    if not model:
        raise CaseError("arm needs model= (a versioned model id, or a deployment name)")
    auth = spec.get("auth") or preset.get("auth") or env.get("DMB_AUTH") or "bearer"
    key_env = spec.get("key_env") or env.get("DMB_KEY_ENV") or "DMB_API_KEY"
    key = env.get(key_env)
    if auth != "none" and not key:
        raise CaseError(f"arm uses auth={auth} but the environment variable {key_env} is empty")
    placement = spec.get("placement", "user")
    if placement != "user" and fmt != "openai":
        raise CaseError("placement= applies to format=openai only")
    try:
        price = float(spec["price_per_m"]) if spec.get("price_per_m") not in (None, "") else None
    except ValueError:
        raise CaseError("price-per-m= must be a number (US dollars per million input "
                        "tokens)") from None
    return {
        "name": spec.get("name") or model, "provider": provider, "format": fmt, "url": url,
        "model": model, "auth": auth, "key_env": key_env if auth != "none" else None,
        "placement": placement, "expect_model": spec.get("expect"), "price_per_m": price,
        "headers": {k[len("header."):]: v for k, v in spec.items() if k.startswith("header.")},
        "verified": bool(preset.get("verified", WIRE_FORMATS[fmt]["verified"])) if provider
        else None,
        "not_confirmed": list(WIRE_FORMATS[fmt]["not_confirmed"]) + list(
            preset.get("not_confirmed", [])),
        "model_is_alias": looks_like_alias(model),
        "_key": key if auth != "none" else None,
    }


def safe_url(url: str) -> str:
    """The URL without user info, query string or fragment, any of which can carry a key."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return f"{parts.scheme}://{host}{parts.path}"


def public_arm(arm: dict) -> dict:
    """The arm as it may be written to disk: no key, and the URL without its query string.
    Values of extra `header.<Name>` settings are kept, so credentials do not belong there."""
    out = {k: v for k, v in arm.items() if not k.startswith("_")}
    out["url"] = safe_url(arm["url"])
    return out


def auth_headers(arm: dict) -> dict:
    key, scheme = arm.get("_key"), arm["auth"]
    if scheme == "none":
        return {}
    if scheme == "bearer":
        return {"Authorization": f"Bearer {key}"}
    if scheme in ("api-key", "x-goog-api-key"):
        return {scheme: key}
    if scheme.startswith("header:"):
        return {scheme.split(":", 1)[1]: key}
    raise CaseError(f"unknown auth scheme {scheme!r}; use bearer, api-key, x-goog-api-key, "
                    "header:<Name> or none")


def redact(text: str | None, secret: str | None) -> str | None:
    if text and secret:
        return text.replace(secret, "***")
    return text


def _opener(url: str):
    """Loopback endpoints (the mock, a local server) must not go through an HTTP proxy."""
    host = urlsplit(url).hostname or ""
    if host in ("localhost", "::1") or host.startswith("127."):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def post_json(url: str, payload: dict, headers: dict, timeout: float) -> tuple[int | None, str]:
    """One POST. Returns (status, body text); status is None for a transport failure."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", **headers})
    try:
        with _opener(url).open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as exc:
        return None, f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"


def decide(arm: dict, case: dict, timeout: float = 60.0, retries: int = 2,
           backoff: float = 1.0, sleep=time.sleep) -> dict:
    """Send one canonical case to one arm. Returns
    {"answers": {name: canonical result}, "model_echo", "input_tokens", "latency_ms",
     "http_status", "attempts"}; every canonical result also carries those shared fields.

    Retries cover 429, 5xx and transport failures only; `attempts` records how many requests
    were made. Latency is the wall time of the last attempt."""
    payload = build_request(arm["format"], case, arm["model"], arm.get("placement", "user"))
    headers = {**arm.get("headers", {}), **auth_headers(arm)}
    status, text, latency, attempts = None, "", None, 0
    for attempt in range(retries + 1):
        attempts += 1
        start = time.perf_counter()
        status, text = post_json(arm["url"], payload, headers, timeout)
        latency = (time.perf_counter() - start) * 1000.0
        if status is not None and status not in RETRY_STATUS:
            break
        if attempt < retries:
            sleep(backoff * (2 ** attempt))
    shared = {"latency_ms": round(latency, 2), "http_status": status, "attempts": attempts,
              "model_echo": None, "input_tokens": None}
    if status == 200:
        try:
            body = json.loads(text)
        except ValueError:
            body = None
        parsed = parse_response(arm["format"], body, case)
        shared.update({"model_echo": parsed["model_echo"], "input_tokens": parsed["input_tokens"]})
        answers = parsed["answers"]
    else:
        answers = {name: parse_error(arm["format"], status, text) for name in case["questions"]}
    for res in answers.values():
        res["error"] = redact(res["error"], arm.get("_key"))
        res.update(shared)
    return {"answers": answers, **shared}
