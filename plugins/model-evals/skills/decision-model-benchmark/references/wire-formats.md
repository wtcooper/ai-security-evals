# Wire formats and what was verified

`adapter.py` translates one canonical case into three wire formats and one canonical result
back. This file records what each format looks like, where that was read, and what was not
confirmed.

**What "verified" means here.** `verified: true` = the request JSON and the response JSON
were both read in a primary source (the vendor's documentation or OpenAPI file) on
2026-11-14. **No live call was made to any decision-model API**: no keys were available.
The adapter was exercised only against `mock_server.py`, which was written from the same
pages, so the mock cannot catch a misreading of them. Treat the first smoke run against a
real endpoint as the real test. The API category is about two months old and the pages move;
re-check them before relying on this file.

## Canonical case and result

```
case    {"state": <string | object | array>,
         "untrusted_field": "<dotted path into state>",        (optional)
         "questions": {"<name>": {"type": "noul" | "choice" | "score",
                                  "instructions": "<text>",
                                  "options": [{"label": "<id>", "criteria": "<text>"}, ...]}}}

result  outcome         answered | refusal | error
        label           argmax of the returned distribution (computed by the adapter)
        probs           {label: probability}, as returned, not renormalised
        top_p, margin   top probability; top minus runner-up
        refusal         true when the server declined
        latency_ms, input_tokens, model_echo, http_status, attempts, error
        vendor_confidence, vendor_choice     recorded, never used for a metric
```

- `noul` has exactly the options `yes` and `no`. Its distribution is `{yes: p, no: 1 - p}`.
- `score` options are ordered lowest to highest; the label names the level and the decision
  is the most probable level, not the probability-weighted average the vendors also return.
- A tie for the top probability goes to the option that was sent first, and the row is
  marked `tie`.
- Anything that is not a complete distribution over exactly the options sent is an `error`.
  A refusal is a `refusal`. Neither is ever turned into a label.

## A. System One (`format=systemone`) — verified: true

Source: TypeSafe API reference, OpenAPI 0.2.0, `POST /v1/systemone`
(https://docs.typesafe.ai/api/system-one.md). Auth: `Authorization: Bearer <key>`.

```
request   {"model": "...", "state": <string | object | array>,
           "questions": {"<name>": {"type": "noul", "instructions": "...",
                                    "criteria": {"true": "...", "false": "..."}},   (optional)
                         "<name>": {"type": "choice", "instructions": "...",
                                    "criteria": {"<option>": "<description>", ...}},
                         "<name>": {"type": "score", "instructions": "...",
                                    "criteria": ["<lowest level>", ..., "<highest level>"]}}}

response  {"model": "...",
           "answers": {"<name>": {"type": "noul", "noul": 0.98},
                       "<name>": {"type": "choice", "choice": "...", "confidence": 0.7,
                                  "probabilities": {"<option>": 0.8, ...}},
                       "<name>": {"type": "score", "score": 1.7, "confidence": 0.55,
                                  "legend": {"0": "...", ...},
                                  "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8}}},
           "usage": {"input_tokens": 120, "output_tokens": 12}}

errors    400 {"detail": "<string or object>"}   422 {"detail": [{"loc": [...], "msg": "...", "type": "..."}]}
```

How the adapter maps to it:
- `state` is sent as given; an object stays an object.
- `choice` options become the `criteria` object in the order given. JSON objects have no
  defined order, but TypeSafe documents that the model "leans toward the option that comes
  first", so the order in the request text is what the reorder axis changes.
- `score` levels are sent as `"<label>: <criteria>"` strings; probabilities come back keyed
  by level index and are mapped back to the labels.
- Response `model` "may differ from the alias supplied in the request" (TypeSafe); the
  adapter records it as `model_echo`.

Not confirmed:
- TypeSafe's reference shows no refusal answer. OpenRouter documents `{"type": "refusal"}`
  per question for this format; the parser accepts that from any server.
- Limits (64k tokens; 262k behind the `TypeSafe-Danger-Zone-Long-Context: true` header) were
  not exercised. Pass the header with `header.TypeSafe-Danger-Zone-Long-Context=true` on the arm.
- `box` questions and image assets are not implemented.

### Providers that use format A

| Provider | Endpoint | Auth | Verified | Not confirmed |
|---|---|---|---|---|
| `typesafe` | `https://api.typesafe.ai/v1/systemone` | bearer | true | — |
| `openrouter` | `https://openrouter.ai/api/alpha/decisions` | bearer | true | Error body is not documented. The path is under `/api/alpha`. Response adds `id`, `provider`, `usage.cost`, and `confidence` on `noul`; all ignored. Source: https://openrouter.ai/docs/guides/features/decisions |
| `microsoft` | `<foundry-resource-endpoint>/providers/microsoft/v1/systemone` | bearer (Entra token) or `auth=api-key` | **false** | See below |
| `clef` | your Workers AI or self-hosted URL | bearer | **false** | Request and response JSON were not read in a primary source; only the claim that it is compatible with this format |
| `local` | your server | none | **false** | Whatever that server implements |

**Microsoft-Decision-1** (https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision).
Confirmed from the page: the path; request bodies for `noul`, `choice` and `score`, which
match format A including `criteria: {"true", "false"}`; `Authorization: Bearer` or `api-key`
headers; the request `model` is the **deployment name** and the response `model` names the
underlying model; the response has an `answers` object keyed by question name plus the model
name and token usage; the page's sample code reads `answers[name].type` and
`answers[name].choice`. **Not confirmed:** the page shows no raw response JSON, so the field
names `probabilities`, `noul`, `score` and `usage.input_tokens` are assumed from its statement
that the pattern is "similar to a system-one API". If they differ, every row will be an
`error` with `malformed_response`, which the smoke depth shows at once. Because the request
carries a deployment name, pin the underlying model with `expect=<id>` on the arm.

## B. OpenAI Decisions (`format=openai`) — verified: true

Sources: https://developers.openai.com/api/docs/guides/decisions and the create-decision
reference at https://developers.openai.com/api/reference/resources/decisions/methods/create.
`POST https://api.openai.com/v1/decisions`, `Authorization: Bearer <key>`.

```
request   {"model": "gpt-6-luna",
           "input": "<string>"  |  [ {"role": "user", "content": [{"type": "input_json", "data": {...}}]},
                                     {"type": "function_call", "call_id": "...", "name": "...", "arguments": "..."},
                                     {"type": "function_call_output", "call_id": "...", "output": "<text>"} ],
           "questions": [ {"type": "predicate", "name": "...", "instructions": "..."},
                          {"type": "choice", "name": "...", "instructions": "...",
                           "choices": [{"value": "...", "description": "..."}, ...]},
                          {"type": "score", "name": "...", "instructions": "...",
                           "levels": [{"label": "...", "description": "..."}, ...]} ]}

response  {"model": "...",
           "answers": [ {"type": "predicate", "name": "...", "probability": 0.95},
                        {"type": "choice", "name": "...", "choice": "...", "confidence": 0.93,
                         "probabilities": [{"value": "...", "probability": 0.95}, ...]},
                        {"type": "score", "name": "...", "score": 1.1, "confidence": 0.55,
                         "probabilities": [{"value": 0, "label": "...", "probability": 0.1}, ...]},
                        {"type": "refusal", "name": "..."} ],
           "usage": {"input_tokens": 42, "input_tokens_details": {...}, "output_tokens": 0, ...}}
```

How the adapter maps to it:
- Yes/no is `predicate`, which has **no criteria field**. The canonical yes/no criteria are
  appended to the instructions as `Answer true when: ...` and `Answer false when: ...`.
- A string state is sent as a string. An object state is sent as one `input_json` part in a
  user message (the guide says keys inside `data` are ordinary data).
- `placement=tool_output` (an arm option) removes the untrusted field from the user message
  and sends its text as a `function_call` / `function_call_output` pair. OpenAI is the only
  format with separate positions for developer, user and tool content, so this is the only
  format where the question "does the position of untrusted content matter" can be asked.
  Run the same model as two arms, `placement=user` and `placement=tool_output`.
- Answers are matched by `name`, falling back to position for unnamed answers.
- A per-question `{"type": "refusal"}` becomes outcome `refusal`.

Not confirmed:
- The error body is not described on either page. The parser reads `error.message` when the
  body has that shape and keeps the raw text otherwise.
- Whether the real API accepts the exact `tool_output` item sequence above was not tested.
- Prompt caching: identical re-runs may be served with cached input. That changes billing,
  not the request; whether it changes run-to-run variation is unknown.
- `azure-openai`: the Azure path, `api-version` parameter and header were not read.

## C. Gemini Decisions (`format=gemini`) — verified: true

Source: https://aistudio.google.com/docs/decisions-api (REST examples and the request and
response reference table). `POST https://generativelanguage.googleapis.com/v1beta/decisions`,
header `x-goog-api-key: <key>`.

```
request   {"model": "gemini-decision-1", "input": "<string>" | <content block(s)>,
           "questions": {"<name>": {"type": "noul", "instructions": "...",
                                    "criteria": {"true_description": "...", "false_description": "..."}},
                         "<name>": {"type": "choice", "instructions": "...", "criteria": {"<option>": "<description>"}},
                         "<name>": {"type": "score", "instructions": "...", "criteria": ["<lowest>", ..., "<highest>"]}}}

response  {"answers": {"<name>": {"type": "noul", "noul": 0.99, "confidence": 0.99},
                       "<name>": {"type": "choice", "choice": "...", "probabilities": {...}, "confidence": 0.99},
                       "<name>": {"type": "score", "score": 1.12, "legend": {...}, "probabilities": {...}, "confidence": 0.83}},
           "usage": {"total_input_tokens": 100, "input_tokens_by_modality": [...], "total_output_tokens": 0, "total_tokens": 100}}

blocked   HTTP 400 {"error": {"code": "safety" | "prohibited_content" | "blocklist" | "image_safety" | "content_blocked", "message": "..."}}
```

How the adapter maps to it:
- An object state is serialised to a JSON string and sent as text, as Google's guide advises.
- Yes/no criteria use the keys `true_description` and `false_description`.
- **The API sorts choice option keys alphabetically before evaluation**, and says that
  changing key order in the request does not change option positions. The `option_order`
  variants therefore reach a Gemini arm as the same request as the clean one. They are still
  sent, so that every arm gets the same request list; the summary flags the arm
  (`option_order_not_sent`) and that row is a second noise-floor estimate. A renamed option
  can change its sorted position, so `option_rename` on Gemini mixes a name effect with a
  position effect.
- HTTP 400 with one of the five block codes becomes outcome `refusal`. Any other 400 is an
  `error`.
- Yes/no probabilities are documented to lie between 0.01 and 0.99.

Not confirmed:
- No documented response example has a `model` field, so `model_echo` is null and the run
  cannot confirm which model answered (flag `no_model_echo`).
- Only the safety-block error body is documented.
- Content blocks (image, audio, video, PDF) are not implemented; text only.

## Vendor `confidence` is not comparable, so it is not used

| Vendor | What `confidence` is | Source |
|---|---|---|
| TypeSafe | Choice: `(p_max - 1/n) / (1 - 1/n)`. Score: one minus the spread around the most likely level, normalised. It "measures how concentrated the answer's probabilities are", not the chance the answer is right. `noul` has no confidence field. | https://docs.typesafe.ai/confidence.md |
| Gemini | Equal to the top outcome's probability, or `max(noul, 1 - noul)` | the Decisions API page above |
| OpenAI | Returned on choice and score answers; no formula given | the guide above |
| Microsoft | Not shown | — |

The same distribution therefore gives different `confidence` values at different vendors.
Every confidence figure in this skill is computed from the returned distribution: `top_p`
(the top probability) and `margin` (top minus runner-up). The vendor value is kept in
`samples.jsonl` as `vendor_confidence` for reference only.

## Model identity

| Format | Request `model` | What the server reports |
|---|---|---|
| A TypeSafe | name or alias | the model that answered; may differ from an alias |
| A Microsoft | deployment name | documented to be the underlying model name |
| B OpenAI | model id | `model`: "The model used." |
| C Gemini | model id | nothing |

No seed or determinism setting was found in any of the pages read, which is why the
identical-re-run noise floor is measured in every run.
