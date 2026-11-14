#!/usr/bin/env bash
# Run all unit tests (Python + Node) offline, no keys. Canonical libs live in tools/;
# skills get vendored copies via tools/sync_skills.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Node tests (status policy / transform / guardrail adapter) =="
node tools/tests/status_policy.test.cjs
node tools/tests/transform_response.test.cjs
node tools/tests/extract_transcript.test.cjs
node plugins/defense-evals/skills/control-isolate/tests/generic_guardrail.test.cjs

echo
echo "== Python tests (classifier / m2s / corpus / metrics / connectors / shim / A-B-C) =="
PYTEST="${PYTEST:-.venv/bin/python -m pytest}"
$PYTEST tools/tests plugins/defense-evals/skills/control-bench/tests plugins/model-evals/skills/model-benchmark/tests -q

echo
echo "== Vendored copies in sync with tools/ (no drift) =="
bash tools/sync_skills.sh >/dev/null
if ! git diff --quiet -- plugins/*/skills/*/lib plugins/*/skills/*/corpus \
       plugins/*/skills/*/new_experiment.sh plugins/*/skills/*/ephemeral_repo.sh plugins/*/skills/*/install_dependencies.sh \
       plugins/*/skills/*/objectives; then
  echo "DRIFT: a skill's vendored lib/corpus/script differs from tools/. Commit the sync output." >&2
  exit 1
fi
echo "  ok"

echo
echo "== Plugins conform to Agent Plugins 1.0.0; generated manifests current =="
python3 scripts/check_plugins.py
python3 scripts/gen_manifests.py --check

echo
echo "== Skills are copy-paste self-contained (no escaping references) =="
bash scripts/check_independence.sh

echo
echo "All skill tests passed."
