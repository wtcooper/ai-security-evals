# Contributing to ai-security-evals

Thanks for your interest. This repo hosts distributable Claude Code skills for evaluating AI security defenses. Contributions are welcome whether you're improving an existing skill, adding a new benchmark source, or proposing a new skill entirely.

## Ground rules

- **Open an issue first** for non-trivial changes (new skill, new corpus source, breaking API change). This avoids you spending time on something we'd reject for scope or design reasons.
- **Small, focused PRs** beat large ones. One topic per PR.
- **Tests required** for every behavior change. The harness's correctness is the product — we can't ship a regression.
- **No keyword classification in the eval pipeline, ever.** This rule is non-negotiable; see [`skills/ai-guardrail-eval/RESEARCH.md`](skills/ai-guardrail-eval/RESEARCH.md) §6 for why. Mock handlers used purely for local testing (e.g. `local/mock_handlers.py`) are exempt.
- **Match existing style.** Don't reformat unrelated code in your PR.

## Dev environment

```bash
# Python 3.11+; uv installs everything else
uv sync --extra dev --extra corpus

# Run unit tests (always)
uv run pytest

# Run integration tests against the bundled mock proxy (optional)
bash local/start_proxy.sh > /tmp/litellm_proxy.log 2>&1 &
# wait ~5s for curl -s http://localhost:4000/health/readiness to return 200
uv run pytest skills/ai-guardrail-eval/tests/test_local_proxy_integration.py
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

## Pull request flow

1. Fork the repo (or create a feature branch if you have write access).
2. Branch from `main`: `git checkout -b your-username/short-topic-name`.
3. Make your change with a focused commit history (rebase/squash before opening the PR if you have a messy series).
4. Run `uv run pytest` and confirm green.
5. Open the PR against `main`. Fill in the template — what changed, why, how you tested.
6. CI runs automatically. Address review comments by pushing more commits (don't force-push until review is complete; then squash if needed).
7. Once approved and CI is green, a maintainer merges (squash by default).

## What kinds of changes are easy to land

- New corpus sources (peer-reviewed benchmark, permissive license, clear citation)
- Provider implementations (real `OpenAICompatibleProvider` / `RESTProvider`)
- Skill-level docs improvements
- Test coverage on edge cases
- Performance improvements with a measured baseline → after delta

## What needs design discussion first

- New skills (open an issue with the SKILL.md frontmatter draft)
- Changes to the four-outcome taxonomy or judge prompt
- Changes to corpus tier assignment, scoring weights, or schema
- Breaking changes to the `Provider` / `Judge` interface

## Security issues

**Don't open a public issue for security vulnerabilities.** See [`SECURITY.md`](SECURITY.md) for the private reporting flow.

## Code of conduct

By participating you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).
