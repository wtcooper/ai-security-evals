# Decision models — what they are and how to security-evaluate them

Research snapshot, 14 November 2026. The category is about two months old and moving weekly;
re-check anything here before relying on it.

**Evidence labels.** **[P]** primary source fetched and read · **[P-snippet]** primary page
seen only through a search snippet · **[K]** prior knowledge, not re-checked. Three [P]
sources were re-fetched independently after the research pass (TypeSafe API reference,
Microsoft Learn page, arXiv 2610.12292); the rest rests on a single research pass. All arXiv
items are recent preprints read at abstract/repo level, not full text.

## 1. What a decision model is

A decision model takes a shared input (`state`: text or JSON, sometimes images/audio/video)
plus one or more **typed questions with a caller-defined closed answer set**, and returns
typed answers with probabilities. It generates no text and no rationale.

- TypeSafe: a System One model "evaluates a state and returns typed answers and
  probabilities". [P] https://docs.typesafe.ai/concepts/system-one
- Microsoft: it "doesn't generate a free-form response or written rationale". [P]
  https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision
- Question types: yes/no (`noul`, or `predicate` at OpenAI), `choice` (one of N), `score`
  (ordered rubric, returned as a probability-weighted average). Jev 1.14 adds `box`. [P]
  https://docs.typesafe.ai/api/system-one.md

**The policy is supplied at inference time**, inside each question's `instructions` and
option `criteria`. No API read has a separate policy object.

| Compared with | Difference |
|---|---|
| Chat LLM | No generation, input-only billing, single forward pass, no rationale |
| Trained classifier | Zero-shot: labels and their definitions arrive per request |
| Guardrail model (Llama Guard, ShieldGemma, gpt-oss-safeguard) | Same policy-in-context idea, but general-purpose with a native probability distribution |
| Reranker | Can act as one, but answers arbitrary typed questions |
| Reasoning model | Opposite end: no multi-step reasoning; TypeSafe documents weakness on arithmetic, counting, dates, double negatives. [P] https://docs.typesafe.ai/model-jaggedness.md |

Vendor-listed uses: routing, triage, gating/filtering, grading model output, tool/agent
selection, prompt-injection and content screening. Microsoft's own example of a `noul` is
"whether a tool call touches production data, a document contains a prompt injection"; Google
says Search uses its API "as a safety layer to detect adversarial behavior in MCP tools". [P]
https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/

## 2. Products

| | TypeSafe **Jev** | **OpenAI Decisions API** | **Microsoft-Decision-1** | **Gemini Decision 1** |
|---|---|---|---|---|
| Release | 15 Sep 2026 [P-snippet]; 1.14 on 14 Oct [P] | preview 29 Sep, GA 22 Oct [P-snippet]; GA confirmed in docs [P] | 9 Oct 2026, public preview [P] | 11 Nov 2026 [P] |
| Model IDs | `jev-1.14.0`, `jev-1.13.0`; aliases `jev-latest`, `jev-preview` | `gpt-6-luna` | `Microsoft-Decision-1` v1 (request uses deployment name) | `gemini-decision-1` |
| Endpoint | `POST api.typesafe.ai/v1/systemone` | `POST /v1/decisions` | `POST {resource}/providers/microsoft/v1/systemone` | `POST /v1beta/decisions` (per Google codelab) |
| Request | `state` + `questions` map | `input` (string or role-separated messages, tool calls/outputs) + `questions` array | `state` + `questions` map | `input` + `questions` |
| Output | probabilities; `confidence` on choice/score | probabilities; `confidence`; per-question **`refusal`** | probabilities | probabilities + `confidence` on every answer |
| Limits | 64k tokens (262k "danger zone", less accurate) | 400 questions/request | text/JSON; 32K context [P-snippet] | 256K tokens, 1,000 questions; multimodal |
| Price (input only) | $0.042/M | $0.10/M | $0.042/M | $0.10/M |
| Weights | closed | closed | post-trained Qwen3.5-9B, not released | closed |
| Seed / determinism | none | none stated | none stated | none found |

