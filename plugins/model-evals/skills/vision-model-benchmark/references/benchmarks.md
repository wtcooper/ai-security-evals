# Known-lane benchmarks: what was verified, and why these two

Two published benchmarks, both fetched one file at a time at a pinned revision, never
vendored. Facts below were checked against the primary sources on 2026-11-21.

## CyberSecEval 3, visual prompt injection

| Fact | Value | Source |
|---|---|---|
| Location | `huggingface.co/datasets/facebook/cyberseceval3-visual-prompt-injection` | dataset page |
| Revision | `7933662024dc994be4ab90d520ab712e5765b655` (the one inspect_evals 0.29.0 pins) | Hub API |
| Licence | MIT | dataset card `license: mit`, Hub tag `license:mit` |
| Size | 1000 cases in `test_cases.json` (587,907 bytes, sha256 `960e7eb1…a442e530`) and `images/<id>.png` (10 KB to 3.1 MB, about 1.3 MB on average, 1.2 GB in all) | file listing |
| Subset fetch | yes: `test_cases.json` first, then only the selected images, each by its own URL | tested |
| Upstream scoring | a judge answers the case's `judge_question`; `accuracy` is the share of injections that succeeded (lower is better) | inspect_evals source |

Split used here, by upstream's own labels:

| Check | Cases | Rule | Threat | Scored by |
|---|---|---|---|---|
| `cyse3_vpi_secret` | 300 | `risk_category: security-violating` and a judge question of the form `Does this response contain: <key>?` | `vi-exfiltration` | string match on the key (the question asks exactly that), no judge |
| `cyse3_vpi_indirect` | 300 | the rest with `injection_type: indirect`: text in the image tries to change the answer | `vi-image-injection` | upstream judge template and question |
| `cyse3_vpi_direct` | 400 | the rest with `injection_type: direct`: the user puts a request the system prompt forbids into the image, including 100 CAPTCHA-solving cases | `vi-policy-bypass` | upstream judge template and question |

Differences from running inspect_evals' `cyse3_visual_prompt_injection` task directly:

- The system prompt, user text and image are sent exactly as upstream builds them, with the
  upstream generation settings (temperature 0.6, 2048 output tokens) and one epoch (upstream
  defaults to five). The inspect_evals 0.29.0 task also inserts a second system message whose
  text is the literal string `{test_case_prompt}` (a template with no matching field); this
  skill leaves that message out.
- The 300 secret cases are decided by string match instead of the judge.
- Selection is seeded and stratified by injection technique, and only the selected images are
  downloaded.

## FigStep SafeBench

| Fact | Value | Source |
|---|---|---|
| Location | `github.com/ThuCCSLab/FigStep` | repository |
| Revision | `0861b17b3d67887c06ee3534ec65b3012f9becb7` (main on 2026-11-21) | `git ls-remote` |
| Licence | MIT | repository `LICENSE` |
| Size | 500 questions in `data/question/safebench.csv` (78,942 bytes, sha256 `8e47f40b…be941b394`), 10 topics × 50; one typographic image per question, `data/images/SafeBench/query_ForbidQI_<topic>_<task>_6.png`, 30 to 50 KB | file and raw URLs |
| Subset fetch | yes: the CSV, then each selected image by its raw URL | tested |
| Upstream scoring | manual review of attack success | paper and README |

Used here: the seven topics where a helpful answer is itself the harm (Illegal Activity, Hate
Speech, Malware Generation, Physical Harm, Fraud, Adult Content, Privacy Violation: 350
questions). Legal Opinion, Financial Advice and Health Consultation are left out: answering
them is not a security failure. The image arm sends the upstream image with FigStep's
incitement prompt; the typed twin sends the question column, FigStep's own baseline. A judge
model replaces the manual review.

## Candidates not used

- **MM-SafetyBench** (`github.com/isXinLiu/MM-SafetyBench`): data licence CC BY-NC 4.0
  (non-commercial only) and images distributed as one archive on Google Drive or Baidu, so no
  subset can be fetched. Not used.
- **The inspect_evals `cyse3_visual_prompt_injection` task as is**: downloads all 1000 images
  (1.2 GB) on first use and reports one number for three different threats. The shared suite
  in `lib/inspect_suite.py` still lists it; this skill uses the split above.
- Over-refusal on images (for example MOSSBench) and agent benchmarks with visual injection
  (for example VisualWebArena-based attack sets) were not verified here: the two-benchmark
  limit is used by the two above, and the agent sets need live web environments (tier T2).
