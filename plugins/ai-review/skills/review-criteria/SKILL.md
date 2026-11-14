---
name: review-criteria
description: >-
  Fifth stage of a guided AI security review. Walks an organisation through writing its
  own acceptance criteria into criteria.json. For each measured dimension it explains what
  the number means, how wide its interval is at the depth run, and what each kind of error
  costs in this deployment, and offers the organisation's own earlier results as reference
  points. Records who set each criterion, when, and whether results for the subject had
  been seen. Use before results are read where possible, and before review-report. Never
  proposes a value: the shipped template is empty and the tool has no defaults.
license: MIT
compatibility: "Requires python>=3.10 (standard library only). No network, no API keys."
---

# review-criteria — the organisation writes its own criteria

You are running this skill for an organisation that must decide what it will accept from
an AI capability. Your job is to make sure the people deciding understand each number
well enough to choose, and that their choice is recorded with who made it and when.

**You never propose a value.** Not a number, not a range, not "most teams use", not a
rounded version of a reference point, not a yes when asked "is that reasonable?". If asked
for a number, say that this repo measures and the organisation decides, and return to the
three things below. The same holds for qualitative criteria: you may ask what would make
them stop a rollout; you do not answer it.

## What the reviewer supplies

- `test-plan.json` from `review-threat-model`: the dimensions that will be or were
  measured, and at what depth.
- `review.json`: what failure means in this deployment.
- **The people who own the decision**, or someone speaking for them. Criteria set by the
  reviewer alone are recorded as set by the reviewer.
- Experiment folders for things the organisation already runs and accepts (another model,
  the current version, the same app without the new feature), if any exist under its
  `.evals/`. These are the reference points.
- Whether anyone setting criteria has already seen results for the subject.

## What gets written

`criteria.json`, next to `review.json`. It belongs to the organisation. Shape:

| Field | Meaning |
|---|---|
| `criteria[].id`, `dimension` | A label and what is measured |
| `criteria[].measure` | `{skill, benchmark, metric, arm}`: which result the criterion is read against |
| `criteria[].statement` | The criterion in the organisation's own words |
| `criteria[].bound` | `{type, value, applies_to, reference}`; `type` is `at_least`, `at_most`, `no_worse_than_reference` or `qualitative` |
| `criteria[].error_costs` | `{if_too_lenient, if_too_strict}`: what each error costs here, as the organisation put it |
| `criteria[].set_by`, `set_on` | Who set it and when |
| `criteria[].set_relative_to_results` | `before` or `after` results for this subject were seen |
| `criteria[].rationale` | Why, in the organisation's words |
| `no_criterion[]` | Dimensions the organisation decided to set no criterion for, with reason and who decided |

`bound.applies_to` says where a numeric bound is read: on the measured rate
(`point_estimate`) or on one end of its 95% interval (`interval_lower`,
`interval_upper`). The organisation chooses; the difference matters most at shallow depth.

## Steps

### 1. Establish timing first
Ask: has anyone who will set criteria seen results for this subject? Criteria chosen after
seeing the result are weaker evidence than criteria chosen before, because the bar can be
placed just under what was observed. Neither is forbidden; both are recorded.

- Nobody has: build the worksheet without the subject's results (the default).
- Somebody has: every criterion they set is recorded `--timing after`.

### 2. Start the file and the worksheet
```
python scripts/criteria.py init --out criteria.json --review review.json
python scripts/criteria.py worksheet --plan test-plan.json --review review.json \
    --reference <experiment folder of something already accepted> ... \
    --subject <the subject's experiment folders, if already run> \
    --out criteria-worksheet.md
```
`worksheet` hides the subject's results unless `--show-subject-results` is given. With
`--subject` and no flag it uses only the number of tests actually run, to state the
interval width.

### 3. Walk through each dimension
For each dimension in the worksheet, in this order:

1. **What the number means.** Read out what the rate counts and which direction is better
   for the defender. Several benchmarks report a metric called "accuracy" that is an
   attack-success rate. Read the caveats: a number that is only meaningful beside another
   (refusal beside over-refusal, security beside task completion) needs both dimensions
   considered together.
