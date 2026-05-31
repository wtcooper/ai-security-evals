# `_shared` — common components for the security-eval skills

Shared by `app-eval`, `app-redteam`, `control-isolate`, and `control-bench`.

| File | Purpose | Tests |
|---|---|---|
| `status_policy.js` | Single source of truth for response classification: `classify(status, json, text)` → `answer`/`block`/`error`/`ambiguous`, **body-signal first, status as a hint**. Recognizes vendor block bodies (`action:block`, `guardrail_name`, "content blocked", …) and infra errors (5xx/429/401/auth/quota/timeout). Required by both JS consumers so they never drift. | `tests/status_policy.test.cjs` |
| `transform_response.js` | promptfoo `transformResponse` for the app skills over `classify`: answer→text→judge; block→native `guardrails` + sentinel; error→throw (excluded); ambiguous→judge (default) or exclude (`GUARDRAIL_AMBIGUOUS_POLICY`). Emits `metadata.{httpStatus,statusClass}` for the histogram. | `tests/transform_response.test.cjs` |
| `m2s.py` | Multi-turn→single-turn flattening (`hyphenize`/`numberize`/`pythonize`, arXiv:2503.04856). | `tests/test_m2s.py` |
| `build_corpus.py` | Builds promptfoo test files from the vendored offline sources; adds MHJ→M2S harmful cases; dedups; stratified seeded tiers. | `tests/test_build_corpus.py` |
| `corpus/sources/` | Vendored, offline, license-clean datasets (PromptInject, AdvBench, CyberSecEval PI + FRR, XSTest, MHJ). | — |

## Corpus classes & metrics

Cases are tagged with a `metric:` so promptfoo aggregates per class:

- `Injection_Block`, `Harmful_Block`, `Leak_Block` — block rate = guardrail **recall** (higher = more secure).
- `Not_Over_Refused` — utility on the benign **negative class**; **FRR = 1 − this**.

Treating the defense as a binary classifier (benign = negative class), each skill's
`promptfooconfig.yaml` derives **precision / recall / F1** with promptfoo
`derivedMetrics` from these tags, so a defense that just refuses everything is
penalized on FRR. `metadata.technique_family` enables the per-family breakdown
(a defense strong on content harm but weak on `m2s_*` or `system_prompt_exfiltration`
has a gap that overall recall hides).

## Judge conventions (all skills)

- One `llm-rubric` per case (no shared rubric — promptfoo doesn't resolve per-case
  vars in `defaultTest` rubrics). Judge model pinned in `defaultTest.options.provider`.
- **Warn if judge model == target model.** No keyword-classifier fallback. Judge is
  label-blind (never sees harmful/benign label).

## Build

```bash
python skills/_shared/build_corpus.py --tier smoke   # ~30  (wiring/cost)
python skills/_shared/build_corpus.py --tier mid     # ~150 (regression)
python skills/_shared/build_corpus.py --tier full    # everything (default)
# write into a specific skill: --out skills/app-eval/corpus/promptfoo
```

MHJ (`corpus/sources/raw/mhj_multiturn.csv`) is research-only — confirm authorization
before redistributing a built corpus that includes the `mhj-m2s-*` cases.
