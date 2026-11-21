# Evidence harvest — what the vendor already says, before anything runs

A short step: eight items, about half an hour. It tells you which surface and settings the
vendor's own claims apply to, and it turns "the vendor never evaluated this" into a recorded
finding instead of a silence. For each item record one of:

- `found`: a one-sentence claim in your own words, the URL, and the date you read it;
- `absent`: you looked in the named place and it is not there. **This is a finding** and
  becomes an evidence row with `absent: true`; give the place you looked as `source`;
- `not_checked`: you did not look. It is listed as such.

Put the answers in a JSON file shaped like `examples/harvest.example.json` and run
`python scripts/record_harvest.py answers.json --out $EXP`. Provenance follows the
`review-evidence` skill's meanings: `published` (the default) for the vendor's own documents,
read at their URL; `harvested` for a third party (a paper, a press report); `reviewed` for a
document you hold that has no URL, such as a contract. `published` and `harvested` rows must
cite an http(s) URL. An optional `kind` labels the row (`system_card`, `model_card`,
`data_handling`, `limitation`, `incident`, `research`, `other`).

Rules
- Quote the model and version the document names. A card for a sibling model is evidence
  about the sibling; say so in the note.
- Record what the document says, not what it implies.
- Never copy a vendor's numbers into this skill's files. They go in your evidence rows, with
  the URL and date, and they describe the vendor's test, not this benchmark.

## The items

| Id | Pull this | Where it usually is | Bears on |
|---|---|---|---|
| H-01 | A system card or model card for this exact model and version; its date | vendor safety or model-card site | all threats |
| H-02 | Safety evaluation results: categories, metric definitions, per category or aggregate, sample counts, safeguards on or off, which surface | the card's evaluation section | ig-reframing-bypass |
| H-03 | Whether brand assets, forged documents, QR codes or likeness were evaluated at all | the card; usually absent | ig-brand-impersonation, ig-forged-documents, ig-machine-payload, ig-likeness |
| H-04 | Usage policy on impersonation, fraud, deception and real people, and whether it is enforced at the prompt layer, the image layer or both | usage policy; the card | ig-brand-impersonation, ig-forged-documents, ig-likeness |
| H-05 | Provenance: C2PA metadata (which surfaces and formats, who signs), invisible watermark (its name), visible label, detector (public, partner-only, internal), robustness claims and admitted limits | the card's provenance section; help pages | ig-provenance |
| H-06 | Surfaces and settings: which of app, API and reseller consoles the published results apply to; which safety settings a customer can change, and which this deployment uses | the card; API and cloud provider documentation | ig-reframing-bypass, ig-provenance |
| H-07 | Independent evaluations and public bypass reports for this model | papers, security blogs, incident notes | ig-reframing-bypass |
| H-08 | Operations: retention and training use of prompts and outputs, per-generation logs or ids, abuse reporting, rate limits, quotas, spend controls | data-processing terms; API and admin documentation | design review |

The table is the people-readable form of `templates/harvest.json`; a unit test keeps the two
in step. Read H-06 before choosing `--extra` for the run: the benchmark result applies to the
surface and settings it ran with, and the vendor's claims may apply to different ones.

## What a current card actually reports (two examples)

Read on 2026-11-14 through an automated page-to-text summary, not line by line. They are
examples of structure. Re-read the card for the model you are reviewing; do not reuse these
descriptions as evidence.

**OpenAI, "ChatGPT Images 2.0 System Card"**, published 21 April 2026,
`https://deploymentsafety.openai.com/chatgpt-images-2-0`.
- Sections: introduction; observed safety challenges, evaluations and mitigations (new
  challenges, the safety stack, automated evaluations and adversarial testing, an
  image-specific Preparedness assessment); image provenance.
- Evaluation: adversarial prompts across the vendor's tracked policy categories, reported as
  aggregate rates with a per-layer breakdown (image layer, prompt layer, combined), for a
  standard and a thinking mode. Not per category, and no safeguards-off baseline.
- Provenance: states C2PA metadata, and an imperceptible watermark with internal tooling to
  tell whether an image came from its products.
- Real people: names realistic deepfakes as a new challenge and says they are blocked at the
  prompt and image layers; gives no separate measurement.
- Not found in it: any evaluation of fraud documents, phishing or brand assets, identity
  documents or QR codes; false-block rates; which surface (app or API) was tested.

**Google DeepMind, "Gemini 3.1 Flash Image — Model Card"**, published 26 February 2026,
`https://deepmind.google/models/model-cards/gemini-3-1-flash-image/`.
- Sections: model information; model data; implementation; distribution; evaluation
  (capability results for text-to-image and editing); intended usage and limitations; ethics
  and content safety (evaluation approach, safety policies, frontier safety, risks and
  mitigations).
- Safety: lists content-policy areas and describes human red teaming and assurance
  evaluations, with no quantitative safety results.
- Not found in it: provenance (SynthID or C2PA), likeness, fraud or identity documents.
  Google documents SynthID elsewhere (`https://deepmind.google/models/synthid/`), which is
  why H-05 says to look at help pages as well as the card.

What the two have in common, and what to expect: content-safety policy areas are covered;
the security categories of this benchmark (H-03) are not; provenance is stated but not
measured; results are aggregate and tied to an unstated or single surface.

Not verified here: OpenAI's help article on C2PA in generated images could not be fetched
(the site refused an automated client). Read it yourself for H-05 on OpenAI models.
