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
    T2 supervised sandbox (off by default).

## Modality benchmarks (decision, voice, vision, image generation)

Skills that evaluate a model of one modality follow one shape, so a reviewer reads them the
same way and models can be ranked as new ones are released.

19. **Threat model first.** `references/threat-model.md` is a copy of the asset class's formal
    threat model from `threat-models/` (written by the sync script, never edited in place). It
    names every threat in `threats.json` with the same id. **[checked]** by
    `scripts/check_threat_models.py`, which also requires every skill that evaluates an asset
    class to carry one.
20. **`threats.json`** at the skill root lists those threats: `id`, `name`, `risk_source`, and
    `lanes` naming the benchmarks that measure each threat in each lane. A threat with no
    benchmark in either lane says so and becomes a design-review question. **[checked]**
21. **Two lanes of evidence.** The *known* lane uses at most two published benchmarks per skill,
    fetched at a pinned revision and never vendored unless the licence allows and the data is
    small. The *custom* lane is one small core set authored here, about 10–20 cases per threat,
    scored deterministically (a canary, a tool call, a decoded payload) wherever possible and
    by a judge only where nothing else can decide.
22. **Scorecard.** `samples.jsonl` rows carry `threat`, `lane`, `benchmark`, `case` and `good`
    (true = the safe outcome; null = no verdict), and `lib/scorecard.py` turns one or more runs
    into a per-threat, per-lane comparison of models with intervals, an ordering, and the
    differences unlikely to be noise. **[checked]** that the scorecard is vendored.

## Guided skills (`review-*`, `-review`)

23. State what the reviewer supplies, what the skill produces, and where it is written.
24. Record what was not assessed. An absent vendor document or an untested threat is a
    finding, not a gap to leave silent.
25. Never prescribe a control or a verdict. Decision fields are left for people to fill.

## Definition of done for a new or changed skill

- `bash scripts/run_tests.sh` is green.
- The keyless smoke test in its `SKILL.md` was run and its output matches what the runbook says.
- Anything that could not be exercised here (a real API, a sandbox) is listed under
  `Not verified` in the skill's `SKILL.md` notes.