Sources: https://docs.typesafe.ai/models.md · https://docs.typesafe.ai/changelog.md ·
https://developers.openai.com/api/docs/guides/decisions ·
https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/decisions ·
https://commandline.microsoft.com/microsoft-decision-1-model-foundry/ ·
https://codelabs.developers.google.com/codelabs/discriminative-models

Also in the field: **Cloudflare Clef / Clef-flash** (Apache-2.0 open weights, Jev-API
compatible, Workers AI) [P] https://blog.cloudflare.com/clef-decision-models · **AWS Strands
Decider 2B** (open source, runs locally) [P]
https://strandsagents.com/blog/introducing-strands-decider/ · Liquid `d1` and Inception
`mercury-decide` on OpenRouter, which reports 22 decision models from 13 makers [P-snippet]
https://openrouter.ai/docs/guides/features/decisions

### Hosting

| Platform | Status |
|---|---|
| First-party | TypeSafe, OpenAI, Gemini API / AI Studio |
| Azure AI Foundry | Both Microsoft-Decision-1 and the Azure OpenAI Decisions API (`gpt-6-luna`) [P] |
| Vertex AI | Not yet; Google says "coming soon" [P] |
| AWS Bedrock | No managed decision model found; AWS's own post runs Strands Decider on EC2/Lambda [P] https://aws.amazon.com/blogs/machine-learning/use-decision-models-with-amazon-bedrock-agentcore-evaluations/ |
| OpenRouter | Unified `POST /api/alpha/decisions` in the Jev wire format |
| Self-hosted | Clef, Clef-flash, Strands Decider 2B |
| `/chat/completions` | Not applicable to any of them |

**Three wire formats:** (A) System One — `state` + `questions` map (TypeSafe, Microsoft,
Clef, OpenRouter, local servers); (B) OpenAI — `input` + `questions` array with `predicate`;
(C) Gemini — `input` + `questions` with `noul`.

### Security-relevant facts from the vendors' own docs

- **Confidence is not comparable across vendors.** Jev's is normalised top probability and
  "measures concentration, not the chance the answer is correct" [P]
  https://docs.typesafe.ai/confidence.md; Gemini's equals the top probability; OpenAI's is
  undefined. Thresholds must be set per model.
- **Only OpenAI separates roles** (developer/system vs user vs tool output) and returns
  refusals. Jev and Microsoft take one undifferentiated `state`.
- **TypeSafe admits injection susceptibility**: "State is data, and Jev does not treat it as
  hostile by default"; the model "leans toward the option that comes first"; accuracy falls
  with unrelated state. [P] model-jaggedness page
- **Microsoft's stated limits**: scores change with wording and option order; as a safety
  filter it "might miss subtle harmful content or flag benign content"; add an abstention
  option; not the sole decision-maker for consequential decisions about people. [P]
- Microsoft reports 1.3% decision change under perturbation across 5,250 requests and 11
  safety benchmarks — vendor-reported, no methodology published.

## 3. Published security findings

| Paper | Finding | Artefacts |
|---|---|---|
| **One Word Opens the Gate** (arXiv 2610.12292) [P] | As agent guardrails, allow/block accuracy 36–72% against 50% chance. Six lines of irrelevant log text raised fail-open from 0% to 63%; renaming the permissive option raised it to 93–100% on four models. Low-confidence escalation failed. Conclusion: these models "should not be the component that decides". | https://github.com/ArminAzizi98/option-channel-attack |
| **JevAdvBench** (arXiv 2609.31142) | Attacks flip 46.3% of Jev's correct decisions vs 0.17% for identical re-runs; at a 0.8 threshold 23.5% of executed decisions are wrong | https://github.com/JevAdvBench/JevAdvBench (code MIT, **data CC BY-NC 4.0**) |
| **DecisionRobust** (arXiv 2610.19118) | Five suites, text + vision, 1,058 curated examples. Robustness to perturbation does not predict robustness to injection | https://github.com/Yifan-Lan/DecisionRobust (code MIT; data licence unchecked) |
| **Decision Hijacking** (arXiv 2609.28613) | 510 InjecAgent cases recast for jev-1.13.0. Injection shifts probabilities but rarely selects the attacker's target; probability feedback roughly doubles success | no code |
| **From Detection to Decision** (arXiv 2610.20907) | Jev as injection detector on 47,611 examples: AUROC 0.871 vs 0.897 for an LLM judge. At a 1% false-negative target every system needed >91.8% escalation | no code |
| **JevBench** (independent) | Accuracy, Brier, ECE, paraphrase consistency, option-order sensitivity (one model 72% → 21% with options reversed) | https://github.com/fstandhartinger/jevbench (MIT) |

