# Evidence harvest — what to pull from the vendor before probing anything

Work through the fourteen items. For each, the reviewer records one of:

- `found`: a one-sentence claim in your own words, the URL, and the date you read it;
- `absent`: you looked in the named place and it is not there. **This is a finding** and
  becomes an evidence row with `absent: true`; give the place you looked as `source`;
- `not_checked`: you did not look. The record lists it.

Put the answers in a JSON file shaped like `examples/review_answers.example.json` and run
`scripts/record_review.py`. Provenance follows the `review-evidence` skill's meanings:
`published` (the default) for the vendor's own documents, read at their URL; `harvested` for
a third party (a paper about the model, a press report, H-13); `reviewed` for a document you
hold that has no URL, such as a contract. `published` and `harvested` rows must cite an
http(s) URL. An optional `kind` labels the row (`system_card`, `model_card`, `data_handling`,
`limitation`, `incident`, `research`, `other`).

Rules for the harvest
- Quote the model and version the document names. A card for a sibling model is evidence
  about the sibling; say so in the note.
- Record what the document says, not what it implies. "The card reports one aggregate rate"
  is a claim; "the model is safe" is not.
- Never copy a vendor's numbers into this skill's templates. They go in your evidence rows,
  with the URL and date, and they describe the vendor's test, not yours.

## The items

| Id | Pull this | Where it usually is | Bears on |
|---|---|---|---|
| H-01 | A system card or model card for this exact model and version; its date | vendor safety or model-card site | all |
| H-02 | Safety evaluation results: categories covered, metric definitions, aggregate or per category, sample counts, safeguards on or off, which surface | the card's evaluation section | img-09 |
| H-03 | Whether fraud documents, brand impersonation, QR codes, hidden payloads or likeness were evaluated at all | the card; usually absent | img-01 to img-05 |
| H-04 | Red teaming: internal or external, scope, whether findings are disclosed | the card | img-01, img-02, img-05, img-09 |
| H-05 | Provenance: C2PA metadata (which surfaces and formats), invisible watermark (its name), visible label, detector (public, partner-only, internal), robustness claims and admitted limits | the card's provenance section; help pages | img-07, img-08 |
| H-06 | Usage policy: impersonation, fraud, deception, real people, minors; how it is enforced | usage policy | img-01, img-02, img-05 |
| H-07 | Safeguards: prompt-layer and image-layer checks, checks on uploaded images, and which safety settings a customer can change | the card; API documentation | img-01 to img-06, img-09 |
| H-08 | Surfaces: which of app, API and reseller consoles the published results apply to, and documented differences | the card; cloud provider documentation | img-07, img-09 |
| H-09 | Image input and editing: rules for uploading photos of people and documents | usage policy; API documentation | img-05, img-06 |
| H-10 | Data handling: retention of prompts, uploads and outputs; training use; region; abuse-monitoring copies | data-processing terms; privacy documentation | img-10 |
| H-11 | Logging and attribution available to the customer; abuse-reporting channel | API and admin documentation | img-11 |
| H-12 | Rate limits, quotas, spend controls | API documentation; pricing | img-12 |
| H-13 | Independent evaluations and public bypass reports for this model | papers, security blogs, the vendor's own incident notes | img-09 |
| H-14 | Video only: separate evaluation, provenance in video files, likeness and voice rules | the card for the video model | img-13 |

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
the security categories of this review (H-03) are not; provenance is stated but not
measured; results are aggregate and tied to an unstated or single surface.

Not verified here: OpenAI's help article on C2PA in generated images could not be fetched
(the site refused an automated client). Read it yourself for H-05 on OpenAI models.
