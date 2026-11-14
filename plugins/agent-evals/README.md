# agent-evals

Evaluate an AI agent and the features switched on for it.

| Skill | What it does |
|---|---|
| [`agent-feature-review`](skills/agent-feature-review/SKILL.md) | Guided review of an agent feature: computer use, persistent memory, connectors/MCP, code execution, file search, multi-agent, background agents. |

`agent-misuse-benchmark` (will a model inside a coding harness carry out offensive work when
asked) is planned for this plugin but not built.

## Install

The plugin follows [Agent Plugins 1.0.0](https://agent-plugins.org/specification): a root
`plugin.json` and one folder per skill under `skills/`. Any client that loads Agent Plugins can
load this directory.

Claude Code:

```
/plugin marketplace add wtcooper/ai-security-evals
/plugin install agent-evals@ai-security-evals
```

Each skill is also self-contained: copying its folder into any agent's skills directory works.
