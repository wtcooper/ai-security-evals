# Deployment context — what to capture before the threats

A feature's risk depends on where it is switched on. Record the context first, in the
`deployment` block of the answers file, using the vocabulary of the AWS Agentic AI Security
Scoping Matrix so that two reviews can be compared.

Source: AWS, "The Agentic AI Security Scoping Matrix"
(`https://aws.amazon.com/ai/security/agentic-ai-scoping-matrix/`) and the AWS Security Blog
post of 21 November 2025 that introduces it. Read on 2026-11-14 through an automated page
summary; the scope names, the two definitions and the six dimension names below are as that
reading returned them. Check the page before quoting it elsewhere.

## Two words the matrix separates

- **Agency**: the "scope of actions an AI system is permitted and enabled to take within the
  operating environment". Record it as a list of what the feature can touch and change.
- **Autonomy**: the "degree of independent decision-making and action the system can take
  without human intervention". Record it as who starts a run and where a person must act.

A feature can be high on one and low on the other. A read-only agent that runs on a
schedule has little agency and a lot of autonomy.

## The four scopes

| `aws_scope` | Name | In short |
|---|---|---|
| 1 | No Agency | A person starts it; it follows fixed paths; it reads and advises and cannot change anything |
| 2 | Prescribed Agency | A person starts it; it can prepare and carry out changes, but a person approves each consequential one |
| 3 | Supervised Agency | A person starts it and sets the objective; it then plans and acts within bounds without further approval |
| 4 | Full Agency | It starts itself from events or conditions and runs continuously with little human oversight |

Choose the scope the deployment will actually run at, not the one the product could run at.
If one deployment runs at two scopes (attended by day, scheduled by night), write two
records. If you cannot tell, leave `aws_scope` empty: the record then lists it as not
recorded, which is the honest state.

Enabling a feature often moves a deployment up a scope. Scheduled or background agents are
the clearest case, since "a person starts it" stops being true. Say so in `autonomy` when it
happens.

## The six dimensions

The matrix names six security dimensions. Use them as headings for **what is in place
today**, in `deployment.security_dimensions`. Write what exists, including "nothing". Do not
write what should exist: this skill records controls, it does not prescribe them.

| Key | Dimension | Record |
|---|---|---|
| `identity_context` | Identity Context | whose identity the agent acts under; how users, services and agents are authenticated; how delegation works |
| `data_memory_state` | Data, Memory & State Protection | what state and memory persist, where, and how they are protected |
| `audit_logging` | Audit & Logging | what is logged about actions and reasoning, where it goes, how long it is kept |
| `agent_llm_controls` | Agent & LLM Controls | guardrails, monitoring, sandboxing and isolation that are switched on |
| `agency_perimeters` | Agency Perimeters & Policies | the stated limits on what the agent may do, and what enforces them |
| `orchestration` | Orchestration | how tool access and execution flow are managed across systems |

## Other fields

- `started_by`: `human`, `event`, `schedule` or `agent`.
- `human_approval`: where a person must act, in the deployment's own words (for example
  "none", "per consequential action", "at start only").
- `feature_context`: the three questions at the top of each feature's reference file.
- `context` (top level of the answers file): the same keys every measurement skill in this
  repo records with a result: `surface`, `harness`, `harness_version`, `system_prompt`,
  `tools`, `safeguards`, `data_sensitivity`, `autonomy`, `notes`. Fill it so a test result
  cited in this review can be matched to the context it was run in.

Anything left empty is listed in the record under "Deployment context not recorded".
