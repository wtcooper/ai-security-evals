#!/usr/bin/env bash
# Keyless smoke test of the whole ai-review pipeline on bundled, fictional example inputs:
#   scope-validate -> evidence-append -> plan -> criteria-validate -> report
#
#   bash tests/smoke.sh [skills-dir] [out-dir]
#
# skills-dir is the directory that holds the five review-* skills side by side (the
# plugin's skills/ directory). It defaults to the directory this skill sits in.
# No API key, no network. The last line printed is `smoke ok: <path to report.md>`.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL="$(dirname "$HERE")"
SKILLS="${1:-$(dirname "$SKILL")}"
OUT="${2:-$(mktemp -d)}"
PY="${PYTHON:-python3}"

for s in review-scope review-evidence review-threat-model review-criteria; do
  [ -d "$SKILLS/$s" ] || {
    echo "smoke: $s not found in $SKILLS. This test needs the whole ai-review plugin;" \
         "for review-report alone, run the command under 'Smoke test' in its SKILL.md." >&2
    exit 1; }
done
mkdir -p "$OUT"
rm -f "$OUT/evidence.jsonl"

echo "== 1. review-scope: validate the example profile"
"$PY" "$SKILLS/review-scope/scripts/validate_review.py" \
  "$SKILLS/review-scope/examples/review.example.json"
cp "$SKILLS/review-scope/examples/review.example.json" "$OUT/review.json"

echo "== 2. review-evidence: append claims, an absence, and an open-weights harvest"
EV="$SKILLS/review-evidence/scripts/evidence.py"
"$PY" "$EV" append --file "$OUT/evidence.jsonl" --absent --captured 2026-11-11 \
  --claim "No system card or safety evaluation report was found for example-model-1-20261101." \
  --threats harmful-assistance,jailbreak,agent-goal-hijack \
  --source https://example.com/docs --provenance reviewed --kind system_card \
  --note "Searched the vendor documentation index and trust centre (fictional example)."
"$PY" "$EV" append --file "$OUT/evidence.jsonl" --captured 2026-11-11 \
  --claim "The vendor documentation states the model may follow instructions that appear in tool results." \
  --threats agent-goal-hijack --source https://example.com/docs/limitations \
  --provenance published --kind limitation --note "A stated limitation, not a measurement."
"$PY" "$EV" from-weights "$SKILLS/review-evidence/examples/weights.example.json" \
  --file "$OUT/evidence.jsonl" --captured 2026-11-11
"$PY" "$EV" append --file "$OUT/evidence.jsonl" --captured 2026-11-13 \
  --claim "On the core profile at standard depth the bare model's result for tool-borne injection carries a low-utility validity flag." \
  --threats agent-goal-hijack,harmful-assistance,over-refusal,jailbreak,insecure-code,memory-poisoning \
  --source .evals/model-benchmark/example-model-1-core_2026-11-12/summary.md \
  --pointer .evals/model-benchmark/example-model-1-core_2026-11-12/summary.md \
  --provenance self_run --kind result --note "Bare API, not the harness."

echo "== 3. review-threat-model: threat model and test plan"
"$PY" "$SKILLS/review-threat-model/scripts/plan.py" --review "$OUT/review.json" --out-dir "$OUT"
"$PY" "$EV" validate "$OUT/evidence.jsonl" --known-threats "$OUT/test-plan.json"

echo "== 4. review-criteria: validate the example criteria against the experiment dates"
cp "$SKILLS/review-criteria/examples/criteria.example.json" "$OUT/criteria.json"
"$PY" "$SKILLS/review-criteria/scripts/criteria.py" validate "$OUT/criteria.json" \
  --evals "$HERE/fixtures/evals"

echo "== 5. review-report: compile"
"$PY" "$SKILL/scripts/compile_report.py" --review "$OUT/review.json" \
  --evidence "$OUT/evidence.jsonl" --plan "$OUT/test-plan.json" \
  --criteria "$OUT/criteria.json" --evals "$HERE/fixtures/evals" --out "$OUT/report.md"

echo "== report sections"
grep '^## ' "$OUT/report.md"
for want in "What was reviewed" "Evidence, with provenance" "Results" "Threats not covered" \
            "criteria beside the results" "Decision" "Conditions" "Sign-off"; do
  grep -q "^## .*$want" "$OUT/report.md" || { echo "smoke: section missing: $want" >&2; exit 1; }
done
grep -qx -- "- Decision: " "$OUT/report.md" || { echo "smoke: decision field is not blank" >&2; exit 1; }
echo "smoke ok: $OUT/report.md"
