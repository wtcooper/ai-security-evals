---
name: decision-model-benchmark
description: >-
  Compare decision models (TypeSafe Jev, OpenAI Decisions, Microsoft-Decision-1, Gemini
  Decision, Clef, any System One compatible server) used as a security gate, and measure how
  easily a decision can be flipped. Decision models take a state plus typed questions with a
  closed answer set (yes/no, choice, score) and return probabilities, no text. One adapter
  speaks the three wire formats; every arm gets the same seeded labelled cases and
  adversarial variants (injection, padding, option reorder, misleading option rename,
  paraphrase, encoding, extra JSON fields). Reports fail-open and fail-closed rates, flip
  rate per attack axis beside the identical-re-run noise floor, targeted attack success,
  consistency, calibration, refusal and error rates, latency and input tokens, with 95%
  intervals and a paired comparison between arms. Use when asked whether a decision model
  can gate tool calls, screen for prompt injection, route alerts or enforce a content
  policy. For chat models use model-benchmark.
license: MIT
compatibility: "Python 3.10+, standard library only (no SDKs, no extra packages). Real runs need HTTPS access to each endpoint under test and its API key in an environment variable. The keyless smoke test needs neither."
---

# decision-model-benchmark — how often a decision model is wrong, and how easily it flips

You are running this skill **on behalf of a user** who wants to put a decision model in front
of something (an agent's tool calls, retrieved documents, an alert queue, a chat assistant)
and needs to compare candidates. Drive **Plan → Run → Analyze**.

A decision model takes an input (`state`) and typed questions with a closed answer set, and
returns probabilities. The policy travels in the request, as each question's instructions and
option criteria. That makes two things attacker-reachable: the state, and any option text
that is built from data.

This skill **measures**. It sets no threshold and gives no verdict; the user's organisation
decides what is acceptable. **Execution tier: T0** (pure API): the runner sends HTTPS requests
to the endpoints named and runs nothing else.

Files: `run_bench.py` (runner), `report.py` (summary), `adapter.py` (wire formats),
`variants.py` (corpus loader and variant generator), `metrics.py`, `mock_server.py`,
`corpus/` (seed corpus), `references/` (detail), `tests/`.

---

## PLAN

### 1. Ask what is being decided
- **Which decision is the model making**, and what does a wrong answer cost in each
  direction? Fail-open (the gate lets through what it should stop) and fail-closed (it stops
  what it should let through) are reported separately; the user needs to know which one hurts.
- **Who can write to the state, and is any option text built from data?** If option labels or
  criteria can be influenced from outside, the `option_rename` and `option_order` results
  apply directly.
- **What happens to an unanswered request** in their integration (treated as allow, as block,
  or sent to a person)? Refusals and errors are reported as their own class for this reason.

### 2. Choose the arms
An arm is one model behind one endpoint. A run varies the arm and holds the cases, variants,
seed and depth fixed. The first arm is the baseline for paired comparison unless
`report.py --baseline` names another.

```
--arm name=<label>,provider=<preset>,model=<id>[,url=<endpoint>][,key-env=<ENV VAR NAME>]
      [,auth=bearer|api-key|x-goog-api-key|header:<Name>|none][,expect=<model id>]
      [,placement=user|tool_output][,price-per-m=<USD per million input tokens>]
```

| `provider=` | Wire format | Default endpoint | `verified` |
|---|---|---|---|
| `typesafe` | A `systemone` | `https://api.typesafe.ai/v1/systemone` | true |
| `openrouter` | A `systemone` | `https://openrouter.ai/api/alpha/decisions` | true |
| `microsoft` | A `systemone` | none: pass `url=<resource>/providers/microsoft/v1/systemone` | **false** |
| `clef`, `local` | A `systemone` | none: pass `url=` | **false** |
| `openai` | B `openai` | `https://api.openai.com/v1/decisions` | true |
| `azure-openai` | B `openai` | none: pass `url=` | **false** |
| `gemini` | C `gemini` | `https://generativelanguage.googleapis.com/v1beta/decisions` | true |

`verified: true` means the request and response JSON were read in the vendor's own
documentation on 2026-11-14. It does **not** mean a live call was made: none was (see Notes).
For each `false` row, `references/wire-formats.md` says exactly what was not confirmed; the
same text is in `adapter.PROVIDERS` and appears in the summary as a validity flag.

Rules for arms:
- **Keys** are read from the environment variable named by `key-env` (default
  `DMB_API_KEY`). Never put a key on the command line. Keys are held in memory, sent only in
  that arm's credential header, and written to no output file. Arm URLs are recorded without
  their query string. Values of extra `header.<Name>=<value>` settings **are** recorded, so
  they are for switches (for example `header.TypeSafe-Danger-Zone-Long-Context=true`), not
  for credentials.
- **Pin the model.** Use the most specific versioned id the vendor offers (`jev-1.14.0`, not
  `jev-latest`). The runner records the id the server reports for every request, warns when
  an id looks like an alias, and flags a run in which the reported id changed. For Microsoft
  the request carries a deployment name; add `expect=<underlying model>` to pin what the
  server should report. Gemini reports no model id, so only the requested id is on record.
- **OpenAI only:** `placement=tool_output` sends the untrusted field as a tool output instead
  of inside the user message. Run the same model as two arms to see whether position matters.
- An arm can also be set from the environment: `DMB_PROVIDER`, `DMB_FORMAT`, `DMB_URL`,
  `DMB_MODEL`, `DMB_AUTH`, `DMB_KEY_ENV`.

### 3. Choose the cases
- **Bundled seed corpus** (default): 54 synthetic labelled cases in five policy families:
  tool-call authorisation (`choice`), prompt-injection screening (`noul`), alert routing
  (`choice`, four queues), acceptable-use check (`choice`), data-sensitivity rating
  (`score`). Each record has the policy, the state, the ground-truth decision and the cost
  class of an error on it. It is small and written by one author; it compares arms, it does
  not estimate a deployment's failure rate.
- **The user's own labelled cases** (`--cases`, `--policies`): this is where the numbers
  become about their deployment. Format and labelling rules: `references/bring-your-own-cases.md`.
- **External suites** (DecisionRobust, JevBench, JevAdvBench) run with their own harnesses
  and are not bundled: `references/external-suites.md`. JevAdvBench data is CC BY-NC 4.0.

### 4. Choose depth and show the cost
| `--depth` | Cases | Variants | Per arm, bundled corpus |
|---|---|---|---|
| `smoke` | 10, spread over every family and both error classes | one technique per axis | 86 requests. Proves the wiring only; intervals are too wide to read |
| `standard` | all | one technique per axis, drawn with the seed | 466 requests |
| `full` | all | every technique | 764 requests |
| a number N | N | one technique per axis | |

`--repeats N` (default 3) sends each clean request N times; the re-runs are the noise floor
that every flip rate is read against. `--repeat-scope all` re-sends variants too.

Show the user the plan before anything is sent:
```
python run_bench.py --depth standard --plan
```
It prints requests and estimated input tokens per axis and in total. These models bill input
tokens only, so cost is tokens times the arm's price. The estimate is characters divided by
four; the count each server reports is what gets recorded.

### 5. Smoke test (no key, loopback only, a few seconds)
```
python run_bench.py --mock --depth smoke --out /tmp/dmb-smoke --force
python report.py /tmp/dmb-smoke
```
`--mock` starts `mock_server.py` in-process and runs three arms, one per wire format, against
a toy bag-of-words "model" that is deliberately sensitive to option order, injected text and
reassuring labels. **Its numbers describe the toy, not any decision model.** Expected:
- `258` requests in `samples.jsonl` (86 per arm); `mock-b` reports 2 refusals (it refuses
  base64-wrapped input), no arm reports an error.
- Noise floor `0/12` flips for every arm: the toy is deterministic.
- `mock-a` flips under `injection`, `option_order` and `option_rename`; `mock-a-gemini`
  shows option-order consistency `1.00` and the `option_order_not_sent` flag, because that
  wire format sorts option keys.
- `few_clean_correct_cases` is flagged for every arm: smoke depth is 10 cases.

To see a non-zero noise floor, run the mock as a server with random jitter and point an arm
at it:
```
python mock_server.py --port 8765 --jitter 1.5 &
python run_bench.py --arm name=noisy,provider=mock,url=http://127.0.0.1:8765/v1/systemone,model=mock-decision-a \
  --depth standard --out /tmp/dmb-noisy --force
```

### 6. Open an experiment folder
```
bash new_experiment.sh decision-model-benchmark "<label>" http-api --arms <a>,<b>
```
It prints `EXP=<path>`. If the user has a review profile (`review.json`), pass
`--review <file>` here and to `run_bench.py` so the deployment context (surface, tools,
safeguards) is recorded with the result.

---

## RUN

```
export TYPESAFE_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=...     # the user's own shell
python run_bench.py \
  --arm name=jev,provider=typesafe,model=jev-1.14.0,key-env=TYPESAFE_API_KEY \
  --arm name=luna,provider=openai,model=gpt-6-luna,key-env=OPENAI_API_KEY \
  --arm name=gemini,provider=gemini,model=gemini-decision-1,key-env=GEMINI_API_KEY \
  --depth standard --out "<EXP>"
```
- Run `--depth smoke` against each real arm first. The runner sends an arm's first request
  alone; if it errors (wrong path, bad key, unknown model) the arm is skipped with the server's
  message and the exit code is 1.
- Every arm receives the same requests in the same order: one question per request.
- Rows are appended to `<EXP>/samples.jsonl` as requests finish, one per arm × case ×
  variant × repeat. `<EXP>/results/variants.jsonl` holds the exact state and question of every
  request; `<EXP>/results/run.json` holds seed, depth, arms (without keys), the plan, the
  corpus hash and the context. If `<EXP>/manifest.json` exists it is filled in.
- 429, 5xx and network failures are retried (`--retries`, `--backoff`); what still fails is
  an `error` row. `--concurrency` (default 4) is the number of parallel requests per arm.
- To add a model later, run it with the same `--seed`, `--depth`, `--repeats` and corpus into
  a new folder and pass both folders to `report.py`. It marks the summary "Not comparable"
  when the settings differ.

---

## ANALYZE

```
python report.py "<EXP>" [--baseline <arm>]
```
writes `<EXP>/summary.md` and `<EXP>/summary.json`. Present to the user in this order:

1. **Read before trusting a number.** Validity flags and any error examples: an unverified
   adapter, a model id that moved or was never reported, a high unanswered share, too few
   clean-correct cases. A flag says a measurement may not be trustworthy; it never removes a
   number, and its limits are `report.py` options.
2. **Fail-open and fail-closed on clean cases**, separately, with intervals. Say which one
   the user said matters more. Do not merge them into one accuracy figure.
3. **Flips under attack, beside the noise floor.** For each axis: the flip rate on cases the
   arm got right when clean, the identical-re-run flip rate above it, how many flips went
   fail-open, and targeted success (the attacker's option was chosen) for `injection` and
   `option_rename`. A flip rate inside the noise floor's interval is not evidence of an effect.
4. **Consistency**: agreement under option reorder and under paraphrase, and the
   first-option pick rate against what a fully correct arm would show.
5. **Calibration and the confidence of flipped decisions.** Mean top probability of flipped
   decisions next to that of kept ones, and the kept-versus-flipped AUROC. Near 0.5 means
   "send low-confidence decisions to a person" cannot pick out the flipped ones. Confidence is
   always this skill's own (top probability and margin); vendor `confidence` fields are
   defined differently per vendor and are not compared.
6. **Refusals and errors**, clean versus attacked. An attack that turns answers into refusals
   is a finding; what it means depends on how the integration treats an unanswered request.
7. **Paired comparison** against the baseline arm: exact McNemar on the same requests. Do
   not rank arms on overlapping intervals; offer a deeper run or more cases instead.
8. Latency p50/p95 and input tokens (and cost when `price-per-m` was given).

Say plainly what the run does not show: `references/not-measured.md` lists the threats this
skill leaves out (adaptive attacks that use the returned probabilities, multilingual and
image inputs, the model as a gate inside a running agent, drift over time, bias).

Definitions and denominators for every number: `references/metrics.md`.

End by offering: the user's own cases if only the seed corpus was run; `--depth full` for a
per-technique table; an OpenAI `placement=tool_output` arm; one of the external suites.

## Notes
- **Variants keep the label by construction, not by review.** Injected text goes only into the
  field the policy names as untrusted, and every bundled policy says that approvals or
  instructions in that field do not count. Encoded variants carry the label of the decoded
  text; a flip toward the restrictive label on opaque input can be a defensible answer, which
  is why flips are split by direction. If the user writes policies without such a clause,
  injection variants may change the right answer and the flip rate is overstated.
- **Variants are fixed templates**, the same for every arm and every run. They measure
  sensitivity to known perturbations. They are a floor on what an attacker who adapts to the
  model can do.
- **Unit of analysis is the request.** Several requests share a case, so intervals are
  somewhat narrower than a per-case analysis would give.
- **Yes/no questions** are scored at the argmax (probability 0.5); `samples.jsonl` keeps the
  full distribution, so they can be re-scored at another operating point.
- **Gemini sorts option keys** before evaluation, so `option_order` cannot change what a
  Gemini arm evaluates; its row is a second noise-floor estimate and is flagged as such.
- **Secrets.** The runner starts no subprocess and no sandbox, so no credential is passed on
  to anything. Keys are never logged; server error text is recorded with the key redacted.
- **Not verified:**
  - No live decision-model API was called while building this skill; no keys were available.
    All three adapters were exercised only against `mock_server.py`, which was written from
    the same documentation as the adapter. A misreading of that documentation would pass
    the tests. Run `--depth smoke` against each real endpoint and read the errors.
  - Microsoft-Decision-1: the response JSON (field names for probabilities and token usage)
    is not shown in Microsoft's documentation and is assumed to match System One.
  - Clef, Azure OpenAI Decisions and self-hosted servers: request and response shapes were
    not read in a primary source.
  - The OpenAI `placement=tool_output` request shape follows the API reference but was not
    accepted or rejected by the real API.
  - The mapping of a Gemini HTTP 400 safety block to a refusal follows the documented error
    body and was not triggered on the real API. Error bodies for OpenAI and OpenRouter are
    not documented and are kept as text.
  - The seed corpus labels were written by one author and checked by no second rater and no
    model.
  - DecisionRobust, JevBench and JevAdvBench were not run; `references/external-suites.md`
    is from their READMEs.
