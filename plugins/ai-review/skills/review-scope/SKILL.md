---
name: review-scope
description: >-
  First stage of a guided AI security review. Interviews the requester about the AI
  capability being enabled (a model, a model inside an agent harness, an app, a decision,
  voice or image model, or a new agent feature) and writes review.json: the subject, the
  deployment context, who controls each input channel, what the capability can do, what
  happens on failure and the time budget. Ships a validator that prints what is missing.
  Use when a review is requested and before any threat model, evidence harvest or
  measurement. Records the scope; never judges it.
license: MIT
compatibility: "Requires python>=3.10 (standard library only). No network, no API keys."
---

# review-scope — write down what is being reviewed

You are running this skill for a reviewer who has been asked whether an AI capability can
be enabled. This stage produces one file, `review.json`. Every later stage reads it:
`review-threat-model` picks the threat template from `subject.type`, measurement skills copy
`context` into their manifests so each result says where it applies, and `review-report`
prints it as the first section.

This skill records the scope. It does not say whether the scope is acceptable, and it does
not recommend controls.

## What the reviewer supplies

- The request as it arrived (ticket, email, message) and who sent it.
- Access to someone who knows the deployment: which product surface, which harness and
  version, which tools are switched on, what data it will see.
- The date a decision is needed and the reviewer hours available.

## What gets written

`review.json` in the review's working directory (the directory that will also hold
`evidence.jsonl`, `criteria.json` and `.evals/`). Schema and field notes:
[references/review-schema.md](references/review-schema.md).

## Steps

### 1. Start from a blank profile
```
python scripts/validate_review.py --blank <type> > review.json
```
`<type>` is one of `model`, `agent`, `app`, `decision-model`, `voice-model`, `image-model`,
`feature`. Pick by what the requester would name: a model reached through its API is
`model`; the same model inside a coding or desktop harness is `agent`; something the
organisation built on a model is `app`; a single capability being switched on in an
existing agent (computer use, memory, connectors, code execution, multi-agent, background
agents) is `feature`.

### 2. Interview the requester
Ask one or two questions at a time. Write the answer in the requester's words; do not
tidy an answer into something more reassuring than what was said.

**Subject**
- What exactly is being enabled, and which version? An alias such as "latest" is not a
  version: ask for the dated or numbered identifier.
- Who supplies it? Are the weights downloadable (and from which repository)?

**Context** — the nine keys under `context`. Measurement skills copy these keys and no
others, so do not add keys here.
- `surface`: where people meet it (API, web chat, IDE, phone line, internal tool).
- `harness`, `harness_version`: the agent software around the model, or `none`.
- `system_prompt`: whose prompt runs (vendor default, harness default, the organisation's
  own) and whether the reviewer can read it.
- `tools`: every tool or connector that will be switched on. `[]` means none.
- `safeguards`: provider classifiers, harness permission prompts, guardrails in front.
  Record on/off as deployed, not as documented.
- `data_sensitivity`: the most sensitive data that will reach it.
- `autonomy`: what it may do without a person approving.

**Who controls each input channel** — one entry per channel under `input_channels`.
- Start with the obvious one (the user's prompt), then ask "what else does it read?":
  files, retrieved documents, web pages, tool results, email, tickets, other agents'
  output, audio in the room, images.
- For each: who can put content there, and is any of them outside the organisation's
  control (`untrusted: true`)? A channel nobody thought of is the common finding here.

**What it can do** — `capabilities`.
- What can it read? What can it change, send, execute or spend?
- Which of those need a person's approval, and whose?
- Does it keep anything between sessions (`memory`)?

**What happens on failure** — `failure_impact`.
- What is the worst realistic outcome if it is steered by an attacker or simply wrong?
- Who is affected? Can it be undone? How would anyone notice?

**Time budget** — `time_budget`.
- When is the decision due and how many reviewer hours exist? Later stages use this to
  choose how deep to measure; they print their cost before running.

**Out of scope** — `out_of_scope`.
- What did the requester rule out (other surfaces, other data, other user groups)? Write
  each with its reason. `[]` is allowed only when the question was asked and the answer
  was "nothing".

### 3. Validate
```
python scripts/validate_review.py review.json
```
It prints three separate lists:

| List | Meaning | What to do |
|---|---|---|
| `errors` | The file breaks the schema | Fix the file |
| `missing` | A required answer is absent | Go back to the requester |
| `stated as unknown` | The answer is the literal `"unknown"` | Keep it; it is carried into the report as not assessed |

Exit code 0 means every required answer is present. `--strict` also fails on unknowns;
`--json` prints the same findings for another tool.

### 4. Hand over
Tell the reviewer where `review.json` is, read back the `stated as unknown` list and the
`out_of_scope` list, and point to the next stages: `review-evidence` (what already
exists) and `review-threat-model` (threats and a test plan).

## Saying what was not assessed

- An answer nobody could give is written as `"unknown"`, never left blank and never
  guessed. The validator lists these and `review-report` repeats them.
- A surface, data class or user group the requester excluded goes in `out_of_scope` with
  the reason. Results from later stages apply only to the context written here.
- If the deployment changes after measurements were taken (a tool is added, a safeguard is
  switched off), the earlier results describe a different context. Update `review.json`
  and say so; do not edit it silently.

## Smoke test

No keys, no network:
```
python scripts/validate_review.py examples/review.example.json
```
Expected: `complete: every required answer is present.` and exit code 0. The example is a
fictional subject.

## Notes

- `context` must hold exactly these keys: `surface`, `harness`, `harness_version`,
  `system_prompt`, `tools`, `safeguards`, `data_sensitivity`, `autonomy`, `notes`. They
  are read from the vendored `lib/evalkit.py`, the same list measurement skills use.
- The validator checks that answers are present and well-formed. It cannot check that
  they are true; the interview is the control on that.
- **Not verified**
  - The interview was not exercised with a real requester; the question list comes from
    the review design, not from field use.
