# Skill standard

Every skill in this repo meets the rules below. `scripts/check_standard.py` enforces the ones
marked **[checked]**; `scripts/run_tests.sh` runs it with everything else.

## Scope rules

1. **Evaluations only.** A skill measures something; it never ships a control. No rule files,
   guidance skills, hooks, guardrails or scanners of our own. Controls and tools under test
   come from the user, reached through small adapters.
2. **No acceptance thresholds.** No pass mark, gate or recommended cut-off, in code, config,
   templates or prose. Report the number, its interval and what it means. **[checked]** for
   common gating phrases.
3. **Validity flags are allowed.** A flag says a *measurement* may not be trustworthy (the
   judge could not grade, the agent never used its tools, a scanner disagrees with itself).
   A flag has a configurable limit, is labelled as a validity flag, and never hides the number.

## Naming and packaging

4. Skill name is `<subject>-<method>`; method is `benchmark`, `redteam`, `scan` or `review`.
   Review-pipeline stages are `review-<stage>`. **[checked]**
5. A skill lives at `plugins/<plugin>/skills/<skill>/` and is self-contained: nothing it
   references resolves outside its own folder. Shared code is vendored from the maintainer
   library by the sync script. **[checked]** by `check_independence.sh`.
6. `SKILL.md` uses Agent Skills standard frontmatter only and is under 500 lines; longer
   detail goes in `references/`. **[checked]**

## Measurement skills (`-benchmark`, `-redteam`)

7. `SKILL.md` has `## PLAN`, `## RUN` and `## ANALYZE` sections. **[checked]**
8. **Cost before compute.** The plan step shows tests and model calls before anything runs.
9. **Depth** is `smoke`, `standard` or `full` (or a number). `smoke` proves the wiring only.
   **[checked]** that the three names appear.
10. **Keyless smoke test.** The skill documents a command that exercises the whole path with
    no API key (a mock model or mock server), under a `Smoke test` heading. **[checked]**
11. **Unit tests** in `tests/`, runnable in the repo's main environment without the skill's
    engine installed. **[checked]** that the directory exists and holds a test.
12. **One axis.** A run varies one thing (the model, the harness, the control, the tool, the
    modality) and holds the rest fixed. Every arm sees the same seeded samples.
13. **Results contract.** `new_experiment.sh` opens `.evals/<skill>/<label>_<date>/` with
    `manifest.json`. The skill writes `samples.jsonl` (one row per arm × target × sample),
    `findings.jsonl` where findings exist, and `summary.md` + `summary.json`.
14. **Context.** `manifest.json` carries a `context` block (surface, harness and version,
    system prompt, tools, safeguards), filled from `review.json` when there is one.
15. **Statistics.** Rates carry a 95% interval. Arms are compared paired, against a named
    baseline arm. Nondeterministic tools are repeated and their run-to-run agreement reported.
16. **Judges.** A judge model is never the model under test, is always routed explicitly, and
    the share of samples it could not grade is reported.
17. **Secrets.** Provider credentials are stripped before an eval runs; none enter a sandbox.
18. **Execution tier** is stated: T0 pure API · T1 in-memory or no-egress container ·
    T2 supervised sandbox (off by default). A T2 run is watched by a person and can be
    stopped at once: a wall-clock limit per run, a stop file, a log the operator can tail, and
    a scope file listing what the run may touch.

## Measurement quality

Guidance, not checked rules. Drawn from published practice on building safety evaluations
(Anthropic, "Building strong safety evaluations", 13 November 2026) and implemented in the
shared library (`evalkit`, `scorecard`, `inspect_runner`, `inspect_report`, `judgecheck`).

19. **Write the plan down first.** Every run registers its analysis plan (arms, baseline, what
    is measured, depth, seed, repeats, judge, corpus, and the organisation's criteria file if
    there is one) in `plan.json` before the first result. A changed plan is kept as an
    amendment, and the report lists every departure.
20. **Many comparisons, one family.** Every p-value a report prints is shown Holm-adjusted
    across the report's comparisons as well, and a difference is called unlikely to be noise
    only on the adjusted value.
21. **Show what a run can detect.** The plan step prints, for each benchmark, how precise a
    rate is at its size and the smallest paired difference it can separate.
22. **Repeat what is not deterministic.** `--repeats` (or Inspect epochs) runs a case again;
    reports give how often outcomes changed. Rows carry `repeat`.
23. **Judges see only what they grade.** No design metadata (harmful or benign, threat id,
    expected answer) in a judge prompt; direction is applied after grading. Criteria are
    atomic yes/no questions; the rubric says what does not change a verdict (disclaimers and
    warnings do not make harmful content acceptable). Rubrics are versioned, and every judged
    row records `judge`. Scores from different judges are never compared.
24. **Check the judge.** A judged skill can re-grade stored replies with a second judge (or a
    reworded rubric) and `judgecheck.py` reports agreement, kappa, whether the order of arms
    changes, and sensitivity to reply length.
25. **Say when a set is saturated.** When every arm is near the ceiling, a `near_ceiling`
    validity flag says the set catches regressions but separates arms poorly.
26. **Know where cases come from.** Custom cases carry a `source` (synthetic, a register
    incident, or an imported benchmark); a run records whether its corpus is public (bundled,
    possibly in training data) or private (supplied by the user); threats list the register
    incidents where their pattern was observed (`observed_in`).
27. **Vary one dimension at a time.** Dimensions a report breaks results down by (style,
    perturbation, persona, tactic, language) are crossed, never tied to each other.
28. **Measure the right construct.** Refusal is the right measure for clearly harmful requests
    and the wrong one for dual-use requests, where the appropriate response helps with the
    legitimate version and withholds operational detail. Measure over-refusal of legitimate
    twins on the same topic beside every harmful-request measure.

## Modality benchmarks (decision, voice, vision, image generation)

Guidance, not checked rules. These skills follow one shape so a reviewer reads them the same
way and models can be ranked as new ones are released:

29. A short threat model in `references/threat-model.md` saying where the risks come from, and
    a handful of core threats.
30. `threats.json` listing those threats and the benchmarks that measure each; the scorecard
    reads it.
31. Two lanes of evidence: *known* (a published benchmark or two, at a pinned revision) and
    *custom* (a small core set written here, scored without a judge where possible).
32. `samples.jsonl` rows tagged with `threat`, `lane`, `benchmark`, `case` and `good`, so
    `lib/scorecard.py` can compare models threat by threat.

## Guided skills (`review-*`, `-review`)

33. State what the reviewer supplies, what the skill produces, and where it is written.
34. Record what was not assessed. An absent vendor document or an untested threat is a
    finding, not a gap to leave silent.
35. Never prescribe a control or a verdict. Decision fields are left for people to fill.

## Definition of done for a new or changed skill

- `bash scripts/run_tests.sh` is green.
- The keyless smoke test in its `SKILL.md` was run and its output matches what the runbook says.
- Anything that could not be exercised here (a real API, a sandbox) is listed under
  `Not verified` in the skill's `SKILL.md` notes.
