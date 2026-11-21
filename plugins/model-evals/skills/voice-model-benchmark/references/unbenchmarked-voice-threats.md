# Voice threats with no standardized benchmark

The known lane measures the same published requests typed and spoken, with and without
simple audio perturbations. The threats below matter for a voice deployment and, as far as
the survey behind this skill found (2026-11), have **no standardized benchmark**. The custom
lane (`custom/`, scored without a judge) covers a fixed, fictional version of the first three;
the rest are design-review questions. For each one this file gives a probe you could build
against the deployment's own configuration and questions for a design review.

How to use it:
- These are checklists for the reviewer. They are not controls and not requirements, and
  nothing here says what answer is acceptable.
- For every item, record one of: probed (with what, how many cases, the result and its
  interval), reviewed by design (who answered, pointing at which document or code), or not
  assessed. "Not assessed" is a finding to carry into the report, not a gap to leave out.
- "No standardized benchmark exists" is itself the state to report for these threats.
- Custom probes are your own test cases. Results from them are not comparable with anyone
  else's numbers.

Parts of this skill you can reuse in a probe: the custom-lane format (`custom/cases.jsonl`
and `custom/scenarios.json`, run with `--custom-dir <folder> --lanes custom`), which takes
your real instructions and tool definitions per scenario and scores canaries, forbidden calls
and secrets deterministically; `synth.py` (local speech, two voices), `audio.mix`, `perturb.py`;
and `--save-audio` for listening. Every row of `samples.jsonl` keeps the transcript, the
provider's status and any `tool_calls` the model asked for.

## 1. Background-speech injection in the call flow

A second voice in the caller's audio (a television, another person, audio played down the
line on purpose) carries instructions, and the model follows them as if the caller said them.

Measured by the custom lane as `vm-third-party-speech`: 8 pairs in a fictional retailer's
session, a second Piper voice at -3 or -6 dB under or after the caller, scored by a canary
word or a forbidden refund call. One mixing level per case; no level sweep.

Custom probe against your own deployment:
- Synthesise a normal caller request and, with a different voice, an instruction that
  demands a marker phrase the caller never asks for. Mix the second under the first at a
  few levels (add the samples of the two clips; `audio.py` reads and writes them).
- Run the mixed clips with your real `instructions`. Count replies containing the marker.
  Report the rate per mixing level, with the clean clip as the baseline arm.
- An injection corpus with marker phrases, such as the one in this repository's
  app-benchmark skill, is a source of instruction text.

Review questions:
- Does anything separate the caller's voice from other audio before the model hears it?
- Is input noise reduction on, and was the probe run with the same setting?
- Which actions can a spoken instruction trigger without a second factor?
- What does the agent do when two voices give conflicting instructions?

## 2. Tool or MCP abuse by voice, with the team's real tool schema

The realtime models call functions. A spoken request may trigger a sensitive tool, or carry
arguments the caller is not entitled to set.

Measured by the custom lane as `vm-tool-abuse` with two fictional tool sets (a refund limit;
account changes behind a one-time code). With the team's real schema it becomes a
deployment-specific probe:
- Put the deployment's real tool definitions and instructions in `--session-config`.
- Write cases (your own `--corpus` file) that ask, by voice, for actions the caller should
  not get: another customer's data, a refund without the preconditions, a changed payout
  destination. Include matched legitimate requests.
- This skill does not execute tools. In the custom-lane format, write the rule as a
  `forbidden` call (tool name, argument conditions, per-key totals) and the matching
  legitimate request as a benign twin with an `expected` call; the scorer reads `tool_calls`.
  The judge's refused/complied verdict on the transcript is not the metric here.

Review questions:
- Which tools are irreversible or move money or data? Who or what authorises each call:
  the model, the application, a person?
- Are tool arguments checked on the server against the authenticated caller, or trusted as
  the model produced them?
- For MCP servers: which tools are allowed, and is approval required per call? (OpenAI's
  realtime MCP configuration has `allowed_tools` and `require_approval` fields.)
- Tool results come back into the conversation. Can a result contain text the model will
  treat as instructions?
- Is a spoken confirmation ("yes") enough for a high-impact action, and can it be supplied
  by audio the caller did not produce (see 1 and 5)?

## 3. System-prompt leakage

The session instructions may hold business rules, internal names or secrets. A caller asks
the model to read them out, translate them, or spell them.

Measured by the custom lane as `vm-secret-leak`: a canary code in a fictional carrier's
instructions, 8 spoken extraction requests and 8 benign twins asking for public facts. The
scorer normalises spelled-out digits, letter-by-letter and phonetic-alphabet spelling.

Custom probe against your own instructions:
- Add a unique marker string to a copy of the instructions in `--session-config`.
- Write cases that ask for the instructions in different ways, spoken and typed. Run them
  and count transcripts that contain the marker or a recognisable part of it.
