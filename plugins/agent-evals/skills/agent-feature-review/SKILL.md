---
name: agent-feature-review
description: >-
  Guided security review of a new agent feature being switched on for a model or product the
  organisation already uses, when someone asks "can we enable this?" and no single benchmark
  answers it. One threat-and-test template per feature type: computer use and browser
  control, persistent memory, connectors and MCP servers, code execution sandboxes, file
  search and RAG, multi-agent and subagents, scheduled and background agents. Each template
  says what the feature changes about the trust boundary and, per threat, the review
  questions, the vendor evidence to look for, which existing benchmark could test it and
  through which skill, and what has no standardized test. Threats carry OWASP LLM 2025,
  OWASP Agentic and MITRE ATLAS ids where verified. Writes a JSON and markdown record,
  evidence.jsonl rows, and a list of every threat left unassessed. It prescribes no
  control and makes no recommendation. For an image-generation model use image-generation-benchmark.
license: MIT
compatibility: "Python 3.10+ standard library only. No API key and no network access are needed by the scripts."
---

# agent-feature-review — security review of a new agent feature

You are running this skill **on behalf of a reviewer** whose organisation is about to turn
on an agent feature. You pick the template for the feature, capture the deployment context,
walk the reviewer through each threat's questions, record the evidence they bring, and write
a record that separates what was examined from what was not.

Three rules hold throughout:

- **You record. You do not decide.** No rating, no "approve", no bar. The decision block is
  written empty.
- **You do not prescribe controls.** Record the controls that are in place and which were
  examined. Do not propose ones to add.
- **Nothing is dropped silently.** Every threat in the template ends up in the record as
  `evidence_recorded`, `answers_only`, `not_applicable` (with a reason) or `not_assessed`.

## What the reviewer supplies

| Input | Used for |
|---|---|
| The feature type, and the exact product, vendor, model and feature version | choosing the template; the record's subject |
| The deployment context: what the agent can touch, who starts a run, where a person approves, whose identity it uses | the `deployment` block (`references/deployment-context.md`) |
| Vendor documents for this feature: system card, product and security documentation, data-handling terms | `vendor_evidence` and `vendor_absent` per threat |
| Results of any tests already run, with the path of their summary file | `tests` per threat |
| What they checked themselves in a console, a configuration or a contract | `reviewed` per threat |

What they cannot supply stays empty and is reported as not assessed.

## Steps

Work in a review folder. If this is part of a wider review, use that review's folder and
pass its `evidence.jsonl` with `--evidence`; otherwise create
`.evals/agent-feature-review/<label>_<date>/`. Below, `$R` is that folder.

### 1. Pick the feature template

```
python scripts/write_review.py --list
```

| Feature type | Template | Reference |
|---|---|---|
| Computer use, browser control | `computer-use` | `references/computer-use.md` |
| Persistent memory | `memory` | `references/memory.md` |
| Connectors, MCP servers | `connectors-mcp` | `references/connectors-mcp.md` |
| Code execution sandboxes | `code-execution` | `references/code-execution.md` |
| File search, RAG | `file-search-rag` | `references/file-search-rag.md` |
| Multi-agent, subagents | `multi-agent` | `references/multi-agent.md` |
| Scheduled or background agents | `background-agents` | `references/background-agents.md` |

A product that turns on several at once (an agent with connectors and memory that runs on a
schedule) gets one record per feature type. Read the reference file with the reviewer,
starting with "What the feature changes about the trust boundary".

### 2. Get a blank form

```
python scripts/write_review.py --feature computer-use --blank > $R/answers.json
```

The form lists every threat with its questions, and shows how to fill each kind of entry.

### 3. Capture the deployment context

Follow `references/deployment-context.md`. Ask:

- What can the agent touch and change (agency)? Who starts a run and where must a person act
  (autonomy)? Which of the four scopes of the AWS Agentic AI Security Scoping Matrix does
  that put it in?
- For each of the matrix's six dimensions, what is in place today? "Nothing" is an answer.
- The three feature-specific context questions at the top of the reference file.

### 4. Go through the threats

For each threat in the reference file, ask its review questions and record:

