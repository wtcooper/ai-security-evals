# Benchmark catalogue

`benchmarks.json` is the single list of benchmarks this repo's skills can run or plan to
run, and the threats each one bears on. `review-threat-model` reads it to sort every
threat of a review into: covered by a catalogued benchmark, needs a custom probe, design
review only, or uncovered. "No catalogued benchmark exists" is a result the review
reports, not a gap to hide.

The catalogue describes benchmarks. It holds no scores, no thresholds and no advice on
what result is acceptable.

## Files

| File | Purpose |
|---|---|
| `benchmarks.json` | The catalogue. Edit this one. |
| `README.md` | This file. |
| `tests/test_catalog.py` | Cross-checks the catalogue against `model-benchmark`'s suite file, the threat registry, and the copy shipped inside `review-threat-model`. |

A skill cannot read files outside its own folder, so `review-threat-model` ships a copy at
`plugins/ai-review/skills/review-threat-model/catalog.json`. The test fails when the copy
differs from `benchmarks.json`. After editing the catalogue, copy it over (or let the sync
script do it once the copy is registered there).

## Entry fields

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Unique id. For `model-benchmark` it is the check id in its suite file. |
| `name` | string | Human-readable name. |
| `skill` | string | The skill that runs it, or would. |
| `status` | `available` / `planned` / `candidate` | `available`: a skill in this repo runs it today. `planned`: named in the framework proposal for a skill, or for a mode of a skill, that does not run it yet. `candidate`: named in research as usable; nothing is committed. Only `available` entries count as coverage in a test plan. |
| `subjects` | list | Review subject types it applies to: `model`, `agent`, `app`, `decision-model`, `voice-model`, `image-model`, `feature`. |
| `engine` | `inspect` / `promptfoo` / `pyrit` / `custom` | What executes it. |
| `threats` | list | Threat ids it bears on, from `review-threat-model`'s `references/threats.json`. The mapping is this catalogue's judgement, not a claim by the benchmark's authors. |
| `tier` | `T0` / `T1` / `T2` / null | Execution tier. T0: pure API calls. T1: in-memory tools or a no-egress container. T2: supervised sandbox, off by default. null: not known (candidates only). |
| `needs_judge` | true / false / null | Whether scoring needs a judge model. A judge is never the model under test. |
| `needs_sandbox` | true / false / null | Whether it needs a container or VM. |
| `calls_per_sample` | number / null | Model calls per test, counting subject, judge and any helper model. null: varies or not known. |
| `dataset_size` | number / null | Tests in the full set, as the skill runs it. |
| `licence` | string / null | Licence of the dataset or, where stated, the repository. null: not checked. |
| `verified` | true / false | See below. |
| `verified_from` | string / null | Where the verified facts were read, and when. |
| `source` | URL / null | Upstream home of the benchmark. null for sets bundled in a skill and for names with no source given. |
| `note` | string | What it measures, and its caveats. |

Entries seeded from `model-benchmark` also carry `dimension`, `metric_key`, `direction`,
`reads_as` and `profile`, copied from its suite file, and `subject_notes` (a caveat shown
when the benchmark is planned for that subject type).

`null` always means "not known". It never means "no" or "zero".

## What `verified` means

`verified: true` means every non-null value among `dataset_size`, `licence`,
`needs_judge`, `needs_sandbox` and `calls_per_sample` was read in one of two places:

1. `model-benchmark`'s suite file, which was itself checked against the installed
   `inspect_evals` package; or
2. a primary source that was opened and read (an upstream repository's LICENSE or README,
   the installed package's own metadata, the corpus files bundled in a skill), named in
   `verified_from`.

`verified: false` means at least one stated fact comes from the framework proposal, the
research note or prior knowledge, and nobody confirmed it. Treat every value in such an
entry as a lead to check, not as a fact.

`threats`, `tier`, `subjects` and `status` are this repo's own classification and are not
covered by `verified`.

## Adding or changing an entry

1. Read the fact at its primary source. If you cannot, leave the field `null` and keep
   `verified: false`.
2. Use threat ids that exist in the threat registry; the test rejects others.
3. A new check in `model-benchmark`'s suite file needs an entry with the same id; the
   test compares size, calls per sample, judge need, metric and direction.
4. Copy the file into `review-threat-model` and run `pytest catalog/tests -q`.

## Not catalogued

- **Target sets of `security-tool-benchmark`.** They measure a security tool (a scanner,
  a pentest tool) against known answers, not the AI capability under review. They belong
  here only if a review's subject is itself a security tool.
- **`guardrail-benchmark` in-line mode.** It re-runs `model-benchmark` checks with a
  guardrail off and on; the checks are already listed.
- **Benchmarks that elicit offensive capability in a sandbox** (`cve_bench`, `cybench`,
  `cybergym`, `threecb`). `model-benchmark` excludes them by design; they would be tier T2.

## Not verified

- Every entry with `verified: false`.
- Dataset licences where the entry says so in `licence` or `note` (for example the
  DecisionRobust and JALMBench datasets, hosted apart from their code).
- Whether a `planned` entry's skill has since started running it. `status` is set by
  hand.
- The `strong_reject` size: the suite file lists 313, the `eval.yaml` in `inspect_evals`
  0.29.0 lists 324. The entry keeps the suite's value and says so.
