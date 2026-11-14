---
name: review-report
description: >-
  Final stage of a guided AI security review. Compiles report.md from review.json,
  evidence.jsonl, the experiment folders the measurement skills wrote under .evals/, the
  test plan, and criteria.json if the organisation wrote one. Sections: what was reviewed
  and in what context; evidence with provenance; results with each skill's validity flags
  surfaced first; threats not covered; the organisation's criteria beside the results
  (only when criteria.json exists); and decision, conditions and sign-off left blank for
  people. Use when the measurements a review planned are done. Compiles; never decides.
license: MIT
compatibility: "Requires python>=3.10 (standard library only). No network, no API keys."
---

# review-report — compile what was established, leave the decision blank

You are running this skill for a reviewer who must hand leadership the evidence for a
decision on an AI capability. The report arranges what the earlier stages recorded. It
adds no judgement of its own.

**You do not write a verdict.** Not in the report, not in your message to the reviewer,
not as a "summary recommendation". The decision, conditions and sign-off sections are
blank fields for the accountable people. If asked "so should we enable it?", say that the
report sets out what was measured and what was not, and the decision is theirs.

## What the reviewer supplies

| Input | From | If absent |
|---|---|---|
| `review.json` | `review-scope` | Required. The compiler stops. |
| `evidence.jsonl` | `review-evidence` | Section 2 says nothing was harvested and that this reads as not assessed |
| `.evals/<skill>/<label>_<date>/` | the measurement skills; each folder has `manifest.json` and `summary.md`, sometimes `summary.json` / `results.json` | Section 3 says nothing was measured |
| `test-plan.json` | `review-threat-model` | Section 4 says threat coverage cannot be stated |
| `criteria.json` | the organisation, with `review-criteria` | No criteria section at all; the report says none were supplied and none are implied |

Inputs not named on the command line are looked for next to `review.json`.

## What gets written

`report.md`, next to `review.json` (or `--out`). Sections, in this order:

1. **What was reviewed, and in what context** — subject, the deployment context, who
   controls each input channel, what it can do, what failure means, the time budget, what
   was excluded, and every scoping answer recorded as unknown.
2. **Evidence, with provenance** — absences first, then claims grouped by who
   established them: measured here, examined here, stated by the vendor, read from third
   parties.
3. **Results** — first one list, across all experiments, of everything to read before
   any number: rows that produced no result, validity flags the skills raised, and what
   the compiler itself noticed about a folder. Then each experiment: its flags again,
   then the skill's own summary, unedited.
4. **Threats not covered** — from the test plan: planned benchmarks with no result,
   probes and reviews nobody recorded, threats the plan leaves uncovered, threats ruled
   out or never confirmed at scoping; then a table of every threat and its state.
5. **The organisation's criteria beside the results** — only if `criteria.json` exists.
   Each criterion with who set it, when, before or after results, and the matching
   result beside it. The "Met?" column is empty.
6. **Decision**, **Conditions**, **Sign-off** — blank.

Then a list of the input files with their hashes and the experiment folders read.

## Steps

### 1. Check the inputs are the ones for this review
`.evals/` may hold experiments from other reviews. Either point `--evals` at a directory
that holds only this review's folders, or name each folder with `--exp` (repeatable).
Ask the reviewer if unsure; an experiment for another subject in this report is worse
than a missing one.

### 2. Compile
```
python scripts/compile_report.py --review review.json \
    [--evidence evidence.jsonl] [--evals .evals | --exp <folder> ...] \
    [--plan test-plan.json] [--criteria criteria.json] [--out report.md]
```
It prints how many evidence rows and experiments it read, how many experiments have
something to read first, and whether a plan and criteria were supplied.

### 3. Read the report before handing it over
Read these to the reviewer, in this order:

1. **Section 3, "Read before any number".** Every item. A row with no result is not a
   zero and not a pass. A validity flag says a measurement may not mean what it appears
   to (the judge could not grade, the agent rarely completed its task so its security
   score reflects not acting, the run was at smoke depth). The number is still shown.
   "Report check" items are the compiler's own: a summary that is missing, a manifest
   left unfinished, an experiment whose recorded context differs from `review.json`. A
   context difference means that result describes a different deployment.
