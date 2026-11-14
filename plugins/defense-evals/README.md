# defense-evals

Evaluate how well a defence works. The defence itself always comes from you; these skills only measure it.

| Skill | What it does |
|---|---|
| [`control-isolate`](skills/control-isolate/SKILL.md) | Send labelled harmful and benign prompts straight to a guardrail API and score catch rate against false-block rate. |
| [`control-bench`](skills/control-bench/SKILL.md) | Run a standard model benchmark with a guardrail off and on, and report the risk it removed and what it cost in over-blocking. |
| [`control-codegen`](skills/control-codegen/SKILL.md) | Have a coding agent build an app with and without guidance in place, then score whether the code got more secure. |
| [`tool-codescan`](skills/tool-codescan/SKILL.md) | Compare code scanners on source code with known vulnerabilities. |
| [`tool-assetscan`](skills/tool-assetscan/SKILL.md) | Compare scanners of skills, MCP servers and model files on labelled malicious and benign samples. |
| [`tool-pentest`](skills/tool-pentest/SKILL.md) | Compare pentest tools against running vulnerable apps, counting only oracle-confirmed exploits. |

Planned renames (see `docs/plans/holistic-review-framework-proposal.md`): `control-isolate` and
`control-bench` merge into `guardrail-benchmark`; `control-codegen` becomes
`coding-guidance-benchmark`; the three `tool-*` skills merge into `security-tool-benchmark`.

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
