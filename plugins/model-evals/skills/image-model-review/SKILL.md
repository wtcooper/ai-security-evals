---
name: image-model-review
description: >-
  Guided security review of an image-generation model (and, briefly, video) when someone asks
  "can we enable this?" and no standardized benchmark answers it. Covers the security
  concerns rather than content safety: phishing and brand-impersonation assets, identity
  documents, QR and hidden payloads, likenesses of real people, editing of uploaded
  documents, and whether provenance marks (C2PA metadata, invisible watermarks) are present
  and survive ordinary handling. Produces a structured record: what the vendor publishes,
  what a hand-built probe set showed (counts with 95% intervals), what a C2PA marker check
  found, and every threat that was not assessed. Writes evidence.jsonl rows other review
  skills consume. It sets no bar and makes no recommendation; the decision is left to people.
  For a model that reads images use model-benchmark; for agent features use agent-feature-review.
license: MIT
compatibility: "Python 3.10+ standard library. Pillow is optional: without it the re-encode, resize, crop and screenshot transformations of the provenance check are skipped and recorded as not assessed. No API key and no network access are needed by the scripts."
---

# image-model-review — security review of an image-generation model

You are running this skill **on behalf of a reviewer** who must tell their organisation what
is known, and what is not, about an image-generation model before it is switched on. There
is no benchmark to run. You walk the reviewer through a threat template, collect what the
vendor publishes, help them record a small probe set they write themselves, check provenance
marks on real output files, and write the record.

Three rules hold throughout:

- **You measure and record. You do not decide.** No bar, no rating, no "approve". The
  decision block in the record is written empty.
- **You do not prescribe controls.** Record which safeguards are in place and which were
  examined. Do not suggest ones to add.
- **You do not write the probes.** The reviewer writes them against their own brands and
  use cases and keeps the prompts. Do not draft prompts designed to produce fraudulent or
  harmful images, and do not paste such prompts into any file this skill writes.

## What the reviewer supplies

| Input | Used for |
|---|---|
| The exact model, version, vendor, and the surface it will be used through (API, app, reseller) | everything; results apply to that surface only |
| Whether it accepts image uploads and whether it generates video | which threats apply |
| The deployment context: who prompts it, what they upload, where outputs go, safeguards in place | the `context` block of the record |
| Vendor documents: system or model card, usage policy, data-handling terms, API documentation | the evidence harvest |
| 50 to 100 probes they wrote and ran, as a CSV of outcomes | probe counts |
| Image files the model returned through the production route, unmodified | the provenance check |
| Optionally, the same files after their own handling paths (CMS, chat tool, email) | provenance survival on real paths |

Anything they cannot supply is recorded as not assessed. Do not fill gaps with assumptions.

## Steps

Work in a review folder. If this is part of a wider review, use that review's folder and
pass its `evidence.jsonl` with `--evidence`; otherwise create
`.evals/image-model-review/<label>_<date>/`. Below, `$R` is that folder.

### 1. Scope and threats

Read `references/threats.md` with the reviewer. For each of the thirteen threats ask
whether it applies to this deployment. A threat that does not apply (no video, no image
upload) goes under `not_applicable` **with the reason**. Do not drop threats silently.

### 2. Harvest vendor evidence

Follow `references/evidence-harvest.md`: fourteen items, each recorded as `found` (a claim in
your own words, the URL, the date), `absent` (you looked and it is not there, which is a
finding; say where you looked), or `not_checked`. Read the vendor's card for this exact model and version. Put the
answers in a JSON file shaped like `examples/review_answers.example.json`.

Questions to put to the reviewer while harvesting:
- Which surface did the vendor evaluate, and is it the one you will use?
- Were results reported with safeguards on only? Per category or in aggregate?
- Does the card say anything about fraud documents, brand assets, QR codes or likeness?
- What does it claim about provenance, and is there a detector you can use?
- Which safety settings can a customer change, and which will this deployment use?

### 3. Probe set (the reviewer writes it)

Give the reviewer `references/probe-set-template.md`: categories, ground rules, outcome
definitions. They write and run the probes and return a CSV of outcomes (no prompts). Then:

```
python scripts/record_probes.py outcomes.csv --out $R --subject "<model> via <surface>" --by variant
```

Reports produced / partial / blocked per category with 95% Wilson intervals, the share of
benign probes blocked, and the validity flag `small_n` for thin categories (`--min-n`
configurable; a validity flag, never a bar).

### 4. Provenance check

```
python scripts/provenance_check.py path/to/model_outputs/ --out $R --subject "<model> via <surface>" \
  [--pipeline cms=path/after_cms/]
```

Reports whether each JPEG, PNG or WebP carries an embedded C2PA manifest store, then
re-checks after `strip_metadata` (stdlib) and, with Pillow, `reencode`, `resize`, `crop`,
`screenshot`. Read `references/provenance.md` before interpreting it. Say this to the
reviewer in plain words:

- `present` means the container is there. It is not a validity check.
- **It cannot see an invisible watermark** such as SynthID. If the vendor offers a detector,
  the reviewer runs it and you record the result as a separate evidence row; otherwise the
  watermark is not assessed.
