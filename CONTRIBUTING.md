# Contributing to ai-security-evals

Thanks for your interest. This repo hosts distributable agent skills, packaged as Agent Plugins, for evaluating the security of AI models, agents, applications and the defences around them. Contributions are welcome whether you're improving an existing skill, adding a new benchmark source, or proposing a new skill entirely.

## Ground rules

- **Open an issue first** for non-trivial changes (new skill, new corpus source, breaking API change). This avoids you spending time on something we'd reject for scope or design reasons.
- **Small, focused PRs** beat large ones. One topic per PR.
- **Tests required** for every behavior change. The harness's correctness is the product — we can't ship a regression.
- **No keyword classification in the eval pipeline, ever.** Verdicts come from the target's own block signal, a deterministic detector, or a judge model. Mock handlers used purely for local testing (`targets/proxy/mock_handlers.py`) are exempt.
- **Evaluations only.** A skill measures a control; it never ships one. No rule files, guardrails or scanners of our own, and no acceptance thresholds.
- **Match existing style.** Don't reformat unrelated code in your PR.

## Dev environment

```bash
# Python 3.11+; uv installs everything else
uv sync --extra dev --extra corpus

# Run every offline check: Node + Python tests, vendoring drift, plugin conformance
bash scripts/run_tests.sh
```

If you add a runtime dep, update `pyproject.toml` and run `uv sync` so `uv.lock` is updated and committed.

## Sign-off (DCO)

We use the [Developer Certificate of Origin](https://developercertificate.org/) for all contributions. Add a `Signed-off-by` trailer to every commit:

```bash
git commit -s -m "your message"
# expands to: Signed-off-by: Your Name <your.email@example.com>
```

By signing off you're asserting that you wrote the patch (or have the right to submit it under the project's MIT license). This is enforced by a CI check; PRs without sign-off won't merge.

Set your git identity once if you haven't:
```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

To retroactively sign off a series of unsigned commits:
```bash
git rebase --signoff HEAD~N      # where N = number of commits to fix
git push --force-with-lease
```

## Branching model

We use a light gitflow setup:

- **`develop`** is the active development branch and the default branch — `git clone` checks it out, all PRs target it, and that's where work integrates day-to-day.
- **`main`** is the stable release branch. It only receives PRs **from `develop`** (typically at release time, possibly with a tag). Never PR a feature branch directly to main.

## Pull request flow

1. Fork the repo (or create a feature branch if you have write access).
2. Branch from `develop`: `git checkout develop && git pull && git checkout -b your-username/short-topic-name`.
3. Make your change with a focused commit history (rebase/squash before opening the PR if you have a messy series).
4. Run `bash scripts/run_tests.sh` and confirm green.
5. Open the PR against **`develop`**. Fill in the template — what changed, why, how you tested.
6. CI runs automatically. Address review comments by pushing more commits (don't force-push until review is complete; then squash if needed).
7. Once approved and CI is green, a maintainer merges (squash by default).
8. Promotion to `main` is a separate PR cut from `develop` by a maintainer, typically tied to a release. After merging to `main`, the maintainer merges `main` back into `develop` so any release-specific commits (tags, version bumps) are reflected in active dev.

## What kinds of changes are easy to land

- New corpus sources (peer-reviewed benchmark, permissive license, clear citation)
- A new adapter for a tool, scanner or guardrail vendor (one file, no harness change)
- A newly verified benchmark entry in an existing suite
- Skill-level docs improvements
- Test coverage on edge cases

## What needs design discussion first

- New skills (open an issue with the SKILL.md frontmatter draft; names follow `<subject>-<method>`, frontmatter uses the Agent Skills standard fields only)
- New plugins, or moving a skill between plugins
- Changes to the shared results contract (`manifest.json`, `samples.jsonl`, `findings.jsonl`) or to the statistics in `tools/lib/evalstats.py`
- Changes to corpus tier assignment or scoring

## Security issues

**Don't open a public issue for security vulnerabilities.** See [`SECURITY.md`](SECURITY.md) for the private reporting flow.

## Code of conduct

By participating you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).
