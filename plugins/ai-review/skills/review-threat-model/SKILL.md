---
name: review-threat-model
description: >-
  Third stage of a guided AI security review. Produces the threat model for the subject
  type in review.json (model, agent in a harness, app, decision model, voice model, image
  model, agent feature) with OWASP LLM Top 10 2025, OWASP Agentic Top 10 and MITRE ATLAS
  ids where verified, and a test plan that sorts every threat into: covered by a
  catalogued benchmark (skill, benchmark, depth), needs a custom probe, design review
  only, or uncovered. Use after review-scope and before running any measurement skill.
  Names what to measure; prescribes no controls and sets no acceptance criteria.
license: MIT
compatibility: "Requires python>=3.10 (standard library only). No network, no API keys."
---

# review-threat-model — threats for this subject, and what can test them

You are running this skill for a reviewer who has a validated `review.json`. This stage
answers two questions: which threats apply to this kind of subject in this deployment,
and for each one, what in this repo can measure it. The second answer is often "nothing",
and saying so is part of the output.

This skill does not recommend controls, mitigations or acceptance criteria. Where a threat
has no benchmark it says how the threat could be probed or what to examine, not what to
build to stop it.

## What the reviewer supplies

- `review.json` from `review-scope`, validated. The script reads `subject.type`,
  `subject.feature`, `subject.weights.open`, `context.tools` and `input_channels`.
- Knowledge of the deployment, to confirm each threat applies and to add threats the
  template lacks.
- The depth to plan at (`smoke`, `standard`, `full` or a number), chosen against the time
  budget in `review.json`.

## What gets written

Next to `review.json`:

| File | Contents |
|---|---|
| `test-plan.json` | Every threat in the template with its framework ids, whether it applies, its route, the benchmarks planned (skill, id, depth, tests, model calls, interval width), and fields the reviewer fills in as the review proceeds (`status`, `owner`, `evidence_ids`) |
| `test-plan.md` | The same as a document: threat model table, then the test plan in four parts, then what is not applicable and what the plan does not do |

## Steps

### 1. Read the template for the subject type
Each `subject.type` has a threat template under `references/`:

| `subject.type` | Template |
|---|---|
| `model` | [references/model.md](references/model.md) |
| `agent` | [references/agent-in-harness.md](references/agent-in-harness.md) |
| `app` | [references/app.md](references/app.md) |
| `decision-model` | [references/decision-model.md](references/decision-model.md) |
| `voice-model` | [references/voice-model.md](references/voice-model.md) |
| `image-model` | [references/image-model.md](references/image-model.md) |
| `feature` | [references/feature.md](references/feature.md) (one list per feature kind) |

Each template opens with questions that subject type raises. Ask the reviewer any that
`review.json` does not already answer, and update `review.json` if the answer changes the
scope (a tool nobody listed, an input channel nobody thought of).

Framework ids appear in a template only where the id was checked against its primary
source; [references/framework-ids.md](references/framework-ids.md) lists them, the source
and the date. A `—` means no verified match was found, not that the frameworks are silent.

### 2. Build the plan skeleton
```
python scripts/plan.py --review review.json --depth standard
```
It prints the route counts, the runs it plans per skill with tests and model calls, and
any scope question `review.json` leaves open. Options: `--depth smoke|standard|full|N`,
`--out-dir DIR`, `--catalog FILE`, `--include-t2`.

How a threat gets its route:

| Route | When | What the plan records |
|---|---|---|
| `benchmark` | An entry in the catalogue covers the threat, applies to this subject type, has status `available`, and runs at tier T0 or T1 | Skill, benchmark id, depth, tests, model calls, judge need, tier, and the 95% interval half-width at that number of tests |
| `custom_probe` | The threat is measurable but nothing available covers it | How it could be probed; any planned or candidate benchmark that exists but is not runnable here today |
| `design_review` | The threat is assessed by reading a design, configuration or contract | What to examine |
| `uncovered` | Nothing here assesses it | Why |

Tier T2 benchmarks (supervised sandbox) are left out unless `--include-t2` is given.
Planned and candidate catalogue entries never count as coverage; they are listed beside
the threat as "exists elsewhere".

Benchmarks that measure a control the user supplies (a guardrail) rather than the subject
are never counted as coverage. The plan lists them under "Benchmarks for a control the
deployment relies on"; add one to the runs only if `context.safeguards` in `review.json`
includes that control.

For `decision-model`, `voice-model` and `image-model` subjects the plan names the core
benchmark for that subject type (`decision-model-benchmark`, `voice-model-benchmark`,
`image-generation-benchmark`): run it first, since its own threat model and two-lane
scorecard are the main evidence. For `feature` subjects it names the guided review skill
(`agent-feature-review`), which covers threats no benchmark measures. For image input to a
chat model, `vision-model-benchmark` is the core benchmark.