2. **Section 4.** Everything listed there was not assessed. In the table, `measured`
   means a number exists on a public test set; it does not mean the threat is absent.
   `claims only` means the review rests on what a vendor or third party said.
3. **Section 2, "Looked for and not found".**
4. **Section 5**, if present: which criteria were set after results were seen, and any
   criterion with no matching result.

Fix inputs, not the report: if something is wrong or missing, correct `review.json`,
`evidence.jsonl` or the experiment folder and compile again. Do not edit `report.md` to
add interpretation.

### 4. Hand over
Give the reviewer the path. Say which sections people must fill in. Do not summarise the
report into a recommendation.

## How the compiler reads experiment folders

The measurement skills do not share one JSON shape, so `scripts/expread.py` looks for
three things wherever they sit in `summary.json` or `results.json`:

| It looks for | Recognised as |
|---|---|
| Validity flags | objects with a `flag` key in a list named `flags` or `validity_flags` |
| Rows with no result | objects with a `status` other than `ok` beside a `check` or `arm` |
| Metrics | objects with a numeric `value` or `rate` and a sample count or an interval |

When a folder has only `summary.md`, the lines under its own validity heading ("Read
first", "Validity flags" and similar) are quoted. When it has neither machine-readable
flags nor such a heading, the report says the skill did not state whether its numbers
can be trusted. The summary text itself is always included whole.

Criteria are matched to results by `measure.skill` plus whichever of `benchmark`,
`metric` and `arm` the criterion names.

## Saying what was not assessed

The report is built so that absence is printed, not skipped:

- no evidence file, no experiments, no plan: each is stated in its section;
- a planned benchmark that was not run, or ran without a score: listed in section 4;
- a threat with only an `absent` evidence row is `not assessed`, not `examined`;
- surfaces and data excluded at scoping are repeated at the end of section 4;
- no `criteria.json`: stated under the title, and no criteria section appears.

If the reviewer knows of something not assessed that no input records, add it to the
inputs (an `absent` evidence row, an `out_of_scope` entry) and recompile.

## Smoke test

No keys, no network. For this skill alone, from its directory:
```
python scripts/compile_report.py --review tests/fixtures/review.json \
    --evals tests/fixtures/evals --out "$(mktemp -d)/report.md"
```
Expected: `wrote …/report.md: 7 evidence row(s), 3 experiment(s) (3 with something to
read first), plan supplied, criteria supplied`. The fixtures are a fictional subject with
invented numbers.

For the whole plugin (scope-validate → evidence-append → plan → criteria-validate →
report), with the five `review-*` skills side by side as the plugin installs them:
```
bash tests/smoke.sh
```
It runs each stage's script on that stage's bundled example, compiles `report.md` in a
temporary directory, prints the report's section headings and ends with
`smoke ok: <path>`. Pass the directory holding the five skills as the first argument if
they are somewhere else, and an output directory as the second.

## Notes

- The compiler never computes whether a criterion is met and never orders results as
  good or bad. It counts, groups, copies and compares dates.
- Validity flags come from the measurement skills, with their own configurable limits.
  They are not acceptance thresholds and never remove a number from the report.
- The before/after note on criteria compares each criterion's `set_on` with the earliest
  `created` date among the experiments read. It is printed as a question to confirm, and
  the organisation's own record is shown unchanged.
- **Not verified**
  - Experiment folders written by a real run of any measurement skill: the fixtures were
    built with the shared Inspect runner's own helpers and by hand, with invented numbers.
  - `summary.json` shapes other than those in the tests (the shared Inspect runner; nested
    objects with `rate`, `n`, `ci95`; `validity_flags` lists at any depth).
  - Rendering of the report in any particular markdown viewer; tables use pipe syntax and
    `<br>` inside one cell.
