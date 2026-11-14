# What to harvest, and how to write the row

Work down the list. For each item either append a row for what you found or an `absent`
row for what you did not. `kind` values are in brackets.

## 1. System card or model card [`system_card`, `model_card`]

Look for: a document from the vendor describing this exact version's safety evaluations.

Questions the rows should answer:
- Does a card exist for this version, or only for an earlier one or a sibling model?
- Which evaluations does it report, and on which surface: the bare API, the consumer
  product, a harness? Results on one surface do not establish another.
- Which safeguards were on during those evaluations?
- Does it name things it did not evaluate?

Row wording: quote or closely paraphrase one claim per row. Put the surface, the
safeguards and the test set in `note`. If the card covers a different version, the row is
`absent` for this version, with the other version named in `note`.

## 2. Published benchmark scores [`benchmark_score`]

Look for: scores on named benchmarks, from the vendor (`published`) or from a leaderboard
or third party (`harvested`).

Record per row: the benchmark and its version, the metric, the number as printed, the
number of samples if given, who ran it, the date, the model identifier as printed. A
score with no sample count or no stated configuration is still a row; say in `note` what
is missing. Do not convert, average or round.

Public benchmarks are in training data. A published score is comparative at best.

## 3. Documented limitations [`limitation`]

Look for: the vendor's own statements of what the subject does poorly or must not be used
for (acceptable-use policy, "limitations" or "known issues" pages, release notes).

These are the cheapest strong evidence there is: a vendor saying "this is susceptible to
X" settles that X needs testing in your deployment. One row per limitation, mapped to the
threat it bears on.

## 4. Data handling and hosting [`data_handling`, `hosting`]

Look for: retention period for inputs and outputs; whether inputs are used for training
and how to opt out; where processing happens; sub-processors; whether a zero-retention or
regional option exists and whether the organisation's contract has it.

Sources: the vendor's data-processing terms and trust centre (`published`); the
organisation's own contract (`reviewed`, with the contract reference as `source`).
Distinguish what the public terms say from what the organisation actually signed.

## 5. Known incidents and research [`incident`, `research`]

Look for: papers, advisories and incident reports that name this subject, its model
family, its harness or its feature.

Record per row: what was shown, on which version, under which conditions, and whether the
authors state it was fixed. A preprint read only at abstract level is recorded as such in
`note`. Headline attack-success rates are usually measured on attack-selected hard sets;
say so rather than presenting them as everyday failure rates.

## 6. Open weights [`weights_scan`]

Run the open-weights harvest (`scripts/weights_scan.py`, then
`scripts/evidence.py from-weights`). It reads the scan verdicts Hugging Face publishes.
`unscanned` and unreadable repositories become `absent` rows.

Also worth a row each, when the weights are open: the licence as stated on the repository
page; whether the publishing account is the vendor's own; the revision hash the
organisation would pin.

## 7. What you ran or reviewed yourself [`result`, `design_review`]

Later stages produce these. A measurement gets a `self_run` row pointing at its summary;
a design review gets a `reviewed` row pointing at the notes. Write the claim from the
summary's own words, including its validity flags.

## Wording rules

- One claim per row.
- Keep the source's scope. "Refused 98% of the vendor's internal harmful-request set on
  the bare API" is not "resists harmful requests".
- Never write a row from memory or from a search snippet.
- An `absent` row states what does not exist and where you looked. "Not found" after
  looking and "not searched" are different rows.
