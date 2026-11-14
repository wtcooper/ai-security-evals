# defense-evals

Evaluate how well a defence works. The defence always comes from you; these skills only measure it.

| Skill | What it does |
|---|---|
| [`guardrail-benchmark`](skills/guardrail-benchmark/SKILL.md) | Direct mode scores a guardrail's own verdict on a labelled corpus. In-line mode runs benchmarks with the same model behind each guardrail and reports risk removed beside over-blocking. |
| [`coding-guidance-benchmark`](skills/coding-guidance-benchmark/SKILL.md) | A/B test of anything placed in front of a coding agent (a skill, rules file, hook or MCP server), scored on BaxBench for correct and secure code. |
| [`security-tool-benchmark`](skills/security-tool-benchmark/SKILL.md) | Compare security tools against targets with known answers: code scanners, scanners of skills / MCP servers / model files, and pentest tools. |

## Install

The plugin follows [Agent Plugins 1.0.0](https://agent-plugins.org/specification): a root
`plugin.json` and one folder per skill under `skills/`. Any client that loads Agent Plugins can
load this directory.

Claude Code:

```
/plugin marketplace add wtcooper/ai-security-evals
/plugin install defense-evals@ai-security-evals
```

Each skill is also self-contained: copying its folder into any agent's skills directory works.
