# agent-evals

Evaluate an AI agent and the features switched on for it.

| Skill | What it does |
|---|---|
| [`agent-misuse-benchmark`](skills/agent-misuse-benchmark/SKILL.md) | **Scaffold.** Does a model inside an agent harness carry out tasks your policy says it must decline, and does it still complete the matched legitimate ones? You supply the scenarios, the harness module and the outcome scorer; the build guide says how. |
| [`agent-feature-review`](skills/agent-feature-review/SKILL.md) | Guided review of an agent feature: computer use, persistent memory, connectors/MCP, code execution, file search, multi-agent, background agents. |

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