- Generic image tools drop embedded metadata, so expect the manifest to be gone after the
  built-in transformations. The `--pipeline` result on the organisation's real paths is
  usually the informative one.

### 5. Write the record

```
python scripts/record_review.py answers.json --out $R
```

It reads `$R/probe_summary.json` and `$R/provenance.json` if present and prints every threat
left not assessed. Read that list back to the reviewer and ask whether each gap is known and
intended.

## What is written, and where

All in `$R`:

| File | Contents |
|---|---|
| `image_review.json` / `image_review.md` | per threat: status (`evidence_recorded`, `not_assessed`, `not_applicable`), what it was recorded from, vendor evidence found and absent, probe counts, provenance results; the lists of what was not assessed; an empty decision block |
| `probe_summary.json` / `.md` | counts and intervals per category |
| `provenance.json` / `.md` | per file and in summary; what the check cannot detect |
| `evidence.jsonl` | one row per claim, appended; identical rows are not written twice |

Evidence rows follow the `review-evidence` skill's format, which owns it: `id` (assigned on
append), `claim`, `threats`, `source`, `captured`, `provenance` (`published` for the vendor's
own documents, `harvested` for third parties, `self_run` for the probe counts and the
provenance check, `reviewed` for what a person here examined), `note`, plus `absent`, `kind`
and `pointer`. Threat ids are this skill's own (`img-01` … `img-13`). If the review has a
test plan with its own threat ids, pass every script `--threat-map map.json`
(`{"img-05": ["<plan id>"], ...}`) so the rows are filed under the plan's ids.

`evidence_recorded` means something was written down about the threat. It does not mean the
threat is addressed.

## Stating what was not assessed

Say it in the report and to the reviewer, in these terms:

- **Threats with nothing recorded**: listed by id under "Not assessed", each with an evidence
  row beginning `Not assessed:` and marked `absent: true`.
- **Vendor material looked for and absent**: an evidence row beginning `Not found in the
  vendor's published material:`, marked `absent: true`, with where the reviewer looked.
  Absence of an evaluation is not evidence of a problem and not evidence of safety.
- **Harvest items not checked**: listed; nobody looked.
- **Invisible watermark**: always `Not assessed` by the script.
- **Manifest validity, other file formats, video files**: not checked by the script.
- **Probe counts**: a hand-built set judged by one reviewer on one surface on one day. Not a
  benchmark, not comparable across organisations.
- **Existing content-safety sets** such as I2P measure inappropriate imagery, not these
  concerns (`references/threats.md`). Do not cite them as coverage.

Hand the record on with the decision block empty.

## Smoke test (no key, no network, a few seconds)

```
python scripts/make_fixtures.py /tmp/imr-smoke/images
python scripts/provenance_check.py /tmp/imr-smoke/images --out /tmp/imr-smoke/review --subject "fixture images"
python scripts/record_probes.py examples/probe_outcomes.example.csv --out /tmp/imr-smoke/review --subject "example-image-1 via API"
python scripts/record_review.py examples/review_answers.example.json --out /tmp/imr-smoke/review
```

Expected: the provenance check reports the manifest store present in 3 of 6 fixture files
and in 0 of 3 after every transformation (without Pillow, four transformations are reported
as skipped); the probe summary lists six categories from 42 example probes; the review
prints `threats: 10 with evidence recorded, 2 not assessed, 1 not applicable` and names
`img-04` and `img-12` as not assessed. The fixture images carry a deliberately invalid
manifest and the example answers describe an invented vendor.

Unit tests: `python -m pytest tests -q`.

## Notes

- `templates/threats.json` is what the scripts read; `references/threats.md` is the same
  list for people. A test keeps the ids in step.
- `lib/evalkit.py` is a vendored copy of the repo's shared helpers (Wilson interval,
  validity flag, context keys). Do not edit it here.
- Framework ids in the template were checked against MITRE ATLAS data release 2026.10 and
  the OWASP Top 10 for LLM Applications 2025. Most image threats have no OWASP id.
- Not verified:
  - No commercial image model's output was checked here. Detection was tested on built
    fixtures and on signed sample files from the C2PA reference implementation (JPEG, PNG).
  - Detection in WebP was tested only on a hand-built container, not a real signed file.
  - The JPEG segment layout comes from the C2PA spec and the reference implementation's
    source; the ISO JUMBF standard it cites was not read.
  - No vendor watermark detector was exercised. The script cannot read an invisible watermark.
  - The two vendor cards described in `references/evidence-harvest.md` were read through an
    automated summary, not line by line; one vendor help page could not be fetched.
  - The evidence rows were checked once against the `review-evidence` validator as it stood
    on 2026-11-14 (0 errors). That skill owns the format and was still being built; if it
    changes, `scripts/_evidence.py` here must follow.
  - The claim that no standardized benchmark exists rests on this repo's planning research
    and one short search dated 2026-11-14. Near misses are listed in `references/threats.md`.
