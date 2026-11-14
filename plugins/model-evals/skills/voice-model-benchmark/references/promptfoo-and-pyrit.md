# Running the same comparison with promptfoo or PyRIT

For teams that already run one of these tools. Both can reach OpenAI realtime models. Only
what was read in their documentation or source on 2026-11-14 is stated here; neither tool
was installed or run for this skill, so treat every snippet as a starting point to verify.

Whichever tool sends the audio, keep this skill's design: the same seeded cases in every
arm, speech synthesised locally, one arm per input condition, a judge that is not the model
under test, and the unresolved share reported.

## Inspect AI (why this skill does not use it)

Issue #2698 on `UKGovernmentBEIS/inspect_ai` ("How to evaluate OpenAI Realtime API in
Inspect AI?") was open when read. The maintainer's reply there is that audio can be included
in ordinary generation requests, and that live realtime interaction needs a custom model
provider, solver or agent that talks to the API directly. No such provider ships with it.

## promptfoo

From `site/docs/providers/openai.md` in the promptfoo repository:

- Provider id `openai:realtime:<model>`, for example `openai:realtime:gpt-realtime-2.1`.
  It opens a conversational WebSocket session.
- `config.modalities: [text]` gives text-only output; `[text, audio]` with a `voice` gives
  spoken output plus a transcript that text assertions read.
- Session settings include `instructions`, `voice`, `turn_detection`, `tools`,
  `tool_choice`, `input_audio_transcription`, `max_response_output_tokens` and
  `websocketTimeout`.
- "Structured user messages use `input_text`, `input_audio`, or `input_image` blocks." That
  is how a locally made clip is sent: as an `input_audio` block holding base64 audio. The
  exact prompt layout is in promptfoo's `examples/openai-realtime` folder; it was not
  reproduced here.
- `apiBaseUrl` is converted to `ws://` or `wss://` and `/realtime` is appended, so the
  provider can be pointed at another host.
- "Failed, incomplete, and cancelled Realtime responses return the server status or reason
  as an error." A reply cut off by a content filter therefore shows up as an error, not as
  a graded refusal. Count those separately when you compare with this skill's numbers.

Do **not** use promptfoo's red-team `audio` strategy for this. Its documentation says the
text-to-speech conversion "requires remote generation", is "implemented exclusively on the
server side", and that the strategy sends the text to the remote service. That sends your
prompts off the machine and gives you no control over the voice or its repeatability.

A workable division of labour:
1. `python cases.py --depth standard --out cases.jsonl`, then `synth.py` and `perturb.py`
   to make the clips and their manifest with this skill.
2. Generate promptfoo test cases from the manifest: one test per (arm, case), the clip as an
   `input_audio` block, the arm name in `metadata`.
3. Grade with an `llm-rubric` whose `provider` is your judge, set explicitly.
4. Export results and compute paired differences yourself; promptfoo reports per-test
   outcomes, not paired statistics across arms.

## PyRIT

From the PyRIT repository (`microsoft/PyRIT`, main branch, version `1.3.0.dev0`; the project
moved from `Azure/PyRIT`). Module paths below are from main and have moved between releases,
so check them against the version you have installed.

- `RealtimeTarget` (`pyrit/prompt_target/openai/openai_realtime_target.py`, exported from
  `pyrit.prompt_target`). Its declared input modalities are text, and text with
  `audio_path`; outputs are text and `audio_path`. Its documented endpoints are
  `wss://api.openai.com/v1` and the Azure OpenAI equivalents. It takes `model_name`,
  `endpoint`, `api_key` and `voice`, with environment variables `OPENAI_REALTIME_MODEL`,
  `OPENAI_REALTIME_ENDPOINT` and `OPENAI_REALTIME_API_KEY` as defaults. It uses a 24 kHz PCM
  sample rate.
- Audio converters under `pyrit/converter/`: `AudioEchoConverter` (`delay`, `decay`),
  `AudioFrequencyConverter` (`shift_value`), `AudioSpeedConverter` (`speed_factor`),
  `AudioVolumeConverter` (`volume_factor`) and `AudioWhiteNoiseConverter` (`noise_scale`).
  These are the same families as this skill's perturbations, with different
  parameterisations, so results are comparable in kind and not in value.
- `AzureSpeechTextToAudioConverter` synthesises speech with the Azure Speech service. That
  is a cloud call with a credential. To keep synthesis local, make the WAV files with
  `synth.py` and hand PyRIT the file paths as `audio_path` inputs.

Whether the white-noise converter is seeded, and how PyRIT decides the end of a user turn,
were not checked.

## What you lose and keep

| | This skill's runner | promptfoo | PyRIT |
|---|---|---|---|
| Local, repeatable speech | yes (Piper, noise scales 0) | bring your own clips | bring your own clips |
| Perturbations with recorded parent and parameters | yes | bring your own clips | its converters, or bring clips |
| Same cases in every arm, paired statistics | yes | you compute them | you compute them |
| Multi-turn conversations | no, one turn per case | yes (`test.metadata.conversationId`) | yes (the target declares multi-turn support) |
| Tool calls executed during the test | no, recorded only | yes (`functionCallHandler`) | not checked |
