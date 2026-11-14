# app-evals

Evaluate an LLM application's endpoint.

| Skill | What it does |
|---|---|
| [`app-benchmark`](skills/app-benchmark/SKILL.md) | Send a fixed set of attack and benign prompts to your app and score how many it handles correctly (F1, recall, false-block rate, by technique). |
| [`app-redteam`](skills/app-redteam/SKILL.md) | Run multi-turn attacks that adapt to your app's replies, to find weaknesses a fixed test set misses. |

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
