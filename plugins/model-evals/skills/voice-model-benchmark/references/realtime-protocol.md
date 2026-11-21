# Realtime protocol used by the adapter, and how to add another vendor

## What the OpenAI adapter relies on

`adapters/openai_realtime.py` speaks the OpenAI Realtime API over WebSocket. Every item
below was read from OpenAI's documentation on 2026-11-14. The API has changed its event
names before, so re-read the sources after any API version change and re-run the smoke test.

Sources (developers.openai.com/api):
- `docs/guides/voice-websockets` (Realtime tab): connection URL and headers.
- `docs/guides/realtime-conversations`: session update, text and audio input, output events,
  turning voice activity detection off.
- `reference/resources/realtime/client-events` and `.../server-events`: event schemas.
- `docs/guides/realtime-costs`: audio token rule used for the plan estimate.
- `docs/models/gpt-realtime-2.1` and `docs/models/gpt-realtime-2.1-mini`: both are served only
  on `v1/realtime`; input text, audio, image; output text, audio; function calling.

| Step | Event or value | Fields the adapter uses |
|---|---|---|
| Connect | `wss://api.openai.com/v1/realtime?model=<model>` with `Authorization: Bearer <key>` | |
| Server greets | `session.created` | `session.model` |
| Configure | client `session.update` | `session.type: "realtime"`, `output_modalities: ["audio"]` or `["text"]`, `audio.input.format: {type: "audio/pcm", rate: 24000}`, `audio.input.turn_detection: null`, `audio.output.format`, optional `audio.input.transcription.model`, `max_output_tokens`, plus the caller's `instructions`, `tools`, `audio.output.voice`, `reasoning` |
| Confirmed | `session.updated` | |
| Typed input | client `conversation.item.create` | `item: {type: "message", role: "user", content: [{type: "input_text", text}]}` |
| Spoken input, buffer mode | client `input_audio_buffer.append` (base64 PCM16, one second per event), then `input_audio_buffer.commit` | server answers `input_audio_buffer.committed` |
| Spoken input, item mode | client `conversation.item.create` | `content: [{type: "input_audio", audio: <base64>}]` |
| Ask for a reply | client `response.create` | |
| Reply, audio output | `response.output_audio.delta`, `response.output_audio_transcript.delta`, `response.output_audio_transcript.done` | `delta` (base64 audio or text), `transcript` |
| Reply, text output | `response.output_text.delta`, `response.output_text.done` | `delta`, `text` |
| Function calls | `response.output_item.added` / `.done` with `item.type: "function_call"`, `response.function_call_arguments.done` | `item.id`, `item.name`, `call_id`, `name`, `arguments` (a JSON string); calls are keyed by `call_id` so each is recorded once |
| End of reply | `response.done` | `response.status`, `response.status_details.reason`, `response.output[].content[].transcript` or `.text`, `response.output[]` items of type `function_call` (`name`, `arguments`, `call_id`), `response.usage` |
| Input transcription (optional) | `conversation.item.input_audio_transcription.completed` | `transcript` |
| Failure | `error` | `error.type`, `error.code`, `error.message` |

Choices the adapter makes, and why:
- **One session per case.** A fresh connection for every (arm, case), so no case sees
  another's conversation.
- **Per-case instructions and tools.** A custom-lane case carries its scenario's
  `instructions`, `tools` and `tool_choice` (`TargetInput.session`); they replace those of
  `--session-config` in that case's `session.update` only. The measurement keys (modalities,
  audio format, turn detection off) stay fixed on top.
- **Function calls are recorded, never executed.** The exchange ends at the first
  `response.done`; no `function_call_output` is sent and no second response is requested. The
  custom lane scores the calls the model chose to make on hearing the request. A model that
  would first call a lookup tool and only then the privileged one is not exercised; the
  bundled scenarios declare no lookup tools for that reason.
- **Voice activity detection off.** With `turn_detection: null` the client commits the audio
  buffer and asks for the response. The clip is the whole user turn in every arm. A
  deployment that leaves detection on can cut a turn short or respond early; that is barge-in
  behaviour, which this benchmark does not measure (see unbenchmarked-voice-threats.md).
- **Audio is sent faster than real time**, one second per append event. The documentation
  describes the buffer as storage the client writes and then commits; it does not require
  pacing when detection is off. Not verified against the live API.
- **Output modality is the same in every arm.** The default is audio output with its
  transcript, because that is what a voice deployment does. `--output text` is cheaper and
  removes the transcript-versus-audio question, but it is a different configuration from a
  spoken deployment.
- **`status_details.reason`** is kept on every row. The documented reasons include
  `content_filter` and `max_output_tokens`. An empty reply with `content_filter` is recorded
  as a refusal graded by status, not by the judge.
- **Input noise reduction** is a session setting (`audio.input.noise_reduction`) that
  filters audio written to the buffer. The adapter does not set it. If the deployment sets
  it, put it in `--session-config`: it changes what the perturbation arms measure.

What was exercised against the real endpoint: the TLS connection, the WebSocket upgrade and
the `error` event, using an invalid key (the server replied `invalid_request_error` /
`invalid_api_key`). No session was configured and no audio was sent. Everything after the
greeting has only run against `mock_realtime_server.py`.

## A second realtime API: add one adapter file

An adapter is a class with `name`, `describe()` and `respond(TargetInput) -> TargetResult`
(`adapters/base.py`). Register it in `adapters/__init__.py` and select it with `--target`.

- `respond` opens a fresh session, sends typed text or the PCM16 clip (mono, 24 kHz; resample
  inside the adapter if the vendor wants another rate, and say so in `describe()`), and returns
  the reply transcript, the provider's status, any tool calls, the usage it reports and the
  spoken audio.
- It never raises for a target-side failure. It returns `TargetResult(error=...)`, which the
  report counts as a target error and keeps out of every rate.
- `describe()` returns the endpoint, model and session settings for the run manifest, and
  never a credential.
- Hold the same things fixed: end-of-turn decided by the client, one session per case, one
  output modality for all arms.

`miniws.py` is a standard-library WebSocket client you can reuse; pass `--transport
websockets` to the OpenAI adapter to use the `websockets` package instead.

OpenAI also documents a separate "Live" API (`wss://api.openai.com/v1/live/sessions`,
`session.start`, `session.input_audio.append`, `session.output_transcript.delta`). Its events
differ from the Realtime API, and the two models named above are listed as not supported on
it. It would be a separate adapter; none is included.