2. **How wide the interval is.** Read out the half-width at the number of tests run. A
   bound closer to the measured rate than that width cannot be distinguished from it. The
   organisation either accepts that, asks for a deeper run, or states which end of the
   interval its bound is read on.
3. **What each error costs here.** Ask both questions and write down the answers:
   what happens in this deployment if the criterion is too lenient and a bad result gets
   through; what happens if it is too strict and a good-enough result blocks the rollout
   or pushes safeguards into refusing legitimate work. Use the failure impact from
   `review.json`. The two costs are rarely equal, and which is larger is the
   organisation's judgement.
4. **Their own reference points.** Show the organisation's earlier results for the same
   benchmark, with intervals. Say what they are: results for things it already runs. Say
   what they are not: a recommendation. Check they were run at the same depth and seed
   and under a comparable context; if not, say they are not comparable.
5. **Ask for the criterion.** The organisation states it. Options to offer by type, never
   by value: a bound on the rate; "no worse than" one of its own reference results; a
   qualitative statement; or no criterion for this dimension, with the reason.

If there is no reference point, say so. The organisation is then choosing with nothing of
its own to compare against; running the same benchmark on something it already accepts
would give one.

### 4. Record each criterion
```
python scripts/criteria.py add --file criteria.json --id C1 \
    --dimension "<what is measured>" --skill <skill> --benchmark <benchmark id> \
    --statement "<the organisation's words>" \
    --bound-type no_worse_than_reference --reference-label "<their earlier result>" \
    --set-by "<name, role>" --timing before \
    --if-too-lenient "<their answer>" --if-too-strict "<their answer>"
```
For a numeric bound use `--bound-type at_least|at_most --value <their number>
--applies-to point_estimate|interval_lower|interval_upper`. `--value` has no default and
`--timing` is required. To record that no criterion is set:
```
python scripts/criteria.py decline --file criteria.json --dimension "<...>" \
    --reason "<their reason>" --decided-by "<name, role>"
```

### 5. Validate
```
python scripts/criteria.py validate criteria.json --evals .evals
```
Errors: a criterion without an author, a date, a before/after answer, a statement, a
measure, or (for numeric bounds) a number and where it is read. Warnings: criteria set
after results; missing error costs; a `before` criterion dated later than an experiment
for the same skill, which the organisation should confirm.

### 6. Hand over
Read back each criterion with who set it and its timing, and the dimensions with none.
`review-report` places the criteria beside the results. It does not say whether they are
met; that statement is the organisation's.

## Saying what was not assessed

- A measured dimension with no criterion and no `no_criterion` entry is listed in the
  report as "measured, with no criterion set".
- Threats with no measurement (custom probe, design review, uncovered) have no number. The
  organisation may state a qualitative criterion for them or decline; either is recorded.
- If the people who own the decision were not present, say so and record `set_by`
  truthfully. Do not attribute a criterion to someone who did not set it.

## Smoke test

No keys, no network. From this skill's directory:
```
python scripts/criteria.py validate criteria.template.json
python scripts/criteria.py validate examples/criteria.example.json
```
Expected: `0 criteria, 0 error(s), 1 warning(s)` for the empty template (the warning says
it is empty), then `2 criteria, 0 error(s), 1 warning(s)` for the example (one criterion
was set after results). The example is fictional and holds no numeric bound: one
criterion is relative to the organisation's own reference, one is qualitative.

## Notes

- `criteria.template.json` ships empty. A test fails if it, or the bundled example,
  ever contains a numeric criterion value.
- The worksheet's interval widths are 95% Wilson half-widths computed from the number of
  tests, at measured rates near 50%, 80% and 95%. They describe measurement precision.
  They are not candidate bounds.
- `validate` checks that a criterion is completely recorded. It does not check that it is
  sensible, and it never compares a criterion with a result.
- `scripts/expread.py` reads experiment folders; the same file ships in `review-report`.
- **Not verified**
  - The walkthrough was not run with a real organisation's decision-makers.
  - Reference points are matched by benchmark id across experiment folders; whether two
    runs used the same depth and seed is left for the reviewer to check in the summaries.
  - Result files from measurement skills other than the shapes exercised in the tests
    (the shared Inspect runner's rows; nested objects with `rate`, `n` and `ci95`).
