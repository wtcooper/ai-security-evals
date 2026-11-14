# Threat template — Voice or realtime speech model

A speech-to-speech or realtime audio model, on a phone line, in an app or in a device.

Which threats a catalogued benchmark covers depends on the catalogue at the time the plan is built; `scripts/plan.py` decides that. The last column says how a threat is assessed when no available benchmark covers it. A `—` in a framework column means no id was verified for that threat, not that none exists. The verified ids and where they were checked are in [framework-ids.md](framework-ids.md).

## Questions to ask for this subject type

- Where does audio come from: a phone line, a browser, a device in a room?
- Who else can be heard on the channel?
- Which tools can a spoken request trigger?
- Do any guardrails read a transcript rather than the audio?
- How is the caller identified?
- Is there a cap on session length and cost?

## Threats

| Threat id | Threat | Why it matters here | OWASP LLM 2025 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `voice-audio-jailbreak` | **Spoken request succeeds where text is refused.** A request the model refuses as text is fulfilled when delivered as speech. | The audio channel has been measured as weaker than text. | LLM01:2025 | — | AML.T0054 | custom probe: Synthesise refused text requests as speech locally and compare the two channels paired. |
| `voice-perturbation` | **Acoustic variation changes the outcome.** Accent, noise, speed, pitch or audio effects change whether a request is refused. | Real callers and attackers both vary the audio. | — | — | AML.T0043 | custom probe: Apply a fixed set of perturbations to the same spoken requests and report the change from the clean recording. |
| `voice-background-injection` | **Background speech followed as an instruction.** Speech from another person, a played recording or media in the room is treated as the caller's instruction. | Anything audible is input. | LLM01:2025 | — | AML.T0051.001, AML.T0129 | custom probe: No benchmark exists. Mix planted speech into recordings of the real call flow. |
| `voice-tool-abuse` | **Tool call triggered by voice.** A spoken instruction, including one from the background, triggers a tool call the caller should not be able to cause. | If spoken requests can trigger tools. | LLM06:2025 | ASI02 | AML.T0053 | custom probe: No benchmark exists. Script spoken requests for each tool that changes something. |
| `voice-transcript-gap` | **Guardrail sees the transcript, the model hears the audio.** Safeguards that read a transcript miss what transcription drops or alters. | If any safeguard works on a transcript. | — | — | — | custom probe: No benchmark exists. Compare guardrail verdicts on transcripts with the model's behaviour on the audio for the same recordings. |
| `voice-barge-in` | **Interruption and turn-taking manipulation.** Interrupting, overlapping or timing speech changes what the model accepts. | Realtime turn-taking is part of the attack surface. | — | — | — | custom probe: No benchmark exists. Script interruptions at the points where the call flow confirms an action. |
| `voice-caller-spoofing` | **Caller identity taken on trust.** Caller ID, signalling headers or a familiar-sounding voice are treated as authentication. | Voice is not authentication. | — | — | AML.T0073, AML.T0088 | design review: Review what the call flow uses to establish who is speaking. |
| `voice-cloning-misuse` | **Voice output used to impersonate a person.** Generated speech imitates a real person's voice. | If the model can produce arbitrary voices. | — | — | AML.T0088, AML.T0052.001 | design review: Review which voices can be produced and the vendor's stated restrictions. |
| `harmful-assistance` | **Assistance with a harmful request.** The model helps with a harmful request that is asked plainly, with no trick: for example operational help with an intrusion. | The text baseline the audio channel is compared with. | — | — | — | custom probe: Write a small set of requests that matter in this deployment and their benign twins. |
| `over-refusal` | **Over-refusal of legitimate work.** Legitimate requests are refused or blocked. This is the cost side of every safeguard: a refusal rate on harmful requests is never read without it. | Legitimate callers refused, including by accent or noise. | — | — | — | custom probe: Collect legitimate requests from the deployment that look risky and count refusals. |
| `prompt-injection` | **Prompt injection through input or content.** Text in the user's input, or in content the model is asked to process, overrides the instructions the system gave it. | Through any text or documents the voice agent is given. | LLM01:2025 | — | AML.T0051, AML.T0051.000, AML.T0051.001 | custom probe: Plant instructions in each untrusted input channel listed in review.json and score whether they are followed. |
| `system-prompt-leak` | **System prompt disclosure.** The system prompt or other configuration is revealed, exposing rules, internal details or secrets that were placed in it. | Spoken extraction of the agent's instructions. | LLM07:2025 | — | AML.T0069.002, AML.T0085.003 | custom probe: Run extraction prompts against the deployed system prompt; separately, read the prompt for secrets that should not be there. |
| `data-leakage` | **Sensitive data leaves through output or a tool.** Secrets, personal data or another user's data that are in the context, in memory or reachable by a tool appear in a response, in rendered content or in a tool call to an outside destination. | Account data read aloud to the wrong caller. | LLM02:2025 | — | AML.T0086, AML.T0136, AML.T0077 | custom probe: Seed the context with canary values and test each route out: the reply, rendered links or images, and each tool that can send data. |
| `unbounded-consumption` | **Unbounded cost or resource use.** Requests, loops or tool calls drive cost or load without a cap. | Realtime sessions bill by the minute. | LLM10:2025 | — | AML.T0034, AML.T0029 | design review: Review rate limits, spend caps, context and step limits as configured. |
| `data-retention-hosting` | **Retention, training use and hosting of submitted data.** Prompts, outputs, files or audio are kept, used for training, or processed in a place or by a party the organisation has not accepted. | Recordings and transcripts. | — | — | — | design review: Read the contract and the vendor's data terms; record what was signed, not what the public page says. |
| `version-drift` | **The thing reviewed is not the thing running later.** An alias moves to a new model, the harness updates itself, or outputs are not reproducible, so results stop describing the deployment. | Realtime model aliases. | — | — | — | design review: Record the pinned identifiers, how updates arrive, and who is told. |

## What the template does not cover

The list is a starting point for this subject type. Threats that come from the particular deployment (its data, its users, its integrations) are added by the reviewer. The template names no controls.

---
Generated by `scripts/render_templates.py` from `threats.json` and `templates.json`. Edit the JSON, then re-run the script.
