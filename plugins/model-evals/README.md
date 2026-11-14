# model-evals

Evaluate a model release, open-weights or frontier.

| Skill | What it does |
|---|---|
| [`model-benchmark`](skills/model-benchmark/SKILL.md) | Run a fixed suite of security benchmarks, one per risk dimension, on the same seeded samples for every model, and report which differences are larger than the noise. |

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