- **Answers** in the reviewer's words. An answer with nothing behind it is recorded as such.
- **Vendor evidence**: what a document says, in one sentence, with its URL (`published`
  for the vendor's own document, `harvested` for a third party).
- **Vendor absent**: what you looked for and where it was not. This is a finding.
- **Tests**: a result that exists, with the path to its summary. If the reference names a
  benchmark that this repo can run (it says through which skill), ask the reviewer whether
  to run it now; that is a separate skill with its own plan and cost. Do not report a
  benchmark as run because it exists.
- **Reviewed**: something the reviewer examined themselves.
- **Not applicable**: `"applies": false` and the reason.

Keep the reviewer honest about what a benchmark covers. The reference file states each
one's limits, and `references/benchmarks.md` says how each description was verified. A
result on a model through the bare API is not a result on the vendor's product.

### 5. Write the record

```
python scripts/write_review.py --feature computer-use --answers $R/answers.json --out $R
```

Read the printed `NOT ASSESSED` and `ANSWERS ONLY` lines back to the reviewer and ask
whether each gap is known and intended. Then hand the record on with the decision block empty.

## What is written, and where

All in `$R`:

| File | Contents |
|---|---|
| `<feature>_review.json` | subject, deployment context, per threat: status, answers, evidence, vendor material not found, benchmarks available and whether one was cited, what has no standardized test; lists of threats by status; an empty decision block |
| `<feature>_review.md` | the same for people: context, threat table, "Not assessed", "No standardized test exists for", per-threat detail |
| `evidence.jsonl` | one row per claim, appended; rows already present are not written again |

Evidence rows follow the `review-evidence` skill's format, which owns it: `id` (assigned on
append), `claim`, `threats`, `source`, `captured`, `provenance` (`published`, `harvested`,
`self_run`, `reviewed`), `note`, plus `absent`, `kind` and `pointer`. Threat ids are the
template's own (`cu-01`, `mem-03`, `mcp-02` …); the OWASP and ATLAS ids of each threat are
in the record. If the review has a test plan with its own threat ids, pass
`--threat-map map.json` (`{"cu-01": ["<plan id>"], ...}`).

## Stating what was not assessed

- `not_assessed`: nothing was supplied. Listed by id, and written to evidence as
  `Not assessed: …` with `absent: true`.
- `answers_only`: the reviewer answered questions but cited no document, test or finding.
  Listed separately; say plainly that it rests on the reviewer's statement.
- `evidence_recorded`: something was written down. It does not mean the threat is addressed
  or that the evidence is good.
- **Vendor material not found**: listed with where the reviewer looked.
- **Benchmarks available and not run**: listed by name. A benchmark that exists is not a
  result.
- **No standardized test exists for**: copied from the template for every applicable threat.
  These parts cannot be measured with a public benchmark however much time is available;
  the record says so rather than leaving it out.
- **Deployment context not recorded**: every empty context field.

## Smoke test (no key, no network, under a second)

```
python scripts/write_review.py --feature computer-use \
  --answers examples/computer-use.answers.example.json --out /tmp/afr-smoke
```

Expected: `computer-use: 7 threats — 3 evidence_recorded, 1 answers_only, 1 not_applicable,
2 not_assessed`, with `cu-04` and `cu-05` named as not assessed, `cu-02` as answers only,
two deployment-context items not recorded, and 8 evidence rows. The example describes an
invented vendor and invented results.

Unit tests: `python -m pytest tests -q`.

## Notes

- `templates/<feature>.json` is the source of truth. The reference files are generated from
  it by `python scripts/templates.py --render`; a unit test fails if they differ.
- `lib/evalkit.py` is a vendored copy of the repo's shared helpers, used for the context
  keys every skill records. Do not edit it here.
- Framework ids were checked against the OWASP Top 10 for LLM Applications 2025, the OWASP
  Top 10 for Agentic Applications 2026 (the December 2025 PDF) and MITRE ATLAS data release
  2026.10. A threat with no id that was verified to fit carries none.
- Skills named as routes (`model-benchmark`, `app-benchmark`, `app-redteam`,
  `agent-misuse-benchmark`, `security-tool-benchmark`) are the names in this repo's plan.
  Check that the skill is installed and supports the case before promising a run.
- Not verified:
  - No benchmark named in the templates was run for this skill. Most were read from the
    paper abstract only; `references/benchmarks.md` says which, and what was not checked
    (code location, licence, dataset details).
  - The AWS scoping matrix and the two vendor-neutral OWASP lists were read on 2026-11-14;
    the AWS page through an automated summary rather than line by line.
  - The attribution of SandboxEscapeBench to the UK AI Security Institute comes from a
    search listing of AISI's blog, not from the paper.
  - `agent-misuse-benchmark` and `security-tool-benchmark` were being built when this was
    written; what they support was taken from the repo plan, not from running them.
  - The evidence rows were checked once against the `review-evidence` validator as it stood
    on 2026-11-14 (0 errors). That skill owns the format; if it changes,
    `scripts/_evidence.py` here must follow.
  - "None found" for a benchmark means a single survey on 2026-11-14 found none.
