# ai-review

Guided security review of an AI capability. These skills scope the review, gather evidence, model the threats, help your organisation write its own acceptance criteria, and compile the report. They measure and record; they never decide.

| Skill | What it does |
|---|---|
| [`review-scope`](skills/review-scope/SKILL.md) | Interview the requester and write `review.json`: what is being enabled, where, with what data and permissions. |
| [`review-evidence`](skills/review-evidence/SKILL.md) | Harvest vendor cards, published scores and documented limits, each with its source and provenance. Includes the open-weights scan harvest. |
| [`review-threat-model`](skills/review-threat-model/SKILL.md) | Threats for this subject type, and a test plan that sorts each threat into: covered by a catalogued benchmark, needs a custom probe, design review only, or uncovered. |
| [`review-criteria`](skills/review-criteria/SKILL.md) | Walk the organisation through writing its own acceptance criteria. Never proposes a value; the shipped template is empty. |
| [`review-report`](skills/review-report/SKILL.md) | Compile evidence, results (validity flags first) and uncovered threats. Shows your criteria beside results only if you supplied them; decision fields are left blank. |

## Install

The plugin follows [Agent Plugins 1.0.0](https://agent-plugins.org/specification): a root
`plugin.json` and one folder per skill under `skills/`. Any client that loads Agent Plugins can
load this directory.

Claude Code:

```
/plugin marketplace add wtcooper/ai-security-evals
/plugin install ai-review@ai-security-evals
```

Each skill is also self-contained: copying its folder into any agent's skills directory works.
