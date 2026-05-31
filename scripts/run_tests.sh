#!/usr/bin/env bash
# Run all unit tests (Python + Node) for the security-eval skills. Offline, no keys.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Node tests (status policy / transform / guardrail adapter) =="
node skills/_shared/tests/status_policy.test.cjs
node skills/_shared/tests/transform_response.test.cjs
node skills/control-isolate/tests/generic_guardrail.test.cjs

echo
echo "== Python tests (m2s / corpus / metrics / connectors / shim / A-B-C) =="
PYTEST="${PYTEST:-.venv/bin/python -m pytest}"
$PYTEST skills/_shared/tests skills/control-bench/tests -q

echo
echo "All skill tests passed."
