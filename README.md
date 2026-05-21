# ai-security-evals

A repository of distributable Claude Code skills for evaluating AI security defenses.

Each skill is a self-contained step-by-step runbook that Claude executes interactively — gather requirements, set up configs, run the experiment, and analyze results — backed by a Python harness in the same directory.

## Skills

| Skill | What it does |
|---|---|
| [`ai-guardrail-eval`](skills/ai-guardrail-eval/) | A/B/C-test AI safety defenses (guardrails, prompt-injection filters, jailbreak classifiers, refusal-tuning policies, custom in-house classifiers, foundation-model baseline) against a static peer-reviewed adversarial+benign benchmark corpus. Ships with a local LiteLLM proxy and mock models so the full pipeline can be verified with zero API keys. |

## Repository layout

```
ai-security-evals/
├── pyproject.toml            # uv-managed Python deps (Python 3.11+)
├── .python-version           # 3.11
├── local/                    # local LiteLLM proxy: config, start script, mock judge handler
├── skills/                   # one subdirectory per skill
│   └── ai-guardrail-eval/
│       ├── SKILL.md          # runbook frontmatter + step-by-step body
│       ├── README.md         # full reference docs
│       ├── RESEARCH.md       # design rationale
│       ├── run_eval.py       # CLI entry point
│       ├── guardrail_eval/   # Python package
│       ├── scripts/          # corpus builder
│       ├── data/             # bundled sample corpus (partial; rebuild for full)
│       ├── configs/          # example LiteLLM target configs
│       ├── examples/         # programmatic usage examples
│       └── tests/            # pytest unit tests
└── .evals/                   # working directory the skill creates on demand
    ├── corpus/               # staged corpora (bundled copy, rebuilt, or augmented)
    └── experiments/<name>/   # one subdirectory per experiment run
```

`.evals/` is **data only** — the skill reads and writes configs, staged corpora, and per-experiment outputs (`config.json`, `metrics.json`, `results.json`, `transcript.jsonl`) there. No logic, no docs, no source code lives in this directory; the skill creates the subdirectories on demand and you can delete anything in `.evals/` without losing reproducible state.

It is intentionally **not** in `.gitignore` so Claude can read prior runs across sessions, but do not commit corpora containing gated datasets (MHJ, AgentHarm) — those require accepting a HuggingFace access agreement and are not redistributable. The bundled `skills/ai-guardrail-eval/data/corpus_v1.json` contains only sources with permissive redistribution licenses.

## Quick start

```bash
# 1. Set up the environment (Python 3.11+)
uv sync

# (Optional) Copy the env template and edit if you're using real upstream
# models or guardrails. Defaults work for the bundled mock proxy.
cp env.example .env.local && $EDITOR .env.local

# 2. Start the local LiteLLM proxy (mock models, no API keys needed)
bash local/start_proxy.sh &

# 3. Run the skill — Claude Code picks up SKILL.md automatically
#    Or invoke the CLI directly:
LITELLM_BASE_URL=http://localhost:4000 \
LITELLM_API_KEY=sk-mock \
JUDGE_MODEL=mock-judge \
uv run python skills/ai-guardrail-eval/run_eval.py \
    --guardrail none \
    --model mock-target-refusal \
    --tier smoke \
    --experiment-name smoke_baseline_test
```

## License

MIT. See [`LICENSE`](LICENSE). Bundled benchmark datasets retain their original licenses (per-case attribution in `corpus_v1.json`).
