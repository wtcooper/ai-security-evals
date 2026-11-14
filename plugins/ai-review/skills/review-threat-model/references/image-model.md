# Threat template — Image generation or editing model

A model that produces or edits images from text or from other images. For image input to a chat model, use the model template.

Which threats a catalogued benchmark covers depends on the catalogue at the time the plan is built; `scripts/plan.py` decides that. The last column says how a threat is assessed when no available benchmark covers it. A `—` in a framework column means no id was verified for that threat, not that none exists. The verified ids and where they were checked are in [framework-ids.md](framework-ids.md).

## Questions to ask for this subject type

- Who can prompt it, and where do the outputs go?
- Does it accept reference or input images?
- What does the organisation's content policy prohibit?
- Does the vendor document provenance metadata or a watermark?

Guided review for this subject type: `image-model-review`. A guided review skill for image-generation models. It covers the probe-set and provenance threats below that no benchmark measures, and writes evidence rows.

## Threats

| Threat id | Threat | Why it matters here | OWASP LLM 2025 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `image-prohibited-content` | **Prohibited imagery is generated.** The model produces images the organisation or the law prohibits, directly or through prompt rewording. | No standardised benchmark exists for this. | — | — | AML.T0054 | custom probe: No standardised benchmark exists. Hand-build a small probe set from the organisation's content policy, with benign twins. |
| `image-real-person-likeness` | **Likeness of a real person.** The model produces a convincing image of a real, identifiable person. | Impersonation and non-consensual imagery. | — | — | AML.T0088 | custom probe: No standardised benchmark exists. Probe with named public figures and with uploaded reference photos if the product accepts them. |
| `image-provenance` | **Missing or removable provenance.** Outputs carry no provenance signal, or it is lost on the first re-save or crop. | Whether an output can later be identified as generated. | — | — | — | custom probe: Inspect outputs for provenance metadata and any vendor-documented watermark; re-encode and re-check. |
| `visual-prompt-injection` | **Instructions hidden in an image.** Text or patterns inside an input image are followed as instructions. | If the model edits or is conditioned on input images. | LLM01:2025 | — | AML.T0051.001, AML.T0129 | custom probe: Embed instructions in images of the kind the deployment receives and score whether they are followed. |
| `jailbreak` | **Jailbreak.** A crafted prompt gets the model to produce what its safeguards would otherwise withhold. | Prompt rewording against the content filter. | LLM01:2025 | — | AML.T0054 | custom probe: Apply current jailbreak transformations to requests the subject refuses when asked plainly; report the uplift over the plain rate. |
| `over-refusal` | **Over-refusal of legitimate work.** Legitimate requests are refused or blocked. This is the cost side of every safeguard: a refusal rate on harmful requests is never read without it. | Benign prompts blocked by the content filter. | — | — | — | custom probe: Collect legitimate requests from the deployment that look risky and count refusals. |
| `training-data-extraction` | **Memorised training data is recovered.** The model reproduces personal, confidential or copyrighted material it memorised during training or fine-tuning. | Reproduction of training images. | LLM02:2025 | — | AML.T0137.003 | uncovered: No catalogued benchmark. For a model the organisation fine-tuned on its own data, a canary study is possible; for a vendor model only vendor statements exist. |
| `supply-chain-model` | **Tampered or unsafe model artefact.** Downloaded weights or model files carry malicious code or were replaced on the way: unsafe serialisation formats, a look-alike repository, a changed revision. | Open-weight image models and their add-on weights. | LLM03:2025 | — | AML.T0010.003, AML.T0011.000, AML.T0018.002 | design review: For open weights, harvest the published scan verdicts with review-evidence and record the pinned revision. For closed weights only vendor statements exist. |
| `unbounded-consumption` | **Unbounded cost or resource use.** Requests, loops or tool calls drive cost or load without a cap. | Generation is expensive per request. | LLM10:2025 | — | AML.T0034, AML.T0029 | design review: Review rate limits, spend caps, context and step limits as configured. |
| `data-retention-hosting` | **Retention, training use and hosting of submitted data.** Prompts, outputs, files or audio are kept, used for training, or processed in a place or by a party the organisation has not accepted. | Uploaded reference images, especially of people. | — | — | — | design review: Read the contract and the vendor's data terms; record what was signed, not what the public page says. |
| `version-drift` | **The thing reviewed is not the thing running later.** An alias moves to a new model, the harness updates itself, or outputs are not reproducible, so results stop describing the deployment. | Filter and model updates. | — | — | — | design review: Record the pinned identifiers, how updates arrive, and who is told. |

## What the template does not cover

The list is a starting point for this subject type. Threats that come from the particular deployment (its data, its users, its integrations) are added by the reviewer. The template names no controls.

---
Generated by `scripts/render_templates.py` from `threats.json` and `templates.json`. Edit the JSON, then re-run the script.
