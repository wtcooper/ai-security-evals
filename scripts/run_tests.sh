#!/usr/bin/env bash
# Run all unit tests (Python + Node) offline, no keys. Canonical libs live in tools/;
# skills get vendored copies via tools/sync_skills.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Node tests (status policy / transform / guardrail adapter) =="
node tools/tests/status_policy.test.cjs
node tools/tests/transform_response.test.cjs
node tools/tests/extract_transcript.test.cjs
node skills/control-isolate/tests/generic_guardrail.test.cjs

echo
echo "== Python tests (classifier / m2s / corpus / metrics / connectors / shim / A-B-C) =="
PYTEST="${PYTEST:-.venv/bin/python -m pytest}"
$PYTEST tools/tests skills/control-bench/tests -q

echo
echo "== Vendored copies in sync with tools/ (no drift) =="
bash tools/sync_skills.sh >/dev/null
if ! git diff --quiet -- skills/*/lib skills/app-eval/corpus skills/control-isolate/corpus \
       skills/*/new_experiment.sh skills/*/install_dependencies.sh skills/app-redteam/objectives; then
  echo "DRIFT: a skill's vendored lib/corpus/script differs from tools/. Commit the sync output." >&2
  exit 1
fi
echo "  ok"

echo
echo "All skill tests passed."
