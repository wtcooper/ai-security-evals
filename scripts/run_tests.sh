#!/usr/bin/env bash
# Run all unit tests (Python + Node) offline, no keys. Canonical libs live in tools/;
# skills get vendored copies via tools/sync_skills.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Node tests (status policy / transform / guardrail adapter) =="
node tools/tests/status_policy.test.cjs
node tools/tests/transform_response.test.cjs
node tools/tests/extract_transcript.test.cjs
for t in plugins/*/skills/*/tests/*.test.cjs; do node "$t"; done

echo
echo "== Python tests (classifier / m2s / corpus / metrics / connectors / shim / A-B-C) =="
PYTEST="${PYTEST:-.venv/bin/python -m pytest}"
$PYTEST tools/tests -q
[ -d catalog/tests ] && $PYTEST catalog/tests -q
# Each skill's tests run in their own process: skills are independent and may reuse module names.
for d in plugins/*/skills/*/tests; do
  ls "$d"/test_*.py >/dev/null 2>&1 || continue
  echo "-- $d"; $PYTEST "$d" -q
done

echo
echo "== Keyless smoke scripts =="
for s in plugins/*/skills/*/tests/smoke.sh; do [ -f "$s" ] && { echo "-- $s"; bash "$s" | tail -1; }; done

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
echo "== Skills meet docs/skill-standard.md =="
python3 scripts/check_standard.py

echo
echo "== Threat models complete and copied into their skills =="
python3 scripts/check_threat_models.py

echo
echo "== Skills are copy-paste self-contained (no escaping references) =="
bash scripts/check_independence.sh

echo
echo "All skill tests passed."
