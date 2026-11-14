# model-evals

Evaluate a model, reached through whatever API it has.

| Skill | What it does |
|---|---|
| [`model-benchmark`](skills/model-benchmark/SKILL.md) | A fixed suite of Inspect benchmarks, one per risk dimension, on the same seeded samples for every model. Includes a vision-input profile. |
| [`decision-model-benchmark`](skills/decision-model-benchmark/SKILL.md) | Decision and classification endpoints: fail-open and fail-closed rates on labelled policy cases, and how easily a decision is flipped. |
| [`voice-model-benchmark`](skills/voice-model-benchmark/SKILL.md) | The same prompts as text and as synthesised speech, with audio perturbations, against a realtime voice model. |
| [`image-model-review`](skills/image-model-review/SKILL.md) | Guided review of an image-generation model, with a provenance (C2PA) check and a recorder for your own probe set. |

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
