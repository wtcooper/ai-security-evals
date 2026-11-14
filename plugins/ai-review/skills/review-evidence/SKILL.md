---
name: review-evidence
description: >-
  Second stage of a guided AI security review. Harvests what already exists about the
  subject before anything is measured: vendor system and model cards, published benchmark
  scores, documented limitations, data retention and hosting, known incidents and
  research, and for open weights the scan verdicts Hugging Face publishes. Each item
  becomes a row in evidence.jsonl with its source, capture date and provenance; what was
  looked for and not found is recorded as a row too. Use after review-scope and before
  measuring. Records evidence; does not weigh it or reach a verdict.
license: MIT
compatibility: "Requires python>=3.10 (standard library only). The open-weights harvest needs HTTPS access to huggingface.co; HF_TOKEN only for gated repos. No model API keys."
---

# review-evidence — harvest before measuring

You are running this skill for a reviewer who has a `review.json` (from `review-scope`)
and needs to know what is already established about the subject. Anything a vendor,
researcher or registry has already published is cheaper than a measurement, and its
gaps tell you what to measure.

This stage writes one file, `evidence.jsonl`. It does not score evidence, decide whether
it is sufficient, or recommend controls.

## What the reviewer supplies

- `review.json`: the subject's name, version and vendor, and whether weights are open.
- Any documents the requester already holds (contract, data processing terms, vendor
  security questionnaire).
- If a test plan exists already (`test-plan.json` from `review-threat-model`), its threat
  ids. If not, use the threat names the reviewer uses and align them later.

## What gets written

`evidence.jsonl`, next to `review.json`. One JSON object per line:

| Field | Meaning |
|---|---|
| `id` | `E001`, `E002` … assigned on append |
| `claim` | What the source says, in one sentence, not upgraded |
| `threats` | Threat ids the claim bears on |
| `source` | URL the claim was read at (for `self_run` / `reviewed`, a URL or file path) |
| `captured` | Date the source was read, `YYYY-MM-DD` |
| `provenance` | `published`, `harvested`, `self_run` or `reviewed` |
| `note` | Conditions the claim holds under, and what it leaves out |
| `absent` | `true` when the row records something looked for and not found |
| `kind`, `pointer` | Optional label; path to the summary or notes the row came from |

**Provenance** says who established the claim, which is what a reader needs to weigh it:

| Value | Meaning |
|---|---|
| `published` | Stated by the vendor or a benchmark's authors in their own document. Read at the source. Not checked by you. |
| `harvested` | Read from a third party or an automated feed: a registry API, a leaderboard, an incident database, the press. Not checked by you. |
| `self_run` | Measured by this organisation with a measurement skill. `pointer` names the experiment summary. |
| `reviewed` | A person in this organisation examined a design, configuration, contract or search result and recorded what they saw. |

## Steps

### 1. Work through the harvest list
[references/what-to-harvest.md](references/what-to-harvest.md) lists what to look for by
category, the question each item answers, and how to phrase the row. In short:

1. **System card / model card** — does one exist for this exact version?
2. **Published scores** — which benchmarks, on which surface (bare API or product), with
   which safeguards on, measured by whom?
3. **Documented limitations** — what the vendor says it does not do or should not be
   used for.
4. **Data handling** — retention, training on inputs, hosting region, sub-processors.
5. **Incidents and research** — published attacks, advisories, incident reports that name
   this subject or its family.
6. **Open weights** — the scan verdicts the Hub publishes (step 3 below).

Read each source yourself at its URL. A search-result snippet or a secondary summary is
not a source: either open the primary page or record the claim as `harvested` with the
page you actually read.

### 2. Append a row per claim
```
python scripts/evidence.py append --file evidence.jsonl \
  --claim "<what the source says>" --threats <id>,<id> \
  --source <url> --provenance published --kind system_card \
  --note "<surface and conditions it was measured under; what it omits>"
```
Write the claim as narrowly as the source does. If a score was measured on the bare API
and the review's `context.surface` is a product or harness, say so in `note`: the result
may not transfer.

**Record what is absent.** When you looked for something and did not find it, that is a
finding. Add `--absent`, state in the claim what does not exist, give the page you
searched as `--source`, and say in `--note` where you looked:
```
python scripts/evidence.py append --file evidence.jsonl --absent \
  --claim "No system card or safety evaluation was found for <subject> <version>." \
  --threats <ids it would have informed> --source <vendor docs index url> \
  --provenance reviewed --note "Searched <places>, <date>."
```

