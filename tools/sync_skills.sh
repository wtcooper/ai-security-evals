#!/usr/bin/env bash
# Vendor the canonical runtime libs (tools/lib) and the prebuilt corpus into each
# standalone skill, so every skill folder is self-contained (no cross-skill imports).
#
# tools/ is the single source of truth; skills get committed copies. CI runs this +
# `git diff --exit-code` to ensure the vendored copies never drift.
#
#   bash tools/sync_skills.sh
set -euo pipefail
cd "$(dirname "$0")"                 # tools/
ROOT=".."
PY="${PYTHON:-$ROOT/.venv/bin/python}"

# Skills live at plugins/<plugin>/skills/<skill>; resolve by skill name (names are unique).
sd() {
  local d; d=$(ls -d "$ROOT"/plugins/*/skills/"$1" 2>/dev/null | head -1)
  [ -n "$d" ] || { echo "sync_skills: no skill named $1 under plugins/" >&2; exit 1; }
  printf '%s' "$d"
}
has() { ls -d "$ROOT"/plugins/*/skills/"$1" >/dev/null 2>&1; }

vendor() {  # vendor <skill> <lib-file>...   (copies from tools/lib into the skill's lib/)
  local skill="$1" dir; shift
  dir=$(sd "$skill")
  mkdir -p "$dir/lib"
  for f in "$@"; do cp "lib/$f" "$dir/lib/$f"; done
}
root_copy() {  # root_copy <file> <skill>...   (copies a tools/ file into each skill's root)
  local f="$1"; shift
  for s in "$@"; do cp "$f" "$(sd "$s")/$f"; done
}

# --- promptfoo runtime: response classification, transcript extraction, metrics ---
vendor app-benchmark       status_policy.js transform_response.js summarize.py extract_transcript.js
vendor app-redteam         status_policy.js transform_response.js extract_transcript.js redteam_summary.py

# --- guardrail-benchmark: promptfoo runtime (direct mode) + shim classifier and the
#     shared Inspect suite/runner/report (in-line mode) ---
vendor guardrail-benchmark status_policy.js summarize.py extract_transcript.js \
                           status_policy.py evalkit.py inspect_suite.py inspect_runner.py inspect_report.py

# --- model-benchmark: the shared Inspect suite/runner/report (the arm axis is the model) ---
vendor model-benchmark     evalkit.py inspect_suite.py inspect_runner.py inspect_report.py

# --- security-tool-benchmark: findings/samples contract, paired stats, SARIF normaliser,
#     manifest editor, contamination probe, probe helpers, optional sdlc locator ---
vendor security-tool-benchmark evalstats.py sarif_to_findings.py cwe_map.py manifest.py \
                               canary_probe.py find_sdlc.sh probelib.py evalkit.py

# --- skills built on the shared helpers only; registered as they land ---
EVALKIT_SKILLS="decision-model-benchmark image-generation-benchmark agent-feature-review review-scope review-threat-model review-criteria coding-guidance-benchmark agent-misuse-benchmark"
for s in $EVALKIT_SKILLS; do has "$s" && vendor "$s" evalkit.py; done

# --- voice-model-benchmark: shared helpers + the manifest editor ---
has voice-model-benchmark && vendor voice-model-benchmark evalkit.py manifest.py
has image-generation-benchmark && vendor image-generation-benchmark manifest.py

# --- modality benchmarks: the two-lane scorecard ---
for s in decision-model-benchmark voice-model-benchmark vision-model-benchmark image-generation-benchmark; do
  has "$s" && vendor "$s" scorecard.py
done

# --- benchmark catalogue: the threat-model skill plans tests from its own copy ---
has review-threat-model && cp "$ROOT/catalog/benchmarks.json" "$(sd review-threat-model)/catalog.json"

# --- promptfoo setup script: each promptfoo skill ships its OWN copy ---
root_copy install_dependencies.sh app-benchmark app-redteam guardrail-benchmark

# --- experiment scaffolder: every measurement skill ships its own copy ---
SCAFFOLD_SKILLS="app-benchmark app-redteam guardrail-benchmark model-benchmark security-tool-benchmark"
for s in decision-model-benchmark coding-guidance-benchmark voice-model-benchmark agent-misuse-benchmark image-generation-benchmark; do has "$s" && SCAFFOLD_SKILLS="$SCAFFOLD_SKILLS $s"; done
root_copy new_experiment.sh $SCAFFOLD_SKILLS

# --- mock target / judge / guardrail server for keyless smoke tests ---
for s in app-benchmark app-redteam guardrail-benchmark; do
  mkdir -p "$(sd "$s")/tests"; cp mock_server.py "$(sd "$s")/tests/mock_server.py"
done

# --- ephemeral GitHub repo + CodeQL driver (optional path of the code kind) ---
root_copy ephemeral_repo.sh security-tool-benchmark

# --- prebuilt, license-clean corpus (full tier; skills sample at run time) ---
$PY build_corpus.py --tier full --out "$(sd app-benchmark)/corpus" >/dev/null
$PY build_corpus.py --tier full --assert guardrail --out "$(sd guardrail-benchmark)/corpus" >/dev/null

# --- voice-model-benchmark speaks a subset of the app-benchmark corpus (deterministic) ---
has voice-model-benchmark && $PY "$(sd voice-model-benchmark)/corpus/build_subset.py" \
    --source "$(sd app-benchmark)/corpus" >/dev/null

# --- prebuilt red-team OBJECTIVE pack (drives promptfoo's local `intent` plugin) ---
$PY build_redteam_objectives.py >/dev/null
mkdir -p "$(sd app-redteam)/objectives"
cp corpus/redteam_objectives.json corpus/redteam_objectives.smoke.json \
   corpus/redteam_objectives.manifest.json "$(sd app-redteam)/objectives/"

echo "synced vendored libs, scaffolder, corpus and red-team objectives into the skills"
