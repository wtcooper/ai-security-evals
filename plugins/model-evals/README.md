# model-evals

Evaluate a model, reached through whatever API it has.

| Skill | What it does |
|---|---|
| [`model-benchmark`](skills/model-benchmark/SKILL.md) | A fixed suite of Inspect benchmarks, one per risk dimension, on the same seeded samples for every model. For image input use `vision-model-benchmark`. |
| [`vision-model-benchmark`](skills/vision-model-benchmark/SKILL.md) | Models that read images: instructions hidden in images, secret extraction, tool hijack, harmful requests written as images, and over-refusal, on CyberSecEval 3, FigStep and a rendered core set. |
| [`decision-model-benchmark`](skills/decision-model-benchmark/SKILL.md) | Decision and classification endpoints: fail-open and fail-closed rates on labelled policy cases, and how easily a decision is flipped. |
| [`voice-model-benchmark`](skills/voice-model-benchmark/SKILL.md) | The same prompts as text and as synthesised speech, with audio perturbations, against a realtime voice model. |
| [`image-generation-benchmark`](skills/image-generation-benchmark/SKILL.md) | Image generation: phishing assets, forged documents, working QR payloads, likeness, justification bypass and provenance, measured on a small core set and the C2PA reference verifier. |

## Install

The plugin follows [Agent Plugins 1.0.0](https://agent-plugins.org/specification): a root
`plugin.json` and one folder per skill under `skills/`. Any client that loads Agent Plugins can
load this directory.

Claude Code:

```
/plugin marketplace add wtcooper/ai-security-evals
/plugin install model-evals@ai-security-evals
```

Each skill is also self-contained: copying its folder into any agent's skills directory works.
