# Planted-weakness manifests for the ai-evals / ai-redteam meta-eval (design §8)

The `ai-evals` / `ai-redteam` plugins wrap Promptfoo, which `app-eval` / `app-redteam` /
`control-bench` already evaluate directly. What is untested is the plugins' **profile → config**
step. This dir holds a `<target>.planted.jsonl` per known-vulnerable LLM app: one row per planted
weakness that a good generated config should surface.

Row: `{"id": "pw-1", "target": "dvaa", "category": "prompt_injection|tool_abuse|data_leakage|...",
        "where": "system prompt | RAG doc | tool <name>", "canary": "regex the eval output must
        contain to count as surfaced", "severity": "high", "note": "..."}`

Design: point `security-profile` + `eval-security` + `redteam-app` at the target (DVAA, AIGoat,
sdlc `testbed/`, or `targets/proxy` with planted canary secrets), k=3, and score whether the
generated config surfaces each planted weakness (recall on the planted list) + the false-positive
rate, and whether a config written from a *thin* profile does worse than from a full one (the
profile is the lever). Score with `tools/lib/evalstats.py` (recall = Wilson CI on planted-found).
No new harness — just the manifest here + the existing app-eval/app-redteam skills.
