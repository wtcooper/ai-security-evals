# Threats this skill does not measure

A run of this skill answers: on these labelled cases, how often is each arm wrong in each
direction, and how often does a fixed set of perturbations change a decision that was right?
The list below is what it leaves open. When reporting results, name the rows that apply to
the user's deployment as untested; an untested threat is a finding, not a gap to leave
silent.

| Threat | What this skill does | What is left open |
|---|---|---|
| Injection through the judged content | Five fixed injection templates appended to the untrusted field | Injections written for the specific model, placed elsewhere in the state, split across fields, or hidden in markup. The templates are public and identical every run |
| Option-channel override | One misleading rename of the permissive label; option reorder; one hand-written paraphrase | Searching over many candidate labels (the published attack swept about two hundred), attacker-written criteria, added or removed options |
| Adaptive attacks using the returned probabilities | Nothing | The API returns a probability for every option, which is a gradient-free optimisation signal. An attacker who can query the model can tune an input against it. This needs a red-team method, not a fixed benchmark, and is the largest gap |
| Confidence manipulation | Reports the top probability of flipped decisions and whether it separates them from kept ones | Attacks built to keep a wrong answer confident, or to push correct answers below a review cut-off and flood reviewers |
| Threshold behaviour | Scores yes/no at the argmax and keeps every distribution in `samples.jsonl` | Fail-open and fail-closed as a curve over operating points; the share of executed decisions that are wrong at a given cut-off |
| The model as a gate inside a running agent | Static tool-call records with an untrusted context field | The end-to-end case: an agent that reads attacker-controlled tool output, proposes a call, and a gate that approves it. That needs an agent benchmark with the decision model as approver |
| Non-determinism and drift | Identical re-runs inside one run; records the model id the server reports | Change between runs days or weeks apart, silent alias moves between runs, differences between regions or deployment types |
| Refusal as an evasion path | Counts refusals, clean and under attack, as their own class | Whether the user's integration treats an unanswered request as allow. That is a property of their code, not of the model |
| Encoding and obfuscation | Base64 wrapper, zero-width characters, Latin-to-Cyrillic homoglyphs, on one field | Other encodings and ciphers, nested encodings, markup and Unicode tricks, obfuscated code |
| Languages other than English | Nothing | All seed cases and policies are English |
| Images, audio, video, PDF | Nothing | The adapter sends text and JSON only. Image overlays and instructions inside images are untested; `box` questions are not implemented |
| Long inputs | Padding of six log lines or one paragraph | Behaviour near context limits, including TypeSafe's long-context mode, and accuracy as unrelated state grows to thousands of tokens |
| Many questions per request | One question per request | Whether questions interfere with one another, and the vendors' limits of hundreds of questions per request |
| Unbounded consumption | Records input tokens, latency and, with a price, cost | Cost or latency attacks through oversized state or question counts; rate-limit behaviour under load |
| Data and policy leakage | Nothing | Whether probing through probabilities can recover policy text or prior inputs. No study was found |
| Bias and fairness | Nothing | Whether decisions about people differ by protected attribute. The vendors acknowledge the risk; no benchmark was found |
| Faithfulness | Nothing | These models return no rationale, so why a decision was made cannot be tested. Audit depends on logging the input and the full distribution |
| Policy quality | Nothing | A badly written policy gives wrong decisions that this skill attributes to the model. The seed policies are one author's wording |
| Real-world failure rate | Nothing | The seed corpus is 54 synthetic cases balanced by construction. Rates on it compare arms; they are not the rate at which a deployment will fail on real traffic |
| Training-data exposure | Nothing | The seed corpus is public in this repository and may enter training data. Keep a private held-out set for anything that matters |

## What a low flip rate means

It means the arm did not change its answer under these templates on these cases. It does not
mean the arm resists injection. Published attack papers on this model class report much
higher success with attacks chosen against the model, and report that robustness to
perturbation did not predict robustness to injection. Fixed variants are a floor.

## What a high flip rate means

It means a known, cheap perturbation changed decisions the arm had right, more often than
re-sending the same request did. Whether that matters depends on who can write to the state
and the options in the user's deployment, and on what else stands between the model's answer
and the action.
