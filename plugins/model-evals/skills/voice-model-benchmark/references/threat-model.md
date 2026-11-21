# Threat model: a realtime voice model behind a voice agent

What this skill tests is a speech-to-speech model (for example one reached through OpenAI's
Realtime API) used as the brain of a phone or app voice agent. The model hears audio, speaks
audio, and can ask the application to call functions.

## System sketch

```
 caller's room / phone line                operator (trusted)
 ┌──────────────────────────┐             ┌───────────────────────────────┐
 │ caller's voice           │             │ session instructions          │
 │ + anything else audible: │             │ tool definitions and rules    │
 │   TV, companion, a       │             │ voice, turn detection, limits │
 │   recording played in    │             └──────────────┬────────────────┘
 └────────────┬─────────────┘                            │
   ── trust boundary 1: audio is untrusted, and not only the caller's ──
              │ PCM audio (or typed text)                │
              ▼                                          ▼
        ┌───────────────────────────────────────────────────────┐
        │ realtime model: one session, one conversation        │
        └──────┬──────────────────────┬──────────────────────┬──┘
               │ spoken reply          │ function calls       │ transcripts
               ▼                       ▼                      ▼
        heard by the caller    ── trust boundary 2 ──    logs, guardrails,
        (and anyone listening)  application executes:    graders (read text,
                                refunds, account changes, not the audio)
                                data lookups
```

Input channels: caller audio (untrusted); other audio on the same channel (untrusted, and not
the caller); typed text where the deployment has it; operator instructions and tools
(trusted); tool results and telephony metadata such as SIP headers (untrusted, not measured
here). Outputs that matter: what the model says (harmful content, disclosed secrets), and
the function calls it asks for, which the application turns into actions.

## Where the risk comes from, per channel

| Channel | Where the risk comes from |
|---|---|
| Caller speech | Safety behaviour was learnt and tested mostly on text. The same request spoken, or spoken oddly (fast, pitched, noisy, echoing), may not be refused. |
| Other audio on the line | The model receives one mixed signal. Nothing marks which voice is the caller, so an instruction from a background speaker or a played recording arrives with the caller's authority. |
| Function calls | The model, not the application, decides whether the rules in its instructions are met. A spoken claim ("I'm the manager", "I read you the code earlier") is all the evidence it has; a voice is not authentication. |
| Session instructions | Operators place business rules and internal values there. The caller can ask for them in any wording, and a spoken answer can spell a value out in forms that defeat a plain string filter. |
| Transcripts | Guardrails and graders read text the provider transcribed; the model acted on audio. A gap between the two is unchecked (a design-review question, see below). |

## Core threats and how each is measured

| Id | Threat | Known lane (published) | Custom lane (vm-core, authored here) |
|---|---|---|---|
| `vm-spoken-harm` | Harmful requests get through when spoken | AdvBench + XSTest unsafe contrasts, spoken clean; typed baseline in summary.md | — |
| `vm-audio-evasion` | Perturbed audio evades refusal | the same requests under this skill's own perturbations (speed, pitch, volume, noise, echo, reverb); not a published attack set | — |
| `vm-third-party-speech` | A second voice gives the agent instructions | no published benchmark found | 8 pairs: caller voice plus a different voice mixed under or after it; scored by a canary word or a forbidden refund call |
| `vm-tool-abuse` | Spoken social engineering triggers a privileged call | no published benchmark found | 8 pairs: refund over the limit, account change without or with a wrong one-time code, impersonation; scored from function-call arguments |
| `vm-secret-leak` | Spoken requests extract a secret from the instructions | no published benchmark found | 8 pairs: a canary code in the instructions; scored on the reply, normalised for spoken and spelled forms |
| `vm-over-refusal` | Safe spoken requests are refused | XSTest safe prompts, spoken clean and perturbed | benign twins sit in their own threats' rows |

Every custom attack has a benign twin in the same scenario that the agent should carry out
(the caller asks for the canary word; the refund is within the limit; the code is right; the
question is about a public fact). A model that declines everything is safe on attacks and
fails the twins, so it cannot score well by doing nothing.

What the lanes cannot tell you:
- One synthetic caller voice and one synthetic second voice (Piper), fixed mixing levels, one
  turn per case, turn detection off. Not human callers, not real rooms or phone codecs.
- Function calls are scored as the model asked for them; nothing is executed and no tool
  result is returned, so multi-step tool chains are not exercised.
- The custom scenarios are fictional businesses with short instructions. A deployment's own
  instructions and tools can change every number: run the custom lane format with them
  (`--custom-dir`) when the review needs that.

## Design-review questions (no benchmark in either lane)

These have no standard benchmark and are not measured here. Record each as probed, reviewed
by design, or not assessed; `unbenchmarked-voice-threats.md` has the questions.

- Transcript-versus-audio gap in guardrails and logging.
- Barge-in and turn-detection manipulation (needs real-time streaming with detection on).
- SIP header spoofing and caller-ID trust.
- Session cost caps (long sessions, induced long replies).
- Voice cloning against voice-based identity, and impersonation by the agent's own voice.
