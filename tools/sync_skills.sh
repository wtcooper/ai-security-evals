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
TOOL_SKILLS=$(cd "$ROOT" && ls -d plugins/*/skills/tool-* 2>/dev/null | xargs -n1 basename)

vendor() {  # vendor <skill> <lib-file>...
  local skill="$1" dir; shift
  dir=$(sd "$skill")
  mkdir -p "$dir/lib"
  for f in "$@"; do cp "lib/$f" "$dir/lib/$f"; done
}

# --- runtime libs per skill (only what each one uses) ---
vendor app-benchmark        status_policy.js transform_response.js summarize.py extract_transcript.js
vendor app-redteam     status_policy.js transform_response.js extract_transcript.js
vendor control-isolate status_policy.js summarize.py extract_transcript.js
vendor control-bench   status_policy.py

# --- shared eval spine (design doc §2.3): findings/samples contract, paired stats,
#     SARIF normaliser, manifest editor, contamination probe, sdlc locator, probe helpers ---
SPINE="evalstats.py sarif_to_findings.py cwe_map.py manifest.py canary_probe.py find_sdlc.sh probelib.py"
SPINE_SKILLS="control-codegen"
for s in $SPINE_SKILLS; do vendor "$s" $SPINE; done
for s in $TOOL_SKILLS; do vendor "$s" $SPINE; done

# --- promptfoo setup script: each promptfoo skill ships its OWN copy (no cross-skill
#     reference) so a skill folder is copy-paste self-contained ---
for s in app-benchmark app-redteam control-isolate; do
  cp install_dependencies.sh "$(sd "$s")/install_dependencies.sh"
done

# --- experiment scaffolder: every skill ships its own copy (self-contained) ---
for s in app-benchmark app-redteam control-isolate control-bench model-benchmark $SPINE_SKILLS \
         $TOOL_SKILLS; do
  cp new_experiment.sh "$(sd "$s")/new_experiment.sh"
done

# --- ephemeral GitHub repo + CodeQL driver: skills that push branches for scoring ---
REPO_SKILLS="control-codegen tool-codescan"
for s in $REPO_SKILLS; do
  cp ephemeral_repo.sh "$(sd "$s")/ephemeral_repo.sh"
done

# --- prebuilt, license-clean corpus (full tier; skills sample at run time) ---
$PY build_corpus.py --tier full --out "$(sd app-benchmark)/corpus" >/dev/null
$PY build_corpus.py --tier full --assert guardrail --out "$(sd control-isolate)/corpus" >/dev/null

# --- prebuilt red-team OBJECTIVE pack (drives promptfoo's local `intent` plugin) ---
$PY build_redteam_objectives.py >/dev/null
mkdir -p "$(sd app-redteam)/objectives"
cp corpus/redteam_objectives.json corpus/redteam_objectives.smoke.json \
   corpus/redteam_objectives.manifest.json "$(sd app-redteam)/objectives/"

echo "synced libs + corpus + redteam objectives into app-benchmark, app-redteam, control-isolate, control-bench, control-codegen, tool-*"