A threat the scope rules out stays in the plan with `applies: false` and the reason (for
example a tool threat when `context.tools` is `[]`). Where `review.json` does not settle
it, `applies` is `null` and the question is printed: settle it with the reviewer.

### 3. Go through the plan with the reviewer
Work down `test-plan.md`:

1. **Threat model table.** For each row: does it apply here, and why? Change `applies`
   and `applies_reason` in `test-plan.json` where the reviewer disagrees with the
   template. Add rows for threats specific to this deployment; give each a route.
2. **Benchmarks.** Read the interval column aloud. At `smoke` depth the interval is too
   wide to compare anything; say so before the reviewer picks it to save time. Several
   benchmarks have only a handful of cases whatever the depth.
3. **Subject-type caveat.** For an `agent` subject, `model-benchmark` runs against the
   bare model API. The plan says so; it is a baseline and does not establish behaviour
   inside the harness.
4. **Custom probes and design reviews.** Each needs an owner or an explicit decision not
   to do it. A probe nobody builds is an uncovered threat; move it there and say why.
5. **Uncovered.** Read the list back. These go into the report as not assessed.

Then re-run nothing: edit `test-plan.json` by hand from here on. Re-running `plan.py`
overwrites the reviewer's edits.

### 4. Hand over
Tell the reviewer which measurement skills the plan names, at what depth, and the total
tests and model calls. Each of those skills prints its own cost plan before it runs and
reads `review.json` for the context block. After each run, add a `self_run` row to
`evidence.jsonl` (`review-evidence`); after each design review, a `reviewed` row. The
report matches results to the plan by skill and benchmark id.

## Saying what was not assessed

- Every threat in the template is in the plan with a route. None is dropped for lack of a
  benchmark.
- `uncovered`, and any `custom_probe` or `design_review` nobody carries out, are reported
  by `review-report` under "Threats not covered".
- A benchmark covers a threat on a public test set. The plan says this in its closing
  section; do not let "covered by a catalogued benchmark" be read as "not a risk here".
- The template is a starting list for the subject type. If the reviewer adds nothing, say
  that the plan contains template threats only.

## Smoke test

No keys, no network. From this skill's directory:
```
T=$(mktemp -d)
python scripts/plan.py --review examples/review.example.json --depth smoke --out-dir "$T"
python scripts/render_templates.py --check
```
Expected output (the counts move when the catalogue changes):
```
template model: 20 threats — 9 benchmark, 2 custom probe, 5 design review, 3 uncovered, 1 not applicable
  model-benchmark @ smoke: 10 benchmark(s), 218 tests, about 422 model calls
<T>/test-plan.json
<T>/test-plan.md
```
and exit code 0 from the template check. The example is a fictional `model` subject with
no tools, so `agent-goal-hijack` is listed as not applicable.

## Files

| Path | Purpose |
|---|---|
| `scripts/plan.py` | Builds `test-plan.json` and `test-plan.md` |
| `scripts/render_templates.py` | Renders `references/*.md` from the JSON below; `--check` fails if they are stale |
| `examples/review.example.json` | A fictional `model` profile for the smoke test |
| `references/threats.json` | Threat registry: id, description, verified framework ids, route when no benchmark is available |
| `references/templates.json` | Which threats each subject type gets, and why |
| `references/frameworks.json` | The framework ids that were verified, with source and date |
| `catalog.json` | Copy of the repo's benchmark catalogue (which benchmark covers which threat) |
| `lib/evalkit.py` | Vendored: depth names and the Wilson interval |

## Notes

- `catalog.json` is a copy of the repository's catalogue. Its `verified` flag says whether
  an entry's size, licence, judge and sandbox facts were read at a primary source; the
  plan prints it per benchmark. Threat coverage is the catalogue's judgement.
- Which threat an OWASP or ATLAS id is attached to is this skill's reading of the
  framework text. Only the existence and title of each id were verified.
- The plan sets depth for every benchmark from one `--depth`. Change it per benchmark in
  `test-plan.json` if the time budget needs it; `at_depth` holds the cost at each depth.
- **Not verified**
  - The templates were not reviewed by practitioners for each subject type; they were
    written from the design notes, the decision-model research note and the three
    frameworks.
  - The full text of the OWASP Top 10 for Agentic Applications (the PDF sits behind a
    download form); ids and short titles were read on the publisher's own pages.
  - Whether catalogue entries marked `planned` have since become runnable.