### 3. Open weights: harvest the published scan verdicts
Only when `review.json` has `subject.weights.open: true`.
```
python scripts/weights_scan.py <org/repo> [--revision main] --out weights.json
python scripts/evidence.py from-weights weights.json --file evidence.jsonl
```
`weights_scan.py` reads the scan results Hugging Face already publishes for every file in
a model repository (two unauthenticated API calls). It downloads no weights and runs no
scanner of its own. Its verdict is one of:

| Verdict | Meaning | Exit code |
|---|---|---|
| `clean` | The Hub reports its scans finished, every weight file has at least one scanner verdict, and none is unsafe | 0 |
| `unsafe` | Any scanner, or the Hub's summary, flags any file | 1 |
| `unscanned` | Scans not reported finished, no weight files found, or a weight file with no verdict | 2 |
| `error` | The repository could not be read (missing, gated, private, network) | 2 |

**`unscanned` is never `clean`.** `from-weights` turns `unscanned` and `error` into
`absent` rows ("no complete scan result exists"), not into a reassuring claim. The output
also reports how many weight files each scanner covered, and whether the repository ships
only pickle-based formats (which can execute code on load) with no safetensors or GGUF
alternative; `from-weights` adds a separate row for that. Rows use the threat id
`supply-chain-model`; pass `--threat <id>` if the review uses another id.

A `clean` verdict says the scanners that ran found nothing. It does not show that the
weights are free of a backdoor.

### 4. Validate and summarise
```
python scripts/evidence.py validate evidence.jsonl [--known-threats test-plan.json]
python scripts/evidence.py summary  evidence.jsonl
```
`validate` exits 1 on any malformed row. `summary` prints counts by provenance, the
absent rows, and the threats whose only evidence is `published` or `harvested`.

### 5. Hand over
Read the summary back to the reviewer in this order: what is absent; which threats rest
only on claims nobody here checked; then what exists. Point to `review-threat-model`,
which sorts each threat into benchmark, custom probe, design review or uncovered.

## Later in the review

Measurement results and design reviews are evidence too. After a measurement skill has
written an experiment summary, add a `self_run` row whose `pointer` is that summary; after
a design review, add a `reviewed` row whose `pointer` is the notes. `review-report` then
shows every threat with the provenance of what stands behind it.

## Saying what was not assessed

- A missing document is an `absent` row, never an empty section.
- A category you did not have time to search is also an `absent`-style statement: add a
  row saying it was not searched (`--provenance reviewed --absent`, note "not searched:
  out of time"). Silence reads as "nothing found".
- A claim you could not open at its primary source is recorded as `harvested`, with the
  page you did read as the source.

## Smoke test

No keys, no network. From this skill's directory:
```
T=$(mktemp -d)
python scripts/evidence.py append --file "$T/evidence.jsonl" --absent \
  --claim "No system card was found for example-model-1." --threats harmful-assistance \
  --source https://example.com/docs --provenance reviewed \
  --note "Searched the documentation index (fictional example)."
python scripts/evidence.py from-weights examples/weights.example.json --file "$T/evidence.jsonl"
python scripts/evidence.py validate "$T/evidence.jsonl"
```
Expected: `appended E001`, `appended E002 (absent): No complete scan result exists …`,
then `2 row(s), 0 error(s), 0 warning(s)`. `examples/weights.example.json` is
`weights_scan.py` output for a fictional repository, built from a synthetic file listing.

## Notes

- This skill never rates a source or a claim. Sorting by provenance is the only ordering.
- Public benchmark scores published by a vendor were measured under the vendor's
  conditions. Record the surface and safeguards they state; if they state none, say so.
- Checked in this build: `weights_scan.py` was run against the live Hub on 2026-11-14 for
  one public repository (verdict `clean`, per-scanner coverage returned) and one
  non-existent repository (verdict `error`, exit code 2), and the first result was
  converted with `from-weights`.
- **Not verified**
  - A live repository that the Hub flags `unsafe`, and one it reports `unscanned`: those
    verdict paths are unit-tested on synthetic file listings only.
  - Gated repositories with `HF_TOKEN`.
  - The harvest list in `references/` was not exercised on a real vendor's documents.
