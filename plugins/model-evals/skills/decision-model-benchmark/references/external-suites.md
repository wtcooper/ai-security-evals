# External decision-model suites

Three public suites target decision models directly. This skill does **not** bundle their
data or code. Each has its own harness; run it beside this skill against the same endpoints
and report its numbers next to this skill's, with the source named.

Everything below is from each project's README as read on 2026-11-14. **None of these
suites was run while building this skill.** Commands are quoted from the READMEs and may
have changed; check the repository first. Licences must be re-checked by whoever uses the
data.

| Suite | Repository | Code licence | Data licence | What it adds to this skill |
|---|---|---|---|---|
| DecisionRobust | https://github.com/Yifan-Lan/DecisionRobust | MIT | Not stated in the README; it points to `THIRD_PARTY_NOTICES.md` and the Hugging Face dataset card `yflantmy/DecisionRobust`. **Unchecked.** | A larger curated attack set (1,058 examples from 441 questions) and image attacks |
| JevBench | https://github.com/fstandhartinger/jevbench | MIT, covering "this harness and the 72 original public decisions"; other tiers and upstream data keep their own terms (`THIRD-PARTY.md`) | as left | Clean accuracy, Brier, ECE, paraphrase consistency, latency and cost on a broader task mix |
| JevAdvBench | https://github.com/JevAdvBench/JevAdvBench | MIT | **CC BY-NC 4.0 (non-commercial)** for questions, labels, attack variants, model outputs and metadata | 812 questions with 12 single-edit attack variants each, and raw responses for `jev-1.13.0` |

## DecisionRobust

- Five suites: `text_adversarial_curated` (141), `text_injection_curated` (374),
  `image_perturbation_curated` (200), `image_overlay_curated` (223),
  `image_instruction_curated` (120).
- Metrics: **Flip ASR** (among clean-correct pairs, the adversarial answer is wrong) and
  **Target ASR** (wrong and equal to the attacker's target), with accuracy and coverage.
  Errors and refusals are excluded and a zero denominator is undefined. These are the same
  definitions as this skill's flip rate and targeted success, so the numbers can sit in the
  same table, on different cases.
- Adapters listed: Jev SDK, Liquid D1, OpenAI Decisions, a "native-compatible server"
  (`configs/models/local_server.json`, endpoint from `DECISION_ENDPOINT`), and a custom
  Python adapter (`configs/models/custom.json`, interface in `examples/custom_adapter.py`).
  No Gemini or Microsoft adapter is listed. Microsoft-Decision-1 uses the System One format,
  so the native-compatible server config pointed at
  `<resource>/providers/microsoft/v1/systemone` may work; that is untested, and the auth
  header it sends was not checked.
- From its README:
  ```
  git clone https://github.com/Yifan-Lan/DecisionRobust.git && cd DecisionRobust
  python -m venv .venv && source .venv/bin/activate && python -m pip install -e .
  decisionrobust download --output downloads/release-v1.3.0
  export DECISION_ENDPOINT=http://127.0.0.1:8000/systemone
  decisionrobust evaluate --release-dir downloads/release-v1.3.0 \
    --model-config runs/my-model-config.json --suites text_adversarial_curated \
    --limit 3 --output runs/my-model-smoke
  decisionrobust summarize --release-dir downloads/release-v1.3.0 --output runs/my-model-smoke
  ```
  It writes `summary.json`, `outcomes.jsonl`, `predictions.jsonl`, `requests.jsonl` and
  `run.json` to the output directory.
- Wiring check without a key: this skill's mock speaks the System One format, so
  `python mock_server.py --port 8765` with `DECISION_ENDPOINT=http://127.0.0.1:8765/v1/systemone`
  should exercise DecisionRobust's local-server path. Not tried.

## JevBench

- Public task files: `datasets/public/original.jsonl` (72 decisions),
  `datasets/public/easy.jsonl` (48), `datasets/public/hard.jsonl` (111). The README says the
  hard tier was written by language models and cross-reviewed; held-out tiers are not
  published.
- Adapters: `typesafe` (the `/v1/systemone` format and rebuilds that share it),
  `systemone_list`, `gradio_space`, `local_openjev`, `openai_compat` (ordinary chat models
  with a JSON schema). `--endpoint` points `typesafe` at another base URL and `--key-env`
  names the variable holding the key. No OpenAI Decisions or Gemini adapter is listed.
- From its README:
  ```
  python -m jevbench.cli run --tasks datasets/public/original.jsonl \
    --adapter typesafe --model jev-latest --key-env TYPESAFE_API_KEY \
    --price-in-per-m 0.042 --price-out-per-m 0 \
    --results RUN/results.jsonl --raw-dir RUN/raw \
    --ledger RUN/ledger.jsonl --cap-usd 15 --manifest RUN/manifest.json
  python -m jevbench.cli summarize --tasks datasets/public/original.jsonl \
    --results RUN/results.jsonl --public-export RUN/summary.json
  ```
  The README example uses the alias `jev-latest`; use a versioned id so the run can be
  repeated.
- Its Brier score is the multi-class sum and its ECE uses top-label confidence in 10
  equal-width bins, the same definitions as `metrics.py`. Its composite "JevBench Score"
  weights intelligence, calibration, speed and cost; report the components, since a weighted
  composite embeds someone else's priorities.

## JevAdvBench

- Data: `data/Bench1.0.json` (812 typed questions over 66 scenarios: 314 `noul`, 337
  `choice`, 161 `score`) and `data/AdvBench1.0.json` (9,744 single-edit variants, 12 per
  question, in four families: question edits, state edits, injection, structure). Also on
  Hugging Face as `Hangtao/JevAdvBench`.
- **Licence: the data is CC BY-NC 4.0.** Do not copy it into this repository or into a
  commercial product's test set. Using it for an internal, non-commercial evaluation is a
  licence question for the user's organisation, not something this skill can settle.
- The README covers `jev-1.13.0` only and does not say how to point the code at another
  model or endpoint; it reads the key from `TYPESAFE_API_KEY`. Its offline analysis
  (`bash data_analysis/run_all.sh`) recomputes the paper's numbers from stored responses
  without any request.
- The README says 82.4% of its labels are model-derived (`standard_answer.source` is
  `jev_default` rather than `human_review`). A flip rate on model-derived labels measures
  change from the model's own earlier answer, not error against ground truth. Say which
  label source a quoted number uses.
- The arXiv abstract and the README have been reported to disagree on the question count
  and headline flip rate. Quote a number only with the document it came from.

## Related: option-channel attack code

https://github.com/ArminAzizi98/option-channel-attack (MIT) holds the code for the paper
that renamed the permissive option of a guardrail question and added six lines of unrelated
log text. It evaluates open-weight models on a GPU, not hosted decision APIs. This skill's
`option_rename` and `padding.log_lines` axes follow the same idea with its own labels and
log lines; nothing was copied from that repository.

## Running external cases through this skill instead

If a suite's licence allows you to keep a converted copy, its rows fit this skill's format:
one policies entry per distinct (instructions, options) pair and one case per row (see
`bring-your-own-cases.md`). Three cautions:

- This skill needs a ground-truth label per case. Rows labelled with a model's own answer
  are not ground truth.
- This skill generates its own variants from clean cases. Do not also feed it another suite's
  pre-built attack variants as if they were clean cases.
- Keep converted files out of version control unless the licence permits redistribution.
  JevAdvBench's does not permit commercial use.

No converter is shipped, because the record schemas of these suites were not read in
enough detail to write one that could be trusted.