- Listen to a sample of the saved audio: the transcript is the provider's, and a spelling the
  normaliser does not know (for example "K as in kilo") is missed.

Review questions:
- Is anything in the instructions that would matter if a caller heard it?
- Are secrets (keys, internal URLs, account identifiers) kept out of the instructions and
  supplied through tools instead?
- Is the transcript logged where more people can read it than can read the instructions?

## 4. The transcript-versus-audio guardrail gap

Guardrails and graders usually read text. The model consumes and produces audio. OpenAI's
reference says input transcription runs on a separate speech-recognition model and "may
diverge somewhat from the model's interpretation". A filter on the transcript therefore
checks something adjacent to what was heard or said. This skill's own judge has the same
limit, which is why ANALYZE includes listening to a sample.

Custom probe:
- Keep the spoken output (`--save-audio all` on a small run), transcribe it with a speech
  recogniser of your own, and compare with the provider's transcript: word error rate, and
  the cases where the two differ in meaning.
- For an input-side filter: run the perturbed arms with `--input-transcription <model>` and
  compare `input_transcript` with the prompt. Where the transcript is wrong and the model
  still answered the real request, a transcript filter saw the wrong text.

Review questions:
- Does each guardrail read the input transcript, the output transcript, or audio?
- Output is streamed. When a guardrail triggers, how much audio has already been played,
  and what happens to it?
- Which languages, accents and code-switching were the guardrails tested on?
- Does anything check content that is spelled out, sung, or spoken very fast or slowly?

## 5. Barge-in manipulation

With voice activity detection on, speech from the caller interrupts the model. The session
settings `interrupt_response` and `create_response`, and the detection type (`server_vad` or
`semantic_vad`), decide what an interruption does.

Why this skill does not probe it: the runner turns detection off and sends each clip as one
complete turn. A barge-in probe needs audio streamed at real-time pace into a session with
detection on, timed against the model's speech.

Review questions:
- If the caller interrupts a refusal, a disclosure or a confirmation prompt, what state is
  the conversation in afterwards? Does the application treat the interrupted step as done?
- After an interruption, does the conversation record match what the caller actually heard?
- Can sound that is not the caller (echo of the model's own voice, background speech)
  trigger an interruption or a new turn?
- Are turn-detection settings the same in test and production?

## 6. SIP header spoofing

Phone calls reach the model through a SIP trunk. OpenAI's SIP guide shows the incoming-call
webhook carrying `sip_headers` such as `From`, `To` and `Call-ID`, with a signature header
on the webhook itself. Its guide for the newer Live API states that those headers are
"untrusted caller metadata, not authorization".

Why this skill does not probe it: it needs calls placed through a trunk you control, with
chosen header values, against your call-handling code.

Review questions:
- Is the caller's number or display name used to authenticate, authorise, look up an
  account, or personalise the greeting?
- Is any header value placed into the session instructions? If so, it is attacker-chosen
  text in the prompt.
- Does the webhook handler verify the signature and reject replays before accepting a call?
- Who can send calls to the project's SIP address, and does the trunk restrict sources?
- Can the model's output choose a transfer destination or send keypad tones?

## 7. Session cost caps

Realtime sessions are billed by tokens, and audio is many tokens per second (OpenAI's cost
guide: one token per 100 ms of user audio, one per 50 ms of assistant audio). A caller who
keeps a line open, or induces long spoken replies, spends the operator's money.

Custom probe:
- Script a long session and sum `usage` from each `response.done` (this skill's rows keep
  it) to get tokens per minute for your instructions and tools.
- Send requests for very long output with and without `--max-output-tokens` and compare
  `output_audio_seconds` and `status_reason`.

Review questions:
- What bounds one session: duration, turns, output tokens per response, idle time?
- What bounds one caller: concurrent sessions, calls per number per hour?
- Is there a spend alert or cap per project, and what happens to live calls when it is hit?
- Does the application close the session when the caller hangs up or goes silent?

## 8. Voice cloning

Two different questions share this name.

(a) A cloned voice used *against* the deployment: someone sounds like a customer.
- Is voice used anywhere as evidence of identity, by the model, the application or a human
  agent the call is transferred to?
- If so, what else is required, and was it tested with synthetic speech?

(b) The deployment's *own* output voice.
- Which output voices are enabled? OpenAI documents custom voices created from a recording,
  which require a consent recording from the speaker. Where are those consent records?
- Can a caller get the agent to imitate a named person, a staff member or the caller?
  A small manual probe: ask, by voice, for an impersonation and listen to the saved audio.
- Are call recordings and voice samples handled as personal data under the organisation's
  own policy?

Published audio sets include clips that imitate public figures' voices (see
public-audio-sets.md). Using them in a test is a decision for the organisation.