Cautions: JevAdvBench's arXiv v2 abstract and its GitHub README disagree (862 vs 812
questions, 46.3% vs 10–12% flip rate) — read the v2 PDF before quoting. Headline rates are on
attack-selected hard sets and do not estimate everyday failure rates.

## 4. Threat model

| # | Threat | What is specific to decision models |
|---|---|---|
| 1 | Injection via judged content | `state` is one blob; unverified opinions and flawed arguments work about as well as explicit commands |
| 2 | Option-channel / policy override | Labels and criteria are prompt. If any option text is attacker-influenced or templated from data, the gate fails open |
| 3 | Flipping by benign-looking perturbation | Irrelevant context, paraphrase, option order; first-option bias is vendor-documented |
| 4 | Confidence manipulation | Push below a review threshold (reviewer DoS) or keep a wrong answer confident |
| 5 | Probability oracle | Returned probabilities give a gradient-free optimisation signal |
| 6 | Non-determinism and drift | No seed anywhere; aliases move silently |
| 7 | Error asymmetry | Fail-open and fail-closed must be reported separately |
| 8 | No rationale | Faithfulness is untestable; audit depends on logging input + full distribution |
| 9 | Forced choice / refusal | Always answers unless an abstain option exists; OpenAI's `refusal` is an evasion path if treated as allow |
| 10 | Encoding, obfuscation, multilingual, multimodal | Image overlay tested in DecisionRobust; no encoding-specific study found |
| 11 | Unbounded consumption | Input-token billing, up to 262k context and 400–1,000 questions per request |
| 12 | Confused deputy as agent gate | The gate reads attacker-controlled tool output; a deterministic rule over typed fields scored 100% where the model did not |
| 13 | Data and policy leakage | No generation, so limited to probing through probabilities; no study found |
| 14 | Bias | Vendor-acknowledged; no fairness benchmark found |

## 5. Adjacent benchmarks that can be recast

All **[K]** — re-check licences and availability before adopting.

| Benchmark | Measures | Fit for a label-only API |
|---|---|---|
| DynaGuard / DynaBench (arXiv 2509.02563) | Compliance with arbitrary user-written policies | **High** — policy + dialogue + label is the decision-model shape |
| R-Judge (arXiv 2401.10019) | Safe/unsafe judgement of agent trajectories | **High** for agent-gate use |
| GuardBench, WildGuardMix | Guardrail classification, adversarial split | High as `noul` |
| XSTest (in inspect_evals), OR-Bench | Over-blocking of safe-but-scary prompts | High for false positives |
| Lakera PINT, deepset/prompt-injections, Open-Prompt-Injection, TensorTrust | Injection detection | High as detector tasks |
| BIPIA, InjecAgent | Indirect injection | Medium — recast as "is this tool output safe" |
| AgentDojo, AgentHarm (both in inspect_evals) | End-to-end agent attacks | Medium — decision model as tool-call approver in front of a fixed agent |
| HarmBench, StrongREJECT | Harmful behaviours | Medium — behaviours + jailbreak-wrapped variants as cases |
| JudgeDeceiver (arXiv 2403.17710), null-model cheating (arXiv 2410.07137) | Optimised attacks on LLM judges | Medium–high as attack **methods** |
| PolyGuard (arXiv 2504.04377) | Multilingual moderation | High for the multilingual axis |

