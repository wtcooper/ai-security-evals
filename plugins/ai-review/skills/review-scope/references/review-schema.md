# review.json — schema (version 1)

One JSON object. `scripts/validate_review.py` enforces everything marked required.
Any required string may be the literal `"unknown"`; any required true/false may be
`"unknown"`. Unknowns are valid and are reported separately.

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | number | yes | `1` |
| `review_id` | string | yes | The organisation's own reference |
| `requested_by` | string | yes | Person or role who asked |
| `reviewer` | string | yes | Person or team doing the review |
| `opened` | date `YYYY-MM-DD` | yes | |
| `subject.type` | one of `model`, `agent`, `app`, `decision-model`, `voice-model`, `image-model`, `feature` | yes | Selects the threat template |
| `subject.name` | string | yes | |
| `subject.version` | string | yes | A dated or numbered identifier, not an alias |
| `subject.vendor` | string | yes | |
| `subject.feature` | one of `computer-use`, `memory`, `connectors`, `code-execution`, `multi-agent`, `background-agent`, `other` | when type is `feature` | |
| `subject.weights.open` | true / false | for every type except `app` and `feature` | Are the weights downloadable |
| `subject.weights.repo` | string | when `open` is true | e.g. a Hugging Face `org/repo`; read by the open-weights harvest in `review-evidence` |
| `context` | object | yes | Exactly the nine keys below, no others |
| `input_channels` | list | yes, at least one | See below |
| `capabilities` | object | yes | See below |
| `failure_impact` | object | yes | See below |
| `time_budget` | object | yes | See below |
| `out_of_scope` | list of `{item, reason}` | yes (`[]` allowed) | What the requester ruled out |

## `context`

These nine keys are the contract with the measurement skills: each copies `context` into
its `manifest.json`, so a result always says which deployment it applies to. A key outside
this list is an error, because it would be dropped silently on copy.

| Key | Type | Required | Meaning |
|---|---|---|---|
| `surface` | string | yes | Where people meet the capability |
| `harness` | string | yes | Agent software around the model, or `none` |
| `harness_version` | string | when there is a harness | |
| `system_prompt` | string | yes | Whose prompt runs and whether it can be read; not the prompt text |
| `tools` | list of strings | yes (`[]` = none) | Tools and connectors switched on |
| `safeguards` | string, list or object | yes | Provider classifiers, permission prompts, guardrails, as deployed |
| `data_sensitivity` | string | yes | Most sensitive data that reaches it |
| `autonomy` | string | yes | What it may do without approval |
| `notes` | string | no | |

## `input_channels[]`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `channel` | string | yes | e.g. "user prompt", "retrieved documents", "tool results" |
| `controlled_by` | string | yes | Who can put content into this channel |
| `untrusted` | true / false | yes | true when someone outside the organisation's control can write to it |
| `notes` | string | no | |

## `capabilities`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `can_read` | list of strings | yes (`[]` = nothing) | Data it can read |
| `can_do` | list of strings | yes (`[]` = nothing) | Actions with effect outside the conversation |
| `approval` | string | yes | Which actions need a person's approval, and whose |
| `memory` | true / false | yes | Keeps state between sessions |

## `failure_impact`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `worst_case` | string | yes | Worst realistic outcome if steered or wrong |
| `affected` | string | yes | Who bears it |
| `reversible` | true / false | yes | Can it be undone |
| `detection` | string | yes | How a failure would be noticed |

## `time_budget`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `decision_due` | date | yes | |
| `hours_available` | positive number | yes | Reviewer hours |
| `notes` | string | no | |

## Warnings the validator prints

Warnings do not fail validation; each is a question to take back to the requester.

- `context.tools` is `[]` while `capabilities.can_do` lists actions.
- Every input channel is marked trusted.
