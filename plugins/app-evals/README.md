# app-evals

Evaluate an LLM application's endpoint.

| Skill | What it does |
|---|---|
| [`app-benchmark`](skills/app-benchmark/SKILL.md) | Send a bundled labelled corpus of attack and benign prompts to your app and score recall, false-block rate and attack success by technique. |
| [`app-redteam`](skills/app-redteam/SKILL.md) | Run multi-turn attacks that adapt to your app's replies, with repeats, to find weaknesses a fixed test set misses. |

## Install

The plugin follows [Agent Plugins 1.0.0](https://agent-plugins.org/specification): a root
`plugin.json` and one folder per skill under `skills/`. Any client that loads Agent Plugins can
load this directory.

Claude Code:

```
/plugin marketplace add wtcooper/ai-security-evals
/plugin install app-evals@ai-security-evals
```

Each skill is also self-contained: copying its folder into any agent's skills directory works.