No public access-control or authorisation-decision dataset designed for LLM judges was found.

## 6. Options for a standardised comparison, ranked by value for effort

1. **Run the existing decision-model benchmarks as-is (days).** DecisionRobust ships adapters
   for Jev, OpenAI Decisions, Liquid d1, a local server and a custom Python adapter; JevBench
   has `typesafe` and `openai_compat`. Gives accuracy, calibration, flip rate, targeted attack
   success, paraphrase and option-order sensitivity. Gaps: no confirmed Gemini or Microsoft
   adapter (Microsoft uses the Jev wire format, so the `typesafe` adapter with a different base
   URL should work — untested); JevAdvBench data is non-commercial.
2. **A thin vendor-neutral adapter (about a week; the enabling step).** One canonical case
   (`state`, typed questions) translated to the three wire formats, one canonical result
   (argmax label, full distribution, refusal flag, latency, tokens, resolved model ID). Fix
   up front: compute your own confidence from the distribution rather than comparing vendor
   `confidence`; pin versioned IDs, never aliases, and record the `model` echoed back; score
   refusals and HTTP errors as their own class; for OpenAI, test untrusted content in both the
   user and tool-output positions.
3. **An in-house labelled policy corpus (custom; highest long-term value).** Record = policy
   (instructions + criteria), case, ground-truth decision, cost class (fail-open vs
   fail-closed). Generate adversarial variants per clean case on fixed axes: in-state
   injection (command, authority claim, fake validation note, unverified opinion, flawed
   argument); irrelevant padding; option-channel edits (misleading label, reorder, paraphrased
   criteria); encoding and language; structure (extra JSON fields); image overlay. Seed from
   real authorisation / tool-gating policies plus recast DynaBench, R-Judge, XSTest,
   InjecAgent. Keep a private held-out split. Re-validate that each variant preserves the
   label, or attack rates are overstated.
4. **Wrap the adapter in Inspect AI (moderate).** A custom model provider or solver plus
   scorers; buys logging, reruns and inspect_evals datasets. promptfoo's HTTP/Python provider
   is a lighter option for CI regression. Neither has a native decisions provider.
5. **Agent-gate evaluation with AgentDojo (higher).** Each decision model as the tool-call
   approver in front of a fixed agent; report utility and attack success. The only option that
   measures the confused-deputy risk end to end.
6. **Adaptive attacks with returned probabilities as the signal (highest).** Per release, for
   shortlisted models only. garak is a poor fit: its detectors assume generated text.

### Metrics

- **Fail-open and fail-closed rate** against labelled cases, separately, at operating
  thresholds and as a curve.
- **Decision-flip rate under attack**, on cases the model got right when clean, always beside
  the **identical re-run flip rate** as the noise floor.
- **Targeted attack success** (attacker's chosen option selected).
- **Consistency** across N repeats, paraphrases and option permutations.
- **Calibration** (ECE, Brier) clean and under attack — the confidence of flipped decisions is
  the number that decides whether "escalate when unsure" works.
- **Threshold-gate metrics**: share of executed decisions that are wrong at threshold t, and
  share of correct decisions pushed into review.
- Refusal/abstain rate, latency p50/p95, cost per 1,000 decisions.

### Design conclusion the evidence supports

Evaluate these models as a **screening layer** that reduces reviewer or LLM load, with
deterministic code making the final allow/block call wherever the policy can be expressed
over typed fields. The strongest attack paper and TypeSafe's own guidance agree on this.

## 7. Not verified

- OpenAI's announcement post returned 403; its dates and cached price are from snippets.
- TypeSafe's launch date is from a snippet; sources disagree on whether Jev is formally GA.
- No raw Gemini request/response JSON was read; the endpoint path is from Google's codelab.
- Vertex AI has no date; "nothing on Bedrock" is absence of evidence.
- No system card or safety evaluation report was found for any of the four products.
- Not found at all: fairness benchmarks, policy-extraction studies, encoding-specific
  studies, or native support in Inspect AI, promptfoo, garak, PyRIT or LiteLLM.
