# tools — maintainer build layer (not a distributed skill)

The skills are **self-contained** — each ships its own `lib/` (vendored runtime code)
and `corpus/` (prebuilt). `tools/` is the **single source of truth** those copies come
from, plus the corpus builder and unit tests. End users never install `tools/`.

| Path | What |
|---|---|
| `lib/status_policy.js`, `status_policy.py` | canonical body-first response classifier (JS + Python) |
| `lib/transform_response.js` | canonical promptfoo transformResponse for the app skills |
| `lib/summarize.py` | canonical metrics/F1/histogram summarizer |
| `build_corpus.py`, `m2s.py` | corpus builder + M2S (multi-turn→single-turn) flattening |
| `m2s_strategies.py` | our own multi-turn attack scaffolds (crescendo/actor/puzzler/decomposition/payload-split/cipher/leak/override), all domains, cited |
| `corpus/sources/` | vendored datasets (AdvBench, CyberSecEval, XSTest, PromptInject, **SafeMTData**) |
| `tests/` | unit tests for everything above (run via `scripts/run_tests.sh`) |
| `sync_skills.sh` | vendors `lib/*` + rebuilds the prebuilt corpus into each skill |

## Workflow
Edit a lib or the corpus **here**, then vendor it into the skills:
```bash
bash tools/sync_skills.sh        # copies lib/* + builds corpus into each skill
```
CI runs this and `git diff --exit-code`, so the committed skill copies can never drift
from `tools/`.

## Corpus
```bash
python tools/build_corpus.py --tier full                         # app-eval (rubric)
python tools/build_corpus.py --tier full --assert guardrail      # control-isolate
python tools/build_corpus.py --with-mhj                          # add MHJ (local-only)
```
Bundled multi-turn = **our own generated scaffolds** (`m2s_strategies.py`, all domains,
cited) + **SafeMTData Attack_600 (MIT)**, flattened via M2S. Add a strategy by writing a
`s_<name>(seed)` turn-template + registering it in `STRATEGIES`; add a domain seed in
`SEEDS`. MHJ is CC-BY-NC (non-commercial) — opt-in, never bundled. M2S is dataset-agnostic:
`m2s.flatten(turns, template)` works on any ordered turn-list. See
`corpus/sources/NOTICE` for per-source licenses.
